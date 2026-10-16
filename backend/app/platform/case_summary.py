"""Read model for the NDR command center.

The command center filters and sorts large volumes of cases on ~25 attributes that live in different tables.
Instead of joining and sub-selecting all of them per row, each case carries a denormalized summary that is
recomputed in the same transaction as any change that affects it (see outbox.emit / before_commit). Listing
is then a single indexed query on `ndr_cases`.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, Shipment
from app.platform.models import (Address, AgentTask, CarrierAction, Customer, DeliveryOutcome, DeliveryPreference,
                                 Escalation, IntentExtraction, Message, NdrCase, RuleDecision, VoiceCall)

AGENT_STATUS = {
    ("active", None): "running", ("waiting", "customer_reply"): "awaiting_customer",
    ("active", "customer_reply"): "awaiting_customer", ("active", "call_result"): "awaiting_call",
    ("waiting", "call_result"): "awaiting_call", ("active", "carrier_response"): "awaiting_carrier",
    ("waiting", "carrier_response"): "awaiting_carrier", ("active", "delivery"): "awaiting_delivery",
    ("waiting", "delivery"): "awaiting_delivery",
}


def refresh_many(db: Session, case_ids: set[str], shipment_ids: set[str]) -> None:
    ids = set(case_ids)
    if shipment_ids:
        for cid in db.scalars(select(NdrCase.id).where(NdrCase.shipment_id.in_(list(shipment_ids)))):
            ids.add(cid)
    for cid in ids:
        case = db.get(NdrCase, cid)
        if case is not None:
            refresh(db, case)


def refresh(db: Session, case: NdrCase) -> None:
    shipment = db.get(Shipment, case.shipment_id)
    order = db.get(Order, shipment.order_id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    address = db.get(Address, order.address_id) if order.address_id else None
    case.customer_id = customer.id if customer else None
    case.order_ref = order.code or order.merchant_order_id
    case.awb = shipment.tracking_number
    case.carrier_code = shipment.carrier_code
    case.payment_mode = order.payment_type
    case.cod_amount_paise = int(float(order.cod_amount or 0) * 100)
    case.shipment_status = shipment.current_status
    if address:
        case.city, case.state, case.pincode = address.city, address.state, address.pincode
    if customer:
        case.language_predicted = customer.predicted_language
        case.language_confirmed = customer.preferred_language

    pref = db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == shipment.id,
                                                       DeliveryPreference.status != "superseded")
                      .order_by(DeliveryPreference.created_at.desc())).first()
    case.preferred_date = pref.requested_date if pref else None
    case.preferred_window = pref.requested_window if pref else None

    wa = db.scalars(select(Message).where(Message.ndr_case_id == case.id, Message.direction == "outbound")
                    .order_by(Message.created_at.desc())).first()
    case.whatsapp_status = wa.delivery_status if wa else None
    call = db.scalars(select(VoiceCall).where(VoiceCall.ndr_case_id == case.id)
                      .order_by(VoiceCall.created_at.desc())).first()
    case.call_outcome = (call.result or call.status) if call else None

    last_in = db.scalar(select(func.max(Message.created_at)).where(Message.ndr_case_id == case.id,
                                                                   Message.direction == "inbound"))
    last_call = db.scalar(select(func.max(VoiceCall.ended_at)).where(VoiceCall.ndr_case_id == case.id,
                                                                     VoiceCall.status == "completed"))
    if last_in or last_call:
        from app.platform.clock import as_utc
        a, b = as_utc(last_in), as_utc(last_call)
        case.last_contact_channel = "whatsapp" if (a and (not b or a >= b)) else "voice"
        case.last_customer_contact_at = max(x for x in (a, b) if x)

    task = db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == case.id)
                      .order_by(AgentTask.created_at.desc())).first()
    if task is None:
        case.agent_status = "not_started"
    elif task.status in ("completed", "cancelled", "superseded", "failed", "escalated"):
        case.agent_status = task.status
    else:
        case.agent_status = AGENT_STATUS.get((task.status, task.waiting_for), "running")

    pending_decision = db.scalars(select(RuleDecision).where(RuleDecision.ndr_case_id == case.id,
                                                             RuleDecision.approval_status == "pending")
                                  .order_by(RuleDecision.created_at.desc())).first()
    open_action = db.scalars(select(CarrierAction).where(
        CarrierAction.ndr_case_id == case.id, CarrierAction.status.in_(("requested", "unknown", "retrying", "accepted")))
        .order_by(CarrierAction.requested_at.desc())).first()
    if open_action is not None:
        case.pending_action = f"{open_action.action}:{open_action.status}"
    elif pending_decision is not None:
        case.pending_action = f"approval:{pending_decision.action or 'review'}"
    else:
        case.pending_action = None

    outcome = db.scalars(select(DeliveryOutcome).where(DeliveryOutcome.shipment_id == shipment.id)).first()
    case.recovery_outcome = outcome.attribution if outcome else (case.resolution or None)

    if customer and customer.opted_out_at:
        case.contactability = "opted_out"
    elif last_in or last_call:
        case.contactability = "reachable"
    else:
        failed_calls = db.scalar(select(func.count()).select_from(VoiceCall).where(
            VoiceCall.ndr_case_id == case.id, VoiceCall.status.in_(("no_answer", "busy", "failed")))) or 0
        failed_msgs = db.scalar(select(func.count()).select_from(Message).where(
            Message.ndr_case_id == case.id, Message.delivery_status == "failed")) or 0
        case.contactability = "unreachable" if (failed_calls or failed_msgs) else "unknown"

    case.has_open_escalation = db.scalar(select(func.count()).select_from(Escalation).where(
        Escalation.ndr_case_id == case.id, Escalation.status != "resolved")) > 0
    ext = db.scalars(select(IntentExtraction).where(IntentExtraction.ndr_case_id == case.id)
                     .order_by(IntentExtraction.created_at.desc())).first()
    case.low_confidence = bool(ext and (ext.validation_status != "valid" or ext.confidence < 0.7))
    case.callback_requested = bool(ext and ext.intent == "callback" and case.status not in ("resolved", "closed_no_response"))
