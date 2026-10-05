from .. import db


def summary() -> dict:
    with db.conn() as c:
        one = lambda q: c.execute(q).fetchone()["n"]  # noqa: E731
        return {
            "totals": {
                "orders": one("SELECT count(*) n FROM orders"),
                "shipments": one("SELECT count(*) n FROM shipments"),
                "in_transit": one("SELECT count(*) n FROM shipments WHERE status IN ('PICKED_UP','IN_TRANSIT','OUT_FOR_DELIVERY')"),
                "delivered": one("SELECT count(*) n FROM shipments WHERE status='DELIVERED'"),
                "ndr_cases": one("SELECT count(*) n FROM ndr_cases"),
            },
            "recent_shipments": c.execute(
                """SELECT s.*, o.customer_name FROM shipments s JOIN orders o ON o.id=s.order_id
                   ORDER BY s.updated_at DESC, s.id DESC LIMIT 5""").fetchall(),
            "recent_ndr": c.execute(
                """SELECT n.id, n.order_id, n.reason, n.attempt_number, n.status, o.customer_name, s.carrier
                   FROM ndr_cases n JOIN orders o ON o.id=n.order_id JOIN shipments s ON s.id=n.shipment_id
                   ORDER BY n.created_at DESC, n.id DESC LIMIT 5""").fetchall(),
        }
