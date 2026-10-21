"""Client for any OpenAI-compatible chat-completions API (LLM gateways and hosted model providers).

Configured entirely by settings: LLM_BASE_URL (e.g. https://<gateway>/v1), LLM_API_KEY (sent as a Bearer token) and
LLM_MODEL. Only `POST {base}/chat/completions` is used. Output is still validated against the intent schema by the
caller, and any failure falls back to the deterministic rules.
"""
import json
import re

import httpx

from app.config import get_settings
from app.platform.providers.base import ProviderError, ProviderNotConfigured

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class OpenAICompatClient:
    def __init__(self):
        s = get_settings()
        missing = [n for n, v in (("LLM_BASE_URL", s.llm_base_url), ("LLM_API_KEY", s.llm_api_key), ("LLM_MODEL", s.llm_model)) if not v]
        if missing:
            raise ProviderNotConfigured("OpenAI-compatible LLM not configured: " + ", ".join(missing))
        self.base = s.llm_base_url.rstrip("/")
        self.key = s.llm_api_key
        self.timeout = s.provider_timeout_seconds

    def _post(self, body: dict) -> httpx.Response:
        try:
            return httpx.post(f"{self.base}/chat/completions", json=body, timeout=self.timeout,
                              headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        except httpx.TimeoutException as exc:
            raise ProviderError("LLM request timed out", "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM network error: {type(exc).__name__}", "network") from exc

    def chat_json(self, model: str, messages: list[dict], schema: dict) -> dict:
        body = {"model": model, "messages": messages, "temperature": 0,
                "response_format": {"type": "json_schema", "json_schema": schema}}
        resp = self._post(body)
        if resp.status_code == 400:
            # Some gateways accept only JSON mode, not strict schemas; the caller validates the shape either way.
            body["response_format"] = {"type": "json_object"}
            resp = self._post(body)
        if resp.status_code >= 400:
            raise ProviderError(f"LLM error http_{resp.status_code}", f"http_{resp.status_code}",
                                resp.status_code in (429, 500, 502, 503, 504), resp.status_code)
        content = resp.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return json.loads(_FENCE.sub("", content.strip()))
