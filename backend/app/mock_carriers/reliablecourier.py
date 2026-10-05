"""Mock carrier 3: ReliableCourier. GET with query params for options, PUT for orders, numeric status codes."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query

from app.mock_carriers import common as c

router = APIRouter(prefix="/mock/reliablecourier", tags=["mock-reliablecourier"])
SLUG = "reliablecourier"

STATUS_CODES = {
    "CREATED": 100,
    "PICKED_UP": 200,
    "IN_TRANSIT": 300,
    "OUT_FOR_DELIVERY": 400,
    "DELIVERED": 500,
    "DELIVERY_FAILED": 450,
    "RTO": 600,
}
STATUS_TEXT = {
    100: "Order registered",
    200: "Parcel collected from sender",
    300: "Parcel moving between facilities",
    400: "Courier is out to deliver",
    450: "Delivery attempt unsuccessful",
    500: "Parcel handed to recipient",
    600: "Parcel is being returned to sender",
}


@router.get("/shipping-options", dependencies=[Depends(c.chaos(SLUG))])
async def shipping_options(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    weight: float = 1,
    cod: bool = False,
    amount: float = 0,
):
    return _options(weight, cod)


def _options(weight: float, cod: bool) -> dict:
    def option(oid: str, name: str, base: float, handling: float, eta: str) -> dict:
        fee = 25.0 if cod else 0.0
        tax = round((base + handling + fee) * 0.18, 1)
        return {
            "id": oid,
            "name": name,
            "rate": {
                "base": base,
                "handling": handling,
                "cashCollectionFee": fee,
                "taxAmount": tax,
                "grandTotal": round(base + handling + fee + tax, 1),
            },
            "eta": eta,
        }

    return {
        "code": 200,
        "data": [
            option("RC-SURFACE", "Reliable Surface", 60 + 20 * weight, 10.0, "4-5 business days"),
            option("RC-AIR", "Reliable Air", 100 + 20 * weight, 12.0, "2-3 business days"),
        ],
    }


@router.put("/orders", dependencies=[Depends(c.chaos(SLUG))])
async def create_order(body: dict = Body(...)):
    seq = c.next_sequence(SLUG)
    s = c.register_shipment(
        c.MockShipment(
            carrier=SLUG,
            carrier_shipment_id=f"RC-DO-{10000 + seq}",
            tracking_number=f"RC{c.random_digits(10)}",
            reference=body.get("ref"),
        )
    )
    return {"result": "ACCEPTED", "deliveryOrder": {"id": s.carrier_shipment_id, "trackingCode": s.tracking_number}}


def build_webhook(s: c.MockShipment, status: str, event_id: str, at: datetime) -> dict:
    code = STATUS_CODES[status]
    return {
        "notification": {
            "id": event_id,
            "trackingCode": s.tracking_number,
            "code": code,
            "message": STATUS_TEXT[code],
            "place": c.LOCATIONS[status],
            "ts": at.strftime("%Y-%m-%d %H:%M:%S"),  # UTC, no timezone marker
        }
    }
