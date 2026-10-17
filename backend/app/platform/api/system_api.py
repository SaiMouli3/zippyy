import asyncio
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import new_session
from app.domain.errors import DomainError, not_found
from app.platform import audit, clock, policies
from app.platform.api.common import Page, iso, page_response
from app.platform.auth import Principal, get_principal, require, tenant_db
from app.platform.ingest import IngestError, ingest_webhook
from app.platform.models import (AgentTask, ApiKey, AuditLog, Carrier, CarrierCapability, DeliveryPreference, Job,
                                 Membership, Merchant, MerchantSettings, MessageTemplate, OutboxEvent, PolicyVersion,
                                 ProviderCall, User, WebhookInbox, WebhookQuarantine)
from app.platform.rbac import API_KEY_SCOPES
from app.platform.security import crypto

router = APIRouter(tags=["system"])


# ================================================================== settings & policies
class SettingsIn(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    messageRetentionDays: int | None = Field(default=None, ge=30, le=3650)
    transcriptRetentionDays: int | None = Field(default=None, ge=7, le=3650)
    callRecordingEnabled: bool | None = None
    unmaskRequiresReason: bool | None = None
    opsAlertEmail: str | None = Field(default=None, max_length=254)


def _settings(db: Session, merchant_id: str) -> MerchantSettings:
    s = db.get(MerchantSettings, merchant_id)
    if s is None:
        s = MerchantSettings(merchant_id=merchant_id)
        db.add(s)
        db.flush()
    return s


def _settings_out(s: MerchantSettings, m: Merchant) -> dict:
    return {"merchant": {"id": m.id, "code": m.code, "brandName": m.brand_name, "legalName": m.legal_name,
                         "plan": m.plan, "isDemo": m.is_demo},
            "timezone": s.timezone, "messageRetentionDays": s.message_retention_days,
            "transcriptRetentionDays": s.transcript_retention_days, "callRecordingEnabled": s.call_recording_enabled,
            "unmaskRequiresReason": s.unmask_requires_reason, "opsAlertEmail": s.ops_alert_email,
            "updatedAt": iso(s.updated_at)}


@router.get("/api/v1/merchant/settings")
def get_settings_(p: Principal = Depends(require("settings.read")), db: Session = Depends(tenant_db)):
    s = _settings(db, p.merchant_id)
    db.commit()
    return _settings_out(s, db.get(Merchant, p.merchant_id))


@router.patch("/api/v1/merchant/settings")
def patch_settings(body: SettingsIn, p: Principal = Depends(require("settings.write")), db: Session = Depends(tenant_db)):
    s = _settings(db, p.merchant_id)
    before = _settings_out(s, db.get(Merchant, p.merchant_id))
    mapping = {"timezone": "timezone", "messageRetentionDays": "message_retention_days",
               "transcriptRetentionDays": "transcript_retention_days", "callRecordingEnabled": "call_recording_enabled",
               "unmaskRequiresReason": "unmask_requires_reason", "opsAlertEmail": "ops_alert_email"}
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "timezone" and v:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(v)
            except Exception as exc:
                raise DomainError("INVALID_TIMEZONE", "Unknown timezone", 422) from exc
            db.get(Merchant, p.merchant_id).timezone = v
        setattr(s, mapping[k], v)
    s.updated_by = p.user_id
    after = _settings_out(s, db.get(Merchant, p.merchant_id))
    audit.record(db, p.actor, p.merchant_id, "merchant_settings", p.merchant_id, "settings.updated", before=before, after=after)
    db.commit()
    return after


def _policy_out(row: PolicyVersion, history: list[PolicyVersion]) -> dict:
    return {"kind": row.kind, "version": row.version, "config": row.config, "changeNote": row.change_note,
            "createdAt": iso(row.created_at), "createdBy": row.created_by, "rulesVersion": policies.RULES_VERSION,
            "history": [{"version": h.version, "createdAt": iso(h.created_at), "changeNote": h.change_note,
                         "createdBy": h.created_by, "active": h.is_active} for h in history]}


class PolicyIn(BaseModel):
    config: dict
    changeNote: str = Field(min_length=3, max_length=500)
    dryRun: bool = False


def _policy_routes(kind: str, path: str, read_perm: str, write_perm: str):
    @router.get(path)
    def get_policy(p: Principal = Depends(require(read_perm)), db: Session = Depends(tenant_db)):
        row, _ = policies.active(db, p.merchant_id, kind)
        hist = list(db.scalars(select(PolicyVersion).where(PolicyVersion.merchant_id == p.merchant_id,
                                                           PolicyVersion.kind == kind).order_by(PolicyVersion.version.desc()).limit(20)))
        db.commit()
        return {**_policy_out(row, hist), "schema": policies.SCHEMAS[kind].model_json_schema(by_alias=False)}

    @router.patch(path)
    def patch_policy(body: PolicyIn, p: Principal = Depends(require(write_perm)), db: Session = Depends(tenant_db)):
        try:
            result = policies.publish(db, p.merchant_id, kind, body.config, p.actor, body.changeNote, body.dryRun)
        except ValueError as exc:  # pydantic ValidationError subclasses ValueError
            errors = getattr(exc, "errors", lambda: [{"msg": str(exc)}])()
            raise HTTPException(422, [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg")} for e in errors])
        db.commit()
        return result

    @router.get(path + "/versions/{version}")
    def get_version(version: int, p: Principal = Depends(require(read_perm)), db: Session = Depends(tenant_db)):
        row = db.scalars(select(PolicyVersion).where(PolicyVersion.merchant_id == p.merchant_id, PolicyVersion.kind == kind,
                                                     PolicyVersion.version == version)).first()
        if row is None:
            raise not_found("Policy version")
        return {"version": row.version, "config": row.config, "changeNote": row.change_note, "createdAt": iso(row.created_at)}


_policy_routes("agent_config", "/api/v1/merchant/agent-config", "agent_config.read", "agent_config.write")
_policy_routes("contact_policy", "/api/v1/merchant/contact-policies", "policies.read", "policies.write")


@router.get("/api/v1/merchant/templates")
def templates(p: Principal = Depends(require("policies.read")), db: Session = Depends(tenant_db)):
    rows = db.scalars(select(MessageTemplate).where(MessageTemplate.merchant_id == p.merchant_id)
                      .order_by(MessageTemplate.code, MessageTemplate.language))
    return {"items": [{"id": t.id, "code": t.code, "language": t.language, "version": t.version, "status": t.status,
                       "category": t.category, "providerTemplateName": t.provider_template_name, "body": t.body}
                      for t in rows]}


@router.get("/api/v1/merchant/carriers")
def carriers(p: Principal = Depends(require("integrations.read")), db: Session = Depends(tenant_db)):
    out = []
    for c in db.scalars(select(Carrier).order_by(Carrier.name)):
        caps = {cap.capability: cap.constraints for cap in db.scalars(select(CarrierCapability).where(CarrierCapability.carrier_id == c.id))}
        out.append({"code": c.code, "name": c.name, "mode": c.api_mode, "active": c.active, "timeoutMs": c.timeout_ms,
                    "capabilities": caps})
    return {"items": out}


# ================================================================== users & API keys
@router.get("/api/v1/merchant/users")
def users(p: Principal = Depends(require("settings.read")), db: Session = Depends(tenant_db)):
    rows = db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id)
                      .where(Membership.merchant_id == p.merchant_id).order_by(User.name)).all()
    return {"items": [{"id": u.id, "name": u.name, "email": u.email if p.can("users.manage") else None,
                       "role": m.role, "active": u.is_active, "lastLoginAt": iso(u.last_login_at)} for u, m in rows]}


class KeyIn(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expiresInDays: int | None = Field(default=365, ge=1, le=730)


@router.get("/api/v1/merchant/api-keys")
def list_keys(p: Principal = Depends(require("api_keys.manage")), db: Session = Depends(tenant_db)):
    rows = db.scalars(select(ApiKey).where(ApiKey.merchant_id == p.merchant_id).order_by(ApiKey.created_at.desc()))
    return {"items": [{"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "createdAt": iso(k.created_at),
                       "lastUsedAt": iso(k.last_used_at), "expiresAt": iso(k.expires_at), "revokedAt": iso(k.revoked_at)}
                      for k in rows], "availableScopes": sorted(API_KEY_SCOPES)}


@router.post("/api/v1/merchant/api-keys", status_code=201)
def create_key(body: KeyIn, p: Principal = Depends(require("api_keys.manage")), db: Session = Depends(tenant_db)):
    bad = set(body.scopes) - API_KEY_SCOPES
    if bad:
        raise DomainError("INVALID_SCOPE", f"Unknown scopes: {', '.join(sorted(bad))}", 422)
    raw = "zpy_live_" + secrets.token_urlsafe(32)
    key = ApiKey(merchant_id=p.merchant_id, name=body.name, prefix=raw[:16], key_hash=crypto.token_hash(raw),
                 scopes=sorted(set(body.scopes)), created_by=p.user_id,
                 expires_at=clock.now() + timedelta(days=body.expiresInDays) if body.expiresInDays else None)
    db.add(key)
    db.flush()
    audit.record(db, p.actor, p.merchant_id, "api_key", key.id, "api_key.created", after={"name": body.name, "scopes": key.scopes})
    db.commit()
    return {"id": key.id, "key": raw, "prefix": key.prefix, "note": "Shown once. Store it in your secret manager."}


@router.post("/api/v1/merchant/api-keys/{key_id}/revoke")
def revoke_key(key_id: str, p: Principal = Depends(require("api_keys.manage")), db: Session = Depends(tenant_db)):
    key = db.get(ApiKey, key_id)
    if key is None or key.merchant_id != p.merchant_id:
        raise not_found("API key")
    if key.revoked_at is None:
        key.revoked_at = clock.now()
        audit.record(db, p.actor, p.merchant_id, "api_key", key.id, "api_key.revoked")
        db.commit()
    return {"ok": True}


# ================================================================== audit
@router.get("/api/v1/audit-logs")
def audit_logs(page: Page = Depends(), entityType: str | None = None, entityId: str | None = None, action: str | None = None,
               actorType: str | None = None, p: Principal = Depends(require("audit.read")), db: Session = Depends(tenant_db)):
    f = [AuditLog.merchant_id == p.merchant_id]
    if entityType:
        f.append(AuditLog.entity_type == entityType)
    if entityId:
        f.append(AuditLog.entity_id == entityId)
    if action:
        f.append(AuditLog.action.like(f"{action}%"))
    if actorType:
        f.append(AuditLog.actor_type == actorType)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*f)) or 0
    rows = db.scalars(select(AuditLog).where(*f).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                      .offset(page.offset).limit(page.size))
    return page_response([{"id": r.id, "at": iso(r.created_at), "actorType": r.actor_type, "actorId": r.actor_id,
                           "actor": r.actor_label, "entityType": r.entity_type, "entityId": r.entity_id,
                           "action": r.action, "before": r.before, "after": r.after, "reason": r.reason,
                           "requestId": r.request_id} for r in rows], total, page)


