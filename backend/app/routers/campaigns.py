"""Outbound campaigns of a client. Each campaign has its own tagging form (see routers/forms.py)."""
import re
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import CAMPAIGN_STATUSES, Campaign, Client, FormField, Scenario, User, ValueList

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

STATUS_LABEL = {"draft": "Draft", "active": "Active", "paused": "Paused", "closed": "Closed"}
# what a campaign may move to next
TRANSITIONS = {"draft": ("active", "closed"), "active": ("paused", "closed"), "paused": ("active", "closed"), "closed": ("paused",)}


class CampaignIn(BaseModel):
    client_id: Optional[int] = None
    name: str = Field(min_length=2, max_length=150)
    code: Optional[str] = Field(default=None, max_length=30)
    description: Optional[str] = Field(default=None, max_length=500)
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class StatusIn(BaseModel):
    status: str


def fail(fields: dict[str, str], message: str = "Please fix the highlighted fields") -> None:
    raise HTTPException(422, detail={"message": message, "fields": fields})


def _staff(u: User) -> bool:
    return u.user_type == "staff"


def _need(user: User, perm: str) -> None:
    if perm not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")


def _client_scope(db: Session, user: User, client_id: Optional[int]) -> Client:
    """Staff choose the client; a client user always works inside their own company."""
    cid = client_id if _staff(user) else user.client_id
    client = db.get(Client, cid) if cid else None
    if not client or (not _staff(user) and client.id != user.client_id):
        raise HTTPException(404, "Client not found")
    return client


def _get(db: Session, user: User, campaign_id: int) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if not c or (not _staff(user) and c.client_id != user.client_id):
        raise HTTPException(404, "Campaign not found")  # same answer for other companies' campaigns
    return c


def out(db: Session, c: Campaign) -> dict[str, Any]:
    fields = db.scalar(select(func.count()).select_from(FormField).where(FormField.campaign_id == c.id))
    scenarios = db.scalar(select(func.count()).select_from(Scenario).where(Scenario.campaign_id == c.id))
    client = db.get(Client, c.client_id)
    return {"id": c.id, "client_id": c.client_id, "client_name": client.company_name if client else None, "name": c.name,
            "code": c.code, "description": c.description, "status": c.status, "start_date": c.start_date,
            "end_date": c.end_date, "created_at": c.created_at, "fields_count": fields, "scenarios_count": scenarios,
            "next_statuses": list(TRANSITIONS[c.status])}


def _check(db: Session, client: Client, body: CampaignIn, existing: Optional[Campaign]) -> tuple[str, str]:
    errors: dict[str, str] = {}
    name = " ".join(body.name.split())
    clash = select(Campaign.id).where(Campaign.client_id == client.id, func.lower(Campaign.name) == name.lower())
    if existing:
        clash = clash.where(Campaign.id != existing.id)
    if db.scalar(clash):
        errors["name"] = "This client already has a campaign with this name"
    code = (body.code or "").strip().upper()
    if code:
        if not re.fullmatch(r"[A-Z0-9_-]{2,30}", code):
            errors["code"] = "Use letters, numbers, - and _ (2 to 30 characters)"
        else:
            dup = select(Campaign.id).where(Campaign.client_id == client.id, Campaign.code == code)
            if existing:
                dup = dup.where(Campaign.id != existing.id)
            if db.scalar(dup):
                errors["code"] = "This code is already used by another campaign of the client"
    else:
        n = (db.scalar(select(func.count()).select_from(Campaign).where(Campaign.client_id == client.id)) or 0) + 1
        code = f"CMP{n:03d}"
        while db.scalar(select(Campaign.id).where(Campaign.client_id == client.id, Campaign.code == code)):
            n += 1
            code = f"CMP{n:03d}"
    if body.start_date and body.end_date and body.end_date < body.start_date:
        errors["end_date"] = "The end date cannot be before the start date"
    if errors:
        fail(errors)
    return name, code


@router.get("/clients")
def clients_for_campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.view")
    stmt = select(Client).where(Client.status.in_(("active", "suspended"))).order_by(Client.company_name)
    if not _staff(user):
        stmt = stmt.where(Client.id == user.client_id)
    return [{"id": c.id, "name": c.company_name, "code": c.code} for c in db.scalars(stmt)]


