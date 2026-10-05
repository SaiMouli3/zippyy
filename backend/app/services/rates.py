"""Rate aggregation: fan out to all carriers, normalize, persist as quotes, cache in Redis."""
import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache import cache_get_json, cache_set_json
from app.carriers.registry import all_adapters
from app.config import get_settings
from app.domain.carrier_types import NormalizedRate
from app.models import Order, ShippingQuote
from app.services.orders import get_order


def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def _num(v) -> str:
    """Integer-looking numbers without the '.0' so keys stay stable."""
    d = Decimal(str(v))
    return str(int(d)) if d == d.to_integral() else str(d)


def rate_cache_key(o: Order) -> str:
    return (
        f"zippy:rates:{o.merchant_id}:{o.pickup_pincode}:{o.delivery_pincode}:{o.weight_grams}:"
        f"{o.length_cm}:{o.width_cm}:{o.height_cm}:{o.payment_type}:{_num(o.cod_amount)}"
    )


@dataclass
class RatesResult:
    order_id: str
    quotes: list[ShippingQuote]
    failed: list[dict] = field(default_factory=list)
    cached: bool = False


# ---- (de)serialising normalized rates for Redis
def _rate_to_json(r: NormalizedRate) -> dict:
    d = asdict(r)
    for k in ("base_charge", "cod_charge", "additional_charges", "tax", "total_charge"):
        d[k] = str(d[k])
    return d


def _rate_from_json(d: dict) -> NormalizedRate:
    d = dict(d)
    for k in ("base_charge", "cod_charge", "additional_charges", "tax", "total_charge"):
        d[k] = Decimal(d[k])
    return NormalizedRate(**d)


async def _call_carrier(adapter, order: Order) -> tuple[list[NormalizedRate], dict | None]:
    timeout = get_settings().carrier_rate_timeout_seconds
    try:
        rates = await asyncio.wait_for(adapter.get_rates(order), timeout=timeout + 0.5)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return [], {"carrierCode": adapter.code, "carrierName": adapter.name, "reason": f"timed out after {timeout}s"}
    except Exception as exc:  # one carrier must never take down the aggregate
        return [], {"carrierCode": adapter.code, "carrierName": adapter.name, "reason": str(exc) or type(exc).__name__}
    if not rates:
        return [], {"carrierCode": adapter.code, "carrierName": adapter.name, "reason": "no service available"}
    return rates, None


def latest_quotes(db: Session, order_id: str) -> list[ShippingQuote]:
    """Quotes of the most recent batch for this order (the only set that may be selected)."""
    newest = db.scalars(
        select(ShippingQuote).where(ShippingQuote.order_id == order_id).order_by(ShippingQuote.created_at.desc()).limit(1)
    ).first()
    if newest is None:
        return []
    rows = db.scalars(select(ShippingQuote).where(ShippingQuote.batch_id == newest.batch_id)).all()
    return sorted(rows, key=lambda q: q.total_charge)


def _persist(db: Session, order: Order, rates: list[NormalizedRate]) -> list[ShippingQuote]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=get_settings().quote_validity_seconds)
    batch = str(uuid.uuid4())
    quotes = [
        ShippingQuote(
            order_id=order.id, batch_id=batch, carrier_code=r.carrier_code, service_code=r.service_code,
            service_name=r.service_name, base_charge=r.base_charge, cod_charge=r.cod_charge,
            additional_charges=r.additional_charges, tax=r.tax, total_charge=r.total_charge,
            estimated_min_days=r.estimated_min_days, estimated_max_days=r.estimated_max_days,
            quote_reference=r.quote_reference, raw_carrier_response=r.raw, created_at=now, expires_at=expires,
        )
        for r in sorted(rates, key=lambda r: r.total_charge)
    ]
    db.add_all(quotes)
    if order.status in ("CREATED", "QUOTED"):
        order.status = "QUOTED"
    db.commit()
    return quotes


async def fetch_rates(db: Session, order_id: str, refresh: bool = False) -> RatesResult:
    order = get_order(db, order_id)
    key = rate_cache_key(order)

    if not refresh:
        hit = await cache_get_json(key)
        if hit is not None:
            current = latest_quotes(db, order.id)
            if current and as_utc(current[0].expires_at) > datetime.now(timezone.utc):
                return RatesResult(order.id, current, [], cached=True)
            return RatesResult(order.id, _persist(db, order, [_rate_from_json(r) for r in hit["rates"]]), [], cached=True)

    results = await asyncio.gather(*(_call_carrier(a, order) for a in all_adapters()))
    rates = [r for rs, _ in results for r in rs]
    failed = [f for _, f in results if f]

    quotes = _persist(db, order, rates) if rates else []
    if rates and not failed:  # never cache a partial answer: the failed carrier may recover in seconds
        await cache_set_json(key, {"rates": [_rate_to_json(r) for r in rates]}, get_settings().rate_cache_ttl_seconds)
    return RatesResult(order.id, quotes, failed, cached=False)


def stored_rates(db: Session, order_id: str) -> RatesResult:
    """GET: what we last quoted for this order (no carrier calls)."""
    get_order(db, order_id)
    quotes = latest_quotes(db, order_id)
    return RatesResult(order_id, quotes, [], cached=False)
