"""Rate aggregation with Redis caching.

Cache strategy (see docs/assumptions.md):
  * key  = zippy:rates:{merchantId}:{pickup}:{delivery}:{grams}:{L}:{W}:{H}:{paymentType}:{codAmount}
    so ANY pricing input change produces a different key (and different orders with identical
    inputs share a quote).
  * complete results (every carrier answered) -> RATE_CACHE_TTL (default 300s)
  * partial results (>=1 carrier failed)      -> PARTIAL_RATE_CACHE_TTL (default 60s), failures included
  * Redis down -> never fails the request; carriers are called directly and the failure is logged.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, wait
import contextvars

import redis

from .. import config, db
from ..carriers.base import CarrierError
from ..carriers.registry import ADAPTERS, BY_CODE
from ..logs import log
from ..util import ApiError
from .orders import get_order

_redis = redis.Redis.from_url(config.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def _fmt_amount(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def cache_key(order: dict) -> str:
    return ":".join(["zippy:rates", order["merchant_id"], order["pickup_pincode"], order["delivery_pincode"],
                     str(order["weight_grams"]), str(order["length_cm"]), str(order["width_cm"]),
                     str(order["height_cm"]), order["payment_mode"], _fmt_amount(order["cod_amount"])])


def _cache_get(key: str, order_id: str):
    """-> (status, value) with status HIT | MISS | UNAVAILABLE."""
    try:
        raw = _redis.get(key)
    except redis.RedisError as e:
        log("CACHE_UNAVAILABLE", level="warning", orderId=order_id, operation="GET", error=type(e).__name__)
        return "UNAVAILABLE", None
    if raw is None:
        log("CACHE_MISS", orderId=order_id, key=key)
        return "MISS", None
    log("CACHE_HIT", orderId=order_id, key=key)
    return "HIT", json.loads(raw)


def _cache_set(key: str, order_id: str, value: dict, ttl: int) -> bool:
    try:
        _redis.set(key, json.dumps(value), ex=ttl)
        return True
    except redis.RedisError as e:
        log("CACHE_UNAVAILABLE", level="warning", orderId=order_id, operation="SET", error=type(e).__name__)
        return False


def _drop(key: str):
    try:
        _redis.delete(key)
    except redis.RedisError:
        pass


def _fetch_all(order: dict) -> tuple[list[dict], list[dict]]:
    """Call every carrier concurrently, bounded by CARRIER_TIMEOUT_MS. Never raises for a carrier failure."""
    deadline = config.CARRIER_TIMEOUT_MS / 1000 + 1.0  # hard stop on top of the per-request httpx timeout
    ex = ThreadPoolExecutor(max_workers=len(ADAPTERS))
    start = time.perf_counter()
    futures = {}
    for a in ADAPTERS:
        ctx = contextvars.copy_context()  # keep requestId in logs from worker threads
        futures[ex.submit(ctx.run, a.get_rates, order)] = a
    done, pending = wait(futures, timeout=deadline)
    ex.shutdown(wait=False, cancel_futures=True)  # don't block on a hung carrier
    rates, errors = [], []
    for f, a in futures.items():
        if f in pending:
            errors.append({"carrier": a.code, "code": "TIMEOUT", "message": f"{a.name} exceeded the deadline",
                           "durationMs": round((time.perf_counter() - start) * 1000, 1)})
            continue
        try:
            rates += [r.model_dump() for r in f.result()]
        except CarrierError as e:
            errors.append({"carrier": a.code, "code": e.code, "message": e.message, "durationMs": e.duration_ms})
        except Exception as e:  # noqa: BLE001 - e.g. malformed carrier payload
            errors.append({"carrier": a.code, "code": "BAD_RESPONSE", "message": f"{type(e).__name__}: {e}",
                           "durationMs": round((time.perf_counter() - start) * 1000, 1)})
    return rates, errors


def _store_quotes(order_id: str, rates: list[dict]):
    """Persist the quotes the order may later select from. Frozen once a shipment exists."""
    with db.conn() as c:
        get_order(c, order_id, lock=True)  # serialise concurrent refreshes (double-submit)
        if c.execute("SELECT 1 FROM shipments WHERE order_id=%s", (order_id,)).fetchone():
            return
        c.execute("DELETE FROM shipping_quotes WHERE order_id=%s", (order_id,))
        for r in rates:
            c.execute(
                """INSERT INTO shipping_quotes(order_id, carrier, service, service_name, price,
                       eta_min_days, eta_max_days) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (order_id, r["carrier"], r["service"], r["serviceName"], r["price"],
                 r["etaMinDays"], r["etaMaxDays"]))


