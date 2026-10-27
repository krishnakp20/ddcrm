from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class ContactIn(BaseModel):
    name: str = ""
    designation: str = ""
    mobile: str = ""
    email: str = ""


class OnboardingData(BaseModel):
    """The full company profile. Fields may be blank; the client fills them in over time."""

    company_name: str = ""
    business_type: str = ""
    website: str = ""
    gstin: str = ""
    pan: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    billing_same: bool = True
    billing_address: str = ""
    billing_city: str = ""
    billing_state: str = ""
    billing_pincode: str = ""
    billing_email: str = ""
    services: list[str] = []
    monthly_volume: str = ""
    contacts: list[ContactIn] = Field(default_factory=list, max_length=5)


class BasicRegistration(BaseModel):
    """The short form on the login page (and the admin's 'Add client' form)."""

    company_name: str = ""
    gstin: str = ""
    city: str = ""
    contact_name: str = ""
    designation: str = ""
    mobile: str = ""
    email: str = ""
    terms_accepted: bool = False
    website: str = ""  # hidden honeypot field: real people leave it empty, bots fill it
    activate_now: bool = False  # admin only: activate and send the welcome message straight away


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class DocReviewIn(BaseModel):
    status: str = Field(pattern="^(approved|rejected|pending)$")
    note: Optional[str] = Field(default=None, max_length=300)


class SetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=100)


class TemplatesIn(BaseModel):
    templates: dict[str, str]
