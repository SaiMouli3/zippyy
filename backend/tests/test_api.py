import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from app import config
from app.services import rates as rates_service

from .conftest import ORDER, new_order_body, send_event

R = redis.Redis.from_url(os.environ["REDIS_URL"])
KEY = "zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500"


def carrier_calls(logs, op="RATE_REQUEST"):
    return [r for r in logs if r.get("event") == "CARRIER_CALL" and r.get("operation") == op]


@pytest.fixture
def fault(api):
    """Inject carrier faults; always reset afterwards."""
    def set_(carrier, **kw):
        api.post("/mock/_control/failures", json={"carrier": carrier, **kw}).raise_for_status()
    yield set_
    for c in ("fastship", "quickexpress", "reliable"):
        api.post("/mock/_control/failures", json={"carrier": c, "fail": False, "delayMs": 0})


def mk_shipment(api, carrier="FASTSHIP", service="FAST-AIR", **over):
    oid = api.post("/api/orders", json=new_order_body(**over)).json()["id"]
    api.post(f"/api/orders/{oid}/rates").raise_for_status()
    api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": carrier, "service": service}).raise_for_status()
    s = api.post(f"/api/orders/{oid}/shipment")
    assert s.status_code == 201, s.text
    return oid, s.json()["trackingNumber"]


# ------------------------------------------------------------------ orders
def test_order_creation(api):
    r = api.post("/api/orders", json=new_order_body())
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("ZPY-ORD-") and body["status"] == "CREATED" and body["codAmount"] == 2500
    assert body["duplicate"] is False and body["weightGrams"] == 1500 and body["lengthCm"] == 20
    assert api.get(f"/api/orders/{body['id']}").json()["customerName"] == "Rahul Sharma"


def test_order_validation(api):
    assert api.post("/api/orders", json=new_order_body(phone="123")).status_code == 422
    assert api.post("/api/orders", json=new_order_body(codAmount=0)).status_code == 422
    assert api.post("/api/orders", json=new_order_body(lengthCm=0)).status_code == 422
    assert api.get("/api/orders/NOPE").status_code == 404


def test_order_idempotency_same_merchant_order_id(api):
    body = new_order_body()
    first = api.post("/api/orders", json=body)
    second = api.post("/api/orders", json=body)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"] and second.json()["duplicate"] is True
    assert len([o for o in api.get("/api/orders").json() if o["merchantOrderId"] == body["merchantOrderId"]]) == 1


def test_order_idempotency_conflicting_payload(api):
    body = new_order_body()
    first = api.post("/api/orders", json=body).json()
    r = api.post("/api/orders", json={**body, "weightGrams": 9999})
    assert r.status_code == 409
    assert r.json()["existingOrderId"] == first["id"] and "weight_grams" in r.json()["differingFields"]


def test_order_idempotency_is_per_merchant(api):
    body = new_order_body()
    a = api.post("/api/orders", json=body).json()
    b = api.post("/api/orders", json={**body, "merchantId": "MRC-200"})
    assert b.status_code == 201 and b.json()["id"] != a["id"]


def test_order_idempotency_under_concurrency(api):
    body = new_order_body()
    with ThreadPoolExecutor(6) as ex:
        rs = list(ex.map(lambda _: api.post("/api/orders", json=body), range(6)))
    assert {r.status_code for r in rs} <= {200, 201} and sum(r.status_code == 201 for r in rs) == 1
    assert len({r.json()["id"] for r in rs}) == 1


