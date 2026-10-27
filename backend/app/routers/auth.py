from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, permissions_of
from ..models import PasswordToken, User
from ..schemas import SetPasswordIn, Token
from ..security import create_access_token, hash_password, verify_password
from ..services.onboarding import logo_url, profile_status
from ..services.tokens import hash_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.strip().lower()))
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is disabled. Please contact DialDesk support.")
    return Token(access_token=create_access_token(user.id))


def me_payload(user: User) -> dict:
    c = user.client
    return {
        "id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "is_active": user.is_active,
        "user_type": user.user_type, "role": user.role_key, "role_name": user.role.name if user.role else None,
        "department": user.department.name if user.department else None,
        "permissions": sorted(permissions_of(user)),
        "client": {"id": c.id, "name": c.company_name, "code": c.code, "logo_url": logo_url(c),
                   "profile_percent": profile_status(c)["percent"]} if c else None,
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return me_payload(user)


def _valid_token(db: Session, token: str) -> PasswordToken:
    row = db.scalar(select(PasswordToken).where(PasswordToken.token_hash == hash_token(token)))
    if not row or row.used_at or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, "This link has expired or was already used. Ask your administrator for a new one.")
    return row


@router.get("/set-password/{token}")
def check_token(token: str, db: Session = Depends(get_db)):
    user = db.get(User, _valid_token(db, token).user_id)
    return {"name": user.name, "email": user.email}


@router.post("/set-password")
def set_password(body: SetPasswordIn, db: Session = Depends(get_db)):
    row = _valid_token(db, body.token)
    user = db.get(User, row.user_id)
    user.hashed_password = hash_password(body.password)
    user.password_set_at = row.used_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "email": user.email}
