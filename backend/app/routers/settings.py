from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as cfg
from ..database import get_db
from ..deps import audit, require_permission
from ..models import Notification, Setting, User
from ..schemas import TemplatesIn
from ..services import notify

router = APIRouter(prefix="/api/settings", tags=["settings"])
admin_only = require_permission("settings.manage")


@router.get("/templates")
def get_templates(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    current = notify.get_templates(db)
    return {"templates": {k: current[k] for k in notify.EDITABLE_TEMPLATES},
            "defaults": {k: notify.DEFAULT_TEMPLATES[k] for k in notify.EDITABLE_TEMPLATES},
            "variables": ["company", "contact_name", "client_code", "login_url", "login_email", "password_link"]}


@router.put("/templates")
def save_templates(body: TemplatesIn, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    clean = {k: v for k, v in body.templates.items() if k in notify.EDITABLE_TEMPLATES and v.strip()}
    row = db.get(Setting, "templates")
    if row:
        row.value = clean
    else:
        db.add(Setting(key="templates", value=clean))
    audit(db, user, "templates_saved")
    db.commit()
    return {"ok": True}


@router.get("/channels")
def channels(user: User = Depends(admin_only)):
    """Which providers are configured. A channel that is not configured only logs its messages."""
    return {"email": bool(cfg.SMTP_HOST), "sms": bool(cfg.SMS_API_URL), "whatsapp": bool(cfg.WHATSAPP_API_URL)}


@router.get("/notifications")
def notifications(channel: Optional[str] = None, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(Notification).order_by(Notification.id.desc()).limit(100)
    if channel:
        stmt = stmt.where(Notification.channel == channel)
    return [{"id": n.id, "channel": n.channel, "recipient": n.recipient, "subject": n.subject, "body": n.body,
             "status": n.status, "error": n.error, "client_id": n.client_id, "created_at": n.created_at}
            for n in db.scalars(stmt)]
