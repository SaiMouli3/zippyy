"""Pure adapter tests: request mapping and response normalization, no network."""
from decimal import Decimal
from types import SimpleNamespace

from app.carriers.fastship import FastShipAdapter
from app.carriers.quickexpress import QuickExpressAdapter
from app.carriers.registry import all_adapters
from app.carriers.reliable import ReliableCourierAdapter, parse_eta
from app.domain.enums import ShipmentStatus

ORDER = SimpleNamespace(
    id="o1", pickup_pincode="560001", delivery_pincode="500001", weight_grams=2000, length_cm=20, width_cm=15,
    height_cm=10, payment_type="COD", cod_amount=2000, customer_name="Asha", customer_phone="9876543210",
)
QUOTE = SimpleNamespace(service_code="X", quote_reference="QE-Q-1")


def test_fastship_request_mapping():
    call = FastShipAdapter().build_rate_request(ORDER)
    assert (call.method, call.path) == ("POST", "/mock/fastship/api/v1/rate")
    assert call.json == {"origin_pin": "560001", "destination_pin": "500001", "weight_kg": 2.0,
                         "payment_mode": "COD", "invoice_value": 2000.0}


def test_quickexpress_request_mapping():
    call = QuickExpressAdapter().build_rate_request(ORDER)
    assert call.path == "/mock/quickexpress/rates/check"
    assert call.json["weightInGrams"] == 2000 and call.json["isCod"] is True
    assert call.json["dimensions"] == {"length": 20, "breadth": 15, "height": 10}
    assert QuickExpressAdapter().build_shipment_request(ORDER, QUOTE).json["quoteId"] == "QE-Q-1"


def test_reliable_request_mapping():
    call = ReliableCourierAdapter().build_rate_request(ORDER)
    assert (call.method, call.path) == ("GET", "/mock/reliablecourier/shipping-options")
    assert call.params == {"from": "560001", "to": "500001", "weight": 2.0, "cod": "true", "amount": 2000.0}
    assert ReliableCourierAdapter().build_shipment_request(ORDER, QUOTE).method == "PUT"


def test_fastship_normalization():
    [r] = FastShipAdapter().normalize_rate_response({"success": True, "service": {
        "service_code": "FAST-AIR", "service_name": "FastShip Air Express", "freight_charge": 140,
        "cod_charge": 30, "tax": 25.2, "total_amount": 195.2, "estimated_days": 2}})
    assert (r.carrier_code, r.service_code, r.base_charge, r.cod_charge, r.tax, r.total_charge) == (
        "FASTSHIP", "FAST-AIR", Decimal("140.00"), Decimal("30.00"), Decimal("25.20"), Decimal("195.20"))
    assert (r.estimated_min_days, r.estimated_max_days) == (2, 2)


def test_quickexpress_normalization():
    [r] = QuickExpressAdapter().normalize_rate_response({
        "status": "AVAILABLE", "quoteId": "QE-Q-10001",
        "charges": {"shipping": 130, "cod": 35, "fuelSurcharge": 10, "gst": 31.5}, "payable": 206.5,
        "deliveryEstimate": {"minimumDays": 2, "maximumDays": 3}, "product": "EXPRESS"})
    assert r.additional_charges == Decimal("10.00") and r.total_charge == Decimal("206.50")
    assert r.quote_reference == "QE-Q-10001" and (r.estimated_min_days, r.estimated_max_days) == (2, 3)


def test_reliable_normalization_returns_two_options():
    rates = ReliableCourierAdapter().normalize_rate_response({"code": 200, "data": [
        {"id": "RC-SURFACE", "name": "Reliable Surface", "eta": "4-5 business days",
         "rate": {"base": 100, "handling": 10, "cashCollectionFee": 25, "taxAmount": 24.3, "grandTotal": 159.3}},
        {"id": "RC-AIR", "name": "Reliable Air", "eta": "2-3 business days",
         "rate": {"base": 140, "handling": 12, "cashCollectionFee": 25, "taxAmount": 31.9, "grandTotal": 208.9}}]})
    assert [r.service_code for r in rates] == ["RC-SURFACE", "RC-AIR"]
    assert rates[0].additional_charges == Decimal("10.00") and rates[0].cod_charge == Decimal("25.00")
    assert (rates[0].estimated_min_days, rates[0].estimated_max_days) == (4, 5)
    assert parse_eta("2 business days") == (2, 2) and parse_eta("soon") == (None, None)


def test_unserviceable_responses_normalize_to_empty():
    assert FastShipAdapter().normalize_rate_response({"success": False}) == []
    assert QuickExpressAdapter().normalize_rate_response({"status": "UNAVAILABLE"}) == []
    assert ReliableCourierAdapter().normalize_rate_response({"code": 404}) == []


def test_shipment_response_normalization():
    s = FastShipAdapter().normalize_shipment_response(
        {"success": True, "shipment_id": "FS-100001", "tracking_number": "FST123456789", "status": "BOOKED"})
    assert (s.carrier_shipment_id, s.tracking_number, s.status) == ("FS-100001", "FST123456789", ShipmentStatus.SHIPMENT_CREATED)
    s = QuickExpressAdapter().normalize_shipment_response({"bookingStatus": "CONFIRMED", "booking": {
        "bookingId": "QE-B-10001", "awb": "QE987654321", "currentState": "SHIPMENT_CREATED"}})
    assert s.tracking_number == "QE987654321"
    s = ReliableCourierAdapter().normalize_shipment_response(
        {"result": "ACCEPTED", "deliveryOrder": {"id": "RC-DO-10001", "trackingCode": "RC1122334455"}})
    assert s.carrier_shipment_id == "RC-DO-10001"


def test_webhook_normalization_all_carriers():
    ev = FastShipAdapter().normalize_webhook({"event_id": "e1", "tracking_number": "T1", "status": "UNDELIVERED",
                                              "timestamp": "2026-01-01T10:00:00+00:00", "location": "Hyd"})
    assert ev.status == ShipmentStatus.DELIVERY_FAILED and ev.location == "Hyd" and ev.event_id == "e1"
    ev = QuickExpressAdapter().normalize_webhook({"eventId": "e2", "awb": "T2", "state": "PICKUP_DONE",
                                                  "hub": {"city": "BLR"}, "occurredAt": 1767261600000})
    assert ev.status == ShipmentStatus.PICKED_UP and ev.location == "BLR" and ev.event_time.tzinfo is not None
    ev = ReliableCourierAdapter().normalize_webhook({"notification": {
        "id": "e3", "trackingCode": "T3", "code": 600, "message": "returning", "place": "X", "ts": "2026-01-01 10:00:00"}})
    assert ev.status == ShipmentStatus.RTO and ev.tracking_number == "T3"


def test_registry_has_three_distinct_carriers():
    assert sorted(a.code for a in all_adapters()) == ["FASTSHIP", "QUICKEXPRESS", "RELIABLE"]
