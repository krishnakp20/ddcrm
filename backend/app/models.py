from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# Client lifecycle: submitted (waiting for the admin) -> active | rejected. An active client can be suspended
# and re-activated. After activation the client completes the rest of the profile itself.
CLIENT_STATUSES = ("submitted", "active", "suspended", "rejected")


def now_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[Optional[str]] = mapped_column(String(20), unique=True)  # CL0001, given on activation
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)

    company_name: Mapped[str] = mapped_column(String(200), default="")
    business_type: Mapped[Optional[str]] = mapped_column(String(60))
    website: Mapped[Optional[str]] = mapped_column(String(200))
    gstin: Mapped[Optional[str]] = mapped_column(String(15), index=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10), index=True)

    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(60))
    pincode: Mapped[Optional[str]] = mapped_column(String(6))

    billing_same: Mapped[bool] = mapped_column(Boolean, default=True)
    billing_address: Mapped[Optional[str]] = mapped_column(Text)
    billing_city: Mapped[Optional[str]] = mapped_column(String(100))
    billing_state: Mapped[Optional[str]] = mapped_column(String(60))
    billing_pincode: Mapped[Optional[str]] = mapped_column(String(6))
    billing_email: Mapped[Optional[str]] = mapped_column(String(255))

    services: Mapped[list[Any]] = mapped_column(JSON, default=list)  # inbound, outbound, whatsapp ...
    monthly_volume: Mapped[Optional[str]] = mapped_column(String(40))

    logo_file: Mapped[Optional[str]] = mapped_column(String(255))  # stored file name under the client's folder
    logo_key: Mapped[Optional[str]] = mapped_column(String(40), unique=True)  # random, used in the public logo URL

    terms_version: Mapped[Optional[str]] = mapped_column(String(20))
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    terms_ip: Mapped[Optional[str]] = mapped_column(String(45))

    review_note: Mapped[Optional[str]] = mapped_column(Text)  # reason shown to the client when rejected
    source: Mapped[str] = mapped_column(String(20), default="self")  # self (registered on the login page) | admin
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contacts: Mapped[list["ClientContact"]] = relationship(
        cascade="all, delete-orphan", order_by="ClientContact.position", lazy="selectin"
    )
    documents: Mapped[list["ClientDocument"]] = relationship(
        cascade="all, delete-orphan", order_by="ClientDocument.id", lazy="selectin"
    )


class ClientContact(Base):
    __tablename__ = "client_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # 0 is the primary contact
    name: Mapped[str] = mapped_column(String(120))
    designation: Mapped[Optional[str]] = mapped_column(String(80))
    mobile: Mapped[str] = mapped_column(String(15))
    email: Mapped[str] = mapped_column(String(255))


class ClientDocument(Base):
    __tablename__ = "client_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    review_note: Mapped[Optional[str]] = mapped_column(String(300))
    uploaded_at: Mapped[datetime] = now_col()


class AccessRole(Base):
    """A named set of permissions for one kind of user (staff, client or agent)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[Optional[str]] = mapped_column(String(250))
    user_type: Mapped[str] = mapped_column(String(10))  # staff | client | agent
    permissions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # created by the app; cannot be deleted
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # super admin: cannot be edited at all
    created_at: Mapped[datetime] = now_col()


class Department(Base):
    """Department master. client_id empty = a DialDesk department; otherwise it belongs to that client."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(250))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    hashed_password: Mapped[str] = mapped_column(String(255))
    user_type: Mapped[str] = mapped_column(String(10), default="staff", index=True)  # staff | client | agent
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    # permissions added to / taken away from this one user on top of their role
    extra_permissions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    denied_permissions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    dialer_agent_id: Mapped[Optional[str]] = mapped_column(String(60), index=True)  # the agent's login on the dialer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    password_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()

    client: Mapped[Optional["Client"]] = relationship(lazy="joined")
    role: Mapped[Optional["AccessRole"]] = relationship(lazy="joined")
    department: Mapped[Optional["Department"]] = relationship(lazy="joined")

    @property
    def role_key(self) -> Optional[str]:
        return self.role.key if self.role else None


class PasswordToken(Base):
    """One-time link for setting a password (new users) or resetting it. Only the hash is stored."""

    __tablename__ = "password_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """Every email / SMS / WhatsApp the system sends or would send. status: sent | logged | failed."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(12))
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[Optional[str]] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[Optional[str]] = mapped_column(String(500))
    client_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    client_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


PLAN_STATUSES = ("pending", "approved", "rejected", "retired")


