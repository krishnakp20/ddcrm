"""Moves active clients from the old DialDesk CRM (MySQL) into this CRM.

    python migrate_old.py                      # dry run: reads, checks, reports, writes nothing
    python migrate_old.py --commit             # really write
    python migrate_old.py --commit --only clients,users
    python migrate_old.py --client 605 --client 656      # only these old client ids

Safe to run again: every old row that was moved is remembered (table legacy_map) and is skipped next time.
Old passwords are never copied. Moved users get an unusable password; send them a set-password link from the Users page.

Connection to the old database: environment OLD_DB_HOST / OLD_DB_PORT / OLD_DB_USER / OLD_DB_PASSWORD / OLD_DB_NAME
(defaults: 127.0.0.1, 3307, root, empty, db_dialdesk).
"""
import argparse
import os
import re
import secrets
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pymysql
from sqlalchemy import String, cast, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import Base, SessionLocal, engine, ensure_columns
from app.config import settings
from fix_mojibake import fix as fix_text
from app.models import (AccessRole, AgentClient, Campaign, CampaignBatch, Client, ClientContact, Customer, DialerId, FormField, Interaction, Lead,
                        LegacyMap, Plan, PlanAssignment, Scenario, Ticket, TicketComment, User, ValueItem, ValueList)
from app.security import hash_password
from app.services import forms as fs
from app.services import plans as plan_svc
from app.services.access import ensure_system_roles
from app.services.phone import normalize_phone, valid_phone

STEPS = ["clients", "users", "agents", "dialer", "forms", "scenarios", "plans", "campaigns", "calls", "outcalls", "leads", "alerts", "alertmatrix"]
TZ = ZoneInfo(settings.TIMEZONE)
CHUNK = 4000
OPTS = {"dry": True, "months": 12, "leads": "active"}  # set from the command line
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DIALER_VALUE = re.compile(r"^[A-Za-z0-9_.:\- ]{1,60}$")
OWNERS = ("client", "ceo", "director", "owner", "md", "managing director", "founder", "chairman", "co founder", "foundar", "cxes", "gm", "general manager")

warnings: list[str] = []
counts: Counter = Counter()


def warn(msg: str) -> None:
    warnings.append(msg)


def old_db():
    return pymysql.connect(host=os.getenv("OLD_DB_HOST", "127.0.0.1"), port=int(os.getenv("OLD_DB_PORT", "3307")), user=os.getenv("OLD_DB_USER", "root"),
                           password=os.getenv("OLD_DB_PASSWORD", ""), database=os.getenv("OLD_DB_NAME", "db_dialdesk"), charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)


def rows(cur, sql, *args):
    cur.connection.ping(reconnect=True)  # the old server drops a connection that sat idle during a long step
    cur.execute(sql, args)
    return cur.fetchall()


def s(v, n=None):
    v = fix_text(("" if v is None else str(v)).strip())  # old latin1 columns held UTF-8 bytes: undo the garbling
    return v[:n] if n else v


