"""Shipment status transition rules. A webhook whose status is not reachable from the
shipment's current status is quarantined and does NOT update the shipment.

Forward skips are allowed (carriers drop events); going backwards, repeating the same
status under a new event id, or leaving DELIVERED is not. NDR may only follow a transit
status, and after an NDR the shipment can only go out for delivery again or be delivered
(so a second NDR requires a new OUT_FOR_DELIVERY first)."""

ALLOWED: dict[str, set[str]] = {
    "SHIPMENT_CREATED": {"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"},
    "PICKED_UP": {"IN_TRANSIT", "OUT_FOR_DELIVERY"},
    "IN_TRANSIT": {"OUT_FOR_DELIVERY", "NDR"},
    "OUT_FOR_DELIVERY": {"DELIVERED", "NDR"},
    "NDR": {"OUT_FOR_DELIVERY", "DELIVERED"},
    "DELIVERED": set(),
}


def is_valid(current: str, new: str) -> bool:
    return new in ALLOWED.get(current, set())
