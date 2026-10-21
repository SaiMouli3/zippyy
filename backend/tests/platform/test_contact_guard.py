"""Contact policy: opt-outs, evidence-backed consent, quiet hours, caps."""
from datetime import datetime, timezone

from app.platform import contact_guard
from app.platform.models import Customer, Merchant


def _ctx(world, consent=True):
    m = world.merchant()
    sid = world.shipment(m, consent=consent)
    db = world.session()
    from app.models import Order, Shipment
    s = db.get(Shipment, sid)
    o = db.get(Order, s.order_id)
    return db, db.get(Merchant, m), db.get(Customer, o.customer_id), sid


def test_consent_requires_evidence_not_a_default_column(world):
    db, merchant, customer, sid = _ctx(world, consent=False)
    r = contact_guard.check(db, merchant, customer, "whatsapp", "ndr_recovery", sid)
    assert not r.allowed and r.reason == "no_whatsapp_consent"
    db.close()


def test_opt_out_blocks_every_channel(world):
    from app.platform import audit, customers
    db, merchant, customer, sid = _ctx(world)
    customers.record_opt_out(db, customer, "customer_message", audit.SYSTEM, "STOP")
    for ch in ("whatsapp", "voice"):
        assert contact_guard.check(db, merchant, customer, ch, "ndr_recovery", sid).reason == "customer_opted_out"
    db.close()


def test_quiet_hours_and_voice_window_return_next_allowed_time(world):
    db, merchant, customer, sid = _ctx(world)
    world.clock.set(datetime(2026, 10, 14, 17, 0, tzinfo=timezone.utc))  # 22:30 IST
    r = contact_guard.check(db, merchant, customer, "whatsapp", "ndr_recovery", sid)
    assert r.reason == "quiet_hours" and r.retry_at.astimezone(contact_guard.ZoneInfo("Asia/Kolkata")).hour == 9
    world.clock.set(datetime(2026, 10, 14, 3, 45, tzinfo=timezone.utc))  # 09:15 IST: WhatsApp ok, calls not yet
    assert contact_guard.check(db, merchant, customer, "whatsapp", "ndr_recovery", sid).allowed
    r = contact_guard.check(db, merchant, customer, "voice", "ndr_recovery", sid)
    assert r.reason == "outside_voice_window"
    db.close()


def test_daily_cap_counts_proactive_contact_only(world):
    db, merchant, customer, sid = _ctx(world)
    for _ in range(4):
        assert contact_guard.check(db, merchant, customer, "whatsapp", "ndr_recovery", sid).allowed
    assert contact_guard.check(db, merchant, customer, "whatsapp", "ndr_recovery", sid).reason == "customer_daily_contact_limit"
    assert contact_guard.check(db, merchant, customer, "whatsapp", "reply", sid, is_reply_in_session=True).allowed
    assert contact_guard.check(db, merchant, customer, "whatsapp", "confirmation", sid).allowed
    db.close()
