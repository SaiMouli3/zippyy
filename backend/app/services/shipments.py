from psycopg.types.json import Jsonb

from .. import db
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
        except Exception as e:  # noqa: BLE001
            raise ApiError(502, f"{adapter.name} failed to create the shipment: {e}") from e
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
        return s


def tracking(order_id: str) -> dict:
    with db.conn() as c:
        get_order(c, order_id)
        s = c.execute("SELECT * FROM shipments WHERE order_id=%s", (order_id,)).fetchone()
        if not s:
            raise ApiError(404, "No shipment for this order yet")
        events = c.execute(
            """SELECT status, reason, event_id, occurred_at FROM shipment_events
               WHERE shipment_id=%s ORDER BY id""", (s["id"],)).fetchall()
        return {"order_id": order_id, "carrier": s["carrier"], "service": s["service"],
                "tracking_number": s["tracking_number"], "carrier_shipment_id": s["carrier_shipment_id"],
                "current_status": s["status"], "status_history": events}


def list_shipments() -> list[dict]:
    with db.conn() as c:
        return c.execute(
            """SELECT s.*, o.customer_name FROM shipments s JOIN orders o ON o.id=s.order_id
               ORDER BY s.created_at DESC, s.id DESC LIMIT 100""").fetchall()


def handle_webhook(slug: str, payload: dict) -> dict:
    """Carrier webhook -> normalise -> idempotent event insert -> update shipment (+ NDR case)."""
    adapter = BY_SLUG.get(slug)
    if not adapter:
        raise ApiError(404, f"Unknown carrier {slug}")
    try:
        ev = adapter.parse_webhook(payload)
    except (KeyError, TypeError) as e:
        raise ApiError(400, f"Unparseable {adapter.name} webhook: {e!r}") from e

    with db.conn() as c:
        db.audit(c, "WEBHOOK_RECEIVED", "shipment", ev.tracking_number,
                 {"carrier": adapter.code, "status": ev.status, "eventId": ev.event_id})
        s = c.execute("SELECT * FROM shipments WHERE carrier=%s AND tracking_number=%s FOR UPDATE",
                      (adapter.code, ev.tracking_number)).fetchone()
        if not s:
            raise ApiError(404, f"Unknown tracking number {ev.tracking_number}")
        inserted = c.execute(
            """INSERT INTO shipment_events(shipment_id, carrier, tracking_number, status, event_id, reason, raw)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (carrier, tracking_number, status, event_id) DO NOTHING RETURNING id""",
            (s["id"], adapter.code, ev.tracking_number, ev.status, ev.event_id, ev.reason, Jsonb(payload))).fetchone()
        if not inserted:
            return {"status": "duplicate", "duplicate": True}

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
        return {"status": "processed", "duplicate": False, "shipmentStatus": ev.status, "ndrCaseId": ndr_id}
