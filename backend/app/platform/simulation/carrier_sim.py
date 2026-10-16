"""Carrier simulator: after Zippyy ingests an event or a carrier accepts an instruction, emit the carrier's later
scans (out for delivery, delivered/failed/RTO) as signed carrier webhooks — the same path real carriers use."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.platform import clock, jobs
from app.platform.simulation import profiles

ADAPTER_MODULES = {"FASTSHIP": ("fastship", "fastship"), "QUICKEXPRESS": ("quickexpress", "quickexpress"),
                   "RELIABLE": ("reliablecourier", "reliable")}


def schedule_scan(db, shipment, status: str, at: datetime, reason: str | None = None, duplicate: bool = False) -> None:
    jobs.enqueue(db, "sim_carrier_event", {"shipment_id": shipment.id, "status": status, "reason": reason,
                                           "duplicate": duplicate},
                 merchant_id=shipment.merchant_id, run_at=at)


def handle_event(db, job) -> None:
    import importlib
    from app.mock_carriers import common as c
    from app.platform.ingest import ingest_webhook
    from app.platform.ids import new_id
    from app.platform.models import Shipment

    p = job.payload
    shipment = db.get(Shipment, p["shipment_id"])
    module_name, slug = ADAPTER_MODULES[shipment.carrier_code]
    module = importlib.import_module(f"app.mock_carriers.{module_name}")
    mock = c.MockShipment(carrier=module.SLUG, carrier_shipment_id=shipment.carrier_shipment_id or shipment.id,
                          tracking_number=shipment.tracking_number, reference=shipment.order_id, status=p["status"])
    payload = module.build_webhook(mock, p["status"], f"{shipment.tracking_number}-{new_id()[-12:]}", clock.now(), p.get("reason"))
    raw, headers = c.sign_webhook(slug, payload)
    for _ in range(2 if p.get("duplicate") else 1):
        ingest_webhook(db, f"carrier:{slug}", headers, raw, {})


def on_outbox(db, event) -> None:
    """Consume carrier-related outbox events for demo merchants and play the carrier's next moves."""
    from app.platform.models import CarrierAction, Merchant, Shipment
    if event.event_type != "carrier_action.accepted":
        return
    merchant = db.get(Merchant, event.merchant_id)
    if merchant is None or not merchant.is_demo:
        return
    action = db.get(CarrierAction, event.aggregate_id)
    shipment = db.get(Shipment, action.shipment_id)
    prof = profiles.for_shipment(db, shipment.id)
    # A real carrier abandons the original slot once it accepts a new one: drop the superseded planned scans.
    from app.platform.models import Job
    for job in db.scalars(select(Job).where(Job.kind == "sim_carrier_event", Job.status == "queued",
                                            Job.merchant_id == shipment.merchant_id)):
        if job.payload.get("shipment_id") == shipment.id and job.payload.get("status") not in ("RTO", "RTO_DELIVERED"):
            job.status = "cancelled"
            job.finished_at = clock.now()
    tz = ZoneInfo(merchant.timezone)
    day = action.requested_date or (clock.now().astimezone(tz).date() + timedelta(days=1))
    ofd = datetime.combine(day, time(9, 30), tz).astimezone(ZoneInfo("UTC"))
    if ofd < clock.now():
        ofd = clock.now() + timedelta(minutes=30)
    if shipment.current_status != "OUT_FOR_DELIVERY":
        schedule_scan(db, shipment, "OUT_FOR_DELIVERY", ofd)
    elif action.requested_window:  # already on the van: the driver comes back in the agreed slot
        start_hour = int(action.requested_window[:2])
        ofd = datetime.combine(day, time(max(9, start_hour - 5), 0), tz).astimezone(ZoneInfo("UTC"))
    nxt = prof.get("after_reattempt", "DELIVERED")
    reason = prof.get("after_reattempt_reason")
    schedule_scan(db, shipment, nxt, ofd + timedelta(hours=5), reason)
    if nxt == "RTO":
        schedule_scan(db, shipment, "RTO_DELIVERED", ofd + timedelta(days=3))
