"""The ids the dialer uses (vendor, ingroup, campaign) and who may work for which client / campaign."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of, require_permission
from ..models import AgentCampaign, AgentClient, Campaign, Client, DialerId, DialerServer, User
from ..services import agent as ag
from ..services import dialer as dl

router = APIRouter(prefix="/api", tags=["dialer-ids"])

KINDS = {"vendor": "Vendor ID", "ingroup": "Ingroup ID", "campaign": "Campaign ID"}


class DialerIdIn(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=60)
    campaign_id: Optional[int] = None
    label: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = True
    dialer_server_id: Optional[int] = None  # ingroup / campaign ids: which dialer server uses this name (empty = any)


class IdsIn(BaseModel):
    ids: list[int]


def fail(fields: dict[str, str], message: str = "Please fix the highlighted fields") -> None:
    raise HTTPException(422, detail={"message": message, "fields": fields})


def _staff(u: User) -> bool:
    return u.user_type == "staff"


def _out(db: Session, d: DialerId) -> dict[str, Any]:
    camp = db.get(Campaign, d.campaign_id) if d.campaign_id else None
    return {"id": d.id, "kind": d.kind, "value": d.value, "campaign_id": d.campaign_id, "campaign_name": camp.name if camp else None,
            "label": d.label, "is_active": d.is_active, "dialer_server_id": d.dialer_server_id}


def _remap(db: Session, d: DialerId) -> None:
    """Calls and agent rows that arrived before this id was set up now get their client."""
    if d.kind == "vendor" or not d.is_active:
        return
    stmt = select(DialerServer)
    if d.dialer_server_id:
        stmt = stmt.where(DialerServer.id == d.dialer_server_id)
    for server in db.scalars(stmt):
        dl.remap(db, server)


# ---------- dialer ids (DialDesk staff set them up) ----------

@router.get("/clients/{client_id}/dialer-ids")
def list_dialer_ids(client_id: int, user: User = Depends(require_permission("clients.view")), db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    rows = db.scalars(select(DialerId).where(DialerId.client_id == client_id).order_by(DialerId.kind, DialerId.value))
    return [_out(db, d) for d in rows]


@router.get("/campaigns/{campaign_id}/dialer-ids")
def campaign_dialer_ids(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Read-only for client users: shows which dialer campaign ids feed this campaign."""
    if "campaigns.view" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    c = db.get(Campaign, campaign_id)
    if not c or (not _staff(user) and c.client_id != user.client_id):
        raise HTTPException(404, "Campaign not found")
    return [_out(db, d) for d in db.scalars(select(DialerId).where(DialerId.campaign_id == c.id).order_by(DialerId.value))]


def _check(db: Session, client_id: int, body: DialerIdIn, skip: Optional[int] = None) -> str:
    errors: dict[str, str] = {}
    if body.kind not in KINDS:
        errors["kind"] = "Choose vendor, ingroup or campaign"
    value = body.value.strip()
    if not ag.DIALER_VALUE_RE.match(value):
        errors["value"] = "Use letters, numbers, spaces and . _ : - only (up to 60 characters)"
    if body.kind == "campaign":
        camp = db.get(Campaign, body.campaign_id) if body.campaign_id else None
        if not camp or camp.client_id != client_id:
            errors["campaign_id"] = "Choose one of this client's campaigns"
    elif body.campaign_id:
        errors["campaign_id"] = "Only a campaign ID belongs to a campaign"
    if body.dialer_server_id and (body.kind == "vendor" or not db.get(DialerServer, body.dialer_server_id)):
        errors["dialer_server_id"] = "Choose a dialer server (not for vendor IDs)"
    if not errors:
        if body.kind == "vendor":
            clash = db.scalar(select(DialerId).where(DialerId.kind == "vendor", DialerId.value == value, DialerId.id != (skip or 0)))
            if clash:
                owner = db.get(Client, clash.client_id)
                errors["value"] = ("This vendor ID is already used by "
                                   f"{owner.company_name if owner else 'another client'}. A vendor ID can belong to one client only.")
        else:
            clash = db.scalar(select(DialerId).where(DialerId.client_id == client_id, DialerId.kind == body.kind,
                                                     DialerId.value == value, DialerId.id != (skip or 0)))
            if clash:
                errors["value"] = f"This {KINDS[body.kind].lower()} already exists for this client"
    if errors:
        fail(errors)
    return value


