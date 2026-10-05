"""Mock carrier 2: QuickExpress. camelCase JSON, nested charges, POST rates/check + POST booking/create."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends

from app.mock_carriers import common as c

router = APIRouter(prefix="/mock/quickexpress", tags=["mock-quickexpress"])
SLUG = "quickexpress"

STATE_LABELS = {
    "CREATED": "SHIPMENT_CREATED",
    "PICKED_UP": "PICKUP_DONE",
    "IN_TRANSIT": "IN_TRANSIT",
    "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
    "DELIVERED": "DELIVERED",
    "DELIVERY_FAILED": "DELIVERY_ATTEMPT_FAILED",
    "RTO": "RTO_INITIATED",
}


@router.post("/rates/check", dependencies=[Depends(c.chaos(SLUG))])
async def rates_check(body: dict = Body(...)):
    kg = body["weightInGrams"] / 1000
    if kg > 25:
        return {"status": "UNAVAILABLE", "reason": "OVERWEIGHT"}
    seq = c.next_sequence("qe-quote")
    shipping = round(90 + 20 * kg, 2)
    cod = 35.0 if body.get("isCod") else 0.0
    fuel = 10.0
    gst = round((shipping + cod + fuel) * 0.18, 2)
    return {
        "status": "AVAILABLE",
        "quoteId": f"QE-Q-{10000 + seq}",
        "charges": {"shipping": shipping, "cod": cod, "fuelSurcharge": fuel, "gst": gst},
        "payable": round(shipping + cod + fuel + gst, 2),
        "deliveryEstimate": {"minimumDays": 2, "maximumDays": 3},
        "product": "EXPRESS",
    }


@router.post("/booking/create", dependencies=[Depends(c.chaos(SLUG))])
async def booking_create(body: dict = Body(...)):
    seq = c.next_sequence(SLUG)
    s = c.register_shipment(
        c.MockShipment(
            carrier=SLUG,
            carrier_shipment_id=f"QE-B-{10000 + seq}",
            tracking_number=f"QE{c.random_digits(9)}",
            reference=body.get("clientReference"),
        )
    )
    return {
        "bookingStatus": "CONFIRMED",
        "booking": {"bookingId": s.carrier_shipment_id, "awb": s.tracking_number, "currentState": "SHIPMENT_CREATED"},
    }


def build_webhook(s: c.MockShipment, status: str, event_id: str, at: datetime) -> dict:
    return {
        "eventId": event_id,
        "awb": s.tracking_number,
        "state": STATE_LABELS[status],
        "hub": {"city": c.LOCATIONS[status]},
        "note": f"QuickExpress scan: {STATE_LABELS[status]}",
        "occurredAt": int(at.timestamp() * 1000),  # epoch millis
    }
