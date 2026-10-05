"""Mock carrier 1: FastShip. snake_case JSON, flat `service` object, POST rate + POST shipments."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends

from app.mock_carriers import common as c

router = APIRouter(prefix="/mock/fastship", tags=["mock-fastship"])
SLUG = "fastship"

STATUS_LABELS = {
    "CREATED": "BOOKED",
    "PICKED_UP": "PICKED_UP",
    "IN_TRANSIT": "IN_TRANSIT",
    "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
    "DELIVERED": "DELIVERED",
    "DELIVERY_FAILED": "UNDELIVERED",
    "RTO": "RETURNED_TO_ORIGIN",
}


@router.post("/api/v1/rate", dependencies=[Depends(c.chaos(SLUG))])
async def rate(body: dict = Body(...)):
    weight = float(body["weight_kg"])
    if weight > 30:
        return {"success": False, "error": "WEIGHT_LIMIT_EXCEEDED"}
    cod = body.get("payment_mode") == "COD"
    freight = round(100 + 20 * weight, 2)
    cod_charge = 30.0 if cod else 0.0
    tax = round(freight * 0.18, 2)
    return {
        "success": True,
        "service": {
            "service_code": "FAST-AIR",
            "service_name": "FastShip Air Express",
            "freight_charge": freight,
            "cod_charge": cod_charge,
            "tax": tax,
            "total_amount": round(freight + cod_charge + tax, 2),
            "estimated_days": 2,
        },
    }


@router.post("/api/v1/shipments", dependencies=[Depends(c.chaos(SLUG))])
async def create_shipment(body: dict = Body(...)):
    seq = c.next_sequence(SLUG)
    s = c.register_shipment(
        c.MockShipment(
            carrier=SLUG,
            carrier_shipment_id=f"FS-{100000 + seq}",
            tracking_number=f"FST{c.random_digits(9)}",
            reference=body.get("reference"),
        )
    )
    return {"success": True, "shipment_id": s.carrier_shipment_id, "tracking_number": s.tracking_number, "status": "BOOKED"}


def build_webhook(s: c.MockShipment, status: str, event_id: str, at: datetime) -> dict:
    return {
        "event_id": event_id,
        "tracking_number": s.tracking_number,
        "status": STATUS_LABELS[status],
        "remarks": f"FastShip update: {STATUS_LABELS[status]}",
        "location": c.LOCATIONS[status],
        "timestamp": at.isoformat(),
    }