def when(v) -> datetime:
    """An old date or datetime (sometimes text, sometimes empty or 0000-00-00) as a timezone-aware datetime."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.strip().replace("T", " "))
        except ValueError:
            v = None
    if isinstance(v, datetime) and v.year > 2000:
        return v.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def phone10(v) -> str:
    p = normalize_phone(s(v))
    return p if valid_phone(p) else ""


class Map:
    """legacy_map in memory, written through to the database session."""

    def __init__(self, db):
        self.db, self.m = db, {(r.kind, r.old_id): r.new_id for r in db.scalars(select(LegacyMap))}

    def get(self, kind, old):
        return self.m.get((kind, str(old)))

    def set(self, kind, old, new):
        self.m[(kind, str(old))] = new
        self.db.add(LegacyMap(kind=kind, old_id=str(old), new_id=new))


def role_id(db, key):
    return db.scalar(select(AccessRole.id).where(AccessRole.key == key))


def next_code(db) -> str:
    last = db.scalar(select(func.max(Client.code)))
    return f"CL{int(last[2:]) + 1 if last else 1:04d}"


# ---------- steps ----------

def step_clients(db, cur, mp, only):
    inbound = {int(r["client_id"]) for r in rows(cur, "select distinct client_id from ingroup_campaign_master where client_id regexp '^[0-9]+$'")}
    outbound = {r["ClientId"] for r in rows(cur, "select distinct ClientId from ob_campaign")}
    used_gst = set(db.scalars(select(Client.gstin).where(Client.gstin.is_not(None))))
    for r in rows(cur, "select * from registration_master where status='A' order by company_id"):
        cid = r["company_id"]
        if only and cid not in only:
            continue
        if mp.get("client", cid):
            counts["clients already moved"] += 1
            continue
        name = s(r["company_name"], 200)
        if not name:
            warn(f"client {cid}: no company name, skipped")
            continue
        gst = s(r["gst_no"]).upper()
        if not GSTIN.match(gst):
            if gst:
                warn(f"client {cid} {name}: GSTIN {gst!r} is not valid, left empty")
            gst = None
        elif gst in used_gst:
            warn(f"client {cid} {name}: GSTIN {gst} already used by another client, left empty")
            gst = None
        if gst:
            used_gst.add(gst)
        addr = ", ".join(x for x in (s(r["reg_office_address1"]), s(r["reg_office_address2"])) if x)
        comm = ", ".join(x for x in (s(r["comm_address1"]), s(r["comm_address2"])) if x)
        pin = re.sub(r"\D", "", s(r["pincode"]))
        bpin = re.sub(r"\D", "", s(r["comm_pincode"]))
        services = [x for x, on in (("inbound", cid in inbound), ("outbound", cid in outbound)) if on]
        created = when(r["create_date"])
        c = Client(company_name=name, status="active", source="admin", gstin=gst, pan=gst[2:12] if gst else None, address=addr or None,
                   city=s(r["city"], 100).title() or None, state=s(r["state"], 60).title() or None, pincode=pin[:6] if len(pin) == 6 else None,
                   billing_same=not comm or comm == addr, billing_address=comm or None if comm and comm != addr else None,
                   billing_city=s(r["comm_city"], 100).title() or None if comm and comm != addr else None,
                   billing_state=s(r["comm_state"], 60).title() or None if comm and comm != addr else None,
                   billing_pincode=bpin[:6] if len(bpin) == 6 and comm and comm != addr else None,
                   billing_email=s(r["billing_email_id"], 255) if EMAIL.match(s(r["billing_email_id"])) else None,
                   services=services, activated_at=created, created_at=created, code=next_code(db))
        db.add(c)
        db.flush()
        people = [(r["auth_person"], r["designation"], r["phone_no"], r["email"])] + [
            (r[f"contact_person{i}"], r[f"cp{i}_designation"], r[f"cp{i}_phone"], r[f"cp{i}_email"]) for i in (1, 2, 3)]
        pos = 0
        for nm, des, ph, em in people:
            if s(nm):
                db.add(ClientContact(client_id=c.id, position=pos, name=s(nm, 120), designation=s(des, 80) or None, mobile=phone10(ph),
                                     email=s(em, 255).lower() if EMAIL.match(s(em).lower()) else ""))
                pos += 1
        mp.set("client", cid, c.id)
        counts["clients"] += 1


def step_users(db, cur, mp, only):
    have = set(db.scalars(select(User.email)))
    admin, mgr = role_id(db, "client_admin"), role_id(db, "client_manager")
    clients = {int(k[1]): v for k, v in mp.m.items() if k[0] == "client"}

    def add(old_client, name, email, phone, designation, key):
        email = s(email).lower()
        if not EMAIL.match(email):
            warn(f"client {old_client}: user {name!r} has no valid email ({email!r}), skipped")
            return
        if email in have:
            counts["users skipped (email already used)"] += 1
            return
        if mp.get(key[0], key[1]):
            return
        role = admin if s(designation).lower() in OWNERS else mgr
        u = User(name=s(name, 120) or email, email=email, phone=phone10(phone) or None, user_type="client", role_id=role, client_id=clients[old_client],
                 hashed_password=hash_password(secrets.token_urlsafe(24)), is_active=True)
        db.add(u)
        db.flush()
        have.add(email)
        mp.set(key[0], key[1], u.id)
        counts["client users"] += 1

    for old in clients:
        if only and old not in only:
            continue
        for u in rows(cur, "select * from logincreation_master where create_id=%s order by id", old):
            add(old, u["name"], u["username"], u["phone"], u["designation"], ("user", u["id"]))
        r = rows(cur, "select auth_person, designation, phone_no, email from registration_master where company_id=%s", old)[0]
        add(old, r["auth_person"], r["email"], r["phone_no"], "client", ("regcontact", old))


def step_agents(db, cur, mp, only):
    have = set(db.scalars(select(User.email)))
    role = role_id(db, "agent")
    migrated = {int(k[1]): v for k, v in mp.m.items() if k[0] == "client"}
    for a in rows(cur, "select * from agent_master where status='A' order by id"):
        if mp.get("agent", a["id"]):
            counts["agents already moved"] += 1
            continue
        rights = [int(x) for x in re.findall(r"\d+", s(a["ClientRights"]))]
        mine = [migrated[x] for x in rights if x in migrated and (not only or x in only)]
        if not mine:
            continue
        email = s(a["email"]).lower()
        if not EMAIL.match(email) or email in have:
            email = f"agent{a['id']}@legacy.invalid"
        dedicated = s(a["processname"]) in ("IB Dedicated", "OB Dedicated") and len(mine) == 1
        u = User(name=s(a["displayname"], 120) or f"Agent {a['id']}", email=email, phone=phone10(a["phone_no"]) or None, user_type="agent", role_id=role,
                 client_id=mine[0] if dedicated else None, dialer_agent_id=s(a["username"], 60) or None, is_active=True,
                 hashed_password=hash_password(secrets.token_urlsafe(24)))
        db.add(u)
        db.flush()
        have.add(email)
        if not dedicated:
            for c in mine:
                db.add(AgentClient(user_id=u.id, client_id=c))
        mp.set("agent", a["id"], u.id)
        counts["agents (own client)" if dedicated else "agents (shared)"] += 1
        if email.endswith("@legacy.invalid"):
            counts["agents with a placeholder email (fix before inviting)"] += 1


def step_dialer(db, cur, mp, only):
    vendor_of = {v: c for v, c in db.execute(select(DialerId.value, DialerId.client_id).where(DialerId.kind == "vendor"))}  # vendor id -> client, kept current as ids are added
    for k, new in list(mp.m.items()):
        if k[0] != "client":
            continue
        old = int(k[1])
        if only and old not in only:
            continue
        have = {(d.kind, d.value) for d in db.scalars(select(DialerId).where(DialerId.client_id == new))}
        # the vendor id is the did_number of the client's latest row (highest id) in the old did_master; a client with no usable row keeps its old client number
        did = (rows(cur, "select did_number n from did_master where client_id=%s order by id desc limit 1", old) or [{"n": None}])[0]["n"]
        did = did if did and int(did) > 0 else None
        if did:
            holder = vendor_of.get(str(did))
            if holder not in (None, new):  # another client already holds this number: keep this client on its old number
                warn(f"client {old}: did_master number {did} is already the vendor id of another client, so the client number {old} is kept")
                counts["vendor ids kept on the client number (did id already used)"] += 1
                did = None
        vendor = str(did) if did else str(old)
        wanted = [("vendor", vendor)]
        if not did:  # a client that stays on its client number must have it switched on (an earlier run may have switched it off)
            for d in db.scalars(select(DialerId).where(DialerId.client_id == new, DialerId.kind == "vendor", DialerId.value == str(old), DialerId.is_active.is_(False))):
                d.is_active = True
                counts["vendor ids switched back on (client number)"] += 1
        if did:  # the client number used before is switched off (not deleted), so it can be switched back on from the client page
            for d in db.scalars(select(DialerId).where(DialerId.client_id == new, DialerId.kind == "vendor", DialerId.value == str(old), DialerId.is_active.is_(True))):
                if str(old) != vendor:
                    d.is_active = False
                    counts["vendor ids switched off (old client number)"] += 1
        for g in rows(cur, "select ingroup_id from ingroup_campaign_master where client_id=%s and (camp_type is null or camp_type<>'OB')", str(old)):
            v = s(g["ingroup_id"])
            if v and DIALER_VALUE.match(v):
                wanted.append(("ingroup", v))
        # the dialer's inbound group names are kept in registration_master (GroupId, campaignid) and as the campaign name in ingroup_campaign_master;
        # the outbound campaigns' dialer ids (ob_campaign.campaign_id) are not inbound groups
        ob_ids = {s(x["campaign_id"]) for x in rows(cur, "select campaign_id from ob_campaign where ClientId=%s", old)}
        reg = rows(cur, "select GroupId, campaignid from registration_master where company_id=%s", old)
        names: list[str] = []
        for col in (reg[0]["GroupId"], reg[0]["campaignid"]) if reg else ():
            names += re.findall(r"'([^']+)'", s(col)) or [x for x in re.split(r"[,;]", s(col)) if x.strip()]
        names += [s(g["campaign_name"]) for g in rows(cur, "select campaign_name from ingroup_campaign_master where client_id=%s and (camp_type is null or camp_type<>'OB')", str(old))]
        for v in dict.fromkeys(x.strip() for x in names):
            if v and v not in ob_ids and DIALER_VALUE.match(v):
                wanted.append(("ingroup", v))
        for kind, value in wanted:
            if (kind, value) in have:
                continue
            if kind == "vendor" and vendor_of.get(value) not in (None, new):
                warn(f"client {old}: vendor id {value} is already used by another client, so it was not added")
                counts["vendor ids not added (value already used by another client)"] += 1
                continue
            db.add(DialerId(client_id=new, kind=kind, value=value))
            have.add((kind, value))
            if kind == "vendor":
                vendor_of[value] = new
            counts[f"dialer ids ({kind})"] += 1


TYPE = {"TextBox": "text", "TextArea": "textarea", "DropDown": "select"}
VALID = {"Alphanumeric": "alphanumeric", "Char": "alpha", "Numeric": "numeric"}


def step_forms(db, cur, mp, only):
    for k, new in list(mp.m.items()):
        if k[0] != "client":
            continue
        old = int(k[1])
        if only and old not in only:
            continue
        keys = set(db.scalars(select(FormField.key).where(FormField.client_id == new, FormField.context == "in_call")))
        for f in rows(cur, "select * from field_master where ClientId=%s and (FieldStatus is null or FieldStatus<>'D') order by Priority, id", old):
            if mp.get("field", f["id"]):
                continue
            label = s(f["FieldName"], 120)
            if not label:
                continue
            ftype, val = TYPE.get(f["FieldType"], "text"), VALID.get(f["FieldValidation"], "none")
            if f["FieldValidation"] == "Datepicker":
                ftype, val = "date", "none"
            elif f["FieldValidation"] == "Phone":
                ftype, val = "phone", "none"
            base = fs.slug(label)
            base = f"{base}_field" if base in fs.RESERVED_KEYS else base
            key, n = base, 1
            while key in keys:
                n += 1
                key = f"{base[:36]}_{n}"
            keys.add(key)
            ff = FormField(client_id=new, context="in_call", key=key, label=label, field_type=ftype, validation=val, required=s(f["RequiredCheck"]) == "1",
                           sort_order=f["Priority"] or 0, show_always=True)
            if ftype == "select":
                vals = [s(v["FieldValueName"], 200) for v in rows(cur, "select FieldValueName from field_master_value where FieldId=%s and (FieldStatus is null or FieldStatus<>'D') order by id", f["id"])]
                vals = [v for v in dict.fromkeys(vals) if v]
                vl = ValueList(client_id=new, name=label, level_names=[label[:120]], is_private=True)
                db.add(vl)
                db.flush()
                for i, v in enumerate(vals):
                    db.add(ValueItem(list_id=vl.id, level=1, label=v, sort_order=i))
                ff.value_list_id, ff.list_level = vl.id, 1
            db.add(ff)
            db.flush()
            mp.set("field", f["id"], ff.id)
            # old calls kept the answer in column Field<fieldNumber> of call_master; remember which new field that is
            mp.set(f"fieldno:{old}", f["fieldNumber"], ff.id)
            counts["form fields"] += 1


def step_scenarios(db, cur, mp, only):
    orphans: Counter = Counter()
    for k, new in list(mp.m.items()):
        if k[0] != "client":
            continue
        old = int(k[1])
        if only and old not in only:
            continue
        order = 0
        for e in rows(cur, "select id, ecrName, parent_id, Label from ecr_master where Client=%s order by Label, id", str(old)):
            if mp.get("ecr", e["id"]):
                continue
            name = s(e["ecrName"], 150)
            level = int(e["Label"] or 1)
            if not name or not 1 <= level <= 5:
                continue
            parent = None
            if level > 1:
                parent = mp.get("ecr", s(e["parent_id"]))
                if not parent:
                    orphans[old] += 1  # a branch whose top was deleted in the old CRM
                    continue
            order += 1
            sc = Scenario(client_id=new, context="in_call", parent_id=parent, level=level, name=name, sort_order=order)
            db.add(sc)
            db.flush()
            mp.set("ecr", e["id"], sc.id)
            counts[f"scenarios level {level}"] += 1
    for old, n in orphans.items():
        warn(f"client {old}: {n} scenario option(s) skipped because their parent was deleted in the old CRM")
    counts["scenario options skipped (deleted parent)"] += sum(orphans.values())



# =====================================================================
# Part 2: plans, outbound campaigns, call history, tickets, leads
# =====================================================================

def ts(v):
    """An old (local, naive) datetime as an aware datetime; None when empty or 0000-00-00."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.strip().replace("T", " "))
        except ValueError:
            return None
    if isinstance(v, datetime) and v.year > 2000:
        return v.replace(tzinfo=TZ)
    return None


