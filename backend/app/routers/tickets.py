"""Tickets: raised by an agent (offline or from a call), a client user or DialDesk staff. Status, assignment, SLA, comments."""
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import (TICKET_PRIORITIES, TICKET_STATUSES, AgentClient, Client, Customer, Department, FormField, Interaction, SlaRule, Ticket,
                      TicketComment, User)
from ..services import agent as ag
from ..services import alerts
from ..services import forms as fs
from ..services.phone import normalize_phone, valid_phone

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

DEFAULT_SLA_HOURS = {"urgent": 4, "high": 24, "medium": 48, "low": 72}
OPEN_STATUSES = ("open", "in_progress", "pending")
ENDED = ("resolved", "closed")
STATUS_LABEL = {"open": "Open", "in_progress": "In progress", "pending": "Pending", "resolved": "Resolved", "closed": "Closed"}


# ---------- who may see what ----------

def _need(user: User, perm: str) -> None:
    if perm not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")


def scope_ids(db: Session, user: User) -> Optional[set[int]]:
    """Clients whose tickets this person may see. None = all (DialDesk staff)."""
    if user.user_type == "staff":
        return None
    if user.client_id is not None:
        return {user.client_id}
    return {c.id for c in ag.allowed_clients(db, user)}


def _client(db: Session, user: User, client_id: int) -> Client:
    ids = scope_ids(db, user)
    client = db.get(Client, client_id)
    if not client or (ids is not None and client.id not in ids):
        raise HTTPException(404, "Client not found")
    return client


def _ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    _need(user, "tickets.view")
    t = db.get(Ticket, ticket_id)
    ids = scope_ids(db, user)
    if not t or (ids is not None and t.client_id not in ids):
        raise HTTPException(404, "Ticket not found")  # same answer for other companies' tickets
    return t


def _fail(fields: dict[str, str], message: str = "Please fix the highlighted fields") -> None:
    raise HTTPException(422, detail={"message": message, "fields": fields})


# ---------- SLA ----------

def sla_hours(db: Session, client_id: int) -> dict[str, tuple[int, bool]]:
    custom = {r.priority: r.resolve_hours for r in db.scalars(select(SlaRule).where(SlaRule.client_id == client_id))}
    return {p: (custom[p], True) if p in custom else (DEFAULT_SLA_HOURS[p], False) for p in TICKET_PRIORITIES}


def due_for(db: Session, client_id: int, priority: str, start: datetime) -> datetime:
    return start + timedelta(hours=sla_hours(db, client_id)[priority][0])


def sla_state(t: Ticket, now: datetime) -> str:
    if not t.due_at:
        return "none"
    if t.status in ENDED:
        end = t.resolved_at or t.closed_at
        return "met" if end and end <= t.due_at else "breached"
    if now > t.due_at:
        return "breached"
    return "due_soon" if t.due_at - now < timedelta(hours=2) else "ok"


# ---------- output ----------

def _names(db: Session, rows: list[Ticket]) -> dict[str, dict[int, str]]:
    def pick(model, col, ids, attr):
        ids = {i for i in ids if i}
        return {i: n for i, n in db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids or {0})))} if ids else {}
    return {
        "client": pick(Client, "id", [t.client_id for t in rows], "company_name"),
        "user": pick(User, "id", [t.assigned_user_id for t in rows], "name"),
        "dept": pick(Department, "id", [t.assigned_department_id for t in rows], "name"),
        "cust": pick(Customer, "id", [t.customer_id for t in rows], "name"),
        "mobile": pick(Customer, "id", [t.customer_id for t in rows], "mobile"),
    }


