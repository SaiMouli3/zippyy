"""Deterministic policy. The AI proposes an intent; only these rules decide whether
the system may act on it automatically."""
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from . import config
from .ai.intent import WEEKDAYS

ALLOWED = "ALLOWED"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
NO_ACTION = "NO_ACTION"

MIN_CONFIDENCE = 0.6


@dataclass
class Decision:
    outcome: str
    reasons: list[str] = field(default_factory=list)
    action: str | None = None
    requested_date: str | None = None
    requested_window: str | None = None

    def to_dict(self):
        return asdict(self)


def resolve_date(text: str | None, today: date) -> date | None:
    if not text:
        return None
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text == "day after tomorrow":
        return today + timedelta(days=2)
    m = re.fullmatch(r"in (\d+) days", text)
    if m:
        return today + timedelta(days=int(m.group(1)))
    if text in WEEKDAYS:
        delta = (WEEKDAYS.index(text) - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    return None


def evaluate(intent: dict, order: dict, today: date | None = None) -> Decision:
    today = today or date.today()
    kind = intent["intent"]
    if intent.get("confidence", 0) < MIN_CONFIDENCE or kind == "UNKNOWN":
        return Decision(NEEDS_CLARIFICATION, ["Could not confidently understand the buyer's request"])

    if kind in ("CANCEL_ORDER", "REFUSE_ORDER"):
        return Decision(REQUIRES_APPROVAL, ["Cancellation / refusal needs seller approval (RTO)"])
    if kind == "SWITCH_TO_PREPAID":
        return Decision(REQUIRES_APPROVAL, ["Changing payment mode COD -> prepaid needs approval"])
    if kind == "ADDRESS_CORRECTION":
        return Decision(REQUIRES_APPROVAL, ["Address / pincode changes need approval"])

    if kind in ("RESCHEDULE_DELIVERY", "COD_READY"):
        pin = intent.get("pincode")
        if pin and pin != order["delivery_pincode"]:
            return Decision(REQUIRES_APPROVAL, ["Delivery pincode differs from the order"])
        text = intent.get("date")
        if text:
            target = resolve_date(text, today)
            if target is None:
                return Decision(NEEDS_CLARIFICATION, [f"Could not interpret date '{text}'"])
        else:
            target = today + timedelta(days=1)
        offset = (target - today).days
        if offset < 0 or offset > config.MAX_AUTO_RESCHEDULE_DAYS:
            return Decision(REQUIRES_APPROVAL,
                            [f"Requested date is {offset} days out; auto-reattempt allows 0-"
                             f"{config.MAX_AUTO_RESCHEDULE_DAYS}"])
        return Decision(ALLOWED, ["Same address and phone", f"Reschedule within {config.MAX_AUTO_RESCHEDULE_DAYS} days"],
                        action="REATTEMPT", requested_date=target.isoformat(),
                        requested_window=intent.get("time_window") or intent.get("time"))

    return Decision(NO_ACTION, ["No automated action for this intent"])
