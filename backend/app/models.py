import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt() -> DateTime:
    return DateTime(timezone=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("merchant_id", "merchant_order_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    merchant_id: Mapped[str] = mapped_column(String(50), index=True)
    merchant_order_id: Mapped[str] = mapped_column(String(100))
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(20))
    pickup_pincode: Mapped[str] = mapped_column(String(6))
    delivery_pincode: Mapped[str] = mapped_column(String(6))
    weight_grams: Mapped[int] = mapped_column(Integer)
    length_cm: Mapped[int] = mapped_column(Integer)
    width_cm: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[int] = mapped_column(Integer)
    payment_type: Mapped[str] = mapped_column(String(10))
    cod_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(30), default="CREATED")
    created_at: Mapped[datetime] = mapped_column(_dt(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(_dt(), default=_now, onupdate=_now)


class ShippingQuote(Base):
    __tablename__ = "shipping_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)  # one batch per rate fetch
    carrier_code: Mapped[str] = mapped_column(String(30))
    service_code: Mapped[str] = mapped_column(String(50))
    service_name: Mapped[str] = mapped_column(String(100))
    base_charge: Mapped[float] = mapped_column(Numeric(12, 2))
    cod_charge: Mapped[float] = mapped_column(Numeric(12, 2))
    additional_charges: Mapped[float] = mapped_column(Numeric(12, 2))
    tax: Mapped[float] = mapped_column(Numeric(12, 2))
    total_charge: Mapped[float] = mapped_column(Numeric(12, 2))
    estimated_min_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_max_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_carrier_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_dt(), default=_now)
    expires_at: Mapped[datetime] = mapped_column(_dt())


class Shipment(Base):
    """Created when a carrier is selected (quoted_amount frozen); filled in on booking."""

    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("shipping_quotes.id"))
    carrier_code: Mapped[str] = mapped_column(String(30))
    carrier_shipment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)
    selected_service_code: Mapped[str] = mapped_column(String(50))
    quoted_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    current_status: Mapped[str] = mapped_column(String(30), default="CARRIER_SELECTED")
    created_at: Mapped[datetime] = mapped_column(_dt(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(_dt(), default=_now, onupdate=_now)

    events: Mapped[list["ShipmentEvent"]] = relationship(
        back_populates="shipment", order_by="ShipmentEvent.received_at"
    )


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    carrier_status: Mapped[str] = mapped_column(String(60))
    normalized_status: Mapped[str] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_time: Mapped[datetime] = mapped_column(_dt())
    raw_event_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(_dt(), default=_now)

    shipment: Mapped[Shipment] = relationship(back_populates="events")
