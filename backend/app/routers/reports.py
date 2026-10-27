"""Reports: calls, tickets, agents and campaigns for a date range, on screen and as CSV."""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, permissions_of
from ..models import Campaign, Client, Customer, Department, FormField, Interaction, Lead, Ticket, User
from .tickets import sla_state

router = APIRouter(prefix="/api/reports", tags=["reports"])
TZ = ZoneInfo(settings.TIMEZONE)
PAGE = 50
CSV_LIMIT = 100000


# ---------- filters ----------

class F:
    def __init__(self, date_from: Optional[str], date_to: Optional[str], client_id: Optional[int], campaign_id: Optional[int],
                 agent_id: Optional[int], mode: Optional[str], status: Optional[str], outcome: Optional[str], priority: Optional[str]):
        today = datetime.now(TZ).date()
        try:
            self.d_to = date.fromisoformat(date_to) if date_to else today
            self.d_from = date.fromisoformat(date_from) if date_from else self.d_to - timedelta(days=6)
        except ValueError:
            raise HTTPException(422, "Dates must look like 2026-10-31.")
        if self.d_from > self.d_to:
            raise HTTPException(422, "The start date is after the end date.")
        if (self.d_to - self.d_from).days > 366:
            raise HTTPException(422, "Choose a range of at most one year.")
        self.client_id, self.campaign_id, self.agent_id = client_id, campaign_id, agent_id
        self.mode, self.status, self.outcome, self.priority = mode, status, outcome, priority

    @property
    def start(self) -> datetime:
        return datetime.combine(self.d_from, datetime.min.time(), TZ).astimezone(timezone.utc)

    @property
    def end(self) -> datetime:
        return datetime.combine(self.d_to + timedelta(days=1), datetime.min.time(), TZ).astimezone(timezone.utc)


def filters(date_from: Optional[str] = None, date_to: Optional[str] = None, client_id: Optional[int] = None, campaign_id: Optional[int] = None,
            agent_id: Optional[int] = None, mode: Optional[str] = None, status: Optional[str] = None, outcome: Optional[str] = None,
            priority: Optional[str] = None) -> F:
    return F(date_from, date_to, client_id, campaign_id, agent_id, mode, status, outcome, priority)


def _scope(user: User) -> Optional[int]:
    if "reports.view" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    if user.user_type == "staff":
        return None
    if user.client_id is None:
        raise HTTPException(403, "You don't have permission for this")
    return user.client_id


def _client_clause(col, user_client: Optional[int], f: F) -> list:
    cid = user_client or f.client_id
    return [col == cid] if cid else []


# ---------- helpers ----------

def _local(dt: Optional[datetime]) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if dt else ""


def _mins(a: Optional[datetime], b: Optional[datetime]) -> str:
    if not a or not b:
        return ""
    return f"{(b - a).total_seconds() / 60:.1f}"


def _lookup(db: Session, model, ids: Iterable[int], attr: str) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {i: n for i, n in db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids)))} if ids else {}


# ---------- calls ----------

CALL_COLS = [("when", "Started"), ("client", "Client"), ("campaign", "Campaign"), ("mode", "Mode"), ("agent", "Agent"), ("customer", "Customer"),
             ("phone", "Phone"), ("cat1", "Category 1"), ("cat2", "Category 2"), ("cat3", "Category 3"), ("cat4", "Category 4"), ("cat5", "Category 5"),
             ("outcome", "Outcome"), ("status", "Status"), ("minutes", "Minutes"), ("notes", "Notes")]


