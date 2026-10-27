"""The agent panel: a call opens from the dialer's link, the agent tags it, and the next one can start."""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of, require_permission
from ..models import Campaign, CampaignBatch, Client, Customer, Interaction, Lead, User
from ..services import agent as ag
from .tickets import CallTicketIn, ticket_from_call
from ..services import alerts
from ..services import forms as fs
from ..services import leads as ls
from ..services.phone import normalize_phone, valid_phone

router = APIRouter(prefix="/api/agent", tags=["agent"])
works = require_permission("calls.work")


class StartIn(BaseModel):
    phonenumber: str = Field(max_length=40)
    vendor_id: str = Field(max_length=80)
    ingroup_id: Optional[str] = Field(default=None, max_length=80)
    campaign_id: Optional[str] = Field(default=None, max_length=80)
    call_id: Optional[str] = Field(default=None, max_length=100)
    agent_id: Optional[str] = Field(default=None, max_length=60)  # the agent's id on the dialer, to catch a wrong login


class CustomerIn(BaseModel):
    name: str = Field(default="", max_length=150)
    mobile: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    ext_ref: Optional[str] = Field(default=None, max_length=100)


class SaveIn(BaseModel):
    path: list[int] = []
    answers: dict = {}
    notes: Optional[str] = Field(default=None, max_length=2000)
    callback_at: Optional[datetime] = None  # when to call this person back (call-back outcomes)
    ticket: Optional[CallTicketIn] = None   # also raise a ticket for this call


class SkipIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


def _mine(db: Session, user: User, call_id: int) -> Interaction:
    it = db.get(Interaction, call_id)
    if not it or it.agent_id != user.id:
        raise HTTPException(404, "Call not found")  # an agent never sees a colleague's call
    return it


def _expire_old(db: Session, user: User) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ag.LOCK_HOURS)
    for it in db.scalars(select(Interaction).where(Interaction.agent_id == user.id, Interaction.status == "open",
                                                   Interaction.started_at < cutoff)):
        it.status, it.skip_reason = "skipped", "Not finished (timed out)"
        ls.after_skip(db, it)


# ---------- opening a call ----------

@router.post("/calls/start")
def start_call(body: StartIn, user: User = Depends(works), db: Session = Depends(get_db)):
    phone = normalize_phone(body.phonenumber)
    if not valid_phone(phone):
        raise ag.err(422, "The phone number in the link is not valid.", "bad_phone")
    r = ag.resolve(db, user, body.vendor_id, body.ingroup_id, body.campaign_id)
    cid = r.campaign.id if r.campaign else None
    call_id = ag.clean_value(body.call_id) or None
    warnings: list[str] = []
    if body.agent_id and user.dialer_agent_id and body.agent_id.strip() != user.dialer_agent_id:
        warnings.append(f"The dialer says this call is for agent {body.agent_id}, but you are signed in as {user.name} "
                        f"(dialer ID {user.dialer_agent_id}). Check you are using your own login.")

    _expire_old(db, user)
    existing = None
    if call_id:
        existing = db.scalar(select(Interaction).where(Interaction.agent_id == user.id, Interaction.call_id == call_id))
    else:  # no call id: a reload or a second click must not create a second call
        since = datetime.now(timezone.utc) - timedelta(minutes=30)
        existing = db.scalar(select(Interaction).where(
            Interaction.agent_id == user.id, Interaction.client_id == r.client.id, Interaction.phone == phone,
            Interaction.mode == r.mode, Interaction.status == "open", Interaction.started_at >= since))
    if existing:
        db.commit()
        return ag.payload(db, user, existing, warnings)

    # wrap-up lock: finish (or skip) the previous call first
    pending = db.scalar(select(Interaction).where(Interaction.agent_id == user.id, Interaction.status == "open").order_by(Interaction.id))
    if pending:
        raise ag.err(409, "You have a call that is not tagged yet. Finish it, or skip it with a reason, before taking the next one.",
                     "locked", open_call_id=pending.id)

    customer = db.scalar(select(Customer).where(Customer.client_id == r.client.id, Customer.mobile == phone))
    it = Interaction(client_id=r.client.id, campaign_id=cid, customer_id=customer.id if customer else None, agent_id=user.id,
                     mode=r.mode, phone=phone, call_id=call_id, dialer_vendor=ag.clean_value(body.vendor_id), dialer_group=r.group)
    db.add(it)
    db.flush()
    ls.attach_dialed(db, user, it)  # a predictive call to a number from the campaign data is linked to that lead
    audit(db, user, "call_opened", client_id=r.client.id, detail={"interaction": it.id, "mode": r.mode, "phone_tail": phone[-4:]})
    db.commit()
    return ag.payload(db, user, it, warnings)


