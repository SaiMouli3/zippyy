import redis
import psycopg
import os

from .conftest import ORDER, send_event

R = redis.Redis.from_url(os.environ["REDIS_URL"])


def test_order_creation(api):
    r = api.post("/api/orders", json=ORDER)
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("ZPY-ORD-") and body["status"] == "CREATED" and body["codAmount"] == 2500
    assert api.get(f"/api/orders/{body['id']}").json()["customerName"] == "Rahul Sharma"


def test_order_validation(api):
    assert api.post("/api/orders", json={**ORDER, "phone": "123"}).status_code == 422
    assert api.post("/api/orders", json={**ORDER, "codAmount": 0}).status_code == 422
    assert api.get("/api/orders/NOPE").status_code == 404


def test_rates_normalized_and_cached(api, order):
    oid = order["id"]
    r = api.post(f"/api/orders/{oid}/rates").json()
    assert r["cached"] is False and r["errors"] == []
    by = {x["carrier"]: x for x in r["rates"]}
    assert set(by) == {"FASTSHIP", "QUICKEXPRESS", "RELIABLECOURIER"}
    assert by["FASTSHIP"]["price"] == 182.9 and by["QUICKEXPRESS"]["price"] == 197.06
    assert by["RELIABLECOURIER"]["price"] == 159.3
    assert set(by["FASTSHIP"]) == {"carrier", "carrierName", "service", "serviceName", "price", "etaMinDays", "etaMaxDays"}

    # redis key + TTL
    assert 0 < R.ttl(f"rates:{oid}") <= 300
    assert api.get(f"/api/orders/{oid}/rates").json()["cached"] is True
    # refresh bypasses and replaces the cache
    assert api.get(f"/api/orders/{oid}/rates?refresh=true").json()["cached"] is False
    assert R.exists(f"rates:{oid}")


def test_concurrent_rate_requests(api, order):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda _: api.post(f"/api/orders/{order['id']}/rates?refresh=true"), range(4)))
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]


def test_partial_carrier_failure(api, order):
    oid = order["id"]
    api.post("/mock/_control/failures", json={"carrier": "quickexpress", "fail": True})
    try:
        r = api.post(f"/api/orders/{oid}/rates?refresh=true")
        assert r.status_code == 200
        body = r.json()
        assert {x["carrier"] for x in body["rates"]} == {"FASTSHIP", "RELIABLECOURIER"}
        assert [e["carrier"] for e in body["errors"]] == ["QUICKEXPRESS"]
        assert not R.exists(f"rates:{oid}")  # partial results are not cached
        bad = api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": "QUICKEXPRESS", "service": "EXPRESS"})
        assert bad.status_code == 400
    finally:
        api.post("/mock/_control/failures", json={"carrier": "quickexpress", "fail": False})


def test_select_carrier(api, order):
    oid = order["id"]
    # no quotes yet
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "FASTSHIP", "service": "FAST-AIR"}).status_code == 400
    api.post(f"/api/orders/{oid}/rates")
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "FASTSHIP", "service": "NOT-A-SERVICE"}).status_code == 400
    r = api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": "FASTSHIP", "service": "FAST-AIR"})
    assert r.status_code == 200
    assert (r.json()["selectedCarrier"], r.json()["selectedService"], r.json()["quotedPrice"]) == ("FASTSHIP", "FAST-AIR", 182.9)


def test_shipment_creation_each_carrier(api):
    for carrier, service, prefix in [("FASTSHIP", "FAST-AIR", "FST"), ("QUICKEXPRESS", "EXPRESS", "QXP"),
                                     ("RELIABLECOURIER", "RC-SURFACE", "RLC")]:
        oid = api.post("/api/orders", json=ORDER).json()["id"]
        api.post(f"/api/orders/{oid}/rates")
        api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": carrier, "service": service})
        s = api.post(f"/api/orders/{oid}/shipment")
        assert s.status_code == 201, s.text
        assert s.json()["trackingNumber"].startswith(prefix) and s.json()["status"] == "SHIPMENT_CREATED"
        assert api.post(f"/api/orders/{oid}/shipment").status_code == 409  # only once
        t = api.get(f"/api/orders/{oid}/tracking").json()
        assert t["currentStatus"] == "SHIPMENT_CREATED" and len(t["statusHistory"]) == 1


