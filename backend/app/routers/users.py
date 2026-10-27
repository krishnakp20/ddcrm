"""Users: DialDesk admin users, client users and agents."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import AccessRole, Client, Department, PasswordToken, User
from ..security import hash_password
from ..services import access, india, notify
from ..services.tokens import hash_token, new_token
from .roles import requester_perms, role_out

router = APIRouter(prefix="/api/users", tags=["users"])


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    user_type: str = Field(pattern="^(staff|client|agent)$")
    role_id: int
    department_id: Optional[int] = None
    client_id: Optional[int] = None
    dialer_agent_id: Optional[str] = Field(default=None, max_length=60)
    extra_permissions: list[str] = []
    denied_permissions: list[str] = []
    is_active: bool = True
    send_invite: bool = True


def fail(fields: dict[str, str], message: str = "Please fix the highlighted fields") -> None:
    raise HTTPException(422, detail={"message": message, "fields": fields})


def is_staff(u: User) -> bool:
    return u.user_type == "staff"


def status_of(u: User) -> str:
    if not u.is_active:
        return "disabled"
    return "invited" if u.invited_at and not u.password_set_at else "active"


def user_out(u: User, detail: bool = False) -> dict[str, Any]:
    out = {
        "id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "user_type": u.user_type,
        "type_label": access.TYPE_LABEL.get(u.user_type, u.user_type), "is_active": u.is_active, "status": status_of(u),
        "role": {"id": u.role.id, "key": u.role.key, "name": u.role.name} if u.role else None,
        "department": {"id": u.department.id, "name": u.department.name} if u.department else None,
        "client": {"id": u.client.id, "name": u.client.company_name} if u.client else None,
        "dialer_agent_id": u.dialer_agent_id, "created_at": u.created_at,
    }
    if detail:
        eff = access.effective_permissions(u)
        out.update({"extra_permissions": u.extra_permissions or [], "denied_permissions": u.denied_permissions or [],
                    "effective_permissions": sorted(eff),
                    "role_permissions": sorted(access.allowed_for(u.user_type) if (u.role and u.role.is_locked)
                                               else (u.role.permissions if u.role else []))})
    return out


def _visible(requester: User, target: User) -> bool:
    return is_staff(requester) or (requester.client_id is not None and target.client_id == requester.client_id
                                   and target.user_type != "staff")


def _get_visible(db: Session, requester: User, user_id: int) -> User:
    target = db.get(User, user_id)
    if not target or not _visible(requester, target):
        raise HTTPException(404, "User not found")  # same answer for "missing" and "someone else's"
    return target


def _need(requester: User, perm: str) -> None:
    if perm not in permissions_of(requester):
        raise HTTPException(403, "You don't have permission for this")


# ---------- helpers for the add / edit form ----------

@router.get("/meta")
def meta(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the add/edit form needs, limited to what this person is allowed to hand out."""
    _need(user, "users.view")
    mine = requester_perms(user)
    types = list(access.USER_TYPES) if is_staff(user) else ["client", "agent"]
    roles = [role_out(db, r, mine) for r in db.scalars(select(AccessRole).order_by(AccessRole.user_type, AccessRole.name))
             if r.user_type in types]
    dstmt = select(Department).where(Department.is_active.is_(True))
    if not is_staff(user):
        dstmt = dstmt.where(Department.client_id == user.client_id)
    clients = []
    if is_staff(user):
        clients = [{"id": c.id, "name": c.company_name, "code": c.code}
                   for c in db.scalars(select(Client).where(Client.status.in_(("active", "suspended"))).order_by(Client.company_name))]
    return {"types": [{"key": t, "label": access.TYPE_LABEL[t]} for t in types], "roles": roles, "clients": clients,
            "departments": [{"id": d.id, "name": d.name, "client_id": d.client_id} for d in db.scalars(dstmt.order_by(Department.name))],
            "own_client_id": user.client_id,
            "catalog": [{"group": g, "permissions": items} for g, items in access.CATALOG],
            "my_permissions": sorted(access.allowed_for("staff")) if "*" in mine else sorted(mine)}


# ---------- list / detail ----------

