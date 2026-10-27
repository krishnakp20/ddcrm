from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditLog, User
from .services.access import effective_permissions
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    user_id = decode_access_token(token)
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def permissions_of(user: User) -> set[str]:
    return effective_permissions(user)


def require_permission(*needed: str):
    """Allows the request when the user holds at least one of the listed permissions."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not (permissions_of(user) & set(needed)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission for this")
        return user

    return checker


def audit(db: Session, user: User | None, action: str, client_id: int | None = None, detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, client_id=client_id, action=action, detail=detail or {}))
