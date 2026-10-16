"""HTTP hardening: request ids, body size limits, security headers, sanitized errors."""
import logging
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.platform.logging_setup import request_id_var

log = logging.getLogger("zippy.http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id")
        if not rid or len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = "req_" + secrets.token_hex(8)
        token = request_id_var.set(rid)
        request.state.request_id = rid
        started = time.perf_counter()
        settings = get_settings()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > settings.max_request_bytes:
                return JSONResponse({"detail": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large"}},
                                    status_code=413, headers={"X-Request-Id": rid})
            try:
                response: Response = await call_next(request)
            except Exception:  # noqa: BLE001 - never leak stack traces or internals to clients
                log.exception("unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse({"detail": {"code": "INTERNAL_ERROR", "message": "Something went wrong",
                                                    "requestId": rid}}, status_code=500)
            elapsed = int((time.perf_counter() - started) * 1000)
            response.headers["X-Request-Id"] = rid
            response.headers["Server-Timing"] = f"app;dur={elapsed}"
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
            if settings.session_cookie_secure:
                response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
            if request.url.path.startswith("/api/v1"):
                response.headers.setdefault("Cache-Control", "no-store")
            if elapsed > 1000:
                log.warning("slow request %s %s %sms", request.method, request.url.path, elapsed)
            return response
        finally:
            request_id_var.reset(token)
