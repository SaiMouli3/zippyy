from .. import config, db
from ..logs import log
from ..util import ApiError

# Fields that define "the same order" for idempotent replays.
_SIGNATURE = ("customer_name", "phone", "pickup_pincode", "delivery_pincode", "weight_grams",
              "length_cm", "width_cm", "height_cm", "payment_mode", "cod_amount")


def get_order(c, order_id: str, lock: bool = False) -> dict:
    # Fetch a single order by ID. Optionally lock it for transactional updates.
    row = c.execute(f"SELECT * FROM orders WHERE id=%s {'FOR UPDATE' if lock else ''}", (order_id,)).fetchone()
    if not row:
        raise ApiError(404, f"Order {order_id} not found")
    return row


def _existing(c, merchant_id: str, merchant_order_id: str) -> dict | None:
    # Check whether this merchant already created an order with the same external order ID.
    return c.execute("SELECT * FROM orders WHERE merchant_id=%s AND merchant_order_id=%s",
                     (merchant_id, merchant_order_id)).fetchone()


def _replay(existing: dict, data: dict) -> tuple[dict, bool]:
    # This is an idempotent retry: if the same merchantOrderId is reused, we accept it only when
    # the payload matches the original order. Any mismatch is treated as a conflict.
    diff = [k for k in _SIGNATURE if existing[k] != data[k]]
    if diff:
        raise ApiError(409, f"merchantOrderId '{existing['merchant_order_id']}' was already used for order "
                            f"{existing['id']} with different details", existingOrderId=existing["id"],
                       differingFields=diff)
    log("ORDER_DUPLICATE", orderId=existing["id"], merchantId=existing["merchant_id"])
    return existing, True


def create_order(data: dict) -> tuple[dict, bool]:
    """Returns (order, duplicate). Idempotent on (merchantId, merchantOrderId)."""
    # Copy the payload so we can normalize default values without mutating the caller's object.
    data = dict(data)
    data["merchant_id"] = data.get("merchant_id") or config.DEFAULT_MERCHANT_ID
    moid = data.get("merchant_order_id")

    # COD orders require a positive collected amount; prepaid orders treat COD as zero.
    if data["payment_mode"] == "COD" and data["cod_amount"] <= 0:
        raise ApiError(422, "COD orders need a codAmount > 0")
    if data["payment_mode"] == "PREPAID":
        data["cod_amount"] = 0

    with db.conn() as c:
        # Ensure the merchant row exists before writing an order for it.
        c.execute("INSERT INTO merchants(id, name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                  (data["merchant_id"], data["merchant_id"]))

        # Reuse the original order if the same external order ID is submitted again.
        if moid and (ex := _existing(c, data["merchant_id"], moid)):
            return _replay(ex, data)

        # Insert the order and return the created row. The UPSERT avoids duplicates on the same
        # merchant/order ID under a race condition while still allowing a retry-safe replay.
        row = c.execute(
            """INSERT INTO orders(id, merchant_id, merchant_order_id, customer_name, phone, address,
                   pickup_pincode, delivery_pincode, weight_grams, length_cm, width_cm, height_cm,
                   payment_mode, cod_amount)
               VALUES ('ZPY-ORD-' || nextval('order_seq'), %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (merchant_id, merchant_order_id) WHERE merchant_order_id IS NOT NULL DO NOTHING
               RETURNING *""",
            (data["merchant_id"], moid, data["customer_name"], data["phone"], data.get("address", ""),
             data["pickup_pincode"], data["delivery_pincode"], data["weight_grams"], data["length_cm"],
             data["width_cm"], data["height_cm"], data["payment_mode"], data["cod_amount"])).fetchone()

        # If another request inserted the same row between the check and the insert, replay it.
        if row is None:  # lost a race with a concurrent identical request
            return _replay(_existing(c, data["merchant_id"], moid), data)

        db.audit(c, "ORDER_CREATED", "order", row["id"], {"customer": row["customer_name"], "merchantOrderId": moid})
        log("ORDER_CREATED", orderId=row["id"], merchantId=row["merchant_id"])
        return row, False


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
