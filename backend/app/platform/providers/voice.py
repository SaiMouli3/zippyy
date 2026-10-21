"""Voice providers.

* `SarvamVoiceAgent` places calls through Sarvam's hosted voice agents (instant outbound API). Sarvam runs the
  multilingual conversation; our webhook receives the outcome, English transcript and the agent's final
  variables. The agent must be configured to write the variables in `FINAL_VARIABLES_CONTRACT`; anything
  missing is recorded as unknown, never guessed.
* `SimulatedVoice` runs our own turn-by-turn conversation engine (voice_engine.py) against a scripted demo
  customer and delivers the result through the same signed webhook path.
"""
from datetime import datetime, timezone

from app.config import get_settings
from app.platform.ids import new_id
from app.platform.providers.base import CallTurn, CallUpdate, Health, ProviderNotConfigured, log_call
from app.platform.security import crypto

FINAL_VARIABLES_CONTRACT = {
    "intent": "one of the platform intents (reschedule, reattempt_today, refuse, address_change, callback, ...)",
    "requested_date": "YYYY-MM-DD or empty",
    "requested_window": "HH:MM-HH:MM or empty",
    "customer_language": "language code the call ended in (en, hi, te, ...)",
    "language_switches": "list of {from, to, turn}",
    "confirmed_by_customer": "true when the agent read the preference back and the customer agreed",
}

SARVAM_STATUS = {"connected": "completed", "no_answer": "no_answer", "busy": "busy", "failed": "failed"}


def callback_token(call_id: str) -> str:
    return crypto.sign(call_id.encode(), get_settings().voice_webhook_secret)


class VoiceProvider:
    name = "base"
    mode = "live"

    def place_call(self, db, merchant_id: str, call_id: str, to_e164: str, language: str, variables: dict) -> str:
        raise NotImplementedError

    def verify(self, headers: dict, query: dict, raw_body: bytes) -> bool:
        raise NotImplementedError

    def parse(self, payload: dict) -> CallUpdate:
        raise NotImplementedError

    def health(self) -> Health:
        raise NotImplementedError


class SarvamVoiceAgent(VoiceProvider):
    name = "sarvam_agents"
    mode = "live"

    def __init__(self):
        from app.platform.providers.sarvam import SarvamAgentsClient
        self.client = SarvamAgentsClient()

    def place_call(self, db, merchant_id, call_id, to_e164, language, variables):
        token = callback_token(call_id)
        url = f"{get_settings().zippy_public_url}/api/v1/providers/voice/sarvam?call={call_id}&token={token}"
        try:
            attempt_id = self.client.create_outbound(to_e164, language, variables, url, {"call_id": call_id})
            log_call(db, merchant_id, "voice:sarvam_agents", "create_outbound", True, 0, 200)
            return attempt_id
        except Exception as exc:
            log_call(db, merchant_id, "voice:sarvam_agents", "create_outbound", False, 0, getattr(exc, "status_code", None),
                     getattr(exc, "code", "error"))
            raise

    def verify(self, headers, query, raw_body):
        call_id, token = query.get("call"), query.get("token")
        return bool(call_id and token) and crypto.verify_signature(call_id.encode(), get_settings().voice_webhook_secret, token)

    def parse(self, payload: dict) -> CallUpdate:
        status = SARVAM_STATUS.get(payload.get("status", ""), "unknown")
        fv = payload.get("final_agent_variables") or {}
        turns = [CallTurn(speaker="agent" if t.get("role") == "agent" else "customer", text=None,
                          text_en=t.get("en_text")) for t in (payload.get("interaction_transcript") or [])]
        switches = fv.get("language_switches") or []
        return CallUpdate(
            provider_call_id=payload["attempt_id"], status=status, raw_status=payload.get("status", ""),
            provider_event_id=f"sarvam:{payload['attempt_id']}:{payload.get('status')}",
            occurred_at=datetime.now(timezone.utc), duration_seconds=int(payload["duration"]) if payload.get("duration") else None,
            failure_reason=payload.get("failure_reason"), turns=turns, final_variables=fv,
            final_language=fv.get("customer_language"), start_language=(switches[0]["from"] if switches else None),
            interaction_id=payload.get("interaction_id"),
        )

    def health(self) -> Health:
        return Health("voice:sarvam_agents", "live", "connected", "Sarvam voice agent configured")


class SimulatedVoice(VoiceProvider):
    name = "simulator"
    mode = "simulated"

    def place_call(self, db, merchant_id, call_id, to_e164, language, variables):
        log_call(db, merchant_id, "voice:simulator", "place_call", True, 1, 200)
        return f"sim.call.{new_id()}"

    def verify(self, headers, query, raw_body):
        return crypto.verify_signature(raw_body, get_settings().voice_webhook_secret + ":sim", headers.get("x-zippy-signature"))

    @staticmethod
    def sign(raw: bytes) -> dict:
        return {"x-zippy-signature": crypto.sign(raw, get_settings().voice_webhook_secret + ":sim")}

    def parse(self, payload: dict) -> CallUpdate:
        turns = [CallTurn(**t) for t in payload.get("turns", [])]
        return CallUpdate(
            provider_call_id=payload["provider_call_id"], status=payload["status"], raw_status=payload["status"],
            provider_event_id=payload["event_id"], occurred_at=datetime.fromisoformat(payload["occurred_at"]),
            duration_seconds=payload.get("duration_seconds"), failure_reason=payload.get("failure_reason"),
            turns=turns, final_variables=payload.get("final_variables", {}),
            start_language=payload.get("start_language"), final_language=payload.get("final_language"),
            cost_paise=payload.get("cost_paise"),
        )

    def health(self) -> Health:
        return Health("voice:simulator", "simulated", "simulated", "Simulator: no real calls are placed")


def get_voice(merchant_is_demo: bool) -> VoiceProvider:
    s = get_settings()
    if merchant_is_demo or s.voice_provider == "simulator":
        if s.is_production and not merchant_is_demo:
            raise ProviderNotConfigured("Voice simulator is not allowed for live merchants in production")
        return SimulatedVoice()
    if s.voice_provider == "sarvam_agents":
        return SarvamVoiceAgent()
    raise ProviderNotConfigured(f"unknown VOICE_PROVIDER {s.voice_provider}")


def provider_by_name(name: str) -> VoiceProvider:
    return SarvamVoiceAgent() if name == "sarvam_agents" else SimulatedVoice()
