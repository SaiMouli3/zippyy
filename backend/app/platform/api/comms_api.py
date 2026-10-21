from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import not_found
from app.models import Order, Shipment
from app.platform import audit, clock
from app.platform.api.common import Page, iso, page_response
from app.platform.auth import Principal, require, tenant_db
from app.platform.models import (Conversation, Customer, IntentExtraction, MerchantSettings, Message, NdrCase,
                                 VoiceCall, VoiceCallEvent)
from app.platform.security import crypto

router = APIRouter(prefix="/api/v1", tags=["communications"])


def _retention_ok(db: Session, merchant_id: str, created_at, kind: str) -> bool:
    s = db.get(MerchantSettings, merchant_id)
    days = (s.transcript_retention_days if kind == "transcript" else s.message_retention_days) if s else 365
    return clock.now() - clock.as_utc(created_at) <= timedelta(days=days)


def serialize_message(db: Session, m: Message, extraction: IntentExtraction | None, show_body: bool) -> dict:
    return {"id": m.id, "kind": "message", "channel": m.channel, "direction": m.direction,
            "at": iso(m.created_at), "sender": "customer" if m.direction == "inbound" else ("agent" if m.agent_run_id else "system"),
            "body": m.body if show_body else "[expired under the retention policy]", "language": m.language,
            "languageConfidence": m.language_confidence, "templateCode": m.template_code,
            "templateVersion": m.template_version, "status": m.delivery_status, "statusUpdatedAt": iso(m.status_updated_at),
            "failureReason": m.failure_reason, "provider": m.provider, "providerMessageId": m.provider_message_id,
            "sentAt": iso(m.sent_at), "deliveredAt": iso(m.delivered_at), "readAt": iso(m.read_at),
            "shipmentId": m.shipment_id, "ndrCaseId": m.ndr_case_id, "agentRunId": m.agent_run_id,
            "intent": {"id": extraction.id, "intent": extraction.intent, "confidence": extraction.confidence,
                       "date": iso(extraction.requested_date), "window": extraction.requested_window,
                       "validation": extraction.validation_status} if extraction else None}


def serialize_call(c: VoiceCall, extraction: IntentExtraction | None = None) -> dict:
    return {"id": c.id, "kind": "call", "code": c.code, "channel": "voice", "at": iso(c.created_at),
            "direction": c.direction, "purpose": c.purpose, "provider": c.provider, "providerCallId": c.provider_call_id,
            "status": c.status, "result": c.result, "providerRawStatus": c.provider_raw_status,
            "scheduledFor": iso(c.scheduled_for), "startedAt": iso(c.started_at), "answeredAt": iso(c.answered_at),
            "endedAt": iso(c.ended_at), "durationSeconds": c.duration_seconds, "startLanguage": c.start_language,
            "finalLanguage": c.final_language, "languageSwitchCount": c.language_switch_count,
            "transcriptAvailable": c.transcript_available, "recordingAvailable": bool(c.recording_ref),
            "preferenceCaptured": c.preference_captured, "triggeredCarrierActionId": c.triggered_carrier_action_id,
            "followupScheduled": c.followup_scheduled, "attemptNo": c.attempt_no, "costPaise": c.cost_paise,
            "errorCode": c.error_code, "errorMessage": c.error_message, "shipmentId": c.shipment_id,
            "ndrCaseId": c.ndr_case_id,
            "intent": {"id": extraction.id, "intent": extraction.intent, "confidence": extraction.confidence,
                       "date": iso(extraction.requested_date), "window": extraction.requested_window} if extraction else None}


