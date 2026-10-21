"""Deterministic policy engine: the only component that authorizes carrier actions."""
from datetime import date, datetime, timedelta, timezone

from app.platform.policies import AgentConfig
from app.platform.policy import PolicyInput, evaluate

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
CAPS = {"reattempt": {"max_days_ahead": 3, "same_day_cutoff_hour": 11, "windows": ["09-13", "13-17", "17-21"]},
        "reschedule": {"max_days_ahead": 3, "windows": ["09-13", "13-17", "17-21"]}, "rto": {}}


def inp(**kw) -> PolicyInput:
    base = dict(intent="reschedule", intent_valid=True, intent_confidence=0.9, requested_date=TODAY + timedelta(days=1),
                requested_window="18:00-21:00", today=TODAY, now=NOW, purpose="ndr_recovery", case_open=True,
                shipment_status="DELIVERY_FAILED", attempt_count=1, payment_mode="PREPAID", cod_amount_paise=0,
                sla_due_at=NOW + timedelta(hours=10), carrier_capabilities=CAPS, config=AgentConfig())
    base.update(kw)
    return PolicyInput(**base)


def test_reschedule_within_limits_is_allowed():
    r = evaluate(inp())
    assert r.verdict == "ALLOWED" and r.action == "reschedule" and r.requested_window == "18:00-21:00"


def test_beyond_auto_limit_needs_approval_and_beyond_carrier_horizon_is_denied():
    assert evaluate(inp(requested_date=TODAY + timedelta(days=3))).verdict == "REQUIRES_APPROVAL"
    r = evaluate(inp(requested_date=TODAY + timedelta(days=5)))
    assert r.verdict == "DENIED" and "R06" in r.rules_fired and any(a.startswith("latest_date:") for a in r.alternatives)


def test_same_day_after_cutoff_is_denied_with_next_day_alternative():
    r = evaluate(inp(intent="reattempt_today", requested_date=TODAY, now=NOW.replace(hour=13)))
    assert r.verdict == "DENIED" and "R07" in r.rules_fired


def test_attempts_exhausted_proposes_rto():
    r = evaluate(inp(attempt_count=3))
    assert r.verdict == "DENIED" and "rto" in r.alternatives


def test_rto_and_address_changes_always_need_a_human():
    assert evaluate(inp(intent="refuse")).verdict == "REQUIRES_APPROVAL"
    assert evaluate(inp(intent="cancel_order")).verdict == "REQUIRES_APPROVAL"
    assert evaluate(inp(intent="address_change")).verdict == "REQUIRES_APPROVAL"


def test_low_confidence_or_ambiguous_intent_never_authorizes():
    assert evaluate(inp(intent_confidence=0.4)).verdict == "DENIED"
    assert evaluate(inp(intent_valid=False)).verdict == "DENIED"


def test_carrier_without_reschedule_api_uses_next_day_reattempt_or_stores_preference():
    caps = {"reattempt": {"max_days_ahead": 2}}
    r = evaluate(inp(carrier_capabilities=caps))
    assert r.verdict == "ALLOWED" and r.action == "reattempt"
    r = evaluate(inp(carrier_capabilities=caps, requested_date=TODAY + timedelta(days=2)))
    assert r.verdict == "DENIED" and "store_preference" in r.alternatives


def test_unsupported_window_is_not_promised():
    r = evaluate(inp(carrier_capabilities={"reschedule": {"max_days_ahead": 3}}))
    assert r.verdict == "ALLOWED" and r.requested_window is None and not r.carrier_window_supported


def test_policy_rejects_actions_on_delivered_shipments_and_closed_cases():
    assert evaluate(inp(shipment_status="DELIVERED")).verdict == "DENIED"
    assert evaluate(inp(case_open=False)).verdict == "DENIED"


def test_high_value_cod_and_sla_breach_need_approval():
    assert evaluate(inp(payment_mode="COD", cod_amount_paise=2_000_000, requested_date=TODAY + timedelta(days=2))).verdict == "REQUIRES_APPROVAL"
    assert evaluate(inp(sla_due_at=NOW - timedelta(minutes=1))).verdict == "REQUIRES_APPROVAL"


def test_opted_out_customer_requires_operator():
    assert evaluate(inp(customer_opted_out=True)).verdict == "REQUIRES_APPROVAL"


def test_config_cannot_make_rto_automatic():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentConfig(auto_actions=["reattempt", "rto"], approval_required_actions=["address_change"])