def since():
    return f"DATE_SUB(NOW(), INTERVAL {int(OPTS['months'])} MONTH)"


def stream(sql, *args):
    """Rows of a big query without loading them all (own connection: a streaming cursor blocks the connection)."""
    conn = old_db()
    c = conn.cursor(pymysql.cursors.SSDictCursor)
    try:
        c.execute(sql, args)
        while True:
            batch = c.fetchmany(CHUNK)
            if not batch:
                break
            yield batch
    finally:
        c.close()
        conn.close()


def clients_map(mp, only):
    return {int(k[1]): v for k, v in mp.m.items() if k[0] == "client" and (not only or int(k[1]) in only)}


_agents: dict = {}


def agent_user(db, cur, mp, old_id):
    """The user for an old agent id. Agents that were not migrated (inactive ones) are created switched off, so history keeps names."""
    if old_id in _agents:
        return _agents[old_id]
    new = mp.get("agent", old_id)
    if not new:
        a = rows(cur, "select * from agent_master where id=%s", old_id)
        a = a[0] if a else None
        email = f"agent{old_id}@legacy.invalid"
        u = User(name=(s(a["displayname"], 120) if a else "") or f"Agent {old_id} (old CRM)", email=email, phone=None, user_type="agent",
                 role_id=role_id(db, "agent"), dialer_agent_id=(s(a["username"], 60) or None) if a else None, is_active=False,
                 hashed_password=hash_password(secrets.token_urlsafe(24)))
        exists = db.scalar(select(User.id).where(User.email == email))
        if exists:
            new = exists
        else:
            db.add(u)
            db.flush()
            new = u.id
            counts["agents created switched off (they only appear in history)"] += 1
        mp.set("agent", old_id, new)
    _agents[old_id] = new
    return new


# ---------- plans ----------

PERIOD = {"MONTH": "monthly", "MONTHLY": "monthly", "QUATER": "quarterly", "QUARTER": "quarterly", "HALF": "half_yearly", "YEAR": "yearly", "YEARLY": "yearly"}
PLAN_FIELDS = {
    "setup_fee": "SetupCost", "subscription_amount": "RentalAmount", "credit_value": "CreditValue", "credit_value_per_mode": "CreditValuePerMode",
    "subscription_credit_pct": "CreditPointPercent", "topup_talktime_pct": "TalktimePercent", "balance_carry_forward": "TransferAfterRental",
    "first_minute": "first_minute", "ib_day_charge": "InboundCallCharge", "ib_day_pulse": "pulse_day_shift", "ib_night_charge": "InboundCallChargeNight",
    "ib_night_pulse": "pulse_night_shift", "ob_charge": "OutboundCallCharge", "ob_pulse": "pulse_outbound_call_shift", "ml_ib_charge": "MultiIBCharges",
    "ml_ib_pulse": "pulse_ib_multi", "ml_ob_charge": "MultiOBCharges", "ml_ob_pulse": "pulse_ob_multi", "miss_call_charge": "MissCallCharge",
    "ivr_charge": "IVR_Charge", "vfo_charge": "VFOCallCharge", "sms_charge": "SMSCharge", "email_charge": "EmailCharge",
    "whatsapp_charge": "whatsapp_message_charge", "ml_live_chat_charge": "MultiLiveChat", "free_users": "NoOfFreeUser",
    "extra_user_charge": "ChargePerExtraUser", "total_seat": "TotalSeat", "seat_rate": "SeatRate", "remote_user_enabled": "RemoteUser",
    "remote_user_rate": "RemoteUserRate", "total_remote_user": "TotalRemoteUser",
}


