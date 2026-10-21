"""Append-only audit trail. Written in the same transaction as the change it describes."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.platform.models import AuditLog

_SENSITIVE_KEYS = {"phone", "phone_e164", "email", "line1", "line2", "landmark", "token", "secret", "password",
                   "api_key", "authorization", "access_token"}


@dataclass
class Actor:
    type: str  # user | api_key | agent | carrier | system | provider
    id: str | None = None
    label: str | None = None
    request_id: str | None = None
    ip: str | None = None


SYSTEM = Actor("system", "system", "Zippyy platform")
AGENT = Actor("agent", "zippyy-agent", "Zippyy agent")


def scrub(value):
    """Remove secrets and raw PII from anything that is about to be persisted for observability."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if k.lower() in _SENSITIVE_KEYS else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def record(db: Session, actor: Actor, merchant_id: str | None, entity_type: str, entity_id: str, action: str,
           before: dict | None = None, after: dict | None = None, reason: str | None = None) -> AuditLog:
    row = AuditLog(
        merchant_id=merchant_id, actor_type=actor.type, actor_id=actor.id, actor_label=actor.label,
        entity_type=entity_type, entity_id=entity_id, action=action,
        before=scrub(before) if before else None, after=scrub(after) if after else None,
        reason=reason, request_id=actor.request_id, ip=actor.ip,
    )
    db.add(row)
    return row
