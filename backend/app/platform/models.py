"""Platform tables (migration 0002). Shapes follow docs/Zippyy_Database_Design with the additions the NDR
autonomy platform needs: delivery preferences, voice calls, agent tasks/runs/steps, contact policies,
consent evidence and delivery-outcome attribution.

Conventions
* `merchant_id` on every tenant row; Postgres row-level security enforces it (migration 0003).
* Status columns are short strings validated by CHECK constraints, so adding a value needs no type change.
* Money is integer paise. Append-only history tables are never updated by application code.
* PII (phone, email, address lines) lives only in `customers`/`addresses`, encrypted (`*_enc`).
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import JSONType, Order, Shipment, ShipmentEvent  # noqa: F401  (re-exported: one import site for all tables)
from app.platform.clock import now
from app.platform.ids import new_id


def _dt() -> DateTime:
    return DateTime(timezone=True)


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _merchant() -> Mapped[str]:
    return mapped_column(ForeignKey("merchants.id"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(_dt(), default=now)


def _updated() -> Mapped[datetime]:
    return mapped_column(_dt(), default=now, onupdate=now)


def _check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ",".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


ROLES = ("owner", "ops_lead", "ops", "finance", "viewer")
NDR_REASONS = ("customer_unavailable", "customer_refused", "address_issue", "phone_unreachable", "cod_not_ready", "other")
NDR_STATUSES = (
    "open", "contacting", "awaiting_customer", "decided", "action_requested",
    "reattempt_scheduled", "escalated", "rto", "resolved", "closed_no_response",
)
NDR_CLOSED = ("resolved", "closed_no_response")
LANGS = ("en", "hi", "te", "ta", "kn", "ml", "mr", "bn", "gu", "pa", "or")


# ================================================================== tenancy, identity, access
class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = (_check("plan", ("starter", "growth", "enterprise"), "ck_merchants_plan"),
                      _check("status", ("onboarding", "active", "suspended"), "ck_merchants_status"))

    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    brand_name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(20), default="growth")
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # demo merchants only ever use simulators
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-cased
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (_check("role", ROLES, "ck_memberships_role"),)

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()


class AuthSession(Base):
    """Web sessions. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[str] = _pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    active_merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(_dt())
    revoked_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(24))  # shown in UI: zpy_live_ab12cd
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSONType, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()


