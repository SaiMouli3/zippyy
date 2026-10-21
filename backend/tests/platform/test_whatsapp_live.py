from app.config import get_settings
from app.platform.providers.whatsapp import whatsapp_live


def test_live_merchant_without_whatsapp_falls_back_to_voice(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "simulator")
    assert whatsapp_live(merchant_is_demo=True)        # demo workspaces keep the simulated WhatsApp flow
    assert not whatsapp_live(merchant_is_demo=False)   # a real customer would never see a simulated message
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "meta_cloud")
    assert whatsapp_live(merchant_is_demo=False)
