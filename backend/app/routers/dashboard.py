from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..config import settings
from ..models import CLIENT_STATUSES, Campaign, Client, ClientDocument, Interaction, Notification, Plan, User
from ..services.onboarding import logo_url, profile_status

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def operations(db: Session, client_id: Optional[int], days: int) -> dict:
    """Call-centre numbers for the period: volumes, outcomes, hours, agents, clients. `client_id` limits it to one company.
    Everything is counted by the database, so it stays quick with millions of calls."""
    tz = ZoneInfo(settings.TIMEZONE)
    now = datetime.now(tz)
    today = now.date()
    start_local = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    w = [Interaction.started_at >= start_local.astimezone(timezone.utc)]
    if client_id:
        w.append(Interaction.client_id == client_id)
    local = func.timezone(settings.TIMEZONE, Interaction.started_at)

    by_status = dict(db.execute(select(Interaction.status, func.count()).where(*w).group_by(Interaction.status)).all())
    by_mode = dict(db.execute(select(Interaction.mode, func.count()).where(*w).group_by(Interaction.mode)).all())
    secs = func.extract("epoch", Interaction.tagged_at - Interaction.started_at)
    avg = db.scalar(select(func.avg(secs)).where(*w, Interaction.status == "tagged", Interaction.tagged_at.is_not(None), secs >= 0, secs <= 4 * 3600))
    total = sum(by_status.values())
    agents_n = db.scalar(select(func.count(func.distinct(Interaction.agent_id))).where(*w))

    hourly = [0] * 24
    for h, n in db.execute(select(func.extract("hour", local), func.count()).where(*w, func.date(local) == today).group_by(func.extract("hour", local))).all():
        hourly[int(h)] = n
    per_day = {d.isoformat() if hasattr(d, "isoformat") else str(d): n for d, n in db.execute(select(func.date(local), func.count()).where(*w).group_by(func.date(local))).all()}
    outcomes = db.execute(select(Interaction.outcome, func.count()).where(*w, Interaction.status == "tagged").group_by(Interaction.outcome).order_by(func.count().desc())).all()

    agent_rows = db.execute(select(
        Interaction.agent_id, func.count(), func.sum(case((Interaction.status == "tagged", 1), else_=0)),
        func.avg(case(((Interaction.status == "tagged") & (secs >= 0) & (secs <= 4 * 3600), secs), else_=None)))
        .where(*w).group_by(Interaction.agent_id).order_by(func.count().desc()).limit(8)).all()
    by_client = db.execute(select(Interaction.client_id, func.count()).where(*w).group_by(Interaction.client_id).order_by(func.count().desc()).limit(6)).all()
    by_campaign = db.execute(select(Interaction.campaign_id, func.count()).where(*w, Interaction.campaign_id.is_not(None))
                             .group_by(Interaction.campaign_id).order_by(func.count().desc()).limit(6)).all()
    open_stmt = select(Interaction).where(Interaction.status == "open")
    if client_id:
        open_stmt = open_stmt.where(Interaction.client_id == client_id)
    open_now = list(db.scalars(open_stmt.order_by(Interaction.started_at.desc()).limit(20)))
    open_count = db.scalar(select(func.count()).select_from(open_stmt.subquery()))

    def names(model, attr, ids):
        ids = {i for i in ids if i}
        return {i: n for i, n in db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids)))} if ids else {}

    nu = names(User, "name", [a for a, *_ in agent_rows] + [r.agent_id for r in open_now])
    nc = names(Client, "company_name", [c for c, _ in by_client] + [r.client_id for r in open_now])
    npc = names(Campaign, "name", [c for c, _ in by_campaign])
    tagged = by_status.get("tagged", 0)
    return {
        "days": days,
        "kpi": {
            "calls": total, "tagged": tagged, "skipped": by_status.get("skipped", 0), "open": open_count, "agents": agents_n,
            "avg_secs": round(avg or 0), "tag_rate": round(100 * tagged / total) if total else 0,
            "inbound": by_mode.get("inbound", 0), "pd": by_mode.get("pd", 0), "manual": by_mode.get("manual", 0),
        },
        "hourly": hourly,
        "daily": [{"date": (today - timedelta(days=i)).isoformat(), "calls": per_day.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(days - 1, -1, -1)],
        "outcomes": [{"outcome": o or "none", "count": n} for o, n in outcomes],
        "top_agents": [{"name": nu.get(a, "?"), "calls": c, "tagged": int(t or 0), "avg_secs": round(av or 0)} for a, c, t, av in agent_rows],
        "by_client": [{"name": nc.get(k, "?"), "calls": v} for k, v in by_client],
        "by_campaign": [{"name": npc.get(k, "?"), "calls": v} for k, v in by_campaign],
        "live": [{"id": r.id, "agent": nu.get(r.agent_id), "client": nc.get(r.client_id), "phone": r.phone, "mode": r.mode, "started_at": r.started_at} for r in open_now],
    }


@router.get("/clients")
def client_options(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Companies for the client switcher in the top bar (DialDesk staff only)."""
    if user.user_type != "staff":
        return []
    rows = db.scalars(select(Client).where(Client.status.in_(("active", "suspended"))).order_by(Client.company_name))
    return [{"id": c.id, "name": c.company_name, "code": c.code, "logo_url": logo_url(c)} for c in rows]


@router.get("")
def summary(days: int = 1, client_id: Optional[int] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    days = days if days in (1, 7, 30) else 1
    if user.user_type != "staff":
        client = user.client
        return {"scope": "client", "profile": profile_status(client) if client else None,
                "ops": operations(db, user.client_id, days) if user.client_id else None,
                "active_campaigns": db.scalar(select(func.count()).select_from(Campaign).where(
                    Campaign.client_id == user.client_id, Campaign.status == "active")) if user.client_id else 0}
    counts = dict(db.execute(select(Client.status, func.count()).group_by(Client.status)).all())
    week = datetime.now(timezone.utc) - timedelta(days=7)
    waiting = db.scalars(select(Client).where(Client.status == "submitted").order_by(Client.id.desc()).limit(8))
    recent_active = db.scalars(select(Client).where(Client.status == "active").order_by(Client.activated_at.desc()).limit(5))
    docs_to_review = db.scalar(
        select(func.count()).select_from(ClientDocument).join(Client, Client.id == ClientDocument.client_id)
        .where(ClientDocument.status == "pending", Client.status == "active"))
    return {
        "scope": "admin",
        "ops": operations(db, client_id, days),
        "active_campaigns": db.scalar(select(func.count()).select_from(Campaign).where(
            Campaign.status == "active", *([Campaign.client_id == client_id] if client_id else []))),
        "counts": {s: counts.get(s, 0) for s in CLIENT_STATUSES},
        "pending_review": counts.get("submitted", 0),
        "docs_to_review": docs_to_review,
        "plans_to_approve": db.scalar(select(func.count()).select_from(Plan).where(Plan.status == "pending")),
        "new_this_week": db.scalar(select(func.count()).select_from(Client).where(Client.created_at >= week)),
        "failed_messages": db.scalar(select(func.count()).select_from(Notification).where(Notification.status == "failed")),
        "waiting": [{"id": c.id, "company_name": c.company_name, "status": c.status, "created_at": c.created_at,
                     "source": c.source, "contact_name": c.contacts[0].name if c.contacts else None} for c in waiting],
        "recent_active": [{"id": c.id, "company_name": c.company_name, "code": c.code, "logo_url": logo_url(c),
                           "activated_at": c.activated_at, "profile_percent": profile_status(c)["percent"]}
                          for c in recent_active],
    }
