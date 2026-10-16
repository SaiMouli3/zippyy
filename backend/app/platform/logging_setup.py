"""Structured JSON logs with request/correlation ids and PII redaction (phone numbers, emails, bearer tokens)."""
import json
import logging
import re
import sys
from contextvars import ContextVar

from app.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_PATTERNS = [
    (re.compile(r"\+?91[\s-]?\d{5}[\s-]?\d{5}|\b[6-9]\d{9}\b"), "[phone]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._-]+"), "Bearer [token]"),
    (re.compile(r"zpy_(live|test)_[A-Za-z0-9]+"), "zpy_[key]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))[-4000:]
        return json.dumps(out, ensure_ascii=False)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging() -> None:
    s = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if s.log_json else RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(s.log_level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
