"""Structured JSON logging. Every line carries requestId (from X-Request-ID or generated)
plus whatever of orderId / shipmentId / carrier / event the caller supplies."""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from . import config

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("zippy")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
                "level": record.levelname, "requestId": request_id_var.get()}
        data.update(getattr(record, "fields", {}))
        return json.dumps({k: v for k, v in data.items() if v is not None}, default=str)


def setup_logging() -> None:
    if any(getattr(h, "_zippy", False) for h in logger.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h._zippy = True  # type: ignore[attr-defined]
    logger.addHandler(h)
    logger.setLevel(config.LOG_LEVEL)
    logger.propagate = False


def log(event: str, level: str = "info", **fields) -> None:
    fields = {"event": event, **{k: v for k, v in fields.items() if v is not None}}
    logger.log(getattr(logging, level.upper()), event, extra={"fields": fields})


class RequestIdMiddleware:
    """Pure ASGI middleware (keeps contextvars intact for sync route handlers)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode()
        rid = incoming or f"req-{uuid.uuid4().hex[:12]}"
        token = request_id_var.set(rid)
        status = {"code": 0}
        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            if path.startswith("/api") or path.startswith("/mock"):
                log("HTTP_REQUEST", method=scope["method"], path=path, status=status["code"],
                    durationMs=round((time.perf_counter() - start) * 1000, 1))
            request_id_var.reset(token)
