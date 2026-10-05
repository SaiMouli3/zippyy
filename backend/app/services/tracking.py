"""Webhook ingestion (idempotent, regression-safe) and tracking queries."""
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.carrier_types import NormalizedEvent
from app.domain.enums import ShipmentStatus
from app.domain.errors import DomainError, not_found
from app.domain.tracking import is_valid_transition
from app.models import Order, Shipment, ShipmentEvent
from app.services.shipments import get_shipment_for_order


@dataclass
class IngestResult:
    outcome: str  # "applied" | "duplicate" | "ignored"
    shipment_id: str
    current_status: str
    reason: str | None = None


def idempotency_key(ev: NormalizedEvent) -> str:
    if ev.event_id:
        return f"{ev.carrier_code}:{ev.event_id}"
    basis = f"{ev.tracking_number}|{ev.status.value}|{ev.event_time.isoformat()}"
    return f"{ev.carrier_code}:h:{hashlib.sha256(basis.encode()).hexdigest()[:32]}"


def ingest_event(db: Session, ev: NormalizedEvent) -> IngestResult:
    shipment = db.scalars(select(Shipment).where(Shipment.tracking_number == ev.tracking_number)).first()
    if shipment is None or shipment.carrier_code != ev.carrier_code:
        raise not_found("Shipment")

    key = idempotency_key(ev)
    if db.scalars(select(ShipmentEvent.id).where(ShipmentEvent.idempotency_key == key)).first():
        return IngestResult("duplicate", shipment.id, shipment.current_status)

    current = ShipmentStatus(shipment.current_status)
    if not is_valid_transition(current, ev.status):
        return IngestResult("ignored", shipment.id, shipment.current_status, f"{current.value} -> {ev.status.value} not allowed")

    db.add(
        ShipmentEvent(
            shipment_id=shipment.id, idempotency_key=key, carrier_status=ev.carrier_status,
            normalized_status=ev.status.value, description=ev.description, location=ev.location,
            event_time=ev.event_time, raw_event_payload=ev.raw,
        )
    )
    shipment.current_status = ev.status.value
    order = db.get(Order, shipment.order_id)
    order.status = ev.status.value
    try:
        db.commit()
    except IntegrityError:  # concurrent delivery of the same event won the race
        db.rollback()
        return IngestResult("duplicate", shipment.id, shipment.current_status)
    return IngestResult("applied", shipment.id, ev.status.value)


def get_tracking(db: Session, order_id: str) -> dict:
    shipment = get_shipment_for_order(db, order_id)
    if shipment is None or not shipment.tracking_number:
        raise DomainError("NO_SHIPMENT", "No shipment has been created for this order yet", 404)
    return {
        "trackingNumber": shipment.tracking_number,
        "carrier": shipment.carrier_code,
        "currentStatus": shipment.current_status,
        "history": [
            {
                "status": e.normalized_status,
                "timestamp": e.event_time,
                "location": e.location,
                "description": e.description,
            }
            for e in shipment.events
        ],
    }