# ================================================================== integrations & health
def _provider_stats(db: Session, provider_prefix: str) -> dict:
    since = clock.now() - timedelta(hours=1)
    rows = db.execute(select(ProviderCall.ok, ProviderCall.latency_ms, ProviderCall.created_at).where(
        ProviderCall.provider.like(f"{provider_prefix}%"), ProviderCall.created_at >= since)).all()
    total = len(rows)
    errors = sum(1 for r in rows if not r.ok)
    lat = sorted(r.latency_ms for r in rows)
    last_ok = db.scalar(select(func.max(ProviderCall.created_at)).where(ProviderCall.provider.like(f"{provider_prefix}%"),
                                                                        ProviderCall.ok.is_(True)))
    return {"calls1h": total, "errors1h": errors, "errorRate1h": round(errors / total, 4) if total else None,
            "p95LatencyMs": lat[int(len(lat) * 0.95) - 1] if lat else None, "lastSuccessAt": iso(last_ok)}


def _state(stats: dict, mode: str) -> str:
    if mode == "not_configured":
        return "not_configured"
    if mode == "simulated":
        return "simulated"
    if stats["calls1h"] and stats["errorRate1h"] is not None and stats["errorRate1h"] > 0.5:
        return "failing"
    if stats["calls1h"] and stats["errorRate1h"] and stats["errorRate1h"] > 0.1:
        return "degraded"
    return "connected"


