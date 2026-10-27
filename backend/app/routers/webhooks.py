"""Client webhook: a client posts calling data to a campaign; the same data can be forwarded to the dialer."""
import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import Campaign, DialerId, Lead, User, WebhookEndpoint, WebhookLog
from ..routers.campaigns import _get
from ..services import delivery as dv
from ..services import leads as ls

router = APIRouter(tags=["webhook"])
MAX_PER_CALL = 500
RATE = 60            # calls per minute per key
_hits: dict[str, deque] = defaultdict(deque)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _manage(db: Session, user: User, campaign_id: int) -> Campaign:
    if "alerts.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    return _get(db, user, campaign_id)


def _out(db: Session, ep: Optional[WebhookEndpoint], campaign: Campaign) -> dict[str, Any]:
    logs = db.scalars(select(WebhookLog).where(WebhookLog.campaign_id == campaign.id).order_by(WebhookLog.id.desc()).limit(15))
    ids = list(db.scalars(select(DialerId.value).where(DialerId.campaign_id == campaign.id, DialerId.kind == "campaign", DialerId.is_active.is_(True))))
    return {
        "exists": ep is not None, "is_active": bool(ep and ep.is_active), "token_hint": ep.token_hint if ep else None,
        "dialer_url": ep.dialer_url if ep else None, "dialer_auth_set": bool(ep and ep.dialer_auth),
        "last_used_at": ep.last_used_at if ep else None, "accepted_total": ep.accepted_total if ep else 0,
        "dialer_campaign_ids": ids, "base_url": settings.APP_BASE_URL.rstrip("/"),
        "logs": [{"id": l.id, "source": l.source, "received": l.received, "accepted": l.accepted, "duplicates": l.duplicates,
                  "invalid": l.invalid, "dialer_status": l.dialer_status, "created_at": l.created_at} for l in logs],
    }


# ---------- setup (admin screens) ----------

@router.get("/api/campaigns/{campaign_id}/webhook")
def get_webhook(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _manage(db, user, campaign_id)
    return _out(db, db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.campaign_id == c.id)), c)