@router.get("")
def list_users(type: Optional[str] = None, client_id: Optional[int] = None, department_id: Optional[int] = None,
               status: Optional[str] = None, q: Optional[str] = None, page: int = Query(1, ge=1),
               page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _need(user, "users.view")
    stmt = select(User)
    if not is_staff(user):
        stmt = stmt.where(User.client_id == user.client_id, User.user_type != "staff")
    elif client_id:
        stmt = stmt.where(User.client_id == client_id)
    if type:
        stmt = stmt.where(User.user_type == type)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if status == "disabled":
        stmt = stmt.where(User.is_active.is_(False))
    elif status == "invited":
        stmt = stmt.where(User.is_active.is_(True), User.invited_at.is_not(None), User.password_set_at.is_(None))
    elif status == "active":
        stmt = stmt.where(User.is_active.is_(True), or_(User.invited_at.is_(None), User.password_set_at.is_not(None)))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like),
                              User.dialer_agent_id.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "page_size": page_size, "items": [user_out(u) for u in rows]}


@router.get("/{user_id}")
def get_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "users.view")
    return user_out(_get_visible(db, user, user_id), detail=True)


# ---------- create / update ----------

def _validate(db: Session, requester: User, body: UserIn, target: Optional[User]) -> tuple[AccessRole, Optional[int], str]:
    """Checks a create/update request. Returns (role, client_id, normalised email) or raises 422/403."""
    errors: dict[str, str] = {}
    # --- who may create what
    if not is_staff(requester) and body.user_type == "staff":
        raise HTTPException(403, "You cannot add DialDesk admin users")
    client_id = body.client_id if is_staff(requester) else requester.client_id
    if body.user_type == "staff":
        client_id = None
    elif body.user_type == "client" and not client_id:
        errors["client_id"] = "Choose the client this user belongs to"
    if client_id and not db.get(Client, client_id):
        errors["client_id"] = "Client not found"

    email = body.email.strip().lower()
    if not india.EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email"
    elif db.scalar(select(User.id).where(User.email == email, User.id != (target.id if target else 0))):
        errors["email"] = "A user with this email already exists"
    if body.phone:
        mobile = india.normalize_mobile(body.phone)
        if not india.valid_mobile(mobile):
            errors["phone"] = "Enter a valid 10-digit mobile number"
    if body.dialer_agent_id:
        if body.user_type != "agent":
            errors["dialer_agent_id"] = "Only agents have a dialer agent ID"
        elif db.scalar(select(User.id).where(User.dialer_agent_id == body.dialer_agent_id.strip(),
                                             User.id != (target.id if target else 0))):
            errors["dialer_agent_id"] = "This dialer agent ID is already used by another user"

    # --- role
    role = db.get(AccessRole, body.role_id)
    if not role:
        errors["role_id"] = "Choose a role"
    elif role.user_type != body.user_type:
        errors["role_id"] = f"This role is for {access.TYPE_LABEL[role.user_type].lower()}s, not {access.TYPE_LABEL[body.user_type].lower()}s"

    # --- department must be in the same scope as the user
    if body.department_id:
        dept = db.get(Department, body.department_id)
        unchanged = target is not None and target.department_id == body.department_id  # keeping an old choice is fine
        if not dept or (not dept.is_active and not unchanged):
            errors["department_id"] = "Choose an active department"
        elif dept.client_id != client_id:
            errors["department_id"] = "This department belongs to a different company"

    # --- permission overrides: valid, applicable to the kind of user, and not more than the requester has
    allowed = access.allowed_for(body.user_type)
    mine = requester_perms(requester)
    for key in body.extra_permissions + body.denied_permissions:
        if key not in access.PERMISSIONS:
            errors["permissions"] = f"Unknown permission: {key}"
    if "permissions" not in errors:
        bad = [k for k in body.extra_permissions if k not in allowed]
        if bad:
            errors["permissions"] = f"“{access.PERMISSIONS[bad[0]]['label']}” does not apply to this kind of user"
    if "*" not in mine:
        if role and not role.is_locked and not set(role.permissions or []) <= mine and (not target or target.role_id != role.id):
            errors["role_id"] = "You cannot give a role with more access than you have"
        if role and role.is_locked:
            errors["role_id"] = "Only a super admin can give the super admin role"
        over = [k for k in body.extra_permissions if k not in mine and k not in (target.extra_permissions if target else [])]
        if over:
            errors["permissions"] = f"You cannot grant “{access.PERMISSIONS[over[0]]['label']}” because you do not have it"
    if errors:
        fail(errors)
    return role, client_id, email


