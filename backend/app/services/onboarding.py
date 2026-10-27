"""Client registration logic shared by the public (self-onboarding) and admin endpoints."""
import os
import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Client, ClientContact, ClientDocument, User
from ..schemas import BasicRegistration, ContactIn, OnboardingData
from . import india

TERMS_VERSION = "2026-10"

DOC_TYPES = {
    "gst_certificate": "GST certificate",
    "pan_card": "PAN card",
    "authorized_person_id": "Authorized person ID",
    "registered_address_proof": "Registered address proof",
    "billing_address_proof": "Billing address proof",
    "authorized_address_proof": "Authorized person address proof",
    "other": "Other document",
}
SERVICES = {"inbound": "Inbound calls", "outbound": "Outbound calls", "whatsapp": "WhatsApp", "email": "Email support"}
VOLUMES = ["Up to 1,000 calls / month", "1,000 - 10,000", "10,000 - 50,000", "More than 50,000"]
BUSINESS_TYPES = ["Private Limited", "Public Limited", "LLP", "Partnership", "Proprietorship", "Trust / NGO", "Government", "Other"]

MAX_DOC_BYTES = 5 * 1024 * 1024
MAX_LOGO_BYTES = 1 * 1024 * 1024
MAX_DOCS = 12
DOC_EXT = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8"}
LOGO_EXT = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".webp": b"RIFF"}
LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
DOC_TYPES_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def fail(fields: dict[str, str], message: str = "Please fix the highlighted fields") -> None:
    raise HTTPException(422, detail={"message": message, "fields": fields})