@router.get("/calls/open")
def open_calls(user: User = Depends(works), db: Session = Depends(get_db)):
    _expire_old(db, user)
    db.commit()
    rows = db.scalars(select(Interaction).where(Interaction.agent_id == user.id, Interaction.status == "open").order_by(Interaction.id))
    out = []
    for it in rows:
        client = db.get(Client, it.client_id)
        out.append({**ag.interaction_out(it), "client_name": client.company_name if client else None})
    return out


@router.get("/calls/{call_id}")
def get_call(call_id: int, user: User = Depends(works), db: Session = Depends(get_db)):
    return ag.payload(db, user, _mine(db, user, call_id))


# ---------- the customer on the call ----------

@router.put("/calls/{call_id}/customer")
def set_customer(call_id: int, body: CustomerIn, user: User = Depends(works), db: Session = Depends(get_db)):
    it = _mine(db, user, call_id)
    if it.status != "open":
        raise ag.err(409, "This call is already closed.", "closed")
    errors = {}
    name = " ".join(body.name.split())
    mobile = normalize_phone(body.mobile) if body.mobile else it.phone
    if len(name) < 2:
        errors["name"] = "Name is required"
    if not valid_phone(mobile):
        errors["mobile"] = "Enter a valid mobile number"
    email = (body.email or "").strip().lower() or None
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        errors["email"] = "Enter a valid email"
    if errors:
        raise HTTPException(422, detail={"message": "Please fix the highlighted fields", "fields": errors})

    other = db.scalar(select(Customer).where(Customer.client_id == it.client_id, Customer.mobile == mobile))
    cust = db.get(Customer, it.customer_id) if it.customer_id else None
    if cust and other and other.id != cust.id:
        raise HTTPException(422, detail={"message": "This number already belongs to another customer",
                                         "fields": {"mobile": f"This number already belongs to {other.name}"}})
    city, ext_ref = (body.city or "").strip() or None, (body.ext_ref or "").strip() or None
    if cust:  # a correction to the customer already on this call
        cust.name, cust.mobile, cust.email, cust.city, cust.ext_ref = name, mobile, email, city, ext_ref
    elif other:
        # this number is already a known customer: use that record and only fill in what is missing,
        # so typing a different name on a call can never rewrite someone else's details
        cust = other
        cust.email, cust.city, cust.ext_ref = cust.email or email, cust.city or city, cust.ext_ref or ext_ref
    else:
        cust = Customer(client_id=it.client_id, name=name, mobile=mobile, email=email, city=city, ext_ref=ext_ref,
                        created_by_id=user.id)
        db.add(cust)
    db.flush()
    it.customer_id = cust.id
    db.commit()
    return ag.payload(db, user, it)


# ---------- saving the tag ----------

