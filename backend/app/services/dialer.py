"""Vicidial data pushed to the CRM: reading the rows, finding the client, joining recordings, and building the APR."""
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import AgentLog, AprDaily, CdrCall, CdrRecording, DialerId, DialerServer, PauseCode

TABLES = ("closer_log", "log", "agent_log", "recording_log")
MAX_ROWS = 1000
CATEGORIES = ("lunch", "tea", "bio", "operation", "quality", "refresher", "training", "other")
# used when a pause code has not been mapped yet (the admin can change them per code)
DEFAULT_PATTERNS = (("lunch", ("LUNCH", "LNCH")), ("tea", ("TEA", "SHORT", "BREAK", "BRK", "SNACK")), ("bio", ("BIO", "TOILET", "WASH")),
                    ("operation", ("OPER", "OPS", "MEETING", "TEAM", "FEEDBACK")), ("quality", ("QUAL", "QA", "QC")),
                    ("refresher", ("REFRESH", "REFR")), ("training", ("TRAIN", "TRNG", "COACH")))


def default_category(code: Optional[str]) -> str:
    c = (code or "").upper()
    for cat, words in DEFAULT_PATTERNS:
        if any(w in c for w in words):
            return cat
    return "other"


# ---------- reading rows ----------

def _i(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _s(v: Any, n: int) -> Optional[str]:
    v = ("" if v is None else str(v)).strip()
    return v[:n] or None


def _epoch(v: Any) -> Optional[datetime]:
    n = _i(v, 0)
    return datetime.fromtimestamp(n, tz=timezone.utc) if n > 946684800 else None  # a real date, not 0


def _local(v: Any, tz: str) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).strip().replace("T", " ")).replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        return None


def _phone(v: Any) -> Optional[str]:
    d = re.sub(r"\D", "", str(v or ""))
    return d[-15:] or None


class Mapper:
    """Finds the client of a dialer campaign or ingroup. The same name on two servers can belong to different clients,
    so an id tagged with a server wins over an untagged one; two different clients for one name means "not mapped"."""

    def __init__(self, db: Session, server: DialerServer):
        self.server = server
        self.by_code: dict[str, list[tuple[int, Optional[int], str]]] = {}
        for d in db.scalars(select(DialerId).where(DialerId.kind.in_(("ingroup", "campaign")), DialerId.is_active.is_(True))):
            self.by_code.setdefault(d.value.lower(), []).append((d.client_id, d.dialer_server_id, d.kind))
        self.cache: dict[tuple[str, str], Optional[int]] = {}

    def client(self, code: Optional[str], prefer: str) -> Optional[int]:
        key = ((code or "").lower(), prefer)
        if key in self.cache:
            return self.cache[key]
        cands = [c for c in self.by_code.get(key[0], []) if c[1] in (None, self.server.id)]
        found = None
        for tier in ([c for c in cands if c[1] == self.server.id and c[2] == prefer], [c for c in cands if c[1] == self.server.id],
                     [c for c in cands if c[2] == prefer], cands):
            clients = {c[0] for c in tier}
            if len(clients) == 1:
                found = clients.pop()
                break
            if len(clients) > 1:
                break  # two clients use this name: do not guess
        self.cache[key] = found if found else self.server.default_client_id
        return self.cache[key]