# ------------------------------------------------------------------- rates
def test_rates_normalized_and_cache_miss_then_hit(api, order, logs):
    oid = order["id"]
    r = api.post(f"/api/orders/{oid}/rates").json()
    assert r["cached"] is False and r["cacheStatus"] == "MISS" and r["errors"] == [] and r["partial"] is False
    assert r["cacheKey"] == KEY
    by = {x["carrier"]: x for x in r["rates"]}
    assert set(by) == {"FASTSHIP", "QUICKEXPRESS", "RELIABLECOURIER"}
    assert (by["FASTSHIP"]["price"], by["QUICKEXPRESS"]["price"], by["RELIABLECOURIER"]["price"]) == (182.9, 197.06, 159.3)
    assert set(by["FASTSHIP"]) == {"carrier", "carrierName", "service", "serviceName", "price", "etaMinDays", "etaMaxDays"}
    assert len(carrier_calls(logs)) == 3
    assert 0 < R.ttl(KEY) <= config.RATE_CACHE_TTL

    logs.clear()
    hit = api.get(f"/api/orders/{oid}/rates").json()
    assert hit["cached"] is True and hit["cacheStatus"] == "HIT" and hit["rates"] == r["rates"]
    assert carrier_calls(logs) == []  # cache hit: zero carrier calls


def test_cache_shared_between_orders_with_identical_pricing_inputs(api, order, logs):
    api.post(f"/api/orders/{order['id']}/rates")
    other = api.post("/api/orders", json=new_order_body()).json()
    logs.clear()
    r = api.post(f"/api/orders/{other['id']}/rates").json()
    assert r["cached"] is True and carrier_calls(logs) == []
    # ...and the second order can still select from its own stored quotes
    assert api.post(f"/api/orders/{other['id']}/select-carrier",
                    json={"carrier": "RELIABLECOURIER", "service": "RC-SURFACE"}).status_code == 200


def test_refresh_bypasses_and_replaces_cache(api, order, logs):
    oid = order["id"]
    api.post(f"/api/orders/{oid}/rates")
    logs.clear()
    r = api.get(f"/api/orders/{oid}/rates?refresh=true").json()
    assert r["cached"] is False and r["cacheStatus"] == "REFRESH" and len(carrier_calls(logs)) == 3
    assert R.exists(KEY)
    assert api.get(f"/api/orders/{oid}/rates").json()["cached"] is True


def test_cache_expiry(api, order, monkeypatch, logs):
    monkeypatch.setattr(config, "RATE_CACHE_TTL", 1)
    oid = order["id"]
    api.post(f"/api/orders/{oid}/rates")
    assert api.post(f"/api/orders/{oid}/rates").json()["cached"] is True
    time.sleep(1.3)
    logs.clear()
    r = api.post(f"/api/orders/{oid}/rates").json()
    assert r["cached"] is False and len(carrier_calls(logs)) == 3


@pytest.mark.parametrize("field,value", [
    ("pickupPincode", "560002"), ("deliveryPincode", "400001"), ("weightGrams", 2000), ("lengthCm", 30),
    ("widthCm", 16), ("heightCm", 11), ("paymentMode", "PREPAID"), ("codAmount", 2600), ("merchantId", "MRC-200")])
def test_changed_pricing_input_changes_cache_key(api, order, field, value):
    base = api.post(f"/api/orders/{order['id']}/rates").json()["cacheKey"]
    other = api.post("/api/orders", json=new_order_body(**{field: value})).json()
    r = api.post(f"/api/orders/{other['id']}/rates").json()
    assert r["cacheKey"] != base and r["cached"] is False
    assert R.exists(base) and R.exists(r["cacheKey"])


def test_pricing_inputs_actually_change_prices(api, order):
    base = {x["carrier"]: x["price"] for x in api.post(f"/api/orders/{order['id']}/rates").json()["rates"]}
    heavy = api.post("/api/orders", json=new_order_body(weightGrams=3000)).json()
    new = {x["carrier"]: x["price"] for x in api.post(f"/api/orders/{heavy['id']}/rates").json()["rates"]}
    assert all(new[c] > base[c] for c in base)
    bulky = api.post("/api/orders", json=new_order_body(lengthCm=60, widthCm=40, heightCm=30)).json()  # volumetric
    vol = {x["carrier"]: x["price"] for x in api.post(f"/api/orders/{bulky['id']}/rates").json()["rates"]}
    assert all(vol[c] > base[c] for c in base)


