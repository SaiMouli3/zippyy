"""Contact guard: every outbound message or call is checked here first, and every check is recorded in
`contact_attempts` (allowed or blocked, with the reason and the policy version).

It enforces opt-outs, evidence-backed consent, quiet hours and voice windows in the merchant's timezone,
per-customer/per-case frequency caps, merchant daily call volume, concurrent calls and the daily voice budget.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform import clock, policies
from app.platform.models import ConsentRecord, ContactAttempt, Customer, Merchant, VoiceCall


# Replies inside the customer's own conversation, and notifications of the outcome of something the customer
# asked for, do not count towards the proactive-contact cap (opt-out, consent and quiet hours still apply).
EXEMPT_FROM_CAP = ("reply", "confirmation")


@dataclass
class GuardResult:
    allowed: bool
    reason: str | None = None
    retry_at: datetime | None = None  # when the block is time-based (quiet hours / window), the next legal time
    attempt_id: str | None = None


def local_now(merchant: Merchant, at: datetime | None = None) -> datetime:
    return (at or clock.now()).astimezone(ZoneInfo(merchant.timezone or "Asia/Kolkata"))


def _in_quiet_hours(t: time, start: time, end: time) -> bool:
    return (t >= start or t < end) if start > end else (start <= t < end)


def next_allowed_time(merchant: Merchant, start: time, end: time, at: datetime | None = None,
                      window: bool = False) -> datetime:
    """Next instant outside quiet hours (window=False) or inside [start, end) (window=True), in UTC."""
    tz = ZoneInfo(merchant.timezone or "Asia/Kolkata")
    local = (at or clock.now()).astimezone(tz)
    candidate_day = local.date()
    for _ in range(3):
        if window:
            open_at = datetime.combine(candidate_day, start, tz)
            close_at = datetime.combine(candidate_day, end, tz)
            if local < open_at:
                return open_at.astimezone(ZoneInfo("UTC"))
            if open_at <= local < close_at:
                return local.astimezone(ZoneInfo("UTC"))
        else:
            if not _in_quiet_hours(local.timetz().replace(tzinfo=None), start, end):
                return local.astimezone(ZoneInfo("UTC"))
            quiet_end = datetime.combine(candidate_day, end, tz)
            if quiet_end > local:
                return quiet_end.astimezone(ZoneInfo("UTC"))
        candidate_day = candidate_day + timedelta(days=1)
        local = datetime.combine(candidate_day, time(0, 0), tz)
    return local.astimezone(ZoneInfo("UTC"))


def has_consent(db: Session, customer: Customer, channel: str) -> bool:
    latest = db.scalars(select(ConsentRecord).where(
        ConsentRecord.customer_id == customer.id, ConsentRecord.channel == channel
    ).order_by(ConsentRecord.recorded_at.desc())).first()
    return latest is not None and latest.status == "granted"


def check(db: Session, merchant: Merchant, customer: Customer, channel: str, purpose: str,
          shipment_id: str | None = None, ndr_case_id: str | None = None, record: bool = True,
          is_reply_in_session: bool = False) -> GuardResult:
    """`is_reply_in_session`: a direct answer to a message the customer just sent (WhatsApp service window)."""
    pv, cp = policies.contact_policy(db, merchant.id)
    _, ac = policies.agent_config(db, merchant.id)
    now = clock.now()
    local = local_now(merchant, now)
    result = GuardResult(True)

    def block(reason: str, retry_at: datetime | None = None) -> GuardResult:
        return GuardResult(False, reason, retry_at)

    if not ac.agent_enabled:
        result = block("agent_disabled")
    elif channel not in ac.channels:
        result = block(f"channel_disabled:{channel}")
    elif customer.opted_out_at is not None and (cp.honour_opt_out_across_channels or customer.opt_out_source == channel):
        result = block("customer_opted_out")
    elif customer.pii_erased_at is not None:
        result = block("customer_erased")
    elif channel == "whatsapp" and cp.require_whatsapp_consent and not has_consent(db, customer, "whatsapp"):
        result = block("no_whatsapp_consent")
    elif channel == "voice" and cp.require_voice_consent and not has_consent(db, customer, "voice"):
        result = block("no_voice_consent")
    elif not is_reply_in_session and _in_quiet_hours(local.time(), cp.quiet_start, cp.quiet_end):
        result = block("quiet_hours", next_allowed_time(merchant, cp.quiet_start, cp.quiet_end, now))
    elif channel == "voice" and not (cp.voice_window_start <= local.time() < cp.voice_window_end):
        result = block("outside_voice_window", next_allowed_time(merchant, cp.voice_window_start, cp.voice_window_end, now, window=True))
    else:
        day_start = now - timedelta(hours=24)
        # Only proactive contacts count towards the cap; answering a customer inside their own conversation does not.
        contacts_today = db.scalar(select(func.count()).select_from(ContactAttempt).where(
            ContactAttempt.customer_id == customer.id, ContactAttempt.outcome == "allowed",
            ContactAttempt.purpose.not_in(EXEMPT_FROM_CAP), ContactAttempt.created_at >= day_start)) or 0
        if not is_reply_in_session and purpose not in EXEMPT_FROM_CAP and contacts_today >= cp.max_contacts_per_customer_per_day:
            result = block("customer_daily_contact_limit", now + timedelta(hours=12))
        elif channel == "voice":
            calls_customer = db.scalar(select(func.count()).select_from(VoiceCall).where(
                VoiceCall.customer_id == customer.id, VoiceCall.created_at >= day_start)) or 0
            calls_case = db.scalar(select(func.count()).select_from(VoiceCall).where(
                VoiceCall.ndr_case_id == ndr_case_id)) if ndr_case_id else 0
            calls_merchant = db.scalar(select(func.count()).select_from(VoiceCall).where(
                VoiceCall.merchant_id == merchant.id, VoiceCall.created_at >= day_start)) or 0
            concurrent = db.scalar(select(func.count()).select_from(VoiceCall).where(
                VoiceCall.merchant_id == merchant.id, VoiceCall.status.in_(("queued", "initiated", "ringing", "answered")))) or 0
            spend = db.scalar(select(func.coalesce(func.sum(VoiceCall.cost_paise), 0)).where(
                VoiceCall.merchant_id == merchant.id, VoiceCall.created_at >= day_start)) or 0
            if calls_customer >= cp.max_voice_calls_per_customer_per_day:
                result = block("customer_daily_call_limit", now + timedelta(hours=12))
            elif ndr_case_id and (calls_case or 0) >= ac.max_voice_attempts_per_case:
                result = block("case_call_attempts_exhausted")
            elif calls_merchant >= cp.max_calls_per_merchant_per_day:
                result = block("merchant_daily_call_limit", now + timedelta(hours=6))
            elif concurrent >= cp.max_concurrent_calls:
                result = block("concurrent_call_limit", now + timedelta(minutes=5))
            elif spend >= cp.daily_voice_budget_paise:
                result = block("daily_voice_budget_exhausted", now + timedelta(hours=6))

    if record:
        row = ContactAttempt(merchant_id=merchant.id, customer_id=customer.id, shipment_id=shipment_id,
                             ndr_case_id=ndr_case_id, channel=channel, purpose=purpose,
                             outcome="allowed" if result.allowed else "blocked", block_reason=result.reason,
                             policy_version_id=pv.id)
        db.add(row)
        db.flush()
        result.attempt_id = row.id
    return result
