"""Shipment import (merchant systems push parcels booked with any carrier) and shipment read models."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.models import Order, Shipment, ShipmentEvent
from app.platform import audit, clock, outbox
from app.platform.customers import CustomerInput, upsert_customer
from app.platform.ids import short_code
from app.platform.models import Carrier


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CustomerIn(_In):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=10, max_length=16)
    email: str | None = Field(default=None, max_length=254)


class AddressIn(_In):
    line1: str = Field(min_length=1, max_length=300)
    line2: str | None = Field(default=None, max_length=300)
    landmark: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    pincode: str

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v: str) -> str:
        if not re.fullmatch(r"[1-9]\d{5}", v):
            raise ValueError("must be a 6-digit pincode")
        return v


class ConsentIn(_In):
    whatsapp: str | None = Field(default=None, max_length=300, description="Evidence, e.g. 'checkout opt-in v3, order #1042'")
    voice: str | None = Field(default=None, max_length=300)


class ShipmentImport(_In):
    merchant_order_id: str = Field(min_length=1, max_length=100)
    customer: CustomerIn
    address: AddressIn
    payment_mode: str = Field(pattern="^(PREPAID|COD)$")
    cod_amount_paise: int = Field(default=0, ge=0, le=10_000_000)
    order_value_paise: int = Field(ge=0, le=100_000_000)
    carrier_code: str = Field(min_length=2, max_length=30)
    awb: str = Field(min_length=4, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    carrier_shipment_id: str | None = Field(default=None, max_length=100)
    pickup_pincode: str = Field(default="560001", pattern=r"^[1-9]\d{5}$")
    weight_grams: int = Field(default=500, gt=0, le=50_000)
    eta_start: datetime | None = None
    eta_end: datetime | None = None
    consent: ConsentIn = Field(default_factory=ConsentIn)

    @model_validator(mode="after")
    def _cod(self):
        if self.payment_mode == "COD" and self.cod_amount_paise <= 0:
            raise ValueError("codAmountPaise must be > 0 for COD")
        if self.payment_mode == "PREPAID":
            self.cod_amount_paise = 0
        return self


def import_shipment(db: Session, merchant_id: str, data: ShipmentImport, actor: audit.Actor) -> tuple[Shipment, bool]:
    """Idempotent on (merchant, merchant_order_id). Returns (shipment, created)."""
    existing = db.scalars(select(Order).where(Order.merchant_id == merchant_id,
                                              Order.merchant_order_id == data.merchant_order_id)).first()
    if existing is not None:
        shipment = db.scalars(select(Shipment).where(Shipment.order_id == existing.id)).first()
        if shipment is None or shipment.tracking_number != data.awb:
            raise DomainError("ORDER_CONFLICT", "This order was imported earlier with different shipment details", 409)
        return shipment, False
    carrier_code = data.carrier_code.upper()
    if db.scalars(select(Carrier).where(Carrier.code == carrier_code, Carrier.active.is_(True))).first() is None:
        raise DomainError("UNKNOWN_CARRIER", f"Carrier {carrier_code} is not integrated", 422)
    if db.scalars(select(Shipment.id).where(Shipment.tracking_number == data.awb)).first():
        raise DomainError("DUPLICATE_AWB", "This AWB is already registered", 409)

    customer, address = upsert_customer(db, merchant_id, CustomerInput(
        name=data.customer.name, phone=data.customer.phone, email=data.customer.email, line1=data.address.line1,
        line2=data.address.line2, landmark=data.address.landmark, city=data.address.city, state=data.address.state,
        pincode=data.address.pincode, whatsapp_consent_evidence=data.consent.whatsapp,
        voice_consent_evidence=data.consent.voice))
    order = Order(merchant_id=merchant_id, merchant_order_id=data.merchant_order_id, code=short_code("ZPY-ORD"),
                  customer_id=customer.id, address_id=address.id, pickup_pincode=data.pickup_pincode,
                  delivery_pincode=data.address.pincode, weight_grams=data.weight_grams, length_cm=20, width_cm=15,
                  height_cm=10, payment_type=data.payment_mode, cod_amount=data.cod_amount_paise / 100,
                  order_value_paise=data.order_value_paise, status="SHIPMENT_CREATED", source="api")
    db.add(order)
    db.flush()
    now = clock.now()
    shipment = Shipment(order_id=order.id, carrier_code=carrier_code, carrier_shipment_id=data.carrier_shipment_id,
                        tracking_number=data.awb, current_status="SHIPMENT_CREATED", merchant_id=merchant_id,
                        code=short_code("ZPY-SHP"), eta_start=data.eta_start, eta_end=data.eta_end, created_at=now)
    db.add(shipment)
    db.flush()
    db.add(ShipmentEvent(shipment_id=shipment.id, idempotency_key=f"{carrier_code}:imported:{data.awb}",
                         carrier_status="IMPORTED", normalized_status="SHIPMENT_CREATED",
                         description="Shipment imported into Zippyy", event_time=now, received_at=now,
                         merchant_id=merchant_id, raw_event_payload={}))
    audit.record(db, actor, merchant_id, "shipment", shipment.id, "shipment.imported",
                 after={"awb": data.awb, "carrier": carrier_code, "order": data.merchant_order_id})
    outbox.emit(db, merchant_id, "shipment", shipment.id, "shipment.imported", {"shipmentId": shipment.id})
    return shipment, True
