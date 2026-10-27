"""Sending a campaign's leads to the dialer: which Vicidial list each campaign loads into, and the two calls the server's script makes."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import Campaign, DialerList, DialerServer, LeadDelivery, User
from ..routers.campaigns import _get
from ..routers.dialer import _server
from ..services import delivery as dv

router = APIRouter(prefix="/api", tags=["dialer lists"])


# ---------- the server's script ----------

@router.post("/dialer/leads/claim")
def claim(request: Request, db: Session = Depends(get_db)):
    """New leads waiting for this server. Each is claimed, so a second run cannot take the same ones."""
    s = _server(request, db)
    items = dv.claim(db, s.id)
    seen = dict(s.last_seen or {})
    seen["leads"] = {"at": datetime.now(timezone.utc).isoformat(), "rows": len(items)}
    s.last_seen, s.last_seen_at = seen, datetime.now(timezone.utc)
    db.commit()
    return {"leads": items}


class ResultsIn(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list, max_length=dv.BATCH)


@router.post("/dialer/leads/result")
def result(body: ResultsIn, request: Request, db: Session = Depends(get_db)):
    s = _server(request, db)
    n = dv.record(db, s.id, body.results)
    db.commit()
    return {"ok": True, **n}


# ---------- setup on the campaign (DialDesk staff) ----------

def _need(user: User) -> None:
    if "dialer.manage" not in permissions_of(user):
        raise HTTPException(403, "Only DialDesk staff can connect a campaign to a dialer list.")


def _out(db: Session, dl: DialerList) -> dict[str, Any]:
    s = db.get(DialerServer, dl.server_id)
    return {"id": dl.id, "server_id": dl.server_id, "server": s.name if s else None, "list_id": dl.list_id, "phone_code": dl.phone_code,
            "dup_check": dl.dup_check, "field_map": dl.field_map if dl.field_map is not None else dv.DEFAULT_MAP, "is_active": dl.is_active,
            "counts": dv.counts(db, dl.id),
            "last_error": db.scalar(select(LeadDelivery.error).where(LeadDelivery.dialer_list_id == dl.id, LeadDelivery.error.is_not(None)).order_by(LeadDelivery.id.desc()).limit(1))}


@router.get("/campaigns/{campaign_id}/dialer-lists")
def list_lists(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    c = _get(db, user, campaign_id)
    rows = db.scalars(select(DialerList).where(DialerList.campaign_id == c.id).order_by(DialerList.id))
    return {"items": [_out(db, r) for r in rows], "targets": list(dv.TARGETS), "sources": list(dv.SOURCES), "dup_checks": list(dv.DUP_CHECKS),
            "servers": [{"id": s.id, "name": s.name} for s in db.scalars(select(DialerServer).where(DialerServer.is_active.is_(True)).order_by(DialerServer.name))]}


class ListIn(BaseModel):
    server_id: int
    list_id: str = Field(max_length=20)
    phone_code: str = Field(default="91", max_length=5)
    dup_check: str = "DUPLIST"
    field_map: Optional[list[dict[str, str]]] = None
    is_active: bool = True
    send_existing: bool = False     # also queue the campaign's uncalled leads that are already in the CRM


@router.put("/campaigns/{campaign_id}/dialer-lists")
def save_list(campaign_id: int, body: ListIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    c: Campaign = _get(db, user, campaign_id)
    errors: dict[str, str] = {}
    if not db.get(DialerServer, body.server_id):
        errors["server_id"] = "Choose a server"
    list_id = body.list_id.strip()
    if not list_id.isdigit():
        errors["list_id"] = "The Vicidial list id is a number, for example 1001"
    phone_code = body.phone_code.strip() or "91"
    if not phone_code.isdigit():
        errors["phone_code"] = "Digits only, for example 91"
    if body.dup_check not in dv.DUP_CHECKS:
        errors["dup_check"] = "Choose one of the options"
    try:
        fmap = dv.clean_map(body.field_map if body.field_map is not None else dv.DEFAULT_MAP)
    except ValueError as exc:
        errors["field_map"] = str(exc)
        fmap = []
    if errors:
        raise HTTPException(422, detail={"message": "Please fix the highlighted fields", "fields": errors})
    dl = db.scalar(select(DialerList).where(DialerList.campaign_id == c.id, DialerList.server_id == body.server_id))
    created = dl is None
    if created:
        dl = DialerList(campaign_id=c.id, client_id=c.client_id, server_id=body.server_id, list_id=list_id)
        db.add(dl)
    dl.list_id, dl.phone_code, dl.dup_check, dl.field_map, dl.is_active = list_id, phone_code, body.dup_check, fmap, body.is_active
    db.flush()
    queued = dv.queue_existing(db, dl) if body.send_existing and dl.is_active else 0
    audit(db, user, "dialer_list_saved", client_id=c.client_id, detail={"campaign": c.id, "server": body.server_id, "list": list_id, "queued_existing": queued})
    db.commit()
    return {**_out(db, dl), "queued_existing": queued, "created": created}


@router.delete("/campaigns/{campaign_id}/dialer-lists/{dl_id}")
def delete_list(campaign_id: int, dl_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stops sending. Leads already added stay in the dialer; nothing is removed there."""
    _need(user)
    c = _get(db, user, campaign_id)
    dl = db.get(DialerList, dl_id)
    if not dl or dl.campaign_id != c.id:
        raise HTTPException(404, "Not found")
    db.delete(dl)
    audit(db, user, "dialer_list_removed", client_id=c.client_id, detail={"campaign": c.id, "list": dl.list_id})
    db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/dialer-lists/{dl_id}/retry")
def retry(campaign_id: int, dl_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _need(user)
    c = _get(db, user, campaign_id)
    dl = db.get(DialerList, dl_id)
    if not dl or dl.campaign_id != c.id:
        raise HTTPException(404, "Not found")
    n = dv.retry_failed(db, dl.id)
    db.commit()
    return {"retried": n}