def test_partial_failure_returns_others_and_caches_with_short_ttl(api, order, fault):
    oid = order["id"]
    fault("quickexpress", fail=True)
    body = api.post(f"/api/orders/{oid}/rates").json()
    assert {x["carrier"] for x in body["rates"]} == {"FASTSHIP", "RELIABLECOURIER"} and body["partial"] is True
    err = body["errors"][0]
    assert err["carrier"] == "QUICKEXPRESS" and err["code"] == "HTTP_ERROR" and "503" in err["message"]
    assert 0 < R.ttl(KEY) <= config.PARTIAL_RATE_CACHE_TTL < config.RATE_CACHE_TTL
    hit = api.post(f"/api/orders/{oid}/rates").json()
    assert hit["cached"] is True and hit["partial"] is True and hit["errors"][0]["carrier"] == "QUICKEXPRESS"
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "QUICKEXPRESS", "service": "EXPRESS"}).status_code == 400
    # carrier recovers: explicit refresh gives the complete result and upgrades the TTL
    fault("quickexpress", fail=False)
    full = api.post(f"/api/orders/{oid}/rates?refresh=true").json()
    assert len(full["rates"]) == 3 and full["partial"] is False and R.ttl(KEY) > config.PARTIAL_RATE_CACHE_TTL


def test_partial_result_expires_quickly_then_recovers(api, order, fault, monkeypatch):
    monkeypatch.setattr(config, "PARTIAL_RATE_CACHE_TTL", 1)
    fault("reliable", fail=True)
    assert api.post(f"/api/orders/{order['id']}/rates").json()["partial"] is True
    fault("reliable", fail=False)
    time.sleep(1.3)
    again = api.post(f"/api/orders/{order['id']}/rates").json()
    assert again["cached"] is False and len(again["rates"]) == 3


def test_carrier_timeout(api, order, fault, monkeypatch, logs):
    monkeypatch.setattr(config, "CARRIER_TIMEOUT_MS", 500)
    fault("quickexpress", delayMs=5000)
    t0 = time.perf_counter()
    r = api.post(f"/api/orders/{order['id']}/rates")
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200 and elapsed < 2.5, elapsed   # did not wait for the 5s carrier
    body = r.json()
    assert {x["carrier"] for x in body["rates"]} == {"FASTSHIP", "RELIABLECOURIER"}
    err = body["errors"][0]
    assert err["carrier"] == "QUICKEXPRESS" and err["code"] == "TIMEOUT" and 400 < err["durationMs"] < 2500
    assert any(l.get("event") == "CARRIER_CALL_FAILED" and l.get("code") == "TIMEOUT" for l in logs)


def test_all_carriers_failing_returns_502_with_details(api, order, fault):
    for c in ("fastship", "quickexpress", "reliable"):
        fault(c, fail=True)
    r = api.post(f"/api/orders/{order['id']}/rates")
    assert r.status_code == 502 and len(r.json()["errors"]) == 3
    assert not R.exists(KEY)


def test_redis_failure_falls_back_to_carriers(api, order, monkeypatch, logs):
    monkeypatch.setattr(rates_service, "_redis", redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2))
    r = api.post(f"/api/orders/{order['id']}/rates")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rates"]) == 3 and body["cacheStatus"] == "UNAVAILABLE" and body["cached"] is False
    assert any(l.get("event") == "CACHE_UNAVAILABLE" and l.get("level", "warning") for l in logs)
    # selection still works because quotes live in Postgres
    assert api.post(f"/api/orders/{order['id']}/select-carrier",
                    json={"carrier": "FASTSHIP", "service": "FAST-AIR"}).status_code == 200


