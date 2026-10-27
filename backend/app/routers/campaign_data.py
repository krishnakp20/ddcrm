"""Campaign data: upload a file, map its columns, see the leads, and allocate them to agents or the shared queue."""
import csv
import io
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, permissions_of
from ..models import AgentCampaign, Campaign, CampaignBatch, DialerList, Lead, User, WebhookEndpoint, WebhookLog
from ..routers.campaigns import _get
from ..services import delivery as dv
from ..services import leads as ls

router = APIRouter(prefix="/api/campaigns/{campaign_id}/data", tags=["campaign data"])


def _view(db: Session, user: User, campaign_id: int) -> Campaign:
    if "campaigns.view" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission for this")
    return _get(db, user, campaign_id)


def _manage(db: Session, user: User, campaign_id: int) -> Campaign:
    if "campaigns.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission to change campaign data")
    c = _get(db, user, campaign_id)
    if c.status == "closed":
        raise HTTPException(409, "This campaign is closed. Reopen it before changing its data.")
    return c


def _allocated_agents(db: Session, campaign: Campaign) -> dict[int, str]:
    rows = db.execute(select(User.id, User.name).join(AgentCampaign, AgentCampaign.user_id == User.id)
                      .where(AgentCampaign.campaign_id == campaign.id, User.is_active.is_(True)))
    return {i: n for i, n in rows}


def _distribute(db: Session, leads: list[Lead], agent_ids: list[int]) -> None:
    """Shares leads evenly between the agents, in order. No agents = shared queue."""
    for i, l in enumerate(leads):
        l.assigned_to_id = agent_ids[i % len(agent_ids)] if agent_ids else None


# ---------- upload ----------

@router.post("/preview")
async def preview(campaign_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _manage(db, user, campaign_id)
    header, rows = ls.read_file(file.filename or "", await file.read())
    return {"filename": file.filename, "columns": header, "rows": len(rows), "sample": rows[:5], "mapping": ls.guess_mapping(header)}


@router.post("/import", status_code=201)
async def import_data(campaign_id: int, tasks: BackgroundTasks, file: UploadFile = File(...), mapping: str = Form(...), agent_ids: str = Form("[]"), name: str = Form(""),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    camp = _manage(db, user, campaign_id)
    try:
        mp = json.loads(mapping)
        agents = [int(a) for a in json.loads(agent_ids)]
    except (ValueError, TypeError):
        raise HTTPException(422, "The column choices could not be read. Try again.")
    allowed = _allocated_agents(db, camp)
    if any(a not in allowed for a in agents):
        raise HTTPException(422, "You can only share data with agents who are allocated to this campaign.")
    header, rows = ls.read_file(file.filename or "", await file.read())
    existing = set(db.scalars(select(Lead.mobile).where(Lead.campaign_id == camp.id)))
    good, dups, errors = ls.build_leads(header, rows, mp, existing)
    if not good:
        raise HTTPException(422, detail={"message": "No new data could be added from this file.", "errors": [{"row": r, "reason": m} for r, m in errors[:50]],
                                          "duplicates": dups, "invalid": len(errors)})
    batch = CampaignBatch(client_id=camp.client_id, campaign_id=camp.id, filename=(file.filename or "upload")[:200], name=" ".join(name.split())[:120] or None, total_rows=len(rows),
                          accepted=len(good), duplicates=dups, invalid=len(errors), uploaded_by_id=user.id)
    db.add(batch)
    db.flush()
    objs = [Lead(client_id=camp.client_id, campaign_id=camp.id, batch_id=batch.id, **g) for g in good]
    _distribute(db, objs, agents)
    db.add_all(objs)
    db.flush()
    dv.queue(db, camp.id, objs)  # lines the new numbers up for the dialer list, if the campaign has one
    audit(db, user, "campaign_data_uploaded", client_id=camp.client_id, detail={"campaign": camp.id, "batch": batch.id, "accepted": len(good)})
    ep = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.campaign_id == camp.id))
    log_id = None
    if ep and ep.dialer_url:  # the dialer gets a copy of an uploaded file too
        wl = WebhookLog(campaign_id=camp.id, source="upload", received=len(rows), accepted=len(good), duplicates=dups, invalid=len(errors),
                        dialer_status="Waiting to be sent to the dialer")
        db.add(wl)
        db.flush()
        log_id = wl.id
    db.commit()
    if log_id:
        from .webhooks import forward_to_dialer
        tasks.add_task(forward_to_dialer, camp.id, log_id, good)
    return {"batch_id": batch.id, "name": batch.name or batch.filename, "total": len(rows), "accepted": len(good), "duplicates": dups, "invalid": len(errors),
            "errors": [{"row": r, "reason": m} for r, m in errors[:50]], "shared": not agents}


