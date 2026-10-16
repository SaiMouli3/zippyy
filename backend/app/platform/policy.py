"""Deterministic policy engine. The only component that can authorize a carrier action.

`evaluate()` is a pure function of explicit inputs, so every verdict is reproducible from the stored decision
row (inputs, rule ids, rules version, policy version). Intent extraction output is an *input*; it can propose,
never authorize.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.platform.policies import RULES_VERSION, AgentConfig

INTENT_TO_ACTION = {
    "reschedule": "reschedule",
    "reattempt_today": "reattempt",
    "cod_ready": "reattempt",
    "cod_not_ready": "reschedule",
    "available": "reattempt",
    "refuse": "rto",
    "cancel_order": "rto",
    "address_change": "address_change",
    "phone_change": "phone_change",
}

RULE_TEXT = {
    "R01": "Case must be open and the shipment must be in a state the action applies to",
    "R02": "Intent must be valid and above the confidence threshold",
    "R03": "Delivery attempts must be below the merchant's RTO threshold",
    "R04": "Carrier must support the action through its API",
    "R05": "Requested date must be within the auto-reschedule limit",
    "R06": "Requested date must be within the carrier's booking horizon",
    "R07": "Same-day reattempts must be requested before the carrier's cut-off",
    "R08": "Merchant policy decides which actions run automatically",
    "R09": "High-value COD reschedules need approval",
    "R10": "Actions after the SLA deadline need approval",
    "R11": "RTO and cancellation always need a human",
    "R12": "Address and phone changes need verification by a human",
    "R13": "Requested time window must be one the carrier offers",
    "R14": "Customer must not have opted out of delivery changes",
}


@dataclass
class PolicyInput:
    intent: str
    intent_valid: bool
    intent_confidence: float
    requested_date: date | None
    requested_window: str | None
    today: date  # merchant-local
    now: datetime
    purpose: str  # ndr_recovery | pre_delivery
    case_open: bool
    shipment_status: str
    attempt_count: int
    payment_mode: str  # PREPAID | COD
    cod_amount_paise: int
    sla_due_at: datetime | None
    carrier_capabilities: dict[str, dict]  # capability -> constraints
    config: AgentConfig
    customer_opted_out: bool = False


@dataclass
class PolicyResult:
    verdict: str  # ALLOWED | REQUIRES_APPROVAL | DENIED
    action: str | None
    requested_date: date | None
    requested_window: str | None
    reasons: list[str] = field(default_factory=list)
    rules_fired: list[str] = field(default_factory=list)
    rules_version: str = RULES_VERSION
    carrier_window_supported: bool = True
    alternatives: list[str] = field(default_factory=list)

    def fire(self, rule: str, reason: str) -> None:
        self.rules_fired.append(rule)
        self.reasons.append(reason)


def _window_ok(window: str, offered: list[str] | None) -> bool:
    """A requested window ("18:00-21:00") is serviceable when it starts inside one of the carrier's slots
    ("17-21"): the carrier then attempts within that slot."""
    if not offered:
        return False
    start = int(window.split("-")[0][:2])
    for slot in offered:
        a, b = (int(x) for x in slot.split("-"))
        if a <= start < b:
            return True
    return False


def evaluate(p: PolicyInput) -> PolicyResult:
    action = INTENT_TO_ACTION.get(p.intent)
    r = PolicyResult("DENIED", action, p.requested_date, p.requested_window)
    cfg = p.config

    if action is None:
        r.fire("R02", f"Intent '{p.intent}' does not map to a carrier action")
        return r
    if not p.case_open and p.purpose == "ndr_recovery":
        r.fire("R01", "The NDR case is already closed")
        return r
    allowed_states = {"ndr_recovery": {"DELIVERY_FAILED"},
                      "pre_delivery": {"OUT_FOR_DELIVERY", "IN_TRANSIT", "PICKED_UP", "SHIPMENT_CREATED"}}[p.purpose]
    if p.shipment_status not in allowed_states:
        r.fire("R01", f"Shipment is {p.shipment_status}; {action} applies only to {', '.join(sorted(allowed_states))}")
        return r
    if not p.intent_valid or p.intent_confidence < cfg.intent_confidence_threshold:
        r.fire("R02", f"Intent confidence {p.intent_confidence:.2f} is below {cfg.intent_confidence_threshold:.2f} or "
                      "the extraction needs clarification")
        return r
    if p.customer_opted_out and action not in ("rto",):
        r.fire("R14", "Customer has opted out; delivery changes need an operator")
        r.verdict = "REQUIRES_APPROVAL"
        return r

    # Pre-delivery requests with "available" need no carrier change at all.
    if p.purpose == "pre_delivery" and p.intent == "available":
        r.action = None
        r.verdict = "ALLOWED"
        r.fire("R08", "Customer confirmed availability; no carrier change required")
        return r

    if action in ("rto", "cancel"):
        r.verdict = "REQUIRES_APPROVAL"
        r.fire("R11", "Return-to-origin is never automatic: a person confirms the customer's refusal first")
        if "rto" not in p.carrier_capabilities:
            r.fire("R04", "Carrier has no RTO API; the operator raises it with the carrier")
        return r

    if action in ("address_change", "phone_change"):
        cap = action
        r.verdict = "REQUIRES_APPROVAL"
        r.fire("R12", f"{'Address' if cap == 'address_change' else 'Phone'} changes need human verification")
        if cap not in p.carrier_capabilities:
            r.verdict = "REQUIRES_APPROVAL"
            r.fire("R04", f"Carrier API does not support {cap.replace('_', ' ')}; needs manual coordination")
        return r

    # reattempt / reschedule
    if p.purpose == "ndr_recovery" and p.attempt_count >= cfg.max_attempts_before_rto:
        r.fire("R03", f"{p.attempt_count} attempts already made (limit {cfg.max_attempts_before_rto}); "
                      "the next step is an RTO decision by a person")
        r.alternatives.append("rto")
        return r

    cap_name = action
    caps = p.carrier_capabilities
    if cap_name not in caps:
        if action == "reschedule" and "reattempt" in caps and p.requested_date == p.today + timedelta(days=1):
            action = r.action = "reattempt"
            cap_name = "reattempt"
            r.fire("R04", "Carrier has no reschedule API; a next-day reattempt covers the requested date")
        else:
            r.fire("R04", f"Carrier does not support {action} through its API")
            r.alternatives.append("store_preference")
            return r
    constraints = caps.get(cap_name) or {}

    target = p.requested_date or (p.today + timedelta(days=1))
    r.requested_date = target
    days_ahead = (target - p.today).days
    horizon = int(constraints.get("max_days_ahead", 3))
    if days_ahead < 0:
        r.fire("R05", "Requested date is in the past")
        return r
    if days_ahead > horizon:
        r.fire("R06", f"Carrier accepts dates up to {horizon} days ahead; customer asked for {days_ahead}")
        r.alternatives.append(f"latest_date:{(p.today + timedelta(days=horizon)).isoformat()}")
        return r
    if days_ahead == 0:
        cutoff = int(constraints.get("same_day_cutoff_hour", 12))
        if p.now.hour >= cutoff:
            r.fire("R07", f"Same-day reattempts close at {cutoff}:00; next possible attempt is tomorrow")
            r.alternatives.append(f"date:{(p.today + timedelta(days=1)).isoformat()}")
            return r

    windows = constraints.get("windows")
    if p.requested_window and not _window_ok(p.requested_window, windows):
        r.carrier_window_supported = False
        r.requested_window = None
        r.fire("R13", "Carrier does not offer that time window; it is stored as a preference, not promised"
               if windows else "Carrier does not accept time windows; the window is stored as a preference, not promised")

    needs_approval = False
    if days_ahead > cfg.max_auto_reschedule_days:
        needs_approval = True
        r.fire("R05", f"{days_ahead} days ahead exceeds the auto limit of {cfg.max_auto_reschedule_days}")
    if action not in cfg.auto_actions:
        needs_approval = True
        r.fire("R08", f"Merchant policy requires approval for {action}")
    if p.payment_mode == "COD" and p.cod_amount_paise >= cfg.cod_high_value_approval_paise and days_ahead > 1:
        needs_approval = True
        r.fire("R09", f"COD amount ₹{p.cod_amount_paise / 100:,.0f} is above the high-value threshold")
    if p.sla_due_at and p.now > p.sla_due_at:
        needs_approval = True
        r.fire("R10", "SLA deadline has passed")

    if needs_approval:
        r.verdict = "REQUIRES_APPROVAL"
        return r
    r.verdict = "ALLOWED"
    r.fire("R08", f"{action.capitalize()} on {target.isoformat()} is within policy and carrier limits")
    return r
