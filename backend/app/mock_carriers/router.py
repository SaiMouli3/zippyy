"""Three mock carriers with deliberately different API contracts.

They live inside the API process for the MVP but are only ever reached over HTTP
(by the carrier adapters), exactly as a real carrier would be.
"""
import asyncio
import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import config

router = APIRouter()

# Per-carrier fault injection (flip via /mock/_control/failures to demo failures and timeouts).
STATE: dict[str, dict] = {s: {"fail": False, "delayMs": 0} for s in ("fastship", "quickexpress", "reliable")}


async def _gate(slug: str):
    """Simulated latency, then simulated outage."""
    if STATE[slug]["delayMs"]:
        await asyncio.sleep(STATE[slug]["delayMs"] / 1000)
    if STATE[slug]["fail"]:
        raise HTTPException(503, f"{slug} is down (simulated)")


def _chargeable_kg(grams: float, l: float, w: float, h: float, divisor: float) -> float:
    """Carriers bill the greater of actual and volumetric weight (each uses its own divisor)."""
    # A shipment is charged by the larger of: actual weight and box-volume weight.
    # This simulates real courier billing, where bulky but light packages still cost more.
    return max(grams / 1000, l * w * h / divisor)


def _zone_factor(origin: str, dest: str) -> float:
    # Distance affects price. If the pickup and delivery pincode are far apart, the final price is higher.
    gap = abs(int(origin[0]) - int(dest[0]))
    return 1.0 + 0.05 * max(0, gap - 4) + (0.0 if gap > 0 else -0.1)


def _digits(n: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))


class FaultToggle(BaseModel):
    carrier: str
    fail: bool | None = None
    delayMs: int | None = None


@router.post("/mock/_control/failures", tags=["Mock carriers"], summary="Inject carrier outage / latency")
async def set_failure(body: FaultToggle):
    """Make a mock carrier return 503 (`fail`) and/or respond after `delayMs` (use > CARRIER_TIMEOUT_MS to simulate a timeout)."""
    if body.carrier not in STATE:
        raise HTTPException(404, "unknown carrier")
    if body.fail is not None:
        STATE[body.carrier]["fail"] = body.fail
    if body.delayMs is not None:
        STATE[body.carrier]["delayMs"] = body.delayMs
    return STATE


@router.get("/mock/_control/failures", tags=["Mock carriers"], summary="Current fault-injection state")
async def get_failures():
    return STATE


# ---------------------------------------------------------------- FastShip ---
# JSON, camelCase, flat single-service response.
@router.post("/mock/fastship/rates")
async def fastship_rates(req: Request):
    # FastShip pricing: base charge + weight charge + distance multiplier.
    await _gate("fastship")
    b = await req.json()
    d = b["dimensions"]
    kg = _chargeable_kg(b["weightGrams"], d["lengthCm"], d["widthCm"], d["heightCm"], 5000)
    price = (119.9 + 42.0 * kg) * _zone_factor(b["origin"], b["destination"])
    return {"service": "FAST-AIR", "price": round(price, 2), "etaDays": 2}


@router.post("/mock/fastship/shipments")
async def fastship_create(req: Request):
    await _gate("fastship")
    b = await req.json()
    if not b.get("orderRef"):
        raise HTTPException(422, "orderRef required")
    return {"shipmentId": f"FS-{_digits(6)}", "awb": f"FST{_digits(9)}", "status": "CREATED"}


@router.post("/mock/fastship/ndr-action")
async def fastship_ndr(req: Request):
    await _gate("fastship")
    b = await req.json()
    if b.get("attempt", 1) >= 3:
        return {"status": "REJECTED", "message": "Max attempts reached"}
    return {"status": "ACCEPTED", "message": "Reattempt scheduled"}


# ------------------------------------------------------------ QuickExpress ---
# snake_case, grams, nested booking envelope.
@router.post("/mock/quickexpress/rates")
async def quick_rates(req: Request):
    # QuickExpress uses a slightly higher base price and a different volumetric divisor.
    await _gate("quickexpress")
    b = await req.json()
    d = b["dimensions_cm"]
    kg = _chargeable_kg(b["weight_grams"], d["l"], d["w"], d["h"], 4000)
    price = (134.06 + 42.0 * kg) * _zone_factor(b["from_pin"], b["to_pin"])
    return {"product": "EXPRESS", "payable": round(price, 2), "deliveryEstimate": 3}


@router.post("/mock/quickexpress/bookings")
async def quick_create(req: Request):
    await _gate("quickexpress")
    b = await req.json()
    if not b.get("reference"):
        raise HTTPException(422, "reference required")
    return {"booking": {"id": f"QX-{_digits(6)}", "tracking": f"QXP{_digits(10)}"}, "ok": True}


@router.post("/mock/quickexpress/ndr/{tracking}/reattempt")
async def quick_ndr(tracking: str, req: Request):
    await _gate("quickexpress")
    b = await req.json()
    if b.get("attempt", 1) >= 3:
        return {"result": "DECLINED", "note": "Max attempts reached"}
    return {"result": "OK", "note": "Reattempt scheduled"}