class Plan(Base):
    """A price plan. The rates live in `config` as validated decimal strings (see services/plans.py)."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    plan_type: Mapped[str] = mapped_column(String(12))  # prepaid | postpaid
    plan_mode: Mapped[str] = mapped_column(String(15))  # monthly | quarterly | half_yearly | yearly
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reject_remarks: Mapped[Optional[str]] = mapped_column(Text)
    cloned_from_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by: Mapped[Optional["User"]] = relationship(foreign_keys=[created_by_id], lazy="joined")
    approved_by: Mapped[Optional["User"]] = relationship(foreign_keys=[approved_by_id], lazy="joined")


class PlanAssignment(Base):
    """A client is on a plan from `effective_from` until the next assignment starts."""

    __tablename__ = "plan_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[Optional[str]] = mapped_column(String(300))
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = now_col()
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    plan: Mapped["Plan"] = relationship(lazy="joined")


class BillingExclusion(Base):
    """A user the client is not charged for (not counted as a billable seat)."""

    __tablename__ = "billing_exclusions"
    __table_args__ = (UniqueConstraint("client_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[Optional[str]] = mapped_column(String(200))
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = now_col()


class ValueList(Base):
    """A list of choices for dropdowns, with up to 5 levels (for example Country > State > City).
    client_id empty = a shared list kept by DialDesk; private lists belong to one field and are edited from it."""

    __tablename__ = "value_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(String(250))
    level_names: Mapped[list[Any]] = mapped_column(JSON, default=list)  # ["Country", "State", "City"]
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class ValueItem(Base):
    __tablename__ = "value_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("value_lists.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("value_items.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FormField(Base):
    """One question on a client's call / ticket form."""

    __tablename__ = "form_fields"
    __table_args__ = (UniqueConstraint("client_id", "context", "campaign_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    context: Mapped[str] = mapped_column(String(10))  # in_call (also used for tickets) | out_call
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)  # out_call only
    key: Mapped[str] = mapped_column(String(40))  # stable name the answers are saved under
    label: Mapped[str] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(15), default="text")
    validation: Mapped[str] = mapped_column(String(15), default="none")
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # min_length, max_length, min, max, pattern, default
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    help_text: Mapped[Optional[str]] = mapped_column(String(250))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    show_always: Mapped[bool] = mapped_column(Boolean, default=True)  # else only for the scenarios it is linked to
    value_list_id: Mapped[Optional[int]] = mapped_column(ForeignKey("value_lists.id", ondelete="SET NULL"))
    list_level: Mapped[int] = mapped_column(Integer, default=1)  # which level of the list this field picks from
    parent_field_id: Mapped[Optional[int]] = mapped_column(ForeignKey("form_fields.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = now_col()


class Scenario(Base):
    """A step in the call scenario (disposition) tree, up to 5 levels deep."""

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    context: Mapped[str] = mapped_column(String(10))
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[Optional[str]] = mapped_column(String(15))  # connected | not_connected | callback | converted | closed | dnc
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class ScenarioField(Base):
    """A field that is shown for a scenario (and everything below it), optionally made mandatory there."""

    __tablename__ = "scenario_fields"
    __table_args__ = (UniqueConstraint("scenario_id", "field_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("form_fields.id", ondelete="CASCADE"), index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)


CAMPAIGN_STATUSES = ("draft", "active", "paused", "closed")


class Campaign(Base):
    """An outbound calling campaign of one client. Each campaign has its own tagging form."""

    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("client_id", "name"), UniqueConstraint("client_id", "code"))

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(30))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="draft", index=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DialerId(Base):
    """How the dialer names things. The dialer passes these in the link it opens for the agent:
    vendor = identifies the client (unique across DialDesk), ingroup = an inbound group of that client,
    campaign = the dialer's id for one of the client's CRM campaigns (a campaign can have several)."""

    __tablename__ = "dialer_ids"
    __table_args__ = (
        UniqueConstraint("client_id", "kind", "value"),
        Index("uq_dialer_vendor_value", "value", unique=True, postgresql_where=text("kind = 'vendor'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # vendor | ingroup | campaign
    value: Mapped[str] = mapped_column(String(60), index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    dialer_server_id: Mapped[Optional[int]] = mapped_column(Integer)  # which dialer server this id belongs to; empty = any server
    label: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class AgentClient(Base):
    """A shared DialDesk agent that is allowed to work for a client."""

    __tablename__ = "agent_clients"
    __table_args__ = (UniqueConstraint("user_id", "client_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)


class AgentCampaign(Base):
    """An agent allocated to an outbound campaign (predictive and manual calls)."""

    __tablename__ = "agent_campaigns"
    __table_args__ = (UniqueConstraint("user_id", "campaign_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)


class Customer(Base):
    """Someone a client talks to, found by phone number. One row per client and number."""

    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("client_id", "mobile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    mobile: Mapped[str] = mapped_column(String(15), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    ext_ref: Mapped[Optional[str]] = mapped_column(String(100))  # the client's own customer / policy / order id
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Interaction(Base):
    """One call an agent handled (later also tickets link to it). Answers are saved by field key and by label,
    so changing the form later never changes what was recorded."""

    __tablename__ = "interactions"
    __table_args__ = (UniqueConstraint("agent_id", "call_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(10))  # inbound | pd | manual
    phone: Mapped[str] = mapped_column(String(15))
    call_id: Mapped[Optional[str]] = mapped_column(String(100))
    dialer_vendor: Mapped[Optional[str]] = mapped_column(String(60))
    dialer_group: Mapped[Optional[str]] = mapped_column(String(60))  # ingroup or dialer campaign id as received
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | tagged | skipped
    scenario_path: Mapped[list[Any]] = mapped_column(JSON, default=list)
    scenario_names: Mapped[list[Any]] = mapped_column(JSON, default=list)
    outcome: Mapped[Optional[str]] = mapped_column(String(15))
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    skip_reason: Mapped[Optional[str]] = mapped_column(String(200))
    started_at: Mapped[datetime] = now_col()
    tagged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


LEAD_STATUSES = ("new", "callback", "done", "dnc")


class CampaignBatch(Base):
    """One uploaded file of calling data for a campaign."""

    __tablename__ = "campaign_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    name: Mapped[Optional[str]] = mapped_column(String(120))  # what the agents see when they choose an allocation
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()


class Lead(Base):
    """A person to call in a campaign (uploaded data). One row per campaign and number.
    `assigned_to_id` empty = shared queue. A lead is locked to one agent while that agent has it open."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "mobile"),
        Index("ix_leads_queue", "campaign_id", "status", "next_call_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaign_batches.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    mobile: Mapped[str] = mapped_column(String(15), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    ext_ref: Mapped[Optional[str]] = mapped_column(String(100))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # the other columns of the file, shown to the agent
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    locked_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_call_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    interaction_id: Mapped[Optional[int]] = mapped_column(Integer)  # the latest call made to this lead
    last_outcome: Mapped[Optional[str]] = mapped_column(String(15))
    last_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = now_col()



TICKET_STATUSES = ("open", "in_progress", "pending", "resolved", "closed")
TICKET_PRIORITIES = ("low", "medium", "high", "urgent")


class SlaRule(Base):
    """How long a client's tickets of one priority may take to be resolved."""

    __tablename__ = "sla_rules"
    __table_args__ = (UniqueConstraint("client_id", "priority"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    priority: Mapped[str] = mapped_column(String(10))
    resolve_hours: Mapped[int] = mapped_column(Integer)


class Ticket(Base):
    """A request that needs follow-up: raised by an agent (offline, or from a call), a client user or DialDesk staff.
    The inbound form of the client is filled in, so the same questions are asked for calls and tickets."""

    __tablename__ = "tickets"
    __table_args__ = (Index("ix_tickets_client_status", "client_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    interaction_id: Mapped[Optional[int]] = mapped_column(Integer)  # the call it was raised from
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    scenario_path: Mapped[list[Any]] = mapped_column(JSON, default=list)
    scenario_names: Mapped[list[Any]] = mapped_column(JSON, default=list)
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    answer_labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # field key -> label when it was saved
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12), default="manual", server_default="manual")  # manual | call | website | whatsapp | email
    channel_id: Mapped[Optional[int]] = mapped_column(Integer)
    contact_name: Mapped[Optional[str]] = mapped_column(String(150))   # who wrote in, when no customer record exists (email)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TicketComment(Base):
    """The conversation and history of a ticket. kind: comment (written by a person) or event (status, assignment...)."""

    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10), default="comment")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = now_col()



ALERT_EVENTS = ("ticket_created", "ticket_assigned", "ticket_resolved", "sla_due_soon", "sla_breached", "call_tagged")


class AlertRule(Base):
    """Tells the system who to message, on which channels, when something happens for a client.
    conditions: {"priority": [...], "outcome": [...], "scenario_contains": "text", "field_key": "...", "field_value": "..."}
    recipients: {"assignee": bool, "agent": bool, "users": [ids], "emails": [...], "mobiles": [...]}"""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    event: Mapped[str] = mapped_column(String(20), index=True)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recipients: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    channels: Mapped[list[Any]] = mapped_column(JSON, default=list)
    message: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = now_col()


class AlertLog(Base):
    """One time a rule fired. `dedupe` keeps timed alerts (SLA) from being sent again and again."""

    __tablename__ = "alert_logs"
    __table_args__ = (UniqueConstraint("rule_id", "dedupe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(20))
    ref: Mapped[Optional[str]] = mapped_column(String(40))  # ticket number, call id
    dedupe: Mapped[Optional[str]] = mapped_column(String(60))
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = now_col()


class WebhookEndpoint(Base):
    """Lets a client post calling data to a campaign over HTTPS, and (optionally) forwards the same data to the dialer."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hint: Mapped[str] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    dialer_url: Mapped[Optional[str]] = mapped_column(String(500))
    dialer_auth: Mapped[Optional[str]] = mapped_column(String(300))  # sent as the Authorization header
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    accepted_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = now_col()


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(10), default="webhook")  # webhook | upload
    received: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    dialer_status: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = now_col()



INTAKE_KINDS = ("website", "whatsapp", "email")


class IntakeChannel(Base):
    """A way for a client's customers to reach support that becomes tickets: website form, WhatsApp bot, or an email address.
    settings: {"priority": "medium", "assigned_user_id": 5, "assigned_department_id": null}"""

    __tablename__ = "intake_channels"
    __table_args__ = (UniqueConstraint("client_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hint: Mapped[str] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = now_col()


class IntakeMessage(Base):
    """A message already received (by the sender's own message id), so a retry never creates a second ticket,
    and a reply can be found again by the id of the message it answers."""

    __tablename__ = "intake_messages"
    __table_args__ = (UniqueConstraint("channel_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("intake_channels.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    ticket_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = now_col()


class IntakeLog(Base):
    __tablename__ = "intake_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    channel_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10))
    result: Mapped[str] = mapped_column(String(12))  # created | appended | duplicate | rejected
    ticket_number: Mapped[Optional[str]] = mapped_column(String(20))
    detail: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = now_col()


class LegacyMap(Base):
    """Which row of the old CRM became which row here, so a migration can be run again without making duplicates."""

    __tablename__ = "legacy_map"
    __table_args__ = (UniqueConstraint("kind", "old_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    old_id: Mapped[str] = mapped_column(String(60))
    new_id: Mapped[int] = mapped_column(Integer)


class DialerServer(Base):
    """One Vicidial server (or cluster). It pushes its call and agent logs here with its own key, from the IP addresses listed."""

    __tablename__ = "dialer_servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(15), default="vicidial")
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata")  # the server's clock (agent log times are local)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_hint: Mapped[str] = mapped_column(String(12))
    allowed_ips: Mapped[list[Any]] = mapped_column(JSON, default=list)  # empty = nothing is accepted
    default_client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))  # a server used by one client only
    recording_base_url: Mapped[Optional[str]] = mapped_column(String(300))  # where the recording files are served from
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # table -> {"at": ..., "rows": n}
    created_at: Mapped[datetime] = now_col()


class CdrCall(Base):
    """One call from vicidial_log (outbound) or vicidial_closer_log (inbound)."""

    __tablename__ = "cdr_calls"
    __table_args__ = (
        UniqueConstraint("server_id", "source", "source_key"),
        Index("ix_cdr_client_start", "client_id", "start_at"),
        Index("ix_cdr_server_unique", "server_id", "uniqueid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(6))       # log | closer
    source_key: Mapped[str] = mapped_column(String(60))  # closecallid, or uniqueid + lead id for vicidial_log
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)  # empty = not mapped yet
    direction: Mapped[str] = mapped_column(String(3))    # in | out
    campaign_code: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # the dialer campaign, or the ingroup for inbound
    phone: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    agent_user: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    user_group: Mapped[Optional[str]] = mapped_column(String(40))
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    length_sec: Mapped[int] = mapped_column(Integer, default=0)
    queue_sec: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    term_reason: Mapped[Optional[str]] = mapped_column(String(30))
    uniqueid: Mapped[Optional[str]] = mapped_column(String(40))
    lead_id: Mapped[Optional[int]] = mapped_column(Integer)
    list_id: Mapped[Optional[int]] = mapped_column(Integer)
    recording_id: Mapped[Optional[int]] = mapped_column(Integer)  # cdr_recordings.id, joined when both have arrived
    created_at: Mapped[datetime] = now_col()


class CdrRecording(Base):
    """A row of recording_log: where the audio file is. Only the path is stored."""

    __tablename__ = "cdr_recordings"
    __table_args__ = (UniqueConstraint("server_id", "recording_id"), Index("ix_rec_vid", "server_id", "vicidial_id"), Index("ix_rec_lead", "server_id", "lead_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"))
    recording_id: Mapped[int] = mapped_column(Integer)
    vicidial_id: Mapped[Optional[str]] = mapped_column(String(40))  # uniqueid (or closecallid) of the call it belongs to
    lead_id: Mapped[Optional[int]] = mapped_column(Integer)
    agent_user: Mapped[Optional[str]] = mapped_column(String(40))
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    length_sec: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[Optional[str]] = mapped_column(String(200))
    location: Mapped[Optional[str]] = mapped_column(String(400))
    created_at: Mapped[datetime] = now_col()


class AgentLog(Base):
    """A row of vicidial_agent_log (one stretch of an agent's work: pause, wait, talk, wrap-up)."""

    __tablename__ = "agent_log"
    __table_args__ = (UniqueConstraint("server_id", "log_id"), Index("ix_agentlog_day", "server_id", "agent_user", "event_at"))

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"))
    log_id: Mapped[int] = mapped_column(Integer)
    agent_user: Mapped[str] = mapped_column(String(40))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    campaign_code: Mapped[Optional[str]] = mapped_column(String(40))
    user_group: Mapped[Optional[str]] = mapped_column(String(40))
    client_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    pause_sec: Mapped[int] = mapped_column(Integer, default=0)
    wait_sec: Mapped[int] = mapped_column(Integer, default=0)
    talk_sec: Mapped[int] = mapped_column(Integer, default=0)
    dispo_sec: Mapped[int] = mapped_column(Integer, default=0)
    dead_sec: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[Optional[str]] = mapped_column(String(10))
    sub_status: Mapped[Optional[str]] = mapped_column(String(30))  # the pause code
    lead_id: Mapped[Optional[int]] = mapped_column(Integer)
    uniqueid: Mapped[Optional[str]] = mapped_column(String(40))


class AprDaily(Base):
    """One agent's day on one client (from the agent log), kept up to date as rows arrive."""

    __tablename__ = "apr_daily"
    __table_args__ = (UniqueConstraint("server_id", "agent_user", "day", "client_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"), index=True)
    agent_user: Mapped[str] = mapped_column(String(40), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    client_key: Mapped[int] = mapped_column(Integer, default=0)  # client id, or 0 when not mapped (a real column for the unique key)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    talk_sec: Mapped[int] = mapped_column(Integer, default=0)
    wait_sec: Mapped[int] = mapped_column(Integer, default=0)
    dispo_sec: Mapped[int] = mapped_column(Integer, default=0)
    dead_sec: Mapped[int] = mapped_column(Integer, default=0)
    pause_sec: Mapped[int] = mapped_column(Integer, default=0)
    breaks: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # category -> seconds (lunch, tea, bio ...)
    first_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PauseCode(Base):
    """What a dialer pause code means for the APR (lunch, tea, bio ...). server_id empty = the same on every server."""

    __tablename__ = "pause_codes"
    __table_args__ = (UniqueConstraint("server_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(20))  # lunch | tea | bio | operation | quality | refresher | training | other


class DialerList(Base):
    """Where a campaign's leads go on a Vicidial server: one fixed list. The server's own script fetches the queued leads and adds them."""

    __tablename__ = "dialer_lists"
    __table_args__ = (UniqueConstraint("campaign_id", "server_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("dialer_servers.id", ondelete="CASCADE"), index=True)
    list_id: Mapped[str] = mapped_column(String(20))            # the Vicidial list id (must exist and belong to the dialer campaign)
    phone_code: Mapped[str] = mapped_column(String(5), default="91")
    dup_check: Mapped[str] = mapped_column(String(12), default="DUPLIST")  # Vicidial's duplicate_check option
    field_map: Mapped[list[Any]] = mapped_column(JSON, default=list)       # [{"to": "city", "from": "city"}]; from = a CRM field or a column of the data
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class LeadDelivery(Base):
    """One lead waiting to be (or already) added to a Vicidial list. Leads are never deleted from the dialer."""

    __tablename__ = "lead_deliveries"
    __table_args__ = (UniqueConstraint("lead_id", "dialer_list_id"), Index("ix_delivery_queue", "dialer_list_id", "status", "id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    dialer_list_id: Mapped[int] = mapped_column(ForeignKey("dialer_lists.id", ondelete="CASCADE"))
    server_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | claimed | sent | duplicate | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dialer_lead_id: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = now_col()