def _intent_usage(db: Session, merchant_id: str) -> dict:
    from app.platform.models import IntentExtraction
    since = clock.now() - timedelta(hours=24)
    f = [IntentExtraction.merchant_id == merchant_id, IntentExtraction.created_at >= since]
    total = db.scalar(select(func.count()).select_from(IntentExtraction).where(*f)) or 0
    model = db.scalar(select(func.count()).select_from(IntentExtraction).where(*f, IntentExtraction.extractor.like("llm:%"))) or 0
    return {"modelCalls24h": int(model), "extractions24h": int(total)}


def _intent_provider(s) -> dict:
    if s.intent_extractor == "sarvam_llm" and s.sarvam_api_key:
        name, detail = s.sarvam_llm_model, "Sarvam chat completions with JSON-schema output; falls back to rules"
    elif s.intent_extractor == "openai_compatible" and s.llm_base_url and s.llm_api_key and s.llm_model:
        from urllib.parse import urlparse
        name, detail = s.llm_model, f"OpenAI-compatible API at {urlparse(s.llm_base_url).netloc}; output schema-validated, falls back to rules"
    else:
        return {"id": "intent", "name": "Intent extraction", "provider": "rules", "mode": "local", "state": "connected",
                "detail": "Deterministic multilingual rules (no external calls)" + (
                    f" — INTENT_EXTRACTOR={s.intent_extractor} is set but its credentials are missing"
                    if s.intent_extractor != "rules" else "")}
    return {"id": "intent", "name": "Intent extraction", "provider": name, "mode": "live", "state": "connected", "detail": detail}


