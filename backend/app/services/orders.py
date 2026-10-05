import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.errors import DomainError, not_found
from app.models import Order


def create_order(db: Session, data: dict) -> Order:
    """`data` holds already-validated order fields (snake_case)."""
    data = dict(data)
    order_id = str(uuid.uuid4())
    data.setdefault("merchant_id", get_settings().default_merchant_id)
    for key, default in (("length_cm", 20), ("width_cm", 15), ("height_cm", 10), ("cod_amount", 0)):
        data.setdefault(key, default)  # same defaults the REST schema applies
    data["merchant_order_id"] = data.get("merchant_order_id") or f"ORD-{order_id[:8]}"
    order = Order(id=order_id, **data)
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError("DUPLICATE_ORDER", "merchant_order_id already exists for this merchant", 409)
    return order


def get_order(db: Session, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise not_found("Order")
    return order


def list_orders(db: Session, limit: int = 100) -> list[Order]:
    return list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(limit)))
