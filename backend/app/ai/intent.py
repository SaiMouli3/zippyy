"""Intent extraction. The interface is what the rest of the app depends on; swap
MockIntentExtractor for an LLM-backed implementation later. Extractors only
*interpret* text - they never authorise anything (that is rules.py)."""
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

INTENTS = ["RESCHEDULE_DELIVERY", "CANCEL_ORDER", "REFUSE_ORDER", "ADDRESS_CORRECTION",
           "COD_READY", "SWITCH_TO_PREPAID", "UNKNOWN"]


class Intent(BaseModel):
    intent: str
    date: str | None = None          # "today" | "tomorrow" | "day after tomorrow" | weekday | "in N days"
    time: str | None = None          # "morning" | "afternoon" | "evening" | "night"
    time_window: str | None = None   # e.g. "After 6 PM"
    pincode: str | None = None
    confidence: float = 0.0
    entities: dict = Field(default_factory=dict)


class IntentExtractor(ABC):
    @abstractmethod
    def extract(self, text: str) -> Intent: ...


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class MockIntentExtractor(IntentExtractor):
    def extract(self, text: str) -> Intent:
        t = " ".join(text.lower().split())
        date = self._date(t)
        time, window = self._time(t)
        pin = re.search(r"\b(\d{6})\b", t)
        extra = dict(date=date, time=time, time_window=window, pincode=pin.group(1) if pin else None)

        def has(*words):
            return any(w in t for w in words)

        if has("cancel"):
            return Intent(intent="CANCEL_ORDER", confidence=0.95, **extra)
        if has("don't want", "dont want", "do not want", "refuse", "not interested", "return it", "send it back"):
            return Intent(intent="REFUSE_ORDER", confidence=0.95, **extra)
        if has("address", "pincode", "pin code", "landmark", "deliver it to", "deliver to"):
            return Intent(intent="ADDRESS_CORRECTION", confidence=0.9, **extra)
        if has("prepaid", "pay online", "upi", "pay now"):
            return Intent(intent="SWITCH_TO_PREPAID", confidence=0.9, **extra)
        if has("payment ready", "cash ready", "money ready", "have the cash", "will pay", "ready to pay"):
            return Intent(intent="COD_READY", confidence=0.95, **extra)
        if pin and not (date or time):
            return Intent(intent="ADDRESS_CORRECTION", confidence=0.8, **extra)
        if date or time or has("come", "reattempt", "re-attempt", "try again", "deliver again", "redeliver"):
            return Intent(intent="RESCHEDULE_DELIVERY", confidence=0.95, **extra)
        if re.fullmatch(r"(yes|yeah|yep|ok|okay|sure|please|yes please)[.! ]*", t):
            return Intent(intent="RESCHEDULE_DELIVERY", confidence=0.7, **extra)
        return Intent(intent="UNKNOWN", confidence=0.2, **extra)

    @staticmethod
    def _date(t: str) -> str | None:
        if "day after tomorrow" in t or "day after" in t:
            return "day after tomorrow"
        if "tomorrow" in t or "tmrw" in t or "tomorow" in t:
            return "tomorrow"
        if "today" in t or "tonight" in t:
            return "today"
        m = re.search(r"in (\d+) days?", t)
        if m:
            return f"in {m.group(1)} days"
        for d in WEEKDAYS:
            if d in t:
                return d
        return None

    @staticmethod
    def _time(t: str) -> tuple[str | None, str | None]:
        time = next((w for w in ("morning", "afternoon", "evening", "night") if w in t), None)
        if "tonight" in t:
            time = "night"
        window = None
        m = re.search(r"\b(after|before|around|at)\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?", t)
        if m:
            hour, suffix = int(m.group(2)), m.group(3)
            if not suffix:
                suffix = "am" if time == "morning" else "pm"
            window = f"{m.group(1).capitalize()} {hour} {suffix.upper()}"
        return time, window


extractor: IntentExtractor = MockIntentExtractor()
