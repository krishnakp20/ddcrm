"""Super-admin endpoints: create, review and activate clients."""
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit, require_permission
from ..models import CLIENT_STATUSES, AccessRole, Client, ClientContact, PasswordToken, PlanAssignment, User
from ..schemas import BasicRegistration, DocReviewIn, NoteIn, OnboardingData
from ..security import hash_password
from ..services import notify, onboarding as ob
from ..services import plans as plan_service
from ..services.tokens import hash_token, new_token

router = APIRouter(prefix="/api/clients", tags=["clients"])
view_clients = require_permission("clients.view")
manage_clients = require_permission("clients.manage")
review_clients = require_permission("clients.review")


def _get(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client


def _primary(client: Client) -> Optional[ClientContact]:
    return client.contacts[0] if client.contacts else None


def _ctx(client: Client, **extra) -> dict:
    p = _primary(client)
    return {"company": client.company_name, "contact_name": p.name if p else "there", "client_code": client.code or "",
            "login_url": f"{settings.APP_BASE_URL}/login", "login_email": p.email if p else "", **extra}


# ---------- list / detail ----------

@router.get("")
def list_clients(status: Optional[str] = None, q: Optional[str] = None, user: User = Depends(view_clients),
                 db: Session = Depends(get_db)):
    stmt = select(Client)
    if status:
        stmt = stmt.where(Client.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Client.company_name.ilike(like), Client.gstin.ilike(like), Client.code.ilike(like)))
    counts = dict(db.execute(select(Client.status, func.count()).group_by(Client.status)).all())
    clients = list(db.scalars(stmt.order_by(Client.id.desc()).limit(500)))
    # the plan each client is on today (and the next change, if any)
    by_client: dict[int, list] = {}
    for a in db.scalars(select(PlanAssignment).where(PlanAssignment.client_id.in_([c.id for c in clients] or [0]))):
        by_client.setdefault(a.client_id, []).append(a)
    today = plan_service.today()
    items = []
    for c in clients:
        p = _primary(c)
        rows = plan_service.timeline(by_client.get(c.id, []), today)["rows"]
        current = next((r for r in reversed(rows) if r["state"] == "current"), None)
        upcoming = next((r for r in rows if r["state"] == "upcoming"), None)
        items.append({"id": c.id, "code": c.code, "status": c.status, "company_name": c.company_name,
                      "gstin": c.gstin, "city": c.city, "state": c.state, "logo_url": ob.logo_url(c),
                      "contact_name": p.name if p else None, "contact_mobile": p.mobile if p else None,
                      "contact_email": p.email if p else None, "docs": len(c.documents),
                      "pending_docs": sum(1 for d in c.documents if d.status == "pending"),
                      "profile_percent": ob.profile_status(c)["percent"], "source": c.source,
                      "plan_name": current["assignment"].plan.name if current else None,
                      "plan_from": current["assignment"].effective_from if current else None,
                      "next_plan": upcoming["assignment"].plan.name if upcoming else None,
                      "next_plan_from": upcoming["assignment"].effective_from if upcoming else None,
                      "submitted_at": c.submitted_at, "created_at": c.created_at})
    return {"items": items, "counts": {s: counts.get(s, 0) for s in CLIENT_STATUSES}}


@router.get("/{client_id}")
def detail(client_id: int, user: User = Depends(view_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    users = db.scalars(select(User).where(User.client_id == client.id))
    return {**ob.client_out(client), "users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role_key,
                                                "is_active": u.is_active} for u in users]}


