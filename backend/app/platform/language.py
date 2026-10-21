"""Language detection and preference resolution.

Order of trust when choosing the language for a contact:
  1. The customer's confirmed preference (they said so, or an operator corrected it).
  2. Language detected in the customer's own recent messages/calls, above a confidence threshold.
  3. The address prior (pincode/state) — a starting guess, never treated as a preference.
  4. Merchant default (English).

Detection here is a deterministic heuristic (Unicode script + a romanized lexicon) used in simulation and as
the fallback when the Sarvam language-identification API is not configured or unavailable.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform import clock
from app.platform.models import Customer, Message, Pincode, VoiceCallEvent

LANG_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam",
              "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "or": "Odia"}
BCP47 = {"en": "en-IN", "hi": "hi-IN", "te": "te-IN", "ta": "ta-IN", "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN",
         "bn": "bn-IN", "gu": "gu-IN", "pa": "pa-IN", "or": "od-IN"}
FROM_BCP47 = {v: k for k, v in BCP47.items()}

# State -> language prior. Weights express uncertainty: many residents of any state speak other languages.
STATE_PRIORS: dict[str, list[tuple[str, float]]] = {
    "Telangana": [("te", 0.55), ("hi", 0.2), ("en", 0.2), ("ur", 0.05)],
    "Andhra Pradesh": [("te", 0.7), ("en", 0.2), ("hi", 0.1)],
    "Karnataka": [("kn", 0.5), ("en", 0.3), ("hi", 0.1), ("te", 0.05), ("ta", 0.05)],
    "Tamil Nadu": [("ta", 0.7), ("en", 0.25), ("hi", 0.05)],
    "Kerala": [("ml", 0.7), ("en", 0.3)],
    "Maharashtra": [("mr", 0.45), ("hi", 0.35), ("en", 0.2)],
    "Delhi": [("hi", 0.65), ("en", 0.35)],
    "Uttar Pradesh": [("hi", 0.85), ("en", 0.15)],
    "Rajasthan": [("hi", 0.85), ("en", 0.15)],
    "West Bengal": [("bn", 0.7), ("hi", 0.15), ("en", 0.15)],
    "Gujarat": [("gu", 0.65), ("hi", 0.2), ("en", 0.15)],
    "Punjab": [("pa", 0.6), ("hi", 0.25), ("en", 0.15)],
    "Odisha": [("or", 0.65), ("hi", 0.15), ("en", 0.2)],
}

_SCRIPTS = [  # (start, end, language)
    (0x0900, 0x097F, "hi"),  # Devanagari (also Marathi; disambiguated by lexicon below)
    (0x0980, 0x09FF, "bn"),
    (0x0A00, 0x0A7F, "pa"),
    (0x0A80, 0x0AFF, "gu"),
    (0x0B00, 0x0B7F, "or"),
    (0x0B80, 0x0BFF, "ta"),
    (0x0C00, 0x0C7F, "te"),
    (0x0C80, 0x0CFF, "kn"),
    (0x0D00, 0x0D7F, "ml"),
]

# Romanized cue words. Kept small and high-precision: words that are unlikely in English text.
_ROMAN = {
    "hi": {"kal", "parso", "aaj", "nahi", "nahin", "haan", "ji", "ghar", "par", "hoon", "hun", "main", "mein", "mai",
           "shaam", "subah", "dopahar", "baje", "bhej", "bhejo", "dijiye", "karo", "kijiye", "paise", "abhi", "kyunki",
           "kripya", "dhanyavaad", "accha", "theek", "rahunga", "rahungi", "hai", "hain", "mujhe", "chahiye", "lena",
           "nahi chahiye", "wapas", "baad", "kya", "aap", "batao"},
    "te": {"repu", "ellundi", "ivala", "ledu", "kaadu", "avunu", "intlo", "unnanu", "unnaanu", "saayantram",
           "sayantram", "poddunna", "madhyahnam", "pampandi", "cheyandi", "kavali", "vaddu", "dabbulu", "ippudu",
           "tarvata", "dhanyavadalu", "sare", "baagundi", "ostanu", "telugu", "nenu", "meeru", "emi", "enti"},
    "ta": {"naalai", "inniku", "illa", "aamaa", "veetla", "saayangalam", "kaalaila", "anuppunga", "venum",
           "vendaam", "panam", "ippo", "nandri", "sari", "naan", "neenga"},
    "kn": {"naale", "ivattu", "illa", "houdu", "maneli", "sanje", "beligge", "kalisi", "beku", "beda", "duddu",
           "eega", "dhanyavaadagalu", "sari", "naanu", "neevu"},
}
_EN_CUES = {"tomorrow", "today", "evening", "morning", "deliver", "delivery", "please", "home", "office", "time",
            "after", "before", "not", "available", "address", "call", "cancel", "want", "the", "is", "at", "will",
            "can", "send", "parcel", "order", "pay", "cash", "ready", "yes", "no", "thanks", "thank", "you", "pm", "am"}
_MARATHI_CUES = {"उद्या", "आहे", "नाही", "घरी", "संध्याकाळी", "पाठवा"}


@dataclass
class Detection:
    language: str | None
    confidence: float
    script: str  # native | latin | mixed | none
    code_mixed: bool = False
    secondary: str | None = None
    source: str = "heuristic"


def _script_lang(ch: str) -> str | None:
    cp = ord(ch)
    for start, end, lang in _SCRIPTS:
        if start <= cp <= end:
            return lang
    return None


def detect(text: str) -> Detection:
    """Deterministic detector for the 11 supported languages plus Hindi-English / Telugu-English code-mixing."""
    text = unicodedata.normalize("NFC", text or "").strip()
    if not text:
        return Detection(None, 0.0, "none")
    counts: dict[str, int] = {}
    latin = 0
    for ch in text:
        if ch.isalpha():
            lang = _script_lang(ch)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
            elif ch.isascii():
                latin += 1
    native_total = sum(counts.values())
    if native_total:
        lang = max(counts, key=counts.get)
        if lang == "hi" and any(cue in text for cue in _MARATHI_CUES):
            lang = "mr"
        share = native_total / (native_total + latin)
        mixed = latin >= 4 and share < 0.85
        return Detection(lang, round(min(0.98, 0.6 + 0.4 * share), 3), "mixed" if mixed else "native",
                         code_mixed=mixed, secondary="en" if mixed else None)

    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return Detection(None, 0.0, "none")
    scores = {lang: sum(1 for w in words if w in cues) for lang, cues in _ROMAN.items()}
    en = sum(1 for w in words if w in _EN_CUES)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        conf = 0.55 + min(0.4, 0.08 * en) if en else 0.4
        return Detection("en", round(conf, 3), "latin")
    if en >= 1 and en >= scores[best] / 2:
        # Romanized Indic words mixed with English: e.g. "kal evening 6 baje ke baad deliver karo".
        return Detection(best, round(min(0.9, 0.55 + 0.1 * scores[best]), 3), "latin", code_mixed=True, secondary="en")
    return Detection(best, round(min(0.92, 0.5 + 0.12 * scores[best]), 3), "latin")


def address_prior(db: Session, pincode: str | None, state: str | None) -> tuple[str, float] | None:
    priors = None
    if pincode:
        row = db.get(Pincode, pincode)
        if row and row.language_prior:
            priors = [(p["lang"], float(p["weight"])) for p in row.language_prior]
            state = state or row.state
    if priors is None and state in STATE_PRIORS:
        priors = STATE_PRIORS[state]
    if not priors:
        return None
    lang, weight = max(priors, key=lambda p: p[1])
    return lang, weight


@dataclass
class LanguageChoice:
    language: str
    source: str  # confirmed_preference | recent_interaction | address_prior | default
    confidence: float
    supported: bool


def choose_contact_language(db: Session, customer: Customer, supported: list[str], pincode: str | None = None,
                            state: str | None = None, history_threshold: float = 0.8) -> LanguageChoice:
    def pick(lang: str, source: str, conf: float) -> LanguageChoice:
        if lang in supported:
            return LanguageChoice(lang, source, conf, True)
        # Requested/predicted language not offered by this merchant: fall back, flagged as unsupported.
        return LanguageChoice("en" if "en" in supported else supported[0], source, conf, False)

    if customer.preferred_language:
        return pick(customer.preferred_language, "confirmed_preference", 1.0)

    since = clock.now() - timedelta(days=90)
    recent_msg = db.scalars(select(Message).where(
        Message.merchant_id == customer.merchant_id, Message.direction == "inbound",
        Message.conversation_id.in_(_conversation_ids(db, customer)), Message.created_at >= since,
        Message.language.is_not(None), Message.language_confidence >= history_threshold,
    ).order_by(Message.created_at.desc())).first()
    if recent_msg:
        return pick(recent_msg.language, "recent_interaction", float(recent_msg.language_confidence or 0))

    recent_turn = db.scalars(select(VoiceCallEvent).where(
        VoiceCallEvent.merchant_id == customer.merchant_id, VoiceCallEvent.kind == "turn",
        VoiceCallEvent.speaker == "customer", VoiceCallEvent.occurred_at >= since,
        VoiceCallEvent.language_confidence >= history_threshold,
        VoiceCallEvent.call_id.in_(_call_ids(db, customer)),
    ).order_by(VoiceCallEvent.occurred_at.desc())).first()
    if recent_turn and recent_turn.language:
        return pick(recent_turn.language, "recent_interaction", float(recent_turn.language_confidence or 0))

    prior = address_prior(db, pincode, state)
    if prior:
        return pick(prior[0], "address_prior", prior[1])
    return LanguageChoice("en", "default", 0.5, True)


def _conversation_ids(db: Session, customer: Customer):
    from app.platform.models import Conversation
    return select(Conversation.id).where(Conversation.customer_id == customer.id)


def _call_ids(db: Session, customer: Customer):
    from app.platform.models import VoiceCall
    return select(VoiceCall.id).where(VoiceCall.customer_id == customer.id)


class SwitchTracker:
    """In-conversation switching with hysteresis: switch when one strong turn (>= threshold, >= 3 words) or two
    consecutive turns agree on a new language. A single ambiguous word never switches the conversation."""

    def __init__(self, current: str, threshold: float):
        self.current = current
        self.threshold = threshold
        self._pending: str | None = None

    def observe(self, det: Detection, word_count: int) -> tuple[str, bool, bool]:
        """Returns (language_to_use, switched, needs_clarification)."""
        if det.language is None or det.language == self.current:
            self._pending = None
            return self.current, False, False
        strong = det.confidence >= self.threshold and word_count >= 3
        if strong or self._pending == det.language:
            previous, self.current, self._pending = self.current, det.language, None
            return self.current, previous != self.current, False
        self._pending = det.language
        # Moderate evidence for a new language: ask rather than guess.
        return self.current, False, det.confidence >= 0.55 and word_count >= 2