def _call_columns(db: Session, user_client: Optional[int], f: F) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """The call columns, plus one column per question of the client's form when a single client is chosen
    (the old CRM's Field1, Field2 ... with their real names). Returns (columns, {column key: answer key})."""
    cid = user_client or f.client_id
    if not cid:
        return CALL_COLS, {}
    stmt = select(FormField).where(FormField.client_id == cid, FormField.is_active.is_(True))
    if f.campaign_id:
        stmt = stmt.where((FormField.context == "in_call") | ((FormField.context == "out_call") & (FormField.campaign_id == f.campaign_id)))
    else:
        stmt = stmt.where(FormField.context == "in_call")
    cols, amap, seen = list(CALL_COLS), {}, set()
    for ff in db.scalars(stmt.order_by(FormField.context.desc(), FormField.sort_order, FormField.id)):
        if ff.key in seen:
            continue
        seen.add(ff.key)
        cols.append((f"a_{ff.key}", ff.label))
        amap[f"a_{ff.key}"] = ff.key
    return cols, amap


def _call_where(user_client: Optional[int], f: F) -> list:
    w = [Interaction.started_at >= f.start, Interaction.started_at < f.end] + _client_clause(Interaction.client_id, user_client, f)
    if f.campaign_id:
        w.append(Interaction.campaign_id == f.campaign_id)
    if f.agent_id:
        w.append(Interaction.agent_id == f.agent_id)
    if f.mode in ("inbound", "pd", "manual"):
        w.append(Interaction.mode == f.mode)
    if f.status in ("open", "tagged", "skipped"):
        w.append(Interaction.status == f.status)
    if f.outcome:
        w.append(Interaction.outcome == f.outcome)
    return w


def _val(v: Any) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, list) else ("" if v is None else str(v))