# --------------------------------------------------------- ReliableCourier ---
# GET with query params, list of options, different field names again.
@router.get("/mock/reliable/rates")
async def reliable_rates(pickup: str, drop: str, wt: float, l: int, b: int, h: int):
    # Reliable is the cheapest mock carrier and uses a different volumetric divisor.
    await _gate("reliable")
    kg = _chargeable_kg(wt * 1000, l, b, h, 6000)
    price = (99.30 + 40.0 * kg) * _zone_factor(pickup, drop)
    return {"options": [{"code": "RC-SURFACE", "amount": round(price, 2), "days": 5}]}


@router.post("/mock/reliable/consignments")
async def reliable_create(req: Request):
    await _gate("reliable")
    b = await req.json()
    if not b.get("customerRef"):
        raise HTTPException(422, "customerRef required")
    return {"consignmentNo": f"RC-{_digits(6)}", "trackingRef": f"RLC{_digits(9)}"}


@router.post("/mock/reliable/consignments/{ref}/redeliver")
async def reliable_ndr(ref: str, req: Request):
    await _gate("reliable")
    b = await req.json()
    if b.get("attemptNo", 1) >= 3:
        return {"accepted": False, "msg": "Max attempts reached"}
    return {"accepted": True, "msg": "Reattempt scheduled"}


# ----------------------------------------------------------- event control ---
# Zippy-internal status -> that carrier's own vocabulary + payload shape.
FS_STATUS = {"PICKED_UP": "PKD", "IN_TRANSIT": "INT", "OUT_FOR_DELIVERY": "OFD",
             "DELIVERED": "DLV", "NDR": "NDR"}
FS_REASON = {"CUSTOMER_UNAVAILABLE": "CUST_NA", "CUSTOMER_REFUSED": "CUST_REF",
             "ADDRESS_ISSUE": "ADDR_BAD", "PHONE_UNREACHABLE": "PHONE_NR", "COD_NOT_READY": "COD_NR"}
QX_STATUS = {"PICKED_UP": "PICKUP_DONE", "IN_TRANSIT": "IN_TRANSIT", "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
             "DELIVERED": "DELIVERED", "NDR": "DELIVERY_FAILED"}
QX_REASON = {"CUSTOMER_UNAVAILABLE": "RECIPIENT_NOT_AVAILABLE", "CUSTOMER_REFUSED": "RECIPIENT_REFUSED",
             "ADDRESS_ISSUE": "BAD_ADDRESS", "PHONE_UNREACHABLE": "PHONE_NOT_REACHABLE",
             "COD_NOT_READY": "CASH_NOT_READY"}
RC_STATUS = {"PICKED_UP": "Picked Up", "IN_TRANSIT": "In Transit", "OUT_FOR_DELIVERY": "Out For Delivery",
             "DELIVERED": "Delivered", "NDR": "Undelivered"}
RC_REASON = {"CUSTOMER_UNAVAILABLE": "U01", "CUSTOMER_REFUSED": "U02", "ADDRESS_ISSUE": "U03",
             "PHONE_UNREACHABLE": "U04", "COD_NOT_READY": "U05"}


class EventRequest(BaseModel):
    status: str
    reason: str | None = None
    eventId: str | None = None  # supply the same id twice to simulate a duplicate webhook


def build_webhook(slug: str, tracking: str, status: str, reason: str | None, event_id: str) -> dict:
    if status not in FS_STATUS:
        raise HTTPException(422, f"unknown status {status}")
    reason = reason or "CUSTOMER_UNAVAILABLE"
    if slug == "fastship":
        p = {"trackingNumber": tracking, "status": FS_STATUS[status], "eventId": event_id}
        if status == "NDR":
            p["reasonCode"] = FS_REASON[reason]
        return p
    if slug == "quickexpress":
        ev = {"code": QX_STATUS[status]}
        if status == "NDR":
            ev["reason"] = QX_REASON[reason]
        return {"awb": tracking, "id": event_id, "event": ev,
                "ts": datetime.now(timezone.utc).isoformat()}
    if slug == "reliable":
        p = {"reference": tracking, "seq": event_id, "state": RC_STATUS[status]}
        if status == "NDR":
            p["undeliveredCode"] = RC_REASON[reason]
        return p
    raise HTTPException(404, "unknown carrier")


@router.post("/api/mock/{slug}/{tracking}/event", tags=["Mock carriers"], summary="Mock carrier control: emit a carrier webhook")
async def send_event(slug: str, tracking: str, body: EventRequest):
    """Mock carrier control: the carrier pushes a webhook to Zippy over HTTP."""
    event_id = body.eventId or uuid.uuid4().hex[:12]
    payload = build_webhook(slug, tracking, body.status, body.reason, event_id)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{config.WEBHOOK_BASE_URL}/api/webhooks/{slug}", json=payload)
    return {"sent": payload, "webhookStatus": r.status_code, "webhookResponse": r.json()}
