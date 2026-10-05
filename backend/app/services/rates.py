import json
from concurrent.futures import ThreadPoolExecutor

import redis

from .. import config, db
from ..carriers.registry import ADAPTERS, BY_CODE
from ..util import ApiError
from .orders import get_order

_redis = redis.Redis.from_url(config.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def cache_key(order_id: str) -> str:
    return f"rates:{order_id}"


def _cache_get(order_id):
    try:
        raw = _redis.get(cache_key(order_id))
        return json.loads(raw) if raw else None
    except redis.RedisError:
        return None  # cache is best-effort


def _cache_set(order_id, rates):
    try:
        _redis.set(cache_key(order_id), json.dumps(rates), ex=config.RATE_CACHE_TTL)
    except redis.RedisError:
        pass


def _cache_drop(order_id):
    try:
        _redis.delete(cache_key(order_id))
    except redis.RedisError:
        pass


def _call(adapter, order):
    try:
        return adapter.code, [r.model_dump() for r in adapter.get_rates(order)], None
    except Exception as e:  # noqa: BLE001 - one carrier failing must not fail the request
        return adapter.code, [], f"{type(e).__name__}: {e}"


def get_rates(order_id: str, refresh: bool = False) -> dict:
    with db.conn() as c:
        order = get_order(c, order_id)
        if not refresh:
            cached = _cache_get(order_id)
            has_quotes = c.execute("SELECT 1 FROM shipping_quotes WHERE order_id=%s LIMIT 1", (order_id,)).fetchone()
            if cached and has_quotes:
                return {"rates": cached, "cached": True, "errors": []}

    with ThreadPoolExecutor(max_workers=len(ADAPTERS)) as ex:
        results = list(ex.map(lambda a: _call(a, order), ADAPTERS))

    rates = [r for _, rs, _ in results for r in rs]
    errors = [{"carrier": code, "error": err} for code, _, err in results if err]
    if not rates:
        raise ApiError(502, "No carrier returned a rate", errors=errors)

    with db.conn() as c:
        get_order(c, order_id, lock=True)  # serialise concurrent refreshes (e.g. double-submit)
        c.execute("DELETE FROM shipping_quotes WHERE order_id=%s", (order_id,))
        for r in rates:
            c.execute(
                """INSERT INTO shipping_quotes(order_id, carrier, service, service_name, price,
                       eta_min_days, eta_max_days) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (order_id, r["carrier"], r["service"], r["serviceName"], r["price"],
                 r["etaMinDays"], r["etaMaxDays"]))
        db.audit(c, "RATES_FETCHED", "order", order_id,
                 {"carriers": sorted({r["carrier"] for r in rates}), "errors": errors, "refresh": refresh})
    # Only cache complete results so a carrier that was briefly down is retried on the next request.
    if not errors:
        _cache_set(order_id, rates)
    else:
        _cache_drop(order_id)  # never leave a stale full result behind a partial refresh
    return {"rates": rates, "cached": False, "errors": errors}


def select_carrier(order_id: str, carrier: str, service: str) -> dict:
    if carrier not in BY_CODE:
        raise ApiError(400, f"Unknown carrier {carrier}")
    with db.conn() as c:
        order = get_order(c, order_id, lock=True)
        if c.execute("SELECT 1 FROM shipments WHERE order_id=%s", (order_id,)).fetchone():
            raise ApiError(409, "A shipment already exists for this order")
        q = c.execute("SELECT * FROM shipping_quotes WHERE order_id=%s AND carrier=%s AND service=%s",
                      (order_id, carrier, service)).fetchone()
        if not q:
            raise ApiError(400, f"No stored quote for {carrier}/{service}; fetch rates first")
        row = c.execute(
            """UPDATE orders SET selected_carrier=%s, selected_service=%s, quoted_price=%s,
                   status='CARRIER_SELECTED' WHERE id=%s RETURNING *""",
            (carrier, service, q["price"], order_id)).fetchone()
        db.audit(c, "CARRIER_SELECTED", "order", order_id, {"carrier": carrier, "service": service, "price": q["price"]})
        return row