def parse(table: str, rows: list[dict[str, Any]], server: DialerServer, mapper: Mapper) -> tuple[list[dict[str, Any]], int]:
    """Standard Vicidial columns to our rows. Returns (rows, how many were rejected)."""
    out, bad = [], 0
    for r in rows:
        try:
            if table == "closer_log":
                key = _s(r.get("closecallid"), 60)
                if not key:
                    raise ValueError
                out.append({"server_id": server.id, "source": "closer", "source_key": key, "direction": "in", "campaign_code": _s(r.get("campaign_id"), 40),
                            "client_id": mapper.client(r.get("campaign_id"), "ingroup"), "phone": _phone(r.get("phone_number")), "agent_user": _s(r.get("user"), 40),
                            "user_group": _s(r.get("user_group"), 40), "start_at": _epoch(r.get("start_epoch")) or _local(r.get("call_date"), server.timezone),
                            "end_at": _epoch(r.get("end_epoch")), "length_sec": _i(r.get("length_in_sec")), "queue_sec": _i(r.get("queue_seconds")),
                            "status": _s(r.get("status"), 10), "term_reason": _s(r.get("term_reason"), 30), "uniqueid": _s(r.get("uniqueid"), 40),
                            "lead_id": _i(r.get("lead_id")) or None, "list_id": _i(r.get("list_id")) or None})
            elif table == "log":
                uid = _s(r.get("uniqueid"), 40)
                if not uid:
                    raise ValueError
                out.append({"server_id": server.id, "source": "log", "source_key": f"{uid}:{_i(r.get('lead_id'))}", "direction": "out", "campaign_code": _s(r.get("campaign_id"), 40),
                            "client_id": mapper.client(r.get("campaign_id"), "campaign"), "phone": _phone(r.get("phone_number")), "agent_user": _s(r.get("user"), 40),
                            "user_group": _s(r.get("user_group"), 40), "start_at": _epoch(r.get("start_epoch")) or _local(r.get("call_date"), server.timezone),
                            "end_at": _epoch(r.get("end_epoch")), "length_sec": _i(r.get("length_in_sec")), "queue_sec": 0, "status": _s(r.get("status"), 10),
                            "term_reason": _s(r.get("term_reason"), 30), "uniqueid": uid, "lead_id": _i(r.get("lead_id")) or None, "list_id": _i(r.get("list_id")) or None})
            elif table == "recording_log":
                rid = _i(r.get("recording_id"))
                if not rid:
                    raise ValueError
                out.append({"server_id": server.id, "recording_id": rid, "vicidial_id": _s(r.get("vicidial_id"), 40), "lead_id": _i(r.get("lead_id")) or None,
                            "agent_user": _s(r.get("user"), 40), "start_at": _epoch(r.get("start_epoch")) or _local(r.get("start_time"), server.timezone),
                            "length_sec": _i(r.get("length_in_sec")), "filename": _s(r.get("filename"), 200), "location": _s(r.get("location"), 400)})
            else:  # agent_log
                lid, when = _i(r.get("agent_log_id")), _local(r.get("event_time"), server.timezone)
                user = _s(r.get("user"), 40)
                if not lid or not when or not user:
                    raise ValueError
                out.append({"server_id": server.id, "log_id": lid, "agent_user": user, "event_at": when, "campaign_code": _s(r.get("campaign_id"), 40),
                            "user_group": _s(r.get("user_group"), 40), "client_id": mapper.client(r.get("campaign_id"), "campaign"),
                            "pause_sec": max(0, _i(r.get("pause_sec"))), "wait_sec": max(0, _i(r.get("wait_sec"))), "talk_sec": max(0, _i(r.get("talk_sec"))),
                            "dispo_sec": max(0, _i(r.get("dispo_sec"))), "dead_sec": max(0, _i(r.get("dead_sec"))), "status": _s(r.get("status"), 10),
                            "sub_status": _s(r.get("sub_status"), 30), "lead_id": _i(r.get("lead_id")) or None, "uniqueid": _s(r.get("uniqueid"), 40)})
        except (ValueError, TypeError):
            bad += 1
    return out, bad


# ---------- saving ----------