# ---------- look at the data ----------

@router.get("/summary")
def summary(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    camp = _view(db, user, campaign_id)
    by_status = dict(db.execute(select(Lead.status, func.count()).where(Lead.campaign_id == camp.id).group_by(Lead.status)).all())
    per_agent = db.execute(select(Lead.assigned_to_id, func.count()).where(
        Lead.campaign_id == camp.id, Lead.status.in_(("new", "callback"))).group_by(Lead.assigned_to_id)).all()
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_([a for a, _ in per_agent if a] or [0]))).all())
    return {
        "total": sum(by_status.values()), "new": by_status.get("new", 0), "callback": by_status.get("callback", 0),
        "done": by_status.get("done", 0), "dnc": by_status.get("dnc", 0),
        "unassigned": next((n for a, n in per_agent if a is None), 0),
        "per_agent": [{"id": a, "name": names.get(a, "?"), "open": n} for a, n in per_agent if a],
    }


@router.get("/leads")
def leads(campaign_id: int, status: Optional[str] = None, assigned: Optional[str] = None, q: Optional[str] = None, page: int = 1,
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    camp = _view(db, user, campaign_id)
    stmt = select(Lead).where(Lead.campaign_id == camp.id)
    if status in ("new", "callback", "done", "dnc"):
        stmt = stmt.where(Lead.status == status)
    if assigned == "shared":
        stmt = stmt.where(Lead.assigned_to_id.is_(None))
    elif assigned and assigned.isdigit():
        stmt = stmt.where(Lead.assigned_to_id == int(assigned))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Lead.name.ilike(like), Lead.mobile.like(like), Lead.ext_ref.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    size, page = 25, max(1, page)
    rows = list(db.scalars(stmt.order_by(Lead.id).offset((page - 1) * size).limit(size)))
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_({r.assigned_to_id for r in rows if r.assigned_to_id} or {0}))).all())
    return {"items": [ls.lead_out(r, names) for r in rows], "total": total, "page": page, "page_size": size}


