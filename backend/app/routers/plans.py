"""Plans (price lists): create, approve, and allocate to clients with an effective date."""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, permissions_of, require_permission
from ..models import (
    PLAN_STATUSES,
    BillingExclusion,
    Client,
    Plan,
    PlanAssignment,
    User,
)
from ..services import onboarding as ob
from ..services import plans as pl

router = APIRouter(tags=["plans"])
view_plans = require_permission("plans.view")
manage_plans = require_permission("plans.manage")
approve_plans = require_permission("plans.approve")
assign_plans = require_permission("plans.assign")


class PlanIn(BaseModel):
    values: dict[str, Any]
    notes: Optional[str] = Field(default=None, max_length=1000)


class RemarkIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class AssignIn(BaseModel):
    plan_id: int
    effective_from: date
    note: Optional[str] = Field(default=None, max_length=300)


class ExclusionItem(BaseModel):
    user_id: int
    reason: Optional[str] = Field(default=None, max_length=200)


class ExclusionsIn(BaseModel):
    exclusions: list[ExclusionItem]


# ---------- helpers ----------

def _get(db: Session, plan_id: int) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return plan


def _unique_name(db: Session, name: str, skip_id: Optional[int] = None) -> None:
    stmt = select(Plan.id).where(func.lower(Plan.name) == name.lower())
    if skip_id:
        stmt = stmt.where(Plan.id != skip_id)
    if db.scalar(stmt):
        ob.fail({"plan_name": "A plan with this name already exists"})


def plan_out(db: Session, p: Plan, brief: bool = False) -> dict[str, Any]:
    out = {"id": p.id, "name": p.name, "plan_type": p.plan_type, "plan_mode": p.plan_mode, "status": p.status,
           "subscription_amount": p.config.get("subscription_amount", "0"), "setup_fee": p.config.get("setup_fee", "0"),
           "created_at": p.created_at}
    if brief:
        return out
    clients = db.scalar(select(func.count(func.distinct(PlanAssignment.client_id))).where(
        PlanAssignment.plan_id == p.id, PlanAssignment.cancelled_at.is_(None)))
    return {**out, "values": {"plan_name": p.name, "plan_type": p.plan_type, "plan_mode": p.plan_mode, **p.config},
            "notes": p.notes, "reject_remarks": p.reject_remarks, "created_by": p.created_by.name if p.created_by else None,
            "approved_by": p.approved_by.name if p.approved_by else None, "approved_at": p.approved_at,
            "updated_at": p.updated_at, "clients_using": clients, "cloned_from_id": p.cloned_from_id}


# ---------- plans ----------

@router.get("/api/plans/schema")
def get_schema(user: User = Depends(view_plans)):
    return pl.schema()


@router.get("/api/plans")
def list_plans(status: Optional[str] = None, q: Optional[str] = None, user: User = Depends(view_plans),
               db: Session = Depends(get_db)):
    stmt = select(Plan)
    if status:
        stmt = stmt.where(Plan.status == status)
    if q:
        stmt = stmt.where(Plan.name.ilike(f"%{q.strip()}%"))
    counts = dict(db.execute(select(Plan.status, func.count()).group_by(Plan.status)).all())
    return {"items": [plan_out(db, p, brief=True) for p in db.scalars(stmt.order_by(Plan.id.desc()).limit(300))],
            "counts": {s: counts.get(s, 0) for s in PLAN_STATUSES}}


@router.post("/api/plans", status_code=201)
def create_plan(body: PlanIn, user: User = Depends(manage_plans), db: Session = Depends(get_db)):
    data, errors = pl.normalize(body.values)
    if errors:
        ob.fail(errors)
    _unique_name(db, data["plan_name"])
    plan = Plan(name=data["plan_name"], plan_type=data["plan_type"], plan_mode=data["plan_mode"], config=data["config"],
                notes=body.notes, status="pending", created_by_id=user.id)
    db.add(plan)
    db.flush()
    audit(db, user, "plan_created", detail={"plan": plan.id, "name": plan.name})
    db.commit()
    db.refresh(plan)
    return plan_out(db, plan)


@router.get("/api/plans/{plan_id}")
def get_plan(plan_id: int, user: User = Depends(view_plans), db: Session = Depends(get_db)):
    return plan_out(db, _get(db, plan_id))


