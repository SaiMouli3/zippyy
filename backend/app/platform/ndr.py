"""NDR case lifecycle, driven by verified carrier tracking events (called inside the ingestion transaction).

* DELIVERY_FAILED -> delivery attempt recorded, the shipment's single open case created or updated, a recovery
  task started for this delivery cycle (dedupe: one task per shipment per cycle).
* OUT_FOR_DELIVERY -> accepted reattempts verified; pre-delivery confirmation started on the first cycle.
* DELIVERED / RTO_DELIVERED -> terminal: case resolved, open work cancelled (no obsolete follow-ups),
  escalations closed, outcome attribution recorded.
A case only closes on a confirmed terminal condition.
"""
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.platform import audit, clock, outbox, policies
from app.platform.ids import correlation_id, short_code
from app.platform.models import (AgentTask, CarrierAction, Customer, DeliveryAttempt, DeliveryOutcome, Escalation,
                                 EscalationNote, Merchant, Message, NdrCase, VoiceCall)

# Carrier reason vocabularies -> platform reasons. The verbatim carrier reason is always kept on the case.
REASON_MAP = {
    # FastShip
    "CNA": "customer_unavailable", "REF": "customer_refused", "ADI": "address_issue", "PNR": "phone_unreachable",
    "CNR": "cod_not_ready", "OTH": "other",
    # QuickExpress
    "CUSTOMER_UNAVAILABLE": "customer_unavailable", "REFUSED": "customer_refused", "ADDRESS_ISSUE": "address_issue",
    "PHONE_UNREACHABLE": "phone_unreachable", "COD_NOT_READY": "cod_not_ready", "OTHER": "other",
    # ReliableCourier
    "R01": "customer_unavailable", "R02": "customer_refused", "R03": "address_issue", "R04": "phone_unreachable",
    "R05": "cod_not_ready", "R99": "other",
}
_TEXT_RULES = [
    (r"refus|reject|denied|not (want|interested)", "customer_refused"),
    (r"address|location|not found|incomplete|wrong (pin|area)", "address_issue"),
    (r"cash|cod|payment|money", "cod_not_ready"),
    (r"phone|unreachable|switched off|not reachable|no response", "phone_unreachable"),
    (r"not (available|home)|unavailable|door locked|premises closed|absent", "customer_unavailable"),
]


def normalize_reason(carrier_reason: str | None, description: str | None = None) -> str:
    if carrier_reason and carrier_reason.strip().upper() in REASON_MAP:
        return REASON_MAP[carrier_reason.strip().upper()]
    text = f"{carrier_reason or ''} {description or ''}".lower()
    for pattern, reason in _TEXT_RULES:
        if re.search(pattern, text):
            return reason
    return "other"


def _start_task(db: Session, merchant_id: str, task_type: str, shipment, cycle: int, trigger_event: str,
                case: NdrCase | None = None, deadline=None) -> AgentTask | None:
    from app.platform.workflows.engine import trigger
    pv, _ = policies.agent_config(db, merchant_id)
    task = AgentTask(merchant_id=merchant_id, task_type=task_type, shipment_id=shipment.id,
                     ndr_case_id=case.id if case else None, delivery_cycle=cycle, trigger_event=trigger_event,
                     status="active", current_step="start", correlation_id=correlation_id(),
                     policy_version_id=pv.id, deadline_at=deadline, state={})
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError:
        return None  # a task for this shipment + cycle already exists: duplicate trigger
    trigger(db, task, "start", {"event": trigger_event})
    outbox.emit(db, merchant_id, "agent_task", task.id, "agent_task.started",
                {"taskType": task_type, "ndrCaseId": task.ndr_case_id, "shipmentId": shipment.id})
    return task


