from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from .. import config

http = httpx.Client(timeout=config.CARRIER_TIMEOUT)

NDR_REASONS = ["CUSTOMER_UNAVAILABLE", "CUSTOMER_REFUSED", "ADDRESS_ISSUE", "PHONE_UNREACHABLE", "COD_NOT_READY"]


class NormalizedRate(BaseModel):
    """The only rate shape the rest of Zippy (and the frontend) ever sees."""
    carrier: str
    carrierName: str
    service: str
    serviceName: str
    price: float
    etaMinDays: int
    etaMaxDays: int


@dataclass
class ShipmentResult:
    carrier_shipment_id: str
    tracking_number: str


@dataclass
class WebhookEvent:
    tracking_number: str
    status: str            # internal status
    event_id: str
    reason: str | None = None


@dataclass
class ReattemptResult:
    status: str            # ACCEPTED | REJECTED
    message: str
    raw: dict


class CarrierAdapter(ABC):
    code: str   # internal carrier code, e.g. FASTSHIP
    slug: str   # url slug, e.g. fastship
    name: str

    @property
    def base(self) -> str:
        return f"{config.CARRIER_BASE_URL}/mock/{self.slug}"

    @abstractmethod
    def get_rates(self, order: dict) -> list[NormalizedRate]: ...

    @abstractmethod
    def create_shipment(self, order: dict, service: str) -> ShipmentResult: ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookEvent: ...

    @abstractmethod
    def request_reattempt(self, tracking_number: str, requested_date: str,
                          window: str | None, attempt: int) -> ReattemptResult: ...
