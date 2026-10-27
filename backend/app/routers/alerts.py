"""Alert rules: who is messaged (and on which channel) when a ticket or call event happens for a client."""
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import AlertLog, AlertRule, Client, Ticket, User
from ..services import alerts as al
from ..services import notify

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _need(user: User) -> None:
    if "alerts.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")


def _client(db: Session, user: User, client_id: Optional[int]) -> Client:
    cid = client_id if user.user_type == "staff" else user.client_id
    c = db.get(Client, cid) if cid else None
    if not c:
        raise HTTPException(404, "Client not found")
    return c


def _rule(db: Session, user: User, rule_id: int) -> AlertRule:
    _need(user)
    r = db.get(AlertRule, rule_id)
    if not r or (user.user_type != "staff" and r.client_id != user.client_id):
        raise HTTPException(404, "Alert not found")
    return r


def out(r: AlertRule) -> dict[str, Any]:
    return {"id": r.id, "client_id": r.client_id, "name": r.name, "event": r.event, "event_label": al.EVENT_LABEL.get(r.event, r.event),
            "conditions": r.conditions or {}, "recipients": r.recipients or {}, "channels": r.channels or [], "message": r.message,
            "is_active": r.is_active}


class RuleIn(BaseModel):
    client_id: Optional[int] = None
    name: str = Field(default="", max_length=120)
    event: str = ""
    conditions: dict[str, Any] = {}
    recipients: dict[str, Any] = {}
    channels: list[str] = []
    message: Optional[str] = Field(default=None, max_length=1000)
    is_active: bool = True


def _clean(db: Session, user: User, client: Client, body: RuleIn) -> dict[str, Any]:
    errors: dict[str, str] = {}
    name = " ".join(body.name.split())
    if len(name) < 3:
        errors["name"] = "Give the alert a name"
    if body.event not in al.EVENTS:
        errors["event"] = "Choose when to alert"
    channels = [c for c in body.channels if c in al.CHANNELS]
    if not channels:
        errors["channels"] = "Choose at least one channel"
    r = body.recipients or {}
    emails = [e.strip().lower() for e in r.get("emails", []) if e and e.strip()]
    if any(not EMAIL.match(e) for e in emails):
        errors["emails"] = "One of the email addresses is not valid"
    mobiles = ["".join(ch for ch in str(m) if ch.isdigit()) for m in r.get("mobiles", []) if str(m).strip()]
    if any(not 6 <= len(m) <= 15 for m in mobiles):
        errors["mobiles"] = "One of the mobile numbers is not valid"
    if len(emails) > 5 or len(mobiles) > 5:
        errors["recipients"] = "At most 5 email addresses and 5 mobile numbers per alert; add people as users instead"
    pool = select(User.id).where(User.is_active.is_(True), (User.client_id == client.id) | (User.user_type == "staff" if user.user_type == "staff" else False))
    shared = set(db.scalars(pool))
    users = [int(u) for u in r.get("users", []) if int(u) in shared]
    ticket = body.event in al.EVENTS and al.EVENTS[body.event].get("ticket")
    rec = {"assignee": bool(r.get("assignee")) and bool(ticket), "agent": bool(r.get("agent")) and body.event == "call_tagged",
           "customer": bool(r.get("customer")), "users": users, "emails": emails, "mobiles": mobiles}
    if not (rec["assignee"] or rec["agent"] or rec["customer"] or users or emails or mobiles):
        errors["recipients"] = "Choose who should be told"
    c = body.conditions or {}
    cond: dict[str, Any] = {}
    if c.get("priority"):
        cond["priority"] = [p for p in c["priority"] if p in ("low", "medium", "high", "urgent")]
    if c.get("outcome"):
        cond["outcome"] = [o for o in c["outcome"] if isinstance(o, str)]
    if body.event == "ticket_stale":
        try:
            hours = int(c.get("hours"))
            if not 1 <= hours <= 8760:
                raise ValueError
            cond["hours"] = hours
        except (TypeError, ValueError):
            errors["hours"] = "Enter the number of hours (1 to 8760)"
    if isinstance(c.get("campaign"), list):
        cond["campaign"] = [int(x) for x in c["campaign"] if str(x).isdigit()]
    if isinstance(c.get("scenario_path"), list):
        path = [" ".join(str(p).split())[:150] for p in c["scenario_path"] if str(p).strip()][:5]
        if path:
            cond["scenario_path"] = path
    if str(c.get("scenario_contains") or "").strip():
        cond["scenario_contains"] = str(c["scenario_contains"]).strip()[:100]
    if str(c.get("field_key") or "").strip():
        cond["field_key"], cond["field_value"] = str(c["field_key"]).strip()[:60], str(c.get("field_value") or "").strip()[:100]
    if errors:
        raise HTTPException(422, detail={"message": "Please fix the highlighted fields", "fields": errors})
    return {"name": name, "event": body.event, "conditions": cond, "recipients": rec, "channels": channels,
            "message": (body.message or "").strip() or None, "is_active": body.is_active}


