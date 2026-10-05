"""Shared plumbing for the mock carriers: chaos switches, in-memory shipment state, webhook delivery.

Each carrier module (fastship.py, ...) is written as if it were a separate service:
it knows nothing about Zippy's models or adapters.
"""
import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

# Carrier-side lifecycle (the mock's own neutral steps; each carrier renders them in its own vocabulary).
LIFECYCLE = ["CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
EXCEPTIONS = {"DELIVERY_FAILED", "RTO"}


# ---------------------------------------------------------------- chaos switches
_chaos: dict[str, dict] = {}


def set_chaos(carrier: str, failure: bool, delay_ms: int) -> dict:
    _chaos[carrier] = {"failure": failure, "delay_ms": delay_ms}
    return _chaos[carrier]


def get_chaos(carrier: str) -> dict:
    return _chaos.get(carrier, {"failure": False, "delay_ms": 0})


def chaos(carrier: str):
    """FastAPI dependency: honours ?failure=true / ?delay=3000, falling back to /mock/{carrier}/config."""

    async def dependency(failure: bool | None = None, delay: int | None = None) -> None:
        cfg = get_chaos(carrier)
        delay_ms = delay if delay is not None else cfg["delay_ms"]
        fail = failure if failure is not None else cfg["failure"]
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        if fail:
            raise HTTPException(status_code=500, detail=f"{carrier}: simulated carrier failure")

    return dependency


# ---------------------------------------------------------------- shipment state
@dataclass
class MockShipment:
    carrier: str  # slug, e.g. "fastship"
    carrier_shipment_id: str
    tracking_number: str
    reference: str | None
    status: str = "CREATED"
    location: str = "Origin Hub"
    seq: int = 0
    history: list[str] = field(default_factory=lambda: ["CREATED"])


_shipments: dict[str, MockShipment] = {}
_counters: dict[str, int] = {}


def next_sequence(carrier: str) -> int:
    _counters[carrier] = _counters.get(carrier, 0) + 1
    return _counters[carrier]


def random_digits(n: int) -> str:
    return "".join(random.choices("0123456789", k=n))


def register_shipment(s: MockShipment) -> MockShipment:
    _shipments[s.tracking_number] = s
    return s


def find_shipment(tracking_number: str) -> MockShipment | None:
    return _shipments.get(tracking_number)


def all_shipments() -> list[MockShipment]:
    return list(_shipments.values())


def next_status_of(s: MockShipment) -> str | None:
    if s.status in EXCEPTIONS or s.status == "DELIVERED":
        return None
    return LIFECYCLE[LIFECYCLE.index(s.status) + 1]


def reset_state() -> None:
    _shipments.clear()
    _counters.clear()
    _chaos.clear()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


LOCATIONS = {
    "CREATED": "Bengaluru Origin Hub",
    "PICKED_UP": "Bengaluru Pickup Point",
    "IN_TRANSIT": "Hyderabad Sorting Hub",
    "OUT_FOR_DELIVERY": "Hyderabad Delivery Station",
    "DELIVERED": "Hyderabad - Customer Address",
    "DELIVERY_FAILED": "Hyderabad Delivery Station",
    "RTO": "Hyderabad Delivery Station",
}
