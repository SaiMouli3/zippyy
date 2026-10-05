"""The only contract Zippy's business logic knows about carriers.

To add a carrier: subclass CarrierAdapter, implement the methods below, register it in registry.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.config import get_settings
from app.domain.carrier_types import NormalizedEvent, NormalizedRate, NormalizedShipment
from app import http
from app.models import Order, ShippingQuote


@dataclass
class HttpCall:
    """A carrier-specific request, built from the common order model."""

    method: str
    path: str
    json: dict | None = None
    params: dict | None = None


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


class CarrierAdapter(ABC):
    code: str  # normalized carrier code stored in our DB, e.g. "FASTSHIP"
    name: str  # display name
    webhook_slug: str  # /api/webhooks/{slug}

    # --- request mapping (pure, easy to unit test) ---
    @abstractmethod
    def build_rate_request(self, order: Order) -> HttpCall: ...

    @abstractmethod
    def build_shipment_request(self, order: Order, quote: ShippingQuote) -> HttpCall: ...

    # --- response normalization (pure) ---
    @abstractmethod
    def normalize_rate_response(self, response: dict) -> list[NormalizedRate]: ...

    @abstractmethod
    def normalize_shipment_response(self, response: dict) -> NormalizedShipment: ...

    @abstractmethod
    def normalize_webhook(self, payload: dict) -> NormalizedEvent: ...

    # --- network operations (shared) ---
    async def get_rates(self, order: Order) -> list[NormalizedRate]:
        data = await self._send(self.build_rate_request(order), get_settings().carrier_rate_timeout_seconds)
        return self.normalize_rate_response(data)

    async def create_shipment(self, order: Order, selected_quote: ShippingQuote) -> NormalizedShipment:
        data = await self._send(
            self.build_shipment_request(order, selected_quote), get_settings().carrier_booking_timeout_seconds
        )
        return self.normalize_shipment_response(data)

    async def _send(self, call: HttpCall, timeout: float) -> dict:
        async with http.make_client(get_settings().carrier_base_url, timeout) as client:
            resp = await client.request(call.method, call.path, json=call.json, params=call.params)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CarrierError(f"{self.name} returned HTTP {exc.response.status_code}") from exc
        return resp.json()


class CarrierError(Exception):
    pass
