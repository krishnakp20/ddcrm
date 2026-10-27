"""Vicidial servers push their logs here. Also: the servers' setup, the CDR (call records with recordings) and the APR."""
import csv
import hashlib
import io
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..config import settings
from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import AgentLog, AprDaily, CdrCall, CdrRecording, Client, DialerServer, Interaction, PauseCode, User
from ..services import agent as ag
from ..services import dialer as dl

router = APIRouter(prefix="/api", tags=["dialer"])
TZ = ZoneInfo(settings.TIMEZONE)
_hits: dict[int, deque] = defaultdict(deque)
ABANDON = ("DROP", "XDROP", "TIMEOT", "AFTHRS", "NANQUE", "HXFER")


def _hash(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()


def _need(user: User, perm: str) -> None:
    if perm not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")


# =====================================================================
# the servers push here
# =====================================================================

def _client_ip(request: Request) -> str:
    if settings.TRUST_FORWARDED_FOR and request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else ""


def _server(request: Request, db: Session) -> DialerServer:
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    s = db.scalar(select(DialerServer).where(DialerServer.key_hash == _hash(key))) if key else None
    if not s or not s.is_active:
        raise HTTPException(401, "This key is not valid.")
    if _client_ip(request) not in (s.allowed_ips or []):
        raise HTTPException(403, "This address is not allowed to send data for this server.")
    q, now = _hits[s.id], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= 240:
        raise HTTPException(429, "Too many requests. Send fewer, larger batches.")
    q.append(now)
    return s


@router.post("/dialer/ingest/{table}")
async def ingest(table: str, request: Request, db: Session = Depends(get_db)):
    if table not in dl.TABLES:
        raise HTTPException(404, "Unknown table")
    server = _server(request, db)
    if int(request.headers.get("content-length") or 0) > 6 * 1024 * 1024:
        raise HTTPException(413, "The batch is too large. Send at most 1000 rows at a time.")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(422, "Send JSON: {\"rows\": [ ... ]}")
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise HTTPException(422, "Send JSON: {\"rows\": [ ... ]}")
    if len(rows) > dl.MAX_ROWS:
        raise HTTPException(413, f"Send at most {dl.MAX_ROWS} rows at a time.")
    result = dl.save(db, table, server, rows)
    now = datetime.now(timezone.utc)
    seen = dict(server.last_seen or {})
    seen[table] = {"at": now.isoformat(), "rows": result["added"]}
    server.last_seen, server.last_seen_at = seen, now
    db.commit()
    return {"ok": True, **result}


@router.get("/dialer/ingest/state/{table}")
def ingest_state(table: str, request: Request, db: Session = Depends(get_db)):
    """Where the CRM stopped, so the script on the dialer carries on from there (it keeps no state of its own)."""
    if table not in dl.TABLES:
        raise HTTPException(404, "Unknown table")
    s = _server(request, db)
    if table == "closer_log":
        last = db.scalar(select(func.max(cast(CdrCall.source_key, BigInteger))).where(CdrCall.server_id == s.id, CdrCall.source == "closer"))
    elif table == "log":
        t = db.scalar(select(func.max(CdrCall.start_at)).where(CdrCall.server_id == s.id, CdrCall.source == "log"))
        last = int(t.timestamp()) if t else None
    elif table == "agent_log":
        last = db.scalar(select(func.max(AgentLog.log_id)).where(AgentLog.server_id == s.id))
    else:
        last = db.scalar(select(func.max(CdrRecording.recording_id)).where(CdrRecording.server_id == s.id))
    return {"table": table, "last": last, "server_time": int(time.time()), "max_rows": dl.MAX_ROWS}


# =====================================================================
# setting up the servers (DialDesk staff)
# =====================================================================

def _out(s: DialerServer, db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    age = (now - s.last_seen_at).total_seconds() if s.last_seen_at else None
    client = db.get(Client, s.default_client_id) if s.default_client_id else None
    return {"id": s.id, "name": s.name, "kind": s.kind, "timezone": s.timezone, "allowed_ips": s.allowed_ips or [], "key_hint": s.key_hint,
            "default_client_id": s.default_client_id, "default_client": client.company_name if client else None, "recording_base_url": s.recording_base_url,
            "is_active": s.is_active, "last_seen_at": s.last_seen_at, "last_seen": s.last_seen or {}, "silent_minutes": round(age / 60) if age is not None else None,
            "status": "off" if not s.is_active else "never" if age is None else "ok" if age < 600 else "late" if age < 3600 else "silent"}


class ServerIn(BaseModel):
    name: str = Field(default="", max_length=80)
    timezone: str = "Asia/Kolkata"
    allowed_ips: list[str] = []
    default_client_id: Optional[int] = None
    recording_base_url: Optional[str] = Field(default=None, max_length=300)
    is_active: bool = True


def _clean(db: Session, body: ServerIn, existing: Optional[DialerServer] = None) -> dict[str, Any]:
    errors: dict[str, str] = {}
    name = " ".join(body.name.split())
    if len(name) < 2:
        errors["name"] = "Give the server a name"
    elif db.scalar(select(DialerServer.id).where(func.lower(DialerServer.name) == name.lower(), DialerServer.id != (existing.id if existing else 0))):
        errors["name"] = "A server with this name already exists"
    try:
        ZoneInfo(body.timezone)
    except Exception:
        errors["timezone"] = "Unknown time zone, for example Asia/Kolkata"
    ips = []
    for raw in body.allowed_ips:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ips.append(str(ipaddress.ip_address(raw)))
        except ValueError:
            errors["allowed_ips"] = f"{raw!r} is not an IP address"
    base = (body.recording_base_url or "").strip().rstrip("/") or None
    if base and urlparse(base).scheme not in ("http", "https"):
        errors["recording_base_url"] = "Must start with http:// or https://"
    if body.default_client_id and not db.get(Client, body.default_client_id):
        errors["default_client_id"] = "Choose a client"
    if errors:
        raise HTTPException(422, detail={"message": "Please fix the highlighted fields", "fields": errors})
    return {"name": name, "timezone": body.timezone, "allowed_ips": sorted(set(ips)), "default_client_id": body.default_client_id or None,
            "recording_base_url": base, "is_active": body.is_active}


@router.get("/dialer/servers")
def list_servers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "dialer.manage")
    return [_out(s, db) for s in db.scalars(select(DialerServer).order_by(DialerServer.name))]


@router.post("/dialer/servers", status_code=201)
def create_server(body: ServerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "dialer.manage")
    key = secrets.token_urlsafe(32)
    s = DialerServer(key_hash=_hash(key), key_hint=key[:6], **_clean(db, body))
    db.add(s)
    audit(db, user, "dialer_server_created", detail={"name": s.name})
    db.commit()
    return {**_out(s, db), "key": key}


@router.put("/dialer/servers/{server_id}")
def update_server(server_id: int, body: ServerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "dialer.manage")
    s = db.get(DialerServer, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    for k, v in _clean(db, body, s).items():
        setattr(s, k, v)
    audit(db, user, "dialer_server_changed", detail={"server": s.id})
    db.commit()
    return _out(s, db)


@router.post("/dialer/servers/{server_id}/key")
def new_key(server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A new key replaces the old one at once; shown only this once."""
    _need(user, "dialer.manage")
    s = db.get(DialerServer, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    key = secrets.token_urlsafe(32)
    s.key_hash, s.key_hint = _hash(key), key[:6]
    audit(db, user, "dialer_key_created", detail={"server": s.id})
    db.commit()
    return {**_out(s, db), "key": key}


@router.get("/dialer/servers/{server_id}/stats")
def server_stats(server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "dialer.manage")
    s = db.get(DialerServer, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    since = datetime.now(timezone.utc) - timedelta(days=7)
    per_day = db.execute(select(func.date(func.timezone(s.timezone, CdrCall.start_at)).label("d"), CdrCall.direction, func.count())
                         .where(CdrCall.server_id == s.id, CdrCall.start_at >= since).group_by("d", CdrCall.direction).order_by("d")).all()
    unmapped = db.execute(select(CdrCall.campaign_code, CdrCall.direction, func.count()).where(CdrCall.server_id == s.id, CdrCall.client_id.is_(None))
                          .group_by(CdrCall.campaign_code, CdrCall.direction).order_by(func.count().desc()).limit(20)).all()
    unmapped_agent = db.execute(select(AgentLog.campaign_code, func.count()).where(AgentLog.server_id == s.id, AgentLog.client_id.is_(None))
                                .group_by(AgentLog.campaign_code).order_by(func.count().desc()).limit(20)).all()
    return {"last_7_days": [{"day": str(d), "direction": dr, "calls": n} for d, dr, n in per_day],
            "unmapped_calls": [{"code": c, "direction": dr, "calls": n} for c, dr, n in unmapped],
            "unmapped_agent_rows": [{"code": c, "rows": n} for c, n in unmapped_agent]}


@router.post("/dialer/servers/{server_id}/remap")
def remap_server(server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """After adding a campaign or ingroup to a client's Dialer IDs: gives the waiting rows their client."""
    _need(user, "dialer.manage")
    s = db.get(DialerServer, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    out = dl.remap(db, s)
    db.commit()
    return out


@router.post("/dialer/servers/{server_id}/rebuild-apr")
def rebuild(server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recounts every agent day from the raw log (after changing the pause codes)."""
    _need(user, "dialer.manage")
    s = db.get(DialerServer, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    n = dl.rebuild_apr(db, s, None, None)
    db.commit()
    return {"agent_days": n}


class PauseIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    category: str
    server_id: Optional[int] = None


@router.get("/dialer/pause-codes")
def pause_codes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every pause code seen in the agent logs, what it is counted as, and how much time it holds."""
    _need(user, "dialer.manage")
    seen = db.execute(select(AgentLog.sub_status, func.sum(AgentLog.pause_sec), func.count()).where(AgentLog.sub_status.is_not(None), AgentLog.pause_sec > 0)
                      .group_by(AgentLog.sub_status).order_by(func.sum(AgentLog.pause_sec).desc()).limit(200)).all()
    mapped = {p.code.upper(): p for p in db.scalars(select(PauseCode).where(PauseCode.server_id.is_(None)))}
    return {"categories": list(dl.CATEGORIES), "codes": [{"code": c, "seconds": int(sec or 0), "rows": n, "category": mapped[c.upper()].category if c.upper() in mapped else dl.default_category(c),
                                                          "set": c.upper() in mapped} for c, sec, n in seen]}


@router.put("/dialer/pause-codes")
def set_pause_code(body: PauseIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "dialer.manage")
    if body.category not in dl.CATEGORIES:
        raise HTTPException(422, detail={"message": "Choose a category", "fields": {"category": "Choose a category"}})
    row = db.scalar(select(PauseCode).where(PauseCode.code == body.code.strip().upper(), PauseCode.server_id.is_(body.server_id) if body.server_id is None else PauseCode.server_id == body.server_id))
    if row:
        row.category = body.category
    else:
        db.add(PauseCode(code=body.code.strip().upper(), category=body.category, server_id=body.server_id))
    db.commit()
    return {"ok": True}


# =====================================================================
# CDR: who may see which calls
# =====================================================================

def _scope(db: Session, user: User) -> list:
    _need(user, "cdr.view")
    if user.user_type == "staff":
        return []
    if user.user_type == "client" and user.client_id:
        return [CdrCall.client_id == user.client_id]
    if user.user_type == "agent":
        ids = [c.id for c in ag.allowed_clients(db, user)]
        if not user.dialer_agent_id or not ids:
            return [CdrCall.id < 0]  # an agent without a dialer login has no calls to show
        return [CdrCall.agent_user == user.dialer_agent_id, CdrCall.client_id.in_(ids)]
    return [CdrCall.id < 0]


def _where(db: Session, user: User, date_from: Optional[str], date_to: Optional[str], client_id: Optional[int], direction: Optional[str],
           status: Optional[str], agent: Optional[str], q: Optional[str], mapped: Optional[str], server_id: Optional[int], recording: Optional[str]) -> list:
    today = datetime.now(TZ).date()
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
        d_from = date.fromisoformat(date_from) if date_from else d_to - timedelta(days=6)
    except ValueError:
        raise HTTPException(422, "Dates must look like 2026-10-31.")
    if d_from > d_to or (d_to - d_from).days > 366:
        raise HTTPException(422, "Choose a range of at most one year, start before end.")
    w = _scope(db, user) + [CdrCall.start_at >= datetime.combine(d_from, datetime.min.time(), TZ), CdrCall.start_at < datetime.combine(d_to + timedelta(days=1), datetime.min.time(), TZ)]
    if client_id and user.user_type == "staff":
        w.append(CdrCall.client_id == client_id)
    if direction in ("in", "out"):
        w.append(CdrCall.direction == direction)
    if status:
        w.append(CdrCall.status == status.upper())
    if agent:
        w.append(CdrCall.agent_user.ilike(f"%{agent.strip()}%"))
    if q and q.strip():
        w.append(CdrCall.phone.like(f"%{''.join(c for c in q if c.isdigit())}%"))
    if mapped == "no" and user.user_type == "staff":
        w.append(CdrCall.client_id.is_(None))
    if server_id and user.user_type == "staff":
        w.append(CdrCall.server_id == server_id)
    if recording == "yes":
        w.append(CdrCall.recording_id.is_not(None))
    return w


CDR_COLS = [("when", "Start"), ("direction", "Direction"), ("client", "Client"), ("campaign", "Campaign / ingroup"), ("phone", "Phone"), ("agent", "Agent"), ("status", "Status"),
            ("talk", "Length (s)"), ("queue", "Queue (s)"), ("term", "Ended by"), ("server", "Dialer server"), ("recording", "Recording")]


def _rows(db: Session, calls: list[CdrCall]) -> list[dict[str, Any]]:
    cl = {i: n for i, n in db.execute(select(Client.id, Client.company_name).where(Client.id.in_({c.client_id for c in calls if c.client_id} or {0})))}
    sv = {i: n for i, n in db.execute(select(DialerServer.id, DialerServer.name))}
    users = {u.dialer_agent_id: u.name for u in db.scalars(select(User).where(User.dialer_agent_id.in_({c.agent_user for c in calls if c.agent_user} or {""})))}
    return [{"id": c.id, "when": c.start_at.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S") if c.start_at else "", "direction": "Inbound" if c.direction == "in" else "Outbound",
             "client": cl.get(c.client_id, "(not mapped)" if not c.client_id else ""), "campaign": c.campaign_code or "", "phone": c.phone or "",
             "agent": c.agent_user or "", "agent_name": users.get(c.agent_user, ""), "status": c.status or "", "talk": c.length_sec, "queue": c.queue_sec,
             "term": c.term_reason or "", "server": sv.get(c.server_id, ""), "recording": "yes" if c.recording_id else ""} for c in calls]


@router.get("/cdr")
def cdr_list(date_from: Optional[str] = None, date_to: Optional[str] = None, client_id: Optional[int] = None, direction: Optional[str] = None,
             status: Optional[str] = None, agent: Optional[str] = None, q: Optional[str] = None, mapped: Optional[str] = None, server_id: Optional[int] = None,
             recording: Optional[str] = None, page: int = 1, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _where(db, user, date_from, date_to, client_id, direction, status, agent, q, mapped, server_id, recording)
    page = max(1, page)
    total = db.scalar(select(func.count()).select_from(CdrCall).where(*w))
    calls = list(db.scalars(select(CdrCall).where(*w).order_by(CdrCall.start_at.desc()).offset((page - 1) * 50).limit(50)))
    summary = db.execute(select(func.count(), func.count().filter(CdrCall.recording_id.is_not(None)), func.count().filter(CdrCall.status.in_(ABANDON)),
                                func.avg(CdrCall.length_sec).filter(CdrCall.length_sec > 0), func.avg(CdrCall.queue_sec).filter(CdrCall.direction == "in"),
                                func.count().filter(CdrCall.direction == "in"), func.count().filter(CdrCall.direction == "out")).where(*w)).one()
    return {"columns": [{"key": k, "label": l} for k, l in CDR_COLS], "rows": _rows(db, calls), "total": total, "page": page, "page_size": 50,
            "summary": {"calls": summary[0], "with_recording": summary[1], "abandoned": summary[2], "avg_talk": round(summary[3] or 0), "avg_queue": round(summary[4] or 0),
                        "inbound": summary[5], "outbound": summary[6]}}


@router.get("/cdr/export")
def cdr_export(date_from: Optional[str] = None, date_to: Optional[str] = None, client_id: Optional[int] = None, direction: Optional[str] = None,
               status: Optional[str] = None, agent: Optional[str] = None, q: Optional[str] = None, mapped: Optional[str] = None, server_id: Optional[int] = None,
               recording: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _where(db, user, date_from, date_to, client_id, direction, status, agent, q, mapped, server_id, recording)

    def stream() -> Iterable[str]:
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow([l for _, l in CDR_COLS])
        yield "﻿" + buf.getvalue()
        for off in range(0, 200000, 2000):
            chunk = list(db.scalars(select(CdrCall).where(*w).order_by(CdrCall.start_at.desc()).offset(off).limit(2000)))
            for r in _rows(db, chunk):
                buf.seek(0), buf.truncate()
                wr.writerow([("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for v in (r[k] for k, _ in CDR_COLS)])
                yield buf.getvalue()
            if len(chunk) < 2000:
                break
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="cdr.csv"'})


@router.get("/cdr/{cdr_id:int}")
def cdr_detail(cdr_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _scope(db, user)
    c = db.scalar(select(CdrCall).where(CdrCall.id == cdr_id, *w))
    if not c:
        raise HTTPException(404, "Call not found")
    row = _rows(db, [c])[0]
    crm = db.scalar(select(Interaction).where(Interaction.client_id == c.client_id, Interaction.call_id == c.uniqueid)) if c.uniqueid and c.client_id else None
    rec = db.get(CdrRecording, c.recording_id) if c.recording_id else None
    return {**row, "uniqueid": c.uniqueid, "lead_id": c.lead_id, "user_group": c.user_group, "end_at": c.end_at, "recording_seconds": rec.length_sec if rec else None,
            "crm_call": {"id": crm.id, "scenario": crm.scenario_names, "outcome": crm.outcome, "agent_id": crm.agent_id} if crm else None}


# ---------- recordings: played through the CRM, never straight from the dialer ----------

@router.post("/cdr/{cdr_id:int}/recording-link")
def recording_link(cdr_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.scalar(select(CdrCall).where(CdrCall.id == cdr_id, *_scope(db, user)))
    if not c or not c.recording_id:
        raise HTTPException(404, "There is no recording for this call")
    token = jwt.encode({"purpose": "rec", "cdr": c.id, "rec": c.recording_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}, settings.SECRET_KEY, algorithm="HS256")
    audit(db, user, "recording_opened", client_id=c.client_id, detail={"cdr": c.id})
    db.commit()
    return {"url": f"/api/cdr/recording/{token}", "expires_in": 600}


def _recording_target(server: DialerServer, rec: CdrRecording) -> str:
    if not server.recording_base_url:
        raise HTTPException(409, "The address of the recordings is not set for this dialer server yet.")
    loc = rec.location or ""
    path = urlparse(loc).path if loc.lower().startswith("http") else loc
    if not path and rec.filename:
        path = f"/RECORDINGS/MP3/{rec.filename}"
    if ".." in path or not path:
        raise HTTPException(404, "The recording path is not usable")
    return server.recording_base_url.rstrip("/") + "/" + path.lstrip("/")


@router.get("/cdr/recording/{token}")
def recording_play(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        p = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        assert p.get("purpose") == "rec"
    except Exception:
        raise HTTPException(401, "This link has expired. Open the recording again.")
    rec = db.get(CdrRecording, p["rec"])
    server = db.get(DialerServer, rec.server_id) if rec else None
    if not rec or not server:
        raise HTTPException(404, "Recording not found")
    url = _recording_target(server, rec)
    headers = {"Range": request.headers["range"]} if request.headers.get("range") else {}
    client = httpx.Client(timeout=httpx.Timeout(15.0, read=60.0), follow_redirects=False)
    try:
        resp = client.send(client.build_request("GET", url, headers=headers), stream=True)
    except httpx.HTTPError:
        client.close()
        raise HTTPException(502, "The recording server could not be reached.")
    if resp.status_code >= 400:
        resp.close(), client.close()
        raise HTTPException(404 if resp.status_code == 404 else 502, "The recording file is not available.")
    out = {k: v for k, v in resp.headers.items() if k.lower() in ("content-length", "content-range", "accept-ranges")}
    ctype = resp.headers.get("content-type", "audio/mpeg")
    return StreamingResponse(resp.iter_bytes(), status_code=resp.status_code, media_type=ctype if ctype.startswith("audio") else "audio/mpeg", headers=out,
                             background=BackgroundTask(lambda: (resp.close(), client.close())))


# =====================================================================
# APR
# =====================================================================

APR_COLS = [("day", "Date"), ("server", "Server"), ("agent", "Agent (dialer id)"), ("agent_name", "Agent name"), ("client", "Client"), ("calls", "Calls"), ("acht", "ACHT (s)"),
            ("talk", "Talk time"), ("wait", "Wait"), ("dispo", "Wrap-up"), ("net_login", "Net login"), ("productive_login", "Productive login"), ("lunch", "Lunch"),
            ("tea", "Tea / short"), ("bio", "Bio"), ("operation", "Operation"), ("quality", "Quality"), ("refresher", "Refresher"), ("training", "Training"),
            ("other", "Other pause"), ("utilization", "Utilization %"), ("first", "First login"), ("last", "Last activity")]
TIME_KEYS = ("talk", "wait", "dispo", "net_login", "productive_login", "lunch", "tea", "bio", "operation", "quality", "refresher", "training", "other")


def _hms(sec: int) -> str:
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _apr_rows(db: Session, user: User, date_from, date_to, client_id, server_id, agent, group) -> tuple[list[dict[str, Any]], date, date]:
    _need(user, "apr.view")
    today = datetime.now(TZ).date()
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
        d_from = date.fromisoformat(date_from) if date_from else d_to - timedelta(days=6)
    except ValueError:
        raise HTTPException(422, "Dates must look like 2026-10-31.")
    if d_from > d_to or (d_to - d_from).days > 366:
        raise HTTPException(422, "Choose a range of at most one year, start before end.")
    stmt = select(AprDaily).where(AprDaily.day >= d_from, AprDaily.day <= d_to)
    if client_id:
        stmt = stmt.where(AprDaily.client_id == client_id)
    if server_id:
        stmt = stmt.where(AprDaily.server_id == server_id)
    if agent:
        stmt = stmt.where(AprDaily.agent_user.ilike(f"%{agent.strip()}%"))
    data = list(db.scalars(stmt.order_by(AprDaily.day.desc(), AprDaily.agent_user).limit(100000)))
    sv = {i: n for i, n in db.execute(select(DialerServer.id, DialerServer.name))}
    cl = {i: n for i, n in db.execute(select(Client.id, Client.company_name))}
    names = {u.dialer_agent_id: u.name for u in db.scalars(select(User).where(User.dialer_agent_id.is_not(None)))}
    merged: dict[tuple, Any] = {}
    for r in data:
        k = (r.agent_user, r.server_id) if group == "agent" else (r.day, r.server_id, r.agent_user, r.client_key)
        m = merged.get(k)
        if not m:
            merged[k] = m = type("R", (), dict(calls=0, talk_sec=0, wait_sec=0, dispo_sec=0, dead_sec=0, pause_sec=0, breaks={}, first_at=r.first_at, last_at=r.last_at,
                                              day=r.day, server_id=r.server_id, agent_user=r.agent_user, client_id=r.client_id, days=set()))()
            m.breaks = {}
        for f in ("calls", "talk_sec", "wait_sec", "dispo_sec", "dead_sec", "pause_sec"):
            setattr(m, f, getattr(m, f) + getattr(r, f))
        for c, v in (r.breaks or {}).items():
            m.breaks[c] = m.breaks.get(c, 0) + v
        m.first_at, m.last_at = min(m.first_at, r.first_at), max(m.last_at, r.last_at)
        m.days.add(r.day)
        if group == "agent" and m.client_id != r.client_id:
            m.client_id = None
    out = []
    for m in merged.values():
        f = dl.apr_figures(m)
        out.append({"day": f"{len(m.days)} day(s)" if group == "agent" else m.day.isoformat(), "server": sv.get(m.server_id, ""), "agent": m.agent_user, "agent_name": names.get(m.agent_user, ""),
                    "client": cl.get(m.client_id, "") if m.client_id else "(not mapped / several)", **f,
                    "first": m.first_at.astimezone(TZ).strftime("%H:%M:%S") if group != "agent" else "", "last": m.last_at.astimezone(TZ).strftime("%H:%M:%S") if group != "agent" else ""})
    return out, d_from, d_to


@router.get("/apr")
def apr(date_from: Optional[str] = None, date_to: Optional[str] = None, client_id: Optional[int] = None, server_id: Optional[int] = None, agent: Optional[str] = None,
        group: str = "day", page: int = 1, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows, d_from, d_to = _apr_rows(db, user, date_from, date_to, client_id, server_id, agent, group)
    page = max(1, page)
    tot = {k: sum(r[k] for r in rows) for k in ("calls", "talk", "net_login", "productive_login", "pause")}
    return {"columns": [{"key": k, "label": l} for k, l in APR_COLS], "rows": rows[(page - 1) * 50: page * 50], "total": len(rows), "page": page, "page_size": 50,
            "from": d_from.isoformat(), "to": d_to.isoformat(), "time_keys": list(TIME_KEYS),
            "summary": {"agents": len({(r["agent"], r["server"]) for r in rows}), "calls": tot["calls"], "talk": tot["talk"], "net_login": tot["net_login"],
                        "utilization": round(100 * tot["talk"] / tot["net_login"], 2) if tot["net_login"] else 0}}


@router.get("/apr/export")
def apr_export(date_from: Optional[str] = None, date_to: Optional[str] = None, client_id: Optional[int] = None, server_id: Optional[int] = None, agent: Optional[str] = None,
               group: str = "day", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows, _a, _b = _apr_rows(db, user, date_from, date_to, client_id, server_id, agent, group)

    def stream() -> Iterable[str]:
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow([l for _, l in APR_COLS])
        yield "﻿" + buf.getvalue()
        for r in rows:
            buf.seek(0), buf.truncate()
            wr.writerow([_hms(r[k]) if k in TIME_KEYS else r[k] for k, _ in APR_COLS])
            yield buf.getvalue()
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="apr.csv"'})
