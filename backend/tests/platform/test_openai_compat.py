"""OpenAI-compatible LLM extractor: HTTP is mocked; no real provider is called."""
import json
from datetime import date

import httpx
import pytest

from app.config import get_settings
from app.platform import intent as intent_mod
from app.platform.intent import ExtractionContext, SarvamLLMExtractor
from app.platform.providers.openai_compat import OpenAICompatClient

CTX = ExtractionContext(today=date(2026, 10, 14), purpose="ndr_recovery")


@pytest.fixture
def llm_env(monkeypatch):
    monkeypatch.setenv("INTENT_EXTRACTOR", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1/")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _reply(payload, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": payload}}]},
                          request=httpx.Request("POST", "https://llm.example.test/v1/chat/completions"))


def test_factory_selects_openai_compatible(llm_env):
    ext = intent_mod.get_extractor()
    assert isinstance(ext, SarvamLLMExtractor) and isinstance(ext.client, OpenAICompatClient)
    assert ext.name == "llm:test-model"


def test_valid_json_is_used_and_request_is_well_formed(llm_env, monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        out = {"intent": "reschedule", "requested_date": "2026-10-15", "requested_window": "18:00-21:00",
               "accepts_delivery": True, "cod_ready": None, "requested_language": None, "confidence": 0.93}
        return _reply("```json\n" + __import__("json").dumps(out) + "\n```")

    monkeypatch.setattr(httpx, "post", fake_post)
    r = intent_mod.get_extractor().extract("kal shaam 6 ke baad bhejo", CTX)
    assert r.intent == "reschedule" and str(r.requested_date) == "2026-10-15" and r.extractor == "llm:test-model"
    assert seen["url"] == "https://llm.example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert seen["body"]["temperature"] == 0 and seen["body"]["response_format"]["type"] == "json_schema"


def test_json_mode_retry_when_schema_rejected(llm_env, monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json["response_format"]["type"])
        if json["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "unsupported"}, request=httpx.Request("POST", url))
        return _reply('{"intent":"available","requested_date":null,"requested_window":null,"accepts_delivery":true,'
                      '"cod_ready":null,"requested_language":null,"confidence":0.9}')

    monkeypatch.setattr(httpx, "post", fake_post)
    r = intent_mod.get_extractor().extract("haan main ghar pe hoon", CTX)
    assert calls == ["json_schema", "json_object"] and r.intent == "available"


@pytest.mark.parametrize("failure", ["timeout", "garbage", "http_500"])
def test_any_provider_failure_falls_back_to_rules(llm_env, monkeypatch, failure):
    def fake_post(url, json=None, headers=None, timeout=None):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        if failure == "garbage":
            return _reply("I think the customer wants tomorrow")
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    r = intent_mod.get_extractor().extract("deliver tomorrow after 6 pm", CTX)
    assert r.intent == "reschedule" and r.extractor.endswith(":fallback")


def test_unknown_intent_from_model_is_rejected(llm_env, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _reply(json.dumps(
        {"intent": "approve_refund", "requested_date": None, "requested_window": None, "accepts_delivery": None,
         "cod_ready": None, "requested_language": None, "confidence": 0.99})))
    r = intent_mod.get_extractor().extract("please approve my refund", CTX)
    assert r.intent != "approve_refund" and r.extractor.endswith(":fallback")


def test_missing_credentials_keep_rules(monkeypatch):
    monkeypatch.setenv("INTENT_EXTRACTOR", "openai_compatible")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        assert type(intent_mod.get_extractor()).__name__ == "RuleExtractor"
    finally:
        get_settings.cache_clear()