@router.get("")
def list_campaigns(client_id: Optional[int] = None, status: Optional[str] = None, q: Optional[str] = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.view")
    stmt = select(Campaign)
    if not _staff(user):
        stmt = stmt.where(Campaign.client_id == user.client_id)
    elif client_id:
        stmt = stmt.where(Campaign.client_id == client_id)
    if status:
        stmt = stmt.where(Campaign.status == status)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q.strip()}%"))
    counts_stmt = select(Campaign.status, func.count()).group_by(Campaign.status)
    if not _staff(user):
        counts_stmt = counts_stmt.where(Campaign.client_id == user.client_id)
    elif client_id:
        counts_stmt = counts_stmt.where(Campaign.client_id == client_id)
    counts = dict(db.execute(counts_stmt).all())
    return {"items": [out(db, c) for c in db.scalars(stmt.order_by(Campaign.id.desc()).limit(500))],
            "counts": {s: counts.get(s, 0) for s in CAMPAIGN_STATUSES},
            "can_manage": "campaigns.manage" in permissions_of(user)}


@router.post("", status_code=201)
def create_campaign(body: CampaignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.manage")
    client = _client_scope(db, user, body.client_id)
    if client.status not in ("active", "suspended"):
        raise HTTPException(409, "Campaigns can only be created for an active client")
    name, code = _check(db, client, body, None)
    c = Campaign(client_id=client.id, name=name, code=code, description=body.description, start_date=body.start_date,
                 end_date=body.end_date, status="draft", created_by_id=user.id)
    db.add(c)
    db.flush()
    audit(db, user, "campaign_created", client_id=client.id, detail={"campaign": c.id, "name": name})
    db.commit()
    return out(db, c)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.view")
    return {**out(db, _get(db, user, campaign_id)), "can_manage": "campaigns.manage" in permissions_of(user)}


@router.put("/{campaign_id}")
def update_campaign(campaign_id: int, body: CampaignIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.manage")
    c = _get(db, user, campaign_id)
    client = db.get(Client, c.client_id)
    name, code = _check(db, client, body, c)
    c.name, c.code, c.description, c.start_date, c.end_date = name, code, body.description, body.start_date, body.end_date
    audit(db, user, "campaign_updated", client_id=c.client_id, detail={"campaign": c.id})
    db.commit()
    return out(db, c)


@router.post("/{campaign_id}/status")
def set_status(campaign_id: int, body: StatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "campaigns.manage")
    c = _get(db, user, campaign_id)
    if body.status not in TRANSITIONS[c.status]:
        raise HTTPException(409, f"A {STATUS_LABEL[c.status].lower()} campaign cannot be changed to {STATUS_LABEL.get(body.status, body.status).lower()}")
    if body.status == "active":
        has_form = db.scalar(select(func.count()).select_from(FormField).where(FormField.campaign_id == c.id)) \
            or db.scalar(select(func.count()).select_from(Scenario).where(Scenario.campaign_id == c.id))
        if not has_form:
            raise HTTPException(409, "Set up the tagging form first (fields and scenarios), then activate the campaign.")
    c.status = body.status
    audit(db, user, "campaign_status", client_id=c.client_id, detail={"campaign": c.id, "status": body.status})
    db.commit()
    return out(db, c)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only a draft that was never started can be deleted; anything else is closed, so its history is kept."""
    _need(user, "campaigns.manage")
    c = _get(db, user, campaign_id)
    if c.status != "draft":
        raise HTTPException(409, "Only a draft campaign can be deleted. Close it instead.")
    for f in db.scalars(select(FormField).where(FormField.campaign_id == c.id)):
        vl = db.get(ValueList, f.value_list_id) if f.value_list_id else None
        if vl and vl.is_private:
            db.delete(vl)  # the field's own values go with it
    audit(db, user, "campaign_deleted", client_id=c.client_id, detail={"name": c.name})
    db.delete(c)  # its fields and scenarios are removed with it
    db.commit()
    return {"ok": True}
