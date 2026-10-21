"""WhatsApp providers.

`MetaCloudWhatsApp` follows the WhatsApp Business Platform Cloud API:
  POST https://graph.facebook.com/{version}/{phone_number_id}/messages   (Authorization: Bearer <token>)
  webhooks signed with X-Hub-Signature-256 = "sha256=" + HMAC-SHA256(app_secret, raw_body)
  webhook verification: GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
An HTTP 200 from the send API means *accepted*, never delivered: delivery and read states come only from
status webhooks.

`SimulatedWhatsApp` is for development, tests and demo merchants. It returns synthetic message ids and
schedules simulated provider callbacks (see app/platform/simulation), which then travel through exactly the
same signed-webhook ingestion path as real callbacks.

`OpenWAWhatsApp` talks to a self-hosted OpenWA gateway (github.com/rmyndharis/OpenWA), which drives WhatsApp Web
through unofficial clients. It has no Meta templates, so business-initiated messages go out as the already-filled
template text. Its API: POST {base}/sessions/{id}/messages/send-text with X-API-Key and Idempotency-Key headers;
webhooks are signed X-OpenWA-Signature = "sha256=" + HMAC-SHA256(secret, raw_body). Using it carries a real risk
of the WhatsApp number being restricted; see the README.
"""
import json
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.platform.ids import new_id
from app.platform.providers.base import (Health, OutcomeUnknown, ProviderError, ProviderNotConfigured, SendResult,
                                         Timer, WhatsAppInbound, WhatsAppStatusEvent, log_call)
from app.platform.security import crypto

META_LANG = {"en": "en", "hi": "hi", "te": "te", "ta": "ta", "kn": "kn", "ml": "ml", "mr": "mr", "bn": "bn",
             "gu": "gu", "pa": "pa_IN", "or": "or"}


class WhatsAppProvider:
    name = "base"
    mode = "live"
    supports_templates = True  # False: send business-initiated messages as the rendered template text

    def send_template(self, db, merchant_id: str, to_e164: str, template_name: str, language: str,
                      params: list[str], idempotency_key: str) -> SendResult:
        raise NotImplementedError

    def send_text(self, db, merchant_id: str, to_e164: str, body: str, idempotency_key: str) -> SendResult:
        raise NotImplementedError

    def verify_signature(self, headers: dict, raw_body: bytes) -> bool:
        raise NotImplementedError

    def parse_webhook(self, payload: dict) -> tuple[list[WhatsAppStatusEvent], list[WhatsAppInbound]]:
        raise NotImplementedError

    def health(self) -> Health:
        raise NotImplementedError


def _ts(value) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def parse_meta_payload(payload: dict) -> tuple[list[WhatsAppStatusEvent], list[WhatsAppInbound]]:
    statuses: list[WhatsAppStatusEvent] = []
    inbound: list[WhatsAppInbound] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for s in value.get("statuses", []):
                err = (s.get("errors") or [{}])[0]
                statuses.append(WhatsAppStatusEvent(
                    provider_message_id=s["id"], status=s["status"], occurred_at=_ts(s["timestamp"]),
                    provider_event_id=f"{s['id']}:{s['status']}:{s['timestamp']}",
                    error_code=str(err.get("code")) if err.get("code") else None, error_title=err.get("title"),
                ))
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    text = m["text"]["body"]
                elif m.get("type") == "button":
                    text = m.get("button", {}).get("text", "")
                elif m.get("type") == "interactive":
                    i = m.get("interactive", {})
                    text = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                else:
                    text = f"[{m.get('type', 'unsupported')} message]"
                inbound.append(WhatsAppInbound(provider_message_id=m["id"], from_e164="+" + m["from"].lstrip("+"),
                                               text=text, occurred_at=_ts(m["timestamp"]), message_type=m.get("type", "text")))
    return statuses, inbound


