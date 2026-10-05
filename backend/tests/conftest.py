import os
import socket
import threading
import time

import httpx
import psycopg
import pytest

PORT = 8765
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/zippy_test"),
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
    "CARRIER_BASE_URL": f"http://127.0.0.1:{PORT}",
    "WEBHOOK_BASE_URL": f"http://127.0.0.1:{PORT}",
    # set explicitly so a surrounding environment (e.g. the compose container) cannot redirect the test carriers
    "FASTSHIP_BASE_URL": f"http://127.0.0.1:{PORT}/mock/fastship",
    "QUICKEXPRESS_BASE_URL": f"http://127.0.0.1:{PORT}/mock/quickexpress",
    "RELIABLE_BASE_URL": f"http://127.0.0.1:{PORT}/mock/reliable",
    "SEED_DEMO": "true",
})


def _reset_db():
    admin = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS zippy_test WITH (FORCE)")
        c.execute("CREATE DATABASE zippy_test")


@pytest.fixture(scope="session")
def server():
    """Real uvicorn server so adapters -> mock carriers -> webhooks run over actual HTTP."""
    _reset_db()
    import redis
    redis.Redis.from_url(os.environ["REDIS_URL"]).flushdb()
    import uvicorn
    from app.main import app
    srv = uvicorn.Server(uvicorn.Config(app, port=PORT, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    yield
    srv.should_exit = True
    t.join(5)


@pytest.fixture(scope="session")
def api(server):
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=15) as c:
        yield c


import uuid

ORDER = {"merchantId": "MRC-100", "customerName": "Rahul Sharma", "phone": "9876543210",
         "address": "12 MG Road, Delhi", "pickupPincode": "560001", "deliveryPincode": "110001",
         "weightGrams": 1500, "lengthCm": 20, "widthCm": 15, "heightCm": 10,
         "paymentMode": "COD", "codAmount": 2500}


def new_order_body(**over):
    return {**ORDER, "merchantOrderId": f"T-{uuid.uuid4().hex[:10]}", **over}


@pytest.fixture(autouse=True)
def _clean_redis(server):
    import redis
    redis.Redis.from_url(os.environ["REDIS_URL"]).flushdb()


@pytest.fixture
def logs(server):
    """Captures structured log records emitted by the app (same process as the test server)."""
    import logging
    records = []

    class H(logging.Handler):
        def emit(self, record):
            from app.logs import request_id_var
            records.append({"requestId": request_id_var.get(), **getattr(record, "fields", {})})

    h = H()
    logging.getLogger("zippy").addHandler(h)
    yield records
    logging.getLogger("zippy").removeHandler(h)


@pytest.fixture
def order(api):
    r = api.post("/api/orders", json=new_order_body())
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def shipped(api, order):
    """Order with carrier selected + shipment created (FastShip)."""
    oid = order["id"]
    api.post(f"/api/orders/{oid}/rates").raise_for_status()
    api.post(f"/api/orders/{oid}/select-carrier", json={"carrier": "FASTSHIP", "service": "FAST-AIR"}).raise_for_status()
    s = api.post(f"/api/orders/{oid}/shipment")
    assert s.status_code == 201, s.text
    return {"orderId": oid, "tracking": s.json()["trackingNumber"], "shipment": s.json()}


def send_event(api, tracking, status, slug="fastship", **kw):
    r = api.post(f"/api/mock/{slug}/{tracking}/event", json={"status": status, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def ndr_case(api, shipped):
    for st in ("PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"):
        send_event(api, shipped["tracking"], st)
    res = send_event(api, shipped["tracking"], "NDR", reason="CUSTOMER_UNAVAILABLE")
    return {**shipped, "caseId": res["webhookResponse"]["ndrCaseId"]}