@router.get("/api/v1/integrations")
def integrations(p: Principal = Depends(require("integrations.read")), db: Session = Depends(tenant_db)):
    s = get_settings()
    merchant = db.get(Merchant, p.merchant_id)
    sysdb = new_session(system=True)
    try:
        wa_mode = "simulated" if (merchant.is_demo or s.whatsapp_provider == "simulator") else (
            "live" if (s.meta_access_token and s.meta_phone_number_id and s.meta_app_secret) else "not_configured")
        voice_mode = "simulated" if (merchant.is_demo or s.voice_provider == "simulator") else (
            "live" if (s.sarvam_agents_api_key and s.sarvam_app_id) else "not_configured")
        wa_stats = _provider_stats(sysdb, "whatsapp:")
        voice_stats = _provider_stats(sysdb, "voice:")
        providers = [
            {"id": "whatsapp", "name": "WhatsApp Business", "provider": "simulator" if wa_mode == "simulated" else "meta_cloud",
             "mode": wa_mode, "state": _state(wa_stats, wa_mode), **wa_stats,
             "detail": "Simulated for this workspace: no real messages are sent" if wa_mode == "simulated" else (
                 "Meta Cloud API" if wa_mode == "live" else "Set META_PHONE_NUMBER_ID, META_ACCESS_TOKEN, META_APP_SECRET")},
            {"id": "voice", "name": "Sarvam voice agent", "provider": "simulator" if voice_mode == "simulated" else "sarvam_agents",
             "mode": voice_mode, "state": _state(voice_stats, voice_mode), **voice_stats,
             "detail": "Simulated: the in-house conversation engine plays scripted demo customers" if voice_mode == "simulated" else (
                 "Sarvam hosted voice agent (instant outbound)" if voice_mode == "live" else
                 "Set SARVAM_AGENTS_API_KEY, SARVAM_ORG_ID, SARVAM_WORKSPACE_ID, SARVAM_APP_ID, SARVAM_APP_VERSION, SARVAM_CONNECTION_ID, SARVAM_AGENT_PHONE_NUMBER")},
            {**_intent_provider(s), **_intent_usage(db, p.merchant_id)},
        ]
        carrier_rows = []
        for c in sysdb.scalars(select(Carrier).order_by(Carrier.name)):
            st = _provider_stats(sysdb, f"carrier:{c.code}")
            carrier_rows.append({"code": c.code, "name": c.name, "mode": c.api_mode, "active": c.active,
                                 "state": _state(st, "simulated" if c.api_mode == "simulated" else "live"), **st})
        day = clock.now() - timedelta(hours=24)
        inbox = dict(sysdb.execute(select(WebhookInbox.state, func.count()).where(WebhookInbox.received_at >= day)
                                   .group_by(WebhookInbox.state)).all())
        quarantine = dict(sysdb.execute(select(WebhookQuarantine.reason, func.count()).where(
            WebhookQuarantine.created_at >= day, WebhookQuarantine.resolved_at.is_(None)).group_by(WebhookQuarantine.reason)).all())
        queued = sysdb.scalar(select(func.count()).select_from(Job).where(Job.status == "queued", Job.run_at <= clock.now())) or 0
        oldest = sysdb.scalar(select(func.min(Job.run_at)).where(Job.status == "queued", Job.run_at <= clock.now()))
        dead = sysdb.scalar(select(func.count()).select_from(Job).where(Job.status == "dead", Job.created_at >= day)) or 0
        running = sysdb.scalar(select(func.count()).select_from(Job).where(Job.status == "running")) or 0
        scheduled = sysdb.scalar(select(func.count()).select_from(Job).where(Job.status == "queued", Job.run_at > clock.now())) or 0
        outbox_lag = sysdb.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))) or 0
        last_processed = sysdb.scalar(select(func.max(Job.finished_at)).where(Job.status == "done"))
    finally:
        sysdb.close()
    # Healthy means nothing due is waiting too long; it does not claim recent activity (see lastProcessedAt).
    worker_alive = not (queued > 0 and oldest is not None and clock.now() - clock.as_utc(oldest) > timedelta(minutes=2))
    return {"providers": providers, "carriers": carrier_rows,
            "webhooks": {"last24h": inbox, "quarantinedOpen": quarantine},
            "jobs": {"due": queued, "scheduled": scheduled, "running": running, "dead24h": dead,
                     "oldestDueAt": iso(oldest), "lastProcessedAt": iso(last_processed),
                     "workerHealthy": worker_alive},
            "outbox": {"unpublished": outbox_lag},
            "environment": {"appEnv": s.app_env, "signatureRequired": s.carrier_webhook_signature_required},
            "generatedAt": clock.now().isoformat()}


