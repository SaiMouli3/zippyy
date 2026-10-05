from psycopg.types.json import Jsonb  # noqa: F401

from .. import db
from ..util import ApiError

MERCHANT_ID = "MER-DEMO"


def get_order(c, order_id: str, lock: bool = False) -> dict:
    row = c.execute(f"SELECT * FROM orders WHERE id=%s {'FOR UPDATE' if lock else ''}", (order_id,)).fetchone()
    if not row:
        raise ApiError(404, f"Order {order_id} not found")
    return row


def create_order(data: dict) -> dict:
    if data["payment_mode"] == "COD" and data["cod_amount"] <= 0:
        raise ApiError(422, "COD orders need a codAmount > 0")
    if data["payment_mode"] == "PREPAID":
        data["cod_amount"] = 0
    with db.conn() as c:
        row = c.execute(
            """INSERT INTO orders(id, merchant_id, customer_name, phone, address, pickup_pincode,
                   delivery_pincode, weight_kg, payment_mode, cod_amount)
               VALUES ('ZPY-ORD-' || nextval('order_seq'), %s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (MERCHANT_ID, data["customer_name"], data["phone"], data.get("address", ""),
             data["pickup_pincode"], data["delivery_pincode"], data["weight_kg"],
             data["payment_mode"], data["cod_amount"])).fetchone()
        db.audit(c, "ORDER_CREATED", "order", row["id"], {"customer": row["customer_name"]})
        return row


def list_orders() -> list[dict]:
    with db.conn() as c:
        return c.execute("""SELECT o.*, s.tracking_number, s.status AS shipment_status
                            FROM orders o LEFT JOIN shipments s ON s.order_id=o.id
                            ORDER BY o.created_at DESC, o.id DESC LIMIT 100""").fetchall()


def order_detail(order_id: str) -> dict:
    with db.conn() as c:
        o = get_order(c, order_id)
        o["shipment"] = c.execute("SELECT * FROM shipments WHERE order_id=%s", (order_id,)).fetchone()
        return o
