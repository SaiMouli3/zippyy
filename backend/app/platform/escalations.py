"""Human escalation inbox. One open escalation per case; every operator action is recorded as a note and in the
audit log. Approving an action creates a carrier request — it does not mean the carrier agreed."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError, not_found
from app.platform import audit, clock, outbox
from app.platform.ids import short_code
from app.platform.models import (AgentTask, DeliveryPreference, Escalation, EscalationNote, Membership, NdrCase,
                                 RuleDecision, Shipment)

PRIORITY_SLA_HOURS = {"urgent": 2, "high": 4, "medium": 8, "low": 24}
_RANK = {"low": 0, "medium": 1, "high": 2, "urgent": 3}
RESOLUTION_OUTCOMES = ("action_approved", "customer_contacted_manually", "carrier_contacted_manually",
                       "rto_confirmed", "closed_no_response", "duplicate", "no_action_needed")


def open_escalation(db: Session, case: NdrCase, reason: str, priority: str, summary: str, actor: audit.Actor,
                    pending_decision_id: str | None = None) -> Escalation:
    esc = db.scalars(select(Escalation).where(Escalation.ndr_case_id == case.id, Escalation.status != "resolved")).first()
    if esc is not None:
        if _RANK[priority] > _RANK[esc.priority]:
            esc.priority = priority
            esc.sla_due_at = min(clock.as_utc(esc.sla_due_at), clock.now() + timedelta(hours=PRIORITY_SLA_HOURS[priority]))
        if pending_decision_id:
            esc.pending_decision_id = pending_decision_id
        esc.reason = reason
        esc.summary = summary[:1000]
        _note(db, esc, actor, "note", f"Escalation updated: {reason}. {summary}")
        outbox.emit(db, case.merchant_id, "escalation", esc.id, "escalation.updated", {"ndrCaseId": case.id})
        return esc
    esc = Escalation(code=short_code("ESC"), merchant_id=case.merchant_id, ndr_case_id=case.id, reason=reason,
                     priority=priority, summary=summary[:1000], pending_decision_id=pending_decision_id,
                     sla_due_at=clock.now() + timedelta(hours=PRIORITY_SLA_HOURS[priority]))
    db.add(esc)
    db.flush()
    before = case.status
    if case.status not in ("rto",):
        case.status = "escalated"
    _note(db, esc, actor, "note", f"Opened: {reason}. {summary}")
    audit.record(db, actor, case.merchant_id, "escalation", esc.id, "escalation.opened",
                 before={"caseStatus": before}, after={"reason": reason, "priority": priority})
    outbox.emit(db, case.merchant_id, "escalation", esc.id, "escalation.opened",
                {"ndrCaseId": case.id, "priority": priority, "reason": reason})
    for task in db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == case.id, AgentTask.status.in_(("active", "waiting")))):
        task.status = "escalated"
        task.waiting_for = "operator"
    return esc


def _note(db: Session, esc: Escalation, actor: audit.Actor, kind: str, body: str) -> EscalationNote:
    note = EscalationNote(merchant_id=esc.merchant_id, escalation_id=esc.id,
                          author_id=actor.id if actor.type == "user" else None, kind=kind, body=body[:2000])
    db.add(note)
    return note


def _get(db: Session, merchant_id: str, escalation_id: str) -> Escalation:
    esc = db.get(Escalation, escalation_id)
    if esc is None or esc.merchant_id != merchant_id:
        raise not_found("Escalation")
    return esc


def _ensure_open(esc: Escalation) -> None:
    if esc.status == "resolved":
        raise DomainError("ESCALATION_RESOLVED", "This escalation is already resolved", 409)


def assign(db: Session, merchant_id: str, escalation_id: str, user_id: str | None, actor: audit.Actor) -> Escalation:
    esc = _get(db, merchant_id, escalation_id)
    _ensure_open(esc)
    if user_id and not db.get(Membership, (merchant_id, user_id)):
        raise DomainError("NOT_A_MEMBER", "That user is not a member of this workspace", 422)
    before = esc.assigned_to
    esc.assigned_to = user_id
    esc.status = "assigned" if user_id else "open"
    _note(db, esc, actor, "assignment", f"Assigned to {user_id or 'nobody'}")
    audit.record(db, actor, merchant_id, "escalation", esc.id, "escalation.assigned",
                 before={"assignedTo": before}, after={"assignedTo": user_id})
    outbox.emit(db, merchant_id, "escalation", esc.id, "escalation.assigned", {"ndrCaseId": esc.ndr_case_id})
    return esc


def add_note(db: Session, merchant_id: str, escalation_id: str, body: str, actor: audit.Actor) -> EscalationNote:
    esc = _get(db, merchant_id, escalation_id)
    note = _note(db, esc, actor, "note", body)
    audit.record(db, actor, merchant_id, "escalation", esc.id, "escalation.note_added")
    return note


def decide_pending(db: Session, merchant_id: str, escalation_id: str, approve: bool, reason: str,
                   actor: audit.Actor) -> dict:
    from app.platform import carrier_actions
    from app.platform.workflows.engine import trigger

    esc = _get(db, merchant_id, escalation_id)
    _ensure_open(esc)
    if not esc.pending_decision_id:
        raise DomainError("NOTHING_TO_APPROVE", "No action is waiting for approval on this escalation", 409)
    decision = db.get(RuleDecision, esc.pending_decision_id)
    if decision.approval_status in ("approved", "rejected"):
        raise DomainError("ALREADY_DECIDED", f"Already {decision.approval_status}", 409)
    case = db.get(NdrCase, esc.ndr_case_id)
    shipment = db.get(Shipment, case.shipment_id)
    decision.approval_status = "approved" if approve else "rejected"
    decision.approved_by = actor.id
    _note(db, esc, actor, "approval" if approve else "rejection",
          f"{'Approved' if approve else 'Rejected'} {decision.action}: {reason}")
    audit.record(db, actor, merchant_id, "rule_decision", decision.id,
                 "decision.approved" if approve else "decision.rejected", reason=reason,
                 after={"action": decision.action, "requestedDate": str(decision.requested_date)})
    result: dict = {"decisionId": decision.id, "approved": approve}
    if approve and decision.action:
        action = carrier_actions.create_from_decision(db, decision, shipment, actor, case.id)
        case.status = "action_requested"
        result["carrierActionId"] = action.id
        result["carrierActionStatus"] = action.status  # "requested": the carrier has not answered yet
    esc.pending_decision_id = None
    for task in db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == case.id, AgentTask.status == "escalated")):
        task.status = "waiting"
        trigger(db, task, "operator_decision", {"approved": approve, "decision_id": decision.id})
    outbox.emit(db, merchant_id, "escalation", esc.id, "escalation.decision", {"ndrCaseId": case.id, "approved": approve})
    return result


def request_supervisor(db: Session, merchant_id: str, escalation_id: str, reason: str, actor: audit.Actor) -> Escalation:
    esc = _get(db, merchant_id, escalation_id)
    _ensure_open(esc)
    esc.supervisor_requested = True
    if _RANK[esc.priority] < _RANK["high"]:
        esc.priority = "high"
    _note(db, esc, actor, "supervisor", f"Escalated to a supervisor: {reason}")
    audit.record(db, actor, merchant_id, "escalation", esc.id, "escalation.supervisor_requested", reason=reason)
    outbox.emit(db, merchant_id, "escalation", esc.id, "escalation.supervisor", {"ndrCaseId": esc.ndr_case_id})
    return esc


def correct_preference(db: Session, merchant_id: str, escalation_id: str, requested_date, requested_window: str | None,
                       language: str | None, reason: str, actor: audit.Actor) -> DeliveryPreference:
    from app.platform.models import Customer, Order
    esc = _get(db, merchant_id, escalation_id)
    case = db.get(NdrCase, esc.ndr_case_id)
    shipment = db.get(Shipment, case.shipment_id)
    order = db.get(Order, shipment.order_id)
    customer = db.get(Customer, order.customer_id)
    for old in db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == shipment.id,
                                                           DeliveryPreference.status.in_(("requested", "noted")))):
        old.status = "superseded"
    pref = DeliveryPreference(merchant_id=merchant_id, customer_id=customer.id, shipment_id=shipment.id,
                              ndr_case_id=case.id, requested_date=requested_date, requested_window=requested_window,
                              preferred_language=language, language_source="operator" if language else None,
                              language_confidence=1.0 if language else None, status="requested",
                              source_channel="operator", customer_confirmed_at=clock.now())
    db.add(pref)
    if language:
        customer.preferred_language = language
        customer.preferred_language_source = "operator"
        customer.preferred_language_confirmed_at = clock.now()
    _note(db, esc, actor, "correction", f"Preference corrected to {requested_date} {requested_window or ''} "
                                        f"{('language ' + language) if language else ''}: {reason}")
    audit.record(db, actor, merchant_id, "delivery_preference", pref.id if pref.id else esc.id, "preference.corrected",
                 after={"date": str(requested_date), "window": requested_window, "language": language}, reason=reason)
    return pref


def resolve(db: Session, merchant_id: str, escalation_id: str, outcome: str, reason: str, actor: audit.Actor,
            close_case: bool = False) -> Escalation:
    from app.platform import ndr
    if outcome not in RESOLUTION_OUTCOMES:
        raise DomainError("INVALID_OUTCOME", f"outcome must be one of {', '.join(RESOLUTION_OUTCOMES)}", 422)
    if not reason or len(reason.strip()) < 5:
        raise DomainError("REASON_REQUIRED", "A resolution reason is required", 422)
    esc = _get(db, merchant_id, escalation_id)
    _ensure_open(esc)
    esc.status = "resolved"
    esc.resolved_at = clock.now()
    esc.resolution_outcome = outcome
    esc.resolution_reason = reason[:500]
    _note(db, esc, actor, "resolution", f"Resolved ({outcome}): {reason}")
    audit.record(db, actor, merchant_id, "escalation", esc.id, "escalation.resolved",
                 after={"outcome": outcome}, reason=reason)
    case = db.get(NdrCase, esc.ndr_case_id)
    if outcome == "closed_no_response" and close_case:
        ndr.resolve_case(db, case, "no_response", actor, reason)
    elif case.status == "escalated":
        case.status = "awaiting_customer" if outcome in ("customer_contacted_manually",) else "decided"
    outbox.emit(db, merchant_id, "escalation", esc.id, "escalation.resolved", {"ndrCaseId": case.id, "outcome": outcome})
    return esc