@router.put("/api/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, user: User = Depends(manage_plans), db: Session = Depends(get_db)):
    """Only plans that are waiting or were rejected can be edited. An approved plan is frozen so that bills
    already issued never change; clone it to make a new version."""
    plan = _get(db, plan_id)
    if plan.status not in ("pending", "rejected"):
        raise HTTPException(409, "An approved plan cannot be edited. Clone it to create a new version.")
    data, errors = pl.normalize(body.values)
    if errors:
        ob.fail(errors)
    _unique_name(db, data["plan_name"], plan.id)
    plan.name, plan.plan_type, plan.plan_mode = data["plan_name"], data["plan_type"], data["plan_mode"]
    plan.config, plan.notes = data["config"], body.notes
    plan.status, plan.reject_remarks = "pending", None  # an edited rejected plan goes back for approval
    audit(db, user, "plan_edited", detail={"plan": plan.id})
    db.commit()
    return plan_out(db, plan)


@router.post("/api/plans/{plan_id}/approve")
def approve(plan_id: int, user: User = Depends(approve_plans), db: Session = Depends(get_db)):
    plan = _get(db, plan_id)
    if plan.status != "pending":
        raise HTTPException(409, "Only a plan waiting for approval can be approved")
    admins = sum(1 for u in db.scalars(select(User).where(User.is_active.is_(True), User.user_type == "staff"))
                 if "plans.approve" in permissions_of(u))  # people who could approve
    if plan.created_by_id == user.id and admins > 1:
        # maker-checker: with more than one admin, a second person must approve
        raise HTTPException(403, "Another admin must approve a plan you created")
    plan.status, plan.approved_by_id, plan.approved_at = "approved", user.id, datetime.now(timezone.utc)
    plan.reject_remarks = None
    audit(db, user, "plan_approved", detail={"plan": plan.id, "self_approved": plan.created_by_id == user.id})
    db.commit()
    db.refresh(plan)  # reload so the approver's name is included
    return plan_out(db, plan)


@router.post("/api/plans/{plan_id}/reject")
def reject(plan_id: int, body: RemarkIn, user: User = Depends(approve_plans), db: Session = Depends(get_db)):
    plan = _get(db, plan_id)
    if plan.status != "pending":
        raise HTTPException(409, "Only a plan waiting for approval can be rejected")
    plan.status, plan.reject_remarks = "rejected", body.note.strip()
    audit(db, user, "plan_rejected", detail={"plan": plan.id, "note": body.note})
    db.commit()
    return plan_out(db, plan)


@router.post("/api/plans/{plan_id}/retire")
def retire(plan_id: int, user: User = Depends(manage_plans), db: Session = Depends(get_db)):
    """A retired plan cannot be given to new clients; clients already on it stay on it."""
    plan = _get(db, plan_id)
    if plan.status != "approved":
        raise HTTPException(409, "Only an approved plan can be retired")
    plan.status = "retired"
    audit(db, user, "plan_retired", detail={"plan": plan.id})
    db.commit()
    return plan_out(db, plan)


@router.post("/api/plans/{plan_id}/clone", status_code=201)
def clone(plan_id: int, user: User = Depends(manage_plans), db: Session = Depends(get_db)):
    src = _get(db, plan_id)
    name, n = f"{src.name} (copy)", 1
    while db.scalar(select(Plan.id).where(func.lower(Plan.name) == name.lower())):
        n += 1
        name = f"{src.name} (copy {n})"
    plan = Plan(name=name, plan_type=src.plan_type, plan_mode=src.plan_mode, config=dict(src.config), notes=src.notes,
                status="pending", created_by_id=user.id, cloned_from_id=src.id)
    db.add(plan)
    db.flush()
    audit(db, user, "plan_cloned", detail={"from": src.id, "to": plan.id})
    db.commit()
    return plan_out(db, plan)


# ---------- plan of a client, with effective dates ----------

def _client(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client


def _assignments(db: Session, client_id: int) -> list[PlanAssignment]:
    return list(db.scalars(select(PlanAssignment).where(PlanAssignment.client_id == client_id)))


@router.get("/api/clients/{client_id}/plan")
def client_plan(client_id: int, user: User = Depends(view_plans), db: Session = Depends(get_db)):
    _client(db, client_id)
    on = pl.today()
    tl = pl.timeline(_assignments(db, client_id), on)
    rows = []
    for r in tl["rows"]:
        a = r["assignment"]
        rows.append({"id": a.id, "plan_id": a.plan_id, "plan_name": a.plan.name, "plan_type": a.plan.plan_type,
                     "plan_mode": a.plan.plan_mode, "effective_from": a.effective_from, "effective_to": r["effective_to"],
                     "state": r["state"], "note": a.note, "can_cancel": r["state"] == "upcoming"})
    available = db.scalars(select(Plan).where(Plan.status == "approved").order_by(Plan.name))
    return {"today": on, "rows": rows[::-1],  # newest first
            "available_plans": [plan_out(db, p, brief=True) for p in available],
            "first_allocation": not rows}


@router.post("/api/clients/{client_id}/plan-assignments", status_code=201)
def assign(client_id: int, body: AssignIn, user: User = Depends(assign_plans), db: Session = Depends(get_db)):
    """Gives the client a plan from an effective date. Used for the first plan and for every later change."""
    client = _client(db, client_id)
    if client.status not in ("active", "suspended"):
        raise HTTPException(409, "A plan can be given only to an active client")
    plan = _get(db, body.plan_id)
    if plan.status != "approved":
        raise HTTPException(422, "Only an approved plan can be given to a client")
    on = pl.today()
    live = sorted((a for a in _assignments(db, client_id) if not a.cancelled_at), key=lambda a: a.effective_from)
    earliest = on - timedelta(days=90) if not live else on  # the very first plan may start in the recent past
    if body.effective_from < earliest:
        ob.fail({"effective_from": "The effective date cannot be in the past" if live
                 else "The first plan can start at most 90 days ago"})
    if live and body.effective_from <= live[-1].effective_from:
        ob.fail({"effective_from": f"The new plan must start after the last one ({live[-1].effective_from:%d %b %Y}). "
                                   "Cancel the upcoming change first if you want to replace it."})
    if live and live[-1].plan_id == plan.id:
        ob.fail({"plan_id": "The client is already on this plan from that point"})
    a = PlanAssignment(client_id=client_id, plan_id=plan.id, effective_from=body.effective_from, note=body.note,
                       created_by_id=user.id)
    db.add(a)
    audit(db, user, "plan_assigned", client_id=client_id,
          detail={"plan": plan.id, "from": body.effective_from.isoformat()})
    db.commit()
    return {"id": a.id}


@router.delete("/api/clients/{client_id}/plan-assignments/{assignment_id}")
def cancel_assignment(client_id: int, assignment_id: int, user: User = Depends(assign_plans), db: Session = Depends(get_db)):
    """Only a change that has not started yet can be cancelled; history is never rewritten."""
    a = db.get(PlanAssignment, assignment_id)
    if not a or a.client_id != client_id or a.cancelled_at:
        raise HTTPException(404, "Plan change not found")
    if a.effective_from <= pl.today():
        raise HTTPException(409, "This plan has already started and cannot be cancelled")
    a.cancelled_at = datetime.now(timezone.utc)
    audit(db, user, "plan_assignment_cancelled", client_id=client_id, detail={"assignment": a.id})
    db.commit()
    return {"ok": True}


# ---------- users the client is not billed for ----------

def _billing_view(db: Session, client_id: int) -> dict[str, Any]:
    users = list(db.scalars(select(User).where(User.client_id == client_id).order_by(User.name)))
    ex = {e.user_id: e for e in db.scalars(select(BillingExclusion).where(BillingExclusion.client_id == client_id))}
    on = pl.today()
    current = next((r for r in reversed(pl.timeline(_assignments(db, client_id), on)["rows"]) if r["state"] == "current"), None)
    cfg = current["assignment"].plan.config if current else None
    billable = sum(1 for u in users if u.is_active and u.id not in ex)
    out: dict[str, Any] = {
        "users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role_key, "is_active": u.is_active,
                   "excluded": u.id in ex, "reason": ex[u.id].reason if u.id in ex else None} for u in users],
        "billable_users": billable, "excluded_users": sum(1 for u in users if u.id in ex),
        "plan_name": current["assignment"].plan.name if current else None,
    }
    if cfg:
        free, per = int(cfg["free_users"]), pl._dec(cfg["extra_user_charge"])
        extra = max(0, billable - free)
        out.update({"free_users": free, "extra_users": extra, "extra_user_charge": cfg["extra_user_charge"],
                    "extra_user_total": format(per * extra, "f")})
    return out


