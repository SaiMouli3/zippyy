"""Carrier-neutral shapes. Business logic only ever sees these."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.enums import ShipmentStatus


@dataclass
class NormalizedRate:
    carrier_code: str
    service_code: str
    service_name: str
    base_charge: Decimal
    cod_charge: Decimal
    additional_charges: Decimal
    tax: Decimal
    total_charge: Decimal
    estimated_min_days: int | None
    estimated_max_days: int | None
    quote_reference: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedShipment:
    carrier_code: str
    carrier_shipment_id: str
    tracking_number: str
    status: ShipmentStatus
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedEvent:
    carrier_code: str
    tracking_number: str
    status: ShipmentStatus
    carrier_status: str
    event_id: str | None
    description: str | None
    location: str | None
    event_time: datetime
    raw: dict = field(default_factory=dict)