def get_rates(order_id: str, refresh: bool = False) -> dict:
    with db.conn() as c:
        order = get_order(c, order_id)
    key = cache_key(order)
    log("RATE_REQUEST", orderId=order_id, refresh=refresh, key=key)

    cache_status = "REFRESH" if refresh else None
    if not refresh:
        cache_status, hit = _cache_get(key, order_id)
        if hit:
            _store_quotes(order_id, hit["rates"])
            return {"rates": hit["rates"], "errors": hit["errors"], "partial": bool(hit["errors"]),
                    "cached": True, "cacheStatus": "HIT", "cacheKey": key}

    rates, errors = _fetch_all(order)
    if not rates:
        log("RATE_REQUEST_FAILED", level="error", orderId=order_id, errors=errors)
        raise ApiError(502, "No carrier returned a rate", errors=errors)

    _store_quotes(order_id, rates)
    with db.conn() as c:
        db.audit(c, "RATES_FETCHED", "order", order_id,
                 {"carriers": sorted({r["carrier"] for r in rates}), "errors": errors, "refresh": refresh})
    partial = bool(errors)
    ttl = config.PARTIAL_RATE_CACHE_TTL if partial else config.RATE_CACHE_TTL
    stored = _cache_set(key, order_id, {"rates": rates, "errors": errors}, ttl)
    if not stored:
        cache_status = "UNAVAILABLE"
    log("RATES_FETCHED", orderId=order_id, carriers=sorted({r["carrier"] for r in rates}), partial=partial,
        cacheTtl=ttl if stored else None, failed=[e["carrier"] for e in errors] or None)
    return {"rates": rates, "errors": errors, "partial": partial, "cached": False,
            "cacheStatus": cache_status or "MISS", "cacheKey": key}


def select_carrier(order_id: str, carrier: str, service: str, price: float | None = None) -> dict:
    if carrier not in BY_CODE:
        raise ApiError(400, f"Unknown carrier {carrier}")
    with db.conn() as c:
        get_order(c, order_id, lock=True)
        if c.execute("SELECT 1 FROM shipments WHERE order_id=%s", (order_id,)).fetchone():
            raise ApiError(409, "A shipment already exists for this order")
        q = c.execute("SELECT * FROM shipping_quotes WHERE order_id=%s AND carrier=%s AND service=%s",
                      (order_id, carrier, service)).fetchone()
        if not q:
            raise ApiError(400, f"No stored quote for {carrier}/{service}; fetch rates first")
        # The price always comes from the server-side quote. A client may echo it, but never change it.
        if price is not None and round(price, 2) != round(q["price"], 2):
            raise ApiError(409, "Quoted amount cannot be modified", quotedPrice=q["price"], submittedPrice=price)
        row = c.execute(
            """UPDATE orders SET selected_carrier=%s, selected_service=%s, quoted_price=%s,
                   status='CARRIER_SELECTED' WHERE id=%s RETURNING *""",
            (carrier, service, q["price"], order_id)).fetchone()
        db.audit(c, "CARRIER_SELECTED", "order", order_id, {"carrier": carrier, "service": service, "price": q["price"]})
        log("CARRIER_SELECTED", orderId=order_id, carrier=carrier, service=service)
        return row