def step_plans(db, cur, mp, only):
    cl = clients_map(mp, only)
    if not cl:
        return
    ids = ",".join(str(i) for i in cl)
    bal = rows(cur, f"select * from balance_master where clientId in ({ids}) order by Id")
    plan_ids = sorted({b["PlanId"] for b in bal if b["PlanId"]})
    names = set(db.scalars(select(Plan.name)))
    for p in rows(cur, f"select * from plan_master where Id in ({','.join(str(i) for i in plan_ids) or '0'})"):
        if mp.get("plan", p["Id"]):
            continue
        raw = {"plan_name": s(p["PlanName"], 150) or f"Old plan {p['Id']}", "plan_type": s(p["PlanType"]).lower() or "prepaid",
               "plan_mode": PERIOD.get(s(p["PeriodType"]).upper(), "monthly")}
        for k, col in PLAN_FIELDS.items():
            v = p.get(col)
            if k in ("balance_carry_forward",):
                raw[k] = s(v).lower() == "yes"
            elif k == "first_minute":
                raw[k] = s(v).lower() == "enable"
            elif v not in (None, ""):
                raw[k] = v
        res, errs = plan_svc.normalize(raw)
        for _ in range(3):
            if not errs:
                break
            for k in errs:
                warn(f"plan {p['Id']} {raw['plan_name']!r}: {k} {raw.get(k)!r} is not valid, default used")
                raw.pop(k, None)
            res, errs = plan_svc.normalize(raw)
        name = res.get("plan_name") or raw["plan_name"]
        if name in names:
            name = f"{name} (old plan {p['Id']})"[:150]
        names.add(name)
        plan = Plan(name=name, plan_type=res.get("plan_type", "prepaid") if res.get("plan_type") in plan_svc.PLAN_TYPES else "prepaid",
                    plan_mode=res.get("plan_mode", "monthly"), config=res["config"], status="approved", approved_at=when(p.get("approval_date")),
                    notes=f"Moved from the old CRM (plan {p['Id']}). Approval state there: {p.get('approve_status')}. Check the rates before billing.")
        db.add(plan)
        db.flush()
        mp.set("plan", p["Id"], plan.id)
        counts["plans"] += 1
    for b in bal:
        if mp.get("assignment", b["Id"]) or not mp.get("plan", b["PlanId"]):
            continue
        eff = None
        for col in ("activation_date", "start_date"):
            v = b.get(col)
            if isinstance(v, date) and v.year > 2000:
                eff = v
                break
        if not eff:
            eff = db.get(Client, cl[b["clientId"]]).activated_at.date()
            warn(f"client {b['clientId']}: plan start date missing in the old CRM, used the client's activation date")
        a = PlanAssignment(client_id=cl[b["clientId"]], plan_id=mp.get("plan", b["PlanId"]), effective_from=eff, note="Moved from the old CRM")
        db.add(a)
        db.flush()
        mp.set("assignment", b["Id"], a.id)
        counts["plan assignments"] += 1


# ---------- outbound campaigns (with their forms and scenario trees) ----------

def _name_cols(header):
    """Which of an old campaign's data columns are name, mobile, email, city and reference (by what the column is called)."""
    def first(*words, avoid=()):
        for i, h in enumerate(header):
            t = s(h).lower()
            if t and any(w in t for w in words) and not any(a in t for a in avoid):
                return i
        return None
    m = {"mobile": first("mobile", "phone", "contact number", "contact no", "msisdn", "number", avoid=("code", "policy", "account", "order", "pin")),
         "name": first("name", avoid=("company", "school", "college", "product", "campaign", "file", "dealer", "agent")),
         "email": first("email", "e-mail"), "city": first("city", "town"), "ext_ref": first("customer code", "policy", "ref", "account", "order", "code", "id")}
    if m["name"] is not None and m["name"] == m["mobile"]:
        m["name"] = None
    return m


def step_campaigns(db, cur, mp, only):
    cl = clients_map(mp, only)
    for old_client, new_client in cl.items():
        used_names = set(db.scalars(select(Campaign.name).where(Campaign.client_id == new_client)))
        used_codes = set(db.scalars(select(Campaign.code).where(Campaign.client_id == new_client)))
        for c in rows(cur, "select * from ob_campaign where ClientId=%s order by id", old_client):
            if mp.get("campaign", c["id"]):
                continue
            name = s(c["CampaignName"], 150) or f"Campaign {c['id']}"
            if name in used_names:
                name = f"{name} ({c['id']})"[:150]
            used_names.add(name)
            code = re.sub(r"[^A-Za-z0-9_-]", "", s(c["campaign_id"]))[:30] or f"OB{c['id']}"
            if code in used_codes:
                code = f"{code[:24]}-{c['id']}"
            used_codes.add(code)
            created = ts(c["CreationDate"])
            camp = Campaign(client_id=new_client, name=name, code=code, description=s(c["campaign_description"], 500) or None,
                            status="paused" if s(c["CampaignStatus"]) == "A" else "closed", start_date=created.date() if created else None)
            db.add(camp)
            db.flush()
            mp.set("campaign", c["id"], camp.id)
            counts["campaigns (active ones come in paused: activate when the dialer is ready)"] += 1
            # the campaign id the dialer knows
            dv = s(c["campaign_id"])
            if dv and DIALER_VALUE.match(dv) and not db.scalar(select(DialerId.id).where(DialerId.client_id == new_client, DialerId.kind == "campaign", DialerId.value == dv)):
                db.add(DialerId(client_id=new_client, kind="campaign", value=dv, campaign_id=camp.id))
                counts["dialer ids (campaign)"] += 1
            _ob_form(db, cur, mp, old_client, new_client, c["id"], camp.id)


def _ob_form(db, cur, mp, old_client, new_client, old_camp, new_camp):
    keys: set = set()
    for f in rows(cur, "select * from obfield_master where ClientId=%s and CampaignId=%s and (FieldStatus is null or FieldStatus<>'D') order by Priority, id", old_client, str(old_camp)):
        label = s(f["FieldName"], 120)
        if not label:
            continue
        ftype, val = TYPE.get(f["FieldType"], "text"), VALID.get(f["FieldValidation"], "none")
        if f["FieldValidation"] == "Datepicker":
            ftype, val = "date", "none"
        elif f["FieldValidation"] == "Phone":
            ftype, val = "phone", "none"
        base = fs.slug(label)
        base = f"{base}_field" if base in fs.RESERVED_KEYS else base
        key, n = base, 1
        while key in keys:
            n += 1
            key = f"{base[:36]}_{n}"
        keys.add(key)
        ff = FormField(client_id=new_client, context="out_call", campaign_id=new_camp, key=key, label=label, field_type=ftype, validation=val,
                       required=s(f["RequiredCheck"]) == "1", sort_order=f["Priority"] or 0, show_always=True)
        if ftype == "select":
            vals = [s(v["FieldValueName"], 200) for v in rows(cur, "select FieldValueName from obfield_master_value where FieldId=%s and (FieldStatus is null or FieldStatus<>'D') order by id", f["id"])]
            vals = [v for v in dict.fromkeys(vals) if v]
            vl = ValueList(client_id=new_client, name=label, level_names=[label[:120]], is_private=True)
            db.add(vl)
            db.flush()
            for i, v in enumerate(vals):
                db.add(ValueItem(list_id=vl.id, level=1, label=v, sort_order=i))
            ff.value_list_id, ff.list_level = vl.id, 1
        db.add(ff)
        db.flush()
        mp.set("obfield", f["id"], ff.id)
        if mp.get(f"obfieldno:{old_camp}", f["fieldNumber"]) is None:  # the old CRM sometimes reused a column number
            mp.set(f"obfieldno:{old_camp}", f["fieldNumber"], ff.id)
        else:
            warn(f"campaign {old_camp}: field {label!r} shares column Field{f['fieldNumber']} with another field; its old answers are not moved")
        counts["campaign form fields"] += 1
    order = 0
    for e in rows(cur, "select id, ecrName, parent_id, Label from obecr_master where Client=%s and CampaignId=%s order by Label, id", str(old_client), str(old_camp)):
        name, level = s(e["ecrName"], 150), int(e["Label"] or 1)
        if not name or not 1 <= level <= 5 or mp.get("obecr", e["id"]):
            continue
        parent = mp.get("obecr", s(e["parent_id"])) if level > 1 else None
        if level > 1 and not parent:
            counts["campaign scenario options skipped (deleted parent)"] += 1
            continue
        order += 1
        sc = Scenario(client_id=new_client, context="out_call", campaign_id=new_camp, parent_id=parent, level=level, name=name, sort_order=order)
        db.add(sc)
        db.flush()
        mp.set("obecr", e["id"], sc.id)
        counts["campaign scenarios"] += 1