def _row(t: Ticket, n: dict[str, dict[int, str]], now: datetime) -> dict[str, Any]:
    return {"id": t.id, "number": t.number, "subject": t.subject, "client_id": t.client_id, "client_name": n["client"].get(t.client_id),
            "customer_name": n["cust"].get(t.customer_id) or t.contact_name or t.contact_email, "mobile": n["mobile"].get(t.customer_id) or t.contact_email,
            "source": t.source, "priority": t.priority,
            "status": t.status, "assigned_user_id": t.assigned_user_id, "assigned_to": n["user"].get(t.assigned_user_id),
            "assigned_department_id": t.assigned_department_id, "department": n["dept"].get(t.assigned_department_id),
            "due_at": t.due_at, "sla": sla_state(t, now), "created_at": t.created_at, "updated_at": t.updated_at}


def _alert(db: Session, event: str, t: Ticket, client: Optional[Client] = None) -> None:
    client = client or db.get(Client, t.client_id)
    alerts.fire(db, event, t.client_id, alerts.ticket_ctx(db, t, client), priority=t.priority, scenario=t.scenario_names,
                answers=t.answers, assignee_id=t.assigned_user_id, ref=t.number)


def _event(db: Session, t: Ticket, user: Optional[User], body: str, kind: str = "event") -> None:
    db.add(TicketComment(ticket_id=t.id, user_id=user.id if user else None, kind=kind, body=body))


# ---------- helpers for the screens ----------

@router.get("/clients")
def clients_for_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Companies a ticket can be raised for."""
    _need(user, "tickets.view")
    ids = scope_ids(db, user)
    stmt = select(Client).where(Client.status == "active").order_by(Client.company_name)
    if ids is not None:
        stmt = stmt.where(Client.id.in_(ids or {0}))
    return [{"id": c.id, "name": c.company_name, "code": c.code} for c in db.scalars(stmt)]


@router.get("/form/{client_id}")
def ticket_form(client_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The client's inbound form, which a ticket fills in."""
    _need(user, "tickets.manage")
    return fs.build_config(db, _client(db, user, client_id), "in_call")


