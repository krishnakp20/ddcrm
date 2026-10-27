"""Create the first super admin.

    python -m app.seed          # ensure tables + super admin exist
    python -m app.seed --reset  # DROP ALL TABLES first (development only)
"""
import sys

from sqlalchemy import func, select

from .config import settings
from .database import Base, SessionLocal, engine
from .models import AccessRole, User
from .services.access import ensure_system_roles
from .services.forms import ensure_shared_lists
from .security import hash_password


def ensure_admin() -> None:
    with SessionLocal() as db:
        ensure_system_roles(db)
        ensure_shared_lists(db)
        if db.scalar(select(func.count(User.id))):
            return
        role = db.scalar(select(AccessRole).where(AccessRole.key == "super_admin"))
        db.add(
            User(
                name=settings.ADMIN_NAME,
                email=settings.ADMIN_EMAIL.lower(),
                user_type="staff",
                role_id=role.id,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
            )
        )
        db.commit()
        print(f"Created super admin {settings.ADMIN_EMAIL} (change the password after first login)")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        Base.metadata.drop_all(bind=engine)
        print("Dropped all tables")
    Base.metadata.create_all(bind=engine)
    ensure_admin()
