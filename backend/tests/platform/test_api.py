"""v1 API: authentication, CSRF, RBAC, tenant isolation, filters, bulk actions, PII controls, API keys."""
from sqlalchemy import select

from app.platform.models import ApiKey, AuditLog, NdrCase

RESCHEDULE = "kal shaam 6 baje ke baad bhej dijiye"


def setup_two_tenants(world):
    a = world.merchant("MER-A", users=(("ops@t1.test", "ops_lead"), ("viewer@t1.test", "viewer")))
    b = world.merchant("MER-B", users=(("other@t2.test", "ops_lead"),))
    sa = world.shipment(a, customer_profile={"whatsapp_replies": [{"after_minutes": 5, "text": RESCHEDULE}]})
    sb = world.shipment(b)
    for sid in (sa, sb):
        world.scan(sid, "OUT_FOR_DELIVERY")
        world.scan(sid, "DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE")
    world.run(hours=1)
    db = world.session()
    ca = db.scalars(select(NdrCase).where(NdrCase.shipment_id == sa)).one()
    cb = db.scalars(select(NdrCase).where(NdrCase.shipment_id == sb)).one()
    db.close()
    return a, b, ca, cb


def test_auth_required_and_csrf_enforced(world):
    world.merchant()
    assert world.client.get("/api/v1/ndr").status_code == 401
    world.login()
    token = world.client.headers.pop("x-csrf-token")
    assert world.client.post("/api/v1/auth/logout").status_code == 403  # cookie alone is not enough
    world.client.headers["x-csrf-token"] = "forged"
    assert world.client.post("/api/v1/auth/logout").status_code == 403
    world.client.headers["x-csrf-token"] = token
    assert world.client.post("/api/v1/auth/logout").status_code == 200
    assert world.client.get("/api/v1/ndr").status_code == 401  # session revoked


def test_wrong_password_locks_account(world):
    world.merchant()
    for _ in range(5):
        assert world.client.post("/api/v1/auth/login", json={"email": "ops@t1.test", "password": "nope-nope-nope"}).status_code == 401
    r = world.client.post("/api/v1/auth/login", json={"email": "ops@t1.test", "password": "nope-nope-nope"})
    assert r.status_code in (423, 429)


def test_tenant_isolation_on_every_case_endpoint(world):
    a, b, ca, cb = setup_two_tenants(world)
    world.login("ops@t1.test")
    listed = world.client.get("/api/v1/ndr").json()
    assert [i["id"] for i in listed["items"]] == [ca.id]
    for path in ("", "/timeline", "/agent-runs", "/conversations"):
        assert world.client.get(f"/api/v1/ndr/{cb.id}{path}").status_code == 404
    assert world.client.post(f"/api/v1/ndr/{cb.id}/retry").status_code == 404
    assert world.client.post("/api/v1/auth/switch-merchant", json={"merchantId": b}).status_code == 403
    # a merchant id smuggled into the query string is ignored
    assert [i["id"] for i in world.client.get(f"/api/v1/ndr?merchantId={b}").json()["items"]] == [ca.id]


def test_rbac_viewer_is_read_only_and_masked(world):
    a, b, ca, cb = setup_two_tenants(world)
    world.login("viewer@t1.test")
    row = world.client.get("/api/v1/ndr").json()["items"][0]
    assert row["phoneMasked"].startswith("+91 XXXXX")
    assert world.client.post(f"/api/v1/ndr/{ca.id}/retry").status_code == 403
    assert world.client.get("/api/v1/ndr/export.csv").status_code == 403
    assert world.client.post(f"/api/v1/ndr/{ca.id}/unmask", json={"reason": "need to call"}).status_code == 403
    assert world.client.patch("/api/v1/merchant/agent-config", json={"config": {}, "changeNote": "x"}).status_code == 403


def test_unmask_requires_reason_and_is_audited(world):
    a, b, ca, cb = setup_two_tenants(world)
    world.login("ops@t1.test")
    assert world.client.post(f"/api/v1/ndr/{ca.id}/unmask", json={"reason": ""}).status_code == 422
    r = world.client.post(f"/api/v1/ndr/{ca.id}/unmask", json={"reason": "Customer asked for a call back"})
    assert r.status_code == 200 and r.json()["phone"].startswith("+91")
    db = world.session()
    assert db.scalars(select(AuditLog).where(AuditLog.action == "pii.unmasked")).first().reason == "Customer asked for a call back"
    db.close()