@router.post("/clients/{client_id}/dialer-ids", status_code=201)
def add_dialer_id(client_id: int, body: DialerIdIn, user: User = Depends(require_permission("clients.manage")),
                  db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    value = _check(db, client_id, body)
    d = DialerId(client_id=client_id, kind=body.kind, value=value, campaign_id=body.campaign_id if body.kind == "campaign" else None,
                 label=(body.label or "").strip() or None, is_active=body.is_active, dialer_server_id=body.dialer_server_id or None)
    db.add(d)
    db.flush()
    _remap(db, d)
    audit(db, user, "dialer_id_added", client_id=client_id, detail={"kind": d.kind, "value": d.value})
    db.commit()
    return _out(db, d)


@router.put("/dialer-ids/{dialer_id}")
def update_dialer_id(dialer_id: int, body: DialerIdIn, user: User = Depends(require_permission("clients.manage")),
                     db: Session = Depends(get_db)):
    d = db.get(DialerId, dialer_id)
    if not d:
        raise HTTPException(404, "Not found")
    if body.kind != d.kind:
        fail({"kind": "The kind cannot be changed. Add a new one instead."})
    d.value = _check(db, d.client_id, body, d.id)
    d.label, d.is_active = (body.label or "").strip() or None, body.is_active
    d.dialer_server_id = body.dialer_server_id or None
    if d.kind == "campaign":
        d.campaign_id = body.campaign_id
    db.flush()
    _remap(db, d)
    audit(db, user, "dialer_id_updated", client_id=d.client_id, detail={"id": d.id})
    db.commit()
    return _out(db, d)


@router.delete("/dialer-ids/{dialer_id}")
def delete_dialer_id(dialer_id: int, user: User = Depends(require_permission("clients.manage")), db: Session = Depends(get_db)):
    d = db.get(DialerId, dialer_id)
    if not d:
        raise HTTPException(404, "Not found")
    audit(db, user, "dialer_id_deleted", client_id=d.client_id, detail={"kind": d.kind, "value": d.value})
    db.delete(d)
    db.commit()
    return {"ok": True}


# ---------- allocating agents ----------

@router.get("/users/{user_id}/clients")
def agent_clients(user_id: int, user: User = Depends(require_permission("users.view")), db: Session = Depends(get_db)):
    """Clients a shared DialDesk agent is allowed to work for."""
    if user.user_type != "staff":
        raise HTTPException(403, "Only DialDesk staff allocate shared agents to clients")
    agent = db.get(User, user_id)
    if not agent or agent.user_type != "agent":
        raise HTTPException(404, "Agent not found")
    ids = set(db.scalars(select(AgentClient.client_id).where(AgentClient.user_id == agent.id)))
    return {"shared": agent.client_id is None,
            "clients": [{"id": c.id, "name": c.company_name, "allocated": c.id in ids}
                        for c in db.scalars(select(Client).where(Client.status.in_(("active", "suspended"))).order_by(Client.company_name))]}


@router.put("/users/{user_id}/clients")
def set_agent_clients(user_id: int, body: IdsIn, user: User = Depends(require_permission("users.manage")), db: Session = Depends(get_db)):
    if user.user_type != "staff":
        raise HTTPException(403, "Only DialDesk staff allocate shared agents to clients")
    agent = db.get(User, user_id)
    if not agent or agent.user_type != "agent":
        raise HTTPException(404, "Agent not found")
    if agent.client_id is not None:
        raise HTTPException(409, "This agent belongs to a client company and works for it automatically.")
    wanted = set(body.ids)
    valid = set(db.scalars(select(Client.id).where(Client.id.in_(wanted or [0]))))
    if wanted - valid:
        raise HTTPException(422, "One of the chosen clients does not exist")
    for row in list(db.scalars(select(AgentClient).where(AgentClient.user_id == agent.id))):
        if row.client_id not in wanted:
            db.delete(row)
            # leaving a client also removes the agent from that client's campaigns
            for ac in list(db.scalars(select(AgentCampaign).join(Campaign, Campaign.id == AgentCampaign.campaign_id)
                                      .where(AgentCampaign.user_id == agent.id, Campaign.client_id == row.client_id))):
                db.delete(ac)
        else:
            wanted.discard(row.client_id)
    for cid in wanted:
        db.add(AgentClient(user_id=agent.id, client_id=cid))
    audit(db, user, "agent_clients_set", detail={"agent": agent.id, "clients": sorted(valid)})
    db.commit()
    return {"ok": True}


def _campaign_for(db: Session, user: User, campaign_id: int, write: bool) -> Campaign:
    perm = "campaigns.manage" if write else "campaigns.view"
    if perm not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    c = db.get(Campaign, campaign_id)
    if not c or (not _staff(user) and c.client_id != user.client_id):
        raise HTTPException(404, "Campaign not found")
    return c


def _eligible_agents(db: Session, client_id: int) -> list[User]:
    shared = select(AgentClient.user_id).where(AgentClient.client_id == client_id)
    return list(db.scalars(select(User).where(User.user_type == "agent", User.is_active.is_(True),
                                              (User.client_id == client_id) | User.id.in_(shared)).order_by(User.name)))


@router.get("/campaigns/{campaign_id}/agents")
def campaign_agents(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _campaign_for(db, user, campaign_id, False)
    allocated = set(db.scalars(select(AgentCampaign.user_id).where(AgentCampaign.campaign_id == c.id)))
    return [{"id": a.id, "name": a.name, "email": a.email, "dialer_agent_id": a.dialer_agent_id, "shared": a.client_id is None,
             "allocated": a.id in allocated} for a in _eligible_agents(db, c.client_id)]


@router.put("/campaigns/{campaign_id}/agents")
def set_campaign_agents(campaign_id: int, body: IdsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _campaign_for(db, user, campaign_id, True)
    eligible = {a.id for a in _eligible_agents(db, c.client_id)}
    wanted = set(body.ids)
    if wanted - eligible:
        raise HTTPException(422, "One of the chosen people cannot work for this client. Allocate shared agents to the client first.")
    for row in list(db.scalars(select(AgentCampaign).where(AgentCampaign.campaign_id == c.id))):
        if row.user_id not in wanted:
            db.delete(row)
        else:
            wanted.discard(row.user_id)
    for uid in wanted:
        db.add(AgentCampaign(user_id=uid, campaign_id=c.id))
    audit(db, user, "campaign_agents_set", client_id=c.client_id, detail={"campaign": c.id, "agents": sorted(set(body.ids))})
    db.commit()
    return {"ok": True}