@router.get("/api/clients/{client_id}/billing-settings")
def billing_settings(client_id: int, user: User = Depends(view_plans), db: Session = Depends(get_db)):
    _client(db, client_id)
    return _billing_view(db, client_id)


@router.put("/api/clients/{client_id}/billing-settings")
def save_billing_settings(client_id: int, body: ExclusionsIn, user: User = Depends(assign_plans),
                          db: Session = Depends(get_db)):
    """Replaces the list of users that are not billed to this client."""
    _client(db, client_id)
    wanted = {e.user_id: e.reason for e in body.exclusions}
    valid = set(db.scalars(select(User.id).where(User.client_id == client_id, User.id.in_(wanted or [0]))))
    if set(wanted) - valid:
        raise HTTPException(422, "One of the chosen users does not belong to this client")
    for row in list(db.scalars(select(BillingExclusion).where(BillingExclusion.client_id == client_id))):
        if row.user_id not in wanted:
            db.delete(row)
        else:
            row.reason = (wanted.pop(row.user_id) or None)
    for uid, reason in wanted.items():
        db.add(BillingExclusion(client_id=client_id, user_id=uid, reason=reason or None, created_by_id=user.id))
    audit(db, user, "billing_exclusions_saved", client_id=client_id, detail={"users": sorted(valid)})
    db.commit()
    return _billing_view(db, client_id)
