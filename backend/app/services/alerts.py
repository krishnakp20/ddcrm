"""Alerts: when something happens for a client (a ticket is raised or assigned, an SLA is about to be missed, a call is
tagged with a given outcome or answer), message the people its rules name, by email / SMS / WhatsApp."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AlertLog, AlertRule, Client, Ticket, User
from . import notify

log = logging.getLogger("alerts")

CHANNELS = ("email", "sms", "whatsapp")
DUE_SOON = timedelta(hours=2)

EVENTS: dict[str, dict[str, str]] = {
    "ticket_created": {"title": "New ticket", "ticket": "1", "text": "New ticket {number} for {client}: {subject}. Priority {priority}. Customer {customer} ({mobile}). Due {due}. {link}"},
    "ticket_assigned": {"title": "Ticket assigned", "ticket": "1", "text": "Ticket {number} ({subject}) of {client} was assigned to {assignee}. Priority {priority}, due {due}. {link}"},
    "ticket_resolved": {"title": "Ticket resolved", "ticket": "1", "text": "Ticket {number} ({subject}) of {client} is now {status}. {link}"},
    "sla_due_soon": {"title": "Ticket due soon", "ticket": "1", "text": "Ticket {number} ({subject}) of {client} is due at {due}. It is still {status}. {link}"},
    "sla_breached": {"title": "SLA missed", "ticket": "1", "text": "SLA missed: ticket {number} ({subject}) of {client} was due at {due} and is still {status}. Assigned to {assignee}. {link}"},
    "ticket_stale": {"title": "Ticket still open after some hours", "ticket": "1", "text": "Ticket {number} ({subject}) of {client} is still {status} after {age} hours. Assigned to {assignee}. {link}"},
    "call_tagged": {"title": "Call tagged", "text": "{client}: call with {customer} ({mobile}) tagged by {agent}. {scenario}. Outcome: {outcome}. {notes}"},
}
EVENT_LABEL = {k: v["title"] for k, v in EVENTS.items()}


def _phone(raw: Optional[str]) -> Optional[str]:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if not digits:
        return None
    return f"+91{digits}" if len(digits) == 10 else f"+{digits}"


def matches(rule: AlertRule, *, priority: Optional[str], outcome: Optional[str], scenario: list[str], answers: dict[str, Any],
            campaign_id: Optional[int] = None, age_hours: Optional[float] = None) -> bool:
    c = rule.conditions or {}
    if c.get("campaign") and campaign_id not in c["campaign"]:
        return False
    if rule.event == "ticket_stale" and (age_hours is None or age_hours < float(c.get("hours") or 24)):
        return False
    if c.get("priority") and priority not in c["priority"]:
        return False
    if c.get("outcome") and outcome not in c["outcome"]:
        return False
    if c.get("scenario_path"):  # chosen from the form's scenario tree: the call / ticket must be under this path
        want = [str(p).strip().lower() for p in c["scenario_path"]]
        got = [str(s).strip().lower() for s in scenario]
        if got[:len(want)] != want:
            return False
    if c.get("scenario_contains") and not any(c["scenario_contains"].lower() in s.lower() for s in scenario):
        return False
    if c.get("field_key"):
        got = answers.get(c["field_key"])
        want = str(c.get("field_value", "")).strip().lower()
        vals = [str(x).strip().lower() for x in (got if isinstance(got, list) else [got]) if x is not None]
        if want and want not in vals:
            return False
        if not want and not vals:
            return False
    return True


def _targets(db: Session, rule: AlertRule, assignee_id: Optional[int], agent_id: Optional[int],
             customer_phone: Optional[str] = None) -> list[tuple[str, Optional[str], Optional[str]]]:
    """(name, email, phone) of everyone the rule names, each once."""
    r = rule.recipients or {}
    ids = set(r.get("users") or [])
    if r.get("assignee") and assignee_id:
        ids.add(assignee_id)
    if r.get("agent") and agent_id:
        ids.add(agent_id)
    out: list[tuple[str, Optional[str], Optional[str]]] = []
    seen: set[str] = set()
    for u in db.scalars(select(User).where(User.id.in_(ids or {0}), User.is_active.is_(True))):
        out.append((u.name, u.email, _phone(u.phone)))
        seen.add(u.email.lower())
    for e in r.get("emails") or []:
        if e.lower() not in seen:
            out.append((e, e, None))
            seen.add(e.lower())
    for m in r.get("mobiles") or []:
        out.append((m, None, _phone(m)))
    if r.get("customer") and _phone(customer_phone):
        out.append(("Customer", None, _phone(customer_phone)))  # reached by SMS / WhatsApp only: we hold no email for them
    return out


def deliver(db: Session, rule: AlertRule, ctx: dict[str, Any], targets, client_id: int) -> tuple[int, int]:
    text = notify.render(rule.message or EVENTS[rule.event]["text"], ctx)
    subject = f"DialDesk: {EVENTS[rule.event]['title']}" + (f" {ctx['number']}" if ctx.get("number") else "")
    sent = failed = 0
    for _name, email, phone in targets:
        for ch in rule.channels or []:
            to = email if ch == "email" else phone
            if ch not in CHANNELS or not to:
                continue
            note = notify.send(db, ch, to, text, subject if ch == "email" else None, client_id)
            if note.status == "failed":
                failed += 1
            else:
                sent += 1
    return sent, failed


def ticket_ctx(db: Session, t: Ticket, client: Client) -> dict[str, Any]:
    from ..models import Customer
    cust = db.get(Customer, t.customer_id) if t.customer_id else None
    who = db.get(User, t.assigned_user_id) if t.assigned_user_id else None
    due = t.due_at.astimezone().strftime("%d %b %H:%M") if t.due_at else "no due time"
    answers = {k: ", ".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in (t.answers or {}).items()}
    names = list(t.scenario_names or []) + [""] * 5
    age = max(0, int((datetime.now(timezone.utc) - t.created_at).total_seconds() // 3600)) if t.created_at else 0
    return {**answers, "category1": names[0], "category2": names[1], "category3": names[2], "category4": names[3], "category5": names[4],
            "scenario": " > ".join(n for n in names if n), "calldate": t.created_at.astimezone().strftime("%d %b %Y %H:%M") if t.created_at else "", "age": age,
            "number": t.number, "subject": t.subject, "priority": t.priority, "status": t.status.replace("_", " "),
            "client": client.company_name, "customer": cust.name if cust else "-", "mobile": cust.mobile if cust else "-",
            "assignee": who.name if who else "nobody yet", "due": due, "link": f"{settings.APP_BASE_URL}/tickets/{t.id}"}


def fire(db: Session, event: str, client_id: int, ctx: dict[str, Any], *, priority: Optional[str] = None, outcome: Optional[str] = None,
         scenario: Optional[list[str]] = None, answers: Optional[dict[str, Any]] = None, assignee_id: Optional[int] = None,
         agent_id: Optional[int] = None, ref: Optional[str] = None, dedupe: Optional[str] = None, campaign_id: Optional[int] = None,
         age_hours: Optional[float] = None, since: Optional[datetime] = None) -> int:
    """Runs every active rule of the client for this event. Never raises: an alert problem must not break the action."""
    sent_total = 0
    try:
        rules = list(db.scalars(select(AlertRule).where(AlertRule.client_id == client_id, AlertRule.event == event, AlertRule.is_active.is_(True))))
        for rule in rules:
            if since and rule.created_at and rule.created_at > since:
                continue  # an alert only applies to tickets raised after it was set up, so old tickets never trigger it
            if not matches(rule, priority=priority, outcome=outcome, scenario=scenario or [], answers=answers or {}, campaign_id=campaign_id, age_hours=age_hours):
                continue
            row = AlertLog(rule_id=rule.id, client_id=client_id, event=event, ref=ref, dedupe=dedupe)
            if dedupe:
                try:
                    with db.begin_nested():
                        db.add(row)
                        db.flush()
                except IntegrityError:
                    continue  # already sent for this ticket
            else:
                db.add(row)
            targets = _targets(db, rule, assignee_id, agent_id, ctx.get("mobile"))
            row.sent, row.failed = deliver(db, rule, ctx, targets, client_id)
            sent_total += row.sent
    except Exception:  # noqa: BLE001
        log.exception("alert failed")
    return sent_total


def scan_sla(db: Session) -> int:
    """Called every minute: tickets about to miss, or that missed, their SLA."""
    now = datetime.now(timezone.utc)
    n = 0
    tickets = db.scalars(select(Ticket).where(Ticket.status.in_(("open", "in_progress", "pending")), Ticket.due_at.is_not(None),
                                              Ticket.due_at < now + DUE_SOON, Ticket.due_at > now - timedelta(days=1)).limit(500))
    for t in tickets:
        client = db.get(Client, t.client_id)
        if not client:
            continue
        event = "sla_breached" if t.due_at < now else "sla_due_soon"
        n += fire(db, event, t.client_id, ticket_ctx(db, t, client), priority=t.priority, scenario=t.scenario_names, answers=t.answers,
                  assignee_id=t.assigned_user_id, ref=t.number, dedupe=f"{event}:{t.id}", since=t.created_at)
    n += _scan_stale(db, now)
    db.commit()
    return n


def _scan_stale(db: Session, now: datetime) -> int:
    """Tickets that are still open after the hours an alert names (the escalation levels of the old CRM)."""
    rules = list(db.scalars(select(AlertRule).where(AlertRule.event == "ticket_stale", AlertRule.is_active.is_(True))))
    if not rules:
        return 0
    soonest: dict[int, float] = {}
    for r in rules:
        h = float((r.conditions or {}).get("hours") or 24)
        soonest[r.client_id] = min(h, soonest.get(r.client_id, h))
    n = 0
    tickets = db.scalars(select(Ticket).where(Ticket.client_id.in_(list(soonest)), Ticket.status.in_(("open", "in_progress", "pending")),
                                              Ticket.created_at > now - timedelta(days=30)).limit(3000))
    for t in tickets:
        age = (now - t.created_at).total_seconds() / 3600
        if age < soonest[t.client_id]:
            continue
        client = db.get(Client, t.client_id)
        if client:
            n += fire(db, "ticket_stale", t.client_id, ticket_ctx(db, t, client), priority=t.priority, scenario=t.scenario_names, answers=t.answers,
                      assignee_id=t.assigned_user_id, ref=t.number, dedupe=f"stale:{t.id}", age_hours=age, since=t.created_at)
    return n
