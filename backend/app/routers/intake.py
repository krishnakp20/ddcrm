"""Intake channels: website form, WhatsApp bot and email become tickets (or a comment on the ticket they answer)."""
import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import (INTAKE_KINDS, TICKET_PRIORITIES, Client, Customer, IntakeChannel, IntakeLog, IntakeMessage, Ticket, TicketComment,
                      User)
from ..services.phone import normalize_phone, valid_phone
from .tickets import OPEN_STATUSES, _alert, _check_assignment, _event, due_for

router = APIRouter(prefix="/api/intake", tags=["intake"])
KIND_LABEL = {"website": "Website form", "whatsapp": "WhatsApp bot", "email": "Email"}
MAX_BODY = 256 * 1024
_hits: dict[str, deque] = defaultdict(deque)
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
REF = re.compile(r"\bT-(\d{6})\b")
AUTO_SUBJECT = ("auto:", "automatic reply", "out of office", "undeliverable", "delivery status notification")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clean(v: Any, limit: int) -> str:
    return CTRL.sub("", str(v or "")).strip()[:limit]


def _limit(key: str, per_minute: int) -> None:
    q, now = _hits[key], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_minute:
        raise HTTPException(429, "Too many requests. Try again in a minute.")
    q.append(now)


# ---------- setup (admin screens) ----------

def _need(user: User) -> None:
    if "alerts.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")


def _client(db: Session, user: User, client_id: Optional[int]) -> Client:
    cid = client_id if user.user_type == "staff" else user.client_id
    c = db.get(Client, cid) if cid else None
    if not c:
        raise HTTPException(404, "Client not found")
    return c


def _chan_out(db: Session, ch: Optional[IntakeChannel], kind: str) -> dict[str, Any]:
    s = (ch.settings if ch else {}) or {}
    return {"kind": kind, "label": KIND_LABEL[kind], "exists": ch is not None, "is_active": bool(ch and ch.is_active),
            "token_hint": ch.token_hint if ch else None, "received_total": ch.received_total if ch else 0,
            "last_used_at": ch.last_used_at if ch else None, "priority": s.get("priority", "medium"),
            "assigned_user_id": s.get("assigned_user_id"), "assigned_department_id": s.get("assigned_department_id")}


