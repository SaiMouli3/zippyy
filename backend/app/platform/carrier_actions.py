"""Carrier NDR actions: every action is bound to a recorded rules decision, submitted once (idempotency key),
and its lifecycle reflects only what the carrier said:

  requested -> accepted | rejected                      (synchronous answer)
  requested -> unknown -> (reconcile) accepted | rejected | retrying   (timeout / 5xx: may have been applied)
  requested -> pending -> (poll) accepted | rejected    (carrier processes asynchronously)
  accepted  -> completed                                (a new delivery attempt actually happened)

An action whose outcome is unknown is never resubmitted until the carrier confirms it has no record of it.
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.carriers.base import CarrierError, CarrierOutcomeUnknown
from app.carriers.registry import get_adapter
from app.domain.errors import DomainError
from app.platform import audit, clock, jobs, outbox
from app.platform.models import AgentTask, CarrierAction, CarrierActionEvent, RuleDecision, Shipment
from app.platform.providers.base import Timer, log_call

MAX_SUBMISSIONS = 3
RECONCILE_DELAYS = [120, 600, 1800, 3600]  # seconds


def idempotency_key(shipment: Shipment, action: str, requested_date, cycle: int) -> str:
    return f"{shipment.id}:{action}:{requested_date or 'next'}:c{cycle}"


def create_from_decision(db: Session, decision: RuleDecision, shipment: Shipment, actor: audit.Actor,
                         ndr_case_id: str | None) -> CarrierAction:
    """The only way to create a carrier action. Requires an ALLOWED decision, or an approved one."""
    if decision.verdict == "DENIED":
        raise DomainError("DECISION_DENIED", "A denied decision cannot produce a carrier action", 409)
    if decision.verdict == "REQUIRES_APPROVAL" and decision.approval_status != "approved":
        raise DomainError("APPROVAL_REQUIRED", "This action needs an approval first", 409)
    if not decision.action:
        raise DomainError("NO_ACTION", "Decision has no carrier action", 409)
    key = idempotency_key(shipment, decision.action, decision.requested_date, shipment.attempt_count)
    existing = db.scalars(select(CarrierAction).where(CarrierAction.idempotency_key == key)).first()
    if existing is not None:
        return existing  # duplicate trigger: same action, same cycle -> same carrier request
    action = CarrierAction(merchant_id=decision.merchant_id, ndr_case_id=ndr_case_id, shipment_id=shipment.id,
                           decision_id=decision.id, carrier_code=shipment.carrier_code, action=decision.action,
                           requested_date=decision.requested_date, requested_window=decision.requested_window,
                           payload={"awb": shipment.tracking_number}, idempotency_key=key, status="requested")
    db.add(action)
    db.flush()
    _event(db, action, "requested", f"Requested via decision {decision.id[:8]}")
    audit.record(db, actor, action.merchant_id, "carrier_action", action.id, "carrier_action.requested",
                 after={"action": action.action, "date": str(action.requested_date), "decision": decision.id})
    jobs.enqueue(db, "dispatch_carrier_action", {"action_id": action.id}, merchant_id=action.merchant_id,
                 dedupe_key=f"dispatch:{action.id}", max_attempts=4)
    outbox.emit(db, action.merchant_id, "carrier_action", action.id, "carrier_action.requested",
                {"ndrCaseId": ndr_case_id, "action": action.action})
    return action


def _event(db: Session, action: CarrierAction, status: str, detail: str | None = None, latency_ms: int | None = None):
    db.add(CarrierActionEvent(merchant_id=action.merchant_id, action_id=action.id, status=status,
                              detail=(detail or "")[:300] or None, latency_ms=latency_ms))


def _run(coro):
    return asyncio.run(coro)


def handle_dispatch(db: Session, job) -> None:
    action = db.get(CarrierAction, job.payload["action_id"])
    if action is None or action.status not in ("requested", "retrying"):
        return
    shipment = db.get(Shipment, action.shipment_id)
    adapter = get_adapter(action.carrier_code)
    action.attempts += 1
    with Timer() as t:
        try:
            result = _run(adapter.request_ndr_action(
                action.action, shipment.tracking_number, action.requested_date.isoformat() if action.requested_date else None,
                action.requested_window, action.idempotency_key))
        except CarrierOutcomeUnknown as exc:
            result = exc
        except CarrierError as exc:
            result = exc
    if isinstance(result, CarrierOutcomeUnknown):
        log_call(db, action.merchant_id, f"carrier:{action.carrier_code}", "ndr_action", False, t.ms, None, "outcome_unknown")
        action.status, action.last_error = "unknown", str(result)[:300]
        _event(db, action, "unknown", f"{result} — will reconcile before any resubmission", t.ms)
        _schedule_reconcile(db, action, 0)
        outbox.emit(db, action.merchant_id, "carrier_action", action.id, "carrier_action.unknown", {"ndrCaseId": action.ndr_case_id})
        return
    if isinstance(result, CarrierError):
        log_call(db, action.merchant_id, f"carrier:{action.carrier_code}", "ndr_action", False, t.ms, None, "unreachable")
        if action.attempts < MAX_SUBMISSIONS:
            action.status, action.last_error = "retrying", str(result)[:300]
            _event(db, action, "retrying", str(result), t.ms)
            raise result  # the job queue retries with backoff; the request never reached the carrier
        _final(db, action, "failed", str(result))
        return
    log_call(db, action.merchant_id, f"carrier:{action.carrier_code}", "ndr_action", True, t.ms, 200)
    _apply_result(db, action, result, t.ms)


def _apply_result(db: Session, action: CarrierAction, result, latency_ms: int | None = None) -> None:
    if result.reference:
        action.carrier_reference = result.reference
    if result.status == "accepted":
        _final(db, action, "accepted", f"Carrier accepted (ref {result.reference})", latency_ms)
    elif result.status == "rejected":
        action.rejection_reason = (result.reason or "rejected")[:200]
        _final(db, action, "rejected", f"Carrier rejected: {action.rejection_reason}", latency_ms)
    elif result.status == "pending":
        action.status = "requested"
        _event(db, action, "requested", f"Carrier queued the instruction (ref {result.reference}); polling", latency_ms)
        _schedule_reconcile(db, action, 0)
    else:
        action.status = "unknown"
        _event(db, action, "unknown", result.reason, latency_ms)
        _schedule_reconcile(db, action, 0)


def _schedule_reconcile(db: Session, action: CarrierAction, step: int) -> None:
    delay = RECONCILE_DELAYS[min(step, len(RECONCILE_DELAYS) - 1)]
    jobs.enqueue(db, "reconcile_carrier_action", {"action_id": action.id, "step": step}, merchant_id=action.merchant_id,
                 run_at=clock.now() + timedelta(seconds=delay), dedupe_key=f"reconcile:{action.id}", max_attempts=3)


def handle_reconcile(db: Session, job) -> None:
    action = db.get(CarrierAction, job.payload["action_id"])
    if action is None or action.status not in ("unknown", "requested"):
        return
    step = int(job.payload.get("step", 0))
    reconcile(db, action, step)


def reconcile(db: Session, action: CarrierAction, step: int = 0, actor: audit.Actor | None = None) -> str:
    adapter = get_adapter(action.carrier_code)
    with Timer() as t:
        try:
            result = _run(adapter.get_ndr_action_status(action.idempotency_key, action.carrier_reference))
        except CarrierError as exc:
            log_call(db, action.merchant_id, f"carrier:{action.carrier_code}", "ndr_status", False, t.ms, None, "error")
            _event(db, action, action.status, f"Reconciliation attempt failed: {exc}", t.ms)
            if step + 1 < len(RECONCILE_DELAYS):
                jobs.enqueue(db, "reconcile_carrier_action", {"action_id": action.id, "step": step + 1},
                             merchant_id=action.merchant_id,
                             run_at=clock.now() + timedelta(seconds=RECONCILE_DELAYS[step + 1]))
            else:
                _final(db, action, "failed", "Could not confirm the outcome with the carrier")
            return "error"
    log_call(db, action.merchant_id, f"carrier:{action.carrier_code}", "ndr_status", True, t.ms, 200)
    if actor is not None:
        audit.record(db, actor, action.merchant_id, "carrier_action", action.id, "carrier_action.reconciled",
                     after={"carrierStatus": result.status})
    if result.status in ("accepted", "rejected"):
        _apply_result(db, action, result, t.ms)
        return result.status
    if result.status == "pending":
        _event(db, action, "requested", "Still processing at the carrier", t.ms)
        if step + 1 < len(RECONCILE_DELAYS):
            jobs.enqueue(db, "reconcile_carrier_action", {"action_id": action.id, "step": step + 1},
                         merchant_id=action.merchant_id, run_at=clock.now() + timedelta(seconds=RECONCILE_DELAYS[step + 1]))
        else:
            _final(db, action, "timed_out", "Carrier did not decide within the reconciliation window")
        return "pending"
    # Carrier confirms it never received the request: now (and only now) it is safe to resubmit.
    if action.attempts < MAX_SUBMISSIONS:
        action.status = "retrying"
        _event(db, action, "retrying", "Carrier has no record of the request; resubmitting with the same key", t.ms)
        jobs.enqueue(db, "dispatch_carrier_action", {"action_id": action.id}, merchant_id=action.merchant_id,
                     dedupe_key=f"dispatch:{action.id}", max_attempts=4)
        return "resubmitted"
    _final(db, action, "failed", "Carrier never confirmed the request after several attempts")
    return "failed"


def _final(db: Session, action: CarrierAction, status: str, detail: str, latency_ms: int | None = None) -> None:
    action.status = status
    action.responded_at = clock.now()
    if status in ("failed", "timed_out"):
        action.last_error = detail[:300]
    _event(db, action, status, detail, latency_ms)
    outbox.emit(db, action.merchant_id, "carrier_action", action.id, f"carrier_action.{status}",
                {"ndrCaseId": action.ndr_case_id, "action": action.action})
    from app.platform.workflows.engine import trigger
    for task in db.scalars(select(AgentTask).where(AgentTask.shipment_id == action.shipment_id,
                                                   AgentTask.status.in_(("active", "waiting")))):
        trigger(db, task, "carrier_response", {"action_id": action.id, "status": status})


def verify_on_new_attempt(db: Session, shipment: Shipment) -> None:
    """Called when the carrier reports out-for-delivery: an accepted reattempt/reschedule actually happened."""
    for action in db.scalars(select(CarrierAction).where(
            CarrierAction.shipment_id == shipment.id, CarrierAction.status == "accepted",
            CarrierAction.action.in_(("reattempt", "reschedule")))):
        action.status = "completed"
        action.verified_at = clock.now()
        _event(db, action, "completed", "Carrier made the new delivery attempt (out for delivery scan)")
        outbox.emit(db, action.merchant_id, "carrier_action", action.id, "carrier_action.completed",
                    {"ndrCaseId": action.ndr_case_id})
