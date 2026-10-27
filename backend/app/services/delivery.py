"""Getting a campaign's leads into the Vicidial list: queue them, hand them to the server's own script, record the result."""
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import DialerList, Lead, LeadDelivery
from .leads import ALIASES

CLAIM_MINUTES = 10      # a batch handed out and never answered is offered again after this
MAX_ATTEMPTS = 5
RETRY_MINUTES = 5       # a failed lead waits this long before the next try
BATCH = 200
DUP_CHECKS = ("NONE", "DUPLIST", "DUPCAMP", "DUPSYS")

# the Vicidial fields a CRM value may be sent to (phone_number, list_id and vendor_lead_code are always set by the CRM)
TARGETS = ("title", "first_name", "middle_initial", "last_name", "address1", "address2", "address3", "city", "state", "province", "postal_code",
           "country_code", "gender", "date_of_birth", "alt_phone", "email", "security_phrase", "comments", "rank", "owner", "source_id")
SOURCES = ("name", "mobile", "email", "city", "ext_ref")
DEFAULT_MAP = [{"to": "first_name", "from": "name"}, {"to": "email", "from": "email"}, {"to": "city", "from": "city"}]


def clean_map(items: Any) -> list[dict[str, str]]:
    """Keeps only mappings to allowed Vicidial fields (or custom:FIELD). Raises ValueError with a readable message."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for it in items or []:
        to, src = str((it or {}).get("to", "")).strip(), str((it or {}).get("from", "")).strip()
        if not to and not src:
            continue
        if not to or not src:
            raise ValueError("Each mapping needs both a dialer field and a CRM field")
        if to.startswith("custom:"):
            name = to[7:]
            if not name or not all(c.isalnum() or c == "_" for c in name) or len(name) > 50:
                raise ValueError(f"{to!r} is not a valid custom field name (letters, digits and _ only)")
            to = "custom:" + name.lower()
        elif to not in TARGETS:
            raise ValueError(f"{to!r} cannot be set from the CRM")
        if to in seen:
            raise ValueError(f"{to} is mapped twice")
        seen.add(to)
        out.append({"to": to, "from": src[:60]})
    return out


def params_for(lead: Lead, dl: DialerList) -> dict[str, str]:
    """The values for Vicidial's add_lead. Empty values are left out."""
    base = {"name": lead.name, "mobile": lead.mobile, "email": lead.email, "city": lead.city, "ext_ref": lead.ext_ref}
    extra = lead.extra or {}
    out: dict[str, str] = {}
    for m in (dl.field_map if dl.field_map is not None else DEFAULT_MAP):
        src = m["from"]
        if src in SOURCES:
            v = base.get(src)
        elif src in extra:
            v = extra[src]
        else:  # a client's own name for a standard field (policy_no is kept as ext_ref)
            v = base.get(next((f for f, names in ALIASES.items() if src.lower() in names), ""))
        if v not in (None, ""):
            out[m["to"]] = str(v)[:255]
    return out


def queue(db: Session, campaign_id: int, leads: Iterable[Lead]) -> int:
    """Puts new leads in line for every active dialer list of the campaign. Call after the leads have ids (flush first)."""
    lists = list(db.scalars(select(DialerList).where(DialerList.campaign_id == campaign_id, DialerList.is_active.is_(True))))
    n = 0
    for lead in leads:
        for dl in lists:
            db.add(LeadDelivery(lead_id=lead.id, dialer_list_id=dl.id, server_id=dl.server_id))
            n += 1
    return n


def queue_existing(db: Session, dl: DialerList) -> int:
    """Lines up the campaign's leads that nobody has called yet (used when a list is first connected). Skips ones already queued."""
    have = select(LeadDelivery.lead_id).where(LeadDelivery.dialer_list_id == dl.id)
    ids = list(db.scalars(select(Lead.id).where(Lead.campaign_id == dl.campaign_id, Lead.status == "new", Lead.attempts == 0, Lead.id.not_in(have))))
    for i in ids:
        db.add(LeadDelivery(lead_id=i, dialer_list_id=dl.id, server_id=dl.server_id))
    return len(ids)


def claim(db: Session, server_id: int, limit: int = BATCH) -> list[dict[str, Any]]:
    """Hands the server its waiting leads. They are marked claimed so a second run cannot take the same ones."""
    now = datetime.now(timezone.utc)
    stale = now - timedelta(minutes=CLAIM_MINUTES)
    retry = now - timedelta(minutes=RETRY_MINUTES)
    rows = list(db.execute(
        select(LeadDelivery, DialerList, Lead)
        .join(DialerList, DialerList.id == LeadDelivery.dialer_list_id).join(Lead, Lead.id == LeadDelivery.lead_id)
        .where(LeadDelivery.server_id == server_id, DialerList.is_active.is_(True), LeadDelivery.attempts < MAX_ATTEMPTS,
               ((LeadDelivery.status == "pending") & (LeadDelivery.claimed_at.is_(None) | (LeadDelivery.claimed_at < retry)))
               | ((LeadDelivery.status == "claimed") & (LeadDelivery.claimed_at < stale)))
        .order_by(LeadDelivery.id).limit(min(limit, BATCH)).with_for_update(of=LeadDelivery, skip_locked=True)))
    out = []
    for d, dl, lead in rows:
        d.status, d.claimed_at, d.attempts = "claimed", now, d.attempts + 1
        out.append({"delivery_id": d.id, "list_id": dl.list_id, "phone_code": dl.phone_code, "dup_check": dl.dup_check,
                    "phone_number": lead.mobile, "vendor_lead_code": f"CRM{lead.id}", "fields": params_for(lead, dl)})
    return out


def record(db: Session, server_id: int, results: list[dict[str, Any]]) -> dict[str, int]:
    """Stores what the server's script reports for each lead it tried."""
    now = datetime.now(timezone.utc)
    n = {"sent": 0, "duplicate": 0, "failed": 0, "unknown": 0}
    for r in results:
        d = db.get(LeadDelivery, int(r.get("delivery_id") or 0))
        if not d or d.server_id != server_id:
            n["unknown"] += 1
            continue
        status = r.get("status")
        if status == "sent":
            d.status, d.sent_at, d.error = "sent", now, None
            lid = r.get("lead_id")
            d.dialer_lead_id = int(lid) if str(lid or "").isdigit() else None
        elif status == "duplicate":
            d.status, d.sent_at, d.error = "duplicate", now, str(r.get("error") or "Already in the dialer")[:300]
        else:
            status = "failed"
            d.error = str(r.get("error") or "Failed")[:300]
            d.status = "failed" if d.attempts >= MAX_ATTEMPTS else "pending"  # tried again after RETRY_MINUTES, up to MAX_ATTEMPTS
            d.claimed_at = now
        n[status] += 1
    return n


def counts(db: Session, dialer_list_id: int) -> dict[str, int]:
    rows = dict(db.execute(select(LeadDelivery.status, func.count()).where(LeadDelivery.dialer_list_id == dialer_list_id).group_by(LeadDelivery.status)).all())
    return {k: rows.get(k, 0) for k in ("pending", "claimed", "sent", "duplicate", "failed")}


def retry_failed(db: Session, dialer_list_id: int) -> int:
    r = db.execute(update(LeadDelivery).where(LeadDelivery.dialer_list_id == dialer_list_id, LeadDelivery.status == "failed")
                   .values(status="pending", attempts=0, error=None, claimed_at=None))
    return r.rowcount or 0