# ---------- customers, inbound call history and tickets ----------

NAME_FIELDS = ("customer name", "name", "contact name", "caller name", "contact person", "customer", "full name", "cust name", "client name")
CALL_TYPES = ("Inbound", "Manual", "WhatsApp", "Offline Tagging")


def _field_info(db, cur, mp, old_client, new_client):
    """Which Field<N> column holds which answer, and which hold the customer's name, email and city."""
    ids = {n: fid for k, n_, fid in [(k[0], k[1], v) for k, v in mp.m.items() if k[0] == f"fieldno:{old_client}"] for n in [int(n_)]}
    by_id = {f.id: f for f in db.scalars(select(FormField).where(FormField.client_id == new_client, FormField.context == "in_call"))}
    keymap = {n: (by_id[i].key, by_id[i].label) for n, i in ids.items() if i in by_id}
    pos = {"name": None, "email": None, "city": None}
    allf = rows(cur, "select FieldName, fieldNumber from field_master where ClientId=%s order by Priority, id", old_client)
    for want in NAME_FIELDS:
        hit = next((f["fieldNumber"] for f in allf if s(f["FieldName"]).lower() == want), None)
        if hit:
            pos["name"] = hit
            break
    pos["email"] = next((f["fieldNumber"] for f in allf if "email" in s(f["FieldName"]).lower()), None)
    pos["city"] = next((f["fieldNumber"] for f in allf if s(f["FieldName"]).lower() in ("city", "location")), None)
    return keymap, pos


def _ensure_customers(db, new_client, people):
    """people: {mobile: (name, email, city)}. Creates the missing ones; returns {mobile: customer id}."""
    mobiles = list(people)
    found = {m: i for m, i in db.execute(select(Customer.mobile, Customer.id).where(Customer.client_id == new_client, Customer.mobile.in_(mobiles)))}
    new = [m for m in mobiles if m not in found]
    if new:
        db.execute(pg_insert(Customer).values([{"client_id": new_client, "mobile": m, "name": (people[m][0] or f"Customer {m[-4:]}")[:150],
                                                "email": (people[m][1] or None), "city": (people[m][2] or None)} for m in new])
                   .on_conflict_do_nothing(index_elements=["client_id", "mobile"]))
        found.update({m: i for m, i in db.execute(select(Customer.mobile, Customer.id).where(Customer.client_id == new_client, Customer.mobile.in_(new)))})
        counts["customers"] += len(new)
    return found


def step_calls(db, cur, mp, only):
    cl = clients_map(mp, only)
    have_calls = set(db.scalars(select(Interaction.call_id).where(Interaction.call_id.like("legacy-%")))) if not OPTS["dry"] else set()
    for old_client, new_client in cl.items():
        total = rows(cur, f"select count(*) n from call_master where ClientId=%s and CallDate >= {since()} and CallType in %s", old_client, CALL_TYPES)[0]["n"]
        skipped_open = rows(cur, f"select count(*) n from call_master where ClientId=%s and CallDate >= {since()} and CallType='Open'", old_client)[0]["n"]
        counts["calls skipped (opened, never tagged)"] += skipped_open
        if not total:
            continue
        keymap, pos = _field_info(db, cur, mp, old_client, new_client)
        labels = {k: l for k, l in keymap.values()}
        print(f"  client {old_client}: {total} calls", flush=True)
        seen_mobiles: set = set()
        for batch in stream(f"select * from call_master where ClientId=%s and CallDate >= {since()} and CallType in %s order by Id", old_client, CALL_TYPES):
            if OPTS["dry"]:
                for r in batch:
                    m = phone10(r["MSISDN"])
                    if not m:
                        counts["calls skipped (no valid number)"] += 1
                        continue
                    seen_mobiles.add(m)
                    counts["calls"] += 1
                    if r["CloseLoopStatus"] in ("OPEN", "CLOSE"):
                        counts["tickets"] += 1
                continue
            people: dict = {}
            usable = []
            for r in batch:
                if f"legacy-{r['Id']}" in have_calls:
                    continue
                m = phone10(r["MSISDN"])
                if not m:
                    counts["calls skipped (no valid number)"] += 1
                    continue
                usable.append((m, r))
                if m not in people or not people[m][0]:
                    nm = s(r.get(f"Field{pos['name']}")) if pos["name"] else ""
                    people[m] = (nm[:150], s(r.get(f"Field{pos['email']}"))[:255] if pos["email"] else "", s(r.get(f"Field{pos['city']}"))[:100] if pos["city"] else "")
            if not usable:
                continue
            cust = _ensure_customers(db, new_client, people)
            irows, trows = [], []
            for m, r in usable:
                agent = agent_user(db, cur, mp, r["AgentId"] or 0)
                scen = [s(r[f"Category{i}"], 150) for i in range(1, 6) if s(r[f"Category{i}"])]
                answers = {key: s(r[f"Field{n}"], 500) for n, (key, _l) in keymap.items() if s(r.get(f"Field{n}"))}
                started = ts(r["CallDate"])
                if not started:
                    counts["calls skipped (no date)"] += 1
                    continue
                tagged = ts(r["UpdateDate"]) or started
                irows.append({"client_id": new_client, "customer_id": cust[m], "agent_id": agent, "mode": "manual" if r["CallType"] == "Manual" else "inbound",
                              "phone": m, "call_id": f"legacy-{r['Id']}", "status": "tagged", "scenario_path": [], "scenario_names": scen, "answers": answers,
                              "started_at": started, "tagged_at": tagged})
                have_calls.add(f"legacy-{r['Id']}")
                if r["CloseLoopStatus"] in ("OPEN", "CLOSE") and not mp.get("ticket", r["Id"]):
                    closed = r["CloseLoopStatus"] == "CLOSE"
                    done_at = ts(r["CloseLoopingDate"]) or ts(r["UpdateDate"]) or started
                    status = "closed" if closed else ("in_progress" if s(r["CloseLoopCate1"]).lower() in ("in process", "in progress", "wip") else "open")
                    trows.append(({"client_id": new_client, "customer_id": cust[m], "subject": (scen[-1] if scen else "Request")[:200], "description": None,
                                   "priority": "medium", "status": status, "scenario_path": [], "scenario_names": scen, "answers": answers,
                                   "answer_labels": {k: labels.get(k, k) for k in answers}, "created_by_id": agent, "source": "call",
                                   "due_at": ts(r["duedate"]), "resolved_at": done_at if closed else None, "closed_at": done_at if closed else None,
                                   "created_at": started}, r))
            db.execute(insert(Interaction), irows)
            counts["calls"] += len(irows)
            if trows:
                ids = db.execute(insert(Ticket).returning(Ticket.id, sort_by_parameter_order=True), [t for t, _ in trows]).scalars().all()
                comments, maps = [], []
                for tid, (t, r) in zip(ids, trows):
                    maps.append({"kind": "ticket", "old_id": str(r["Id"]), "new_id": tid})
                    mp.m[("ticket", str(r["Id"]))] = tid
                    ref = s(r["callcreated"]) or str(r["Id"])
                    comments.append({"ticket_id": tid, "user_id": None, "kind": "event", "body": f"Moved from the old CRM (reference {ref})", "created_at": t["created_at"]})
                    if s(r["closelooping_remarks"]):
                        comments.append({"ticket_id": tid, "user_id": None, "kind": "comment", "body": s(r["closelooping_remarks"], 2000), "created_at": t["created_at"]})
                db.execute(insert(TicketComment), comments)
                db.execute(insert(LegacyMap), maps)
                counts["tickets"] += len(ids)
            db.flush()
        if OPTS["dry"]:
            counts["customers (distinct numbers, before merging with existing)"] += len(seen_mobiles)
        else:
            db.execute(Ticket.__table__.update().where(Ticket.number.is_(None)).values(number=func.concat("T-", func.lpad(cast(Ticket.id, String), 6, "0"))))
            db.commit()


