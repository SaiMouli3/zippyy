"""Fixed-window rate limiting in Redis (shared across API replicas), with an in-process fallback so a Redis
outage degrades to per-instance limits instead of no limits."""
import time
from collections import defaultdict
from threading import Lock

_local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
_lock = Lock()


async def hit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    bucket = int(time.time() // window_seconds)
    rkey = f"zippy:rl:{key}:{bucket}"
    try:
        from app.cache import get_redis
        r = get_redis()
        count = await r.incr(rkey)
        if count == 1:
            await r.expire(rkey, window_seconds + 5)
    except Exception:  # noqa: BLE001 - Redis down: local fallback
        with _lock:
            b, c = _local[key]
            c = c + 1 if b == bucket else 1
            _local[key] = (bucket, c)
            count = c
    if count > limit:
        return False, window_seconds - int(time.time() % window_seconds)
    return True, 0
