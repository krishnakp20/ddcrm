"""Email / SMS / WhatsApp sending.

Each channel is live only when its settings exist in .env (SMTP_HOST, SMS_API_URL, WHATSAPP_API_URL).
Without them the message is stored in the notification log with status "logged", so the whole flow
can be tested before any provider account exists. Every attempt is recorded in the `notifications` table.
"""
import smtplib
from email.message import EmailMessage
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Notification, Setting

DEFAULT_TEMPLATES: dict[str, str] = {
    "welcome_email_subject": "Welcome to DialDesk, {company}",
    "welcome_email_body": (
        "Hello {contact_name},\n\n"
        "Your company {company} is now active on DialDesk CRM (client code {client_code}).\n\n"
        "1. Set your password: {password_link}\n"
        "2. Sign in at: {login_url}\n"
        "   Your login email is {login_email}.\n\n"
        "If you need any help, just reply to this email.\n\n"
        "Team DialDesk"
    ),
    "welcome_sms": "Welcome to DialDesk, {company}! Your account is active. Set your password: {password_link}",
    "welcome_whatsapp": (
        "Hello {contact_name}, welcome to DialDesk! {company} is now active (client code {client_code}). "
        "Set your password here: {password_link} and sign in at {login_url}"
    ),
    "received_email_subject": "We received your DialDesk registration",
    "received_email_body": (
        "Hello {contact_name},\n\nThank you for registering {company} on DialDesk. Our team will review your details "
        "and activate your account shortly. You will receive another message with your login details.\n\nTeam DialDesk"
    ),
    "received_sms": "DialDesk: we received the registration of {company}. We will activate your account shortly.",
    "received_whatsapp": "Hello {contact_name}, thank you for registering {company} on DialDesk. We will review it and activate your account shortly.",
    "user_invite_email_subject": "Your DialDesk login",
    "user_invite_email_body": (
        "Hello {contact_name},\n\nA DialDesk account has been created for you at {company}.\n\n"
        "1. Set your password: {password_link}\n2. Sign in at: {login_url}\n   Your login email is {login_email}.\n\n"
        "The password link works for 7 days.\n\nTeam DialDesk"
    ),
    "user_invite_sms": "DialDesk: your login is ready. Set your password here: {password_link}",
    "user_invite_whatsapp": "Hello {contact_name}, your DialDesk login is ready. Set your password here: {password_link} and sign in at {login_url}",
    "rejected_email_subject": "Your DialDesk registration",
    "rejected_email_body": (
        "Hello {contact_name},\n\nWe could not approve the registration for {company}.\n\nReason: {note}\n\nTeam DialDesk"
    ),
}

EDITABLE_TEMPLATES = [k for k in DEFAULT_TEMPLATES if k.startswith(("welcome_", "received_", "user_invite_"))]


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"  # unknown variables stay visible instead of crashing


def get_templates(db: Session) -> dict[str, str]:
    row = db.get(Setting, "templates")
    return {**DEFAULT_TEMPLATES, **((row.value if row else None) or {})}


def render(text: str, ctx: dict[str, Any]) -> str:
    return text.format_map(_Safe(ctx))


def _send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def _send_http(url: str, key: str, to: str, body: str) -> None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    resp = httpx.post(url, json={"to": to, "message": body}, headers=headers, timeout=10)
    resp.raise_for_status()


def _configured(channel: str) -> bool:
    return bool({"email": settings.SMTP_HOST, "sms": settings.SMS_API_URL, "whatsapp": settings.WHATSAPP_API_URL}[channel])


def send(db: Session, channel: str, to: str, body: str, subject: Optional[str] = None,
         client_id: Optional[int] = None) -> Notification:
    """Sends (or, when the channel is not configured, only records) one message."""
    status, error = "logged", None
    if _configured(channel):
        try:
            if channel == "email":
                _send_email(to, subject or "", body)
            elif channel == "sms":
                _send_http(settings.SMS_API_URL, settings.SMS_API_KEY, to, body)
            else:
                _send_http(settings.WHATSAPP_API_URL, settings.WHATSAPP_API_KEY, to, body)
            status = "sent"
        except Exception as exc:  # a provider outage must never break onboarding
            status, error = "failed", str(exc)[:480]
    note = Notification(channel=channel, recipient=to, subject=subject, body=body, status=status, error=error,
                        client_id=client_id)
    db.add(note)
    db.flush()
    return note


def send_to_contact(db: Session, prefix: str, ctx: dict[str, Any], *, email: Optional[str], mobile: Optional[str],
                    channels: tuple[str, ...] = ("email", "sms", "whatsapp"), client_id: Optional[int] = None) -> list[Notification]:
    """Sends the `prefix` templates (e.g. "welcome") on each requested channel that has a template and a recipient."""
    templates = get_templates(db)
    out = []
    for channel in channels:
        to = email if channel == "email" else (f"+91{mobile}" if mobile else None)
        body_key = f"{prefix}_{channel}_body" if channel == "email" else f"{prefix}_{channel}"
        if not to or body_key not in templates:
            continue
        subject = render(templates[f"{prefix}_email_subject"], ctx) if channel == "email" else None
        out.append(send(db, channel, to, render(templates[body_key], ctx), subject, client_id))
    return out
