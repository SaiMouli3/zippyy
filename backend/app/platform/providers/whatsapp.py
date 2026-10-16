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


def get_whatsapp(merchant_is_demo: bool) -> WhatsAppProvider:
    s = get_settings()
    if merchant_is_demo or s.whatsapp_provider == "simulator":
        if s.is_production and not merchant_is_demo:
            raise ProviderNotConfigured("WhatsApp simulator is not allowed for live merchants in production")
        return SimulatedWhatsApp()
    if s.whatsapp_provider == "meta_cloud":
        return MetaCloudWhatsApp()
    raise ProviderNotConfigured(f"unknown WHATSAPP_PROVIDER {s.whatsapp_provider}")