@router.post("", status_code=201)
def create_client(body: BasicRegistration, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    """The admin adds a client directly with the basic details; optionally activates it right away."""
    client = ob.create_basic_client(db, body, source="admin")
    audit(db, user, "client_created", client_id=client.id)
    welcome = []
    if body.activate_now:
        welcome = _activate(db, client, user)
    db.commit()
    return {"id": client.id, "status": client.status, "welcome": welcome}


# ---------- editing on behalf of the client ----------

@router.put("/{client_id}/onboarding")
def admin_save(client_id: int, data: OnboardingData, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    old_email = _primary(client).email if _primary(client) else None
    ob.save_form(db, client, data)
    new = _primary(client)
    if old_email and new and new.email != old_email:
        # the primary contact's email is the login; keep the account in step
        account = db.scalar(select(User).where(User.client_id == client.id, User.email == old_email))
        if account:
            account.email = new.email
    audit(db, user, "client_edited", client_id=client.id)
    db.commit()
    return ob.client_out(client)


@router.post("/{client_id}/documents", status_code=201)
async def admin_upload(client_id: int, doc_type: str = Form(...), file: UploadFile = File(...),
                       user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    await ob.add_document(db, client, doc_type, file)
    db.commit()
    return ob.client_out(client)


@router.delete("/{client_id}/documents/{doc_id}")
def admin_delete_doc(client_id: int, doc_id: int, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    ob.remove_document(db, client, doc_id)
    db.commit()
    return ob.client_out(client)


@router.post("/{client_id}/logo")
async def admin_logo(client_id: int, file: UploadFile = File(...), user: User = Depends(manage_clients),
                     db: Session = Depends(get_db)):
    client = _get(db, client_id)
    await ob.set_logo(db, client, file)
    db.commit()
    return ob.client_out(client)


@router.get("/{client_id}/documents/{doc_id}/file")
def download(client_id: int, doc_id: int, user: User = Depends(view_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    doc = next((d for d in client.documents if d.id == doc_id), None)
    path = Path(ob.client_dir(client.id)) / doc.stored_name if doc else None
    if not doc or not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type=doc.content_type, filename=doc.original_name,
                        content_disposition_type="inline")


# ---------- review decisions ----------

@router.put("/{client_id}/documents/{doc_id}/review")
def review_doc(client_id: int, doc_id: int, body: DocReviewIn, user: User = Depends(review_clients),
               db: Session = Depends(get_db)):
    client = _get(db, client_id)
    doc = next((d for d in client.documents if d.id == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.status, doc.review_note = body.status, body.note
    audit(db, user, "document_reviewed", client_id=client.id, detail={"doc": doc.id, "status": body.status})
    db.commit()
    return ob.client_out(client)


@router.post("/{client_id}/reject")
def reject(client_id: int, body: NoteIn, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    if client.status != "submitted":
        raise HTTPException(409, "Only a registration waiting for review can be rejected")
    client.status, client.review_note = "rejected", body.note.strip()
    p = _primary(client)
    notify.send_to_contact(db, "rejected", {**_ctx(client), "note": client.review_note},
                           email=p.email if p else None, mobile=None, channels=("email",), client_id=client.id)
    audit(db, user, "client_rejected", client_id=client.id, detail={"note": body.note})
    db.commit()
    return ob.client_out(client)


# ---------- activation ----------

def _send_welcome(db: Session, client: Client, account: User) -> list[dict]:
    token = new_token()
    db.add(PasswordToken(user_id=account.id, token_hash=hash_token(token),
                         expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    p = _primary(client)
    sent = notify.send_to_contact(
        db, "welcome", {**_ctx(client), "password_link": f"{settings.APP_BASE_URL}/set-password/{token}"},
        email=p.email if p else None, mobile=p.mobile if p else None, client_id=client.id)
    return [{"channel": n.channel, "to": n.recipient, "status": n.status, "error": n.error} for n in sent]


def _activate(db: Session, client: Client, admin: User) -> list[dict]:
    """Creates the client's administrator login, marks the client active and sends the welcome message."""
    p = _primary(client)
    if not p:
        raise HTTPException(422, "The client has no contact person")
    account = db.scalar(select(User).where(User.email == p.email))
    if account and account.client_id != client.id:
        raise HTTPException(409, f"{p.email} already belongs to another account; change the contact's email first")
    if not account:
        role = db.scalar(select(AccessRole).where(AccessRole.key == "client_admin"))
        account = User(name=p.name, email=p.email, phone=p.mobile, user_type="client", role_id=role.id if role else None,
                       client_id=client.id, invited_at=datetime.now(timezone.utc),
                       # unusable until the contact sets their own password through the emailed link
                       hashed_password=hash_password(secrets.token_urlsafe(24)))
        db.add(account)
        db.flush()
    client.status, client.activated_at, client.review_note = "active", datetime.now(timezone.utc), None
    if not client.code:
        # next free number, so codes run CL0001, CL0002 ... without gaps
        last = db.scalar(select(func.max(Client.code)))
        client.code = f"CL{int(last[2:]) + 1 if last else 1:04d}"
    sent = _send_welcome(db, client, account)
    audit(db, admin, "client_activated", client_id=client.id)
    return sent


@router.post("/{client_id}/activate")
def activate(client_id: int, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    if client.status != "submitted":
        raise HTTPException(409, "Only a registration waiting for review can be activated")
    sent = _activate(db, client, user)
    db.commit()
    return {"client": ob.client_out(client), "welcome": sent}


@router.post("/{client_id}/resend-welcome")
def resend_welcome(client_id: int, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    p = _primary(client)
    account = db.scalar(select(User).where(User.client_id == client.id, User.email == (p.email if p else "")))
    if client.status != "active" or not account:
        raise HTTPException(409, "The client must be active")
    sent = _send_welcome(db, client, account)
    db.commit()
    return {"welcome": sent}


@router.post("/{client_id}/suspend")
def suspend(client_id: int, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    if client.status != "active":
        raise HTTPException(409, "Only an active client can be suspended")
    client.status = "suspended"
    for u in db.scalars(select(User).where(User.client_id == client.id)):
        u.is_active = False  # signs everyone from this client out on their next request
    audit(db, user, "client_suspended", client_id=client.id)
    db.commit()
    return ob.client_out(client)


@router.post("/{client_id}/reactivate")
def reactivate(client_id: int, user: User = Depends(manage_clients), db: Session = Depends(get_db)):
    client = _get(db, client_id)
    if client.status != "suspended":
        raise HTTPException(409, "Only a suspended client can be re-activated")
    client.status = "active"
    for u in db.scalars(select(User).where(User.client_id == client.id)):
        u.is_active = True
    audit(db, user, "client_reactivated", client_id=client.id)
    db.commit()
    return ob.client_out(client)