def test_filters_search_sort_and_pagination(world):
    m = world.merchant()
    for i in range(7):
        sid = world.shipment(m, carrier="RELIABLE" if i % 2 else "FASTSHIP", cod=i % 3 == 0)
        world.scan(sid, "OUT_FOR_DELIVERY")
        world.scan(sid, "DELIVERY_FAILED", "ADDRESS_ISSUE" if i == 0 else "CUSTOMER_UNAVAILABLE")
    world.run(minutes=10)
    world.login()
    c = world.client
    page1 = c.get("/api/v1/ndr?pageSize=3&page=1&sort=code&order=asc").json()
    page2 = c.get("/api/v1/ndr?pageSize=3&page=2&sort=code&order=asc").json()
    assert page1["total"] == 7 and len(page1["items"]) == 3
    assert not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}
    assert all(i["carrier"] == "RELIABLE" for i in c.get("/api/v1/ndr?carrier=RELIABLE").json()["items"])
    assert c.get("/api/v1/ndr?reason=address_issue").json()["total"] == 1
    assert all(i["paymentMode"] == "COD" for i in c.get("/api/v1/ndr?payment=COD").json()["items"])
    code = page1["items"][0]["code"]
    assert [i["code"] for i in c.get(f"/api/v1/ndr?q={code}").json()["items"]] == [code]
    awb = page1["items"][0]["awb"]
    assert c.get(f"/api/v1/ndr?q={awb[-6:]}").json()["total"] >= 1
    csv = c.get("/api/v1/ndr/export.csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("id,code")


def test_bulk_actions_report_partial_failures(world):
    a, b, ca, cb = setup_two_tenants(world)
    world.login("ops@t1.test")
    r = world.client.post("/api/v1/ndr/bulk", json={"ids": [ca.id, cb.id, "nope"], "action": "escalate", "reason": "review"})
    body = r.json()
    assert body["succeeded"] == 1 and body["failed"] == 2
    assert {x["id"]: x["ok"] for x in body["results"]} == {ca.id: True, cb.id: False, "nope": False}


def test_case_detail_separates_courier_customer_and_ai_information(world):
    a, b, ca, cb = setup_two_tenants(world)
    world.login("ops@t1.test")
    d = world.client.get(f"/api/v1/ndr/{ca.id}").json()
    assert d["courierReported"]["reason"] == "customer_unavailable"
    assert d["customerSupplied"]["preferredDate"] is not None
    assert d["aiInferred"]["intent"] == "reschedule" and d["decision"]["verdict"] == "ALLOWED"
    assert d["decision"]["rules"] and d["carrierAction"]["status"] == "accepted"
    tl = world.client.get(f"/api/v1/ndr/{ca.id}/timeline").json()["items"]
    types = [i["type"] for i in tl]
    assert types.index("ai.intent_extracted") < types.index("ai.rules_evaluated") < types.index("carrier.reschedule.requested") \
        < types.index("carrier.reschedule.accepted")
    comms = world.client.get(f"/api/v1/ndr/{ca.id}/timeline?category=communication").json()["items"]
    assert comms and all(i["category"] == "communication" for i in comms)


def test_policy_versioning_dry_run_and_audit(world):
    world.merchant(users=(("owner@t1.test", "owner"),))
    world.login("owner@t1.test")
    cur = world.client.get("/api/v1/merchant/agent-config").json()
    cfg = dict(cur["config"], max_auto_reschedule_days=3)
    dry = world.client.patch("/api/v1/merchant/agent-config", json={"config": cfg, "changeNote": "try", "dryRun": True}).json()
    assert dry["applied"] is False and "max_auto_reschedule_days" in dry["changes"]
    assert world.client.get("/api/v1/merchant/agent-config").json()["version"] == cur["version"]
    bad = dict(cfg, auto_actions=["rto"])
    assert world.client.patch("/api/v1/merchant/agent-config", json={"config": bad, "changeNote": "unsafe"}).status_code == 422
    ok = world.client.patch("/api/v1/merchant/agent-config", json={"config": cfg, "changeNote": "allow 3 days"}).json()
    assert ok["applied"] and ok["version"] == cur["version"] + 1


def test_api_key_scoped_import_is_idempotent(world):
    world.merchant(users=(("owner@t1.test", "owner"),))
    world.login("owner@t1.test")
    r = world.client.post("/api/v1/merchant/api-keys", json={"name": "store sync", "scopes": ["shipments.import"]})
    assert r.status_code == 201
    raw = r.json()["key"]
    world.client.headers.pop("x-csrf-token")
    world.client.cookies.clear()
    body = {"merchantOrderId": "SHOP-1", "customer": {"name": "A B", "phone": "9000012345"},
            "address": {"line1": "x", "city": "Hyderabad", "state": "Telangana", "pincode": "500001"},
            "paymentMode": "PREPAID", "orderValuePaise": 50000, "carrierCode": "FASTSHIP", "awb": "FSTAPI0001"}
    h = {"Authorization": f"Bearer {raw}"}
    r1 = world.client.post("/api/v1/shipments/import", json=body, headers=h)
    r2 = world.client.post("/api/v1/shipments/import", json=body, headers=h)
    assert r1.status_code == 201 and r1.json()["created"] and r2.json()["created"] is False and r1.json()["id"] == r2.json()["id"]
    assert world.client.get("/api/v1/ndr", headers=h).status_code == 403  # scope does not include ndr.read
    db = world.session()
    key = db.scalars(select(ApiKey)).one()
    assert key.key_hash != raw and raw not in str(key.__dict__)
    db.close()


def test_request_size_limit_and_sanitized_errors(world):
    world.merchant()
    r = world.client.post("/api/v1/auth/login", content=b"x" * 1_100_000, headers={"content-type": "application/json"})
    assert r.status_code == 413
    r = world.client.post("/api/v1/auth/login", json={"email": 1})
    assert r.status_code == 422 and "input" not in r.text  # submitted values are never echoed
