"""The signed-in client's own company profile: they complete it after their account is activated."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, permissions_of, get_current_user
from ..models import Client, User
from ..schemas import OnboardingData
from ..services import onboarding as ob

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _mine(user: User = Depends(get_current_user)) -> User:
    if "profile.manage" not in permissions_of(user) or not user.client_id:
        raise HTTPException(403, "You do not have permission to edit the company profile")
    return user


def _client(db: Session, user: User) -> Client:
    return db.get(Client, user.client_id)


@router.get("")
def read(user: User = Depends(_mine), db: Session = Depends(get_db)):
    return ob.client_out(_client(db, user))


@router.put("")
def save(data: OnboardingData, user: User = Depends(_mine), db: Session = Depends(get_db)):
    client = _client(db, user)
    ob.save_form(db, client, data, lock_identity=True)
    audit(db, user, "profile_updated", client_id=client.id)
    db.commit()
    return ob.client_out(client)


@router.post("/documents", status_code=201)
async def upload_document(doc_type: str = Form(...), file: UploadFile = File(...), user: User = Depends(_mine),
                          db: Session = Depends(get_db)):
    client = _client(db, user)
    doc = await ob.add_document(db, client, doc_type, file)
    audit(db, user, "document_uploaded", client_id=client.id, detail={"doc": doc.id})
    db.commit()
    return ob.client_out(client)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user: User = Depends(_mine), db: Session = Depends(get_db)):
    client = _client(db, user)
    doc = next((d for d in client.documents if d.id == doc_id), None)
    if doc and doc.status == "approved":
        raise HTTPException(409, "An approved document cannot be removed; contact DialDesk if it is wrong")
    ob.remove_document(db, client, doc_id)
    db.commit()
    return ob.client_out(client)


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...), user: User = Depends(_mine), db: Session = Depends(get_db)):
    client = _client(db, user)
    await ob.set_logo(db, client, file)
    db.commit()
    return ob.client_out(client)
