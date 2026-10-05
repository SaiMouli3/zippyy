from datetime import date

from app import rules
from app.ai.intent import MockIntentExtractor
from app.carriers.fastship import FastShipAdapter
from app.carriers.quickexpress import QuickExpressAdapter
from app.carriers.reliable import ReliableCourierAdapter

ex = MockIntentExtractor()
TODAY = date(2026, 10, 5)  # a Monday
ORDER = {"delivery_pincode": "110001"}



# -- rate normalization: three different carrier shapes -> one internal shape
def test_rate_normalization_fastship():
    r = FastShipAdapter.normalize_rates({"service": "FAST-AIR", "price": 182.90, "etaDays": 2})[0]
    assert r.model_dump() == {"carrier": "FASTSHIP", "carrierName": "FastShip", "service": "FAST-AIR",
                              "serviceName": "Fast Air", "price": 182.9, "etaMinDays": 2, "etaMaxDays": 2}


def test_rate_normalization_quickexpress():
    r = QuickExpressAdapter.normalize_rates({"product": "EXPRESS", "payable": 197.06, "deliveryEstimate": 3})[0]
    assert (r.carrier, r.service, r.price, r.etaMinDays, r.etaMaxDays) == ("QUICKEXPRESS", "EXPRESS", 197.06, 2, 3)


def test_rate_normalization_reliable():
    raw = {"options": [{"code": "RC-SURFACE", "amount": 159.30, "days": 5}]}
    r = ReliableCourierAdapter.normalize_rates(raw)[0]
    assert (r.carrier, r.service, r.price, r.etaMinDays, r.etaMaxDays) == ("RELIABLECOURIER", "RC-SURFACE", 159.3, 4, 5)


# -- intent extraction
def test_intent_examples():
    cases = {
        "Yes tomorrow evening after 6": "RESCHEDULE_DELIVERY",
        "come tomorrow": "RESCHEDULE_DELIVERY",
        "cancel this order": "CANCEL_ORDER",
        "I don't want it": "REFUSE_ORDER",
        "my address is wrong": "ADDRESS_CORRECTION",
        "payment ready": "COD_READY",
        "blah": "UNKNOWN",
    }
    for text, intent in cases.items():
        assert ex.extract(text).intent == intent, text


def test_intent_entities():
    i = ex.extract("Yes tomorrow evening after 6")
    assert (i.date, i.time, i.time_window, i.confidence) == ("tomorrow", "evening", "After 6 PM", 0.95)


# -- rules engine
def decide(text):
    return rules.evaluate(ex.extract(text).model_dump(), ORDER, TODAY)


def test_rules_allow_reschedule_within_window():
    d = decide("Yes tomorrow evening after 6")
    assert d.outcome == rules.ALLOWED and d.requested_date == "2026-10-06" and d.action == "REATTEMPT"
    assert decide("day after tomorrow please").outcome == rules.ALLOWED


def test_rules_require_approval():
    assert decide("come on friday").outcome == rules.REQUIRES_APPROVAL     # 4 days out
    assert decide("cancel this order").outcome == rules.REQUIRES_APPROVAL
    assert decide("I don't want it").outcome == rules.REQUIRES_APPROVAL
    assert decide("my address is wrong").outcome == rules.REQUIRES_APPROVAL
    assert decide("I want to pay online").outcome == rules.REQUIRES_APPROVAL
    assert decide("come tomorrow to 400001").outcome == rules.REQUIRES_APPROVAL  # new pincode


def test_rules_unknown_and_low_confidence():
    assert decide("blah").outcome == rules.NEEDS_CLARIFICATION
    assert decide("yes").outcome == rules.ALLOWED  # 0.7 >= threshold, defaults to next day


# -- cache key + transition rules (pure)
def test_cache_key_contains_every_pricing_input_and_changes_with_each():
    from app.services.rates import cache_key
    base = {"merchant_id": "MRC-100", "pickup_pincode": "560001", "delivery_pincode": "110001",
            "weight_grams": 1500, "length_cm": 20, "width_cm": 15, "height_cm": 10,
            "payment_mode": "COD", "cod_amount": 2500.0}
    assert cache_key(base) == "zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500"
    seen = {cache_key(base)}
    for field, value in [("merchant_id", "MRC-200"), ("pickup_pincode", "560002"), ("delivery_pincode", "110002"),
                         ("weight_grams", 1501), ("length_cm", 21), ("width_cm", 16), ("height_cm", 11),
                         ("payment_mode", "PREPAID"), ("cod_amount", 2501.0)]:
        k = cache_key({**base, field: value})
        assert k not in seen, field
        seen.add(k)
    assert cache_key({**base, "cod_amount": 99.5}).endswith(":COD:99.50")


def test_transition_rules():
    from app.transitions import is_valid
    assert is_valid("SHIPMENT_CREATED", "PICKED_UP") and is_valid("PICKED_UP", "OUT_FOR_DELIVERY")
    assert is_valid("OUT_FOR_DELIVERY", "NDR") and is_valid("NDR", "OUT_FOR_DELIVERY") and is_valid("NDR", "DELIVERED")
    assert not is_valid("DELIVERED", "IN_TRANSIT") and not is_valid("DELIVERED", "NDR")
    assert not is_valid("IN_TRANSIT", "PICKED_UP") and not is_valid("IN_TRANSIT", "IN_TRANSIT")
    assert not is_valid("NDR", "NDR") and not is_valid("SHIPMENT_CREATED", "DELIVERED")
