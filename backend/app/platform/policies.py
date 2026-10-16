"""Schema-validated, versioned agent configuration and contact policy.

A change never edits a row: it inserts version N+1 and deactivates N, in one transaction, with an audit
record. Decisions, contact attempts and agent tasks store the version id they ran under.
"""
from datetime import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.platform import audit
from app.platform.models import LANGS, PolicyVersion

RULES_VERSION = "rules-2026.10.1"

Lang = Literal["en", "hi", "te", "ta", "kn", "ml", "mr", "bn", "gu", "pa", "or"]
Action = Literal["reattempt", "reschedule", "address_change", "phone_change", "rto", "cancel"]


class _Cfg(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class AgentConfig(_Cfg):
    agent_enabled: bool = True
    ndr_auto_contact: bool = True
    pre_delivery_enabled: bool = True
    pre_delivery_trigger: Literal["out_for_delivery", "eta_window", "both"] = "out_for_delivery"
    pre_delivery_cod_only: bool = False
    pre_delivery_min_order_value_paise: int = Field(default=0, ge=0)
    supported_languages: list[Lang] = Field(default_factory=lambda: ["en", "hi", "te", "ta", "kn"])
    voice_languages: list[Lang] = Field(default_factory=lambda: ["en", "hi", "te", "ta", "kn", "ml", "mr", "bn"])
    channels: list[Literal["whatsapp", "voice"]] = Field(default_factory=lambda: ["whatsapp", "voice"])
    whatsapp_reply_wait_minutes: int = Field(default=90, ge=5, le=24 * 60)
    pre_delivery_reply_wait_minutes: int = Field(default=45, ge=5, le=12 * 60)
    max_voice_attempts_per_case: int = Field(default=2, ge=0, le=5)
    voice_retry_minutes: list[int] = Field(default_factory=lambda: [60, 180])
    max_clarifications: int = Field(default=2, ge=0, le=4)
    intent_confidence_threshold: float = Field(default=0.7, ge=0.3, le=0.99)
    language_switch_confidence: float = Field(default=0.8, ge=0.5, le=0.99)
    language_preference_save_confidence: float = Field(default=0.85, ge=0.5, le=0.99)
    max_auto_reschedule_days: int = Field(default=2, ge=0, le=7)
    max_attempts_before_rto: int = Field(default=3, ge=1, le=5)
    auto_actions: list[Action] = Field(default_factory=lambda: ["reattempt", "reschedule"])
    approval_required_actions: list[Action] = Field(default_factory=lambda: ["address_change", "phone_change", "rto", "cancel"])
    cod_high_value_approval_paise: int = Field(default=1_000_000, ge=0)  # ₹10,000
    sla_hours: int = Field(default=24, ge=2, le=96)
    sla_warning_hours: int = Field(default=4, ge=1, le=24)
    no_response_close_policy: Literal["escalate", "close_after_sla"] = "escalate"
    escalate_on_carrier_rejection: bool = True

    @field_validator("voice_retry_minutes")
    @classmethod
    def _retries(cls, v: list[int]) -> list[int]:
        if any(m < 15 or m > 24 * 60 for m in v):
            raise ValueError("retry intervals must be between 15 minutes and 24 hours")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        overlap = set(self.auto_actions) & set(self.approval_required_actions)
        if overlap:
            raise ValueError(f"actions cannot be both automatic and approval-required: {sorted(overlap)}")
        if "rto" in self.auto_actions or "cancel" in self.auto_actions:
            raise ValueError("RTO and cancellation always require human approval")
        if self.sla_warning_hours >= self.sla_hours:
            raise ValueError("SLA warning must be shorter than the SLA")
        return self


class ContactPolicy(_Cfg):
    quiet_start: time = time(21, 0)  # merchant local time
    quiet_end: time = time(9, 0)
    voice_window_start: time = time(10, 0)
    voice_window_end: time = time(19, 30)
    max_contacts_per_customer_per_day: int = Field(default=4, ge=1, le=10)
    max_voice_calls_per_customer_per_day: int = Field(default=2, ge=0, le=5)
    max_calls_per_merchant_per_day: int = Field(default=5000, ge=0)
    max_concurrent_calls: int = Field(default=10, ge=1, le=200)
    daily_voice_budget_paise: int = Field(default=500_000, ge=0)  # ₹5,000/day
    require_whatsapp_consent: bool = True
    require_voice_consent: bool = False  # transactional delivery calls; set true where regulation requires
    whatsapp_fallback_to_voice: bool = True
    honour_opt_out_across_channels: bool = True
    ops_failure_notifications: bool = True

    @model_validator(mode="after")
    def _windows(self):
        if self.voice_window_start >= self.voice_window_end:
            raise ValueError("voice window must start before it ends")
        return self


SCHEMAS = {"agent_config": AgentConfig, "contact_policy": ContactPolicy}


def validate(kind: str, config: dict) -> BaseModel:
    if kind not in SCHEMAS:
        raise DomainError("UNKNOWN_POLICY_KIND", f"unknown policy kind {kind}", 404)
    return SCHEMAS[kind].model_validate(config)


def active(db: Session, merchant_id: str, kind: str) -> tuple[PolicyVersion, BaseModel]:
    row = db.scalars(select(PolicyVersion).where(
        PolicyVersion.merchant_id == merchant_id, PolicyVersion.kind == kind, PolicyVersion.is_active.is_(True)
    )).first()
    if row is None:
        row = PolicyVersion(merchant_id=merchant_id, kind=kind, version=1,
                            config=SCHEMAS[kind]().model_dump(mode="json"), is_active=True, change_note="defaults")
        db.add(row)
        db.flush()
    return row, SCHEMAS[kind].model_validate(row.config)


def agent_config(db: Session, merchant_id: str) -> tuple[PolicyVersion, AgentConfig]:
    return active(db, merchant_id, "agent_config")  # type: ignore[return-value]


def contact_policy(db: Session, merchant_id: str) -> tuple[PolicyVersion, ContactPolicy]:
    return active(db, merchant_id, "contact_policy")  # type: ignore[return-value]


def diff(old: dict, new: dict) -> dict:
    return {k: {"from": old.get(k), "to": new.get(k)} for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)}


def publish(db: Session, merchant_id: str, kind: str, config: dict, actor: audit.Actor, note: str | None,
            dry_run: bool = False) -> dict:
    current, _ = active(db, merchant_id, kind)
    validated = validate(kind, config).model_dump(mode="json")
    changes = diff(current.config, validated)
    if dry_run or not changes:
        return {"dryRun": dry_run, "changes": changes, "version": current.version, "applied": False}
    db.execute(update(PolicyVersion).where(PolicyVersion.id == current.id).values(is_active=False))
    row = PolicyVersion(merchant_id=merchant_id, kind=kind, version=current.version + 1, config=validated,
                        is_active=True, change_note=(note or "")[:500] or None, created_by=actor.id)
    db.add(row)
    db.flush()
    audit.record(db, actor, merchant_id, "policy_version", row.id, f"{kind}.published",
                 before={"version": current.version}, after={"version": row.version, "changes": changes}, reason=note)
    return {"dryRun": False, "changes": changes, "version": row.version, "applied": True}


assert set(LANGS) >= {"en", "hi", "te"}