def unified_thread(db: Session, p: Principal, shipment_id: str) -> dict:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None or shipment.merchant_id != p.merchant_id:
        raise not_found("Shipment")
    msgs = list(db.scalars(select(Message).where(Message.shipment_id == shipment_id).order_by(Message.created_at)))
    calls = list(db.scalars(select(VoiceCall).where(VoiceCall.shipment_id == shipment_id).order_by(VoiceCall.created_at)))
    ext_by_msg = {e.message_id: e for e in db.scalars(select(IntentExtraction).where(
        IntentExtraction.message_id.in_([m.id for m in msgs])))} if msgs else {}
    ext_by_call = {e.call_id: e for e in db.scalars(select(IntentExtraction).where(
        IntentExtraction.call_id.in_([c.id for c in calls])))} if calls else {}
    items = [serialize_message(db, m, ext_by_msg.get(m.id), _retention_ok(db, p.merchant_id, m.created_at, "message"))
             for m in msgs]
    items += [serialize_call(c, ext_by_call.get(c.id)) for c in calls]
    items.sort(key=lambda i: i["at"] or "")
    order = db.get(Order, shipment.order_id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    return {"items": items, "customer": {"name": customer.name, "phoneMasked": crypto.mask_phone(customer.phone_last4),
                                         "preferredLanguage": customer.preferred_language,
                                         "predictedLanguage": customer.predicted_language,
                                         "optedOut": customer.opted_out_at is not None} if customer else None,
            "generatedAt": clock.now().isoformat()}


@router.get("/conversations")
def list_conversations(page: Page = Depends(), q: str | None = None, language: str | None = None,
                       status: str | None = None, p: Principal = Depends(require("conversations.read")),
                       db: Session = Depends(tenant_db)):
    f = [Conversation.merchant_id == p.merchant_id]
    if language:
        f.append(Conversation.language == language)
    if status:
        f.append(Conversation.status == status)
    if q:
        f.append(Conversation.customer_id.in_(select(Customer.id).where(Customer.merchant_id == p.merchant_id,
                                                                        Customer.name.ilike(f"%{q[:80]}%"))))
    total = db.scalar(select(func.count()).select_from(Conversation).where(*f)) or 0
    convs = list(db.scalars(select(Conversation).where(*f).order_by(Conversation.last_message_at.desc().nulls_last(), Conversation.id)
                            .offset(page.offset).limit(page.size)))
    cust = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_([c.customer_id for c in convs])))} if convs else {}
    cases = {c.id: c for c in db.scalars(select(NdrCase).where(NdrCase.id.in_([c.ndr_case_id for c in convs if c.ndr_case_id])))} if convs else {}
    last = {}
    if convs:
        sub = select(Message.conversation_id, func.max(Message.created_at).label("mx")).where(
            Message.conversation_id.in_([c.id for c in convs])).group_by(Message.conversation_id).subquery()
        for m in db.scalars(select(Message).join(sub, (Message.conversation_id == sub.c.conversation_id) & (Message.created_at == sub.c.mx))):
            last[m.conversation_id] = m
    counts = dict(db.execute(select(Message.conversation_id, func.count()).where(
        Message.conversation_id.in_([c.id for c in convs])).group_by(Message.conversation_id)).all()) if convs else {}
    items = []
    for c in convs:
        cu = cust.get(c.customer_id)
        lm = last.get(c.id)
        case = cases.get(c.ndr_case_id)
        items.append({"id": c.id, "customerName": cu.name if cu else None,
                      "phoneMasked": crypto.mask_phone(cu.phone_last4) if cu else None, "language": c.language,
                      "status": c.status, "shipmentId": c.shipment_id, "ndrCaseId": c.ndr_case_id,
                      "ndrCode": case.code if case else None, "messageCount": counts.get(c.id, 0),
                      "lastMessageAt": iso(c.last_message_at), "lastInboundAt": iso(c.last_inbound_at),
                      "lastDirection": lm.direction if lm else None, "lastStatus": lm.delivery_status if lm else None,
                      "lastPreview": (lm.body[:120] if lm else None), "inSessionWindow": bool(c.last_inbound_at and clock.now() - clock.as_utc(c.last_inbound_at) < timedelta(hours=24))})
    return page_response(items, total, page)


def _conv(db: Session, p: Principal, conversation_id: str) -> Conversation:
    c = db.get(Conversation, conversation_id)
    if c is None or c.merchant_id != p.merchant_id:
        raise not_found("Conversation")
    return c


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, p: Principal = Depends(require("conversations.read")), db: Session = Depends(tenant_db)):
    c = _conv(db, p, conversation_id)
    thread = unified_thread(db, p, c.shipment_id) if c.shipment_id else {"items": []}
    return {"id": c.id, "shipmentId": c.shipment_id, "ndrCaseId": c.ndr_case_id, "language": c.language,
            "status": c.status, "lastInboundAt": iso(c.last_inbound_at), **thread}


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, p: Principal = Depends(require("conversations.read")), db: Session = Depends(tenant_db)):
    c = _conv(db, p, conversation_id)
    msgs = list(db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)))
    return {"items": [serialize_message(db, m, None, _retention_ok(db, p.merchant_id, m.created_at, "message")) for m in msgs]}