# --------------------------------------------------------------- selection
def test_select_carrier(api, order):
    oid = order["id"]
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "FASTSHIP", "service": "FAST-AIR"}).status_code == 400   # no quotes yet
    api.post(f"/api/orders/{oid}/rates")
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "FASTSHIP", "service": "NOT-A-SERVICE"}).status_code == 400
    assert api.post(f"/api/orders/{oid}/select-carrier",
                    json={"carrier": "NOPE", "service": "X"}).status_code == 400
    r = api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": "FASTSHIP", "service": "FAST-AIR"})
    assert r.status_code == 200
    assert (r.json()["selectedCarrier"], r.json()["selectedService"], r.json()["quotedPrice"]) == ("FASTSHIP", "FAST-AIR", 182.9)


def test_quoted_amount_cannot_be_modified(api, order):
    oid = order["id"]
    api.post(f"/api/orders/{oid}/rates")
    bad = api.post(f"/api/orders/{oid}/select-carrier",
                   json={"carrier": "FASTSHIP", "service": "FAST-AIR", "price": 1.0})
    assert bad.status_code == 409 and bad.json()["quotedPrice"] == 182.9
    assert api.get(f"/api/orders/{oid}").json()["quotedPrice"] is None
    ok = api.post(f"/api/orders/{oid}/select-carrier",
                  json={"carrier": "FASTSHIP", "service": "FAST-AIR", "price": 182.9})
    assert ok.status_code == 200 and ok.json()["quotedPrice"] == 182.9
    # extra/unknown price-like fields never override the stored quote
    sneaky = api.post(f"/api/orders/{oid}/select-carrier",
                      json={"carrier": "FASTSHIP", "service": "FAST-AIR", "quotedPrice": 1.0})
    assert sneaky.json()["quotedPrice"] == 182.9
    # quotes frozen once shipped: refresh can no longer alter what was bought
    api.post(f"/api/orders/{oid}/shipment").raise_for_status()
    api.post(f"/api/orders/{oid}/rates?refresh=true")
    assert api.get(f"/api/orders/{oid}").json()["quotedPrice"] == 182.9


def test_concurrent_rate_requests(api, order):
    with ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(lambda _: api.post(f"/api/orders/{order['id']}/rates?refresh=true"), range(4)))
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]


# ---------------------------------------------------------------- shipments
def test_shipment_creation_each_carrier_contract(api):
    for carrier, service, prefix in [("FASTSHIP", "FAST-AIR", "FST"), ("QUICKEXPRESS", "EXPRESS", "QXP"),
                                     ("RELIABLECOURIER", "RC-SURFACE", "RLC")]:
        oid = api.post("/api/orders", json=new_order_body()).json()["id"]
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


# ------------------------------------------------------------------ webhooks
def test_webhooks_each_carrier_vocabulary(api):
    for carrier, service, slug in [("QUICKEXPRESS", "EXPRESS", "quickexpress"),
                                   ("RELIABLECOURIER", "RC-SURFACE", "reliable")]:
        oid, tn = mk_shipment(api, carrier, service)
        for st in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"):
            send_event(api, tn, st, slug=slug)
        send_event(api, tn, "NDR", slug=slug, reason="COD_NOT_READY")
        assert api.get(f"/api/orders/{oid}/tracking").json()["currentStatus"] == "NDR"
        case = next(c for c in api.get("/api/ndr").json() if c["orderId"] == oid)
        assert case["reason"] == "COD_NOT_READY"


def test_raw_and_normalized_event_both_stored(api, shipped):
    send_event(api, shipped["tracking"], "PICKED_UP", eventId="evt-raw")
    ev = api.get(f"/api/orders/{shipped['orderId']}/tracking?includeRaw=true").json()["statusHistory"][-1]
    assert ev["raw"] == {"trackingNumber": shipped["tracking"], "status": "PKD", "eventId": "evt-raw"}   # carrier's own shape
    assert ev["normalized"] == {"carrier": "FASTSHIP", "trackingNumber": shipped["tracking"],
                                "status": "PICKED_UP", "eventId": "evt-raw", "reason": None}