def on_tracking_event(db: Session, shipment, order, event, status: str) -> None:
    merchant_id = shipment.merchant_id
    shipment.last_event_at = event.event_time
    if not merchant_id or db.get(Merchant, merchant_id) is None:
        return  # legacy sandbox shipment: no platform workflows
    event.merchant_id = merchant_id

    if status == "OUT_FOR_DELIVERY":
        from app.platform.carrier_actions import verify_on_new_attempt
        verify_on_new_attempt(db, shipment)
        if shipment.dispatched_at is None:
            shipment.dispatched_at = event.event_time
        _, cfg = policies.agent_config(db, merchant_id)
        cycle = shipment.attempt_count + 1
        if cycle == 1 and cfg.pre_delivery_enabled and cfg.pre_delivery_trigger in ("out_for_delivery", "both"):
            eligible = not cfg.pre_delivery_cod_only or order.payment_type == "COD"
            eligible = eligible and (order.order_value_paise or 0) >= cfg.pre_delivery_min_order_value_paise
            if eligible:
                _start_task(db, merchant_id, "pre_delivery", shipment, cycle, "carrier.out_for_delivery",
                            deadline=event.event_time + timedelta(hours=10))
        outbox.emit(db, merchant_id, "shipment", shipment.id, "shipment.out_for_delivery", {"attempt": cycle})
        return

    if status == "DELIVERY_FAILED":
        shipment.attempt_count += 1
        reason = normalize_reason(event.carrier_reason, event.description)
        event.reason_code = reason
        db.add(DeliveryAttempt(merchant_id=merchant_id, shipment_id=shipment.id, attempt_no=shipment.attempt_count,
                               outcome="failed", reason_code=reason, courier_remark=(event.description or "")[:300],
                               event_id=event.id, attempted_at=event.event_time))
        _close_tasks(db, shipment, "pre_delivery", "completed", "delivery attempt failed; NDR recovery takes over")
        _close_tasks(db, shipment, "ndr_recovery", "superseded", f"new failed attempt #{shipment.attempt_count}")
        case = open_case(db, merchant_id, shipment, event, reason)
        _, cfg = policies.agent_config(db, merchant_id)
        if cfg.agent_enabled and cfg.ndr_auto_contact:
            _start_task(db, merchant_id, "ndr_recovery", shipment, shipment.attempt_count, "carrier.delivery_failed",
                        case=case, deadline=case.sla_due_at)
        return

    if status == "DELIVERED":
        shipment.attempt_count += 1
        shipment.delivered_at = event.event_time
        db.add(DeliveryAttempt(merchant_id=merchant_id, shipment_id=shipment.id, attempt_no=shipment.attempt_count,
                               outcome="delivered", event_id=event.id, attempted_at=event.event_time))
        case = current_case(db, shipment.id)
        if case:
            resolve_case(db, case, "delivered", audit.Actor("carrier", shipment.carrier_code, shipment.carrier_code))
        _close_tasks(db, shipment, None, "completed", "shipment delivered")
        attribute(db, shipment, order, case, "delivered")
        outbox.emit(db, merchant_id, "shipment", shipment.id, "shipment.delivered", {"ndrCaseId": case.id if case else None})
        return

    if status == "RTO":
        case = current_case(db, shipment.id)
        if case:
            before = case.status
            case.status = "rto"
            case.recovery_strategy = "return_to_origin"
            audit.record(db, audit.Actor("carrier", shipment.carrier_code), merchant_id, "ndr_case", case.id,
                         "ndr.rto_initiated", before={"status": before}, after={"status": "rto"})
        _close_tasks(db, shipment, None, "completed", "return to origin initiated")
        outbox.emit(db, merchant_id, "shipment", shipment.id, "shipment.rto_initiated", {"ndrCaseId": case.id if case else None})
        return

    if status == "RTO_DELIVERED":
        case = current_case(db, shipment.id)
        if case:
            resolve_case(db, case, "rto", audit.Actor("carrier", shipment.carrier_code, shipment.carrier_code))
        attribute(db, shipment, order, case, "rto")
        outbox.emit(db, merchant_id, "shipment", shipment.id, "shipment.rto_delivered", {"ndrCaseId": case.id if case else None})


