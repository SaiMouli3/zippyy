from app.config import get_settings
from app.platform.providers.whatsapp import whatsapp_live


def test_live_merchant_without_whatsapp_falls_back_to_voice(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "simulator")
    assert whatsapp_live(merchant_is_demo=True)        # demo workspaces keep the simulated WhatsApp flow
    assert not whatsapp_live(merchant_is_demo=False)   # a real customer would never see a simulated message
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "meta_cloud")
    assert whatsapp_live(merchant_is_demo=False)


def test_live_merchant_is_called_and_never_shown_a_simulated_whatsapp_message(world):
    """A real workspace without a WhatsApp connection: first contact is a call, and the carrier confirmation that
    follows is not recorded as a 'delivered' WhatsApp message the customer never received."""
    from sqlalchemy import func, select

    from app.platform.models import CarrierAction, Message, NdrCase, VoiceCall
    from tests.platform.test_workflows import fail_delivery, one

    m = world.merchant(code="MER-LIVE", demo=False)
    sid = world.shipment(m, customer_profile={
        "voice_calls": [{"answer": "answered", "turns": ["hello", "kal shaam 6 baje ke baad bhej do", "haan"]}]})
    fail_delivery(world, sid)
    world.run(hours=3)
    assert one(world, VoiceCall, VoiceCall.shipment_id == sid).status == "completed"
    assert one(world, CarrierAction, CarrierAction.shipment_id == sid).status == "accepted"
    assert one(world, NdrCase, NdrCase.shipment_id == sid).status == "reattempt_scheduled"
    db = world.session()
    try:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.shipment_id == sid)) == 0
    finally:
        db.close()


def test_live_prepaid_pre_delivery_without_whatsapp_records_no_contact(world):
    from app.platform.models import AgentTask, VoiceCall
    from tests.platform.test_workflows import one, rows

    m = world.merchant(code="MER-LIVE2", demo=False)
    sid = world.shipment(m)
    world.scan(sid, "OUT_FOR_DELIVERY")
    world.run(minutes=5)
    task = one(world, AgentTask, AgentTask.shipment_id == sid, AgentTask.task_type == "pre_delivery")
    assert task.status == "completed" and task.state["outcome"].startswith("not contacted")
    assert rows(world, VoiceCall, VoiceCall.shipment_id == sid) == []