def client_dir(client_id: int) -> Path:
    path = Path(settings.UPLOAD_DIR) / "clients" / str(client_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean(v: str) -> str:
    return " ".join((v or "").split())


# ---------- saving the form ----------

def check_format(data: OnboardingData) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalises the data and returns (clean values, errors). Blank fields are fine here; submit checks them."""
    errors: dict[str, str] = {}
    d = {
        "company_name": _clean(data.company_name), "business_type": _clean(data.business_type),
        "website": _clean(data.website).lower(), "gstin": _clean(data.gstin).upper().replace(" ", ""),
        "pan": _clean(data.pan).upper().replace(" ", ""), "address": data.address.strip(), "city": _clean(data.city),
        "state": _clean(data.state), "pincode": _clean(data.pincode), "billing_same": data.billing_same,
        "billing_address": data.billing_address.strip(), "billing_city": _clean(data.billing_city),
        "billing_state": _clean(data.billing_state), "billing_pincode": _clean(data.billing_pincode),
        "billing_email": _clean(data.billing_email).lower(), "services": [s for s in data.services if s in SERVICES],
        "monthly_volume": _clean(data.monthly_volume),
    }
    if d["gstin"]:
        err = india.validate_gstin(d["gstin"])
        if err:
            errors["gstin"] = err
        else:
            gst_state = india.GST_STATES[d["gstin"][:2]]
            if not d["state"]:
                d["state"] = gst_state
            elif d["state"] != gst_state:
                errors["state"] = f"The GSTIN belongs to {gst_state}, but the state is {d['state']}"
            derived_pan = d["gstin"][2:12]
            if d["pan"] and d["pan"] != derived_pan:
                errors["pan"] = "PAN does not match the PAN inside the GSTIN"
            d["pan"] = d["pan"] or derived_pan
    if d["pan"] and "pan" not in errors:
        err = india.validate_pan(d["pan"])
        if err:
            errors["pan"] = err
    if d["state"] and d["state"] not in india.STATES:
        errors["state"] = "Choose a state from the list"
    if d["billing_state"] and d["billing_state"] not in india.STATES:
        errors["billing_state"] = "Choose a state from the list"
    for key in ("pincode", "billing_pincode"):
        if d[key] and not india.valid_pincode(d[key]):
            errors[key] = "Pincode must be 6 digits"
    if d["billing_email"] and not india.EMAIL_RE.match(d["billing_email"]):
        errors["billing_email"] = "Enter a valid email"
    if d["website"] and "." not in d["website"]:
        errors["website"] = "Enter a valid website"

    contacts = []
    for i, c in enumerate(data.contacts):
        row = {"name": _clean(c.name), "designation": _clean(c.designation), "mobile": india.normalize_mobile(c.mobile),
               "email": _clean(c.email).lower()}
        if not any(row.values()):
            continue  # an untouched extra contact row
        idx = len(contacts)
        if row["mobile"] and not india.valid_mobile(row["mobile"]):
            errors[f"contacts.{idx}.mobile"] = "Enter a valid 10-digit mobile number"
        if row["email"] and not india.EMAIL_RE.match(row["email"]):
            errors[f"contacts.{idx}.email"] = "Enter a valid email"
        contacts.append(row)
    d["contacts"] = contacts
    return d, errors


def _duplicates(db: Session, client: Client, d: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field, label in (("gstin", "GSTIN"), ("pan", "PAN")):
        if d.get(field):
            other = db.scalar(select(Client.id).where(getattr(Client, field) == d[field], Client.id != (client.id or 0),
                                                      Client.status != "rejected"))
            if other:
                errors[field] = f"A client with this {label} is already registered"
    if d["contacts"] and d["contacts"][0]["email"]:
        email = d["contacts"][0]["email"]
        taken = db.scalar(select(User.id).where(User.email == email, (User.client_id != (client.id or 0)) | (User.client_id.is_(None))))
        if taken:
            errors["contacts.0.email"] = "This email already has a DialDesk account; use another login email"
    return errors


def save_form(db: Session, client: Client, data: OnboardingData, lock_identity: bool = False) -> None:
    """Saves the profile: formats must be right, but fields may still be empty.

    lock_identity is used when the client edits its own profile after activation: company name, GSTIN, PAN and the
    primary contact's login email stay as they are (only DialDesk can change them).
    """
    if lock_identity:
        contacts = [c.model_copy() for c in data.contacts]
        if client.contacts:
            primary = client.contacts[0]
            if not contacts or not any(contacts[0].model_dump().values()):
                contacts = [ContactIn(name=primary.name, designation=primary.designation or "", mobile=primary.mobile,
                                      email=primary.email)] + contacts[1:]
            contacts[0].email = primary.email
        data = data.model_copy(update={"company_name": client.company_name, "gstin": client.gstin or "",
                                       "pan": client.pan or "", "contacts": contacts})
    d, errors = check_format(data)
    errors.update(_duplicates(db, client, d))
    if errors:
        fail(errors)
    keep_as_is = ("company_name", "billing_same", "services")
    for key, value in d.items():
        if key == "contacts":
            continue
        setattr(client, key, value if key in keep_as_is else (value or None))
    client.contacts.clear()
    db.flush()
    for i, c in enumerate(d["contacts"]):
        client.contacts.append(ClientContact(position=i, **c))


def create_basic_client(db: Session, body: BasicRegistration, source: str) -> Client:
    """Creates a client from the short registration form; it waits for the admin with status 'submitted'."""
    data = OnboardingData(company_name=body.company_name, gstin=body.gstin, city=body.city,
                          contacts=[ContactIn(name=body.contact_name, designation=body.designation, mobile=body.mobile,
                                              email=body.email)])
    d, errors = check_format(data)
    for key, label in (("company_name", "Company name"), ("gstin", "GSTIN")):
        if not d[key]:
            errors[key] = f"{label} is required"
    c = d["contacts"][0] if d["contacts"] else {}
    for key, label in (("name", "Contact name"), ("mobile", "Mobile number"), ("email", "Email")):
        if not c.get(key):
            errors[f"contacts.0.{key}"] = f"{label} is required"
    client = Client(status="submitted", source=source)
    errors.update(_duplicates(db, client, d))
    if errors:
        # the short form names its fields differently from the full profile
        rename = {"contacts.0.name": "contact_name", "contacts.0.mobile": "mobile", "contacts.0.email": "email",
                  "contacts.0.designation": "designation"}
        fail({rename.get(k, k): v for k, v in errors.items()})
    db.add(client)
    db.flush()
    save_form(db, client, data)
    return client


def profile_status(client: Client) -> dict[str, Any]:
    """What is still missing from the company profile, shown to the client as a checklist."""
    checks = [
        ("Registered address", bool(client.address and client.city and client.state and client.pincode)),
        ("Billing address", client.billing_same or bool(client.billing_address and client.billing_city
                                                         and client.billing_state and client.billing_pincode)),
        ("Contact persons", bool(client.contacts and all(c.name and c.mobile and c.email for c in client.contacts))),
        ("At least one document", bool(client.documents)),
        ("Company logo", bool(client.logo_file)),
    ]
    done = sum(1 for _, ok in checks if ok)
    return {"percent": round(done * 100 / len(checks)), "items": [{"label": l, "done": ok} for l, ok in checks],
            "complete": done == len(checks)}


# ---------- files ----------

async def _read_checked(file: UploadFile, allowed: dict[str, bytes], limit: int, kind: str) -> tuple[bytes, str]:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(422, f"{kind} must be one of: {', '.join(sorted(allowed))}")
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(422, f"{kind} must be smaller than {limit // (1024 * 1024)} MB")
    if not content.startswith(allowed[ext]):
        raise HTTPException(422, f"This file is not a real {ext} file")
    return content, ext


async def add_document(db: Session, client: Client, doc_type: str, file: UploadFile) -> ClientDocument:
    if doc_type not in DOC_TYPES:
        raise HTTPException(422, "Unknown document type")
    if len(client.documents) >= MAX_DOCS:
        raise HTTPException(422, f"You can upload at most {MAX_DOCS} documents")
    content, ext = await _read_checked(file, DOC_EXT, MAX_DOC_BYTES, "Document")
    stored = f"{uuid.uuid4().hex}{ext}"
    (client_dir(client.id) / stored).write_bytes(content)
    doc = ClientDocument(client_id=client.id, doc_type=doc_type, original_name=(file.filename or stored)[:250],
                         stored_name=stored, content_type=DOC_TYPES_MIME[ext], size=len(content))
    client.documents.append(doc)
    db.flush()
    return doc


def remove_document(db: Session, client: Client, doc_id: int) -> None:
    doc = next((d for d in client.documents if d.id == doc_id), None)
    if not doc:
        raise HTTPException(404, "Document not found")
    (client_dir(client.id) / doc.stored_name).unlink(missing_ok=True)
    client.documents.remove(doc)


async def set_logo(db: Session, client: Client, file: UploadFile) -> None:
    content, ext = await _read_checked(file, LOGO_EXT, MAX_LOGO_BYTES, "Logo")
    if client.logo_file:
        (client_dir(client.id) / client.logo_file).unlink(missing_ok=True)
    client.logo_file = f"logo-{uuid.uuid4().hex[:8]}{ext}"
    client.logo_key = client.logo_key or secrets.token_urlsafe(16)
    (client_dir(client.id) / client.logo_file).write_bytes(content)


# ---------- output ----------

def logo_url(client: Client) -> str | None:
    if not client.logo_file:
        return None
    # the file name is in the URL so a replaced logo is not served from the browser cache
    return f"/api/public/logo/{client.logo_key}?v={client.logo_file}"


def client_out(client: Client) -> dict[str, Any]:
    return {
        "id": client.id, "code": client.code, "status": client.status, "source": client.source,
        "company_name": client.company_name, "business_type": client.business_type or "", "website": client.website or "",
        "gstin": client.gstin or "", "pan": client.pan or "", "address": client.address or "", "city": client.city or "",
        "state": client.state or "", "pincode": client.pincode or "", "billing_same": client.billing_same,
        "billing_address": client.billing_address or "", "billing_city": client.billing_city or "",
        "billing_state": client.billing_state or "", "billing_pincode": client.billing_pincode or "",
        "billing_email": client.billing_email or "", "services": client.services or [],
        "monthly_volume": client.monthly_volume or "", "logo_url": logo_url(client),
        "terms_accepted": bool(client.terms_accepted_at), "terms_accepted_at": client.terms_accepted_at,
        "profile": profile_status(client), "review_note": client.review_note, "submitted_at": client.submitted_at, "activated_at": client.activated_at,
        "created_at": client.created_at,
        "contacts": [{"name": c.name, "designation": c.designation or "", "mobile": c.mobile, "email": c.email}
                     for c in client.contacts],
        "documents": [{"id": d.id, "doc_type": d.doc_type, "label": DOC_TYPES.get(d.doc_type, d.doc_type),
                       "name": d.original_name, "size": d.size, "content_type": d.content_type, "status": d.status,
                       "note": d.review_note} for d in client.documents],
    }
