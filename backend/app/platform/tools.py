"""Approved agent tool interface (schema version TOOLS_VERSION).

These are the only operations an agent — rule-based today, LLM-driven tomorrow — can perform. There is no SQL
tool, no network tool and no tool that changes shipment state directly. Every call:
  * validates its arguments and its result against versioned pydantic schemas,
  * runs against the task's own tenant and shipment (ids from another tenant/shipment are rejected),
  * checks the agent's permissions, and for mutating tools an idempotency key,
  * is recorded as an `AgentRunStep` with sanitized input and output.
Carrier-changing tools refuse to run without a recorded ALLOWED (or human-approved) rules decision.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.domain.errors import DomainError
from app.platform import audit, carrier_actions, clock, customers as cust_svc, escalations, messaging, policies
from app.platform.calls import CallBlocked, schedule_call
from app.platform.models import (CarrierAction, CarrierCapability, Carrier, DeliveryAttempt, DeliveryPreference,
                                 Message, NdrCase, RuleDecision, VoiceCall)

TOOLS_VERSION = "2026-10.1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShipmentRef(_M):
    shipment_id: str


class ShipmentStatusOut(_M):
    awb: str | None
    carrier: str
    status: str
    attempt_count: int
    eta_end: datetime | None


class OrderOut(_M):
    order_ref: str
    payment_mode: str
    cod_amount_paise: int
    order_value_paise: int | None


class AttemptOut(_M):
    attempt_no: int
    outcome: str
    reason: str | None
    at: datetime


class AttemptsOut(_M):
    attempts: list[AttemptOut]


class PreferencesOut(_M):
    preferred_language: str | None
    preferred_language_source: str | None
    predicted_language: str | None
    opted_out: bool
    latest_requested_date: date | None
    latest_requested_window: str | None
    latest_status: str | None


class OptionsOut(_M):
    capabilities: dict[str, dict]
    max_auto_reschedule_days: int
    max_attempts_before_rto: int


class SavePreferenceIn(_M):
    shipment_id: str
    requested_date: date | None = None
    requested_window: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    language: str | None = None
    language_source: str | None = None
    language_confidence: float | None = None
    status: Literal["requested", "confirmed_available", "noted", "carrier_pending", "carrier_confirmed", "carrier_rejected"]
    source_channel: Literal["whatsapp", "voice", "operator"]
    extraction_id: str | None = None
    carrier_action_id: str | None = None


class IdOut(_M):
    id: str
    status: str


class SendTemplateIn(_M):
    shipment_id: str
    template_code: str
    language: str
    params: list[str] = Field(max_length=10)
    purpose: str
    idempotency_key: str = Field(min_length=8, max_length=160)


class SendReplyIn(_M):
    conversation_id: str
    key: str
    language: str
    idempotency_key: str = Field(min_length=8, max_length=160)
    fmt: dict[str, str] = Field(default_factory=dict)


class MessageRef(_M):
    message_id: str


class ScheduleCallIn(_M):
    shipment_id: str
    purpose: Literal["ndr_recovery", "pre_delivery", "callback"]
    language: str
    at: datetime | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)


class CallRef(_M):
    call_id: str


class CallStatusOut(_M):
    status: str
    result: str | None
    duration_seconds: int | None
    final_language: str | None


class CarrierRequestIn(_M):
    shipment_id: str
    decision_id: str


class ActionRef(_M):
    action_id: str


class FollowupIn(_M):
    name: str = Field(pattern=r"^[a-z_]{3,40}$")
    at: datetime


class CancelFollowupIn(_M):
    name: str = Field(pattern=r"^[a-z_]{3,40}$")


class EscalateIn(_M):
    reason: str = Field(max_length=40)
    priority: Literal["low", "medium", "high", "urgent"]
    summary: str = Field(max_length=1000)
    pending_decision_id: str | None = None


class SlaOut(_M):
    sla_due_at: datetime | None
    minutes_left: int | None
    breached: bool


class OptOutIn(_M):
    shipment_id: str
    evidence: str = Field(max_length=300)


class HistoryIn(_M):
    shipment_id: str
    limit: int = Field(default=10, ge=1, le=50)


class HistoryOut(_M):
    messages: list[dict]
    calls: list[dict]


class Empty(_M):
    pass


class ToolSpec:
    def __init__(self, name, fn, in_model, out_model, mutating: bool, description: str):
        self.name, self.fn, self.in_model, self.out_model = name, fn, in_model, out_model
        self.mutating = mutating
        self.description = description


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, in_model, out_model, mutating: bool, description: str):
    def wrap(fn):
        REGISTRY[name] = ToolSpec(name, fn, in_model, out_model, mutating, description)
        return fn
    return wrap


def tool_schemas() -> list[dict]:
    """What an LLM provider receives for function calling."""
    return [{"name": s.name, "description": s.description, "version": TOOLS_VERSION,
             "parameters": s.in_model.model_json_schema()} for s in REGISTRY.values()]


class ToolBox:
    """Bound to one workflow execution (tenant, shipment, case, run recorder)."""

    def __init__(self, wf):
        self.wf = wf

    def _check_scope(self, args: BaseModel) -> None:
        sid = getattr(args, "shipment_id", None)
        if sid is not None and sid != self.wf.shipment.id:
            raise DomainError("TOOL_SCOPE", "Tool call refers to a different shipment than the task", 403)

    def call(self, name: str, why: str, /, **kwargs):
        """`why` is the human-readable purpose recorded on the step; tool arguments go in kwargs."""
        spec = REGISTRY.get(name)
        if spec is None:
            raise DomainError("UNKNOWN_TOOL", f"tool {name} is not approved", 403)
        args = spec.in_model.model_validate(kwargs)
        self._check_scope(args)
        with self.wf.rec.tool(name, why, TOOLS_VERSION, input=args.model_dump(mode="json")) as step:
            result = spec.fn(self.wf, args, step)
            out = spec.out_model.model_validate(result.model_dump() if isinstance(result, BaseModel) else result)
            step.set(output=out.model_dump(mode="json"))
            return out


# ---------------------------------------------------------------- read tools
@tool("get_shipment_status", ShipmentRef, ShipmentStatusOut, False, "Current carrier status of the shipment")
def _get_shipment_status(wf, a, step):
    s = wf.shipment
    return ShipmentStatusOut(awb=s.tracking_number, carrier=s.carrier_code, status=s.current_status,
                             attempt_count=s.attempt_count, eta_end=s.eta_end)


@tool("get_order_details", ShipmentRef, OrderOut, False, "Order reference, payment mode and COD amount")
def _get_order_details(wf, a, step):
    o = wf.order
    return OrderOut(order_ref=o.code or o.merchant_order_id, payment_mode=o.payment_type,
                    cod_amount_paise=int(float(o.cod_amount or 0) * 100), order_value_paise=o.order_value_paise)


@tool("get_delivery_attempt_history", ShipmentRef, AttemptsOut, False, "Past delivery attempts")
def _get_attempts(wf, a, step):
    rows = wf.db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.shipment_id == wf.shipment.id)
                         .order_by(DeliveryAttempt.attempt_no))
    return AttemptsOut(attempts=[AttemptOut(attempt_no=r.attempt_no, outcome=r.outcome, reason=r.reason_code,
                                            at=r.attempted_at) for r in rows])


@tool("get_customer_preferences", ShipmentRef, PreferencesOut, False, "Language and delivery preferences")
def _get_prefs(wf, a, step):
    c = wf.customer
    p = wf.db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == wf.shipment.id)
                      .order_by(DeliveryPreference.created_at.desc())).first()
    return PreferencesOut(preferred_language=c.preferred_language, preferred_language_source=c.preferred_language_source,
                          predicted_language=c.predicted_language, opted_out=c.opted_out_at is not None,
                          latest_requested_date=p.requested_date if p else None,
                          latest_requested_window=p.requested_window if p else None,
                          latest_status=p.status if p else None)


@tool("get_allowed_delivery_options", ShipmentRef, OptionsOut, False, "What the carrier and policy allow")
def _get_options(wf, a, step):
    return OptionsOut(capabilities=wf.carrier_caps, max_auto_reschedule_days=wf.cfg.max_auto_reschedule_days,
                      max_attempts_before_rto=wf.cfg.max_attempts_before_rto)


@tool("get_message_status", MessageRef, IdOut, False, "Delivery status of a sent message (from provider callbacks)")
def _get_message_status(wf, a, step):
    m = wf.db.get(Message, a.message_id)
    if m is None or m.merchant_id != wf.merchant.id:
        raise DomainError("NOT_FOUND", "message not found", 404)
    return IdOut(id=m.id, status=m.delivery_status)


@tool("get_voice_call_status", CallRef, CallStatusOut, False, "Status and outcome of a voice call")
def _get_call_status(wf, a, step):
    c = wf.db.get(VoiceCall, a.call_id)
    if c is None or c.merchant_id != wf.merchant.id:
        raise DomainError("NOT_FOUND", "call not found", 404)
    return CallStatusOut(status=c.status, result=c.result, duration_seconds=c.duration_seconds, final_language=c.final_language)


@tool("get_conversation_history", HistoryIn, HistoryOut, False, "Recent messages and calls for this shipment")
def _get_history(wf, a, step):
    msgs = wf.db.scalars(select(Message).where(Message.shipment_id == wf.shipment.id)
                         .order_by(Message.created_at.desc()).limit(a.limit))
    calls = wf.db.scalars(select(VoiceCall).where(VoiceCall.shipment_id == wf.shipment.id)
                          .order_by(VoiceCall.created_at.desc()).limit(a.limit))
    return HistoryOut(messages=[{"id": m.id, "direction": m.direction, "status": m.delivery_status,
                                 "language": m.language} for m in msgs],
                      calls=[{"id": c.id, "status": c.status, "result": c.result} for c in calls])


@tool("get_carrier_action_status", ActionRef, IdOut, False, "Lifecycle state of a carrier request")
def _get_action_status(wf, a, step):
    act = wf.db.get(CarrierAction, a.action_id)
    if act is None or act.shipment_id != wf.shipment.id:
        raise DomainError("NOT_FOUND", "carrier action not found", 404)
    return IdOut(id=act.id, status=act.status)


@tool("get_ndr_sla_status", Empty, SlaOut, False, "Deadline for the current NDR case")
def _get_sla(wf, a, step):
    if wf.case is None:
        return SlaOut(sla_due_at=None, minutes_left=None, breached=False)
    due = clock.as_utc(wf.case.sla_due_at)
    left = int((due - clock.now()).total_seconds() // 60)
    return SlaOut(sla_due_at=due, minutes_left=left, breached=left < 0)


# ---------------------------------------------------------------- mutating tools
@tool("save_delivery_preference", SavePreferenceIn, IdOut, True, "Record the customer's delivery preference")
def _save_pref(wf, a, step):
    for old in wf.db.scalars(select(DeliveryPreference).where(
            DeliveryPreference.shipment_id == wf.shipment.id,
            DeliveryPreference.status.in_(("requested", "noted", "carrier_pending")))):
        old.status = "superseded"
    pref = DeliveryPreference(merchant_id=wf.merchant.id, customer_id=wf.customer.id, shipment_id=wf.shipment.id,
                              ndr_case_id=wf.case.id if wf.case else None, requested_date=a.requested_date,
                              requested_window=a.requested_window, preferred_language=a.language,
                              language_source=a.language_source, language_confidence=a.language_confidence,
                              status=a.status, source_channel=a.source_channel, source_extraction_id=a.extraction_id,
                              carrier_action_id=a.carrier_action_id, customer_confirmed_at=clock.now(),
                              expires_at=None)
    wf.db.add(pref)
    wf.db.flush()
    return IdOut(id=pref.id, status=pref.status)


@tool("send_whatsapp_template", SendTemplateIn, IdOut, True, "Send an approved WhatsApp template")
def _send_template(wf, a, step):
    msg = messaging.queue_template(wf.db, wf.merchant, wf.customer, a.template_code, a.language, a.params,
                                   a.purpose, a.idempotency_key, wf.shipment.id, wf.case.id if wf.case else None,
                                   wf.rec.run.id)
    step.set(message_id=msg.id, provider=msg.provider)
    if msg.language != a.language:
        step.set(language_before=a.language, language_after=msg.language,
                 error=f"No approved {a.language} template; sent {msg.language}")
    return IdOut(id=msg.id, status=msg.delivery_status)


@tool("send_whatsapp_reply", SendReplyIn, IdOut, True, "Reply inside the customer's 24-hour session window")
def _send_reply(wf, a, step):
    from app.platform.models import Conversation
    conv = wf.db.get(Conversation, a.conversation_id)
    if conv is None or conv.customer_id != wf.customer.id:
        raise DomainError("TOOL_SCOPE", "conversation does not belong to this customer", 403)
    msg = messaging.queue_session_text(wf.db, wf.merchant, wf.customer, conv, a.key, a.language, a.idempotency_key,
                                       wf.rec.run.id, **a.fmt)
    step.set(message_id=msg.id, provider=msg.provider)
    return IdOut(id=msg.id, status=msg.delivery_status)


@tool("schedule_voice_call", ScheduleCallIn, IdOut, True, "Schedule an outbound call (contact policy enforced)")
def _schedule_call(wf, a, step):
    call = schedule_call(wf.db, wf.merchant, wf.customer, wf.shipment, a.purpose, a.language, a.idempotency_key,
                         a.at, wf.case, wf.task)
    step.set(call_id=call.id, provider=call.provider)
    return IdOut(id=call.id, status=call.status)


def _carrier_request(wf, a, step, expected: tuple[str, ...]):
    decision = wf.db.get(RuleDecision, a.decision_id)
    if decision is None or decision.shipment_id != wf.shipment.id:
        raise DomainError("TOOL_SCOPE", "decision does not belong to this shipment", 403)
    if decision.action not in expected:
        raise DomainError("WRONG_ACTION", f"decision is for {decision.action}", 409)
    action = carrier_actions.create_from_decision(wf.db, decision, wf.shipment, audit.AGENT,
                                                  wf.case.id if wf.case else None)
    step.set(carrier_action_id=action.id, decision_id=decision.id, policy_rule=",".join(decision.rules_fired)[:80],
             provider=f"carrier:{wf.shipment.carrier_code}")
    return IdOut(id=action.id, status=action.status)


@tool("request_reattempt", CarrierRequestIn, IdOut, True, "Ask the carrier to reattempt (needs an allowed decision)")
def _request_reattempt(wf, a, step):
    return _carrier_request(wf, a, step, ("reattempt",))


@tool("request_reschedule", CarrierRequestIn, IdOut, True, "Ask the carrier to deliver on a date (needs an allowed decision)")
def _request_reschedule(wf, a, step):
    return _carrier_request(wf, a, step, ("reschedule",))


@tool("request_address_change", CarrierRequestIn, IdOut, True, "Submit a verified address change (needs approval)")
def _request_address_change(wf, a, step):
    return _carrier_request(wf, a, step, ("address_change",))


@tool("schedule_followup", FollowupIn, IdOut, True, "Set a durable timer for this workflow")
def _schedule_followup(wf, a, step):
    from app.platform.workflows.engine import set_timer
    set_timer(wf.db, wf.task, a.name, a.at)
    return IdOut(id=f"{wf.task.id}:{a.name}", status="scheduled")


@tool("cancel_obsolete_followup", CancelFollowupIn, IdOut, True, "Cancel a timer that is no longer needed")
def _cancel_followup(wf, a, step):
    from app.platform.workflows.engine import cancel_timer
    cancel_timer(wf.db, wf.task, a.name)
    return IdOut(id=f"{wf.task.id}:{a.name}", status="cancelled")


@tool("create_escalation", EscalateIn, IdOut, True, "Hand the case to a human with a summary")
def _create_escalation(wf, a, step):
    if wf.case is None:
        raise DomainError("NO_CASE", "escalations need an NDR case", 409)
    esc = escalations.open_escalation(wf.db, wf.case, a.reason, a.priority, a.summary, audit.AGENT,
                                      a.pending_decision_id)
    wf.rec.run.human_involved = True
    return IdOut(id=esc.id, status=esc.status)


@tool("record_customer_opt_out", OptOutIn, IdOut, True, "Stop all automated contact with this customer")
def _opt_out(wf, a, step):
    cust_svc.record_opt_out(wf.db, wf.customer, "customer_message", audit.AGENT, a.evidence)
    return IdOut(id=wf.customer.id, status="opted_out")


def carrier_capabilities(db, carrier_code: str) -> dict[str, dict]:
    carrier = db.scalars(select(Carrier).where(Carrier.code == carrier_code)).first()
    if carrier is None:
        return {}
    return {c.capability: dict(c.constraints or {}) for c in db.scalars(
        select(CarrierCapability).where(CarrierCapability.carrier_id == carrier.id))}


__all__ = ["ToolBox", "tool_schemas", "carrier_capabilities", "CallBlocked", "policies", "NdrCase"]
