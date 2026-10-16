"""Voice calls: guarded scheduling, idempotent placement, provider callbacks, transcript and language timeline.

Lifecycle states come only from provider callbacks (or reconciliation). Placing a call moves it to `initiated`;
nothing more is assumed until the provider reports. Retries are bounded by the agent config and the contact
guard, so a failing number can never produce a call loop.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.platform import clock, contact_guard, jobs, outbox
from app.platform.customers import first_name, phone_e164
from app.platform.ids import short_code
from app.platform.models import (AgentTask, ContactAttempt, Customer, Merchant, NdrCase, Order, Shipment, VoiceCall,
                                 VoiceCallEvent)
from app.platform.providers.base import CallUpdate, OutcomeUnknown, ProviderError
from app.platform.providers.voice import get_voice

TERMINAL_CALL = ("no_answer", "busy", "failed", "completed", "cancelled")
ANSWERED_RESULTS = ("completed",)


class CallBlocked(Exception):
    def __init__(self, reason: str, retry_at=None):
        super().__init__(reason)
        self.reason = reason
        self.retry_at = retry_at


def schedule_call(db: Session, merchant: Merchant, customer: Customer, shipment: Shipment, purpose: str,
                  language: str, idempotency_key: str, at=None, case: NdrCase | None = None,
                  task: AgentTask | None = None, conversation_id: str | None = None) -> VoiceCall:
    existing = db.scalars(select(VoiceCall).where(VoiceCall.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing
    guard = contact_guard.check(db, merchant, customer, "voice", purpose, shipment.id, case.id if case else None)
    if not guard.allowed:
        raise CallBlocked(guard.reason or "blocked", guard.retry_at)
    attempt_no = (db.scalar(select(func.count()).select_from(VoiceCall).where(
        VoiceCall.ndr_case_id == case.id)) if case else 0) or 0
    call = VoiceCall(code=short_code("CALL"), merchant_id=merchant.id, customer_id=customer.id, shipment_id=shipment.id,
                     ndr_case_id=case.id if case else None, conversation_id=conversation_id,
                     agent_task_id=task.id if task else None, provider=get_voice(merchant.is_demo).name,
                     purpose=purpose, status="queued", idempotency_key=idempotency_key, start_language=language,
                     scheduled_for=at or clock.now(), attempt_no=attempt_no + 1)
    db.add(call)
    db.flush()
    attempt = db.get(ContactAttempt, guard.attempt_id) if guard.attempt_id else None
    if attempt:
        attempt.call_id = call.id
    jobs.enqueue(db, "place_call", {"call_id": call.id}, merchant_id=merchant.id, run_at=at,
                 dedupe_key=f"place:{call.id}", max_attempts=3)
    outbox.emit(db, merchant.id, "voice_call", call.id, "call.scheduled", {"ndrCaseId": call.ndr_case_id})
    return call


def handle_place_call(db: Session, job) -> None:
    call = db.get(VoiceCall, job.payload["call_id"])
    if call is None or call.status != "queued":
        return
    merchant = db.get(Merchant, call.merchant_id)
    customer = db.get(Customer, call.customer_id)
    case = db.get(NdrCase, call.ndr_case_id) if call.ndr_case_id else None
    shipment = db.get(Shipment, call.shipment_id)
    # Re-check at dial time: things change between scheduling and dialing.
    if customer.opted_out_at is not None:
        _cancel(db, call, "customer opted out before the call")
        return
    if case is not None and case.status in ("resolved", "closed_no_response"):
        _cancel(db, call, "case resolved before the call")
        return
    if shipment.current_status in ("DELIVERED", "RTO", "RTO_DELIVERED"):
        _cancel(db, call, f"shipment {shipment.current_status.lower()} before the call")
        return
    order = db.get(Order, shipment.order_id)
    variables = {"customer_first_name": first_name(customer), "brand": merchant.brand_name,
                 "order_ref": order.code or order.merchant_order_id, "purpose": call.purpose,
                 "ndr_reason": case.reason if case else None,
                 "cod_amount": str(int(float(order.cod_amount or 0))) if order.payment_type == "COD" else "0",
                 "language": call.start_language}
    provider = get_voice(merchant.is_demo)
    try:
        provider_call_id = provider.place_call(db, merchant.id, call.id, phone_e164(customer), call.start_language or "en", variables)
    except OutcomeUnknown as exc:
        call.status, call.error_code, call.error_message = "unknown", "outcome_unknown", str(exc)[:300]
        jobs.enqueue(db, "call_outcome_check", {"call_id": call.id}, merchant_id=merchant.id,
                     run_at=clock.now() + timedelta(minutes=20))
        return
    except ProviderError as exc:
        if exc.retryable and job.attempts < job.max_attempts:
            raise
        call.status, call.error_code, call.error_message = "failed", exc.code, str(exc)[:300]
        call.ended_at = clock.now()
        _append(db, call, "status", status="failed", data={"error": exc.code})
        _finished(db, call)
        return
    call.provider_call_id = provider_call_id
    call.status = "initiated"
    call.started_at = clock.now()
    _append(db, call, "status", status="initiated", provider_event_id=None)
    outbox.emit(db, merchant.id, "voice_call", call.id, "call.initiated", {"ndrCaseId": call.ndr_case_id})
    if provider.mode == "simulated":
        from app.platform.simulation import voice_sim
        voice_sim.after_place(db, merchant, customer, call)


def handle_call_outcome_check(db: Session, job) -> None:
    call = db.get(VoiceCall, job.payload["call_id"])
    if call is None or call.status != "unknown":
        return
    # The provider documents no status query: we cannot know. Escalate instead of re-dialling blindly.
    call.status = "failed"
    call.error_message = "provider never confirmed the call; not retried automatically"
    _finished(db, call)


def _cancel(db: Session, call: VoiceCall, reason: str) -> None:
    call.status, call.error_message = "cancelled", reason
    _append(db, call, "status", status="cancelled", data={"reason": reason})
    outbox.emit(db, call.merchant_id, "voice_call", call.id, "call.cancelled", {"ndrCaseId": call.ndr_case_id})


def _next_seq(db: Session, call: VoiceCall) -> int:
    return (db.scalar(select(func.max(VoiceCallEvent.seq)).where(VoiceCallEvent.call_id == call.id)) or 0) + 1


def _append(db: Session, call: VoiceCall, kind: str, **fields) -> VoiceCallEvent:
    ev = VoiceCallEvent(merchant_id=call.merchant_id, call_id=call.id, seq=_next_seq(db, call), kind=kind,
                        occurred_at=fields.pop("occurred_at", None) or clock.now(), **fields)
    db.add(ev)
    db.flush()
    return ev


def apply_update(db: Session, provider: str, upd: CallUpdate) -> str:
    call = db.scalars(select(VoiceCall).where(VoiceCall.provider == provider,
                                              VoiceCall.provider_call_id == upd.provider_call_id)).first()
    if call is None:
        return "unknown_call"
    if db.scalars(select(VoiceCallEvent.id).where(VoiceCallEvent.provider_event_id == upd.provider_event_id)).first():
        return "duplicate"
    if call.status in TERMINAL_CALL:
        return "ignored_terminal"
    try:
        with db.begin_nested():
            _append(db, call, "status", status=upd.status, provider_event_id=upd.provider_event_id,
                    occurred_at=upd.occurred_at, data={"raw_status": upd.raw_status, "failure_reason": upd.failure_reason})
    except IntegrityError:
        return "duplicate"
    call.provider_raw_status = upd.raw_status[:60]
    if upd.status in ("ringing", "answered", "initiated"):
        call.status = upd.status
        if upd.status == "answered":
            call.answered_at = upd.occurred_at
        outbox.emit(db, call.merchant_id, "voice_call", call.id, f"call.{upd.status}", {"ndrCaseId": call.ndr_case_id})
        return "applied"

    # Terminal update: record the conversation.
    start = clock.as_utc(call.started_at) or upd.occurred_at
    lang = upd.start_language or call.start_language
    call.start_language = lang
    switches = 0
    for t in upd.turns:
        at = start + timedelta(seconds=t.offset_seconds or 0)
        if t.kind == "silence":
            _append(db, call, "silence", speaker="customer", occurred_at=at)
            continue
        if t.switched_from:
            switches += 1
            _append(db, call, "language_switch", speaker="customer", from_language=t.switched_from,
                    to_language=t.language, language_confidence=t.language_confidence, code_mixed=t.code_mixed,
                    occurred_at=at)
        _append(db, call, "turn", speaker=t.speaker, text=t.text, text_en=t.text_en, language=t.language,
                language_confidence=t.language_confidence, code_mixed=t.code_mixed, occurred_at=at)
    if not switches:
        switches = len(upd.final_variables.get("language_switches") or [])
    call.language_switch_count = switches
    call.final_language = upd.final_language or (upd.final_variables or {}).get("customer_language") or lang
    call.status = upd.status
    call.duration_seconds = upd.duration_seconds
    call.ended_at = upd.occurred_at
    if upd.status == "completed":
        call.answered_at = call.answered_at or start
    call.transcript_available = bool(upd.turns)
    call.cost_paise = upd.cost_paise
    call.recording_ref = upd.recording_ref
    call.result = (upd.final_variables or {}).get("result") or ({"no_answer": "no_answer", "busy": "busy",
                                                                 "failed": "failed"}.get(upd.status))
    if upd.failure_reason:
        call.error_message = upd.failure_reason[:300]
    case = db.get(NdrCase, call.ndr_case_id) if call.ndr_case_id else None
    if case and upd.status == "completed":
        case.last_customer_contact_at = upd.occurred_at
    _finished(db, call, upd.final_variables)
    return "applied"


def _finished(db: Session, call: VoiceCall, final_variables: dict | None = None) -> None:
    outbox.emit(db, call.merchant_id, "voice_call", call.id, f"call.{call.status}",
                {"ndrCaseId": call.ndr_case_id, "result": call.result, "languageSwitches": call.language_switch_count})
    if call.agent_task_id:
        from app.platform.workflows.engine import trigger
        task = db.get(AgentTask, call.agent_task_id)
        if task is not None:
            trigger(db, task, "call_completed", {"call_id": call.id, "final_variables": final_variables or {}})
