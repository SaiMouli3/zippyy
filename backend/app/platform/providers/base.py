import time
from dataclasses import dataclass, field
from datetime import datetime

from app.platform.models import ProviderCall


class ProviderError(Exception):
    """Provider call failed. `retryable` distinguishes throttling/5xx from bad requests."""

    def __init__(self, message: str, code: str = "provider_error", retryable: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class ProviderNotConfigured(ProviderError):
    def __init__(self, message: str):
        super().__init__(message, "not_configured", retryable=False)


class OutcomeUnknown(ProviderError):
    """The request may or may not have taken effect (timeout after send). Reconcile before resubmitting."""

    def __init__(self, message: str):
        super().__init__(message, "outcome_unknown", retryable=False)


@dataclass
class SendResult:
    provider_message_id: str
    raw_status: str = "accepted"


@dataclass
class WhatsAppStatusEvent:
    provider_message_id: str
    status: str  # sent | delivered | read | failed
    occurred_at: datetime
    provider_event_id: str
    error_code: str | None = None
    error_title: str | None = None


@dataclass
class WhatsAppInbound:
    provider_message_id: str
    from_e164: str
    text: str
    occurred_at: datetime
    message_type: str = "text"


@dataclass
class CallTurn:
    speaker: str  # agent | customer
    text: str | None  # None = silence
    text_en: str | None = None
    language: str | None = None
    language_confidence: float | None = None
    code_mixed: bool = False
    offset_seconds: float = 0
    kind: str = "turn"  # turn | silence | clarification | barge_in
    switched_from: str | None = None


@dataclass
class CallUpdate:
    provider_call_id: str
    status: str  # normalized: initiated|ringing|answered|no_answer|busy|failed|completed|cancelled|unknown
    raw_status: str
    provider_event_id: str
    occurred_at: datetime
    duration_seconds: int | None = None
    failure_reason: str | None = None
    turns: list[CallTurn] = field(default_factory=list)
    final_variables: dict = field(default_factory=dict)
    start_language: str | None = None
    final_language: str | None = None
    cost_paise: int | None = None
    recording_ref: str | None = None
    interaction_id: str | None = None


@dataclass
class Health:
    provider: str
    mode: str  # live | simulated | not_configured
    state: str  # connected | degraded | failing | not_configured | simulated
    detail: str = ""
    last_success_at: datetime | None = None
    error_rate_1h: float | None = None
    p95_latency_ms: int | None = None


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.start) * 1000)


def log_call(db, merchant_id: str | None, provider: str, operation: str, ok: bool, latency_ms: int,
             status_code: int | None = None, error_code: str | None = None) -> None:
    if db is not None:
        db.add(ProviderCall(merchant_id=merchant_id, provider=provider, operation=operation, ok=ok,
                            latency_ms=latency_ms, status_code=status_code, error_code=error_code))