@router.get("/batches")
def batches(campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    camp = _view(db, user, campaign_id)
    rows = db.scalars(select(CampaignBatch).where(CampaignBatch.campaign_id == camp.id).order_by(CampaignBatch.id.desc()).limit(30))
    names = dict(db.execute(select(User.id, User.name)).all())
    out = []
    for b in rows:
        worked = db.scalar(select(func.count()).select_from(Lead).where(Lead.batch_id == b.id, Lead.attempts > 0))
        out.append({"id": b.id, "filename": b.filename, "name": b.name or b.filename, "total": b.total_rows, "accepted": b.accepted, "duplicates": b.duplicates,
                    "invalid": b.invalid, "worked": worked, "by": names.get(b.uploaded_by_id), "created_at": b.created_at})
    return out


# ---------- allocate ----------

class AllocateIn(BaseModel):
    agent_ids: list[int] = []        # empty = back to the shared queue
    lead_ids: Optional[list[int]] = None  # None = every lead still to be called


@router.post("/allocate")
def allocate(campaign_id: int, body: AllocateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    camp = _manage(db, user, campaign_id)
    allowed = _allocated_agents(db, camp)
    if any(a not in allowed for a in body.agent_ids):
        raise HTTPException(422, "You can only share data with agents who are allocated to this campaign.")
    stmt = select(Lead).where(Lead.campaign_id == camp.id, Lead.status.in_(("new", "callback")))
    if body.lead_ids is not None:
        stmt = stmt.where(Lead.id.in_(body.lead_ids or [0]))
    rows = list(db.scalars(stmt.order_by(Lead.id)))
    _distribute(db, rows, body.agent_ids)
    audit(db, user, "campaign_data_allocated", client_id=camp.client_id, detail={"campaign": camp.id, "leads": len(rows), "agents": body.agent_ids})
    db.commit()
    return {"allocated": len(rows), "shared": not body.agent_ids}


@router.delete("/batches/{batch_id}")
def delete_batch(campaign_id: int, batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Removes an upload that was a mistake. Only leads nobody has called yet are removed; worked leads stay."""
    camp = _manage(db, user, campaign_id)
    b = db.get(CampaignBatch, batch_id)
    if not b or b.campaign_id != camp.id:
        raise HTTPException(404, "Upload not found")
    rows = list(db.scalars(select(Lead).where(Lead.batch_id == b.id, Lead.attempts == 0, Lead.locked_by_id.is_(None))))
    for r in rows:
        db.delete(r)
    kept = db.scalar(select(func.count()).select_from(Lead).where(Lead.batch_id == b.id)) - len(rows)
    if kept <= 0:
        db.delete(b)
    audit(db, user, "campaign_data_removed", client_id=camp.client_id, detail={"campaign": camp.id, "batch": b.id, "removed": len(rows)})
    db.commit()
    return {"removed": len(rows), "kept": max(kept, 0)}


# ---------- download (for a dialer that is not connected) ----------

VICI_COLUMNS = ["vendor_lead_code", "source_id", "list_id", "phone_code", "phone_number", "title", "first_name", "middle_initial", "last_name", "address1",
                "address2", "address3", "city", "state", "province", "postal_code", "country_code", "gender", "date_of_birth", "alt_phone", "email",
                "security_phrase", "comments", "rank", "owner"]


def _safe(v: Any) -> str:
    """A spreadsheet runs text that starts with = + - @ as a formula; a leading quote stops that."""
    t = "" if v is None else str(v)
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


@router.get("/export")
def export(campaign_id: int, batch_id: Optional[int] = None, scope: str = "open", format: str = "plain", list_id: str = "", phone_code: str = "91",
           header: Optional[bool] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The campaign's numbers as a file. scope: open (still to call) | all. format: plain (CRM columns) | vicidial (ready for Load Leads)."""
    if "campaigns.manage" not in permissions_of(user):
        raise HTTPException(403, "You don't have permission to download campaign data")
    camp = _get(db, user, campaign_id)
    if scope not in ("open", "all") or format not in ("plain", "vicidial"):
        raise HTTPException(422, "Choose what to download")
    if format == "vicidial":
        if not list_id.strip().isdigit():
            raise HTTPException(422, detail={"message": "Type the Vicidial list ID (a number) the file is for.", "fields": {"list_id": "Required"}})
        if not phone_code.strip().isdigit():
            raise HTTPException(422, detail={"message": "The country code must be digits, for example 91.", "fields": {"phone_code": "Digits only"}})
    stmt = select(Lead).where(Lead.campaign_id == camp.id).order_by(Lead.id)
    if scope == "open":
        stmt = stmt.where(Lead.status.in_(("new", "callback")))
    else:
        stmt = stmt.where(Lead.status != "dnc")   # a number marked do-not-call is never handed to a dialer
    if batch_id is not None:
        stmt = stmt.where(Lead.batch_id.is_(None) if batch_id == 0 else Lead.batch_id == batch_id)
    leads = list(db.scalars(stmt.limit(ls.MAX_ROWS + 1)))
    if len(leads) > ls.MAX_ROWS:
        raise HTTPException(422, f"More than {ls.MAX_ROWS} numbers. Pick one allocation to download.")
    if not leads:
        raise HTTPException(404, "There is nothing to download for this choice.")
    agents = dict(db.execute(select(User.id, User.name)).all())
    batches = dict(db.execute(select(CampaignBatch.id, func.coalesce(CampaignBatch.name, CampaignBatch.filename)).where(CampaignBatch.campaign_id == camp.id)).all())
    buf = io.StringIO()
    w = csv.writer(buf)
    if format == "vicidial":
        dl = db.scalar(select(DialerList).where(DialerList.campaign_id == camp.id, DialerList.is_active.is_(True)).order_by(DialerList.id))
        fmap = (dl.field_map if dl and dl.field_map is not None else dv.DEFAULT_MAP)
        shim = type("L", (), {"field_map": fmap})()
        if header:
            w.writerow(VICI_COLUMNS)
        for l in leads:
            vals = {k: v for k, v in dv.params_for(l, shim).items() if k in VICI_COLUMNS}
            w.writerow([f"CRM{l.id}", "", list_id.strip(), phone_code.strip(), l.mobile] + [_safe(vals.get(c, "")) for c in VICI_COLUMNS[5:]])
        name = f"{camp.code}_vicidial_list{list_id.strip()}"
    else:
        keys: list[str] = []
        for l in leads:
            for k in (l.extra or {}):
                if k not in keys and len(keys) < 30:
                    keys.append(k)
        if header is not False:
            w.writerow(["Name", "Mobile", "Email", "City", "Reference", "Status", "Tries", "Agent", "Allocation", "Last outcome"] + keys)
        for l in leads:
            w.writerow([_safe(l.name), l.mobile, _safe(l.email), _safe(l.city), _safe(l.ext_ref), l.status, l.attempts, agents.get(l.assigned_to_id, "Shared queue"),
                        _safe(batches.get(l.batch_id, "Client API / other")), l.last_outcome or ""] + [_safe((l.extra or {}).get(k)) for k in keys])
        name = f"{camp.code}_data"
    audit(db, user, "campaign_data_downloaded", client_id=camp.client_id, detail={"campaign": camp.id, "rows": len(leads), "format": format, "scope": scope, "batch": batch_id, "list": list_id or None})
    db.commit()
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    return Response(content=("﻿" + buf.getvalue()) if format == "plain" else buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}_{datetime.now():%Y%m%d}.csv"'})