def _call_rows(db: Session, rows: list[Interaction], amap: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    cl = _lookup(db, Client, [r.client_id for r in rows], "company_name")
    ca = _lookup(db, Campaign, [r.campaign_id for r in rows], "name")
    ag = _lookup(db, User, [r.agent_id for r in rows], "name")
    cu = _lookup(db, Customer, [r.customer_id for r in rows], "name")
    out = []
    for r in rows:
        sc = list(r.scenario_names or []) + [""] * 5
        row = {"id": r.id, "when": _local(r.started_at), "client": cl.get(r.client_id, ""), "campaign": ca.get(r.campaign_id, ""),
               "mode": {"pd": "Predictive", "manual": "Manual", "inbound": "Inbound"}.get(r.mode, r.mode), "agent": ag.get(r.agent_id, ""),
               "customer": cu.get(r.customer_id, ""), "phone": r.phone, "cat1": sc[0], "cat2": sc[1], "cat3": sc[2], "cat4": sc[3], "cat5": sc[4],
               "outcome": (r.outcome or "").replace("_", " "), "status": r.status if r.status != "open" else "not tagged",
               "minutes": _mins(r.started_at, r.tagged_at), "notes": (r.notes or r.skip_reason or "")}
        for col, key in (amap or {}).items():
            row[col] = _val((r.answers or {}).get(key))
        out.append(row)
    return out


def _call_summary(db: Session, w: list) -> dict[str, Any]:
    by_status = dict(db.execute(select(Interaction.status, func.count()).where(*w).group_by(Interaction.status)).all())
    by_mode = dict(db.execute(select(Interaction.mode, func.count()).where(*w).group_by(Interaction.mode)).all())
    by_out = db.execute(select(Interaction.outcome, func.count()).where(*w, Interaction.status == "tagged").group_by(Interaction.outcome).order_by(func.count().desc())).all()
    secs = func.extract("epoch", Interaction.tagged_at - Interaction.started_at)
    avg = db.scalar(select(func.avg(secs)).where(*w, Interaction.status == "tagged", Interaction.tagged_at.is_not(None), secs <= 4 * 3600))
    total = sum(by_status.values())
    return {"total": total, "tagged": by_status.get("tagged", 0), "skipped": by_status.get("skipped", 0), "open": by_status.get("open", 0),
            "tag_rate": round(100 * by_status.get("tagged", 0) / total) if total else 0, "avg_minutes": round((avg or 0) / 60, 1),
            "inbound": by_mode.get("inbound", 0), "pd": by_mode.get("pd", 0), "manual": by_mode.get("manual", 0),
            "outcomes": [{"outcome": (o or "none").replace("_", " "), "count": n} for o, n in by_out]}


# ---------- tickets ----------

TICKET_COLS = [("number", "Ticket"), ("created", "Created"), ("source", "Source"), ("client", "Client"), ("customer", "Customer"), ("mobile", "Mobile"),
               ("subject", "Subject"), ("scenario", "Scenario"), ("priority", "Priority"), ("status", "Status"), ("assignee", "Assigned to"),
               ("department", "Department"), ("due", "Due"), ("resolved", "Resolved"), ("hours", "Hours to resolve"), ("sla", "SLA")]


def _ticket_where(user_client: Optional[int], f: F) -> list:
    w = [Ticket.created_at >= f.start, Ticket.created_at < f.end] + _client_clause(Ticket.client_id, user_client, f)
    if f.agent_id:
        w.append(Ticket.assigned_user_id == f.agent_id)
    if f.status in ("open", "in_progress", "pending", "resolved", "closed"):
        w.append(Ticket.status == f.status)
    if f.priority in ("low", "medium", "high", "urgent"):
        w.append(Ticket.priority == f.priority)
    if f.mode in ("manual", "call", "website", "whatsapp", "email"):
        w.append(Ticket.source == f.mode)  # the "mode" filter means the channel for tickets
    return w


def _ticket_rows(db: Session, rows: list[Ticket]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cl = _lookup(db, Client, [r.client_id for r in rows], "company_name")
    cu = _lookup(db, Customer, [r.customer_id for r in rows], "name")
    mo = _lookup(db, Customer, [r.customer_id for r in rows], "mobile")
    us = _lookup(db, User, [r.assigned_user_id for r in rows], "name")
    de = _lookup(db, Department, [r.assigned_department_id for r in rows], "name")
    def sla(r: Ticket) -> str:
        st = sla_state(r, now)
        if st == "breached":
            return "Missed" if r.status in ("resolved", "closed") else "Overdue"
        return {"met": "Met", "ok": "Within time", "due_soon": "Due soon"}.get(st, "")
    return [{"number": r.number, "created": _local(r.created_at), "source": r.source, "client": cl.get(r.client_id, ""),
             "customer": cu.get(r.customer_id, "") or r.contact_name or "", "mobile": mo.get(r.customer_id, "") or r.contact_email or "", "subject": r.subject, "scenario": " > ".join(r.scenario_names or []), "priority": r.priority,
             "status": r.status.replace("_", " "), "assignee": us.get(r.assigned_user_id, ""), "department": de.get(r.assigned_department_id, ""),
             "due": _local(r.due_at), "resolved": _local(r.resolved_at), "hours": (f"{(r.resolved_at - r.created_at).total_seconds() / 3600:.1f}" if r.resolved_at else ""),
             "sla": sla(r)} for r in rows]


def _ticket_summary(db: Session, w: list) -> dict[str, Any]:
    by_status = dict(db.execute(select(Ticket.status, func.count()).where(*w).group_by(Ticket.status)).all())
    by_prio = dict(db.execute(select(Ticket.priority, func.count()).where(*w).group_by(Ticket.priority)).all())
    ended = [Ticket.status.in_(("resolved", "closed")), Ticket.due_at.is_not(None)]
    done = db.scalar(select(func.count()).where(*w, *ended)) or 0
    met = db.scalar(select(func.count()).where(*w, *ended, func.coalesce(Ticket.resolved_at, Ticket.closed_at) <= Ticket.due_at)) or 0
    overdue = db.scalar(select(func.count()).where(*w, Ticket.status.in_(("open", "in_progress", "pending")), Ticket.due_at < datetime.now(timezone.utc))) or 0
    hrs = db.scalar(select(func.avg(func.extract("epoch", Ticket.resolved_at - Ticket.created_at))).where(*w, Ticket.resolved_at.is_not(None)))
    total = sum(by_status.values())
    return {"total": total, "open": sum(by_status.get(s, 0) for s in ("open", "in_progress", "pending")), "resolved": by_status.get("resolved", 0) + by_status.get("closed", 0),
            "overdue": overdue, "sla_met_pct": round(100 * met / done) if done else None, "avg_hours": round((hrs or 0) / 3600, 1),
            "by_status": [{"label": k.replace("_", " "), "count": v} for k, v in by_status.items()],
            "by_priority": [{"label": k, "count": by_prio.get(k, 0)} for k in ("urgent", "high", "medium", "low")]}


# ---------- agents ----------

AGENT_COLS = [("agent", "Agent"), ("calls", "Calls"), ("tagged", "Tagged"), ("skipped", "Skipped"), ("converted", "Converted"), ("callbacks", "Call backs"),
              ("avg_minutes", "Avg minutes per call"), ("tickets_created", "Tickets raised"), ("tickets_resolved", "Tickets resolved")]


def _agent_data(db: Session, user_client: Optional[int], f: F) -> list[dict[str, Any]]:
    w = _call_where(user_client, f)
    secs = func.extract("epoch", Interaction.tagged_at - Interaction.started_at)
    rows = db.execute(select(
        Interaction.agent_id, func.count(), func.sum(case((Interaction.status == "tagged", 1), else_=0)),
        func.sum(case((Interaction.status == "skipped", 1), else_=0)), func.sum(case((Interaction.outcome == "converted", 1), else_=0)),
        func.sum(case((Interaction.outcome == "callback", 1), else_=0)),
        func.avg(case(((Interaction.status == "tagged") & (secs <= 4 * 3600), secs), else_=None))).where(*w).group_by(Interaction.agent_id)).all()
    data: dict[int, dict[str, Any]] = {a: {"calls": c, "tagged": t or 0, "skipped": s or 0, "converted": cv or 0, "callbacks": cb or 0,
                                           "avg_minutes": round((av or 0) / 60, 1), "tickets_created": 0, "tickets_resolved": 0}
                                       for a, c, t, s, cv, cb, av in rows}
    tw = [Ticket.created_at >= f.start, Ticket.created_at < f.end] + _client_clause(Ticket.client_id, user_client, f)
    for a, n in db.execute(select(Ticket.created_by_id, func.count()).where(*tw).group_by(Ticket.created_by_id)).all():
        if a:
            data.setdefault(a, {"calls": 0, "tagged": 0, "skipped": 0, "converted": 0, "callbacks": 0, "avg_minutes": 0, "tickets_created": 0, "tickets_resolved": 0})["tickets_created"] = n
    rw = [Ticket.resolved_at >= f.start, Ticket.resolved_at < f.end] + _client_clause(Ticket.client_id, user_client, f)
    for a, n in db.execute(select(Ticket.assigned_user_id, func.count()).where(*rw).group_by(Ticket.assigned_user_id)).all():
        if a:
            data.setdefault(a, {"calls": 0, "tagged": 0, "skipped": 0, "converted": 0, "callbacks": 0, "avg_minutes": 0, "tickets_created": 0, "tickets_resolved": 0})["tickets_resolved"] = n
    names = _lookup(db, User, data.keys(), "name")
    if f.agent_id:
        data = {k: v for k, v in data.items() if k == f.agent_id}
    return sorted(({"agent": names.get(a, "?"), **v} for a, v in data.items()), key=lambda r: (-r["calls"], r["agent"]))


# ---------- campaigns ----------

CAMPAIGN_COLS = [("campaign", "Campaign"), ("client", "Client"), ("status", "Status"), ("leads", "Leads loaded"), ("not_called", "Not called"),
                 ("callbacks", "Call back"), ("done", "Done"), ("dnc", "Do not call"), ("worked", "Leads called"), ("calls", "Calls in range"),
                 ("tagged", "Tagged in range"), ("converted", "Converted in range"), ("conversion", "Converted % of tagged")]


def _campaign_data(db: Session, user_client: Optional[int], f: F) -> list[dict[str, Any]]:
    stmt = select(Campaign).order_by(Campaign.name)
    for c in _client_clause(Campaign.client_id, user_client, f):
        stmt = stmt.where(c)
    if f.campaign_id:
        stmt = stmt.where(Campaign.id == f.campaign_id)
    camps = list(db.scalars(stmt))
    ids = [c.id for c in camps]
    if not ids:
        return []
    leads: dict[int, dict[str, int]] = {}
    for cid, st, n, worked in db.execute(select(Lead.campaign_id, Lead.status, func.count(), func.sum(case((Lead.attempts > 0, 1), else_=0)))
                                         .where(Lead.campaign_id.in_(ids)).group_by(Lead.campaign_id, Lead.status)).all():
        d = leads.setdefault(cid, {"new": 0, "callback": 0, "done": 0, "dnc": 0, "worked": 0})
        d[st] = n
        d["worked"] += worked or 0
    calls = {cid: (c, t or 0, cv or 0) for cid, c, t, cv in db.execute(select(
        Interaction.campaign_id, func.count(), func.sum(case((Interaction.status == "tagged", 1), else_=0)),
        func.sum(case((Interaction.outcome == "converted", 1), else_=0)))
        .where(Interaction.campaign_id.in_(ids), Interaction.started_at >= f.start, Interaction.started_at < f.end).group_by(Interaction.campaign_id)).all()}
    names = _lookup(db, Client, [c.client_id for c in camps], "company_name")
    out = []
    for c in camps:
        l = leads.get(c.id, {"new": 0, "callback": 0, "done": 0, "dnc": 0, "worked": 0})
        n, t, cv = calls.get(c.id, (0, 0, 0))
        out.append({"campaign": c.name, "client": names.get(c.client_id, ""), "status": c.status, "leads": l["new"] + l["callback"] + l["done"] + l["dnc"],
                    "not_called": l["new"], "callbacks": l["callback"], "done": l["done"], "dnc": l["dnc"], "worked": l["worked"], "calls": n,
                    "tagged": t, "converted": cv, "conversion": round(100 * cv / t) if t else 0})
    return out


# ---------- endpoints ----------

REPORTS = {"calls": CALL_COLS, "tickets": TICKET_COLS, "agents": AGENT_COLS, "campaigns": CAMPAIGN_COLS}


@router.get("/calls/{call_id:int}")
def call_detail(call_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One call with every answer on its form, its customer, and the customer's other calls and tickets."""
    uc = _scope(user)
    it = db.get(Interaction, call_id)
    if not it or (uc and it.client_id != uc):
        raise HTTPException(404, "Call not found")
    fstmt = select(FormField).where(FormField.client_id == it.client_id)
    fstmt = fstmt.where(FormField.campaign_id == it.campaign_id) if it.campaign_id else fstmt.where(FormField.context == "in_call")
    labels = {ff.key: ff.label for ff in db.scalars(fstmt)}
    cust = db.get(Customer, it.customer_id) if it.customer_id else None
    camp = db.get(Campaign, it.campaign_id) if it.campaign_id else None
    agent = db.get(User, it.agent_id)
    others, tickets = [], []
    if it.customer_id:
        others = list(db.scalars(select(Interaction).where(Interaction.client_id == it.client_id, Interaction.customer_id == it.customer_id,
                                                          Interaction.id != it.id).order_by(Interaction.id.desc()).limit(10)))
        tickets = list(db.scalars(select(Ticket).where(Ticket.client_id == it.client_id, Ticket.customer_id == it.customer_id).order_by(Ticket.id.desc()).limit(10)))
    return {
        "id": it.id, "call_id": it.call_id, "client": db.get(Client, it.client_id).company_name, "campaign": camp.name if camp else None,
        "mode": it.mode, "status": it.status, "agent": agent.name if agent else None, "phone": it.phone, "started_at": _local(it.started_at),
        "tagged_at": _local(it.tagged_at), "minutes": _mins(it.started_at, it.tagged_at), "scenario": it.scenario_names or [], "outcome": it.outcome,
        "notes": it.notes, "skip_reason": it.skip_reason,
        "customer": {"name": cust.name, "mobile": cust.mobile, "email": cust.email, "city": cust.city, "ext_ref": cust.ext_ref} if cust else None,
        "answers": [{"label": labels.get(k, k), "value": _val(v)} for k, v in (it.answers or {}).items() if _val(v)],
        "other_calls": [{"id": o.id, "when": _local(o.started_at), "scenario": " > ".join(o.scenario_names or []), "mode": o.mode} for o in others],
        "tickets": [{"id": t.id, "number": t.number, "subject": t.subject, "status": t.status} for t in tickets],
    }


@router.get("/{name}")
def report(name: str, page: int = 1, f: F = Depends(filters), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if name not in REPORTS:
        raise HTTPException(404, "Unknown report")
    uc = _scope(user)
    page = max(1, page)
    cols, amap = _call_columns(db, uc, f) if name == "calls" else (REPORTS[name], {})
    base = {"columns": [{"key": k, "label": l} for k, l in cols], "from": f.d_from.isoformat(), "to": f.d_to.isoformat(), "page": page, "page_size": PAGE}
    if name == "calls":
        w = _call_where(uc, f)
        total = db.scalar(select(func.count()).select_from(Interaction).where(*w))
        rows = list(db.scalars(select(Interaction).where(*w).order_by(Interaction.id.desc()).offset((page - 1) * PAGE).limit(PAGE)))
        return {**base, "total": total, "rows": _call_rows(db, rows, amap), "summary": _call_summary(db, w), "form_columns": bool(amap)}
    if name == "tickets":
        w = _ticket_where(uc, f)
        total = db.scalar(select(func.count()).select_from(Ticket).where(*w))
        rows = list(db.scalars(select(Ticket).where(*w).order_by(Ticket.id.desc()).offset((page - 1) * PAGE).limit(PAGE)))
        return {**base, "total": total, "rows": _ticket_rows(db, rows), "summary": _ticket_summary(db, w)}
    data = _agent_data(db, uc, f) if name == "agents" else _campaign_data(db, uc, f)
    return {**base, "total": len(data), "rows": data[(page - 1) * PAGE: page * PAGE], "summary": None}


def _safe(v: Any) -> Any:
    """Stops a cell that starts with = + - @ from being run as a formula when the file is opened in Excel."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@router.get("/{name}/export")
def export(name: str, f: F = Depends(filters), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if name not in REPORTS:
        raise HTTPException(404, "Unknown report")
    uc = _scope(user)
    cols, amap = _call_columns(db, uc, f) if name == "calls" else (REPORTS[name], {})

    def rows() -> Iterable[dict[str, Any]]:
        if name == "calls":
            w = _call_where(uc, f)
            for off in range(0, CSV_LIMIT, 1000):
                chunk = list(db.scalars(select(Interaction).where(*w).order_by(Interaction.id.desc()).offset(off).limit(1000)))
                yield from _call_rows(db, chunk, amap)
                if len(chunk) < 1000:
                    break
        elif name == "tickets":
            w = _ticket_where(uc, f)
            for off in range(0, CSV_LIMIT, 1000):
                chunk = list(db.scalars(select(Ticket).where(*w).order_by(Ticket.id.desc()).offset(off).limit(1000)))
                yield from _ticket_rows(db, chunk)
                if len(chunk) < 1000:
                    break
        else:
            yield from (_agent_data(db, uc, f) if name == "agents" else _campaign_data(db, uc, f))

    def stream():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([l for _, l in cols])
        yield "﻿" + buf.getvalue()
        for r in rows():
            buf.seek(0), buf.truncate()
            w.writerow([_safe(r.get(k, "")) for k, _ in cols])
            yield buf.getvalue()

    fn = f"{name}_{f.d_from}_{f.d_to}.csv"
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fn}"'})