def _invite(db: Session, u: User) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Creates a 7-day password link and sends it by email, SMS and WhatsApp."""
    token = new_token()
    db.add(PasswordToken(user_id=u.id, token_hash=hash_token(token),
                         expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    company = u.client.company_name if u.client else "DialDesk"
    mobile = india.normalize_mobile(u.phone) if u.phone else None
    sent = notify.send_to_contact(
        db, "user_invite",
        {"company": company, "contact_name": u.name.split()[0], "login_url": f"{settings.APP_BASE_URL}/login",
         "login_email": u.email, "password_link": f"{settings.APP_BASE_URL}/set-password/{token}"},
        email=u.email, mobile=mobile, client_id=u.client_id)
    u.invited_at = datetime.now(timezone.utc)
    # While no email / SMS / WhatsApp provider is connected nothing is really delivered, so the admin gets the
    # link to pass on. Once any message is actually sent, the link is never shown.
    link = None if any(n.status == "sent" for n in sent) else f"{settings.APP_BASE_URL}/set-password/{token}"
    return [{"channel": n.channel, "to": n.recipient, "status": n.status, "error": n.error} for n in sent], link


@router.post("", status_code=201)
def create_user(body: UserIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "users.manage")
    role, client_id, email = _validate(db, user, body, None)
    u = User(name=" ".join(body.name.split()), email=email, phone=india.normalize_mobile(body.phone) if body.phone else None,
             user_type=body.user_type, role_id=role.id, department_id=body.department_id, client_id=client_id,
             dialer_agent_id=(body.dialer_agent_id or "").strip() or None,
             extra_permissions=access.clean_permissions(body.extra_permissions),
             denied_permissions=access.clean_permissions(body.denied_permissions), is_active=body.is_active,
             created_by_id=user.id,
             # unusable until the person sets their own password through the emailed link
             hashed_password=hash_password(secrets.token_urlsafe(24)))
    db.add(u)
    db.flush()
    db.refresh(u)
    sent, link = _invite(db, u) if body.send_invite else ([], None)
    audit(db, user, "user_created", client_id=client_id, detail={"user": u.id, "type": u.user_type, "role": role.key})
    db.commit()
    return {**user_out(u, detail=True), "invitation": sent, "link": link}


def _last_super_admin_guard(db: Session, target: User, will_stay_super: bool) -> None:
    """The system must never be left without an active super admin."""
    if target.role and target.role.is_locked and target.is_active and not will_stay_super:
        others = db.scalar(select(func.count()).select_from(User).join(AccessRole, AccessRole.id == User.role_id)
                           .where(AccessRole.is_locked.is_(True), User.is_active.is_(True), User.id != target.id))
        if not others:
            raise HTTPException(409, "This is the last active super admin. Make another super admin first.")


@router.put("/{user_id}")
def update_user(user_id: int, body: UserIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user, "users.manage")
    target = _get_visible(db, user, user_id)
    if user.id == target.id:
        raise HTTPException(409, "You cannot change your own role, permissions or status. Ask another administrator.")
    if target.role and target.role.is_locked and not (user.role and user.role.is_locked):
        raise HTTPException(403, "Only a super admin can change a super admin")
    if body.user_type != target.user_type:
        raise HTTPException(409, "A user's type cannot be changed. Add a new user instead.")
    # the email is the login; it can be corrected only until the person has set a password
    if body.email.strip().lower() != target.email and target.password_set_at:
        raise HTTPException(409, "The email is this person's login and cannot be changed once they have signed up.")
    role, client_id, email = _validate(db, user, body, target)
    if client_id != target.client_id:
        raise HTTPException(409, "A user cannot be moved to another company")
    stays_super = role.is_locked and body.is_active
    _last_super_admin_guard(db, target, stays_super)
    target.name, target.email = " ".join(body.name.split()), email
    target.phone = india.normalize_mobile(body.phone) if body.phone else None
    target.role_id, target.department_id = role.id, body.department_id
    target.dialer_agent_id = (body.dialer_agent_id or "").strip() or None
    target.extra_permissions = access.clean_permissions(body.extra_permissions)
    target.denied_permissions = access.clean_permissions(body.denied_permissions)
    target.is_active = body.is_active
    audit(db, user, "user_updated", client_id=target.client_id, detail={"user": target.id, "role": role.key})
    db.commit()
    db.refresh(target)
    return user_out(target, detail=True)


@router.post("/{user_id}/send-password-link")
def send_password_link(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sends a fresh set-password link: used to invite again or to reset a forgotten password."""
    _need(user, "users.manage")
    target = _get_visible(db, user, user_id)
    if not target.is_active:
        raise HTTPException(409, "Activate the user first")
    sent, link = _invite(db, target)
    audit(db, user, "password_link_sent", client_id=target.client_id, detail={"user": target.id})
    db.commit()
    return {"invitation": sent, "link": link}
