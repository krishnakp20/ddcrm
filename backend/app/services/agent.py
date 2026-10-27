"""What an agent may work on, and how a link from the dialer is turned into a call on the agent's screen."""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AgentCampaign, AgentClient, Campaign, Client, Customer, DialerId, Interaction, User
from . import forms as fs
from . import leads as ls
from .onboarding import logo_url

DIALER_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:\- ]{1,60}$")
LOCK_HOURS = 4  # an unfinished call older than this no longer blocks the agent


def err(status: int, message: str, code: str = "error", **extra: Any) -> HTTPException:
    return HTTPException(status, detail={"message": message, "code": code, **extra})


def clean_value(raw: Optional[str]) -> str:
    return (raw or "").strip()


def today_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo(settings.TIMEZONE))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


# ---------- who may work what ----------

def can_work_client(db: Session, user: User, client_id: int) -> bool:
    if user.client_id is not None:
        return user.client_id == client_id  # a client's own agent works only for that client
    return bool(db.scalar(select(AgentClient.id).where(AgentClient.user_id == user.id, AgentClient.client_id == client_id)))


def can_work_campaign(db: Session, user: User, campaign: Campaign) -> bool:
    return can_work_client(db, user, campaign.client_id) and bool(
        db.scalar(select(AgentCampaign.id).where(AgentCampaign.user_id == user.id, AgentCampaign.campaign_id == campaign.id)))


def allowed_clients(db: Session, user: User) -> list[Client]:
    if user.client_id is not None:
        c = db.get(Client, user.client_id)
        return [c] if c and c.status == "active" else []
    ids = list(db.scalars(select(AgentClient.client_id).where(AgentClient.user_id == user.id)))
    return [c for c in db.scalars(select(Client).where(Client.id.in_(ids or [0]), Client.status == "active").order_by(Client.company_name))]


def allowed_campaigns(db: Session, user: User) -> list[Campaign]:
    ids = list(db.scalars(select(AgentCampaign.campaign_id).where(AgentCampaign.user_id == user.id)))
    clients = {c.id for c in allowed_clients(db, user)}
    return [c for c in db.scalars(select(Campaign).where(Campaign.id.in_(ids or [0])).order_by(Campaign.name)) if c.client_id in clients]


# ---------- reading the dialer's ids ----------

@dataclass
class Resolved:
    client: Client
    mode: str                      # inbound | pd
    campaign: Optional[Campaign]
    group: str                     # the ingroup / dialer campaign id as it was received


def resolve(db: Session, user: User, vendor_id: str, ingroup_id: Optional[str], campaign_id: Optional[str]) -> Resolved:
    """Turns vendor_id + ingroup_id (inbound) or vendor_id + campaign_id (predictive) into a client and a form,
    and checks the signed-in agent may work there. Every refusal says what to ask the admin for."""
    vendor, ingroup, camp = clean_value(vendor_id), clean_value(ingroup_id), clean_value(campaign_id)
    if not vendor:
        raise err(422, "The link has no vendor_id.", "no_vendor")
    if bool(ingroup) == bool(camp):
        raise err(422, "The link needs exactly one of ingroup_id (inbound) or campaign_id (predictive).", "bad_link")

    vendor_row = db.scalar(select(DialerId).where(DialerId.kind == "vendor", DialerId.value == vendor, DialerId.is_active.is_(True)))
    if not vendor_row:
        raise err(404, f"Vendor ID “{vendor}” is not set up for any client. Ask your admin to add it under the client's Dialer IDs.", "unknown_vendor")
    client = db.get(Client, vendor_row.client_id)
    if not client or client.status != "active":
        raise err(409, "This client is not active.", "client_inactive")
    if not can_work_client(db, user, client.id):
        raise err(403, f"You are not allocated to work for {client.company_name}. Ask your admin.", "not_allocated")

    if ingroup:
        row = db.scalar(select(DialerId).where(DialerId.client_id == client.id, DialerId.kind == "ingroup", DialerId.value == ingroup,
                                               DialerId.is_active.is_(True)))
        if not row:
            raise err(404, f"Ingroup “{ingroup}” is not set up for {client.company_name}. Ask your admin to add it.", "unknown_ingroup")
        return Resolved(client, "inbound", None, ingroup)

    row = db.scalar(select(DialerId).where(DialerId.client_id == client.id, DialerId.kind == "campaign", DialerId.value == camp,
                                           DialerId.is_active.is_(True)))
    campaign = db.get(Campaign, row.campaign_id) if row else None
    if not campaign:
        raise err(404, f"Campaign ID “{camp}” is not set up for {client.company_name}. Ask your admin to add it to the campaign.", "unknown_campaign")
    if campaign.status != "active":
        raise err(409, f"The campaign “{campaign.name}” is {campaign.status}, so calls cannot be tagged.", "campaign_not_active")
    if not can_work_campaign(db, user, campaign):
        raise err(403, f"You are not allocated to the campaign “{campaign.name}”. Ask your admin.", "not_allocated")
    return Resolved(client, "pd", campaign, camp)


# ---------- what the agent's page shows ----------

def customer_out(c: Optional[Customer]) -> Optional[dict[str, Any]]:
    if not c:
        return None
    return {"id": c.id, "name": c.name, "mobile": c.mobile, "email": c.email, "city": c.city, "ext_ref": c.ext_ref}


def history(db: Session, it: Interaction, limit: int = 10) -> list[dict[str, Any]]:
    if not it.customer_id:
        return []
    rows = db.scalars(select(Interaction).where(Interaction.client_id == it.client_id, Interaction.customer_id == it.customer_id,
                                                Interaction.id != it.id, Interaction.status == "tagged")
                      .order_by(Interaction.id.desc()).limit(limit))
    out = []
    for r in rows:
        agent = db.get(User, r.agent_id)
        camp = db.get(Campaign, r.campaign_id) if r.campaign_id else None
        out.append({"id": r.id, "mode": r.mode, "when": r.tagged_at or r.started_at, "agent": agent.name if agent else None,
                    "campaign": camp.name if camp else None, "scenario": r.scenario_names, "outcome": r.outcome, "notes": r.notes})
    return out


def interaction_out(it: Interaction) -> dict[str, Any]:
    return {"id": it.id, "mode": it.mode, "phone": it.phone, "call_id": it.call_id, "status": it.status,
            "started_at": it.started_at, "tagged_at": it.tagged_at, "scenario": it.scenario_names, "outcome": it.outcome,
            "answers": it.answers or {}, "notes": it.notes, "customer_id": it.customer_id}


def payload(db: Session, user: User, it: Interaction, warnings: Optional[list[str]] = None) -> dict[str, Any]:
    client = db.get(Client, it.client_id)
    campaign = db.get(Campaign, it.campaign_id) if it.campaign_id else None
    ctx = "out_call" if campaign else "in_call"
    cust = db.get(Customer, it.customer_id) if it.customer_id else None
    return {
        "interaction": interaction_out(it),
        "client": {"id": client.id, "name": client.company_name, "logo_url": logo_url(client)},
        "campaign": {"id": campaign.id, "name": campaign.name} if campaign else None,
        "customer": customer_out(cust), "history": history(db, it),
        "lead": (lambda l: ls.lead_out(l) if l else None)(ls.lead_of(db, it)),
        "form": fs.build_config(db, client, ctx, campaign.id if campaign else None, campaign),
        "warnings": warnings or [],
    }