def test_duplicate_webhook_creates_one_event(api, shipped):
    t, oid = shipped["tracking"], shipped["orderId"]
    first = send_event(api, t, "PICKED_UP", eventId="evt-1")
    second = send_event(api, t, "PICKED_UP", eventId="evt-1")
    assert first["webhookResponse"]["duplicate"] is False and second["webhookResponse"]["duplicate"] is True
    assert second["webhookStatus"] == 200
    assert [h["status"] for h in api.get(f"/api/orders/{oid}/tracking").json()["statusHistory"]] == \
        ["SHIPMENT_CREATED", "PICKED_UP"]


def test_duplicate_webhook_concurrent(api, shipped):
    payload = {"trackingNumber": shipped["tracking"], "status": "PKD", "eventId": "race"}
    with ThreadPoolExecutor(6) as ex:
        rs = list(ex.map(lambda _: api.post("/api/webhooks/fastship", json=payload), range(6)))
    assert all(r.status_code == 200 for r in rs) and sum(not r.json()["duplicate"] for r in rs) == 1
    assert len(api.get(f"/api/orders/{shipped['orderId']}/tracking").json()["statusHistory"]) == 2


def test_unknown_tracking_number_is_quarantined(api):
    before = api.get("/api/shipments").json()
    payload = {"trackingNumber": "FST000UNKNOWN", "status": "PKD", "eventId": "u1"}
    r = api.post("/api/webhooks/fastship", json=payload)
    assert r.status_code == 202 and r.json()["status"] == "quarantined" and r.json()["reason"] == "UNKNOWN_TRACKING_NUMBER"
    assert api.get("/api/shipments").json() == before            # nothing created
    q = [x for x in api.get("/api/webhook-quarantine").json() if x["trackingNumber"] == "FST000UNKNOWN"]
    assert q and q[0]["raw"] == payload and q[0]["normalized"]["status"] == "PICKED_UP"


def test_unparseable_webhook_is_stored(api):
    r = api.post("/api/webhooks/fastship", json={"nope": 1})
    assert r.status_code == 400 and r.json()["reason"] == "UNPARSEABLE_PAYLOAD"
    assert any(x["reason"] == "UNPARSEABLE_PAYLOAD" and x["raw"] == {"nope": 1}
               for x in api.get("/api/webhook-quarantine").json())
    assert api.post("/api/webhooks/unknown", json={}).status_code == 404


def test_status_regression_is_rejected(api, shipped):
    t, oid = shipped["tracking"], shipped["orderId"]
    for st in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"):
        send_event(api, t, st)
    for bad in ("IN_TRANSIT", "PICKED_UP", "NDR", "OUT_FOR_DELIVERY"):
        r = send_event(api, t, bad)
        assert r["webhookStatus"] == 202
        assert r["webhookResponse"]["reason"] == "INVALID_TRANSITION"
        assert r["webhookResponse"]["currentStatus"] == "DELIVERED"
    tr = api.get(f"/api/orders/{oid}/tracking").json()
    assert tr["currentStatus"] == "DELIVERED"
    assert [h["status"] for h in tr["statusHistory"]] == ["SHIPMENT_CREATED", "PICKED_UP", "IN_TRANSIT",
                                                         "OUT_FOR_DELIVERY", "DELIVERED"]
    assert api.get(f"/api/orders/{oid}").json()["shipment"]["status"] == "DELIVERED"
    q = [x for x in api.get("/api/webhook-quarantine").json()
         if x["trackingNumber"] == t and x["reason"] == "INVALID_TRANSITION"]
    assert len(q) == 4 and q[0]["detail"]["from"] == "DELIVERED" and q[0]["raw"]["trackingNumber"] == t


def test_same_status_new_event_id_is_not_a_second_transition(api, shipped):
    send_event(api, shipped["tracking"], "PICKED_UP", eventId="a")
    r = send_event(api, shipped["tracking"], "PICKED_UP", eventId="b")
    assert r["webhookResponse"]["reason"] == "INVALID_TRANSITION"
    assert len(api.get(f"/api/orders/{shipped['orderId']}/tracking").json()["statusHistory"]) == 2


