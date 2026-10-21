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
    "RTO_DELIVERED": "RTO_DELIVERED",
}
NDR_CODES = {"CUSTOMER_UNAVAILABLE": "CNA", "REFUSED": "REF", "ADDRESS_ISSUE": "ADI", "PHONE_UNREACHABLE": "PNR",
             "COD_NOT_READY": "CNR", "OTHER": "OTH"}


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


def build_webhook(s: c.MockShipment, status: str, event_id: str, at: datetime, reason: str | None = None) -> dict:
    body = {
        "event_id": event_id,
        "tracking_number": s.tracking_number,
        "status": STATUS_LABELS[status],
        "remarks": f"FastShip update: {STATUS_LABELS[status]}",
        "location": c.LOCATIONS[status],
        "timestamp": at.isoformat(),
    }
    if status == "DELIVERY_FAILED":
        reason = reason or "CUSTOMER_UNAVAILABLE"
        body["ndr_reason"] = NDR_CODES.get(reason, "OTH")
        body["remarks"] = c.NDR_REASONS.get(reason, reason)
    return body


@router.post("/api/v1/ndr/actions", dependencies=[Depends(c.chaos(SLUG))])
async def ndr_action(body: dict = Body(...)):
    key = body.get("client_request_id")
    if not key or not body.get("awb"):
        return {"success": False, "error": "MISSING_FIELDS"}
    existing = c.ndr_lookup(key)
    if existing:
        return existing["response"]
    state, reason = c.ndr_decide(body["awb"], body.get("preferred_date"), 3)
    if state == "server_error":
        from fastapi import HTTPException
        raise HTTPException(500, "internal error")  # nothing stored: the carrier never processed it
    ref = f"FSNDR-{c.next_sequence('fs-ndr') + 50000}"
    final = "accepted" if state in ("accepted", "timeout") else state
    response = ({"success": True, "request_id": ref, "status": "ACCEPTED"} if final == "accepted"
                else {"success": True, "request_id": ref, "status": "PENDING"} if final == "pending"
                else {"success": False, "request_id": ref, "status": "REJECTED", "error": reason})
    c.ndr_store(key, {"awb": body["awb"], "state": final, "reason": reason, "response": response, "ref": ref})
    if state == "timeout":
        from fastapi import HTTPException
        raise HTTPException(504, "gateway timeout")  # applied at the carrier, but the caller never hears back
    return response


@router.get("/api/v1/ndr/actions/{client_request_id}")
async def ndr_action_status(client_request_id: str):
    rec = c.ndr_lookup(client_request_id)
    if rec is None:
        from fastapi import HTTPException
        raise HTTPException(404, "unknown request")
    status = {"accepted": "ACCEPTED", "rejected": "REJECTED", "pending": "PENDING"}[rec["state"]]
    return {"success": rec["state"] != "rejected", "request_id": rec["ref"], "status": status, "error": rec.get("reason")}
