"""Webhook ingestion: signatures, inbox dedupe, quarantine, state machine, NDR opening."""
import json

from sqlalchemy import func, select

from app.mock_carriers import common as mock
from app.mock_carriers import fastship


def _payload(awb, status, event_id, at, reason=None):
    s = mock.MockShipment(carrier="fastship", carrier_shipment_id="x", tracking_number=awb, reference=None, status=status)
    return fastship.build_webhook(s, status, event_id, at, reason)


def _count(world, model, *where):
    db = world.session()
    try:
        return db.scalar(select(func.count()).select_from(model).where(*where))
    finally:
        db.close()


def test_failed_attempt_opens_one_case_and_one_task_even_when_duplicated(world):
    from app.platform.models import AgentTask, NdrCase, WebhookInbox
    m = world.merchant()
    sid = world.shipment(m)
    for st in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"):
        world.scan(sid, st)
    world.scan(sid, "DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", duplicate=True)
    assert _count(world, NdrCase, NdrCase.shipment_id == sid) == 1
    assert _count(world, AgentTask, AgentTask.shipment_id == sid, AgentTask.task_type == "ndr_recovery") == 1
    db = world.session()
    case = db.scalars(select(NdrCase).where(NdrCase.shipment_id == sid)).one()
    assert case.reason == "customer_unavailable" and case.carrier_reason and case.attempt_no == 1
    db.close()
    assert _count(world, WebhookInbox) == 4  # 4 distinct events; the duplicate delivery is not stored twice


def test_replayed_webhook_returns_duplicate(world):
    m = world.merchant()
    sid = world.shipment(m, awb="FST100000001")
    world.scan(sid, "PICKED_UP")
    from datetime import datetime, timezone
    body = _payload("FST100000001", "IN_TRANSIT", "evt-1", datetime(2026, 10, 14, 5, tzinfo=timezone.utc))
    raw, headers = mock.sign_webhook("fastship", body)
    r1 = world.client.post("/api/webhooks/fastship", content=raw, headers=headers)
    r2 = world.client.post("/api/webhooks/fastship", content=raw, headers=headers)
    assert r1.json()["outcome"] == "applied" and r2.json()["outcome"] == "duplicate"


def test_bad_signature_is_rejected_and_quarantined_when_required(world, monkeypatch):
    from app.config import get_settings
    from app.platform.models import WebhookQuarantine
    monkeypatch.setattr(get_settings(), "carrier_webhook_signature_required", True)
    m = world.merchant()
    world.shipment(m, awb="FST100000002")
    from datetime import datetime, timezone
    body = _payload("FST100000002", "PICKED_UP", "evt-2", datetime(2026, 10, 14, 5, tzinfo=timezone.utc))
    r = world.client.post("/api/webhooks/fastship", content=json.dumps(body), headers={"content-type": "application/json",
                                                                                       "x-carrier-signature": "forged"})
    assert r.status_code == 401
    assert _count(world, WebhookQuarantine, WebhookQuarantine.reason == "bad_signature") == 1
    raw, headers = mock.sign_webhook("fastship", body)
    assert world.client.post("/api/webhooks/fastship", content=raw, headers=headers).status_code == 200


def test_unknown_awb_and_unparseable_payloads_are_quarantined(world):
    from app.platform.models import WebhookQuarantine
    world.merchant()
    from datetime import datetime, timezone
    raw, headers = mock.sign_webhook("fastship", _payload("NOPE123", "PICKED_UP", "e", datetime.now(timezone.utc)))
    assert world.client.post("/api/webhooks/fastship", content=raw, headers=headers).status_code == 404
    raw, headers = mock.sign_webhook("fastship", {"foo": "bar"})
    assert world.client.post("/api/webhooks/fastship", content=raw, headers=headers).status_code == 422
    assert world.client.post("/api/webhooks/fastship", content=b"{not json", headers={"content-type": "application/json"}).status_code == 422
    reasons = {r for (r,) in world.session().execute(select(WebhookQuarantine.reason))}
    assert {"unknown_awb", "unparseable"} <= reasons


def test_out_of_order_and_illegal_transitions_never_regress_state(world):
    from app.models import Shipment
    from app.platform.models import WebhookQuarantine
    m = world.merchant()
    sid = world.shipment(m)
    world.scan(sid, "OUT_FOR_DELIVERY")
    world.scan(sid, "PICKED_UP")  # late scan arriving out of order
    world.scan(sid, "DELIVERED")
    world.scan(sid, "OUT_FOR_DELIVERY")  # after delivery: illegal
    db = world.session()
    assert db.get(Shipment, sid).current_status == "DELIVERED"
    db.close()
    assert _count(world, WebhookQuarantine, WebhookQuarantine.reason == "illegal_transition") == 2


def test_rto_lifecycle_closes_case_only_when_return_completes(world):
    from app.platform.models import NdrCase
    m = world.merchant()
    sid = world.shipment(m)
    world.scan(sid, "OUT_FOR_DELIVERY")
    world.scan(sid, "DELIVERY_FAILED", "REFUSED")
    world.scan(sid, "RTO")
    db = world.session()
    case = db.scalars(select(NdrCase).where(NdrCase.shipment_id == sid)).one()
    assert case.status == "rto" and case.resolved_at is None and case.reason == "customer_refused"
    db.close()
    world.scan(sid, "RTO_DELIVERED")
    db = world.session()
    case = db.scalars(select(NdrCase).where(NdrCase.shipment_id == sid)).one()
    assert case.status == "resolved" and case.resolution == "rto"
    db.close()
