import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from .. import config
from ..logs import log, request_id_var

NDR_REASONS = ["CUSTOMER_UNAVAILABLE", "CUSTOMER_REFUSED", "ADDRESS_ISSUE", "PHONE_UNREACHABLE", "COD_NOT_READY"]

_client = httpx.Client()


class CarrierError(Exception):
    """A carrier call failed. `code` is TIMEOUT | HTTP_ERROR | UNREACHABLE | BAD_RESPONSE."""

    def __init__(self, code: str, message: str, duration_ms: float = 0):
        super().__init__(message)
        self.code, self.message, self.duration_ms = code, message, duration_ms


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
        return config.CARRIER_URLS[self.slug]

    def call(self, operation: str, method: str, path: str, order_id: str | None = None, **kw) -> dict:
        """HTTP call to the carrier with the configured timeout, logging and error classification."""
        timeout = config.CARRIER_TIMEOUT_MS / 1000
        start = time.perf_counter()
        ms = lambda: round((time.perf_counter() - start) * 1000, 1)  # noqa: E731
        try:
            r = _client.request(method, f"{self.base}{path}", timeout=timeout,
                                headers={"X-Request-ID": request_id_var.get() or ""}, **kw)
            r.raise_for_status()
            data = r.json()
        except httpx.TimeoutException as e:
            err = CarrierError("TIMEOUT", f"{self.name} did not respond within {config.CARRIER_TIMEOUT_MS} ms", ms())
            log("CARRIER_CALL_FAILED", level="warning", carrier=self.code, operation=operation, orderId=order_id,
                code=err.code, durationMs=err.duration_ms)
            raise err from e
        except httpx.HTTPStatusError as e:
            err = CarrierError("HTTP_ERROR", f"{self.name} returned HTTP {e.response.status_code}", ms())
            log("CARRIER_CALL_FAILED", level="warning", carrier=self.code, operation=operation, orderId=order_id,
                code=err.code, status=e.response.status_code, durationMs=err.duration_ms)
            raise err from e
        except httpx.TransportError as e:
            err = CarrierError("UNREACHABLE", f"{self.name} unreachable: {type(e).__name__}", ms())
            log("CARRIER_CALL_FAILED", level="warning", carrier=self.code, operation=operation, orderId=order_id,
                code=err.code, durationMs=err.duration_ms)
            raise err from e
        except ValueError as e:
            raise CarrierError("BAD_RESPONSE", f"{self.name} returned invalid JSON", ms()) from e
        log("CARRIER_CALL", carrier=self.code, operation=operation, orderId=order_id, status=r.status_code,
            durationMs=ms())
        return data

    @abstractmethod
    def get_rates(self, order: dict) -> list[NormalizedRate]: ...

    @abstractmethod
    def create_shipment(self, order: dict, service: str) -> ShipmentResult: ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookEvent: ...

    @abstractmethod
    def request_reattempt(self, tracking_number: str, requested_date: str,
                          window: str | None, attempt: int) -> ReattemptResult: ...