@router.get("/customer")
def find_customer(client_id: int, mobile: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    client = _client(db, user, client_id)
    m = normalize_phone(mobile)
    c = db.scalar(select(Customer).where(Customer.client_id == client.id, Customer.mobile == m)) if valid_phone(m) else None
    return ag.customer_out(c)


@router.get("/assignees")
def assignees(client_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """People and departments a ticket of this client can be given to."""
    _need(user, "tickets.view")
    client = _client(db, user, client_id)
    shared = list(db.scalars(select(AgentClient.user_id).where(AgentClient.client_id == client.id)))
    users = db.scalars(select(User).where(User.is_active.is_(True), or_(
        User.user_type == "staff", User.client_id == client.id, User.id.in_(shared or [0]))).order_by(User.name))
    out = []
    for u in users:
        if "tickets.manage" not in permissions_of(u):
            continue
        out.append({"id": u.id, "name": u.name, "kind": "DialDesk staff" if u.user_type == "staff" else
                    ("Client" if u.user_type == "client" else "Agent")})
    depts = db.scalars(select(Department).where(Department.is_active.is_(True), or_(Department.client_id.is_(None), Department.client_id == client.id))
                       .order_by(Department.name))
    return {"users": out, "departments": [{"id": d.id, "name": d.name, "own": d.client_id is not None} for d in depts]}


# ---------- create ----------

class TicketIn(BaseModel):
    client_id: int
    name: str = Field(default="", max_length=150)
    mobile: str = Field(default="", max_length=40)
    email: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    subject: str = Field(default="", max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    priority: str = "medium"
    path: list[int] = []
    answers: dict = {}
    interaction_id: Optional[int] = None
    assigned_user_id: Optional[int] = None
    assigned_department_id: Optional[int] = None


def _check_assignment(db: Session, client: Client, user_id: Optional[int], dept_id: Optional[int]) -> None:
    errors: dict[str, str] = {}
    if user_id:
        ok = any(u["id"] == user_id for u in assignees_for(db, client)["users"])
        if not ok:
            errors["assigned_user_id"] = "This person cannot be given tickets of this client"
    if dept_id:
        d = db.get(Department, dept_id)
        if not d or not d.is_active or (d.client_id is not None and d.client_id != client.id):
            errors["assigned_department_id"] = "Choose a department of this client or of DialDesk"
    if errors:
        _fail(errors)


def assignees_for(db: Session, client: Client) -> dict[str, Any]:
    shared = list(db.scalars(select(AgentClient.user_id).where(AgentClient.client_id == client.id)))
    users = db.scalars(select(User).where(User.is_active.is_(True), or_(
        User.user_type == "staff", User.client_id == client.id, User.id.in_(shared or [0]))))
    return {"users": [{"id": u.id} for u in users if "tickets.manage" in permissions_of(u)]}


@router.post("", status_code=201)
def create_ticket(body: TicketIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    client = _client(db, user, body.client_id)
    errors: dict[str, str] = {}
    name, mobile = " ".join(body.name.split()), normalize_phone(body.mobile)
    subject = " ".join(body.subject.split())
    if len(name) < 2:
        errors["name"] = "Customer name is required"
    if not valid_phone(mobile):
        errors["mobile"] = "Enter a valid mobile number"
    if len(subject) < 3:
        errors["subject"] = "Write a short subject"
    if body.priority not in TICKET_PRIORITIES:
        errors["priority"] = "Choose a priority"
    email = (body.email or "").strip().lower() or None
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        errors["email"] = "Enter a valid email"
    it = None
    if body.interaction_id:
        it = db.get(Interaction, body.interaction_id)
        if not it or it.client_id != client.id or (user.user_type == "agent" and it.agent_id != user.id):
            errors["interaction_id"] = "This call cannot be linked"
    clean, form_errors, names = fs.validate_answers(db, client.id, "in_call", body.path, body.answers, None)
    errors.update(form_errors)
    if errors:
        _fail(errors)
    _check_assignment(db, client, body.assigned_user_id, body.assigned_department_id)

    cust = db.scalar(select(Customer).where(Customer.client_id == client.id, Customer.mobile == mobile))
    if cust:  # a known number: keep its saved name, only fill what is missing
        cust.email, cust.city = cust.email or email, cust.city or (body.city or "").strip() or None
    else:
        cust = Customer(client_id=client.id, name=name, mobile=mobile, email=email, city=(body.city or "").strip() or None, created_by_id=user.id)
        db.add(cust)
        db.flush()
    cfg = fs.build_config(db, client, "in_call")
    labels = {f["key"]: f["label"] for f in cfg["fields"]}
    now = datetime.now(timezone.utc)
    t = Ticket(client_id=client.id, customer_id=cust.id, interaction_id=it.id if it else None, subject=subject,
               description=(body.description or "").strip() or None, priority=body.priority, status="open",
               scenario_path=body.path, scenario_names=names, answers=clean, answer_labels={k: labels.get(k, k) for k in clean},
               assigned_user_id=body.assigned_user_id, assigned_department_id=body.assigned_department_id, created_by_id=user.id,
               source="call" if it else "manual",
               due_at=due_for(db, client.id, body.priority, now))
    db.add(t)
    db.flush()
    t.number = f"T-{t.id:06d}"
    _event(db, t, user, f"Ticket created by {user.name}")
    audit(db, user, "ticket_created", client_id=client.id, detail={"ticket": t.id})
    _alert(db, "ticket_created", t, client)
    if t.assigned_user_id:
        _alert(db, "ticket_assigned", t, client)
    db.commit()
    return {"id": t.id, "number": t.number}


class CallTicketIn(BaseModel):
    """What the agent adds on the call screen to raise a ticket while tagging the call."""
    subject: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    priority: str = "medium"
    assigned_user_id: Optional[int] = None
    assigned_department_id: Optional[int] = None


def ticket_from_call(db: Session, user: User, it: Interaction, data: CallTicketIn) -> Ticket:
    """A ticket for a call that is being tagged: same customer, scenario and answers, linked to the call. Added to the
    caller's transaction, so a problem here stops the tag from being saved too (nothing is half done)."""
    client = db.get(Client, it.client_id)
    errors: dict[str, str] = {}
    names = list(it.scenario_names or [])
    subject = " ".join((data.subject or "").split()) or (names[-1] if names else "") or "Call follow-up"
    if len(subject) < 3:
        errors["ticket_subject"] = "Write a short subject for the ticket"
    if data.priority not in TICKET_PRIORITIES:
        errors["ticket_priority"] = "Choose a priority"
    if errors:
        _fail(errors)
    _check_assignment(db, client, data.assigned_user_id, data.assigned_department_id)
    fstmt = select(FormField).where(FormField.client_id == it.client_id)
    fstmt = fstmt.where(FormField.campaign_id == it.campaign_id) if it.campaign_id else fstmt.where(FormField.context == "in_call")
    labels = {f.key: f.label for f in db.scalars(fstmt)}
    now = datetime.now(timezone.utc)
    t = Ticket(client_id=it.client_id, customer_id=it.customer_id, interaction_id=it.id, subject=subject[:200],
               description=(data.description or "").strip() or it.notes, priority=data.priority, status="open", scenario_path=list(it.scenario_path or []),
               scenario_names=names, answers=dict(it.answers or {}), answer_labels={k: labels.get(k, k) for k in (it.answers or {})},
               assigned_user_id=data.assigned_user_id, assigned_department_id=data.assigned_department_id, created_by_id=user.id, source="call",
               due_at=due_for(db, it.client_id, data.priority, now))
    db.add(t)
    db.flush()
    t.number = f"T-{t.id:06d}"
    _event(db, t, user, f"Ticket created by {user.name} while tagging call {it.id}")
    audit(db, user, "ticket_created", client_id=it.client_id, detail={"ticket": t.id, "call": it.id})
    _alert(db, "ticket_created", t, client)
    if t.assigned_user_id:
        _alert(db, "ticket_assigned", t, client)
    return t


# ---------- list ----------

def _base(db: Session, user: User, client_id: Optional[int]):
    ids = scope_ids(db, user)
    stmt = select(Ticket)
    if ids is not None:
        stmt = stmt.where(Ticket.client_id.in_(ids or {0}))
    if client_id and (ids is None or client_id in ids):
        stmt = stmt.where(Ticket.client_id == client_id)
    return stmt


@router.get("")
def list_tickets(view: str = "open", status: Optional[str] = None, priority: Optional[str] = None, client_id: Optional[int] = None,
                 q: Optional[str] = None, source: Optional[str] = None, page: int = 1,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.view")
    now = datetime.now(timezone.utc)
    base = _base(db, user, client_id)
    live = Ticket.status.in_(OPEN_STATUSES)
    counts = {
        "open": db.scalar(select(func.count()).select_from(base.where(live).subquery())),
        "mine": db.scalar(select(func.count()).select_from(base.where(live, Ticket.assigned_user_id == user.id).subquery())),
        "unassigned": db.scalar(select(func.count()).select_from(base.where(live, Ticket.assigned_user_id.is_(None)).subquery())),
        "overdue": db.scalar(select(func.count()).select_from(base.where(live, Ticket.due_at < now).subquery())),
        "all": db.scalar(select(func.count()).select_from(base.subquery())),
    }
    stmt = base
    if view == "open":
        stmt = stmt.where(live)
    elif view == "mine":
        stmt = stmt.where(live, Ticket.assigned_user_id == user.id)
    elif view == "unassigned":
        stmt = stmt.where(live, Ticket.assigned_user_id.is_(None))
    elif view == "overdue":
        stmt = stmt.where(live, Ticket.due_at < now)
    if status in TICKET_STATUSES:
        stmt = stmt.where(Ticket.status == status)
    if priority in TICKET_PRIORITIES:
        stmt = stmt.where(Ticket.priority == priority)
    if source in ("manual", "call", "website", "whatsapp", "email"):
        stmt = stmt.where(Ticket.source == source)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ticket.number.ilike(like), Ticket.subject.ilike(like), Ticket.customer_id.in_(
            select(Customer.id).where(or_(Customer.name.ilike(like), Customer.mobile.like(like))))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    size, page = 25, max(1, page)
    rows = list(db.scalars(stmt.order_by(Ticket.due_at.asc().nulls_last(), Ticket.id.desc()).offset((page - 1) * size).limit(size)))
    n = _names(db, rows)
    return {"items": [_row(t, n, now) for t in rows], "total": total, "page": page, "page_size": size, "counts": counts}


# ---------- one ticket ----------

def _detail(db: Session, t: Ticket) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    n = _names(db, [t])
    cust = db.get(Customer, t.customer_id) if t.customer_id else None
    creator = db.get(User, t.created_by_id) if t.created_by_id else None
    people = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(
        {c.user_id for c in db.scalars(select(TicketComment).where(TicketComment.ticket_id == t.id)) if c.user_id} or {0})))}
    comments = db.scalars(select(TicketComment).where(TicketComment.ticket_id == t.id).order_by(TicketComment.id))
    hours = sla_hours(db, t.client_id)
    return {**_row(t, n, now), "description": t.description, "contact_name": t.contact_name, "contact_email": t.contact_email, "scenario": t.scenario_names, "customer": ag.customer_out(cust),
            "answers": [{"label": t.answer_labels.get(k, k), "value": v} for k, v in (t.answers or {}).items()],
            "created_by": creator.name if creator else None, "interaction_id": t.interaction_id,
            "resolved_at": t.resolved_at, "closed_at": t.closed_at, "sla_hours": hours[t.priority][0],
            "comments": [{"id": c.id, "kind": c.kind, "body": c.body, "by": people.get(c.user_id), "created_at": c.created_at} for c in comments]}


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.view")
    now = datetime.now(timezone.utc)
    base = _base(db, user, None)
    live = Ticket.status.in_(OPEN_STATUSES)
    return {"open": db.scalar(select(func.count()).select_from(base.where(live).subquery())),
            "overdue": db.scalar(select(func.count()).select_from(base.where(live, Ticket.due_at < now).subquery())),
            "mine": db.scalar(select(func.count()).select_from(base.where(live, Ticket.assigned_user_id == user.id).subquery()))}


@router.get("/sla")
def get_sla(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.view")
    cid = client_id if user.user_type == "staff" else user.client_id
    if not cid:
        raise HTTPException(404, "Client not found")
    client = _client(db, user, cid)
    return {"client_id": client.id, "client_name": client.company_name,
            "rules": [{"priority": p, "resolve_hours": h, "custom": c} for p, (h, c) in sla_hours(db, client.id).items()]}


class SlaIn(BaseModel):
    client_id: Optional[int] = None
    rules: list[dict[str, Any]]


@router.put("/sla")
def set_sla(body: SlaIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.sla")
    cid = body.client_id if user.user_type == "staff" else user.client_id
    client = _client(db, user, cid or 0)
    errors: dict[str, str] = {}
    wanted: dict[str, int] = {}
    for r in body.rules:
        p, h = r.get("priority"), r.get("resolve_hours")
        if p not in TICKET_PRIORITIES:
            continue
        if not isinstance(h, int) or isinstance(h, bool) or not 1 <= h <= 8760:
            errors[p] = "Enter whole hours between 1 and 8760"
        else:
            wanted[p] = h
    if errors:
        _fail(errors)
    existing = {r.priority: r for r in db.scalars(select(SlaRule).where(SlaRule.client_id == client.id))}
    for p, h in wanted.items():
        if p in existing:
            existing[p].resolve_hours = h
        else:
            db.add(SlaRule(client_id=client.id, priority=p, resolve_hours=h))
    audit(db, user, "sla_changed", client_id=client.id, detail={"rules": wanted})
    db.commit()
    return get_sla(client.id, user, db)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _detail(db, _ticket(db, user, ticket_id))


# ---------- change ----------

class EditIn(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    priority: Optional[str] = None


@router.put("/{ticket_id}")
def edit_ticket(ticket_id: int, body: EditIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    t = _ticket(db, user, ticket_id)
    if t.status == "closed":
        raise HTTPException(409, "A closed ticket cannot be changed. Reopen it first.")
    if body.subject is not None:
        s = " ".join(body.subject.split())
        if len(s) < 3:
            _fail({"subject": "Write a short subject"})
        t.subject = s
    if body.description is not None:
        t.description = body.description.strip() or None
    if body.priority is not None and body.priority != t.priority:
        if body.priority not in TICKET_PRIORITIES:
            _fail({"priority": "Choose a priority"})
        _event(db, t, user, f"Priority changed from {t.priority} to {body.priority}; the due time was recalculated.")
        t.priority = body.priority
        t.due_at = due_for(db, t.client_id, t.priority, t.created_at)
    db.commit()
    return _detail(db, t)


class StatusIn(BaseModel):
    status: str
    comment: Optional[str] = Field(default=None, max_length=2000)


@router.post("/{ticket_id}/status")
def set_status(ticket_id: int, body: StatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    t = _ticket(db, user, ticket_id)
    if body.status not in TICKET_STATUSES:
        _fail({"status": "Choose a status"})
    if body.status == t.status:
        return _detail(db, t)
    note = (body.comment or "").strip()
    if body.status in ENDED and not note and t.status not in ENDED:
        _fail({"comment": "Write what was done before resolving or closing"}, "Add a note")
    now = datetime.now(timezone.utc)
    _event(db, t, user, f"Status changed from {STATUS_LABEL[t.status]} to {STATUS_LABEL[body.status]} by {user.name}")
    if body.status == "resolved":
        t.resolved_at, t.closed_at = now, None
    elif body.status == "closed":
        t.resolved_at, t.closed_at = t.resolved_at or now, now
    else:
        t.resolved_at = t.closed_at = None
    t.status = body.status
    if note:
        _event(db, t, user, note, "comment")
    audit(db, user, "ticket_status", client_id=t.client_id, detail={"ticket": t.id, "status": t.status})
    if t.status in ENDED:
        _alert(db, "ticket_resolved", t)
    db.commit()
    return _detail(db, t)


class AssignIn(BaseModel):
    user_id: Optional[int] = None
    department_id: Optional[int] = None


@router.post("/{ticket_id}/assign")
def assign(ticket_id: int, body: AssignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    t = _ticket(db, user, ticket_id)
    client = db.get(Client, t.client_id)
    if body.user_id == t.assigned_user_id and body.department_id == t.assigned_department_id:
        return _detail(db, t)
    _check_assignment(db, client, body.user_id, body.department_id)
    who = db.get(User, body.user_id).name if body.user_id else None
    dept = db.get(Department, body.department_id).name if body.department_id else None
    t.assigned_user_id, t.assigned_department_id = body.user_id, body.department_id
    text = " and ".join(x for x in (f"{who}" if who else None, f"the {dept} department" if dept else None) if x)
    _event(db, t, user, f"{user.name} assigned the ticket to {text}" if text else f"{user.name} removed the assignment")
    if t.status == "open" and body.user_id:
        t.status = "in_progress"
        _event(db, t, None, "Status changed from Open to In progress (assigned)")
    audit(db, user, "ticket_assigned", client_id=t.client_id, detail={"ticket": t.id, "user": body.user_id, "department": body.department_id})
    if body.user_id:
        _alert(db, "ticket_assigned", t, client)
    db.commit()
    return _detail(db, t)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/{ticket_id}/comments", status_code=201)
def comment(ticket_id: int, body: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "tickets.manage")
    t = _ticket(db, user, ticket_id)
    text = body.body.strip()
    if not text:
        _fail({"body": "Write a comment"})
    _event(db, t, user, text, "comment")
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _detail(db, t)
