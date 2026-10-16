"""Sarvam AI clients, built from the official API reference (docs.sarvam.ai):

api.sarvam.ai (header `api-subscription-key`)
  POST /text-lid                 {"input"} -> {"language_code", "script_code"}
  POST /speech-to-text           multipart file, model=saaras:v3|v4, language_code=unknown -> transcript,
                                 language_code, language_probability
  POST /text-to-speech           {"text", "language_code", "model": "bulbul:v3", "speaker"} -> {"audios": [b64]}
  POST /v1/chat/completions      OpenAI-style; models sarvam-105b / sarvam-105b-conversations;
                                 response_format json_schema for structured output

apps.sarvam.ai (header `X-API-Key`) — hosted voice agents
  POST /api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds -> {"attempt_id"}
  webhook after each attempt: attempt_id, status (connected|no_answer|busy|failed), duration, interaction_id,
  failure_reason, final_agent_variables, webhook_config.metadata, interaction_transcript[{role, en_text}]
  The webhook is not signed by Sarvam, so each call gets its own HMAC token in the callback URL.
"""
import json

import httpx

from app.config import get_settings
from app.platform.language import BCP47, FROM_BCP47
from app.platform.providers.base import OutcomeUnknown, ProviderError, ProviderNotConfigured, Timer

API = "https://api.sarvam.ai"
AGENTS_API = "https://apps.sarvam.ai/api/outbounds/v1"

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam",
                  "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "or": "Odia"}


class SarvamClient:
    def __init__(self):
        s = get_settings()
        if not s.sarvam_api_key:
            raise ProviderNotConfigured("SARVAM_API_KEY is not set")
        self.key = s.sarvam_api_key
        self.timeout = s.provider_timeout_seconds

    def _post(self, path: str, **kwargs) -> dict:
        try:
            resp = httpx.post(API + path, headers={"api-subscription-key": self.key}, timeout=self.timeout, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("Sarvam request timed out", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Sarvam network error: {type(exc).__name__}", "network") from exc
        if resp.status_code >= 400:
            code = "http_" + str(resp.status_code)
            try:
                code = resp.json().get("error", {}).get("code", code)
            except ValueError:
                pass
            raise ProviderError(f"Sarvam error {code}", code, resp.status_code in (429, 500, 502, 503, 504), resp.status_code)
        return resp.json()

    def identify_language(self, text: str) -> tuple[str | None, str | None]:
        data = self._post("/text-lid", json={"input": text[:1000]})
        return FROM_BCP47.get(data.get("language_code") or ""), data.get("script_code")

    def transcribe(self, audio: bytes, filename: str = "turn.wav", model: str = "saaras:v3") -> dict:
        data = self._post("/speech-to-text", files={"file": (filename, audio)},
                          data={"model": model, "language_code": "unknown"})
        return {"transcript": data.get("transcript", ""), "language": FROM_BCP47.get(data.get("language_code") or ""),
                "confidence": data.get("language_probability")}

    def synthesize(self, text: str, language: str, speaker: str = "shubh") -> list[str]:
        data = self._post("/text-to-speech", json={"text": text[:2500], "language_code": BCP47.get(language, "en-IN"),
                                                   "model": "bulbul:v3", "speaker": speaker})
        return data.get("audios", [])

    def chat_json(self, model: str, messages: list[dict], schema: dict) -> dict:
        data = self._post("/v1/chat/completions", json={
            "model": model, "messages": messages, "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": schema},
        })
        return json.loads(data["choices"][0]["message"]["content"])


class SarvamAgentsClient:
    def __init__(self):
        s = get_settings()
        missing = [k for k in ("sarvam_agents_api_key", "sarvam_org_id", "sarvam_workspace_id", "sarvam_app_id",
                               "sarvam_connection_id", "sarvam_agent_phone_number") if not getattr(s, k)]
        if missing or not s.sarvam_app_version:
            raise ProviderNotConfigured("Sarvam voice agent not configured: " + ", ".join(m.upper() for m in missing or ["SARVAM_APP_VERSION"]))
        self.s = s

    def create_outbound(self, to_e164: str, language: str, agent_variables: dict, webhook_url: str,
                        metadata: dict) -> str:
        s = self.s
        url = f"{AGENTS_API}/orgs/{s.sarvam_org_id}/workspaces/{s.sarvam_workspace_id}/outbounds"
        body = {
            "app_config": {
                "app_id": s.sarvam_app_id, "app_version": s.sarvam_app_version,
                "connection_config": {"connection_id": s.sarvam_connection_id,
                                      "agent_phone_number": s.sarvam_agent_phone_number},
                "agent_variables": agent_variables,
                "app_overrides": {"initial_language_name": LANGUAGE_NAMES.get(language, "English")},
            },
            "user_config": {"user_phone_number": to_e164},
            "webhook_config": {"url": webhook_url, "metadata": metadata},
        }
        with Timer():
            try:
                resp = httpx.post(url, json=body, headers={"X-API-Key": s.sarvam_agents_api_key},
                                  timeout=s.provider_timeout_seconds)
            except httpx.TimeoutException as exc:
                raise OutcomeUnknown("Sarvam outbound request timed out; the call may have been placed") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Sarvam network error: {type(exc).__name__}", "network") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"Sarvam outbound error {resp.status_code}", f"http_{resp.status_code}",
                                resp.status_code in (429, 500, 502, 503, 504), resp.status_code)
        return resp.json()["attempt_id"]
