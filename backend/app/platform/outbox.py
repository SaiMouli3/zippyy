"""Transactional outbox. Events are inserted in the same transaction as the state change; the SSE stream and
outbound subscribers read them afterwards, so nothing is published for a change that rolled back.

Emitting an event that concerns an NDR case also marks the case's read model for refresh before commit."""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.platform.models import OutboxEvent


def emit(db: Session, merchant_id: str, aggregate: str, aggregate_id: str, event_type: str,
         payload: dict | None = None, correlation_id: str | None = None) -> None:
    payload = payload or {}
    db.add(OutboxEvent(merchant_id=merchant_id, aggregate=aggregate, aggregate_id=aggregate_id,
                       event_type=event_type, payload=payload, correlation_id=correlation_id))
    case_id = aggregate_id if aggregate == "ndr_case" else payload.get("ndrCaseId")
    if case_id:
        db.info.setdefault("touched_cases", set()).add(case_id)
    if aggregate in ("shipment", "agent_task") and payload.get("shipmentId", aggregate_id if aggregate == "shipment" else None):
        db.info.setdefault("touched_shipments", set()).add(payload.get("shipmentId") or aggregate_id)


@event.listens_for(Session, "before_commit")
def _refresh_read_models(session: Session) -> None:
    cases = session.info.pop("touched_cases", set())
    shipments = session.info.pop("touched_shipments", set())
    if not cases and not shipments:
        return
    from app.platform import case_summary
    case_summary.refresh_many(session, cases, shipments)
