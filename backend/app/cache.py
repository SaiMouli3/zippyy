"""Redis access. Cache problems must never break the main flow, so callers use the safe helpers."""
import json
import logging

import redis.asyncio as redis

from app.config import get_settings

log = logging.getLogger("zippy.cache")
_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def set_redis(client) -> None:
    """Used by tests to inject fakeredis."""
    global _client
    _client = client


async def cache_get_json(key: str):
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        log.warning("cache get failed for %s: %s", key, exc)
        return None


async def cache_set_json(key: str, value, ttl_seconds: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as exc:
        log.warning("cache set failed for %s: %s", key, exc)
