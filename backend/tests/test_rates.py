import time

from tests.conftest import ORDER


def test_three_carrier_aggregation(client, order):
    r = client.post(f"/api/orders/{order['id']}/rates")
    assert r.status_code == 200
    body = r.json()
    opts = body["shippingOptions"]
    assert body["failedCarriers"] == [] and body["cached"] is False
    assert [o["serviceCode"] for o in opts] == ["RC-SURFACE", "FAST-AIR", "EXPRESS", "RC-AIR"]
    assert [o["totalCharge"] for o in opts] == [159.3, 195.2, 206.5, 208.9]
    assert {o["carrierCode"] for o in opts} == {"FASTSHIP", "QUICKEXPRESS", "RELIABLE"}
    surface = opts[0]
    assert (surface["baseCharge"], surface["codCharge"], surface["additionalCharges"], surface["tax"]) == (100, 25, 10, 24.3)
    assert (surface["estimatedMinDays"], surface["estimatedMaxDays"]) == (4, 5)
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "QUOTED"


def test_one_carrier_fails_others_continue(client, order):
    client.put("/mock/fastship/config", params={"failure": "true"})
    body = client.post(f"/api/orders/{order['id']}/rates").json()
    assert {o["carrierCode"] for o in body["shippingOptions"]} == {"QUICKEXPRESS", "RELIABLE"}
    assert [f["carrierCode"] for f in body["failedCarriers"]] == ["FASTSHIP"]
    assert "500" in body["failedCarriers"][0]["reason"]


def test_slow_carrier_times_out(client, order):
    client.put("/mock/quickexpress/config", params={"delay": "3000"})
    start = time.time()
    body = client.post(f"/api/orders/{order['id']}/rates").json()
    assert time.time() - start < 2.5  # did not wait the full 3s
    assert [f["carrierCode"] for f in body["failedCarriers"]] == ["QUICKEXPRESS"]
    assert len(body["shippingOptions"]) == 3


def test_all_carriers_down_returns_empty_not_error(client, order):
    for c in ("fastship", "quickexpress", "reliablecourier"):
        client.put(f"/mock/{c}/config", params={"failure": "true"})
    r = client.post(f"/api/orders/{order['id']}/rates")
    assert r.status_code == 200 and r.json()["shippingOptions"] == [] and len(r.json()["failedCarriers"]) == 3


def test_mock_failure_query_param(client):
    assert client.post("/mock/fastship/api/v1/rate?failure=true", json={"weight_kg": 1}).status_code == 500


def test_cache_miss_then_hit_does_not_call_carriers(client, order):
    first = client.post(f"/api/orders/{order['id']}/rates").json()
    assert first["cached"] is False
    # make every carrier fail: a cache hit must not notice
    for c in ("fastship", "quickexpress", "reliablecourier"):
        client.put(f"/mock/{c}/config", params={"failure": "true"})
    second = client.post(f"/api/orders/{order['id']}/rates").json()
    assert second["cached"] is True and second["failedCarriers"] == []
    assert [o["quoteId"] for o in second["shippingOptions"]] == [o["quoteId"] for o in first["shippingOptions"]]


def test_cache_key_and_ttl(client, order):
    client.post(f"/api/orders/{order['id']}/rates")
    keys = client.portal.call(client.redis.keys, "zippy:rates:*")
    assert keys == ["zippy:rates:MRC-100:560001:500001:2000:20:15:10:COD:2000"]
    ttl = client.portal.call(client.redis.ttl, keys[0])
    assert 0 < ttl <= 300


def test_refresh_bypasses_cache(client, order):
    first = client.post(f"/api/orders/{order['id']}/rates").json()
    second = client.post(f"/api/orders/{order['id']}/rates?refresh=true").json()
    assert second["cached"] is False
    assert {o["quoteId"] for o in second["shippingOptions"]}.isdisjoint({o["quoteId"] for o in first["shippingOptions"]})


def test_same_params_other_order_uses_cache(client, order):
    client.post(f"/api/orders/{order['id']}/rates")
    other = client.post("/api/orders", json=ORDER).json()
    r = client.post(f"/api/orders/{other['id']}/rates").json()
    assert r["cached"] is True and len(r["shippingOptions"]) == 4  # quotes materialised for the new order


def test_partial_results_are_not_cached(client, order):
    client.put("/mock/fastship/config", params={"failure": "true"})
    client.post(f"/api/orders/{order['id']}/rates")
    client.put("/mock/fastship/config", params={"failure": "false"})
    r = client.post(f"/api/orders/{order['id']}/rates").json()
    assert r["cached"] is False and len(r["shippingOptions"]) == 4


def test_get_rates_returns_stored_quotes(client, order):
    assert client.get(f"/api/orders/{order['id']}/rates").json()["shippingOptions"] == []
    client.post(f"/api/orders/{order['id']}/rates")
    assert len(client.get(f"/api/orders/{order['id']}/rates").json()["shippingOptions"]) == 4
