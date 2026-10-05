from datetime import datetime, timedelta, timezone

from app.db import get_session_factory
from app.models import ShippingQuote
from tests.conftest import book


def _opt(client, order_id, carrier, service):
    opts = client.post(f"/api/orders/{order_id}/rates").json()["shippingOptions"]
    return next(o for o in opts if o["carrierCode"] == carrier and o["serviceCode"] == service)


def _select(client, order_id, carrier, service, amount):
    return client.post(f"/api/orders/{order_id}/select-carrier",
                       json={"carrierCode": carrier, "serviceCode": service, "quotedAmount": amount})


def test_select_carrier_freezes_quote(client, order):
    o = _opt(client, order["id"], "FASTSHIP", "FAST-AIR")
    r = _select(client, order["id"], "FASTSHIP", "FAST-AIR", o["totalCharge"])
    assert r.status_code == 200
    assert r.json()["quotedAmount"] == 195.2 and r.json()["status"] == "CARRIER_SELECTED"
    assert client.get(f"/api/orders/{order['id']}").json()["status"] == "CARRIER_SELECTED"


def test_select_rejects_amount_mismatch(client, order):
    _opt(client, order["id"], "FASTSHIP", "FAST-AIR")
    r = _select(client, order["id"], "FASTSHIP", "FAST-AIR", 100)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "AMOUNT_MISMATCH"


def test_select_requires_quotes_and_known_service(client, order):
    assert _select(client, order["id"], "FASTSHIP", "FAST-AIR", 195.2).json()["detail"]["code"] == "NO_QUOTES"
    _opt(client, order["id"], "FASTSHIP", "FAST-AIR")
    r = _select(client, order["id"], "FASTSHIP", "NOPE", 1)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "QUOTE_NOT_FOUND"


def test_select_rejects_expired_quote(client, order):
    o = _opt(client, order["id"], "FASTSHIP", "FAST-AIR")
    db = get_session_factory()()
    for q in db.query(ShippingQuote).all():
        q.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    r = _select(client, order["id"], "FASTSHIP", "FAST-AIR", o["totalCharge"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "QUOTE_EXPIRED"


def test_select_rejects_quote_from_older_batch(client, order):
    # same params => stored rows differ per batch; make the first batch "older" and still valid
    old = _opt(client, order["id"], "QUICKEXPRESS", "EXPRESS")
    client.post(f"/api/orders/{order['id']}/rates?refresh=true")
    db = get_session_factory()()
    latest_batch = db.query(ShippingQuote).order_by(ShippingQuote.created_at.desc()).first().batch_id
    # drop QuickExpress from the latest batch to model "service no longer offered", keep old row
    db.query(ShippingQuote).filter(ShippingQuote.batch_id == latest_batch, ShippingQuote.carrier_code == "QUICKEXPRESS").delete()
    db.commit()
    r = _select(client, order["id"], "QUICKEXPRESS", "EXPRESS", old["totalCharge"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE_QUOTE"


def test_create_shipment_requires_selection(client, order):
    r = client.post(f"/api/orders/{order['id']}/shipment")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_CARRIER_SELECTED"


def test_shipment_creation_each_carrier(client):
    for carrier, service, prefix in (("FASTSHIP", "FAST-AIR", "FST"), ("QUICKEXPRESS", "EXPRESS", "QE"), ("RELIABLE", "RC-AIR", "RC")):
        oid = client.post("/api/orders", json={
            "customerName": "A", "customerPhone": "9876543210", "pickupPincode": "560001", "deliveryPincode": "500001",
            "weightGrams": 2000, "paymentType": "PREPAID"}).json()["id"]
        s = book(client, oid, carrier, service)
        assert s["carrier"] == carrier and s["status"] == "SHIPMENT_CREATED" and s["tracking_number" if False else "trackingNumber"].startswith(prefix)
        assert client.get(f"/api/orders/{oid}").json()["status"] == "SHIPMENT_CREATED"


def test_shipment_creation_is_idempotent_and_blocks_reselect(client, order):
    s1 = book(client, order["id"])
    assert client.post(f"/api/orders/{order['id']}/shipment").json()["trackingNumber"] == s1["trackingNumber"]
    r = _select(client, order["id"], "FASTSHIP", "FAST-AIR", 195.2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ALREADY_BOOKED"


def test_booking_failure_is_reported_and_retryable(client, order):
    o = _opt(client, order["id"], "FASTSHIP", "FAST-AIR")
    _select(client, order["id"], "FASTSHIP", "FAST-AIR", o["totalCharge"])
    client.put("/mock/fastship/config", params={"failure": "true"})
    r = client.post(f"/api/orders/{order['id']}/shipment")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "CARRIER_ERROR"
    client.put("/mock/fastship/config", params={"failure": "false"})
    assert client.post(f"/api/orders/{order['id']}/shipment").status_code == 200