# ---------- outbound call history ----------

def step_outcalls(db, cur, mp, only):
    cl = clients_map(mp, only)
    have = set(db.scalars(select(Interaction.call_id).where(Interaction.call_id.like("legacy-out-%")))) if not OPTS["dry"] else set()
    alloc_camp = {a["id"]: mp.get("campaign", a["CampaignId"]) for a in rows(cur, "select id, CampaignId from ob_allocation_name")}
    for old_client, new_client in cl.items():
        total = rows(cur, f"select count(*) n from call_master_out where ClientId=%s and CallDate >= {since()}", old_client)[0]["n"]
        if not total:
            continue
        print(f"  client {old_client}: {total} outbound calls", flush=True)
        keymaps: dict = {}
        for batch in stream(f"select * from call_master_out where ClientId=%s and CallDate >= {since()} order by Id", old_client):
            usable = []
            for r in batch:
                camp = alloc_camp.get(r["AllocationId"])
                m = phone10(r["MSISDN"])
                if not camp:
                    counts["outbound calls skipped (campaign not moved)"] += 1
                elif not m:
                    counts["outbound calls skipped (no valid number)"] += 1
                elif f"legacy-out-{r['Id']}" not in have:
                    usable.append((m, camp, r))
            if OPTS["dry"]:
                counts["outbound calls"] += len(usable)
                continue
            if not usable:
                continue
            cust = _ensure_customers(db, new_client, {m: ("", "", "") for m, _, _ in usable})
            irows = []
            for m, camp, r in usable:
                if camp not in keymaps:
                    oc = rows(cur, "select CampaignId from ob_allocation_name where id=%s", r["AllocationId"])[0]["CampaignId"]
                    by_id = {f.id: f.key for f in db.scalars(select(FormField).where(FormField.campaign_id == camp))}
                    keymaps[camp] = {int(k[1]): by_id[v] for k, v in mp.m.items() if k[0] == f"obfieldno:{oc}" and v in by_id}
                answers = {key: s(r.get(f"Field{n}"), 500) for n, key in keymaps[camp].items() if s(r.get(f"Field{n}"))}
                scen = [s(r[f"Category{i}"], 150) for i in range(1, 6) if s(r[f"Category{i}"])]
                started = ts(r["CallDate"])
                if not started:
                    continue
                irows.append({"client_id": new_client, "campaign_id": camp, "customer_id": cust[m], "agent_id": agent_user(db, cur, mp, r["AgentId"] or 0),
                              "mode": "pd" if s(r["TagType"]) == "PD" else "manual", "phone": m, "call_id": f"legacy-out-{r['Id']}", "status": "tagged",
                              "scenario_path": [], "scenario_names": scen, "answers": answers, "started_at": started, "tagged_at": ts(r["UpdateDate"]) or started})
                have.add(f"legacy-out-{r['Id']}")
            db.execute(insert(Interaction), irows)
            counts["outbound calls"] += len(irows)
            db.flush()
        if not OPTS["dry"]:
            db.commit()


# ---------- campaign data (leads) ----------

def step_leads(db, cur, mp, only):
    if OPTS["leads"] == "none":
        return
    cl = clients_map(mp, only)
    for old_client, new_client in cl.items():
        for c in rows(cur, "select * from ob_campaign where ClientId=%s order by id", old_client):
            camp = mp.get("campaign", c["id"])
            if not camp or (OPTS["leads"] == "active" and s(c["CampaignStatus"]) != "A"):
                continue
            header = [s(c[f"Field{i}"]) for i in range(1, 26)] if all(f"Field{i}" in c for i in range(1, 26)) else [s(c.get(f"Field{i}")) for i in range(1, 21)]
            m = _name_cols(header)
            if m["mobile"] is None:
                warn(f"campaign {c['id']} {s(c['CampaignName'])!r} (client {old_client}): no mobile column found in the old data, leads skipped")
                continue
            allocs = {a["id"]: a for a in rows(cur, "select * from ob_allocation_name where CampaignId=%s", c["id"])}
            if not allocs:
                continue
            existing = set(db.scalars(select(Lead.mobile).where(Lead.campaign_id == camp))) if not OPTS["dry"] else set()
            batches: dict = {}
            n_ok = n_dup = n_bad = 0
            for batch in stream(f"select * from ob_campaign_data where AllocationId in ({','.join(str(i) for i in allocs)}) and CreationDate >= {since()} order by id"):
                out = []
                for r in batch:
                    mob = phone10(r.get(f"Field{m['mobile'] + 1}"))
                    nm = " ".join(s(r.get(f"Field{m['name'] + 1}")).split()) if m["name"] is not None else ""
                    if not mob:
                        n_bad += 1
                        continue
                    if mob in existing:
                        n_dup += 1
                        continue
                    existing.add(mob)
                    n_ok += 1
                    if OPTS["dry"]:
                        continue
                    used = {x for x in m.values() if x is not None}
                    extra = {header[i]: s(r.get(f"Field{i + 1}"), 200) for i in range(len(header)) if header[i] and i not in used and s(r.get(f"Field{i + 1}"))}
                    alloc = r["AllocationId"]
                    if alloc not in batches:
                        a = allocs[alloc]
                        b = CampaignBatch(client_id=new_client, campaign_id=camp, filename=s(a["AllocationName"], 200) or f"Allocation {alloc}",
                                          total_rows=int(re.sub(r"\D", "", s(a["TotalCount"])) or 0), accepted=0, created_at=ts(a["CreateDate"]) or datetime.now(timezone.utc))
                        db.add(b)
                        db.flush()
                        batches[alloc] = b.id
                    called = s(r["DataStatus"]) == "call"
                    out.append({"client_id": new_client, "campaign_id": camp, "batch_id": batches[alloc], "name": (nm or f"Customer {mob[-4:]}")[:150], "mobile": mob,
                                "email": (s(r.get(f"Field{m['email'] + 1}")).lower()[:255] or None) if m["email"] is not None else None,
                                "city": (s(r.get(f"Field{m['city'] + 1}"))[:100] or None) if m["city"] is not None else None,
                                "ext_ref": (s(r.get(f"Field{m['ext_ref'] + 1}"))[:100] or None) if m["ext_ref"] is not None else None, "extra": dict(list(extra.items())[:20]),
                                "status": "done" if called else "new", "attempts": 1 if called else 0, "last_called_at": ts(r["CallDate"]) if called else None,
                                "created_at": ts(r["CreationDate"]) or datetime.now(timezone.utc)})
                if out:
                    db.execute(pg_insert(Lead).values(out).on_conflict_do_nothing(index_elements=["campaign_id", "mobile"]))
            if not OPTS["dry"]:
                # customers made from call history only have a made-up name; use the real name from the data
                db.execute(__import__("sqlalchemy").text("update customers c set name = l.name from leads l where l.client_id = c.client_id and l.mobile = c.mobile "
                                                         "and l.campaign_id = :camp and c.name like 'Customer %' and l.name not like 'Customer %'"), {"camp": camp})
                for alloc, bid in batches.items():
                    b = db.get(CampaignBatch, bid)
                    b.accepted = db.scalar(select(func.count()).select_from(Lead).where(Lead.batch_id == bid))
                db.commit()
            counts["leads"] += n_ok
            counts["leads skipped (duplicate number in the campaign)"] += n_dup
            counts["leads skipped (no valid number)"] += n_bad
            print(f"  campaign {c['id']} {s(c['CampaignName'])[:40]!r}: {n_ok} leads", flush=True)



