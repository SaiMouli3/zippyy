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


# ============================================================================ platform fixtures
from datetime import datetime, timedelta, timezone  # noqa: E402

PLATFORM_PASSWORD = "Test-Password-2026!"


class World:
    """A platform test world: frozen clock, one or more merchants, helpers to drive carriers and the worker."""

    def __init__(self, client):
        from app.platform import clock
        self.client = client
        # 10:00 IST on a weekday: inside contact windows.
        self.clock = clock.FrozenClock(datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc))
        clock.set_clock(self.clock)

    def session(self, merchant_id=None, system=True):
        from app.db import new_session
        return new_session(merchant_id=merchant_id, system=system)

    def merchant(self, code="MER-T1", demo=True, users=(("ops@t1.test", "ops_lead"),), config: dict | None = None):
        from app.platform.models import Membership, Merchant, MerchantSettings, User
        from app.platform.security.passwords import hash_password
        from app.platform.seed import seed_reference, seed_templates
        from app.platform import policies
        db = self.session()
        try:
            seed_reference(db)
            m = Merchant(code=code, legal_name=code, brand_name=f"{code} Brand", is_demo=demo)
            db.add(m)
            db.flush()
            db.add(MerchantSettings(merchant_id=m.id))
            seed_templates(db, m.id)
            for email, role in users:
                u = db.query(User).filter_by(email=email).first()
                if u is None:
                    u = User(email=email, name=email.split("@")[0], password_hash=hash_password(PLATFORM_PASSWORD))
                    db.add(u)
                    db.flush()
                db.add(Membership(merchant_id=m.id, user_id=u.id, role=role))
            if config:
                from app.platform.audit import SYSTEM
                current, _ = policies.agent_config(db, m.id)
                policies.publish(db, m.id, "agent_config", {**current.config, **config}, SYSTEM, "test config")
            db.commit()
            return m.id
        finally:
            db.close()

    def shipment(self, merchant_id, carrier="FASTSHIP", cod=False, customer_profile=None, shipment_profile=None,
                 consent=True, pincode="500001", state="Telangana", phone=None, awb=None):
        import random
        from app.platform.audit import SYSTEM
        from app.platform.models import SimulationProfile
        from app.models import Order
        from app.platform.shipments import AddressIn, ConsentIn, CustomerIn, ShipmentImport, import_shipment
        awb = awb or f"{carrier[:2]}T{random.randint(10**8, 10**9 - 1)}"
        data = ShipmentImport(
            merchant_order_id=f"T-{awb}", customer=CustomerIn(name="Test Customer", phone=phone or f"+91900{random.randint(1000000, 9999999)}"),
            address=AddressIn(line1="1 Test Street", city="Hyderabad", state=state, pincode=pincode),
            payment_mode="COD" if cod else "PREPAID", cod_amount_paise=150000 if cod else 0, order_value_paise=150000,
            carrier_code=carrier, awb=awb, consent=ConsentIn(whatsapp="test checkout opt-in" if consent else None))
        db = self.session()
        try:
            s, _ = import_shipment(db, merchant_id, data, SYSTEM)
            order = db.get(Order, s.order_id)
            db.add(SimulationProfile(merchant_id=merchant_id, customer_id=order.customer_id, profile=customer_profile or {}))
            db.add(SimulationProfile(merchant_id=merchant_id, shipment_id=s.id, profile=shipment_profile or {}))
            db.commit()
            return s.id
        finally:
            db.close()

    def scan(self, shipment_id, status, reason=None, duplicate=False):
        """Deliver a signed carrier webhook for this shipment, as the carrier would."""
        from app.platform.simulation.carrier_sim import handle_event

        class J:
            payload = {"shipment_id": shipment_id, "status": status, "reason": reason, "duplicate": duplicate}
        db = self.session()
        try:
            handle_event(db, J)
            db.commit()
        finally:
            db.close()

    def run(self, minutes=0, hours=0, days=0, until=None):
        """Advance simulated time, executing every job that becomes due on the way."""
        from app.platform import clock, worker
        end = until or (self.clock.now() + timedelta(minutes=minutes, hours=hours, days=days))
        worker.drain()
        while True:
            nxt = worker.next_job_time()
            if nxt is None or clock.as_utc(nxt) > end:
                break
            if clock.as_utc(nxt) > self.clock.now():
                self.clock.set(clock.as_utc(nxt))
            worker.drain()
        self.clock.set(end)
        worker.drain()

    def login(self, email="ops@t1.test"):
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": PLATFORM_PASSWORD})
        assert r.status_code == 200, r.text
        self.client.headers["x-csrf-token"] = self.client.cookies.get("zpy_csrf")
        return r.json()


@pytest.fixture
def world(client):
    from app.platform import clock
    w = World(client)
    yield w
    clock.reset_clock()