class MetaCloudWhatsApp(WhatsAppProvider):
    name = "meta_cloud"
    mode = "live"

    def __init__(self):
        s = get_settings()
        if not (s.meta_phone_number_id and s.meta_access_token and s.meta_app_secret):
            raise ProviderNotConfigured("META_PHONE_NUMBER_ID, META_ACCESS_TOKEN and META_APP_SECRET are required")
        self.url = f"https://graph.facebook.com/{s.meta_graph_api_version}/{s.meta_phone_number_id}/messages"
        self.token = s.meta_access_token
        self.app_secret = s.meta_app_secret
        self.timeout = s.provider_timeout_seconds

    def _post(self, db, merchant_id: str, body: dict, operation: str) -> SendResult:
        with Timer() as t:
            try:
                resp = httpx.post(self.url, json=body, timeout=self.timeout,
                                  headers={"Authorization": f"Bearer {self.token}"})
            except httpx.TimeoutException as exc:
                log_call(db, merchant_id, "whatsapp:meta_cloud", operation, False, int(self.timeout * 1000), None, "timeout")
                raise OutcomeUnknown("WhatsApp send timed out; the message may have been accepted") from exc
            except httpx.HTTPError as exc:
                log_call(db, merchant_id, "whatsapp:meta_cloud", operation, False, 0, None, "network")
                raise ProviderError(f"network error: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            code = str(err.get("code", resp.status_code))
            log_call(db, merchant_id, "whatsapp:meta_cloud", operation, False, t.ms, resp.status_code, code)
            retryable = resp.status_code == 429 or resp.status_code >= 500
            raise ProviderError(f"WhatsApp API error {code}: {str(err.get('message', ''))[:120]}", code, retryable,
                                resp.status_code)
        log_call(db, merchant_id, "whatsapp:meta_cloud", operation, True, t.ms, resp.status_code)
        return SendResult(provider_message_id=resp.json()["messages"][0]["id"])

    def send_template(self, db, merchant_id, to_e164, template_name, language, params, idempotency_key):
        body = {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": to_e164.lstrip("+"),
            "type": "template",
            "template": {"name": template_name, "language": {"code": META_LANG.get(language, "en")},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]},
        }
        return self._post(db, merchant_id, body, "send_template")

    def send_text(self, db, merchant_id, to_e164, body, idempotency_key):
        return self._post(db, merchant_id, {"messaging_product": "whatsapp", "recipient_type": "individual",
                                            "to": to_e164.lstrip("+"), "type": "text", "text": {"body": body[:4096]}},
                          "send_text")

    def verify_signature(self, headers: dict, raw_body: bytes) -> bool:
        return crypto.verify_signature(raw_body, self.app_secret, headers.get("x-hub-signature-256"), "sha256=")

    def parse_webhook(self, payload):
        return parse_meta_payload(payload)

    def health(self) -> Health:
        return Health("whatsapp:meta_cloud", "live", "connected", "Credentials configured; state from recent calls")


class SimulatedWhatsApp(WhatsAppProvider):
    """Speaks the Meta webhook format so the ingestion path is identical to production."""

    name = "simulator"
    mode = "simulated"

    def send_template(self, db, merchant_id, to_e164, template_name, language, params, idempotency_key):
        return self._accept(db, merchant_id, "send_template")

    def send_text(self, db, merchant_id, to_e164, body, idempotency_key):
        return self._accept(db, merchant_id, "send_text")

    def _accept(self, db, merchant_id, operation) -> SendResult:
        log_call(db, merchant_id, "whatsapp:simulator", operation, True, 1, 200)
        return SendResult(provider_message_id=f"sim.wamid.{new_id()}")

    @staticmethod
    def secret() -> str:
        return get_settings().secret_key + ":whatsapp-sim"

    def verify_signature(self, headers: dict, raw_body: bytes) -> bool:
        return crypto.verify_signature(raw_body, self.secret(), headers.get("x-hub-signature-256"), "sha256=")

    def sign(self, payload: dict) -> tuple[bytes, dict]:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return raw, {"x-hub-signature-256": "sha256=" + crypto.sign(raw, self.secret())}

    def parse_webhook(self, payload):
        return parse_meta_payload(payload)

    def health(self) -> Health:
        return Health("whatsapp:simulator", "simulated", "simulated", "Simulator: no real messages are sent")


_OPENWA_STATUS = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}


def _openwa_phone(chat_id: str | None, sender_phone: str | None) -> str | None:
    if sender_phone:
        return "+" + "".join(ch for ch in str(sender_phone) if ch.isdigit())
    if chat_id and chat_id.endswith("@c.us"):
        return "+" + chat_id.split("@", 1)[0]
    return None  # @lid privacy id without senderPhone: cannot be matched to a customer


def parse_openwa_payload(payload: dict) -> tuple[list[WhatsAppStatusEvent], list[WhatsAppInbound]]:
    event = payload.get("event")
    data = payload.get("data") or {}
    statuses: list[WhatsAppStatusEvent] = []
    inbound: list[WhatsAppInbound] = []
    if event in ("message.ack", "message.failed"):
        status = _OPENWA_STATUS.get(str(data.get("status") or ("failed" if event == "message.failed" else "")))
        mid = data.get("messageId") or data.get("id")
        if status and mid:
            at = datetime.fromisoformat(str(payload.get("timestamp")).replace("Z", "+00:00")) if payload.get("timestamp") \
                else datetime.now(timezone.utc)
            statuses.append(WhatsAppStatusEvent(provider_message_id=str(mid), status=status, occurred_at=at,
                                                provider_event_id=f"{mid}:{status}",
                                                error_title="WhatsApp reported the message as failed" if status == "failed" else None))
    elif event == "message.received":
        if data.get("fromMe") or data.get("isGroup") or data.get("kind", "individual") != "individual":
            return statuses, inbound
        phone = _openwa_phone(data.get("from") or data.get("chatId"), data.get("senderPhone"))
        if phone and data.get("id"):
            mtype = data.get("type") or "text"
            text = data.get("body") or "" if mtype == "text" else (data.get("body") or f"[{mtype} message]")
            inbound.append(WhatsAppInbound(provider_message_id=str(data["id"]), from_e164=phone, text=text,
                                           occurred_at=_ts(data.get("timestamp") or 0), message_type=mtype))
    return statuses, inbound


