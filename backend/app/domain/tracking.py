"""Shipment status rules: ordering and regression protection."""
from app.domain.enums import ShipmentStatus as S

_RANK = {
    S.SHIPMENT_CREATED: 0,
    S.PICKED_UP: 1,
    S.IN_TRANSIT: 2,
    S.OUT_FOR_DELIVERY: 3,
    S.DELIVERY_FAILED: 4,
    S.DELIVERED: 5,
    S.RTO: 5,
}
TERMINAL = {S.DELIVERED, S.RTO}


def is_valid_transition(current: S, new: S) -> bool:
    """Forward moves are allowed (carriers may skip scans). Backwards moves are not,
    except a failed attempt can go back out for delivery. Terminal states are final."""
    if current == new:
        return False
    if current in TERMINAL:
        return False
    if current == S.DELIVERY_FAILED and new == S.OUT_FOR_DELIVERY:
        return True
    return _RANK[new] > _RANK[current]
