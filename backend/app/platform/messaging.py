"""WhatsApp messaging: approved templates, the 24-hour session window, sending, status callbacks, inbound replies.

Status is monotonic and comes only from provider callbacks:
  queued (row created) -> submitted (provider API accepted) -> sent -> delivered -> read     | failed
A `submitted` message is not "sent" and certainly not "delivered".
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.platform import clock, contact_guard, i18n, jobs, outbox
from app.platform import language as lang_svc
from app.platform.models import (AgentTask, Conversation, Customer, Merchant, Message, MessageStatusEvent,
                                 MessageTemplate)
from app.platform.providers.base import OutcomeUnknown, ProviderError, WhatsAppInbound, WhatsAppStatusEvent
from app.platform.providers.whatsapp import get_whatsapp

RANK = {"queued": 0, "submitted": 1, "sent": 2, "delivered": 3, "read": 4}
SESSION_WINDOW = timedelta(hours=24)


class Blocked(Exception):
    def __init__(self, reason: str, retry_at=None):
        super().__init__(reason)
        self.reason = reason
        self.retry_at = retry_at


def template_for(db: Session, merchant_id: str, code: str, language: str) -> tuple[MessageTemplate | None, bool]:
    """Approved template in the requested language, else the approved English one. Returns (template, exact)."""
    rows = list(db.scalars(select(MessageTemplate).where(
        MessageTemplate.merchant_id == merchant_id, MessageTemplate.code == code,
        MessageTemplate.status == "approved").order_by(MessageTemplate.version.desc())))
    for lang in (language, "en"):
        for row in rows:
            if row.language == lang:
                return row, lang == language
    return None, False


def conversation_for(db: Session, customer: Customer, shipment_id: str | None, ndr_case_id: str | None) -> Conversation:
    q = select(Conversation).where(Conversation.customer_id == customer.id, Conversation.status == "active")
    if shipment_id:
        q = q.where(Conversation.shipment_id == shipment_id)
    conv = db.scalars(q.order_by(Conversation.created_at.desc())).first()
    if conv is None:
        conv = Conversation(merchant_id=customer.merchant_id, customer_id=customer.id, shipment_id=shipment_id,
                            ndr_case_id=ndr_case_id)
        db.add(conv)
        db.flush()
    elif ndr_case_id and conv.ndr_case_id is None:
        conv.ndr_case_id = ndr_case_id
    return conv


def in_session(conv: Conversation) -> bool:
    if conv.last_inbound_at is None:
        return False
    return clock.now() - clock.as_utc(conv.last_inbound_at) < SESSION_WINDOW


def queue_template(db: Session, merchant: Merchant, customer: Customer, code: str, language: str, params: list[str],
                   purpose: str, idempotency_key: str, shipment_id: str | None = None, ndr_case_id: str | None = None,
                   run_id: str | None = None) -> Message:
    existing = db.scalars(select(Message).where(Message.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing
    template, exact = template_for(db, merchant.id, code, language)
    if template is None:
        raise Blocked(f"no_approved_template:{code}")
    guard = contact_guard.check(db, merchant, customer, "whatsapp", purpose, shipment_id, ndr_case_id)
    if not guard.allowed:
        raise Blocked(guard.reason or "blocked", guard.retry_at)
    conv = conversation_for(db, customer, shipment_id, ndr_case_id)
    msg = Message(merchant_id=merchant.id, conversation_id=conv.id, shipment_id=shipment_id, ndr_case_id=ndr_case_id,
                  direction="outbound", channel="whatsapp", template_id=template.id, template_code=code,
                  template_version=template.version, body=i18n.fill_template(template.body, params),
                  language=template.language, provider=get_whatsapp(merchant.is_demo).name,
                  delivery_status="queued", idempotency_key=idempotency_key, agent_run_id=run_id)
    db.add(msg)
    db.flush()
    from app.platform.models import ContactAttempt
    attempt = db.get(ContactAttempt, guard.attempt_id) if guard.attempt_id else None
    if attempt:
        attempt.message_id = msg.id
    conv.language = template.language
    conv.last_message_at = clock.now()
    if not exact:
        msg.failure_reason = None  # sending English instead; recorded on the agent step by the caller
    jobs.enqueue(db, "send_message", {"message_id": msg.id, "params": params, "template_name": template.provider_template_name},
                 merchant_id=merchant.id, dedupe_key=f"send:{msg.id}", max_attempts=4)
    outbox.emit(db, merchant.id, "message", msg.id, "message.queued", {"ndrCaseId": ndr_case_id, "channel": "whatsapp"})
    return msg


def queue_session_text(db: Session, merchant: Merchant, customer: Customer, conv: Conversation, key: str,
                       language: str, idempotency_key: str, run_id: str | None = None, **fmt) -> Message:
    """Free-form reply. Only inside the 24h window that the customer's own message opened."""
    existing = db.scalars(select(Message).where(Message.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing
    if not in_session(conv):
        raise Blocked("outside_session_window")
    guard = contact_guard.check(db, merchant, customer, "whatsapp", "reply", conv.shipment_id, conv.ndr_case_id,
                                is_reply_in_session=True)
    if not guard.allowed:
        raise Blocked(guard.reason or "blocked", guard.retry_at)
    text, used = i18n.line(i18n.SESSION, key, language, **fmt)
    msg = Message(merchant_id=merchant.id, conversation_id=conv.id, shipment_id=conv.shipment_id,
                  ndr_case_id=conv.ndr_case_id, direction="outbound", channel="whatsapp", body=text, language=used,
                  provider=get_whatsapp(merchant.is_demo).name, delivery_status="queued",
                  idempotency_key=idempotency_key, agent_run_id=run_id)
    db.add(msg)
    db.flush()
    conv.last_message_at = clock.now()
    jobs.enqueue(db, "send_message", {"message_id": msg.id, "session": True}, merchant_id=merchant.id,
                 dedupe_key=f"send:{msg.id}", max_attempts=4)
    return msg


def handle_send_message(db: Session, job) -> None:
    msg = db.get(Message, job.payload["message_id"])
    if msg is None or msg.delivery_status != "queued":
        return  # already sent or cancelled: idempotent
    merchant = db.get(Merchant, msg.merchant_id)
    conv = db.get(Conversation, msg.conversation_id)
    customer = db.get(Customer, conv.customer_id)
    if customer.opted_out_at is not None:
        msg.delivery_status, msg.failure_reason = "blocked", "customer opted out before send"
        return
    from app.platform.customers import phone_e164

    provider = get_whatsapp(merchant.is_demo)
    to = phone_e164(customer)
    try:
        if job.payload.get("session"):
            result = provider.send_text(db, merchant.id, to, msg.body, msg.idempotency_key or msg.id)
        else:
            result = provider.send_template(db, merchant.id, to, job.payload["template_name"], msg.language or "en",
                                            job.payload.get("params", []), msg.idempotency_key or msg.id)
    except OutcomeUnknown as exc:
        # WhatsApp has no idempotency key: resending could duplicate. Stop and surface it.
        msg.delivery_status, msg.failure_reason = "failed", f"outcome unknown: {exc}"[:200]
        _notify_failure(db, msg)
        return
    except ProviderError as exc:
        if exc.retryable and job.attempts < job.max_attempts:
            raise
        msg.delivery_status, msg.failure_reason = "failed", f"{exc.code}: {exc}"[:200]
        _notify_failure(db, msg)
        return
    msg.provider_message_id = result.provider_message_id
    msg.delivery_status = "submitted"
    msg.status_updated_at = clock.now()
    outbox.emit(db, merchant.id, "message", msg.id, "message.submitted", {"ndrCaseId": msg.ndr_case_id})
    if provider.mode == "simulated":
        from app.platform.simulation import whatsapp_sim
        whatsapp_sim.after_send(db, merchant, customer, msg)


def _notify_failure(db: Session, msg: Message) -> None:
    outbox.emit(db, msg.merchant_id, "message", msg.id, "message.failed",
                {"ndrCaseId": msg.ndr_case_id, "reason": msg.failure_reason})
    _trigger_tasks_for(db, msg.shipment_id, "message_failed", {"message_id": msg.id})


def _trigger_tasks_for(db: Session, shipment_id: str | None, name: str, data: dict) -> None:
    if not shipment_id:
        return
    from app.platform.workflows.engine import trigger
    for task in db.scalars(select(AgentTask).where(AgentTask.shipment_id == shipment_id,
                                                   AgentTask.status.in_(("active", "waiting")))):
        trigger(db, task, name, data)


def apply_status(db: Session, provider: str, ev: WhatsAppStatusEvent) -> str:
    msg = db.scalars(select(Message).where(Message.provider == provider,
                                           Message.provider_message_id == ev.provider_message_id)).first()
    if msg is None:
        return "unknown_message"
    try:
        with db.begin_nested():
            db.add(MessageStatusEvent(merchant_id=msg.merchant_id, message_id=msg.id, provider=provider,
                                      provider_event_id=ev.provider_event_id, status=ev.status,
                                      error_code=ev.error_code, occurred_at=ev.occurred_at))
    except IntegrityError:
        return "duplicate"
    current = msg.delivery_status
    if ev.status == "failed":
        if current in ("delivered", "read"):
            return "ignored_regression"
        msg.delivery_status = "failed"
        msg.failure_reason = (f"{ev.error_code}: {ev.error_title}" if ev.error_code else ev.error_title or "failed")[:200]
        msg.status_updated_at = clock.now()
        _notify_failure(db, msg)
        return "applied"
    if ev.status not in RANK or RANK.get(current, -1) >= RANK[ev.status] or current == "failed":
        return "ignored_regression"
    msg.delivery_status = ev.status
    msg.status_updated_at = clock.now()
    if ev.status == "sent":
        msg.sent_at = ev.occurred_at
    elif ev.status == "delivered":
        msg.sent_at = msg.sent_at or ev.occurred_at
        msg.delivered_at = ev.occurred_at
    elif ev.status == "read":
        msg.delivered_at = msg.delivered_at or ev.occurred_at
        msg.read_at = ev.occurred_at
    outbox.emit(db, msg.merchant_id, "message", msg.id, f"message.{ev.status}", {"ndrCaseId": msg.ndr_case_id})
    return "applied"


def apply_inbound(db: Session, provider: str, ev: WhatsAppInbound) -> str:
    """Inbound customer text. Matching phone -> customer happens across tenants (system context); everything
    after that is tenant-scoped."""
    from app.platform.security import crypto

    if db.scalars(select(Message.id).where(Message.provider == provider,
                                           Message.provider_message_id == ev.provider_message_id)).first():
        return "duplicate"
    try:
        h = crypto.phone_hash(crypto.normalize_phone(ev.from_e164))
    except ValueError:
        return "invalid_sender"
    customers = list(db.scalars(select(Customer).where(Customer.phone_hash == h)))
    if not customers:
        return "unknown_sender"
    convs = list(db.scalars(select(Conversation).where(
        Conversation.customer_id.in_([c.id for c in customers])).order_by(Conversation.last_message_at.desc().nulls_last())))
    if not convs:
        return "no_conversation"
    conv = convs[0]
    customer = next(c for c in customers if c.id == conv.customer_id)
    det = lang_svc.detect(ev.text)
    msg = Message(merchant_id=conv.merchant_id, conversation_id=conv.id, shipment_id=conv.shipment_id,
                  ndr_case_id=conv.ndr_case_id, direction="inbound", channel="whatsapp", body=ev.text[:4000],
                  language=det.language, language_confidence=det.confidence, provider=provider,
                  provider_message_id=ev.provider_message_id, delivery_status="received", created_at=ev.occurred_at)
    try:
        with db.begin_nested():
            db.add(msg)
    except IntegrityError:
        return "duplicate"
    conv.last_inbound_at = ev.occurred_at
    conv.last_message_at = ev.occurred_at
    conv.status = "active"
    if conv.ndr_case_id:
        from app.platform.models import NdrCase
        case = db.get(NdrCase, conv.ndr_case_id)
        if case:
            case.last_customer_contact_at = ev.occurred_at
    outbox.emit(db, conv.merchant_id, "message", msg.id, "message.received",
                {"ndrCaseId": conv.ndr_case_id, "language": det.language})
    if customer.opted_out_at and ev.text.strip().upper() == "START":
        from app.platform.customers import record_consent
        customer.opted_out_at = None
        record_consent(db, customer, "whatsapp", "granted", "customer_message", f"START reply {msg.id}")
    _trigger_tasks_for(db, conv.shipment_id, "customer_reply", {"message_id": msg.id})
    return "applied"


def process_webhook_payload(db: Session, provider: str, payload: dict) -> dict:
    statuses, inbound = get_provider_parser(provider)(payload)
    out = {"statuses": [], "inbound": []}
    for ev in statuses:
        out["statuses"].append(apply_status(db, provider, ev))
    for ev in inbound:
        out["inbound"].append(apply_inbound(db, provider, ev))
    return out


def get_provider_parser(provider: str):
    from app.platform.providers.whatsapp import parse_meta_payload
    return parse_meta_payload  # simulator and Meta share the Cloud API webhook shape