@router.get("/channels")
def channels(client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    client = _client(db, user, client_id)
    have = {c.kind: c for c in db.scalars(select(IntakeChannel).where(IntakeChannel.client_id == client.id))}
    logs = db.scalars(select(IntakeLog).where(IntakeLog.client_id == client.id).order_by(IntakeLog.id.desc()).limit(30))
    return {"client_id": client.id, "client_name": client.company_name, "base_url": settings.APP_BASE_URL.rstrip("/"),
            "channels": [_chan_out(db, have.get(k), k) for k in INTAKE_KINDS],
            "logs": [{"id": l.id, "kind": l.kind, "result": l.result, "ticket": l.ticket_number, "detail": l.detail, "created_at": l.created_at} for l in logs]}


@router.post("/channels/{kind}/key")
def new_key(kind: str, client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creates the channel's key, or replaces it (the old one stops working at once). The key is shown only this once."""
    _need(user)
    if kind not in INTAKE_KINDS:
        raise HTTPException(404, "Unknown channel")
    client = _client(db, user, client_id)
    token = secrets.token_urlsafe(24)
    ch = db.scalar(select(IntakeChannel).where(IntakeChannel.client_id == client.id, IntakeChannel.kind == kind))
    if ch:
        ch.token_hash, ch.token_hint, ch.is_active = _hash(token), token[:6], True
    else:
        ch = IntakeChannel(client_id=client.id, kind=kind, token_hash=_hash(token), token_hint=token[:6], settings={"priority": "medium"})
        db.add(ch)
    audit(db, user, "intake_key_created", client_id=client.id, detail={"kind": kind})
    db.commit()
    base = settings.APP_BASE_URL.rstrip("/")
    return {**_chan_out(db, ch, kind), "token": token, "url": f"{base}/api/intake/{token}/{kind}"}


class ChannelIn(BaseModel):
    is_active: Optional[bool] = None
    priority: Optional[str] = None
    assigned_user_id: Optional[int] = None
    assigned_department_id: Optional[int] = None
    clear_assignment: bool = False


@router.put("/channels/{kind}")
def save_channel(kind: str, body: ChannelIn, client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    if kind not in INTAKE_KINDS:
        raise HTTPException(404, "Unknown channel")
    client = _client(db, user, client_id)
    ch = db.scalar(select(IntakeChannel).where(IntakeChannel.client_id == client.id, IntakeChannel.kind == kind))
    if not ch:
        raise HTTPException(409, "Create the key first.")
    s = dict(ch.settings or {})
    if body.is_active is not None:
        ch.is_active = body.is_active
    if body.priority is not None:
        if body.priority not in TICKET_PRIORITIES:
            raise HTTPException(422, detail={"message": "Choose a priority", "fields": {"priority": "Choose a priority"}})
        s["priority"] = body.priority
    if body.clear_assignment:
        s["assigned_user_id"] = s["assigned_department_id"] = None
    elif body.assigned_user_id is not None or body.assigned_department_id is not None:
        _check_assignment(db, client, body.assigned_user_id, body.assigned_department_id)
        s["assigned_user_id"], s["assigned_department_id"] = body.assigned_user_id, body.assigned_department_id
    ch.settings = s
    audit(db, user, "intake_changed", client_id=client.id, detail={"kind": kind})
    db.commit()
    return _chan_out(db, ch, kind)


# ---------- making a ticket, or adding to one ----------

def _log(db: Session, ch: IntakeChannel, result: str, number: Optional[str] = None, detail: Optional[str] = None) -> None:
    db.add(IntakeLog(client_id=ch.client_id, channel_id=ch.id, kind=ch.kind, result=result, ticket_number=number, detail=(detail or "")[:200] or None))


def _channel(db: Session, token: str, kind: str, request: Request) -> IntakeChannel:
    _limit(f"t:{_hash(token)}", 60)
    ch = db.scalar(select(IntakeChannel).where(IntakeChannel.token_hash == _hash(token)))
    if not ch or ch.kind != kind or not ch.is_active:
        raise HTTPException(401, "This key is not valid.")
    client = db.get(Client, ch.client_id)
    if not client or client.status != "active":
        raise HTTPException(409, "This client is not active.")
    return ch


async def _payload(request: Request) -> dict[str, Any]:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "The message is too large.")
    ctype = request.headers.get("content-type", "")
    try:
        if "json" in ctype:
            data = await request.json()
        elif "form" in ctype:
            data = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
        else:
            raw = (await request.body())[:MAX_BODY]
            import json
            data = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(422, "Send JSON or a form post.")
    return data if isinstance(data, (dict, list)) else {}


def _customer(db: Session, client_id: int, name: str, mobile: str, email: str) -> Optional[Customer]:
    if valid_phone(mobile):
        c = db.scalar(select(Customer).where(Customer.client_id == client_id, Customer.mobile == mobile))
        if c:
            c.email = c.email or email or None
            return c
        c = Customer(client_id=client_id, name=name or f"Customer {mobile[-4:]}", mobile=mobile, email=email or None)
        db.add(c)
        db.flush()
        return c
    if email:
        return db.scalar(select(Customer).where(Customer.client_id == client_id, Customer.email.ilike(email)))
    return None


def _new_ticket(db: Session, ch: IntakeChannel, *, name: str, mobile: str, email: str, subject: str, text: str) -> Ticket:
    s = ch.settings or {}
    priority = s.get("priority") if s.get("priority") in TICKET_PRIORITIES else "medium"
    cust = _customer(db, ch.client_id, name, mobile, email)
    now = datetime.now(timezone.utc)
    t = Ticket(client_id=ch.client_id, customer_id=cust.id if cust else None, subject=_clean(subject, 200) or "New request", description=None,
               priority=priority, status="open", source=ch.kind, channel_id=ch.id, contact_name=name or None, contact_email=email or None,
               assigned_user_id=s.get("assigned_user_id"), assigned_department_id=s.get("assigned_department_id"),
               due_at=due_for(db, ch.client_id, priority, now))
    db.add(t)
    db.flush()
    t.number = f"T-{t.id:06d}"
    _event(db, t, None, f"Ticket created from {KIND_LABEL[ch.kind].lower()}")
    if text:
        db.add(TicketComment(ticket_id=t.id, user_id=None, kind="comment", body=text))
    if t.assigned_user_id:
        t.status = "in_progress"
        _event(db, t, None, "Assigned automatically by the channel's default settings")
    _alert(db, "ticket_created", t)
    if t.assigned_user_id:
        _alert(db, "ticket_assigned", t)
    return t


def _append(db: Session, t: Ticket, text: str, via: str) -> None:
    db.add(TicketComment(ticket_id=t.id, user_id=None, kind="comment", body=text))
    if t.status in ("resolved", "closed", "pending"):
        _event(db, t, None, f"The customer wrote again ({via}), so the ticket is open again")
        t.status, t.resolved_at, t.closed_at = "open", None, None
    t.updated_at = datetime.now(timezone.utc)


def _remember(db: Session, ch: IntakeChannel, external_id: Optional[str], ticket_id: int) -> None:
    if external_id:
        db.add(IntakeMessage(channel_id=ch.id, external_id=external_id[:300], ticket_id=ticket_id))


def _seen(db: Session, ch: IntakeChannel, external_id: Optional[str]) -> bool:
    return bool(external_id and db.scalar(select(IntakeMessage.id).where(IntakeMessage.channel_id == ch.id, IntakeMessage.external_id == external_id[:300])))


def _touch(ch: IntakeChannel) -> None:
    ch.last_used_at = datetime.now(timezone.utc)
    ch.received_total += 1


# ---------- website form ----------

CORS = {"Access-Control-Allow-Origin": "*"}


@router.post("/{token}/website")
async def website(token: str, request: Request, db: Session = Depends(get_db)):
    """A contact form on the client's website. Accepts a normal HTML form post (a thank-you page is shown) or JSON."""
    is_form = "json" not in request.headers.get("content-type", "")
    try:
        _limit(f"ip:{request.client.host if request.client else '?'}", 10)
        ch = _channel(db, token, "website", request)
        data = await _payload(request)
        if not isinstance(data, dict):
            raise HTTPException(422, "Send the form fields as an object.")
        if data.get("website_hp") or data.get("_gotcha"):  # a hidden field only a robot fills
            return _done(is_form, None, fake=True)
        name, message = _clean(data.get("name"), 150), _clean(data.get("message") or data.get("description"), 4000)
        mobile = normalize_phone(_clean(data.get("mobile") or data.get("phone"), 40))
        email = _clean(data.get("email"), 255).lower()
        errors = {}
        if len(name) < 2:
            errors["name"] = "Please enter your name"
        if len(message) < 5:
            errors["message"] = "Please write your message"
        if not valid_phone(mobile) and not ("@" in email and "." in email.split("@")[-1]):
            errors["mobile"] = "Please enter a valid mobile number or email"
        if errors:
            raise HTTPException(422, detail={"message": "Please check the form", "fields": errors})
        if not valid_phone(mobile):
            mobile = ""
        if "@" not in email or "." not in email.split("@")[-1]:
            email = ""
        known = {"name", "mobile", "phone", "email", "message", "description", "subject", "website_hp", "_gotcha"}
        extra = [f"{_clean(k, 60)}: {_clean(v, 300)}" for k, v in list(data.items())[:40] if k not in known and _clean(v, 300)][:15]
        text = message + ("\n\n" + "\n".join(extra) if extra else "")
        subject = _clean(data.get("subject"), 200) or f"Website enquiry: {message[:60]}"
        t = _new_ticket(db, ch, name=name, mobile=mobile, email=email, subject=subject, text=text[:4000])
        _touch(ch)
        _log(db, ch, "created", t.number)
        db.commit()
        return _done(is_form, t.number)
    except HTTPException as e:
        db.rollback()
        detail = e.detail if isinstance(e.detail, dict) else {"message": e.detail}
        if is_form:
            return HTMLResponse(_page("We could not send your message", detail.get("message", "Please try again."), error=True), status_code=e.status_code, headers=CORS)
        return JSONResponse({"ok": False, **detail}, status_code=e.status_code, headers=CORS)


def _done(is_form: bool, number: Optional[str], fake: bool = False):
    if is_form:
        return HTMLResponse(_page("Thank you", "We have received your message and will get back to you soon." + (f" Your reference is {number}." if number else "")), headers=CORS)
    return JSONResponse({"ok": True, "reference": number}, headers=CORS)


def _page(title: str, text: str, error: bool = False) -> str:
    color = "#c4001f" if error else "#005872"
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title>"
            f"<body style='font-family:system-ui,sans-serif;max-width:480px;margin:15vh auto;padding:0 20px'><h2 style='color:{color}'>{title}</h2>"
            f"<p>{text}</p><p><a href='javascript:history.back()'>Go back</a></p></body>")


# ---------- WhatsApp bot ----------

def _wa_messages(data: Any) -> list[dict[str, str]]:
    """The messages in a WhatsApp Cloud API webhook, or in the simple format {from, name, message, message_id} (or a list of those)."""
    out: list[dict[str, str]] = []
    if isinstance(data, dict) and "entry" in data:
        for entry in data.get("entry") or []:
            for chg in entry.get("changes") or []:
                v = chg.get("value") or {}
                names = {c.get("wa_id"): ((c.get("profile") or {}).get("name") or "") for c in v.get("contacts") or []}
                for m in v.get("messages") or []:
                    kind = m.get("type", "text")
                    body = (m.get("text") or {}).get("body") if kind == "text" else None
                    if body is None:
                        inner = m.get(kind) if isinstance(m.get(kind), dict) else {}
                        body = f"[{kind}] {inner.get('caption') or ''}".strip()
                    out.append({"from": str(m.get("from", "")), "name": names.get(m.get("from"), ""), "text": body or "", "id": str(m.get("id", ""))})
        return out
    items = data.get("messages") if isinstance(data, dict) and isinstance(data.get("messages"), list) else (data if isinstance(data, list) else [data])
    for m in items:
        if isinstance(m, dict):
            out.append({"from": str(m.get("from") or m.get("phone") or m.get("mobile") or m.get("wa_id") or ""), "name": str(m.get("name") or m.get("profile_name") or ""),
                        "text": str(m.get("message") or m.get("text") or m.get("body") or ""), "id": str(m.get("message_id") or m.get("id") or "")})
    return out


@router.get("/{token}/whatsapp")
def whatsapp_verify(token: str, request: Request, db: Session = Depends(get_db)):
    """The handshake WhatsApp Cloud API does when the webhook is saved: the verify token is the channel key."""
    q = request.query_params
    ch = db.scalar(select(IntakeChannel).where(IntakeChannel.token_hash == _hash(token)))
    if ch and ch.kind == "whatsapp" and q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verification failed.")


@router.post("/{token}/whatsapp")
async def whatsapp(token: str, request: Request, db: Session = Depends(get_db)):
    ch = _channel(db, token, "whatsapp", request)
    msgs = _wa_messages(await _payload(request))
    done = {"created": 0, "appended": 0, "duplicate": 0, "rejected": 0}
    for m in msgs[:100]:
        mobile, text = normalize_phone(_clean(m["from"], 40)), _clean(m["text"], 4000)
        if not valid_phone(mobile) or not text:
            done["rejected"] += 1
            _log(db, ch, "rejected", detail="No valid sender number or no text")
            continue
        if _seen(db, ch, m["id"]):
            done["duplicate"] += 1
            continue
        cust = _customer(db, ch.client_id, _clean(m["name"], 150), mobile, "")
        open_t = db.scalar(select(Ticket).where(Ticket.client_id == ch.client_id, Ticket.customer_id == cust.id, Ticket.source == "whatsapp",
                                                Ticket.status.in_(OPEN_STATUSES + ("resolved",))).order_by(Ticket.id.desc()))
        try:
            with db.begin_nested():
                if open_t:
                    _append(db, open_t, text, "WhatsApp")
                    t, kind = open_t, "appended"
                else:
                    t, kind = _new_ticket(db, ch, name=_clean(m["name"], 150), mobile=mobile, email="", subject=f"WhatsApp: {text[:70]}", text=text), "created"
                _remember(db, ch, m["id"], t.id)
                db.flush()
        except IntegrityError:
            done["duplicate"] += 1
            continue
        done[kind] += 1
        _touch(ch)
        _log(db, ch, kind, t.number)
    db.commit()
    return {"ok": True, **done}


# ---------- email ----------

@router.post("/{token}/email")
async def email_in(token: str, request: Request, db: Session = Depends(get_db)):
    """An email forwarded by the mail provider's inbound webhook (SendGrid, Mailgun, Postmark ... or your own relay) as JSON or a form post."""
    ch = _channel(db, token, "email", request)
    d = await _payload(request)
    if not isinstance(d, dict):
        raise HTTPException(422, "Send the email as an object.")
    pick = lambda *keys: next((d[k] for k in keys if d.get(k)), "")
    name, addr = parseaddr(str(pick("from", "sender", "from_email", "From")))
    addr = addr.strip().lower()
    name = _clean(pick("from_name") or name, 150)
    subject, text = _clean(pick("subject", "Subject"), 300), _clean(pick("text", "body", "body-plain", "stripped-text", "plain"), 4000)
    mid = _clean(pick("message_id", "Message-Id", "Message-ID", "message-id"), 300).strip("<>")
    reply_to = _clean(pick("in_reply_to", "In-Reply-To", "in-reply-to"), 300).strip("<>")
    if "@" not in addr or "." not in addr.split("@")[-1]:
        _log(db, ch, "rejected", detail="No valid sender address")
        db.commit()
        raise HTTPException(422, "The email has no valid sender address.")
    if subject.lower().startswith(AUTO_SUBJECT) or str(pick("auto_submitted", "Auto-Submitted")).lower() not in ("", "no"):
        _log(db, ch, "rejected", detail="Automatic reply ignored")
        db.commit()
        return {"ok": True, "ignored": "automatic reply"}
    if not (subject or text):
        _log(db, ch, "rejected", detail="Empty email")
        db.commit()
        raise HTTPException(422, "The email is empty.")
    if _seen(db, ch, mid):
        return {"ok": True, "duplicate": True}

    target: Optional[Ticket] = None
    m = REF.search(subject)
    if m:
        cand = db.get(Ticket, int(m.group(1)))
        target = cand if cand and cand.client_id == ch.client_id else None
    if not target and reply_to:
        link = db.scalar(select(IntakeMessage).where(IntakeMessage.channel_id == ch.id, IntakeMessage.external_id == reply_to[:300]))
        target = db.get(Ticket, link.ticket_id) if link and link.ticket_id else None
    body = text or subject
    try:
        with db.begin_nested():
            if target:
                _append(db, target, f"{name or addr}: {body}", "email")
                t, kind = target, "appended"
            else:
                t, kind = _new_ticket(db, ch, name=name, mobile="", email=addr, subject=subject or "(no subject)", text=body), "created"
            _remember(db, ch, mid, t.id)
            db.flush()
    except IntegrityError:
        return {"ok": True, "duplicate": True}
    _touch(ch)
    _log(db, ch, kind, t.number)
    db.commit()
    return {"ok": True, kind: True, "ticket": t.number}