# ---------- alerts ----------

SPECIAL = {"scenario": "scenario", "name": "customer", "customer name": "customer", "contact": "mobile", "contact no": "mobile", "contact number": "mobile",
           "mobile": "mobile", "mobile no": "mobile", "phone": "mobile", "number": "mobile", "calling phone no.": "mobile", "srno": "number", "sr no": "number", "ticket id": "number",
           "ticket no": "number", "ticket number": "number", "tracking number": "number", "agent": "agent", "agent name": "agent"}


def alert_text(raw) -> str:
    """An old alert template (HTML, with :Name: style placeholders) as plain text with {placeholders}."""
    import html as _html
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", s(raw))
    t = _html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\2", t)   # markdown links: keep the address
    t = t.replace("{", "(").replace("}", ")")

    def swap(m):
        name = m.group(1).strip()
        low = name.lower()
        if low.startswith("sub scenario"):
            return "{scenario}"
        return "{" + SPECIAL.get(low, fs.slug(name)) + "}"
    t = re.sub(r":([A-Za-z][A-Za-z0-9 ./-]*?):", swap, t)
    lines: list[str] = []
    for ln in t.replace("\r", "").split("\n"):
        ln = ln.strip()
        if ln and (not lines or lines[-1] != ln):  # no blank lines, and "Scenario" + "Sub scenario" collapse into one
            lines.append(ln)
    return "\n".join(lines)


def _chan(v):
    v = s(v).lower()
    return {"sms": ["sms"], "email": ["email"], "whatsapp": ["whatsapp"], "both": ["email", "sms"], "all": ["email", "sms", "whatsapp"]}.get(v, [])


def step_alerts(db, cur, mp, only):
    from app.models import AlertRule
    cl = clients_map(mp, only)
    ids = ",".join(str(i) for i in cl) or "0"
    made = 0

    def add(kind, old_id, client, name, event, conditions, recipients, channels, message):
        nonlocal made
        if mp.get(kind, old_id):
            return
        r = AlertRule(client_id=client, name=name[:120], event=event, conditions=conditions, recipients=recipients, channels=channels, message=message or None, is_active=True)
        db.add(r)
        db.flush()
        mp.set(kind, old_id, r.id)
        made += 1
        counts["alert rules"] += 1

    def people(email, phone, channels):
        em = s(email).lower() if EMAIL.match(s(email).lower()) else ""
        ph = phone10(phone)
        return ([em] if em and "email" in channels else []), ([ph] if ph and ("sms" in channels or "whatsapp" in channels) else [])

    # 1. alert_mechanisms: by scenario, to the caller or to a person
    for a in rows(cur, f"select * from alert_mechanisms where client_id in ({ids}) order by id"):
        new = cl[a["client_id"]]
        cat, channels = s(a["alert_category"]), _chan(a["alert_on"])
        scen = [s(a[f"scenario{i}"]) for i in range(1, 6) if s(a[f"scenario{i}"])]
        cond = {"scenario_contains": scen[-1][:100]} if scen else {}
        if cat == "caller" and a["abandon"]:
            warn(f"client {a['client_id']}: the SMS to callers of abandoned calls ({s(a['template_name'])!r}) was not moved: abandoned-call events are not available yet")
            counts["alert rules not moved (abandoned-call SMS)"] += 1
            continue
        em, ph = people(a["email"], a["phone"], channels)
        recipients = {"assignee": False, "agent": False, "customer": cat == "caller", "users": [], "emails": em, "mobiles": ph}
        if not (recipients["customer"] or em or ph):
            warn(f"client {a['client_id']}: alert {a['id']} has nobody to tell, skipped")
            continue
        event = {"escalation": "sla_breached", "closeloop": "ticket_resolved"}.get(cat, "call_tagged")
        who = "the caller" if cat == "caller" else (s(a["person_name"]) or s(a["email"]))
        add("alert_mech", a["id"], new, f"Moved: {s(a['template_name']) or 'alert'} to {who}" + (f" ({scen[-1]})" if scen else ""), event, cond, recipients,
            channels or ["email"], alert_text(a["template_text"]))

    # 2. incall_action_matrix: tell a person when a close-loop action is taken
    def event_for(name_a, name_b):
        t = f"{s(name_a)} {s(name_b)}".lower()
        if any(w in t for w in ("clos", "done", "resolv", "complete")):
            return "ticket_resolved"
        if any(w in t for w in ("allocat", "assign")):
            return "ticket_assigned"
        return None

    for m in rows(cur, f"select * from incall_action_matrix where clientId in ({','.join(repr(str(i)) for i in cl) or chr(48)}) order by id"):
        new = cl[int(m["clientId"])]
        ev = event_for(m["call_action_type_name"], m["call_action_sub_type_name"])
        channels = _chan(m["alertOn"])
        em, ph = people(m["email"], m["mobileNo"], channels)
        if not ev:
            warn(f"client {m['clientId']}: close-loop action {s(m['call_action_type_name'])!r} / {s(m['call_action_sub_type_name'])!r} has no matching ticket event, alert skipped")
            continue
        if not (em or ph):
            continue
        add("alert_matrix", m["id"], new, f"Moved: tell {s(m['personName']) or 'person'} when {s(m['call_action_type_name'])} / {s(m['call_action_sub_type_name'])}".replace(" / )", ")"), ev, {},
            {"assignee": False, "agent": False, "customer": False, "users": [], "emails": em, "mobiles": ph}, channels, None)

    # 3. incall_action_sms: SMS to the customer when a close-loop action is taken
    for m in rows(cur, f"select * from incall_action_sms where clientId in ({ids}) order by id"):
        new = cl[m["clientId"]]
        ev = event_for(m["call_action_type_name"], m["call_action_sub_type_name"]) or ("ticket_resolved" if "resolv" in s(m["smsText"]).lower() or "clos" in s(m["smsText"]).lower() else None)
        if not ev:
            warn(f"client {m['clientId']}: SMS for action {s(m['call_action_type_name'])!r} has no matching ticket event, skipped")
            continue
        add("alert_sms", m["id"], new, f"Moved: SMS to the customer when {s(m['call_action_type_name'])}", ev, {},
            {"assignee": False, "agent": False, "customer": True, "users": [], "emails": [], "mobiles": []}, ["sms"], alert_text(m["smsText"]))
    # what we deliberately leave behind



def _path(row, prefix=""):
    """The scenario path an old alert row applies to: the names down to the first 'All'. () = every call."""
    out = []
    for k in ("categoryName", "typeName", "subtypeName", "subtype1Name", "subtype2Name"):
        v = s(row.get(k))
        if not v or v.lower() == "all":
            break
        out.append(v)
    return tuple(out)


def _tat(v) -> int:
    m = re.search(r"\d+", s(v))
    return int(m.group()) if m and int(m.group()) > 0 else 0