def current_case(db: Session, shipment_id: str) -> NdrCase | None:
    return db.scalars(select(NdrCase).where(NdrCase.shipment_id == shipment_id,
                                            NdrCase.status.not_in(("resolved", "closed_no_response")))).first()


def open_case(db: Session, merchant_id: str, shipment, event, reason: str) -> NdrCase:
    _, cfg = policies.agent_config(db, merchant_id)
    now = clock.now()
    case = current_case(db, shipment.id)
    if case is not None:
        case.attempt_no = shipment.attempt_count
        case.reason = reason
        case.carrier_reason = (event.carrier_reason or event.description or "")[:200] or None
        case.status = "open"
        case.sla_due_at = now + timedelta(hours=cfg.sla_hours)
        case.priority = "high" if shipment.attempt_count >= cfg.max_attempts_before_rto - 1 else case.priority
        audit.record(db, audit.Actor("carrier", shipment.carrier_code), merchant_id, "ndr_case", case.id,
                     "ndr.attempt_failed_again", after={"attempt": shipment.attempt_count, "reason": reason})
        outbox.emit(db, merchant_id, "ndr_case", case.id, "ndr.updated", {"attempt": shipment.attempt_count, "reason": reason})
        return case
    for _ in range(5):
        case = NdrCase(code=short_code("NDR"), merchant_id=merchant_id, shipment_id=shipment.id,
                       opened_by_event_id=event.id, attempt_no=shipment.attempt_count, reason=reason,
                       carrier_reason=(event.carrier_reason or event.description or "")[:200] or None,
                       status="open", sla_due_at=now + timedelta(hours=cfg.sla_hours),
                       priority="high" if shipment.attempt_count >= cfg.max_attempts_before_rto - 1 else "normal")
        try:
            with db.begin_nested():
                db.add(case)
                db.flush()
            break
        except IntegrityError:
            existing = current_case(db, shipment.id)
            if existing is not None:  # concurrent ingestion created it
                return existing
    audit.record(db, audit.Actor("carrier", shipment.carrier_code), merchant_id, "ndr_case", case.id, "ndr.opened",
                 after={"reason": reason, "attempt": case.attempt_no, "carrierReason": case.carrier_reason})
    outbox.emit(db, merchant_id, "ndr_case", case.id, "ndr.opened", {"reason": reason, "code": case.code})
    return case


def resolve_case(db: Session, case: NdrCase, resolution: str, actor: audit.Actor, reason: str | None = None) -> None:
    if case.status in ("resolved", "closed_no_response"):
        return
    before = case.status
    case.status = "closed_no_response" if resolution == "no_response" else "resolved"
    case.resolution = resolution
    case.resolved_at = clock.now()
    audit.record(db, actor, case.merchant_id, "ndr_case", case.id, "ndr.resolved", before={"status": before},
                 after={"status": case.status, "resolution": resolution}, reason=reason)
    for esc in db.scalars(select(Escalation).where(Escalation.ndr_case_id == case.id, Escalation.status != "resolved")):
        esc.status = "resolved"
        esc.resolved_at = clock.now()
        esc.resolution_outcome = f"case_{resolution}"
        esc.resolution_reason = "Case reached a terminal state"
        db.add(EscalationNote(merchant_id=case.merchant_id, escalation_id=esc.id, kind="resolution",
                              body=f"Closed automatically: case {resolution}"))
    outbox.emit(db, case.merchant_id, "ndr_case", case.id, "ndr.resolved", {"resolution": resolution, "code": case.code})


def _close_tasks(db: Session, shipment, task_type: str | None, status: str, reason: str) -> None:
    from app.platform.workflows.engine import close_task
    q = select(AgentTask).where(AgentTask.shipment_id == shipment.id, AgentTask.status.in_(("active", "waiting", "escalated")))
    if task_type:
        q = q.where(AgentTask.task_type == task_type)
    for task in db.scalars(q):
        close_task(db, task, status, reason)