def test_shipment_requires_selection(api, order):
    assert api.post(f"/api/orders/{order['id']}/shipment").status_code == 409


def test_webhooks_each_carrier_vocabulary(api):
    for carrier, service, slug in [("QUICKEXPRESS", "EXPRESS", "quickexpress"),
                                   ("RELIABLECOURIER", "RC-SURFACE", "reliable")]:
        oid = api.post("/api/orders", json=ORDER).json()["id"]
        api.post(f"/api/orders/{oid}/rates")
        api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": carrier, "service": service})
        tn = api.post(f"/api/orders/{oid}/shipment").json()["trackingNumber"]
        send_event(api, tn, "PICKED_UP", slug=slug)
        send_event(api, tn, "NDR", slug=slug, reason="COD_NOT_READY")
        assert api.get(f"/api/orders/{oid}/tracking").json()["currentStatus"] == "NDR"
        case = next(c for c in api.get("/api/ndr").json() if c["orderId"] == oid)
        assert case["reason"] == "COD_NOT_READY"


def test_duplicate_webhook_creates_one_event(api, shipped):
    t, oid = shipped["tracking"], shipped["orderId"]
    first = send_event(api, t, "PICKED_UP", eventId="evt-1")["webhookResponse"]
    second = send_event(api, t, "PICKED_UP", eventId="evt-1")["webhookResponse"]
    assert first["duplicate"] is False and second["duplicate"] is True
    hist = api.get(f"/api/orders/{oid}/tracking").json()["statusHistory"]
    assert [h["status"] for h in hist] == ["SHIPMENT_CREATED", "PICKED_UP"]
    # a different eventId is a distinct event
    send_event(api, t, "PICKED_UP", eventId="evt-2")
    assert len(api.get(f"/api/orders/{oid}/tracking").json()["statusHistory"]) == 3


def test_unknown_tracking_and_bad_payload(api):
    assert api.post("/api/webhooks/fastship", json={"trackingNumber": "X", "status": "PKD", "eventId": "1"}).status_code == 404
    assert api.post("/api/webhooks/fastship", json={"nope": 1}).status_code == 400
    assert api.post("/api/webhooks/unknown", json={}).status_code == 404


def test_ndr_creation(api, ndr_case):
    c = api.get(f"/api/ndr/{ndr_case['caseId']}").json()
    assert c["reason"] == "CUSTOMER_UNAVAILABLE" and c["attemptNumber"] == 1 and c["status"] == "OPEN"
    assert c["shipmentStatus"] == "NDR" and c["customerName"] == "Rahul Sharma"
    assert any(x["id"] == c["id"] for x in api.get("/api/ndr").json())
    assert "NDR_CREATED" in [a["event"] for a in c["audit"]]


def test_reattempt_flow(api, ndr_case):
    cid = ndr_case["caseId"]
    # nothing to act on before the buyer speaks
    assert api.post(f"/api/ndr/{cid}/reattempt").status_code == 409

    c = api.post(f"/api/ndr/{cid}/contact").json()
    assert c["messages"][0]["sender"] == "AGENT"
    assert len(api.post(f"/api/ndr/{cid}/contact").json()["messages"]) == 1  # idempotent

    c = api.post(f"/api/ndr/{cid}/message", json={"message": "Yes tomorrow evening after 6"}).json()
    assert c["lastIntent"]["intent"] == "RESCHEDULE_DELIVERY"
    assert c["lastDecision"]["outcome"] == "ALLOWED"
    assert c["status"] == "OPEN"
    agent_texts = [m["message"] for m in c["messages"] if m["sender"] == "AGENT"]
    assert not any("accepted" in t or "confirmed" in t for t in agent_texts)

    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "RESOLVED" and c["actions"][0]["status"] == "CARRIER_ACCEPTED"
    texts = [m["message"] for m in c["messages"] if m["sender"] == "AGENT"]
    # safety rule: "submitted" is said before "accepted", and acceptance only after the carrier replied
    sub = texts.index("Your reattempt request has been submitted to the carrier.")
    acc = texts.index("The carrier has accepted the reattempt request.")
    assert sub < acc
    events = [a["event"] for a in c["audit"]]
    assert events.index("CARRIER_ACTION_SUBMITTED") < events.index("CARRIER_ACTION_ACCEPTED")
    for e in ("BUYER_MESSAGE_RECEIVED", "INTENT_EXTRACTED"):
        assert e in events

    assert api.post(f"/api/ndr/{cid}/reattempt").status_code == 409  # can't repeat


