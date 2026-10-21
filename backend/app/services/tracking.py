"""Webhook ingestion (idempotent, regression-safe) and tracking queries."""
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.carrier_types import NormalizedEvent
from app.domain.enums import ShipmentStatus
from app.domain.errors import DomainError
from app.domain.tracking import is_valid_transition
from app.models import Order, Shipment, ShipmentEvent
from app.services.shipments import get_shipment_for_order


@dataclass
class IngestResult:
    outcome: str  # "applied" | "duplicate" | "ignored" | "unknown_awb"
    shipment_id: str | None
    current_status: str | None
    reason: str | None = None
    merchant_id: str | None = None


def idempotency_key(ev: NormalizedEvent) -> str:
    if ev.event_id:
        return f"{ev.carrier_code}:{ev.event_id}"
    basis = f"{ev.tracking_number}|{ev.status.value}|{ev.event_time.isoformat()}"
    return f"{ev.carrier_code}:h:{hashlib.sha256(basis.encode()).hexdigest()[:32]}"


def ingest_event(db: Session, ev: NormalizedEvent, webhook_id: str | None = None, commit: bool = False) -> IngestResult:
    """Apply one normalized carrier event. Idempotent (event key), regression-safe (status machine), and for
    platform shipments it drives the NDR / pre-delivery workflows in the same transaction."""
    shipment = db.scalars(select(Shipment).where(Shipment.tracking_number == ev.tracking_number)).first()
    if shipment is None or shipment.carrier_code != ev.carrier_code:
        return IngestResult("unknown_awb", None, None, "unknown AWB")

    key = idempotency_key(ev)
    if db.scalars(select(ShipmentEvent.id).where(ShipmentEvent.idempotency_key == key)).first():
        return IngestResult("duplicate", shipment.id, shipment.current_status, merchant_id=shipment.merchant_id)

    current = ShipmentStatus(shipment.current_status) if shipment.current_status in ShipmentStatus.__members__ else None
    if current is None or not is_valid_transition(current, ev.status):
        return IngestResult("ignored", shipment.id, shipment.current_status,
                            f"{shipment.current_status} -> {ev.status.value} not allowed", shipment.merchant_id)

    event = ShipmentEvent(
        shipment_id=shipment.id, idempotency_key=key, carrier_status=ev.carrier_status,
        normalized_status=ev.status.value, description=ev.description, location=ev.location,
        event_time=ev.event_time, raw_event_payload=ev.raw, merchant_id=shipment.merchant_id,
        carrier_reason=(ev.reason or None), webhook_id=webhook_id,
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:  # concurrent delivery of the same event won the race
        return IngestResult("duplicate", shipment.id, shipment.current_status, merchant_id=shipment.merchant_id)
    shipment.current_status = ev.status.value
    shipment.version = (shipment.version or 0) + 1
    order = db.get(Order, shipment.order_id)
    order.status = ev.status.value
    from app.platform import ndr  # platform workflows (no-op for legacy sandbox shipments)
    ndr.on_tracking_event(db, shipment, order, event, ev.status.value)
    if commit:
        db.commit()
    return IngestResult("applied", shipment.id, ev.status.value, merchant_id=shipment.merchant_id)


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
