from sqlalchemy import select

from app.platform.models import SimulationProfile


def for_customer(db, customer_id: str) -> dict:
    row = db.scalars(select(SimulationProfile).where(SimulationProfile.customer_id == customer_id)).first()
    return dict(row.profile) if row else {}


def for_shipment(db, shipment_id: str) -> dict:
    row = db.scalars(select(SimulationProfile).where(SimulationProfile.shipment_id == shipment_id)).first()
    return dict(row.profile) if row else {}


def consume(db, customer_id: str, key: str):
    """Pop the next scripted item for `key` (e.g. the customer's next WhatsApp reply)."""
    row = db.scalars(select(SimulationProfile).where(SimulationProfile.customer_id == customer_id)).first()
    if row is None:
        return None
    profile = dict(row.profile)
    items = list(profile.get(key) or [])
    if not items:
        return None
    item = items.pop(0)
    profile[key] = items
    row.profile = profile
    return item
