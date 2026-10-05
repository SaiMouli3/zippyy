from tests.conftest import book


def say(client, conv, text):
    r = client.post("/api/agent/message", json={"conversationId": conv, "message": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_whatsapp_conversation(client):
    r = say(client, "c1", "I want to send a parcel.")
    assert "pickup pincode" in r["reply"].lower() and r["toolCalls"] == []
    assert "delivery pincode" in say(client, "c1", "560001")["reply"].lower()
    assert "weight" in say(client, "c1", "500001")["reply"].lower()
    assert "prepaid or cod" in say(client, "c1", "2 kg")["reply"].lower()

    r = say(client, "c1", "COD, ₹2000")
    assert [c["name"] for c in r["toolCalls"]] == ["create_order", "get_shipping_rates"]
    assert "4 shipping options" in r["reply"] and "FastShip" in r["reply"] and "₹195.2" in r["reply"]

    r = say(client, "c1", "Book FastShip")
    assert [c["name"] for c in r["toolCalls"]] == ["select_carrier", "create_shipment"]
    tn = r["toolCalls"][1]["result"]["trackingNumber"]
    assert f"Tracking number: {tn}" in r["reply"] and r["reply"].startswith("Done. Your FastShip shipment is booked")

    r = say(client, "c1", "Where is my shipment?")
    assert [c["name"] for c in r["toolCalls"]] == ["get_tracking"] and "shipment created" in r["reply"]

    client.post(f"/mock/fastship/shipments/{tn}/next-status")
    client.post(f"/mock/fastship/shipments/{tn}/next-status")
    assert "in transit" in say(client, "c1", "any update on my parcel?")["reply"]


def test_one_shot_message_and_amount_parsing(client):
    r = say(client, "c2", "I want to send a 2kg parcel from 560001 to 500001")
    assert "prepaid or cod" in r["reply"].lower()
    assert "options" in say(client, "c2", "prepaid")["reply"]


def test_cod_without_amount_asks_for_it(client):
    say(client, "c3", "send parcel from 560001 to 500001, 1.5 kg, cod")
    # last message lacked an amount
    r = say(client, "c3", "1500")
    assert "options" in r["reply"]


def test_option_by_number_and_ambiguous_carrier(client):
    say(client, "c4", "send a 2kg prepaid parcel from 560001 to 500001")
    r = say(client, "c4", "book reliable")
    assert "Reliable" in r["reply"] and "cheaper" in r["reply"]  # two Reliable services -> cheapest chosen, user told
    say(client, "c5", "send a 2kg prepaid parcel from 560001 to 500001")
    assert "booked" in say(client, "c5", "option 1")["reply"]


def test_conversations_are_isolated_and_tracking_before_booking(client):
    assert "don't have a shipment" in say(client, "c6", "where is my parcel?")["reply"]
    say(client, "c7", "send a 2kg prepaid parcel from 560001 to 500001")
    assert "isn't booked" in say(client, "c7", "where is my shipment")["reply"]


def test_agent_reports_failed_carrier(client):
    client.put("/mock/reliablecourier/config", params={"failure": "true"})
    r = say(client, "c8", "send a 2kg prepaid parcel from 560001 to 500001")
    assert "2 shipping options" in r["reply"] and "ReliableCourier" in r["reply"]


def test_agent_never_calls_carriers_directly():
    import pathlib
    for f in pathlib.Path("app/agent").glob("*.py"):
        src = f.read_text()
        assert "app.carriers" not in src.replace("from app.carriers.registry import get_adapter", ""), f
        assert "httpx" not in src, f


def test_voice_call_uses_same_tools(client):
    r = client.post("/api/voice/mock-call", json={"utterances": [
        "I want to send a 2 kg prepaid parcel from 560001 to 500001", "book fastship", "where is my shipment"]})
    assert r.status_code == 200
    agent_lines = [t["text"] for t in r.json()["transcript"] if t["role"] == "agent"]
    assert agent_lines[0].startswith("Welcome") and "options" in agent_lines[1] and "booked" in agent_lines[2]
    assert "shipment created" in agent_lines[3] and r.json()["transcript"][-1]["text"] == "call ended"


def test_complete_happy_path_via_rest(client, order):
    """Order -> rates -> select -> shipment -> webhooks -> tracking."""
    s = book(client, order["id"], "RELIABLE", "RC-SURFACE")
    assert s["status"] == "SHIPMENT_CREATED"
    mock = client.get("/mock/shipments").json()
    assert mock == [{"carrier": "reliablecourier", "trackingNumber": s["trackingNumber"], "carrierShipmentId": mock[0]["carrierShipmentId"],
                     "currentStatus": "CREATED", "nextStatus": "PICKED_UP"}]
    for _ in range(4):
        assert client.post(f"/mock/reliablecourier/shipments/{s['trackingNumber']}/next-status").status_code == 200
    t = client.get(f"/api/orders/{order['id']}/tracking").json()
    assert t["currentStatus"] == "DELIVERED" and t["trackingNumber"] == s["trackingNumber"] and len(t["history"]) == 5
    assert client.get("/api/shipments").json()[0]["currentStatus"] == "DELIVERED"
