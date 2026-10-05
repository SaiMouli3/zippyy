from tests.conftest import book


def _next(client, carrier_slug, tracking, **params):
    r = client.post(f"/mock/{carrier_slug}/shipments/{tracking}/next-status", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _history(client, order_id):
    return [h["status"] for h in client.get(f"/api/orders/{order_id}/tracking").json()["history"]]


def test_tracking_before_shipment_is_404(client, order):
    assert client.get(f"/api/orders/{order['id']}/tracking").status_code == 404


def test_next_status_sends_webhook_and_updates_tracking(client, order):
    s = book(client, order["id"])
    out = _next(client, "fastship", s["trackingNumber"])
    assert out["status"] == "PICKED_UP" and out["deliveries"][0]["body"]["outcome"] == "applied"
    t = client.get(f"/api/orders/{order['id']}/tracking").json()
    assert t["currentStatus"] == "PICKED_UP" and [h["status"] for h in t["history"]] == ["SHIPMENT_CREATED", "PICKED_UP"]


def test_duplicate_webhook_creates_one_event(client, order):
    s = book(client, order["id"])
    out = _next(client, "fastship", s["trackingNumber"], duplicate="true")
    assert [d["body"]["outcome"] for d in out["deliveries"]] == ["applied", "duplicate"]
    assert _history(client, order["id"]) == ["SHIPMENT_CREATED", "PICKED_UP"]
    # replaying the exact payload later is also a no-op
    again = client.post("/api/webhooks/fastship", json=out["webhookPayload"]).json()
    assert again["outcome"] == "duplicate"
    assert _history(client, order["id"]) == ["SHIPMENT_CREATED", "PICKED_UP"]


def test_status_regression_is_rejected(client, order):
    s = book(client, order["id"])
    tn = s["trackingNumber"]
    for _ in range(4):
        _next(client, "fastship", tn)  # -> DELIVERED
    assert client.get(f"/api/orders/{order['id']}/tracking").json()["currentStatus"] == "DELIVERED"
    stale = {"event_id": "late-1", "tracking_number": tn, "status": "IN_TRANSIT", "timestamp": "2026-01-01T00:00:00+00:00"}
    r = client.post("/api/webhooks/fastship", json=stale)
    assert r.status_code == 200 and r.json()["outcome"] == "ignored"
    t = client.get(f"/api/orders/{order['id']}/tracking").json()
    assert t["currentStatus"] == "DELIVERED" and len(t["history"]) == 5
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "DELIVERED"


def test_full_lifecycle_each_carrier_vocabulary(client):
    for carrier, service, slug in (("QUICKEXPRESS", "EXPRESS", "quickexpress"), ("RELIABLE", "RC-SURFACE", "reliablecourier")):
        oid = client.post("/api/orders", json={
            "customerName": "A", "customerPhone": "9876543210", "pickupPincode": "560001", "deliveryPincode": "500001",
            "weightGrams": 1000, "paymentType": "PREPAID"}).json()["id"]
        tn = book(client, oid, carrier, service)["trackingNumber"]
        for _ in range(4):
            _next(client, slug, tn)
        assert _history(client, oid) == ["SHIPMENT_CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
        assert client.post(f"/mock/{slug}/shipments/{tn}/next-status").status_code == 409  # nothing after DELIVERED


def test_delivery_failed_then_retry_then_rto(client, order):
    tn = book(client, order["id"])["trackingNumber"]
    for _ in range(3):
        _next(client, "fastship", tn)
    _next(client, "fastship", tn, event="delivery_failed")
    assert _history(client, order["id"])[-1] == "DELIVERY_FAILED"
    _next(client, "fastship", tn, event="rto")
    t = client.get(f"/api/orders/{order['id']}/tracking").json()
    assert t["currentStatus"] == "RTO"


def test_webhook_for_unknown_shipment_and_bad_payload(client):
    r = client.post("/api/webhooks/fastship", json={"event_id": "x", "tracking_number": "NOPE", "status": "BOOKED",
                                                    "timestamp": "2026-01-01T00:00:00+00:00"})
    assert r.status_code == 404
    assert client.post("/api/webhooks/quickexpress", json={"foo": "bar"}).status_code == 422


def test_next_status_unknown_tracking(client):
    assert client.post("/mock/fastship/shipments/NOPE/next-status").status_code == 404
    assert client.get("/mock/shipments").json() == []