def save(db: Session, table: str, server: DialerServer, rows: list[dict[str, Any]]) -> dict[str, int]:
    mapper = Mapper(db, server)
    parsed, bad = parse(table, rows, server, mapper)
    added = 0
    if parsed:
        if table in ("closer_log", "log"):
            stmt = pg_insert(CdrCall).values(parsed).on_conflict_do_nothing(index_elements=["server_id", "source", "source_key"]).returning(CdrCall.id)
        elif table == "recording_log":
            stmt = pg_insert(CdrRecording).values(parsed).on_conflict_do_nothing(index_elements=["server_id", "recording_id"]).returning(CdrRecording.id)
        else:
            stmt = pg_insert(AgentLog).values(parsed).on_conflict_do_nothing(index_elements=["server_id", "log_id"]).returning(AgentLog.id)
        added = len(db.execute(stmt).all())
        if table in ("closer_log", "log", "recording_log"):
            _link(db, server.id, [p.get("source_key") for p in parsed if p.get("source_key")], [p["recording_id"] for p in parsed if p.get("recording_id")])
        if table == "agent_log":
            _fill_agent_clients(db, server, parsed)
            rebuild_apr(db, server, min(p["event_at"] for p in parsed) - timedelta(days=1), max(p["event_at"] for p in parsed) + timedelta(days=1),
                        users={p["agent_user"] for p in parsed})
    return {"received": len(rows), "added": added, "duplicates": len(parsed) - added, "rejected": bad}


def _link(db: Session, server_id: int, call_keys: list[str], rec_ids: list[int]) -> None:
    """Joins a recording to its call (recording_log.vicidial_id is the call's uniqueid, or the closecallid on older Vicidial)."""
    if call_keys:
        db.execute(text("""update cdr_calls c set recording_id = r.id from cdr_recordings r
            where c.server_id = :s and r.server_id = :s and c.recording_id is null and c.source_key = any(:k)
              and (r.vicidial_id = c.uniqueid or (c.source = 'closer' and r.vicidial_id = c.source_key))"""), {"s": server_id, "k": call_keys})
    if rec_ids:
        db.execute(text("""update cdr_calls c set recording_id = r.id from cdr_recordings r
            where c.server_id = :s and r.server_id = :s and c.recording_id is null and r.recording_id = any(:r)
              and (r.vicidial_id = c.uniqueid or (c.source = 'closer' and r.vicidial_id = c.source_key))"""), {"s": server_id, "r": rec_ids})


def _fill_agent_clients(db: Session, server: DialerServer, parsed: list[dict[str, Any]]) -> None:
    """An agent-log row whose campaign has no client yet takes the client of the call it was for (by uniqueid)."""
    uids = [p["uniqueid"] for p in parsed if not p["client_id"] and p.get("uniqueid")]
    if uids:
        db.execute(text("""update agent_log a set client_id = c.client_id from cdr_calls c
            where a.server_id = :s and c.server_id = :s and a.client_id is null and c.client_id is not null and a.uniqueid = c.uniqueid
              and a.log_id = any(:ids)"""), {"s": server.id, "ids": [p["log_id"] for p in parsed if not p["client_id"]]})


def remap(db: Session, server: DialerServer) -> dict[str, int]:
    """Gives the rows that arrived before their campaign was mapped their client now."""
    mapper = Mapper(db, server)
    done = {"calls": 0, "agent_log": 0}
    for code, direction in db.execute(select(CdrCall.campaign_code, CdrCall.direction).where(CdrCall.server_id == server.id, CdrCall.client_id.is_(None)).distinct()).all():
        cid = mapper.client(code, "ingroup" if direction == "in" else "campaign")
        if cid:
            done["calls"] += db.execute(update(CdrCall).where(CdrCall.server_id == server.id, CdrCall.client_id.is_(None), CdrCall.campaign_code == code,
                                                              CdrCall.direction == direction).values(client_id=cid)).rowcount
    for (code,) in db.execute(select(AgentLog.campaign_code).where(AgentLog.server_id == server.id, AgentLog.client_id.is_(None)).distinct()).all():
        cid = mapper.client(code, "campaign")
        if cid:
            done["agent_log"] += db.execute(update(AgentLog).where(AgentLog.server_id == server.id, AgentLog.client_id.is_(None), AgentLog.campaign_code == code)
                                            .values(client_id=cid)).rowcount
    if done["agent_log"]:
        rebuild_apr(db, server, None, None)
    return done


# ---------- APR ----------

