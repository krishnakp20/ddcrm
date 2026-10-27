"""Endpoints that need no login: form options, the short self-registration, and company logos."""
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit, permissions_of
from ..models import Client, User
from ..schemas import BasicRegistration
from ..services import india, notify, onboarding as ob

router = APIRouter(prefix="/api/public", tags=["public"])

# Simple in-memory limit: 5 registrations per hour per address. Use a shared store (Redis) if you run several servers.
_attempts: dict[str, list[float]] = {}
MAX_PER_HOUR = 5


def _rate_limit(ip: str) -> None:
    now = time.time()
    recent = [t for t in _attempts.get(ip, []) if now - t < 3600]
    if len(recent) >= MAX_PER_HOUR:
        raise HTTPException(429, "Too many registrations from this connection. Please try again later.")
    _attempts[ip] = recent + [now]


@router.get("/meta")
def meta():
    return {
        "states": india.STATES, "gst_codes": india.GST_STATES, "doc_types": ob.DOC_TYPES, "services": ob.SERVICES,
        "volumes": ob.VOLUMES, "business_types": ob.BUSINESS_TYPES, "terms_version": ob.TERMS_VERSION,
        "limits": {"doc_mb": ob.MAX_DOC_BYTES // 1048576, "logo_mb": ob.MAX_LOGO_BYTES // 1048576},
    }


@router.post("/register", status_code=201)
def register(body: BasicRegistration, request: Request, db: Session = Depends(get_db)):
    """Self-registration from the login page. Only the basics; the client completes the profile after activation."""
    if body.website.strip():
        # a bot filled the hidden field: pretend it worked and store nothing
        return {"ok": True}
    ip = request.client.host if request.client else "unknown"
    _rate_limit(ip)
    if not body.terms_accepted:
        ob.fail({"terms": "Please accept the Terms & Conditions"})
    client = ob.create_basic_client(db, body, source="self")
    db.flush()  # session autoflush is off: write the contact before refreshing, or it would be dropped
    db.refresh(client)
    client.terms_version = ob.TERMS_VERSION
    client.terms_accepted_at = client.submitted_at = client.created_at
    client.terms_ip = ip
    contact = client.contacts[0]
    audit(db, None, "client_registered", client_id=client.id)
    # acknowledge to the registrant, and tell every super admin that a registration is waiting
    notify.send_to_contact(db, "received", {"company": client.company_name, "contact_name": contact.name},
                           email=contact.email, mobile=contact.mobile, client_id=client.id)
    staff = db.scalars(select(User).where(User.user_type == "staff", User.is_active.is_(True)))
    for admin in (u for u in staff if "clients.manage" in permissions_of(u)):
        notify.send(db, "email", admin.email,
                    f"{client.company_name} has registered and is waiting for review: "
                    f"{settings.APP_BASE_URL}/clients/{client.id}", "New client registration to review", client.id)
    db.commit()
    return {"ok": True}


@router.get("/logo/{key}")
def logo(key: str, db: Session = Depends(get_db)):
    """Company logos are shown to the client's own users after login, so they are served without a token."""
    client = db.scalar(select(Client).where(Client.logo_key == key))
    if not client or not client.logo_file:
        raise HTTPException(404, "Not found")
    path = Path(ob.client_dir(client.id)) / client.logo_file
    if not path.exists():
        raise HTTPException(404, "Not found")
    mime = ob.LOGO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=3600"})