@router.get("/health/live")
def live():
    return {"ok": True}


@router.get("/health/ready")
async def ready():
    checks = {}
    def db_check():
        db = new_session(system=True)
        try:
            db.execute(text("SELECT 1"))
            return True
        finally:
            db.close()
    try:
        checks["database"] = await run_in_threadpool(db_check)
    except Exception:  # noqa: BLE001
        checks["database"] = False
    try:
        from app.cache import get_redis
        checks["redis"] = bool(await asyncio.wait_for(get_redis().ping(), 1.0))
    except Exception:  # noqa: BLE001
        checks["redis"] = False  # degraded, not fatal: caching and rate limits fall back
    ok = checks["database"]
    if not ok:
        raise HTTPException(503, {"ok": False, "checks": checks})
    return {"ok": True, "checks": checks}


# ================================================================== pre-delivery campaigns
@router.get("/api/v1/pre-delivery")
def predelivery(page: Page = Depends(), status: str | None = None, attention: bool = False,
                p: Principal = Depends(require("ndr.read")), db: Session = Depends(tenant_db)):
    from app.models import Order, Shipment
    from app.platform.models import Customer
    f = [AgentTask.merchant_id == p.merchant_id, AgentTask.task_type == "pre_delivery"]
    if status:
        f.append(AgentTask.status.in_(status.split(",")))
    total = db.scalar(select(func.count()).select_from(AgentTask).where(*f)) or 0
    tasks = list(db.scalars(select(AgentTask).where(*f).order_by(AgentTask.created_at.desc(), AgentTask.id).limit(2000 if attention else page.size)
                            .offset(0 if attention else page.offset)))
    if attention:
        tasks = [t for t in tasks if (t.state or {}).get("needs_attention")]
        total = len(tasks)
        tasks = tasks[page.offset:page.offset + page.size]
    ships = {s.id: s for s in db.scalars(select(Shipment).where(Shipment.id.in_([t.shipment_id for t in tasks])))} if tasks else {}
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_([s.order_id for s in ships.values()])))} if ships else {}
    custs = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_([o.customer_id for o in orders.values()])))} if orders else {}
    prefs = {}
    if tasks:
        for pr in db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id.in_([t.shipment_id for t in tasks]),
                                                              DeliveryPreference.ndr_case_id.is_(None)).order_by(DeliveryPreference.created_at)):
            prefs[pr.shipment_id] = pr
    items = []
    for t in tasks:
        s = ships.get(t.shipment_id)
        o = orders.get(s.order_id) if s else None
        c = custs.get(o.customer_id) if o else None
        pr = prefs.get(t.shipment_id)
        items.append({"taskId": t.id, "shipmentId": t.shipment_id, "awb": s.tracking_number if s else None,
                      "carrier": s.carrier_code if s else None, "shipmentStatus": s.current_status if s else None,
                      "orderRef": (o.code or o.merchant_order_id) if o else None, "paymentMode": o.payment_type if o else None,
                      "customerName": c.name if c else None, "language": (t.state or {}).get("language"),
                      "status": t.status, "waitingFor": t.waiting_for, "outcome": (t.state or {}).get("outcome"),
                      "needsAttention": bool((t.state or {}).get("needs_attention")),
                      "preference": {"date": iso(pr.requested_date), "window": pr.requested_window, "status": pr.status} if pr else None,
                      "startedAt": iso(t.created_at), "updatedAt": iso(t.updated_at)})
    since = clock.now() - timedelta(days=7)
    started = db.scalar(select(func.count()).select_from(AgentTask).where(*f[:2], AgentTask.created_at >= since)) or 0
    confirmed = db.scalar(select(func.count()).select_from(DeliveryPreference).where(
        DeliveryPreference.merchant_id == p.merchant_id, DeliveryPreference.ndr_case_id.is_(None),
        DeliveryPreference.status == "confirmed_available", DeliveryPreference.created_at >= since)) or 0
    rescheduled = db.scalar(select(func.count()).select_from(DeliveryPreference).where(
        DeliveryPreference.merchant_id == p.merchant_id, DeliveryPreference.ndr_case_id.is_(None),
        DeliveryPreference.status.in_(("carrier_confirmed", "carrier_pending", "noted")), DeliveryPreference.created_at >= since)) or 0
    return {**page_response(items, total, page),
            "stats7d": {"started": started, "confirmedAvailable": confirmed, "rescheduledOrNoted": rescheduled,
                        "responseRate": round((confirmed + rescheduled) / started, 4) if started else None}}