def attribute(db: Session, shipment, order, case: NdrCase | None, outcome: str) -> None:
    """Delivered after an NDR counts as recovered by Zippyy only with evidence that our contact led to it:
    a customer response (reply or answered call) and/or an accepted carrier action after the case opened."""
    if db.scalars(select(DeliveryOutcome.id).where(DeliveryOutcome.shipment_id == shipment.id)).first():
        return
    evidence: dict = {}
    contact_cost = 0
    carrier_fee = 0
    if case is not None:
        opened = case.opened_at
        replies = db.scalar(select(func.count()).select_from(Message).where(
            Message.ndr_case_id == case.id, Message.direction == "inbound", Message.created_at >= opened)) or 0
        answered = db.scalar(select(func.count()).select_from(VoiceCall).where(
            VoiceCall.ndr_case_id == case.id, VoiceCall.status == "completed")) or 0
        actions = list(db.scalars(select(CarrierAction).where(CarrierAction.ndr_case_id == case.id,
                                                              CarrierAction.status.in_(("accepted", "completed")))))
        contact_cost = (db.scalar(select(func.coalesce(func.sum(Message.cost_paise), 0)).where(Message.ndr_case_id == case.id)) or 0) \
            + (db.scalar(select(func.coalesce(func.sum(VoiceCall.cost_paise), 0)).where(VoiceCall.ndr_case_id == case.id)) or 0)
        carrier_fee = sum(a.fee_paise or 0 for a in actions)
        evidence = {"customerReplies": replies, "answeredCalls": answered,
                    "acceptedCarrierActions": [a.id for a in actions]}
        contacted = replies > 0 or answered > 0
        if outcome == "delivered":
            attribution = "recovered_after_contact" if contacted else "recovered_without_contact"
        else:
            attribution = "rto_after_contact" if contacted else "rto_without_contact"
    else:
        attribution = "first_attempt" if outcome == "delivered" else "rto_without_contact"
    db.add(DeliveryOutcome(
        merchant_id=shipment.merchant_id, shipment_id=shipment.id, ndr_case_id=case.id if case else None,
        outcome=outcome, attribution=attribution, attributed_to_zippyy=attribution == "recovered_after_contact",
        evidence=evidence, order_value_paise=order.order_value_paise, contact_cost_paise=int(contact_cost),
        carrier_fee_paise=int(carrier_fee)))


def sla_sweep(db: Session, job=None) -> dict:
    """Periodic: warn on cases near their SLA and escalate breaches. Runs per tenant (job.merchant_id)."""
    from app.platform import escalations
    now = clock.now()
    counts = {"warned": 0, "breached": 0}
    merchants = [job.merchant_id] if job is not None and job.merchant_id else [m.id for m in db.scalars(select(Merchant))]
    for merchant_id in merchants:
        _, cfg = policies.agent_config(db, merchant_id)
        open_cases = db.scalars(select(NdrCase).where(
            NdrCase.merchant_id == merchant_id,
            NdrCase.status.in_(("open", "contacting", "awaiting_customer", "decided", "escalated")),
            NdrCase.sla_due_at <= now + timedelta(hours=cfg.sla_warning_hours)))
        for case in open_cases:
            due = clock.as_utc(case.sla_due_at)
            if due <= now:
                if case.priority != "urgent":
                    case.priority = "urgent"
                    escalations.open_escalation(db, case, "sla_breached", "urgent",
                                                f"SLA deadline passed at {due:%d %b %H:%M} UTC without a confirmed recovery action.",
                                                audit.SYSTEM)
                    counts["breached"] += 1
            elif case.priority == "normal":
                case.priority = "high"
                outbox.emit(db, merchant_id, "ndr_case", case.id, "ndr.sla_warning", {"dueAt": due.isoformat(), "code": case.code})
                counts["warned"] += 1
    return counts


__all__ = ["on_tracking_event", "normalize_reason", "resolve_case", "current_case", "sla_sweep", "Customer"]
