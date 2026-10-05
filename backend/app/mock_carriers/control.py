"""Demo controls for the mock carriers: advance a shipment, fire webhooks, toggle failures."""
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app import http
from app.mock_carriers import common as c
from app.mock_carriers import fastship, quickexpress, reliablecourier

router = APIRouter(prefix="/mock", tags=["mock-control"])

CARRIERS = {
    "fastship": (fastship, "fastship"),
    "quickexpress": (quickexpress, "quickexpress"),
    "reliablecourier": (reliablecourier, "reliable"),  # (module, Zippy webhook slug)
}
CARRIERS["reliable"] = CARRIERS["reliablecourier"]


def _carrier(name: str):
    if name not in CARRIERS:
        raise HTTPException(404, f"unknown mock carrier '{name}'")
    return CARRIERS[name]


@router.get("/shipments")
async def list_shipments():
    return [
        {
            "carrier": s.carrier,
            "trackingNumber": s.tracking_number,
            "carrierShipmentId": s.carrier_shipment_id,
            "currentStatus": s.status,
            "nextStatus": c.next_status_of(s),
        }
        for s in c.all_shipments()
    ]


@router.post("/{carrier}/shipments/{tracking_number}/next-status")
async def next_status(carrier: str, tracking_number: str, event: str | None = None, duplicate: bool = False):
    """Advance one step and push the webhook to Zippy.

    ?event=delivery_failed|rto simulates an exception from OUT_FOR_DELIVERY.
    ?duplicate=true delivers the same webhook twice (idempotency demo).
    """
    module, webhook_slug = _carrier(carrier)
    s = c.find_shipment(tracking_number)
    if s is None or s.carrier != module.SLUG:
        raise HTTPException(404, "shipment not found at this carrier")

    if event:
        new = event.upper()
        if new not in c.EXCEPTIONS:
            raise HTTPException(400, "event must be delivery_failed or rto")
    else:
        new = c.next_status_of(s)
        if new is None:
            raise HTTPException(409, f"shipment is already {s.status}; nothing next")

    s.status, s.seq = new, s.seq + 1
    s.history.append(new)
    event_id = f"{s.tracking_number}-{s.seq}"
    payload = module.build_webhook(s, new, event_id, c.utcnow())

    deliveries = []
    settings = get_settings()
    async with http.make_client(settings.zippy_public_url) as client:
        for _ in range(2 if duplicate else 1):
            try:
                resp = await client.post(f"/api/webhooks/{webhook_slug}", json=payload)
                deliveries.append({"httpStatus": resp.status_code, "body": resp.json()})
            except Exception as exc:  # carrier-side: report, don't crash
                deliveries.append({"error": str(exc)})
    return {"trackingNumber": s.tracking_number, "status": new, "webhookPayload": payload, "deliveries": deliveries}


@router.put("/{carrier}/config")
async def configure(carrier: str, failure: bool = False, delay: int = 0):
    """Persistently make a carrier fail or slow down (until reset). Query params on a single call still win."""
    module, _ = _carrier(carrier)
    return {"carrier": module.SLUG, **c.set_chaos(module.SLUG, failure, delay)}


@router.get("/config")
async def configs():
    return {name: c.get_chaos(name) for name in ("fastship", "quickexpress", "reliablecourier")}
