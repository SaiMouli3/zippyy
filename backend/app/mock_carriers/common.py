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

# Carrier-side NDR reason vocabulary (each carrier renders these its own way).
NDR_REASONS = {
    "CUSTOMER_UNAVAILABLE": "Consignee not available",
    "REFUSED": "Consignee refused delivery",
    "ADDRESS_ISSUE": "Address incomplete / not found",
    "PHONE_UNREACHABLE": "Consignee phone switched off",
    "COD_NOT_READY": "Cash not ready",
    "OTHER": "Delivery could not be attempted",
}


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


# ---------------------------------------------------------------- NDR instructions
# idempotency key -> stored response; the same key always returns the same answer (as a real carrier API would).
_ndr_requests: dict[str, dict] = {}
# Per-AWB behaviour for demos/tests: accept | reject | timeout_then_accept | pending_then_accept | pending_then_reject
_ndr_behaviour: dict[str, str] = {}


def set_ndr_behaviour(awb: str, behaviour: str) -> None:
    _ndr_behaviour[awb] = behaviour


def ndr_decide(awb: str, requested_date: str | None, max_days: int) -> tuple[str, str | None]:
    """Returns (state, reason): state in accepted | rejected | timeout | pending."""
    behaviour = _ndr_behaviour.get(awb, "accept")
    if behaviour == "reject":
        return "rejected", "Reattempt not possible: shipment already marked for return"
    if requested_date:
        try:
            days = (datetime.fromisoformat(requested_date).date() - utcnow().date()).days
        except ValueError:
            return "rejected", "Invalid date"
        if days > max_days:
            return "rejected", f"Date beyond {max_days}-day window"
    if behaviour == "timeout_then_accept":
        return "timeout", None
    if behaviour == "server_error":
        return "server_error", None
    if behaviour.startswith("pending_then"):
        return "pending", None
    return "accepted", None


def ndr_store(key: str, record: dict) -> dict:
    return _ndr_requests.setdefault(key, record)


def ndr_lookup(key: str) -> dict | None:
    rec = _ndr_requests.get(key)
    if rec and rec.get("state") == "pending":
        # The carrier finishes processing asynchronously; by the time anyone asks again it has decided.
        behaviour = _ndr_behaviour.get(rec.get("awb", ""), "pending_then_accept")
        rec["state"] = "rejected" if behaviour == "pending_then_reject" else "accepted"
        if rec["state"] == "rejected":
            rec["reason"] = "Hub capacity full for requested date"
    return rec


def sign_webhook(zippy_slug: str, payload: dict) -> tuple[bytes, dict]:
    """Carriers sign webhooks with a shared secret: X-Carrier-Signature = hex(HMAC-SHA256(secret, body))."""
    import hashlib
    import hmac
    import json

    from app.config import get_settings

    secret = getattr(get_settings(), f"carrier_webhook_secret_{zippy_slug}")
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return raw, {"content-type": "application/json",
                 "x-carrier-signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}


def reset_state() -> None:
    _shipments.clear()
    _counters.clear()
    _chaos.clear()
    _ndr_requests.clear()
    _ndr_behaviour.clear()


def utcnow() -> datetime:
    # The mock carriers follow the platform clock so simulated time (demo seeding, tests) stays consistent.
    from app.platform import clock
    return clock.now() if clock else datetime.now(timezone.utc)


LOCATIONS = {
    "CREATED": "Bengaluru Origin Hub",
    "PICKED_UP": "Bengaluru Pickup Point",
    "IN_TRANSIT": "Hyderabad Sorting Hub",
    "OUT_FOR_DELIVERY": "Hyderabad Delivery Station",
    "DELIVERED": "Hyderabad - Customer Address",
    "DELIVERY_FAILED": "Hyderabad Delivery Station",
    "RTO": "Hyderabad Delivery Station",
    "RTO_DELIVERED": "Bengaluru Origin Hub",
}
