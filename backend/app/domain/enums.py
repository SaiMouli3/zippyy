from enum import Enum


class PaymentType(str, Enum):
    PREPAID = "PREPAID"
    COD = "COD"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    QUOTED = "QUOTED"
    CARRIER_SELECTED = "CARRIER_SELECTED"
    SHIPMENT_CREATED = "SHIPMENT_CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    RTO = "RTO"


class ShipmentStatus(str, Enum):
    """Normalized tracking statuses. Every carrier vocabulary maps onto these."""

    SHIPMENT_CREATED = "SHIPMENT_CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    DELIVERED = "DELIVERED"
    RTO = "RTO"