@router.post("/calls/{call_id}/save")
def save_call(call_id: int, body: SaveIn, user: User = Depends(works), db: Session = Depends(get_db)):
    it = _mine(db, user, call_id)
    if it.status != "open":
        raise ag.err(409, "This call is already closed.", "closed")
    if not it.customer_id:
        raise HTTPException(422, detail={"message": "Save the customer's name before tagging the call",
                                         "fields": {"customer": "Save the customer first"}})
    ctx = "out_call" if it.campaign_id else "in_call"
    clean, errors, names = fs.validate_answers(db, it.client_id, ctx, body.path, body.answers, it.campaign_id)
    if errors:
        raise HTTPException(422, detail={"message": "Please fix the form", "fields": errors})
    nodes, _ = fs.path_nodes(db, it.client_id, ctx, body.path, it.campaign_id)
    it.scenario_path, it.scenario_names = body.path, names
    it.outcome = nodes[-1].outcome if nodes else None
    it.answers, it.notes = clean, (body.notes or "").strip() or None
    it.status, it.tagged_at = "tagged", datetime.now(timezone.utc)
    ls.after_tag(db, it, body.callback_at)
    ticket = None
    if body.ticket:
        if "tickets.manage" not in permissions_of(user):
            raise HTTPException(403, "You don't have permission to create tickets")
        ticket = ticket_from_call(db, user, it, body.ticket)
    cust = db.get(Customer, it.customer_id)
    alerts.fire(db, "call_tagged", it.client_id, {
        **{k: (", ".join(map(str, v)) if isinstance(v, list) else str(v)) for k, v in clean.items()},
        "client": db.get(Client, it.client_id).company_name, "customer": cust.name, "mobile": cust.mobile, "agent": user.name,
        "scenario": " > ".join(names), "category1": (names + [""] * 5)[0], "category2": (names + [""] * 5)[1], "category3": (names + [""] * 5)[2],
        "category4": (names + [""] * 5)[3], "category5": (names + [""] * 5)[4], "number": str(it.id), "calldate": it.started_at.astimezone().strftime("%d %b %Y %H:%M"),
        "outcome": (it.outcome or "none").replace("_", " "), "notes": it.notes or ""},
        outcome=it.outcome, scenario=names, answers=clean, agent_id=user.id, ref=f"call {it.id}", campaign_id=it.campaign_id)
    audit(db, user, "call_tagged", client_id=it.client_id, detail={"interaction": it.id, "outcome": it.outcome})
    db.commit()
    return {"ok": True, "interaction": ag.interaction_out(it), "ticket": {"id": ticket.id, "number": ticket.number} if ticket else None}


@router.post("/calls/{call_id}/skip")
def skip_call(call_id: int, body: SkipIn, user: User = Depends(works), db: Session = Depends(get_db)):
    it = _mine(db, user, call_id)
    if it.status != "open":
        raise ag.err(409, "This call is already closed.", "closed")
    it.status, it.skip_reason = "skipped", body.reason.strip()
    ls.after_skip(db, it)
    audit(db, user, "call_skipped", client_id=it.client_id, detail={"interaction": it.id, "reason": it.skip_reason})
    db.commit()
    return {"ok": True}


# ---------- the panel home ----------

@router.get("/home")
def home(user: User = Depends(works), db: Session = Depends(get_db)):
    _expire_old(db, user)
    db.commit()
    start, end = ag.today_bounds()
    base = select(func.count()).select_from(Interaction).where(Interaction.agent_id == user.id, Interaction.started_at >= start,
                                                                Interaction.started_at < end)
    recent = db.scalars(select(Interaction).where(Interaction.agent_id == user.id).order_by(Interaction.id.desc()).limit(10))
    rows = []
    for it in recent:
        client = db.get(Client, it.client_id)
        cust = db.get(Customer, it.customer_id) if it.customer_id else None
        rows.append({**ag.interaction_out(it), "client_name": client.company_name if client else None,
                     "customer_name": cust.name if cust else None})
    return {
        "today": {"calls": db.scalar(base), "tagged": db.scalar(base.where(Interaction.status == "tagged")),
                  "open": db.scalar(base.where(Interaction.status == "open"))},
        "clients": [{"id": c.id, "name": c.company_name} for c in ag.allowed_clients(db, user)],
        "campaigns": [{"id": c.id, "name": c.name, "client_id": c.client_id, "status": c.status} for c in ag.allowed_campaigns(db, user)],
        "recent": rows,
    }


# ---------- manual dialing queue (outbound campaign data) ----------

class TakeIn(BaseModel):
    campaign_id: int
    lead_id: Optional[int] = None  # a specific lead, or empty for the next one
    batch_id: Optional[int] = None  # take the next one of this allocation only (0 = data from the client's API)


def _my_campaign(db: Session, user: User, campaign_id: int) -> Campaign:
    camp = db.get(Campaign, campaign_id)
    if not camp or not ag.can_work_campaign(db, user, camp):
        raise ag.err(403, "You are not allocated to this campaign. Ask your admin.", "not_allocated")
    return camp