@router.post("/api/campaigns/{campaign_id}/webhook/key")
def new_key(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Creates the key, or replaces it (the old one stops working at once). The key is shown only this once."""
    c = _manage(db, user, campaign_id)
    token = secrets.token_urlsafe(24)
    ep = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.campaign_id == c.id))
    if ep:
        ep.token_hash, ep.token_hint, ep.is_active = _hash(token), token[:6], True
    else:
        ep = WebhookEndpoint(campaign_id=c.id, client_id=c.client_id, token_hash=_hash(token), token_hint=token[:6])
        db.add(ep)
    audit(db, user, "webhook_key_created", client_id=c.client_id, detail={"campaign": c.id})
    db.commit()
    return {**_out(db, ep, c), "token": token, "url": f"{settings.APP_BASE_URL.rstrip('/')}/api/hooks/leads/{token}"}


class WebhookIn(BaseModel):
    is_active: Optional[bool] = None
    dialer_url: Optional[str] = Field(default=None, max_length=500)
    dialer_auth: Optional[str] = Field(default=None, max_length=300)
    clear_dialer_auth: bool = False


@router.put("/api/campaigns/{campaign_id}/webhook")
def save_webhook(campaign_id: int, body: WebhookIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _manage(db, user, campaign_id)
    ep = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.campaign_id == c.id))
    if not ep:
        raise HTTPException(409, "Create the key first.")
    if body.is_active is not None:
        ep.is_active = body.is_active
    if body.dialer_url is not None or body.dialer_auth is not None or body.clear_dialer_auth:
        if user.user_type != "staff":
            raise HTTPException(403, "Only DialDesk staff can connect the dialer.")  # a client must not point our server at any address
        if body.dialer_url is not None:
            url = body.dialer_url.strip()
            if url and urlparse(url).scheme not in ("http", "https"):
                raise HTTPException(422, detail={"message": "The dialer address must start with http:// or https://", "fields": {"dialer_url": "Must start with http:// or https://"}})
            ep.dialer_url = url or None
        if body.clear_dialer_auth:
            ep.dialer_auth = None
        elif body.dialer_auth:
            ep.dialer_auth = body.dialer_auth.strip()
    audit(db, user, "webhook_changed", client_id=c.client_id, detail={"campaign": c.id})
    db.commit()
    return _out(db, ep, c)


# ---------- the dialer copy ----------

def forward_to_dialer(campaign_id: int, log_id: int, leads: list[dict[str, Any]]) -> None:
    """Posts the new leads to the dialer. Runs after the response is sent; the outcome is written to the log."""
    db = SessionLocal()
    try:
        ep = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.campaign_id == campaign_id))
        log = db.get(WebhookLog, log_id)
        if not ep or not ep.dialer_url or not log:
            return
        camp = db.get(Campaign, campaign_id)
        ids = list(db.scalars(select(DialerId.value).where(DialerId.campaign_id == campaign_id, DialerId.kind == "campaign", DialerId.is_active.is_(True))))
        headers = {"Authorization": ep.dialer_auth} if ep.dialer_auth else {}
        try:
            r = httpx.post(ep.dialer_url, json={"campaign": camp.name, "campaign_ids": ids,
                                                "leads": [{"name": l["name"], "mobile": l["mobile"]} for l in leads]}, headers=headers, timeout=10)
            log.dialer_status = f"Sent to the dialer (HTTP {r.status_code})" if r.is_success else f"Dialer refused (HTTP {r.status_code})"
        except Exception as exc:  # noqa: BLE001 - a dialer outage must never lose the data already saved here
            log.dialer_status = f"Could not reach the dialer: {str(exc)[:120]}"
        db.commit()
    finally:
        db.close()


# ---------- the public endpoint ----------

@router.post("/api/hooks/leads/{token}")
async def receive(token: str, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    h = _hash(token)
    q = _hits[h]
    now = time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE:
        raise HTTPException(429, "Too many requests. Send at most 60 calls a minute, with up to 500 records each.")
    q.append(now)

    ep = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.token_hash == h))
    if not ep or not ep.is_active:
        raise HTTPException(401, "This key is not valid.")
    camp = db.get(Campaign, ep.campaign_id)
    if not camp or camp.status == "closed":
        raise HTTPException(409, "This campaign is closed.")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(422, "Send a JSON body: one record, a list of records, or {\"leads\": [...]}.")
    records = data.get("leads") if isinstance(data, dict) and "leads" in data else ([data] if isinstance(data, dict) else data)
    if not isinstance(records, list) or not records:
        raise HTTPException(422, "Send a JSON body: one record, a list of records, or {\"leads\": [...]}.")
    if len(records) > MAX_PER_CALL:
        raise HTTPException(413, f"Send at most {MAX_PER_CALL} records per call.")

    existing = set(db.scalars(select(Lead.mobile).where(Lead.campaign_id == camp.id)))
    good, results = ls.build_from_records(records, existing)
    objs = [Lead(client_id=camp.client_id, campaign_id=camp.id, **g) for g in good]
    db.add_all(objs)
    db.flush()
    dv.queue(db, camp.id, objs)
    n = {k: sum(1 for r in results if r["status"] == k) for k in ("accepted", "duplicate", "invalid")}
    log = WebhookLog(campaign_id=camp.id, source="webhook", received=len(records), accepted=n["accepted"], duplicates=n["duplicate"],
                     invalid=n["invalid"], dialer_status=("Waiting to be sent to the dialer" if ep.dialer_url and good else None))
    db.add(log)
    ep.last_used_at = datetime.now(timezone.utc)
    ep.accepted_total += len(good)
    db.flush()
    log_id = log.id
    db.commit()
    if good and ep.dialer_url:
        tasks.add_task(forward_to_dialer, camp.id, log_id, good)
    return {"received": len(records), "accepted": n["accepted"], "duplicates": n["duplicate"], "invalid": n["invalid"], "results": results}