# ================================================================== live events (SSE)
@router.get("/api/v1/events/stream")
async def stream(request: Request, p: Principal = Depends(get_principal)):
    """Server-sent events from the transactional outbox, scoped to the caller's merchant.

    Each event has a stable id (outbox id). Browsers reconnect automatically with Last-Event-ID and receive what
    they missed; a client too far behind gets a `resync` event and refetches. A heartbeat every 15s lets the UI
    show 'live' only while the stream is actually healthy."""
    merchant_id = p.merchant_id
    last = request.headers.get("last-event-id") or request.query_params.get("lastEventId")
    try:
        cursor = int(last) if last else None
    except ValueError:
        cursor = None

    def latest_id() -> int:
        db = new_session(merchant_id=merchant_id)
        try:
            return db.scalar(select(func.max(OutboxEvent.id)).where(OutboxEvent.merchant_id == merchant_id)) or 0
        finally:
            db.close()

    def fetch(after: int) -> list[OutboxEvent]:
        db = new_session(merchant_id=merchant_id)
        try:
            return list(db.scalars(select(OutboxEvent).where(OutboxEvent.merchant_id == merchant_id, OutboxEvent.id > after)
                                   .order_by(OutboxEvent.id).limit(200)))
        finally:
            db.close()

    async def gen():
        nonlocal cursor
        head = await run_in_threadpool(latest_id)
        if cursor is None or head - cursor > 1000:
            if cursor is not None:
                yield f"id: {head}\nevent: resync\ndata: {{}}\n\n"
            cursor = head
        yield f"retry: 3000\nid: {cursor}\nevent: hello\ndata: {json.dumps({'merchantId': merchant_id, 'at': clock.now().isoformat()})}\n\n"
        beat = 0.0
        while True:
            if await request.is_disconnected():
                return
            events = await run_in_threadpool(fetch, cursor)
            for ev in events:
                cursor = ev.id
                data = {"type": ev.event_type, "aggregate": ev.aggregate, "id": ev.aggregate_id, "payload": ev.payload,
                        "at": iso(ev.created_at)}
                yield f"id: {ev.id}\nevent: update\ndata: {json.dumps(data)}\n\n"
            beat += 1.5
            if beat >= 15:
                beat = 0
                yield f"event: heartbeat\ndata: {json.dumps({'at': clock.now().isoformat()})}\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ================================================================== provider webhooks
def _ingest(source: str, headers: dict, raw: bytes, query: dict) -> dict:
    db = new_session(system=True)
    try:
        return ingest_webhook(db, source, headers, raw, query)
    finally:
        db.close()


@router.get("/api/v1/providers/whatsapp/meta", response_class=PlainTextResponse)
def meta_verify(request: Request):
    q = request.query_params
    s = get_settings()
    if q.get("hub.mode") == "subscribe" and s.meta_verify_token and secrets.compare_digest(q.get("hub.verify_token", ""), s.meta_verify_token):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verification failed")


async def _provider(source: str, request: Request) -> dict:
    raw = await request.body()
    try:
        return await run_in_threadpool(_ingest, source, dict(request.headers), raw, dict(request.query_params))
    except IngestError as exc:
        raise HTTPException(exc.status, exc.message)


@router.post("/api/v1/providers/whatsapp/meta")
async def meta_webhook(request: Request):
    await _provider("whatsapp:meta_cloud", request)
    return {"ok": True}  # Meta expects 200 quickly; failures are in the inbox/quarantine


@router.post("/api/v1/providers/voice/sarvam")
async def sarvam_webhook(request: Request):
    return await _provider("voice:sarvam_agents", request)
