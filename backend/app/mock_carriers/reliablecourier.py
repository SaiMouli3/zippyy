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
    "RTO_DELIVERED": 700,
}
REASON_CODES = {"CUSTOMER_UNAVAILABLE": "R01", "REFUSED": "R02", "ADDRESS_ISSUE": "R03", "PHONE_UNREACHABLE": "R04",
                "COD_NOT_READY": "R05", "OTHER": "R99"}
STATUS_TEXT = {
    100: "Order registered",
    200: "Parcel collected from sender",
    300: "Parcel moving between facilities",
    400: "Courier is out to deliver",
    450: "Delivery attempt unsuccessful",
    500: "Parcel handed to recipient",
    600: "Parcel is being returned to sender",
    700: "Returned parcel delivered to sender",
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


def build_webhook(s: c.MockShipment, status: str, event_id: str, at: datetime, reason: str | None = None) -> dict:
    code = STATUS_CODES[status]
    body = {
        "notification": {
            "id": event_id,
            "trackingCode": s.tracking_number,
            "code": code,
            "message": STATUS_TEXT[code],
            "place": c.LOCATIONS[status],
            "ts": at.strftime("%Y-%m-%d %H:%M:%S"),  # UTC, no timezone marker
        }
    }
    if status == "DELIVERY_FAILED":
        reason = reason or "CUSTOMER_UNAVAILABLE"
        body["notification"]["reasonCode"] = REASON_CODES.get(reason, "R99")
        body["notification"]["message"] = c.NDR_REASONS.get(reason, reason)
    return body


@router.put("/ndr", dependencies=[Depends(c.chaos(SLUG))])
async def ndr(body: dict = Body(...)):
    key = body.get("requestKey")
    if not key:
        return {"code": 400, "message": "requestKey required"}
    existing = c.ndr_lookup(key)
    if existing:
        return existing["response"]
    state, reason = c.ndr_decide(body.get("trackingCode", ""), body.get("date"), 3)
    if state == "server_error":
        from fastapi import HTTPException
        raise HTTPException(500, "internal error")
    ref = f"RC-NDR-{c.next_sequence('rc-ndr') + 300}"
    final = "accepted" if state in ("accepted", "timeout") else state
    response = ({"code": 200, "ref": ref, "state": "accepted"} if final == "accepted"
                else {"code": 202, "ref": ref, "state": "processing"} if final == "pending"
                else {"code": 409, "ref": ref, "message": reason})
    c.ndr_store(key, {"awb": body.get("trackingCode"), "state": final, "reason": reason, "response": response, "ref": ref})
    if state == "timeout":
        from fastapi import HTTPException
        raise HTTPException(503, "upstream unavailable")
    return response


@router.get("/ndr/{request_key}")
async def ndr_status(request_key: str):
    rec = c.ndr_lookup(request_key)
    if rec is None:
        from fastapi import HTTPException
        raise HTTPException(404, "not found")
    if rec["state"] == "accepted":
        return {"code": 200, "ref": rec["ref"], "state": "accepted"}
    if rec["state"] == "pending":
        return {"code": 202, "ref": rec["ref"], "state": "processing"}
    return {"code": 409, "ref": rec["ref"], "message": rec.get("reason")}
