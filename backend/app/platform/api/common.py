"""Helpers shared by the v1 routers."""
import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import Query

from app.platform import clock


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return clock.as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def time_range(range_: str | None, start: datetime | None = None, end: datetime | None = None) -> tuple[datetime, datetime]:
    now = clock.now()
    if start and end:
        return clock.as_utc(start), clock.as_utc(end)
    days = {"24h": 1, "7d": 7, "14d": 14, "30d": 30, "90d": 90}.get(range_ or "7d", 7)
    return now - timedelta(days=days), now


class Page:
    def __init__(self, page: int = Query(1, ge=1, le=10_000), page_size: int = Query(50, ge=1, le=200, alias="pageSize")):
        self.page = page
        self.size = page_size
        self.offset = (page - 1) * page_size


def page_response(items: list, total: int, page: Page) -> dict:
    return {"items": items, "total": total, "page": page.page, "pageSize": page.size,
            "generatedAt": clock.now().isoformat()}


def csv_text(rows: list[dict]) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        # Neutralise spreadsheet formula injection.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in r.items()})
    return buf.getvalue()


UTC = timezone.utc