def _allocations(db: Session, user: User, campaign_id: int, now: datetime) -> list[dict[str, Any]]:
    """The uploads that still have numbers this agent may call (their own or the shared queue), with the counts."""
    mine = Lead.assigned_to_id == user.id
    rows = db.execute(
        select(Lead.batch_id, func.count().filter(mine), func.count().filter(Lead.assigned_to_id.is_(None)))
        .where(Lead.campaign_id == campaign_id, Lead.status.in_(("new", "callback")), (Lead.next_call_at.is_(None)) | (Lead.next_call_at <= now),
               mine | Lead.assigned_to_id.is_(None))
        .group_by(Lead.batch_id)).all()
    names = dict(db.execute(select(CampaignBatch.id, func.coalesce(CampaignBatch.name, CampaignBatch.filename)).where(CampaignBatch.campaign_id == campaign_id)).all())
    out = [{"id": b or 0, "name": names.get(b, "Client API / other data") if b else "Client API / other data", "mine": m, "shared": sh} for b, m, sh in rows if m + sh > 0]
    return sorted(out, key=lambda a: (-a["mine"], a["name"]))


@router.get("/queue")
def queue_overview(user: User = Depends(works), db: Session = Depends(get_db)):
    """For each campaign the agent works on: how much data waits for them."""
    now = datetime.now(timezone.utc)
    out = []
    for c in ag.allowed_campaigns(db, user):
        ls.release_stale(db, c.id)
        base = select(func.count()).select_from(Lead).where(Lead.campaign_id == c.id, Lead.status.in_(("new", "callback")))
        due = base.where((Lead.next_call_at.is_(None)) | (Lead.next_call_at <= now))
        out.append({
            "id": c.id, "name": c.name, "status": c.status,
            "mine": db.scalar(due.where(Lead.assigned_to_id == user.id)),
            "shared": db.scalar(due.where(Lead.assigned_to_id.is_(None))),
            "callbacks": db.scalar(due.where(Lead.status == "callback", Lead.assigned_to_id == user.id)),
            "later": db.scalar(base.where(Lead.next_call_at > now, (Lead.assigned_to_id == user.id) | (Lead.assigned_to_id.is_(None)))),
            "allocations": _allocations(db, user, c.id, now),
        })
    db.commit()
    return out


@router.get("/queue/{campaign_id}")
def queue_leads(campaign_id: int, batch_id: Optional[int] = None, user: User = Depends(works), db: Session = Depends(get_db)):
    """The agent's own data in this campaign (or one allocation of it), so they can see what is coming and pick one."""
    _my_campaign(db, user, campaign_id)
    ls.release_stale(db, campaign_id)
    stmt = select(Lead).where(Lead.campaign_id == campaign_id, Lead.assigned_to_id == user.id, Lead.status.in_(("new", "callback")))
    if batch_id is not None:
        stmt = stmt.where(Lead.batch_id.is_(None) if batch_id == 0 else Lead.batch_id == batch_id)
    rows = list(db.scalars(stmt.order_by(Lead.status, Lead.next_call_at, Lead.id).limit(50)))
    db.commit()
    return [ls.lead_out(r) for r in rows]


@router.post("/queue/take")
def take_lead(body: TakeIn, user: User = Depends(works), db: Session = Depends(get_db)):
    camp = _my_campaign(db, user, body.campaign_id)
    if camp.status != "active":
        raise ag.err(409, f"The campaign “{camp.name}” is {camp.status}, so calls cannot be made.", "campaign_not_active")
    _expire_old(db, user)
    pending = db.scalar(select(Interaction).where(Interaction.agent_id == user.id, Interaction.status == "open").order_by(Interaction.id))
    if pending:
        raise ag.err(409, "You have a call that is not tagged yet. Finish it, or skip it with a reason, before taking the next one.",
                     "locked", open_call_id=pending.id)
    ls.release_stale(db, camp.id)
    lead = None
    if body.lead_id:
        lead = db.scalar(ls.available(user.id, camp.id).where(Lead.id == body.lead_id).with_for_update(skip_locked=True))
        if not lead:
            raise ag.err(409, "This lead is not available to you right now (taken by someone else, not due yet, or already done).", "unavailable")
    else:
        lead = ls.pick_next(db, user.id, camp.id, body.batch_id)
        if not lead:
            raise ag.err(404, "No data is waiting for you in this allocation right now." if body.batch_id is not None else "No data is waiting for you in this campaign right now.", "queue_empty")
    it = ls.start_call(db, user, lead)
    audit(db, user, "call_opened", client_id=it.client_id, detail={"interaction": it.id, "mode": "manual", "lead": lead.id})
    db.commit()
    return ag.payload(db, user, it)
