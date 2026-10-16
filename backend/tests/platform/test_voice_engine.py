"""Turn-by-turn multilingual voice conversation engine."""
from datetime import date

from app.platform.voice_engine import CallScript, ConversationEngine

ENGINE = ConversationEngine(["en", "hi", "te", "ta", "kn"], 0.8, max_clarifications=2)
NAMES = {"name": "Ravi", "brand": "Brand", "order": "ORD-1"}
TODAY = date(2026, 10, 14)


def run(turns, lang="en", purpose="ndr_recovery"):
    return ENGINE.run(CallScript(turns), lang, purpose, TODAY, NAMES)


def test_answered_call_captures_and_confirms_preference_without_promising():
    o = run(["deliver tomorrow evening please", "yes"])
    assert o.result == "preference_captured" and o.confirmed_by_customer
    assert o.intent.requested_date == date(2026, 10, 15)
    assert "confirm" in o.turns[-1].text.lower() and "request" in o.turns[-1].text.lower()


def test_silence_ends_politely_without_looping():
    o = run([None, None, "tomorrow"])
    assert o.result == "no_response" and sum(1 for t in o.turns if t.kind == "silence") == 2


def test_customer_correction_is_read_back_again():
    o = run(["deliver tomorrow evening please", "no not tomorrow, day after tomorrow morning", "yes correct"])
    assert o.intent.requested_date == date(2026, 10, 16) and o.intent.requested_window == "09:00-12:00"
    assert sum(1 for t in o.turns if t.speaker == "agent" and (t.text or "").startswith("Just to confirm")) == 2


def test_language_switch_mid_call_keeps_context():
    o = run(["hello", "मुझे हिंदी में बात करनी है, कल शाम को भेज दीजिए", "हाँ"], lang="te")
    assert o.result == "preference_captured" and o.start_language == "te" and o.final_language == "hi"
    assert o.switches and o.switches[0]["to"] == "hi"
    assert o.turns[-1].language == "hi"


def test_code_mixed_speech_is_handled():
    o = run(["kal evening 6 baje ke baad deliver karo", "haan ji"], lang="en")
    assert o.result == "preference_captured" and o.final_language == "hi"


def test_unsupported_language_escalates_instead_of_forcing():
    o = run(["ഹലോ, എനിക്ക് മലയാളം മാത്രമേ അറിയൂ", "മലയാളം മാത്രം"])
    assert o.result == "unsupported_language" and o.final_language == "en"


def test_repeated_misunderstanding_hands_over():
    o = run(["hmm", "uh", "what", "ok"])
    assert o.result == "unresolved"


def test_refusal_is_recorded_without_pressure():
    o = run(["I don't want it, return it"])
    assert o.result == "refused" and len([t for t in o.turns if t.speaker == "agent"]) == 2
