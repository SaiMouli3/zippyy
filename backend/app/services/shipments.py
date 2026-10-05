"""Carrier selection and shipment booking."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.carriers.registry import get_adapter
from app.config import get_settings
from app.domain.enums import ShipmentStatus
from app.domain.errors import DomainError
from app.models import Shipment, ShipmentEvent, ShippingQuote
from app.services.orders import get_order
from app.services.rates import as_utc, latest_quotes


def get_shipment_for_order(db: Session, order_id: str) -> Shipment | None:
    return db.scalars(select(Shipment).where(Shipment.order_id == order_id)).first()


def select_carrier(db: Session, order_id: str, carrier_code: str, service_code: str, quoted_amount: Decimal) -> Shipment:
    order = get_order(db, order_id)
    carrier_code = carrier_code.upper()

    shipment = get_shipment_for_order(db, order_id)
    if shipment and shipment.tracking_number:
        raise DomainError("ALREADY_BOOKED", "A shipment has already been created for this order", 409)

    latest = latest_quotes(db, order_id)
    if not latest:
        raise DomainError("NO_QUOTES", "No rates fetched for this order yet; request rates first", 409)

    quote = next((q for q in latest if q.carrier_code == carrier_code and q.service_code == service_code), None)
    if quote is None:
        exists_older = db.scalars(
            select(ShippingQuote).where(
                ShippingQuote.order_id == order_id,
                ShippingQuote.carrier_code == carrier_code,
                ShippingQuote.service_code == service_code,
            )
        ).first()
        if exists_older:
            raise DomainError("STALE_QUOTE", "That quote is not from the latest rate request; refresh rates", 409)
        raise DomainError("QUOTE_NOT_FOUND", "No such quote for this order", 404)

    if as_utc(quote.expires_at) <= datetime.now(timezone.utc):
        raise DomainError("QUOTE_EXPIRED", "Quote has expired; refresh rates", 409)
    if Decimal(str(quoted_amount)).quantize(Decimal("0.01")) != Decimal(str(quote.total_charge)).quantize(Decimal("0.01")):
        raise DomainError(
            "AMOUNT_MISMATCH", f"quotedAmount does not match stored quote ({quote.total_charge})", 409
        )

    if shipment is None:
        shipment = Shipment(order_id=order.id)
        db.add(shipment)
    shipment.quote_id = quote.id
    shipment.carrier_code = quote.carrier_code
    shipment.selected_service_code = quote.service_code
    shipment.quoted_amount = quote.total_charge  # frozen from the stored quote, never from the client
    shipment.current_status = "CARRIER_SELECTED"
    order.status = "CARRIER_SELECTED"
    db.commit()
    return shipment


async def create_shipment(db: Session, order_id: str) -> Shipment:
    order = get_order(db, order_id)
    shipment = get_shipment_for_order(db, order_id)
    if shipment is None:
        raise DomainError("NO_CARRIER_SELECTED", "Select a carrier before creating the shipment", 409)
    if shipment.tracking_number:
        return shipment  # idempotent: never book twice

    quote = db.get(ShippingQuote, shipment.quote_id)
    adapter = get_adapter(shipment.carrier_code)
    try:
        result = await asyncio.wait_for(
            adapter.create_shipment(order, quote), timeout=get_settings().carrier_booking_timeout_seconds + 0.5
        )
    except Exception as exc:
        # Booking is NOT retried automatically: a timeout may still have created the shipment at the carrier.
        raise DomainError("CARRIER_ERROR", f"{adapter.name} booking failed: {str(exc) or type(exc).__name__}", 502)

    now = datetime.now(timezone.utc)
    shipment.carrier_shipment_id = result.carrier_shipment_id
    shipment.tracking_number = result.tracking_number
    shipment.current_status = ShipmentStatus.SHIPMENT_CREATED.value
    order.status = ShipmentStatus.SHIPMENT_CREATED.value
    db.add(
        ShipmentEvent(
            shipment_id=shipment.id,
            idempotency_key=f"{adapter.code}:created:{result.tracking_number}",
            carrier_status="CREATED",
            normalized_status=ShipmentStatus.SHIPMENT_CREATED.value,
            description=f"Shipment booked with {adapter.name}",
            location=None,
            event_time=now,
            raw_event_payload=result.raw,
            received_at=now,
        )
    )
    db.commit()
    return shipment


def list_shipments(db: Session) -> list[Shipment]:
    return list(db.scalars(select(Shipment).order_by(Shipment.created_at.desc())))