@router.get("/voice-calls")
def list_calls(page: Page = Depends(), status: str | None = None, result: str | None = None, language: str | None = None,
               switched: bool = False, purpose: str | None = None, p: Principal = Depends(require("conversations.read")),
               db: Session = Depends(tenant_db)):
    f = [VoiceCall.merchant_id == p.merchant_id]
    if status:
        f.append(VoiceCall.status.in_(status.split(",")))
    if result:
        f.append(VoiceCall.result == result)
    if language:
        f.append(VoiceCall.final_language == language)
    if switched:
        f.append(VoiceCall.language_switch_count > 0)
    if purpose:
        f.append(VoiceCall.purpose == purpose)
    total = db.scalar(select(func.count()).select_from(VoiceCall).where(*f)) or 0
    calls = list(db.scalars(select(VoiceCall).where(*f).order_by(VoiceCall.created_at.desc(), VoiceCall.id)
                            .offset(page.offset).limit(page.size)))
    cust = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_([c.customer_id for c in calls])))} if calls else {}
    codes = dict(db.execute(select(NdrCase.id, NdrCase.code).where(NdrCase.id.in_([c.ndr_case_id for c in calls if c.ndr_case_id]))).all()) if calls else {}
    items = []
    for c in calls:
        d = serialize_call(c)
        cu = cust.get(c.customer_id)
        d.update({"customerName": cu.name if cu else None, "phoneMasked": crypto.mask_phone(cu.phone_last4) if cu else None,
                  "ndrCode": codes.get(c.ndr_case_id)})
        items.append(d)
    return page_response(items, total, page)


def _call(db: Session, p: Principal, call_id: str) -> VoiceCall:
    c = db.get(VoiceCall, call_id)
    if c is None or c.merchant_id != p.merchant_id:
        raise not_found("Voice call")
    return c


@router.get("/voice-calls/{call_id}")
def get_call(call_id: str, p: Principal = Depends(require("conversations.read")), db: Session = Depends(tenant_db)):
    c = _call(db, p, call_id)
    ext = db.scalars(select(IntentExtraction).where(IntentExtraction.call_id == c.id)).first()
    cu = db.get(Customer, c.customer_id)
    d = serialize_call(c, ext)
    d.update({"customerName": cu.name if cu else None, "phoneMasked": crypto.mask_phone(cu.phone_last4) if cu else None})
    langs = list(db.scalars(select(VoiceCallEvent).where(VoiceCallEvent.call_id == c.id,
                                                         VoiceCallEvent.kind.in_(("language_switch", "status")))
                            .order_by(VoiceCallEvent.seq)))
    d["events"] = [{"seq": e.seq, "kind": e.kind, "status": e.status, "at": iso(e.occurred_at),
                    "fromLanguage": e.from_language, "toLanguage": e.to_language,
                    "confidence": e.language_confidence, "codeMixed": e.code_mixed, "data": e.data} for e in langs]
    return d


@router.get("/voice-calls/{call_id}/transcript")
def transcript(call_id: str, p: Principal = Depends(require("transcripts.read")), db: Session = Depends(tenant_db)):
    c = _call(db, p, call_id)
    if not _retention_ok(db, p.merchant_id, c.created_at, "transcript"):
        return {"available": False, "reason": "Transcript removed under the retention policy", "turns": []}
    turns = list(db.scalars(select(VoiceCallEvent).where(VoiceCallEvent.call_id == c.id,
                                                         VoiceCallEvent.kind.in_(("turn", "silence", "language_switch")))
                            .order_by(VoiceCallEvent.seq)))
    audit.record(db, p.actor, p.merchant_id, "voice_call", c.id, "transcript.viewed")
    db.commit()
    start = clock.as_utc(c.started_at) if c.started_at else None
    return {"available": c.transcript_available, "callId": c.id, "startLanguage": c.start_language,
            "finalLanguage": c.final_language,
            "turns": [{"seq": t.seq, "kind": t.kind, "speaker": t.speaker, "text": t.text, "textEn": t.text_en,
                       "language": t.language, "confidence": t.language_confidence, "codeMixed": t.code_mixed,
                       "fromLanguage": t.from_language, "toLanguage": t.to_language, "at": iso(t.occurred_at),
                       "offsetSeconds": round((clock.as_utc(t.occurred_at) - start).total_seconds(), 1) if start else None}
                      for t in turns]}