def rebuild_apr(db: Session, server: DialerServer, start: Optional[datetime], end: Optional[datetime], users: Optional[set] = None) -> int:
    """Recounts the agent days in the window from the raw agent log. Safe to run again at any time."""
    day = func.date(func.timezone(server.timezone, AgentLog.event_at))
    sub = func.coalesce(AgentLog.sub_status, "")
    stmt = select(AgentLog.agent_user, day.label("d"), AgentLog.client_id, sub.label("code"),
                  func.count().filter(AgentLog.talk_sec > 0), func.sum(AgentLog.talk_sec), func.sum(AgentLog.wait_sec), func.sum(AgentLog.dispo_sec),
                  func.sum(AgentLog.dead_sec), func.sum(AgentLog.pause_sec), func.min(AgentLog.event_at), func.max(AgentLog.event_at)).where(AgentLog.server_id == server.id)
    if start:
        stmt = stmt.where(AgentLog.event_at >= start, AgentLog.event_at < end)
    if users:
        stmt = stmt.where(AgentLog.agent_user.in_(users))
    stmt = stmt.group_by(AgentLog.agent_user, day, AgentLog.client_id, sub)
    mapping = {pc.code.upper(): pc.category for pc in db.scalars(select(PauseCode).where((PauseCode.server_id == server.id) | PauseCode.server_id.is_(None)).order_by(PauseCode.server_id.is_(None).desc()))}
    days: dict[tuple, dict[str, Any]] = {}
    for user, d, cid, code, calls, talk, wait, dispo, dead, pause, first, last in db.execute(stmt).all():
        a = days.setdefault((user, d, cid or 0), {"client_id": cid, "calls": 0, "talk": 0, "wait": 0, "dispo": 0, "dead": 0, "pause": 0, "breaks": {}, "first": first, "last": last})
        a["calls"] += calls or 0
        a["talk"] += talk or 0
        a["wait"] += wait or 0
        a["dispo"] += dispo or 0
        a["dead"] += dead or 0
        a["pause"] += pause or 0
        if pause:
            cat = mapping.get(code.upper()) or default_category(code)
            a["breaks"][cat] = a["breaks"].get(cat, 0) + pause
        a["first"], a["last"] = min(a["first"], first), max(a["last"], last)
    if start is None:  # a full rebuild starts from nothing
        db.execute(text("delete from apr_daily where server_id = :s"), {"s": server.id})
    for (user, d, ckey), a in days.items():
        vals = {"server_id": server.id, "agent_user": user, "day": d, "client_id": a["client_id"], "client_key": ckey, "calls": a["calls"], "talk_sec": a["talk"],
                "wait_sec": a["wait"], "dispo_sec": a["dispo"], "dead_sec": a["dead"], "pause_sec": a["pause"], "breaks": a["breaks"], "first_at": a["first"], "last_at": a["last"]}
        ins = pg_insert(AprDaily).values(vals)
        db.execute(ins.on_conflict_do_update(index_elements=["server_id", "agent_user", "day", "client_key"], set_={k: ins.excluded[k] for k in vals if k not in ("server_id", "agent_user", "day", "client_key")}))
    return len(days)


def apr_figures(r: Any) -> dict[str, Any]:
    """The numbers of the report from one stored day: login = every second the agent was logged in; utilization = talk / login."""
    net = r.pause_sec + r.wait_sec + r.talk_sec + r.dispo_sec + r.dead_sec
    handle = (r.talk_sec + r.dispo_sec) / r.calls if r.calls else 0
    b = r.breaks or {}
    return {"calls": r.calls, "acht": round(handle), "talk": r.talk_sec, "wait": r.wait_sec, "dispo": r.dispo_sec, "dead": r.dead_sec, "pause": r.pause_sec,
            "net_login": net, "productive_login": max(0, net - r.pause_sec), "utilization": round(100 * r.talk_sec / net, 2) if net else 0.0,
            **{c: b.get(c, 0) for c in CATEGORIES}}