def test_reattempt_blocked_by_rules(api, ndr_case):
    cid = ndr_case["caseId"]
    c = api.post(f"/api/ndr/{cid}/message", json={"message": "my address is wrong"}).json()
    assert c["lastDecision"]["outcome"] == "REQUIRES_APPROVAL" and c["status"] == "NEEDS_APPROVAL"
    r = api.post(f"/api/ndr/{cid}/reattempt")
    assert r.status_code == 409 and r.json()["decision"]["outcome"] == "REQUIRES_APPROVAL"
    detail = api.get(f"/api/ndr/{cid}").json()
    assert detail["actions"] == []  # carrier never called


def test_reattempt_carrier_rejection_never_claims_acceptance(api, ndr_case):
    # FastShip rejects the 3rd+ attempt. Force an NDR with attempt 3.
    t = ndr_case["tracking"]
    send_event(api, t, "NDR")                  # attempt 2
    third = send_event(api, t, "NDR")["webhookResponse"]["ndrCaseId"]   # attempt 3
    cid = third
    assert api.get(f"/api/ndr/{cid}").json()["attemptNumber"] == 3
    api.post(f"/api/ndr/{cid}/message", json={"message": "come tomorrow"})
    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "ACTION_FAILED" and c["actions"][0]["status"] == "REJECTED"
    assert not any("has accepted" in m["message"] for m in c["messages"])


def test_dashboard(api):
    d = api.get("/api/dashboard").json()
    assert d["totals"]["orders"] >= 1 and "recentShipments" in d and "recentNdr" in d


def test_seed_data(api):
    o = api.get("/api/orders/ZPY-ORD-10001").json()
    assert o["customerName"] == "Rahul Sharma" and o["shipment"]["trackingNumber"] == "FST123456789"


def test_e2e_full_demo(api):
    """The 3-5 minute demo, end to end."""
    oid = api.post("/api/orders", json=ORDER).json()["id"]
    rates = api.post(f"/api/orders/{oid}/rates").json()["rates"]
    assert len(rates) == 3
    api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": "FASTSHIP", "service": "FAST-AIR"}).raise_for_status()
    tn = api.post(f"/api/orders/{oid}/shipment").json()["trackingNumber"]
    for st in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"):
        send_event(api, tn, st)
    cid = send_event(api, tn, "NDR", reason="CUSTOMER_UNAVAILABLE")["webhookResponse"]["ndrCaseId"]
    api.post(f"/api/ndr/{cid}/contact").raise_for_status()
    c = api.post(f"/api/ndr/{cid}/message", json={"message": "Yes tomorrow evening after 6"}).json()
    assert c["lastIntent"]["intent"] == "RESCHEDULE_DELIVERY" and c["lastDecision"]["outcome"] == "ALLOWED"
    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "RESOLVED"
    assert c["messages"][-1]["message"] == "The carrier has accepted the reattempt request."
    send_event(api, tn, "DELIVERED")
    t = api.get(f"/api/orders/{oid}/tracking").json()
    assert t["currentStatus"] == "DELIVERED"
    assert [h["status"] for h in t["statusHistory"]] == [
        "SHIPMENT_CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "NDR", "DELIVERED"]
