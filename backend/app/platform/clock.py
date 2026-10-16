"""Single source of "now" for the platform.

Production code calls `now()`. The demo scenario runner and tests swap in a controllable clock so that
multi-day workflows (follow-ups, SLA deadlines, carrier reattempts) run through the real code paths.
"""
from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock(Clock):
    def __init__(self, start: datetime):
        self._now = start if start.tzinfo else start.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def advance(self, **kwargs) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now


_clock: Clock = Clock()


def now() -> datetime:
    return _clock.now()


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def reset_clock() -> None:
    set_clock(Clock())


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything stored is UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