@router.get("/meta")
def meta(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    client = _client(db, user, client_id)
    from ..services.forms import form_fields
    cond = (User.client_id == client.id) | (User.user_type == "staff") if user.user_type == "staff" else (User.client_id == client.id)
    people = db.scalars(select(User).where(User.is_active.is_(True), cond).order_by(User.name))
    fields = form_fields(db, client.id, "in_call")
    from ..models import Campaign
    from ..services.forms import scenario_tree

    def slim(nodes):
        return [{"name": n["name"], "children": slim(n["children"])} for n in nodes]

    forms = []
    inbound = slim(scenario_tree(db, client.id, "in_call", only_active=True))
    if inbound:
        forms.append({"key": "in_call", "label": "Inbound calls and tickets", "campaign_id": None, "scenarios": inbound})
    for camp in db.scalars(select(Campaign).where(Campaign.client_id == client.id).order_by(Campaign.name)):
        tree = slim(scenario_tree(db, client.id, "out_call", only_active=True, campaign_id=camp.id))
        if tree:
            forms.append({"key": f"campaign-{camp.id}", "label": f"Campaign: {camp.name}", "campaign_id": camp.id, "scenarios": tree})
    return {"scenario_forms": forms, "events": [{"key": k, "label": v["title"], "ticket": bool(v.get("ticket")), "text": v["text"]} for k, v in al.EVENTS.items()],
            "users": [{"id": u.id, "name": u.name, "kind": "DialDesk" if u.user_type == "staff" else "Client"} for u in people],
            "fields": [{"key": f.key, "label": f.label} for f in fields],
            "channels": [{"key": k, "label": l, "live": notify._configured(k)} for k, l in (("email", "Email"), ("sms", "SMS"), ("whatsapp", "WhatsApp"))],
            "variables": ["category1", "category2", "category3", "category4", "category5", "calldate", "age", "number", "subject", "priority", "status", "client", "customer", "mobile", "assignee", "due", "link", "agent", "scenario", "outcome", "notes"]}


@router.get("/rules")
def list_rules(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    client = _client(db, user, client_id)
    return [out(r) for r in db.scalars(select(AlertRule).where(AlertRule.client_id == client.id).order_by(AlertRule.id))]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    client = _client(db, user, body.client_id)
    r = AlertRule(client_id=client.id, created_by_id=user.id, **_clean(db, user, client, body))
    db.add(r)
    audit(db, user, "alert_created", client_id=client.id, detail={"event": r.event})
    db.commit()
    return out(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _rule(db, user, rule_id)
    for k, v in _clean(db, user, db.get(Client, r.client_id), body).items():
        setattr(r, k, v)
    db.commit()
    return out(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = _rule(db, user, rule_id)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/rules/{rule_id}/test")
def test_rule(rule_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sends a sample message to the people the rule names, so the setup can be checked."""
    r = _rule(db, user, rule_id)
    client = db.get(Client, r.client_id)
    ctx = {"number": "T-000000", "subject": "Sample ticket", "priority": "high", "status": "open", "client": client.company_name,
           "customer": "Sample Customer", "mobile": "9999999999", "assignee": user.name, "due": "tomorrow 10:00", "link": "",
           "agent": user.name, "scenario": "Sample scenario", "outcome": "callback", "notes": ""}
    targets = al._targets(db, r, user.id, user.id, "9999999999")
    sent, failed = al.deliver(db, r, {**ctx}, targets, client.id)
    db.commit()
    return {"sent": sent, "failed": failed, "people": len(targets)}


@router.post("/standard", status_code=201)
def standard_rules(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Adds the usual alerts, once: tell the assignee when a ticket is given to them, and tell them when it is about to be missed."""
    _need(user)
    client = _client(db, user, client_id)
    have = {r.event for r in db.scalars(select(AlertRule).where(AlertRule.client_id == client.id))}
    made = 0
    for name, event in (("Tell the assignee when a ticket is assigned", "ticket_assigned"),
                        ("Warn the assignee before the SLA is missed", "sla_due_soon"),
                        ("Tell the assignee when the SLA is missed", "sla_breached")):
        if event in have:
            continue
        db.add(AlertRule(client_id=client.id, name=name, event=event, conditions={}, channels=["email", "whatsapp"],
                         recipients={"assignee": True, "agent": False, "users": [], "emails": [], "mobiles": []}, created_by_id=user.id))
        made += 1
    db.commit()
    return {"added": made}


@router.get("/log")
def log(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    client = _client(db, user, client_id)
    rows = db.execute(select(AlertLog, AlertRule.name).join(AlertRule, AlertRule.id == AlertLog.rule_id)
                      .where(AlertLog.client_id == client.id).order_by(AlertLog.id.desc()).limit(40)).all()
    return [{"id": l.id, "rule": name, "event": al.EVENT_LABEL.get(l.event, l.event), "ref": l.ref, "sent": l.sent, "failed": l.failed,
             "created_at": l.created_at} for l, name in rows]
