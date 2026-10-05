import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["CARRIER_RATE_TIMEOUT_SECONDS"] = "0.5"

import fakeredis.aioredis  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.http as http_module  # noqa: E402
from app import cache  # noqa: E402
from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.mock_carriers import common as mock_state  # noqa: E402

ORDER = {
    "merchantId": "MRC-100",
    "customerName": "Asha Rao",
    "customerPhone": "9876543210",
    "pickupPincode": "560001",
    "deliveryPincode": "500001",
    "weightGrams": 2000,
    "lengthCm": 20,
    "widthCm": 15,
    "heightCm": 10,
    "paymentType": "COD",
    "codAmount": 2000,
}


@pytest.fixture
def client(monkeypatch):
    """The whole app in-process: carriers are called over ASGI, Redis is fakeredis, DB is SQLite."""
    from app import models  # noqa: F401

    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    mock_state.reset_state()
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache.set_redis(fake)
    monkeypatch.setattr(
        http_module, "make_client",
        lambda base_url, timeout=5.0: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"),
    )
    with TestClient(app) as c:
        c.redis = fake
        yield c


@pytest.fixture
def order(client):
    r = client.post("/api/orders", json=ORDER)
    assert r.status_code == 201, r.text
    return r.json()


def book(client, order_id, carrier="FASTSHIP", service="FAST-AIR"):
    """Fetch rates, select, create shipment. Returns shipment JSON."""
    rates = client.post(f"/api/orders/{order_id}/rates").json()
    opt = next(o for o in rates["shippingOptions"] if o["carrierCode"] == carrier and o["serviceCode"] == service)
    r = client.post(
        f"/api/orders/{order_id}/select-carrier",
        json={"carrierCode": carrier, "serviceCode": service, "quotedAmount": opt["totalCharge"]},
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/orders/{order_id}/shipment")
    assert r.status_code == 200, r.text
    return r.json()
