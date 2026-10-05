from psycopg.types.json import Jsonb

from .. import db, transitions
from ..logs import log, request_id_var
from ..carriers.base import CarrierError
from ..carriers.registry import BY_CODE, BY_SLUG
from ..util import ApiError
from .orders import get_order

VALID_REASONS = {"CUSTOMER_UNAVAILABLE", "CUSTOMER_REFUSED", "ADDRESS_ISSUE", "PHONE_UNREACHABLE", "COD_NOT_READY"}


def create_shipment(order_id: str) -> dict:
    with db.conn() as c:
        order = get_order(c, order_id, lock=True)  # row lock: one carrier booking per order
        if not order["selected_carrier"]:
            raise ApiError(409, "Select a carrier before creating a shipment")
        if c.execute("SELECT 1 FROM shipments WHERE order_id=%s", (order_id,)).fetchone():
            raise ApiError(409, "Shipment already exists for this order")
        adapter = BY_CODE[order["selected_carrier"]]
        try:
            res = adapter.create_shipment(order, order["selected_service"])
        except CarrierError as e:
            raise ApiError(502, f"{adapter.name} failed to create the shipment: {e.message}", code=e.code) from e
        s = c.execute(
            """INSERT INTO shipments(order_id, carrier, service, carrier_shipment_id, tracking_number)
               VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (order_id, adapter.code, order["selected_service"], res.carrier_shipment_id, res.tracking_number)).fetchone()
        c.execute(
            """INSERT INTO shipment_events(shipment_id, carrier, tracking_number, status, event_id, raw)
               VALUES (%s,%s,%s,'SHIPMENT_CREATED','created',%s)""",
            (s["id"], adapter.code, res.tracking_number, Jsonb({"source": "zippy"})))
        c.execute("UPDATE orders SET status='SHIPPED' WHERE id=%s", (order_id,))
        db.audit(c, "SHIPMENT_CREATED", "shipment", str(s["id"]),
                 {"order": order_id, "carrier": adapter.code, "tracking": res.tracking_number})
        log("SHIPMENT_CREATED", orderId=order_id, shipmentId=s["id"], carrier=adapter.code,
            trackingNumber=res.tracking_number)
        return s


def tracking(order_id: str, include_raw: bool = False) -> dict:
    with db.conn() as c:
        get_order(c, order_id)
        s = c.execute("SELECT * FROM shipments WHERE order_id=%s", (order_id,)).fetchone()
        if not s:
            raise ApiError(404, "No shipment for this order yet")
        events = c.execute(
            f"""SELECT status, reason, event_id, occurred_at{', raw, normalized' if include_raw else ''}
               FROM shipment_events WHERE shipment_id=%s ORDER BY id""", (s["id"],)).fetchall()
        return {"order_id": order_id, "carrier": s["carrier"], "service": s["service"],
                "tracking_number": s["tracking_number"], "carrier_shipment_id": s["carrier_shipment_id"],
                "shipment_id": s["id"], "current_status": s["status"], "status_history": events}


def list_shipments() -> list[dict]:
    with db.conn() as c:
        return c.execute(
            """SELECT s.*, o.customer_name FROM shipments s JOIN orders o ON o.id=s.order_id
               ORDER BY s.created_at DESC, s.id DESC LIMIT 100""").fetchall()


def _quarantine(c, carrier, tracking, reason, raw, normalized=None, detail=None):
    c.execute(
        """INSERT INTO webhook_quarantine(carrier, tracking_number, reason, detail, raw, normalized, request_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (carrier, tracking, reason, Jsonb(detail or {}), Jsonb(raw), Jsonb(normalized) if normalized else None,
         request_id_var.get()))
    log("WEBHOOK_QUARANTINED", level="warning", carrier=carrier, trackingNumber=tracking, reason=reason)


def handle_webhook(slug: str, payload: dict) -> tuple[dict, int]:
    """Carrier webhook -> normalise -> idempotent insert (raw + normalized) -> update shipment (+ NDR case).

    Returns (body, http_status). Problem events are quarantined (never silently dropped) and answered
    with 2xx so the carrier does not retry them forever; unparseable payloads get 400."""
    adapter = BY_SLUG.get(slug)
    if not adapter:
        raise ApiError(404, f"Unknown carrier {slug}")
    code = adapter.code
    try:
        ev = adapter.parse_webhook(payload)
    except (KeyError, TypeError, AttributeError) as e:
        with db.conn() as c:
            _quarantine(c, code, None, "UNPARSEABLE_PAYLOAD", payload, detail={"error": repr(e)})
        return {"status": "rejected", "reason": "UNPARSEABLE_PAYLOAD",
                "message": f"Payload is not a valid {adapter.name} webhook; stored for investigation"}, 400

    normalized = {"carrier": code, "trackingNumber": ev.tracking_number, "status": ev.status,
                  "eventId": ev.event_id, "reason": ev.reason}
    log("WEBHOOK_RECEIVED", carrier=code, trackingNumber=ev.tracking_number, status=ev.status, eventId=ev.event_id)

    with db.conn() as c:
        s = c.execute("SELECT * FROM shipments WHERE carrier=%s AND tracking_number=%s FOR UPDATE",
                      (code, ev.tracking_number)).fetchone()
        if not s:
            _quarantine(c, code, ev.tracking_number, "UNKNOWN_TRACKING_NUMBER", payload, normalized)
            db.audit(c, "WEBHOOK_QUARANTINED", "shipment", ev.tracking_number, {"reason": "UNKNOWN_TRACKING_NUMBER"})
            return {"status": "quarantined", "reason": "UNKNOWN_TRACKING_NUMBER",
                    "message": f"No shipment with tracking number {ev.tracking_number}; event stored for investigation"}, 202

        db.audit(c, "WEBHOOK_RECEIVED", "shipment", str(s["id"]), normalized)
        dup = c.execute(
            "SELECT 1 FROM shipment_events WHERE carrier=%s AND tracking_number=%s AND status=%s AND event_id=%s",
            (code, ev.tracking_number, ev.status, ev.event_id)).fetchone()
        if dup:
            log("WEBHOOK_DUPLICATE", carrier=code, shipmentId=s["id"], orderId=s["order_id"], eventId=ev.event_id)
            return {"status": "duplicate", "duplicate": True, "message": "Event already processed"}, 200

        if not transitions.is_valid(s["status"], ev.status):
            detail = {"from": s["status"], "to": ev.status,
                      "allowedFromCurrent": sorted(transitions.ALLOWED.get(s["status"], []))}
            _quarantine(c, code, ev.tracking_number, "INVALID_TRANSITION", payload, normalized, detail)
            db.audit(c, "WEBHOOK_QUARANTINED", "shipment", str(s["id"]), {"reason": "INVALID_TRANSITION", **detail})
            return {"status": "quarantined", "reason": "INVALID_TRANSITION", "currentStatus": s["status"],
                    "message": f"{s['status']} -> {ev.status} is not a valid transition; shipment unchanged",
                    **detail}, 202

        inserted = c.execute(
            """INSERT INTO shipment_events(shipment_id, carrier, tracking_number, status, event_id, reason, raw, normalized)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (carrier, tracking_number, status, event_id) DO NOTHING RETURNING id""",
            (s["id"], code, ev.tracking_number, ev.status, ev.event_id, ev.reason,
             Jsonb(payload), Jsonb(normalized))).fetchone()
        if not inserted:  # lost a race with an identical concurrent delivery
            return {"status": "duplicate", "duplicate": True, "message": "Event already processed"}, 200

        c.execute("UPDATE shipments SET status=%s, updated_at=now() WHERE id=%s", (ev.status, s["id"]))
        if ev.status == "DELIVERED":
            c.execute("UPDATE orders SET status='DELIVERED' WHERE id=%s", (s["order_id"],))
        ndr_id = None
        if ev.status == "NDR":
            reason = ev.reason if ev.reason in VALID_REASONS else "CUSTOMER_UNAVAILABLE"
            attempt = c.execute("SELECT count(*)+1 AS n FROM ndr_cases WHERE shipment_id=%s", (s["id"],)).fetchone()["n"]
            ndr_id = c.execute(
                """INSERT INTO ndr_cases(shipment_id, order_id, reason, attempt_number)
                   VALUES (%s,%s,%s,%s) RETURNING id""", (s["id"], s["order_id"], reason, attempt)).fetchone()["id"]
            db.audit(c, "NDR_CREATED", "ndr_case", ndr_id,
                     {"order": s["order_id"], "reason": reason, "attempt": attempt})
            log("NDR_CREATED", orderId=s["order_id"], shipmentId=s["id"], carrier=code, ndrCaseId=ndr_id)
        log("SHIPMENT_STATUS_UPDATED", orderId=s["order_id"], shipmentId=s["id"], carrier=code,
            fromStatus=s["status"], toStatus=ev.status)
        return {"status": "processed", "duplicate": False, "shipmentStatus": ev.status, "ndrCaseId": ndr_id}, 200


def list_quarantine(limit: int = 100) -> list[dict]:
    with db.conn() as c:
        return c.execute("SELECT * FROM webhook_quarantine ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
