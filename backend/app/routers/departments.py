"""Department master. A department belongs to DialDesk (client_id empty) or to one client."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import Client, Department, User
from ..services import onboarding as ob

router = APIRouter(prefix="/api/departments", tags=["departments"])


class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=250)
    client_id: Optional[int] = None  # staff only; client users always create for their own company
    is_active: bool = True


def _is_staff(u: User) -> bool:
    return u.user_type == "staff"


def _can_view(u: User) -> bool:
    return bool(permissions_of(u) & {"users.view", "users.manage", "departments.manage"})


def _out(db: Session, d: Department) -> dict:
    users = db.scalar(select(func.count()).select_from(User).where(User.department_id == d.id))
    client = db.get(Client, d.client_id) if d.client_id else None
    return {"id": d.id, "name": d.name, "description": d.description, "is_active": d.is_active,
            "client_id": d.client_id, "scope": client.company_name if client else "DialDesk", "users_count": users}


def _scope_client(user: User, requested: Optional[int]) -> Optional[int]:
    """Staff may choose any scope; a client user is always limited to their own company."""
    return requested if _is_staff(user) else user.client_id


def _clash(db: Session, client_id: Optional[int], name: str, skip: Optional[int] = None) -> None:
    stmt = select(Department.id).where(func.lower(Department.name) == name.lower())
    stmt = stmt.where(Department.client_id.is_(None) if client_id is None else Department.client_id == client_id)
    if skip:
        stmt = stmt.where(Department.id != skip)
    if db.scalar(stmt):
        raise HTTPException(422, detail={"message": "This department already exists", "fields": {"name": "A department with this name already exists"}})


def _get_for(db: Session, user: User, dept_id: int) -> Department:
    d = db.get(Department, dept_id)
    if not d or (not _is_staff(user) and d.client_id != user.client_id):
        raise HTTPException(404, "Department not found")  # 404, not 403, so other companies' ids are not revealed
    return d


@router.get("")
def list_departments(client_id: Optional[str] = None, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """client_id: a number for one client, 'dialdesk' for DialDesk's own, empty for everything (staff only)."""
    if not _can_view(user):
        raise HTTPException(403, "You don't have permission for this")
    stmt = select(Department)
    if not _is_staff(user):
        stmt = stmt.where(Department.client_id == user.client_id)
    elif client_id == "dialdesk":
        stmt = stmt.where(Department.client_id.is_(None))
    elif client_id:
        stmt = stmt.where(Department.client_id == int(client_id))
    return [_out(db, d) for d in db.scalars(stmt.order_by(Department.client_id.is_not(None), Department.name))]


@router.post("", status_code=201)
def create_department(body: DepartmentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if "departments.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    client_id = _scope_client(user, body.client_id)
    if client_id and not db.get(Client, client_id):
        raise HTTPException(422, "Client not found")
    name = " ".join(body.name.split())
    _clash(db, client_id, name)
    d = Department(name=name, description=body.description, client_id=client_id, is_active=body.is_active)
    db.add(d)
    db.flush()
    audit(db, user, "department_created", client_id=client_id, detail={"department": d.id, "name": name})
    db.commit()
    return _out(db, d)


@router.put("/{dept_id}")
def update_department(dept_id: int, body: DepartmentIn, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    if "departments.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    d = _get_for(db, user, dept_id)
    name = " ".join(body.name.split())
    _clash(db, d.client_id, name, d.id)
    d.name, d.description, d.is_active = name, body.description, body.is_active
    audit(db, user, "department_updated", client_id=d.client_id, detail={"department": d.id})
    db.commit()
    return _out(db, d)


@router.delete("/{dept_id}")
def delete_department(dept_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if "departments.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    d = _get_for(db, user, dept_id)
    n = db.scalar(select(func.count()).select_from(User).where(User.department_id == d.id))
    if n:
        raise HTTPException(409, f"{n} user(s) are in this department. Move them first, or switch the department off instead.")
    audit(db, user, "department_deleted", client_id=d.client_id, detail={"name": d.name})
    db.delete(d)
    db.commit()
    return {"ok": True}