class OpenWAWhatsApp(WhatsAppProvider):
    name = "openwa"
    mode = "live"
    supports_templates = False

    def __init__(self):
        s = get_settings()
        missing = [n for n, v in (("OPENWA_BASE_URL", s.openwa_base_url), ("OPENWA_API_KEY", s.openwa_api_key),
                                  ("OPENWA_SESSION_ID", s.openwa_session_id), ("OPENWA_WEBHOOK_SECRET", s.openwa_webhook_secret)) if not v]
        if missing:
            raise ProviderNotConfigured("OpenWA not configured: " + ", ".join(missing))
        self.url = f"{s.openwa_base_url.rstrip('/')}/sessions/{s.openwa_session_id}/messages/send-text"
        self.key = s.openwa_api_key
        self.secret = s.openwa_webhook_secret
        self.timeout = s.provider_timeout_seconds

    def send_template(self, db, merchant_id, to_e164, template_name, language, params, idempotency_key):
        raise ProviderError("OpenWA has no message templates; send the rendered text", "unsupported")

    def send_text(self, db, merchant_id, to_e164, body, idempotency_key):
        chat_id = "".join(ch for ch in to_e164 if ch.isdigit()) + "@c.us"
        with Timer() as t:
            try:
                resp = httpx.post(self.url, json={"chatId": chat_id, "text": body[:4096]}, timeout=self.timeout,
                                  headers={"X-API-Key": self.key, "Idempotency-Key": idempotency_key[:200]})
            except httpx.TimeoutException as exc:
                # OpenWA honours Idempotency-Key, so a retry with the same key cannot send a second message.
                log_call(db, merchant_id, "whatsapp:openwa", "send_text", False, int(self.timeout * 1000), None, "timeout")
                raise ProviderError("OpenWA send timed out; retrying with the same idempotency key", "timeout", True) from exc
            except httpx.HTTPError as exc:
                log_call(db, merchant_id, "whatsapp:openwa", "send_text", False, 0, None, "network")
                raise ProviderError(f"OpenWA network error: {type(exc).__name__}", "network", True) from exc
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except ValueError:
                err = {}
            code = str(err.get("code") or resp.status_code)
            log_call(db, merchant_id, "whatsapp:openwa", "send_text", False, t.ms, resp.status_code, code)
            # 409: session reconnecting or WhatsApp Web reloading; 429/5xx: transient. 4xx otherwise: our request or key.
            retryable = resp.status_code in (409, 429) or resp.status_code >= 500
            raise ProviderError(f"OpenWA error {code}: {str(err.get('message', ''))[:120]}", code, retryable, resp.status_code)
        log_call(db, merchant_id, "whatsapp:openwa", "send_text", True, t.ms, resp.status_code)
        return SendResult(provider_message_id=str(resp.json()["messageId"]))

    def verify_signature(self, headers: dict, raw_body: bytes) -> bool:
        return crypto.verify_signature(raw_body, self.secret, headers.get("x-openwa-signature"), "sha256=")

    def parse_webhook(self, payload):
        return parse_openwa_payload(payload)

    def health(self) -> Health:
        return Health("whatsapp:openwa", "live", "connected", "OpenWA gateway configured; state from recent calls")


def whatsapp_live(merchant_is_demo: bool) -> bool:
    """False when a real merchant would only get the simulator: its customers would never see the message."""
    return merchant_is_demo or get_settings().whatsapp_provider != "simulator"


def get_whatsapp(merchant_is_demo: bool) -> WhatsAppProvider:
    s = get_settings()
    if merchant_is_demo or s.whatsapp_provider == "simulator":
        if s.is_production and not merchant_is_demo:
            raise ProviderNotConfigured("WhatsApp simulator is not allowed for live merchants in production")
        return SimulatedWhatsApp()
    if s.whatsapp_provider == "meta_cloud":
        return MetaCloudWhatsApp()
    if s.whatsapp_provider == "openwa":
        return OpenWAWhatsApp()
    raise ProviderNotConfigured(f"unknown WHATSAPP_PROVIDER {s.whatsapp_provider}")