def step_alertmatrix(db, cur, mp, only):
    """The old alert matrix: who is told (tbl_matrix), what is sent (tbl_sms, tbl_template) and escalation after the TAT.
    The outbound versions (tbl_ob*) work the same and are limited to one campaign."""
    import hashlib
    from app.models import AlertRule
    cl = clients_map(mp, only)
    if not cl:
        return
    quoted = ",".join(repr(str(i)) for i in cl)
    for scope, tm, ts_, tt, ccol in (("in", "tbl_matrix", "tbl_sms", "tbl_template", ("clientId", "clientId", "client_id")),
                                      ("ob", "tbl_obmatrix", "tbl_obsms", "tbl_obtemplate", ("clientId", "clientId", "clientId"))):
        atcol = {"tbl_template": "alert_type"}
        # message templates, split into "to the customer" (sendType 0) and "to the people in the matrix" (sendType 1)
        customer_msgs: dict = {}
        internal: dict = {}
        for table, col, channel, textcol in ((ts_, ccol[1], "sms", "smsText"), (tt, ccol[2], "whatsapp", "variable_list")):
            at = atcol.get(table, "alertType")
            for r in rows(cur, f"select * from {table} where cast({col} as char) in ({quoted}) order by id"):
                text = alert_text(r.get(textcol))
                if not text:
                    continue
                camp = mp.get("campaign", r["campaignid"]) if scope == "ob" else None
                if scope == "ob" and not camp:
                    continue
                key = (int(r[col]), camp, s(r[at]) or "Alert", _path(r))
                (customer_msgs if s(r.get("sendType")) == "0" else internal).setdefault(key, {}).setdefault(channel, text)

        def message_for(key, channel):
            for k in (key, key[:3] + ((),)):
                m = internal.get(k, {})
                if channel in m:
                    return m[channel]
                if channel == "email" and m:
                    return next(iter(m.values()))
            return None

        # people to tell
        groups: dict = {}
        for m in rows(cur, f"select * from {tm} where cast(clientId as char) in ({quoted}) order by id"):
            camp = mp.get("campaign", m["campaignid"]) if scope == "ob" else None
            if scope == "ob" and not camp:
                continue
            channels = _chan(m["alertOn"])
            em, ph = people(m["email"], m["mobileNo"], channels) if False else (None, None)
            email = s(m["email"]).lower() if EMAIL.match(s(m["email"]).lower()) and "email" in channels else ""
            mobile = phone10(m["mobileNo"]) if ("sms" in channels or "whatsapp" in channels) else ""
            if not (email or mobile):
                counts["alert people skipped (no usable address for the channel)"] += 1
                continue
            at = s(m["alertType"]) or "Alert"
            tat = _tat(m.get("tat"))
            lvl = re.search(r"(\d+)$", at)
            hours = (tat or 24 * ((int(lvl.group(1)) if lvl else 0) + 1)) if at.lower().startswith("escalation") else 0
            path = _path(m)
            key = (int(m["clientId"]), camp, at, path)
            msg = message_for(key, "whatsapp" if channels == ["whatsapp"] else ("sms" if channels == ["sms"] else "email"))
            g = groups.setdefault((key, hours, tuple(channels), msg), {"emails": [], "mobiles": []})
            if email and email not in g["emails"]:
                g["emails"].append(email)
            if mobile and mobile not in g["mobiles"]:
                g["mobiles"].append(mobile)

        def make(key, hours, channels, msg, emails, mobiles, customer):
            old, camp, at, path = key
            event = "ticket_stale" if at.lower().startswith("escalation") else "call_tagged"
            cond = {}
            if path:
                cond["scenario_contains"] = path[-1][:100]
            if camp:
                cond["campaign"] = [camp]
            if event == "ticket_stale":
                cond["hours"] = hours or 24
            uid = hashlib.md5(f"{scope}|{key}|{hours}|{channels}|{msg}|{emails}|{mobiles}|{customer}".encode("utf8")).hexdigest()
            if mp.get("alertx", uid):
                return
            who = "the customer" if customer else ", ".join((emails + mobiles)[:2]) + ("…" if len(emails + mobiles) > 2 else "")
            label = {"call_tagged": "on", "ticket_stale": f"after {cond.get('hours')}h on"}[event]
            rule = AlertRule(client_id=cl[old], name=f"Moved: tell {who} {label} {' > '.join(path) if path else 'every call'}"[:120], event=event, conditions=cond,
                             recipients={"assignee": False, "agent": False, "customer": customer, "users": [], "emails": emails, "mobiles": mobiles},
                             channels=list(channels), message=msg, is_active=True)
            db.add(rule)
            db.flush()
            mp.set("alertx", uid, rule.id)
            counts["alert rules (from the alert matrix)" if not customer else "alert rules (message to the customer)"] += 1

        for (key, hours, channels, msg), g in groups.items():
            em, mo = g["emails"], g["mobiles"]
            for i in range(0, max(len(em), len(mo), 1), 5):   # the alert screen takes up to 5 addresses per rule
                make(key, hours, channels, msg, em[i:i + 5], mo[i:i + 5], False)
        for key, by_channel in customer_msgs.items():
            for channel, text in by_channel.items():
                make(key, (24 if key[2].lower().startswith("escalation") else 0), (channel,), text, [], [], True)
        unused = sum(1 for k in internal if not any(k[:3] == g[0][:3] and (k[3] == g[0][3] or k[3] == ()) for g in groups))
        if unused:
            counts[f"message templates with nobody to send to ({scope})"] += unused


RUN = {"clients": step_clients, "users": step_users, "agents": step_agents, "dialer": step_dialer, "forms": step_forms, "scenarios": step_scenarios,
       "plans": step_plans, "campaigns": step_campaigns, "calls": step_calls, "outcalls": step_outcalls, "leads": step_leads, "alerts": step_alerts, "alertmatrix": step_alertmatrix}


def main():
    ap = argparse.ArgumentParser(description="Move active clients from the old CRM into this one.")
    ap.add_argument("--commit", action="store_true", help="write the changes (default is a dry run)")
    ap.add_argument("--only", default=",".join(STEPS), help="comma list of: " + ", ".join(STEPS))
    ap.add_argument("--client", type=int, action="append", help="old client id (repeat for several); default all active")
    ap.add_argument("--months", type=int, default=12, help="how many months of call history and data to move (default 12)")
    ap.add_argument("--leads", choices=["active", "all", "none"], default="active", help="campaign data: only campaigns still active in the old CRM (default), all, or none")
    a = ap.parse_args()
    OPTS.update(dry=not a.commit, months=a.months, leads=a.leads)
    steps = [x for x in STEPS if x in a.only.split(",")]
    only = set(a.client or [])

    Base.metadata.create_all(bind=engine)
    ensure_columns()
    old = old_db()
    cur = old.cursor()
    db = SessionLocal()
    ensure_system_roles(db)
    mp = Map(db)
    try:
        for st in steps:
            print(f"- {st} ...", flush=True)
            RUN[st](db, cur, mp, only)
            db.flush()
        print("\nResult" + (" (dry run, nothing written)" if not a.commit else " (written)"))
        for k, v in sorted(counts.items()):
            print(f"  {v:>7}  {k}")
        if warnings:
            print(f"\n{len(warnings)} warning(s):")
            for w in warnings[:60]:
                print("  -", w)
            if len(warnings) > 60:
                print(f"  ... and {len(warnings) - 60} more")
        if a.commit:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        old.close()


if __name__ == "__main__":
    sys.exit(main())