class MerchantSettings(Base):
    """Non-agent business settings. Agent behaviour and contact rules live in versioned `policy_versions`."""

    __tablename__ = "merchant_settings"

    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    message_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    transcript_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    call_recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    unmask_requires_reason: Mapped[bool] = mapped_column(Boolean, default=True)
    ops_alert_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    updated_at: Mapped[datetime] = _updated()
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PolicyVersion(Base):
    """Versioned, schema-validated configuration. Every decision records the version that was active."""

    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("merchant_id", "kind", "version", name="uq_policy_versions"),
        _check("kind", ("agent_config", "contact_policy"), "ck_policy_versions_kind"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    kind: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSONType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created()


# ================================================================== customers and reference data
class Pincode(Base):
    """Reference data. `language_prior` is a *prior* for the first contact, never proof of language."""

    __tablename__ = "pincodes"

    pincode: Mapped[str] = mapped_column(String(6), primary_key=True)
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    language_prior: Mapped[list] = mapped_column(JSONType, default=list)  # [{"lang":"te","weight":0.7},...]


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("merchant_id", "phone_hash", name="uq_customers_phone"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    name: Mapped[str] = mapped_column(String(200))
    phone_enc: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64))
    phone_last4: Mapped[str] = mapped_column(String(4))
    email_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Confirmed preference: only set when the customer stated it or an operator corrected it.
    preferred_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    preferred_language_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    preferred_language_confirmed_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    # Prediction, kept separate: address prior or interaction history.
    predicted_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    predicted_language_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    predicted_language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    opt_out_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pii_erased_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (_check("quality", ("verified", "partial", "unverified"), "ck_addresses_quality"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    line1_enc: Mapped[str] = mapped_column(Text)
    line2_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    landmark_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    quality: Mapped[str] = mapped_column(String(12), default="unverified")
    created_at: Mapped[datetime] = _created()


class ConsentRecord(Base):
    """Evidence-backed consent. A default column value is never treated as consent."""

    __tablename__ = "consent_records"
    __table_args__ = (
        _check("channel", ("whatsapp", "voice", "sms"), "ck_consent_channel"),
        _check("status", ("granted", "revoked"), "ck_consent_status"),
        Index("ix_consent_customer_channel", "customer_id", "channel", "recorded_at"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(40))  # checkout_opt_in | customer_message | operator | api_import
    evidence: Mapped[str] = mapped_column(String(300))  # e.g. "order ZPY-ORD-1042 checkout checkbox v3"
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recorded_at: Mapped[datetime] = _created()


class SimulationProfile(Base):
    """Demo/test-only behaviour for simulated customers and carriers. Read exclusively by simulator adapters."""

    __tablename__ = "simulation_profiles"

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True, unique=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True, unique=True)
    profile: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = _created()


# ================================================================== carriers
class Carrier(Base):
    __tablename__ = "carriers"

    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    adapter: Mapped[str] = mapped_column(String(50))
    api_mode: Mapped[str] = mapped_column(String(12), default="simulated")  # simulated | live
    timeout_ms: Mapped[int] = mapped_column(Integer, default=6000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CarrierCapability(Base):
    __tablename__ = "carrier_capabilities"
    __table_args__ = (
        _check("capability", ("reattempt", "reschedule", "address_change", "phone_change", "rto", "cancel",
                              "otp_delivery", "delivery_window"), "ck_carrier_capability"),
    )

    carrier_id: Mapped[str] = mapped_column(ForeignKey("carriers.id"), primary_key=True)
    capability: Mapped[str] = mapped_column(String(20), primary_key=True)
    constraints: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"max_days_ahead":3,"windows":["09-13"]}


# ================================================================== tracking ingestion
class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"
    __table_args__ = (
        UniqueConstraint("source", "dedupe_key", name="uq_webhook_inbox_dedupe"),
        _check("state", ("pending", "processed", "quarantined", "duplicate", "failed"), "ck_webhook_inbox_state"),
    )

    id: Mapped[str] = _pk()
    source: Mapped[str] = mapped_column(String(40))  # carrier:fastship | whatsapp:meta_cloud | voice:sarvam_agents
    dedupe_key: Mapped[str] = mapped_column(String(200))
    signature_ok: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSONType)
    state: Mapped[str] = mapped_column(String(12), default="pending")
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = _created()
    processed_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class WebhookQuarantine(Base):
    __tablename__ = "webhook_quarantine"
    __table_args__ = (
        _check("reason", ("unparseable", "unknown_awb", "illegal_transition", "bad_signature", "unknown_reference"),
               "ck_webhook_quarantine_reason"),
    )

    id: Mapped[str] = _pk()
    webhook_id: Mapped[str | None] = mapped_column(ForeignKey("webhook_inbox.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(40))
    awb: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (
        UniqueConstraint("shipment_id", "attempt_no", name="uq_delivery_attempts"),
        _check("outcome", ("delivered", "failed"), "ck_delivery_attempts_outcome"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    courier_remark: Mapped[str | None] = mapped_column(String(300), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("shipment_events.id"), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(_dt())


# ================================================================== NDR and AI
class NdrCase(Base):
    __tablename__ = "ndr_cases"
    __table_args__ = (
        _check("reason", NDR_REASONS, "ck_ndr_cases_reason"),
        _check("status", NDR_STATUSES, "ck_ndr_cases_status"),
        # One open case per shipment. RTO cases stay "open" until the return is delivered.
        Index("one_open_ndr_per_shipment", "shipment_id", unique=True,
              postgresql_where=text("status NOT IN ('resolved','closed_no_response')"),
              sqlite_where=text("status NOT IN ('resolved','closed_no_response')")),
        Index("ix_ndr_cases_queue", "merchant_id", "status", "sla_due_at"),
        Index("ix_ndr_cases_opened", "merchant_id", "opened_at"),
        Index("ix_ndr_cases_updated", "merchant_id", "updated_at"),
        Index("ix_ndr_cases_carrier", "merchant_id", "carrier_code", "status"),
        Index("ix_ndr_cases_reason", "merchant_id", "reason", "status"),
    )

    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(20), unique=True)
    merchant_id: Mapped[str] = _merchant()
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    opened_by_event_id: Mapped[str | None] = mapped_column(ForeignKey("shipment_events.id"), nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(30))
    carrier_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # verbatim, courier-reported
    status: Mapped[str] = mapped_column(String(24), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # normal | high | urgent
    recovery_strategy: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(30), nullable=True)  # delivered | rto | cancelled | no_response
    sla_due_at: Mapped[datetime] = mapped_column(_dt())
    last_customer_contact_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    opened_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    updated_at: Mapped[datetime] = _updated()
    # ---- read model for the command center (recomputed by case_summary.refresh in the same transaction) ----
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    order_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    awb: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    carrier_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cod_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)
    language_predicted: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_confirmed: Mapped[str | None] = mapped_column(String(8), nullable=True)
    preferred_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_window: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    call_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_contact_channel: Mapped[str | None] = mapped_column(String(10), nullable=True)
    agent_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pending_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recovery_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contactability: Mapped[str | None] = mapped_column(String(14), nullable=True)
    shipment_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    has_open_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    callback_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_customer", "customer_id", "status"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True, index=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | closed
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)  # WhatsApp 24h window
    last_message_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("merchant_id", "code", "language", "version", name="uq_message_templates"),
        _check("status", ("approved", "pending", "rejected", "paused"), "ck_message_templates_status"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    code: Mapped[str] = mapped_column(String(60))  # ndr_customer_unavailable, predelivery_availability, ...
    language: Mapped[str] = mapped_column(String(8))
    version: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(20), default="utility")
    status: Mapped[str] = mapped_column(String(10), default="approved")
    provider_template_name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)  # with {{1}}, {{2}} placeholders, exactly as approved
    params: Mapped[list] = mapped_column(JSONType, default=list)  # names of placeholders in order
    created_at: Mapped[datetime] = _created()


MESSAGE_STATUSES = ("queued", "submitted", "sent", "delivered", "read", "failed", "received", "blocked")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("provider", "provider_message_id", name="uq_messages_provider_id"),
        _check("direction", ("inbound", "outbound"), "ck_messages_direction"),
        _check("delivery_status", MESSAGE_STATUSES, "ck_messages_status"),
        Index("ix_messages_conversation", "conversation_id", "created_at"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(10))
    channel: Mapped[str] = mapped_column(String(10), default="whatsapp")
    template_id: Mapped[str | None] = mapped_column(ForeignKey("message_templates.id"), nullable=True)
    template_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)  # exact text sent/received (masked after retention)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(10), default="queued")
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    cost_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created()
    sent_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    status_updated_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class MessageStatusEvent(Base):
    """Append-only provider callbacks for outbound messages."""

    __tablename__ = "message_status_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_message_status_events"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_event_id: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(_dt())
    received_at: Mapped[datetime] = _created()


CALL_STATUSES = ("queued", "initiated", "ringing", "answered", "no_answer", "busy", "failed", "completed",
                 "cancelled", "unknown")


class VoiceCall(Base):
    __tablename__ = "voice_calls"
    __table_args__ = (
        UniqueConstraint("provider", "provider_call_id", name="uq_voice_calls_provider_id"),
        _check("status", CALL_STATUSES, "ck_voice_calls_status"),
        Index("ix_voice_calls_merchant_created", "merchant_id", "created_at"),
    )

    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(20), unique=True)
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    agent_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    direction: Mapped[str] = mapped_column(String(10), default="outbound")
    purpose: Mapped[str] = mapped_column(String(30), default="ndr_recovery")  # ndr_recovery | pre_delivery | callback
    status: Mapped[str] = mapped_column(String(12), default="queued")
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)  # preference_captured | refused | ...
    provider_raw_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    start_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    final_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_switch_count: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_for: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    transcript_available: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    preference_captured: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_carrier_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    followup_scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class VoiceCallEvent(Base):
    """Append-only: status callbacks, transcript turns, language detection and switches."""

    __tablename__ = "voice_call_events"
    __table_args__ = (
        UniqueConstraint("call_id", "seq", name="uq_voice_call_events_seq"),
        Index("uq_voice_call_events_provider", "provider_event_id", unique=True,
              postgresql_where=text("provider_event_id IS NOT NULL"), sqlite_where=text("provider_event_id IS NOT NULL")),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    call_id: Mapped[str] = mapped_column(ForeignKey("voice_calls.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # status|turn|language_detected|language_switch|silence|clarification|barge_in|error
    provider_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(10), nullable=True)  # agent | customer
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    from_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    to_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    code_mixed: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(_dt())
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


INTENTS = ("reschedule", "reattempt_today", "available", "refuse", "cancel_order", "address_change", "phone_change",
           "cod_ready", "cod_not_ready", "callback", "opt_out", "language_change", "unclear", "other")


class IntentExtraction(Base):
    __tablename__ = "intent_extractions"
    __table_args__ = (
        _check("validation_status", ("valid", "ambiguous", "invalid"), "ck_intent_validation"),
        Index("ix_intent_case", "ndr_case_id", "created_at"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    call_id: Mapped[str | None] = mapped_column(ForeignKey("voice_calls.id"), nullable=True)
    intent: Mapped[str] = mapped_column(String(30))
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_window: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "18:00-21:00"
    address_change_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_change_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    accepts_delivery: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    extractor: Mapped[str] = mapped_column(String(60))  # rules:v3 | llm:sarvam-105b
    prompt_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(10), default="valid")
    clarification_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    entities: Mapped[dict] = mapped_column(JSONType, default=dict)  # supplementary, non-authoritative
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created()


class RuleDecision(Base):
    __tablename__ = "rule_decisions"
    __table_args__ = (_check("verdict", ("ALLOWED", "REQUIRES_APPROVAL", "DENIED"), "ck_rule_decisions_verdict"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"))
    extraction_id: Mapped[str | None] = mapped_column(ForeignKey("intent_extractions.id"), nullable=True)
    verdict: Mapped[str] = mapped_column(String(20))
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_window: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reasons: Mapped[list] = mapped_column(JSONType, default=list)
    rules_fired: Mapped[list] = mapped_column(JSONType, default=list)
    rules_version: Mapped[str] = mapped_column(String(20))
    policy_version_id: Mapped[str | None] = mapped_column(ForeignKey("policy_versions.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(12), nullable=True)  # pending | approved | rejected
    created_at: Mapped[datetime] = _created()


CARRIER_ACTION_STATUSES = ("requested", "accepted", "rejected", "failed", "timed_out", "retrying", "completed",
                           "cancelled", "unknown")


class CarrierAction(Base):
    __tablename__ = "carrier_actions"
    __table_args__ = (
        _check("action", ("reattempt", "reschedule", "address_change", "phone_change", "rto", "cancel"),
               "ck_carrier_actions_action"),
        _check("status", CARRIER_ACTION_STATUSES, "ck_carrier_actions_status"),
        Index("ix_carrier_actions_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"))
    decision_id: Mapped[str] = mapped_column(ForeignKey("rule_decisions.id"))  # no decision, no action
    carrier_code: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(20))
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_window: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="requested")
    carrier_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    fee_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime] = _created()
    responded_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    updated_at: Mapped[datetime] = _updated()


class CarrierActionEvent(Base):
    __tablename__ = "carrier_action_events"

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    action_id: Mapped[str] = mapped_column(ForeignKey("carrier_actions.id"), index=True)
    status: Mapped[str] = mapped_column(String(12))
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = _created()


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        _check("priority", ("low", "medium", "high", "urgent"), "ck_escalations_priority"),
        _check("status", ("open", "assigned", "resolved"), "ck_escalations_status"),
        Index("ix_escalations_inbox", "merchant_id", "status", "priority", "sla_due_at"),
        Index("one_open_escalation_per_case", "ndr_case_id", unique=True,
              postgresql_where=text("status <> 'resolved'"), sqlite_where=text("status <> 'resolved'")),
    )

    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(20), unique=True)
    merchant_id: Mapped[str] = _merchant()
    ndr_case_id: Mapped[str] = mapped_column(ForeignKey("ndr_cases.id"))
    reason: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="open")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    supervisor_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(String(1000))
    pending_decision_id: Mapped[str | None] = mapped_column(ForeignKey("rule_decisions.id"), nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(_dt())
    resolution_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    resolved_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class EscalationNote(Base):
    __tablename__ = "escalation_notes"

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    escalation_id: Mapped[str] = mapped_column(ForeignKey("escalations.id"), index=True)
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # note|assignment|approval|rejection|correction|resolution|supervisor|retry
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _created()


class DeliveryPreference(Base):
    __tablename__ = "delivery_preferences"
    __table_args__ = (
        _check("status", ("requested", "confirmed_available", "noted", "carrier_pending", "carrier_confirmed",
                          "carrier_rejected", "superseded", "expired"), "ck_delivery_preferences_status"),
        Index("ix_delivery_preferences_shipment", "shipment_id", "created_at"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"))
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_window: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    source_channel: Mapped[str] = mapped_column(String(12))  # whatsapp | voice | operator
    source_extraction_id: Mapped[str | None] = mapped_column(ForeignKey("intent_extractions.id"), nullable=True)
    customer_confirmed_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    carrier_confirmation_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    carrier_action_id: Mapped[str | None] = mapped_column(ForeignKey("carrier_actions.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# ================================================================== agent execution
TASK_STATUSES = ("active", "waiting", "completed", "cancelled", "failed", "escalated", "superseded")


class AgentTask(Base):
    """Durable workflow state. Survives restarts; the worker resumes it from `current_step`."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint("task_type", "shipment_id", "delivery_cycle", name="uq_agent_tasks_cycle"),
        _check("task_type", ("pre_delivery", "ndr_recovery"), "ck_agent_tasks_type"),
        _check("status", TASK_STATUSES, "ck_agent_tasks_status"),
        Index("ix_agent_tasks_due", "status", "next_run_at"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    task_type: Mapped[str] = mapped_column(String(20))
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    delivery_cycle: Mapped[int] = mapped_column(Integer)  # attempt number this task belongs to (dedupe)
    trigger_event: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="active")
    current_step: Mapped[str] = mapped_column(String(40), default="start")
    waiting_for: Mapped[str | None] = mapped_column(String(30), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6)
    correlation_id: Mapped[str] = mapped_column(String(40))
    policy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_merchant_started", "merchant_id", "started_at"),)

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    task_id: Mapped[str | None] = mapped_column(ForeignKey("agent_tasks.id"), nullable=True, index=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True, index=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | completed | failed
    correlation_id: Mapped[str] = mapped_column(String(40))
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    has_failures: Mapped[bool] = mapped_column(Boolean, default=False)
    human_involved: Mapped[bool] = mapped_column(Boolean, default=False)
    next_action: Mapped[str | None] = mapped_column(String(200), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


STEP_STATUSES = ("proposed", "validated", "requested", "accepted", "rejected", "failed", "timed_out", "retrying",
                 "completed", "cancelled", "skipped")


class AgentRunStep(Base):
    """Append-only, ordered operational events that reconstruct a run. Inputs/outputs are sanitized."""

    __tablename__ = "agent_run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_agent_run_steps_seq"),
        _check("status", STEP_STATUSES, "ck_agent_run_steps_status"),
        Index("ix_agent_run_steps_failed", "merchant_id", "status"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # investigate|tool_call|extraction|decision|language|schedule|escalation|note
    purpose: Mapped[str] = mapped_column(String(300))
    tool_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(12))
    input: Mapped[dict] = mapped_column(JSONType, default=dict)
    output: Mapped[dict] = mapped_column(JSONType, default=dict)
    decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extraction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    carrier_action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    policy_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    language_before: Mapped[str | None] = mapped_column(String(8), nullable=True)
    language_after: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ContactAttempt(Base):
    """Contact history: every outbound contact the agent considered, allowed or blocked, and why."""

    __tablename__ = "contact_attempts"
    __table_args__ = (
        Index("ix_contact_attempts_customer", "customer_id", "created_at"),
        _check("outcome", ("allowed", "blocked"), "ck_contact_attempts_outcome"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey("shipments.id"), nullable=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(10))
    purpose: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(10))
    block_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    policy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created()


class DeliveryOutcome(Base):
    """Attribution: was a delivery recovered *because of* Zippyy's contact, or would it have happened anyway?"""

    __tablename__ = "delivery_outcomes"
    __table_args__ = (
        _check("outcome", ("delivered", "rto"), "ck_delivery_outcomes_outcome"),
        _check("attribution", ("recovered_after_contact", "recovered_without_contact", "rto_after_contact",
                               "rto_without_contact", "first_attempt"), "ck_delivery_outcomes_attr"),
    )

    id: Mapped[str] = _pk()
    merchant_id: Mapped[str] = _merchant()
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), unique=True)
    ndr_case_id: Mapped[str | None] = mapped_column(ForeignKey("ndr_cases.id"), nullable=True)
    outcome: Mapped[str] = mapped_column(String(10))
    attribution: Mapped[str] = mapped_column(String(30))
    attributed_to_zippyy: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    order_value_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_cost_paise: Mapped[int] = mapped_column(Integer, default=0)  # measured provider costs only
    carrier_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    determined_at: Mapped[datetime] = _created()


# ================================================================== platform: audit, outbox, jobs
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_merchant_created", "merchant_id", "created_at"),
        _check("actor_type", ("user", "api_key", "agent", "carrier", "system", "provider"), "ck_audit_actor"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    before: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created()


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_merchant_id", "merchant_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    merchant_id: Mapped[str] = mapped_column(String(36))
    aggregate: Mapped[str] = mapped_column(String(30))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = _created()
    published_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    merchant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = _created()


JOB_STATUSES = ("queued", "running", "done", "dead", "cancelled")


class Job(Base):
    """Durable background work. Claimed with FOR UPDATE SKIP LOCKED and a lease; crashed workers' jobs are
    reclaimed after the lease expires."""

    __tablename__ = "jobs"
    __table_args__ = (
        _check("status", JOB_STATUSES, "ck_jobs_status"),
        Index("ix_jobs_due", "status", "run_at"),
        Index("uq_jobs_dedupe", "dedupe_key", unique=True,
              postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('queued','running')"),
              sqlite_where=text("dedupe_key IS NOT NULL AND status IN ('queued','running')")),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    run_at: Mapped[datetime] = _created()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    locked_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(_dt(), nullable=True)


class ProviderCall(Base):
    """Every outbound provider/carrier call: latency and outcome for health and observability. No PII."""

    __tablename__ = "provider_calls"
    __table_args__ = (Index("ix_provider_calls_recent", "provider", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(30))  # whatsapp:meta_cloud | voice:simulator | carrier:FASTSHIP
    operation: Mapped[str] = mapped_column(String(40))
    ok: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


# Tables Postgres RLS is enabled on (migration 0003). Each has a non-null merchant_id.
TENANT_TABLES = (
    "api_keys", "merchant_settings", "policy_versions", "customers", "addresses", "consent_records",
    "simulation_profiles", "delivery_attempts", "ndr_cases", "conversations", "message_templates", "messages",
    "message_status_events", "voice_calls", "voice_call_events", "intent_extractions", "rule_decisions",
    "carrier_actions", "carrier_action_events", "escalations", "escalation_notes", "delivery_preferences",
    "agent_tasks", "agent_runs", "agent_run_steps", "contact_attempts", "delivery_outcomes", "outbox_events",
    "idempotency_keys",
)
# Legacy tables whose merchant_id may be null for MVP sandbox rows; RLS still applies (null rows invisible).
TENANT_TABLES_NULLABLE = ("shipments", "shipment_events", "audit_logs")