# ----------------------------------------------------------------------- NDR
def test_ndr_creation(api, ndr_case):
    c = api.get(f"/api/ndr/{ndr_case['caseId']}").json()
    assert c["reason"] == "CUSTOMER_UNAVAILABLE" and c["attemptNumber"] == 1 and c["status"] == "OPEN"
    assert c["shipmentStatus"] == "NDR" and c["customerName"] == "Rahul Sharma"
    assert any(x["id"] == c["id"] for x in api.get("/api/ndr").json())
    assert "NDR_CREATED" in [a["event"] for a in c["audit"]]


def test_reattempt_flow(api, ndr_case):
    cid = ndr_case["caseId"]
    assert api.post(f"/api/ndr/{cid}/reattempt").status_code == 409     # nothing to act on yet

    c = api.post(f"/api/ndr/{cid}/contact").json()
    assert c["messages"][0]["sender"] == "AGENT"
    assert len(api.post(f"/api/ndr/{cid}/contact").json()["messages"]) == 1

    c = api.post(f"/api/ndr/{cid}/message", json={"message": "Yes tomorrow evening after 6"}).json()
    assert c["lastIntent"]["intent"] == "RESCHEDULE_DELIVERY"
    assert c["lastDecision"]["outcome"] == "ALLOWED" and c["status"] == "OPEN"
    agent_texts = [m["message"] for m in c["messages"] if m["sender"] == "AGENT"]
    assert not any("accepted" in t or "confirmed" in t for t in agent_texts)

    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "RESOLVED" and c["actions"][0]["status"] == "CARRIER_ACCEPTED"
    texts = [m["message"] for m in c["messages"] if m["sender"] == "AGENT"]
    assert texts.index("Your reattempt request has been submitted to the carrier.") < \
        texts.index("The carrier has accepted the reattempt request.")
    events = [a["event"] for a in c["audit"]]
    assert events.index("CARRIER_ACTION_SUBMITTED") < events.index("CARRIER_ACTION_ACCEPTED")
    for e in ("BUYER_MESSAGE_RECEIVED", "INTENT_EXTRACTED"):
        assert e in events
    assert api.post(f"/api/ndr/{cid}/reattempt").status_code == 409


def test_reattempt_blocked_by_rules(api, ndr_case):
    cid = ndr_case["caseId"]
    c = api.post(f"/api/ndr/{cid}/message", json={"message": "my address is wrong"}).json()
    assert c["lastDecision"]["outcome"] == "REQUIRES_APPROVAL" and c["status"] == "NEEDS_APPROVAL"
    r = api.post(f"/api/ndr/{cid}/reattempt")
    assert r.status_code == 409 and r.json()["decision"]["outcome"] == "REQUIRES_APPROVAL"
    assert api.get(f"/api/ndr/{cid}").json()["actions"] == []       # carrier never called


def test_reattempt_carrier_rejection_never_claims_acceptance(api, ndr_case):
    t = ndr_case["tracking"]
    for _ in range(2):                          # attempts 2 and 3 (each needs a fresh out-for-delivery)
        send_event(api, t, "OUT_FOR_DELIVERY")
        cid = send_event(api, t, "NDR")["webhookResponse"]["ndrCaseId"]
    assert api.get(f"/api/ndr/{cid}").json()["attemptNumber"] == 3
    api.post(f"/api/ndr/{cid}/message", json={"message": "come tomorrow"})
    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "ACTION_FAILED" and c["actions"][0]["status"] == "REJECTED"
    assert not any("has accepted" in m["message"] for m in c["messages"])


def test_reattempt_when_carrier_times_out(api, ndr_case, fault, monkeypatch):
    monkeypatch.setattr(config, "CARRIER_TIMEOUT_MS", 400)
    cid = ndr_case["caseId"]
    api.post(f"/api/ndr/{cid}/message", json={"message": "come tomorrow"})
    fault("fastship", delayMs=3000)
    c = api.post(f"/api/ndr/{cid}/reattempt").json()
    assert c["status"] == "ACTION_FAILED"
    assert not any("has accepted" in m["message"] for m in c["messages"])


