from tests.conftest import ORDER


def test_order_creation(client):
    r = client.post("/api/orders", json=ORDER)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "CREATED" and body["pickupPincode"] == "560001" and body["codAmount"] == 2000
    assert client.get(f"/api/orders/{body['id']}").json()["id"] == body["id"]


def test_snake_case_input_accepted(client):
    r = client.post("/api/orders", json={
        "customer_name": "A", "customer_phone": "9876543210", "pickup_pincode": "560001",
        "delivery_pincode": "500001", "weight_grams": 500, "payment_type": "PREPAID"})
    assert r.status_code == 201 and r.json()["codAmount"] == 0


def test_invalid_orders_rejected(client):
    for patch in ({"pickupPincode": "123"}, {"weightGrams": 0}, {"paymentType": "COD", "codAmount": 0},
                  {"customerPhone": "abc"}, {"paymentType": "CHEQUE"}):
        assert client.post("/api/orders", json={**ORDER, **patch}).status_code == 422, patch


def test_unknown_order_404(client):
    assert client.get("/api/orders/nope").status_code == 404
    assert client.post("/api/orders/nope/rates").status_code == 404


def test_duplicate_merchant_order_id(client):
    body = {**ORDER, "merchantOrderId": "X-1"}
    assert client.post("/api/orders", json=body).status_code == 201
    assert client.post("/api/orders", json=body).status_code == 409
