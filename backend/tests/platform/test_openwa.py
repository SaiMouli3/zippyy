"""OpenWA WhatsApp gateway: HTTP to OpenWA is mocked; nothing is sent to WhatsApp."""
import hashlib
import hmac
import json

import httpx
import pytest

from app.config import get_settings
from app.platform.providers.base import ProviderError
from app.platform.providers.whatsapp import OpenWAWhatsApp, parse_openwa_payload

BASE = "http://openwa.test:2785/api"
SECRET = "openwa-test-secret-123456"


@pytest.fixture
def openwa_env(monkeypatch):
    for k, v in {"WHATSAPP_PROVIDER": "openwa", "OPENWA_BASE_URL": BASE, "OPENWA_API_KEY": "owa-key",
                 "OPENWA_SESSION_ID": "zippyy", "OPENWA_WEBHOOK_SECRET": SECRET}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _resp(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", BASE))


def test_parse_inbound_and_acks():
    st, inb = parse_openwa_payload({"event": "message.received", "timestamp": "2026-10-21T10:00:00.000Z", "data": {
        "id": "MSG1", "from": "919000011111@c.us", "chatId": "919000011111@c.us", "body": "kal aana", "type": "text",
        "timestamp": 1792576800, "fromMe": False, "isGroup": False, "kind": "individual"}})
    assert not st and inb[0].from_e164 == "+919000011111" and inb[0].text == "kal aana"
    _, inb = parse_openwa_payload({"event": "message.received", "data": {
        "id": "MSG2", "from": "1234567@lid", "senderPhone": "919000022222", "body": "yes", "type": "text", "timestamp": 1}})
    assert inb[0].from_e164 == "+919000022222"
    for skipped in ({"fromMe": True}, {"isGroup": True}, {"kind": "group"}, {"from": "777@lid"}):
        data = {"id": "X", "from": "919000011111@c.us", "body": "x", "type": "text", "timestamp": 1, **skipped}
        assert parse_openwa_payload({"event": "message.received", "data": data}) == ([], [])
    st, _ = parse_openwa_payload({"event": "message.ack", "timestamp": "2026-10-21T10:00:00.000Z",
                                  "data": {"id": "a", "messageId": "M1", "status": "delivered", "ack": 2}})
    assert (st[0].provider_message_id, st[0].status) == ("M1", "delivered")
    assert parse_openwa_payload({"event": "message.ack", "data": {"messageId": "M1", "status": "pending"}}) == ([], [])
    st, _ = parse_openwa_payload({"event": "message.failed", "data": {"messageId": "M1", "status": "failed", "ack": -1}})
    assert st[0].status == "failed"


def test_send_text_request_and_errors(openwa_env, monkeypatch):
    seen = {}

    def ok(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        return _resp(201, {"messageId": "true_919000011111@c.us_3EB0", "timestamp": 1})

    monkeypatch.setattr(httpx, "post", ok)
    r = OpenWAWhatsApp().send_text(None, None, "+91 90000 11111", "Hello", "idem-1")
    assert r.provider_message_id == "true_919000011111@c.us_3EB0"
    assert seen["url"] == f"{BASE}/sessions/zippyy/messages/send-text"
    assert seen["body"] == {"chatId": "919000011111@c.us", "text": "Hello"}
    assert seen["headers"]["X-API-Key"] == "owa-key" and seen["headers"]["Idempotency-Key"] == "idem-1"

    monkeypatch.setattr("app.platform.providers.whatsapp.log_call", lambda *a, **k: None)
    for status, retryable in ((409, True), (503, True), (429, True), (401, False), (400, False)):
        monkeypatch.setattr(httpx, "post", lambda *a, _s=status, **k: _resp(_s, {"code": "X", "message": "m"}))
        with pytest.raises(ProviderError) as e:
            OpenWAWhatsApp().send_text(None, None, "+919000011111", "Hi", "k")
        assert e.value.retryable is retryable, status

    def slow(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "post", slow)
    with pytest.raises(ProviderError) as e:
        OpenWAWhatsApp().send_text(None, None, "+919000011111", "Hi", "k")
    assert e.value.retryable  # safe: OpenWA de-duplicates on Idempotency-Key


def _signed(payload):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-OpenWA-Signature": sig}


def test_ndr_flow_over_openwa(world, openwa_env, monkeypatch):
    from sqlalchemy import select

    from app.platform.models import CarrierAction, Message, NdrCase
    from tests.platform.test_workflows import fail_delivery, one

    sent = []
    real_post = httpx.post

    def fake_post(url, *a, **k):
        if not str(url).startswith(BASE):
            return real_post(url, *a, **k)
        sent.append(k["json"])
        return _resp(201, {"messageId": f"OWA{len(sent)}", "timestamp": 1})

    monkeypatch.setattr(httpx, "post", fake_post)
    m = world.merchant(code="MER-OWA", demo=False)
    sid = world.shipment(m, phone="+919000033333")
    fail_delivery(world, sid)
    world.run(minutes=5)

    assert len(sent) == 1 and sent[0]["chatId"] == "919000033333@c.us"
    assert "Test" in sent[0]["text"]  # the rendered template text, not a template name
    msg = one(world, Message, Message.shipment_id == sid, Message.direction == "outbound")
    assert (msg.provider, msg.provider_message_id, msg.delivery_status) == ("openwa", "OWA1", "submitted")

    raw, headers = _signed({"event": "message.ack", "timestamp": "2026-10-21T05:00:00.000Z", "sessionId": "zippyy",
                            "idempotencyKey": "ack_OWA1_delivered", "data": {"messageId": "OWA1", "status": "delivered", "ack": 2}})
    assert world.client.post("/api/v1/providers/whatsapp/openwa", content=raw, headers=headers).status_code == 200
    assert world.client.post("/api/v1/providers/whatsapp/openwa", content=raw, headers=headers).status_code == 200  # duplicate
    assert one(world, Message, Message.id == msg.id).delivery_status == "delivered"

    bad = dict(headers, **{"X-OpenWA-Signature": "sha256=" + "0" * 64})
    assert world.client.post("/api/v1/providers/whatsapp/openwa", content=raw, headers=bad).status_code == 401

    raw, headers = _signed({"event": "message.received", "timestamp": "2026-10-21T05:01:00.000Z", "sessionId": "zippyy",
                            "idempotencyKey": "msg_zippyy_IN1", "data": {
                                "id": "IN1", "from": "919000033333@c.us", "chatId": "919000033333@c.us",
                                "body": "kal shaam 6 baje ke baad bhej do", "type": "text", "timestamp": 1792573260,
                                "fromMe": False, "isGroup": False, "kind": "individual"}})
    assert world.client.post("/api/v1/providers/whatsapp/openwa", content=raw, headers=headers).status_code == 200
    world.run(minutes=10)
    assert one(world, CarrierAction, CarrierAction.shipment_id == sid).status == "accepted"
    assert one(world, NdrCase, NdrCase.shipment_id == sid).status == "reattempt_scheduled"
    db = world.session()
    try:
        outbound = db.scalars(select(Message).where(Message.shipment_id == sid, Message.direction == "outbound")).all()
        assert all(o.provider == "openwa" for o in outbound) and len(sent) == len(outbound) >= 2
    finally:
        db.close()
