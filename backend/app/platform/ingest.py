"""Unified webhook ingestion for carriers, WhatsApp and voice providers.

1. Verify the signature for the source (bad signature -> quarantined, 401).
2. Store the raw payload in `webhook_inbox`, deduplicated on (source, dedupe_key) by a unique constraint.
3. Process it; unparseable payloads, unknown AWBs/references and illegal transitions are quarantined with a
   reason instead of being dropped.
Ingestion runs in system context (the tenant is not known until the AWB / phone / call id is matched); every
row written after matching carries the matched merchant_id.
"""
import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.carriers.registry import get_adapter_by_slug
from app.config import get_settings
from app.platform import clock
from app.platform.models import WebhookInbox, WebhookQuarantine
from app.platform.security import crypto

log = logging.getLogger("zippy.ingest")


class IngestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _quarantine(db: Session, inbox: WebhookInbox | None, source: str, reason: str, detail: str, awb: str | None = None,
                merchant_id: str | None = None) -> None:
    db.add(WebhookQuarantine(webhook_id=inbox.id if inbox else None, source=source, awb=awb, reason=reason,
                             detail=detail[:500], merchant_id=merchant_id))
    if inbox is not None:
        inbox.state = "quarantined"
        inbox.error = detail[:500]
        inbox.processed_at = clock.now()


def _verify_carrier(slug: str, headers: dict, raw: bytes) -> tuple[bool, bool]:
    """Returns (signature_ok, enforce)."""
    s = get_settings()
    secret = getattr(s, f"carrier_webhook_secret_{slug}", "")
    ok = crypto.verify_signature(raw, secret, headers.get("x-carrier-signature"))
    return ok, s.carrier_webhook_signature_required


def ingest_webhook(db: Session, source: str, headers: dict, raw: bytes, query: dict) -> dict:
    headers = {k.lower(): v for k, v in headers.items()}
    kind, _, name = source.partition(":")
    try:
        payload = json.loads(raw.decode() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except (ValueError, UnicodeDecodeError) as exc:
        _quarantine(db, None, source, "unparseable", f"invalid JSON: {exc}")
        db.commit()
        raise IngestError(422, "UNPARSEABLE", "payload is not valid JSON") from exc

    if kind == "carrier":
        ok, enforce = _verify_carrier(name, headers, raw)
    elif kind == "whatsapp":
        from app.platform.providers.whatsapp import MetaCloudWhatsApp, SimulatedWhatsApp
        provider = SimulatedWhatsApp() if name == "simulator" else MetaCloudWhatsApp()
        ok, enforce = provider.verify_signature(headers, raw), True
    elif kind == "voice":
        from app.platform.providers.voice import provider_by_name
        ok, enforce = provider_by_name(name).verify(headers, query, raw), True
    else:
        raise IngestError(404, "UNKNOWN_SOURCE", f"unknown webhook source {source}")

    if enforce and not ok:
        _quarantine(db, None, source, "bad_signature", "signature missing or invalid")
        db.commit()
        raise IngestError(401, "BAD_SIGNATURE", "invalid webhook signature")

    dedupe = _dedupe_key(kind, name, payload, raw)
    inbox = WebhookInbox(source=source, dedupe_key=dedupe, signature_ok=ok, payload=payload)
    try:
        with db.begin_nested():
            db.add(inbox)
    except IntegrityError:
        db.commit()
        return {"outcome": "duplicate", "inboxState": "duplicate", "currentStatus": _current_status(db, kind, name, payload)}

    try:
        if kind == "carrier":
            result = _process_carrier(db, inbox, name, payload)
        elif kind == "whatsapp":
            from app.platform import messaging
            result = {"outcome": "applied", **messaging.process_webhook_payload(db, name, payload)}
        else:
            from app.platform import calls
            from app.platform.providers.voice import provider_by_name
            update = provider_by_name(name).parse(payload)
            r = calls.apply_update(db, name, update)
            if r == "unknown_call":
                _quarantine(db, inbox, source, "unknown_reference", f"no call with provider id {update.provider_call_id}")
            result = {"outcome": r}
    except IngestError as exc:
        db.commit()
        raise exc
    if inbox.state == "pending":
        inbox.state = "processed"
        inbox.processed_at = clock.now()
    db.commit()
    return result


def _dedupe_key(kind: str, name: str, payload: dict, raw: bytes) -> str:
    if kind == "carrier":
        try:
            ev = get_adapter_by_slug(name).normalize_webhook(payload)
            if ev.event_id:
                return f"evt:{ev.event_id}"
        except Exception:  # noqa: BLE001 - unparseable payloads still get a content hash key
            pass
    if kind == "voice" and "attempt_id" in payload:
        return f"{payload['attempt_id']}:{payload.get('status')}"
    if kind == "voice" and "event_id" in payload:
        return str(payload["event_id"])
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _current_status(db: Session, kind: str, name: str, payload: dict) -> str | None:
    if kind != "carrier":
        return None
    try:
        ev = get_adapter_by_slug(name).normalize_webhook(payload)
    except Exception:  # noqa: BLE001
        return None
    from app.models import Shipment
    s = db.scalars(select(Shipment).where(Shipment.tracking_number == ev.tracking_number)).first()
    return s.current_status if s else None


def _process_carrier(db: Session, inbox: WebhookInbox, slug: str, payload: dict) -> dict:
    from app.services import tracking as track_svc
    adapter = get_adapter_by_slug(slug)
    try:
        event = adapter.normalize_webhook(payload)
    except (KeyError, ValueError, TypeError) as exc:
        _quarantine(db, inbox, inbox.source, "unparseable", f"unrecognised {adapter.name} payload: {exc!r}")
        raise IngestError(422, "UNPARSEABLE", f"unrecognised {adapter.name} webhook payload: {exc!r}")
    r = track_svc.ingest_event(db, event, webhook_id=inbox.id)
    if r.outcome == "unknown_awb":
        _quarantine(db, inbox, inbox.source, "unknown_awb", f"no shipment with AWB {event.tracking_number}", event.tracking_number)
        raise IngestError(404, "NOT_FOUND", "Shipment not found")
    inbox.merchant_id = r.merchant_id
    if r.outcome == "ignored":
        _quarantine(db, inbox, inbox.source, "illegal_transition", r.reason or "", event.tracking_number, r.merchant_id)
    elif r.outcome == "duplicate":
        inbox.state = "duplicate"
        inbox.processed_at = clock.now()
    return {"outcome": r.outcome, "currentStatus": r.current_status, "reason": r.reason}
