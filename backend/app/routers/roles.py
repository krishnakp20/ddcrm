"""Roles: named bundles of permissions."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of, require_permission
from ..models import AccessRole, User
from ..services import access

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=250)
    user_type: str = Field(pattern="^(staff|client|agent)$")
    permissions: list[str] = []


def role_out(db: Session, r: AccessRole, mine: Optional[set[str]] = None) -> dict:
    users = db.scalar(select(func.count()).select_from(User).where(User.role_id == r.id))
    perms = sorted(access.allowed_for(r.user_type)) if r.is_locked else sorted(r.permissions or [])
    out = {"id": r.id, "key": r.key, "name": r.name, "description": r.description, "user_type": r.user_type,
           "type_label": access.TYPE_LABEL[r.user_type], "permissions": perms, "is_system": r.is_system,
           "is_locked": r.is_locked, "users_count": users}
    if mine is not None:
        # a person can only hand out access they have themselves (super admin: anything)
        out["assignable"] = not r.is_locked and set(perms) <= mine or "*" in mine
    return out


def requester_perms(user: User) -> set[str]:
    """The permissions a person may hand out to others. A locked role (super admin) may hand out anything."""
    return {"*"} if user.role and user.role.is_locked else permissions_of(user)


@router.get("/api/access/permissions")
def permission_catalog(user: User = Depends(get_current_user)):
    if not permissions_of(user) & {"roles.manage", "users.manage", "users.view"}:
        raise HTTPException(403, "You don't have permission for this")
    return {"groups": [{"group": g, "permissions": items} for g, items in access.CATALOG],
            "types": [{"key": k, "label": v} for k, v in access.TYPE_LABEL.items()]}


@router.get("/api/roles")
def list_roles(user_type: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not permissions_of(user) & {"roles.manage", "users.manage", "users.view"}:
        raise HTTPException(403, "You don't have permission for this")
    stmt = select(AccessRole).order_by(AccessRole.user_type, AccessRole.is_system.desc(), AccessRole.name)
    if user_type:
        stmt = stmt.where(AccessRole.user_type == user_type)
    mine = requester_perms(user)
    return [role_out(db, r, mine) for r in db.scalars(stmt)]


def _validated(db: Session, body: RoleIn, skip_id: Optional[int] = None) -> list[str]:
    unknown = [k for k in body.permissions if k not in access.PERMISSIONS]
    if unknown:
        raise HTTPException(422, f"Unknown permission: {unknown[0]}")
    not_allowed = [k for k in body.permissions if body.user_type not in access.PERMISSIONS[k]["types"]]
    if not_allowed:
        raise HTTPException(422, detail={"message": "Some permissions do not apply to this kind of user",
                                         "fields": {"permissions": access.PERMISSIONS[not_allowed[0]]["label"]
                                                    + f" is not available for {access.TYPE_LABEL[body.user_type].lower()}s"}})
    stmt = select(AccessRole.id).where(func.lower(AccessRole.name) == body.name.strip().lower())
    if skip_id:
        stmt = stmt.where(AccessRole.id != skip_id)
    if db.scalar(stmt):
        raise HTTPException(422, detail={"message": "This role already exists", "fields": {"name": "A role with this name already exists"}})
    return access.clean_permissions(body.permissions)


@router.post("/api/roles", status_code=201)
def create_role(body: RoleIn, user: User = Depends(require_permission("roles.manage")), db: Session = Depends(get_db)):
    perms = _validated(db, body)
    key = re.sub(r"[^a-z0-9]+", "_", body.name.strip().lower()).strip("_")[:30] or "role"
    base, n = key, 1
    while db.scalar(select(AccessRole.id).where(AccessRole.key == key)):
        n += 1
        key = f"{base}_{n}"
    role = AccessRole(key=key, name=body.name.strip(), description=body.description, user_type=body.user_type,
                      permissions=perms)
    db.add(role)
    db.flush()
    audit(db, user, "role_created", detail={"role": role.id, "name": role.name})
    db.commit()
    return role_out(db, role)


@router.get("/api/roles/{role_id}")
def get_role(role_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not permissions_of(user) & {"roles.manage", "users.manage", "users.view"}:
        raise HTTPException(403, "You don't have permission for this")
    role = db.get(AccessRole, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    return role_out(db, role)


@router.put("/api/roles/{role_id}")
def update_role(role_id: int, body: RoleIn, user: User = Depends(require_permission("roles.manage")),
                db: Session = Depends(get_db)):
    role = db.get(AccessRole, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_locked:
        raise HTTPException(409, "The super admin role always has every permission and cannot be changed")
    if body.user_type != role.user_type and db.scalar(select(func.count()).select_from(User).where(User.role_id == role.id)):
        raise HTTPException(409, "Users already have this role, so its user type cannot change")
    role.permissions = _validated(db, body, role.id)
    role.name, role.description, role.user_type = body.name.strip(), body.description, body.user_type
    audit(db, user, "role_updated", detail={"role": role.id, "permissions": role.permissions})
    db.commit()
    return role_out(db, role)


@router.delete("/api/roles/{role_id}")
def delete_role(role_id: int, user: User = Depends(require_permission("roles.manage")), db: Session = Depends(get_db)):
    role = db.get(AccessRole, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system:
        raise HTTPException(409, "Built-in roles cannot be deleted")
    n = db.scalar(select(func.count()).select_from(User).where(User.role_id == role.id))
    if n:
        raise HTTPException(409, f"{n} user(s) have this role. Give them another role first.")
    audit(db, user, "role_deleted", detail={"name": role.name})
    db.delete(role)
    db.commit()
    return {"ok": True}