# --------------------------------------------------------- platform concerns
def test_structured_logs_carry_context(api, logs):
    r = api.post("/api/orders", json=new_order_body(), headers={"X-Request-ID": "req-test-123"})
    assert r.headers["x-request-id"] == "req-test-123"
    oid = r.json()["id"]
    api.post(f"/api/orders/{oid}/rates", headers={"X-Request-ID": "req-test-123"})
    mine = [l for l in logs if l["requestId"] == "req-test-123"]
    created = next(l for l in mine if l["event"] == "ORDER_CREATED")
    assert created["orderId"] == oid
    rate_calls = [l for l in mine if l["event"] == "CARRIER_CALL" and l["operation"] == "RATE_REQUEST"]
    assert {l["carrier"] for l in rate_calls} == {"FASTSHIP", "QUICKEXPRESS", "RELIABLECOURIER"}  # requestId survives worker threads
    assert all(l["orderId"] == oid for l in rate_calls)
    assert any(l["event"] == "RATE_REQUEST" and l["orderId"] == oid for l in mine)
    assert api.get("/api/health").headers["x-request-id"].startswith("req-")


def test_shipment_and_webhook_logs_have_shipment_id(api, logs):
    oid, tn = mk_shipment(api)
    send_event(api, tn, "PICKED_UP")
    ev = next(l for l in logs if l["event"] == "SHIPMENT_STATUS_UPDATED" and l["orderId"] == oid)
    assert ev["carrier"] == "FASTSHIP" and isinstance(ev["shipmentId"], int)
    assert any(l["event"] == "SHIPMENT_CREATED" and l["orderId"] == oid and l["shipmentId"] == ev["shipmentId"] for l in logs)


def test_openapi_and_swagger_available(api):
    docs = api.get("/docs")
    assert docs.status_code == 200 and "/static/swagger-ui/swagger-ui-bundle.js" in docs.text and "cdn" not in docs.text
    assert api.get("/static/swagger-ui/swagger-ui-bundle.js").status_code == 200
    spec = api.get("/openapi.json").json()
    paths = spec["paths"]
    for p in ["/api/orders", "/api/orders/{order_id}", "/api/orders/{order_id}/rates",
              "/api/orders/{order_id}/select-carrier", "/api/orders/{order_id}/shipment",
              "/api/orders/{order_id}/tracking", "/api/webhooks/{carrier}", "/api/webhook-quarantine",
              "/api/ndr", "/api/ndr/{case_id}", "/api/ndr/{case_id}/message", "/api/ndr/{case_id}/reattempt",
              "/api/mock/{slug}/{tracking}/event"]:
        assert p in paths, p
    post_orders = paths["/api/orders"]["post"]
    assert {"201", "200", "409", "422"} <= set(post_orders["responses"])
    assert "examples" in spec["components"]["schemas"]["OrderIn"]
    assert "examples" in spec["components"]["schemas"]["RatesOut"]
    assert "example" in paths["/api/orders/{order_id}/rates"]["post"]["responses"]["502"]["content"]["application/json"]
    assert "examples" in paths["/api/webhooks/{carrier}"]["post"]["requestBody"]["content"]["application/json"]


def test_dashboard(api):
    d = api.get("/api/dashboard").json()
    assert d["totals"]["orders"] >= 1 and "recentShipments" in d and "recentNdr" in d


def test_seed_data(api):
    o = api.get("/api/orders/ZPY-ORD-10001").json()
    assert o["customerName"] == "Rahul Sharma" and o["shipment"]["trackingNumber"] == "FST123456789"
    assert o["merchantOrderId"] == "DEMO-1001" and o["weightGrams"] == 1500


def test_e2e_full_demo(api):
    """The 3-5 minute demo, end to end."""
    body = new_order_body()
    oid = api.post("/api/orders", json=body).json()["id"]
    assert api.post("/api/orders", json=body).json()["id"] == oid                 # idempotent
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
