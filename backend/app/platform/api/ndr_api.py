from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError, not_found
from app.models import Order, Shipment, ShipmentEvent
from app.platform import audit, clock, customers as cust_svc, escalations, ndr
from app.platform.api.common import Page, csv_text, iso, page_response
from app.platform.auth import Principal, require, tenant_db
from app.platform.models import (AgentRun, AgentRunStep, AgentTask, CarrierAction, CarrierActionEvent, Conversation,
                                 Customer, DeliveryAttempt, DeliveryPreference, Escalation, EscalationNote,
                                 IntentExtraction, Message, MessageStatusEvent, NdrCase, RuleDecision, VoiceCall,
                                 VoiceCallEvent, Address)
from app.platform.security import crypto

router = APIRouter(prefix="/api/v1/ndr", tags=["ndr"])

SORTABLE = {"opened": NdrCase.opened_at, "sla": NdrCase.sla_due_at, "updated": NdrCase.updated_at,
            "attempts": NdrCase.attempt_no, "code": NdrCase.code, "status": NdrCase.status,
            "lastContact": NdrCase.last_customer_contact_at}
OPEN = ("open", "contacting", "awaiting_customer", "decided", "action_requested", "reattempt_scheduled", "escalated", "rto")
ACTIVE_FOR_SLA = ("open", "contacting", "awaiting_customer", "decided", "escalated")


def _multi(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


def build_filters(p: Principal, q=None, status=None, reason=None, carrier=None, city=None, state=None, pincode=None,
                  language=None, payment=None, min_attempts=None, sla=None, agent_status=None, contactability=None,
                  whatsapp_status=None, call_outcome=None, recovery=None, rto=None, queue=None, opened_from=None,
                  opened_to=None, awb=None, order_ref=None) -> list:
    now = clock.now()
    f = [NdrCase.merchant_id == p.merchant_id]
    for col, val in ((NdrCase.status, status), (NdrCase.reason, reason), (NdrCase.carrier_code, carrier),
                     (NdrCase.payment_mode, payment), (NdrCase.agent_status, agent_status),
                     (NdrCase.contactability, contactability), (NdrCase.whatsapp_status, whatsapp_status),
                     (NdrCase.call_outcome, call_outcome), (NdrCase.recovery_outcome, recovery)):
        vals = _multi(val)
        if vals:
            f.append(col.in_(vals))
    if city:
        f.append(func.lower(NdrCase.city) == city.strip().lower())
    if state:
        f.append(func.lower(NdrCase.state) == state.strip().lower())
    if pincode:
        f.append(NdrCase.pincode == pincode.strip())
    if awb:
        f.append(NdrCase.awb == awb.strip())
    if order_ref:
        f.append(NdrCase.order_ref == order_ref.strip())
    langs = _multi(language)
    if langs:
        f.append(or_(NdrCase.language_confirmed.in_(langs),
                     and_(NdrCase.language_confirmed.is_(None), NdrCase.language_predicted.in_(langs))))
    if min_attempts:
        f.append(NdrCase.attempt_no >= min_attempts)
    if opened_from:
        f.append(NdrCase.opened_at >= opened_from)
    if opened_to:
        f.append(NdrCase.opened_at < opened_to)
    if sla == "breached":
        f += [NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at < now]
    elif sla == "due_4h":
        f += [NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at >= now, NdrCase.sla_due_at < now + timedelta(hours=4)]
    elif sla == "due_24h":
        f += [NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at >= now, NdrCase.sla_due_at < now + timedelta(hours=24)]
    if rto == "initiated":
        f.append(NdrCase.status == "rto")
    elif rto == "completed":
        f.append(NdrCase.resolution == "rto")
    elif rto == "none":
        f.append(or_(NdrCase.resolution.is_(None), NdrCase.resolution != "rto"), )
        f.append(NdrCase.status != "rto")
    queues = {
        "open": [NdrCase.status.in_(OPEN)],
        "urgent": [NdrCase.status.in_(OPEN), or_(NdrCase.priority == "urgent", and_(NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at < now))],
        "awaiting_carrier": [NdrCase.pending_action.like("%:requested"), NdrCase.status.in_(OPEN)],
        "carrier_unknown": [or_(NdrCase.pending_action.like("%:unknown"), NdrCase.pending_action.like("%:retrying"))],
        "callback": [NdrCase.callback_requested.is_(True)],
        "call_failures": [NdrCase.call_outcome.in_(("no_answer", "busy", "failed")), NdrCase.status.in_(OPEN)],
        "low_confidence": [NdrCase.low_confidence.is_(True), NdrCase.status.in_(OPEN)],
        "restricted": [NdrCase.contactability == "opted_out", NdrCase.status.in_(OPEN)],
        "escalated": [NdrCase.has_open_escalation.is_(True)],
        "near_deadline": [NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at >= now, NdrCase.sla_due_at < now + timedelta(hours=4)],
        "recovered": [NdrCase.recovery_outcome == "recovered_after_contact"],
        "rto": [NdrCase.status == "rto"],
        "resolved": [NdrCase.status.in_(("resolved", "closed_no_response"))],
    }
    if queue:
        f += queues.get(queue, [])
    if q:
        term = q.strip()[:100]
        conds = [NdrCase.code.ilike(f"%{term}%"), NdrCase.order_ref.ilike(f"%{term}%"), NdrCase.awb.ilike(f"%{term}%"),
                 NdrCase.shipment_id == term, NdrCase.id == term,
                 NdrCase.customer_id.in_(select(Customer.id).where(Customer.merchant_id == p.merchant_id,
                                                                   Customer.name.ilike(f"%{term}%")))]
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 10 and p.can("pii.unmask"):
            try:
                h = crypto.phone_hash(crypto.normalize_phone(digits))
                conds.append(NdrCase.customer_id.in_(select(Customer.id).where(Customer.merchant_id == p.merchant_id,
                                                                               Customer.phone_hash == h)))
            except ValueError:
                pass
        f.append(or_(*conds))
    return f


def row(c: NdrCase, names: dict, phones: dict, merchant_name: str) -> dict:
    return {
        "id": c.id, "code": c.code, "orderRef": c.order_ref, "shipmentId": c.shipment_id, "awb": c.awb,
        "merchant": merchant_name, "customerName": names.get(c.customer_id), "phoneMasked": phones.get(c.customer_id),
        "city": c.city, "state": c.state, "pincode": c.pincode, "carrier": c.carrier_code, "paymentMode": c.payment_mode,
        "codAmountPaise": c.cod_amount_paise, "shipmentStatus": c.shipment_status, "status": c.status,
        "reason": c.reason, "carrierReason": c.carrier_reason, "attempts": c.attempt_no,
        "languagePredicted": c.language_predicted, "languageConfirmed": c.language_confirmed,
        "preferredDate": iso(c.preferred_date), "preferredWindow": c.preferred_window,
        "whatsappStatus": c.whatsapp_status, "callOutcome": c.call_outcome,
        "lastContactAt": iso(c.last_customer_contact_at), "lastContactChannel": c.last_contact_channel,
        "agentStatus": c.agent_status, "pendingAction": c.pending_action, "slaDueAt": iso(c.sla_due_at),
        "priority": c.priority, "recoveryOutcome": c.recovery_outcome, "resolution": c.resolution,
        "contactability": c.contactability, "hasOpenEscalation": c.has_open_escalation,
        "openedAt": iso(c.opened_at), "updatedAt": iso(c.updated_at),
    }


def _people(db: Session, cases: list[NdrCase]) -> tuple[dict, dict]:
    ids = {c.customer_id for c in cases if c.customer_id}
    if not ids:
        return {}, {}
    rows = db.execute(select(Customer.id, Customer.name, Customer.phone_last4).where(Customer.id.in_(ids))).all()
    return {r.id: r.name for r in rows}, {r.id: crypto.mask_phone(r.phone_last4) for r in rows}


def _merchant_name(db: Session, merchant_id: str) -> str:
    from app.platform.models import Merchant
    m = db.get(Merchant, merchant_id)
    return m.brand_name if m else ""


class Filters:
    def __init__(self, q: str | None = None, status: str | None = None, reason: str | None = None,
                 carrier: str | None = None, city: str | None = None, state: str | None = None,
                 pincode: str | None = None, language: str | None = None, payment: str | None = None,
                 minAttempts: int | None = Query(None, ge=1, le=10), sla: str | None = None,
                 agentStatus: str | None = None, contactability: str | None = None, whatsappStatus: str | None = None,
                 callOutcome: str | None = None, recovery: str | None = None, rto: str | None = None,
                 queue: str | None = None, openedFrom: datetime | None = None, openedTo: datetime | None = None,
                 awb: str | None = None, orderRef: str | None = None):
        self.kw = dict(q=q, status=status, reason=reason, carrier=carrier, city=city, state=state, pincode=pincode,
                       language=language, payment=payment, min_attempts=minAttempts, sla=sla, agent_status=agentStatus,
                       contactability=contactability, whatsapp_status=whatsappStatus, call_outcome=callOutcome,
                       recovery=recovery, rto=rto, queue=queue, opened_from=openedFrom, opened_to=openedTo, awb=awb,
                       order_ref=orderRef)


@router.get("")
def list_cases(filters: Filters = Depends(), page: Page = Depends(), sort: str = "sla", order: str = "asc",
               p: Principal = Depends(require("ndr.read")), db: Session = Depends(tenant_db)):
    f = build_filters(p, **filters.kw)
    col = SORTABLE.get(sort, NdrCase.sla_due_at)
    direction = asc if order == "asc" else desc
    total = db.scalar(select(func.count()).select_from(NdrCase).where(*f)) or 0
    cases = list(db.scalars(select(NdrCase).where(*f).order_by(direction(col).nulls_last(), NdrCase.id)
                            .offset(page.offset).limit(page.size)))
    names, phones = _people(db, cases)
    mname = _merchant_name(db, p.merchant_id)
    return page_response([row(c, names, phones, mname) for c in cases], total, page)


@router.get("/export.csv", response_class=PlainTextResponse)
def export_cases(filters: Filters = Depends(), p: Principal = Depends(require("ndr.read", "export.csv")),
                 db: Session = Depends(tenant_db)):
    f = build_filters(p, **filters.kw)
    cases = list(db.scalars(select(NdrCase).where(*f).order_by(NdrCase.opened_at.desc()).limit(10_000)))
    names, phones = _people(db, cases)
    mname = _merchant_name(db, p.merchant_id)
    rows = [row(c, names, phones, mname) for c in cases]
    audit.record(db, p.actor, p.merchant_id, "ndr_case", "export", "ndr.exported", after={"rows": len(rows)})
    db.commit()
    return PlainTextResponse(csv_text(rows), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="ndr-cases-{clock.now():%Y%m%d-%H%M}.csv"'})


def _case(db: Session, p: Principal, case_id: str) -> NdrCase:
    c = db.get(NdrCase, case_id)
    if c is None:
        c = db.scalars(select(NdrCase).where(NdrCase.code == case_id)).first()
    if c is None or c.merchant_id != p.merchant_id:
        raise not_found("NDR case")
    return c


@router.get("/{case_id}")
def get_case(case_id: str, p: Principal = Depends(require("ndr.read")), db: Session = Depends(tenant_db)):
    c = _case(db, p, case_id)
    shipment = db.get(Shipment, c.shipment_id)
    order = db.get(Order, shipment.order_id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None
    address = db.get(Address, order.address_id) if order.address_id else None
    names, phones = _people(db, [c])
    task = db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == c.id).order_by(AgentTask.created_at.desc())).first()
    escalation = db.scalars(select(Escalation).where(Escalation.ndr_case_id == c.id).order_by(Escalation.created_at.desc())).first()
    pref = db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == shipment.id)
                      .order_by(DeliveryPreference.created_at.desc())).first()
    extraction = db.scalars(select(IntentExtraction).where(IntentExtraction.ndr_case_id == c.id)
                            .order_by(IntentExtraction.created_at.desc())).first()
    decision = db.scalars(select(RuleDecision).where(RuleDecision.ndr_case_id == c.id)
                          .order_by(RuleDecision.created_at.desc())).first()
    action = db.scalars(select(CarrierAction).where(CarrierAction.ndr_case_id == c.id)
                        .order_by(CarrierAction.requested_at.desc())).first()
    from app.platform.models import Merchant
    merchant = db.get(Merchant, p.merchant_id)
    return {
        "case": row(c, names, phones, merchant.brand_name),
        "shipment": {"id": shipment.id, "code": shipment.code, "awb": shipment.tracking_number,
                     "carrier": shipment.carrier_code, "status": shipment.current_status,
                     "attempts": shipment.attempt_count, "createdAt": iso(shipment.created_at),
                     "dispatchedAt": iso(shipment.dispatched_at), "etaStart": iso(shipment.eta_start),
                     "etaEnd": iso(shipment.eta_end), "deliveredAt": iso(shipment.delivered_at),
                     "lastEventAt": iso(shipment.last_event_at)},
        "order": {"id": order.id, "ref": order.code or order.merchant_order_id, "merchantOrderId": order.merchant_order_id,
                  "paymentMode": order.payment_type, "codAmountPaise": int(float(order.cod_amount or 0) * 100),
                  "orderValuePaise": order.order_value_paise},
        "customer": cust_svc.masked(customer) if customer else None,
        "address": cust_svc.masked_address(address),
        "courierReported": {"reason": c.reason, "carrierReason": c.carrier_reason, "attempt": c.attempt_no},
        "customerSupplied": {"preferredDate": iso(pref.requested_date) if pref else None,
                             "preferredWindow": pref.requested_window if pref else None,
                             "preferenceStatus": pref.status if pref else None,
                             "channel": pref.source_channel if pref else None,
                             "confirmedAt": iso(pref.customer_confirmed_at) if pref else None,
                             "languageConfirmed": customer.preferred_language if customer else None},
        "aiInferred": {"intent": extraction.intent if extraction else None,
                       "confidence": extraction.confidence if extraction else None,
                       "extractor": extraction.extractor if extraction else None,
                       "validation": extraction.validation_status if extraction else None,
                       "languagePredicted": customer.predicted_language if customer else None,
                       "languagePredictionSource": customer.predicted_language_source if customer else None,
                       "languagePredictionConfidence": customer.predicted_language_confidence if customer else None},
        "decision": _decision(decision),
        "carrierAction": _action(action),
        "agent": {"taskId": task.id if task else None, "taskType": task.task_type if task else None,
                  "status": task.status if task else None, "waitingFor": task.waiting_for if task else None,
                  "nextRunAt": iso(task.next_run_at) if task else None,
                  "timers": (task.state or {}).get("timers", {}) if task else {},
                  "policyVersionId": task.policy_version_id if task else None},
        "escalation": _escalation(escalation) if escalation else None,
        "isDemo": merchant.is_demo,
        "nextStep": _next_step(c, task, action, escalation),
    }


def _decision(d: RuleDecision | None) -> dict | None:
    if d is None:
        return None
    from app.platform.policy import RULE_TEXT
    return {"id": d.id, "verdict": d.verdict, "action": d.action, "requestedDate": iso(d.requested_date),
            "requestedWindow": d.requested_window, "reasons": d.reasons,
            "rules": [{"id": r, "text": RULE_TEXT.get(r, r)} for r in dict.fromkeys(d.rules_fired)],
            "rulesVersion": d.rules_version, "approvalStatus": d.approval_status, "createdAt": iso(d.created_at)}


def _action(a: CarrierAction | None) -> dict | None:
    if a is None:
        return None
    return {"id": a.id, "action": a.action, "status": a.status, "carrier": a.carrier_code,
            "requestedDate": iso(a.requested_date), "requestedWindow": a.requested_window,
            "carrierReference": a.carrier_reference, "rejectionReason": a.rejection_reason, "attempts": a.attempts,
            "lastError": a.last_error, "requestedAt": iso(a.requested_at), "respondedAt": iso(a.responded_at),
            "verifiedAt": iso(a.verified_at), "decisionId": a.decision_id, "idempotencyKey": a.idempotency_key}


def _escalation(e: Escalation) -> dict:
    return {"id": e.id, "code": e.code, "reason": e.reason, "priority": e.priority, "status": e.status,
            "assignedTo": e.assigned_to, "summary": e.summary, "slaDueAt": iso(e.sla_due_at),
            "pendingDecisionId": e.pending_decision_id, "createdAt": iso(e.created_at),
            "resolution": e.resolution_outcome, "resolutionReason": e.resolution_reason}


def _next_step(c: NdrCase, task: AgentTask | None, action: CarrierAction | None, esc: Escalation | None) -> str:
    if c.status in ("resolved", "closed_no_response"):
        return f"Closed — {c.resolution or c.status}"
    if esc and esc.status != "resolved":
        return "Waiting for an operator: " + esc.reason.replace("_", " ")
    if action and action.status in ("requested", "unknown", "retrying"):
        return f"Waiting for {action.carrier_code} to answer the {action.action} request"
    if action and action.status == "accepted":
        return f"Carrier accepted; next attempt {action.requested_date or 'scheduled'}"
    if task and task.next_run_at:
        return f"Agent resumes at {iso(task.next_run_at)} ({task.waiting_for or 'timer'})"
    if task and task.waiting_for:
        return f"Waiting for {task.waiting_for.replace('_', ' ')}"
    return "No automated step pending"


# ---------------------------------------------------------------- timeline
CATEGORY = {"shipment": "shipment", "message": "communication", "call": "communication", "extraction": "ai",
            "decision": "ai", "agent": "ai", "carrier_action": "carrier", "escalation": "admin", "audit": "admin"}


def _item(kind: str, at, type_: str, title: str, source: str, actor: str, result: str | None, refs: dict,
          detail: dict | None = None, correlation: str | None = None) -> dict:
    return {"id": f"{kind}:{refs.get('id')}:{type_}", "at": iso(at), "category": CATEGORY[kind], "type": type_,
            "title": title, "source": source, "actor": actor, "result": result, "refs": refs, "detail": detail or {},
            "correlationId": correlation}


def build_timeline(db: Session, shipment: Shipment, case_ids: list[str]) -> list[dict]:
    items: list[dict] = []
    for e in db.scalars(select(ShipmentEvent).where(ShipmentEvent.shipment_id == shipment.id)):
        items.append(_item("shipment", e.event_time, f"tracking.{e.normalized_status.lower()}",
                           e.description or e.normalized_status.replace("_", " ").title(), f"carrier:{shipment.carrier_code}",
                           shipment.carrier_code, e.normalized_status, {"entity": "tracking_event", "id": e.id},
                           {"carrierStatus": e.carrier_status, "location": e.location, "reason": e.reason_code,
                            "carrierReason": e.carrier_reason, "receivedAt": iso(e.received_at)}))
    msgs = list(db.scalars(select(Message).where(Message.shipment_id == shipment.id)))
    msg_ids = [m.id for m in msgs]
    statuses: dict[str, list] = {}
    if msg_ids:
        for s in db.scalars(select(MessageStatusEvent).where(MessageStatusEvent.message_id.in_(msg_ids))):
            statuses.setdefault(s.message_id, []).append(s)
    for m in msgs:
        if m.direction == "inbound":
            items.append(_item("message", m.created_at, "message.received", "Customer replied on WhatsApp",
                               f"whatsapp:{m.provider}", "customer", "received", {"entity": "message", "id": m.id},
                               {"language": m.language, "confidence": m.language_confidence}))
            continue
        items.append(_item("message", m.created_at, "message.queued",
                           f"WhatsApp {'template ' + m.template_code if m.template_code else 'reply'} queued",
                           "agent", "zippyy-agent", m.delivery_status, {"entity": "message", "id": m.id},
                           {"language": m.language, "template": m.template_code, "version": m.template_version,
                            "failure": m.failure_reason}))
        for s in sorted(statuses.get(m.id, []), key=lambda x: x.occurred_at):
            items.append(_item("message", s.occurred_at, f"message.{s.status}", f"WhatsApp message {s.status}",
                               f"whatsapp:{m.provider}", m.provider, s.status, {"entity": "message", "id": m.id},
                               {"errorCode": s.error_code}))
    for call in db.scalars(select(VoiceCall).where(VoiceCall.shipment_id == shipment.id)):
        items.append(_item("call", call.created_at, "call.scheduled", f"Voice call {call.code} scheduled",
                           "agent", "zippyy-agent", call.status, {"entity": "voice_call", "id": call.id},
                           {"purpose": call.purpose, "language": call.start_language, "scheduledFor": iso(call.scheduled_for)}))
        for ev in db.scalars(select(VoiceCallEvent).where(VoiceCallEvent.call_id == call.id,
                                                          VoiceCallEvent.kind.in_(("status", "language_switch")))
                             .order_by(VoiceCallEvent.seq)):
            if ev.kind == "language_switch":
                items.append(_item("call", ev.occurred_at, "call.language_switch",
                                   f"Language switched {ev.from_language} → {ev.to_language}", f"voice:{call.provider}",
                                   "customer", ev.to_language, {"entity": "voice_call", "id": call.id},
                                   {"confidence": ev.language_confidence, "codeMixed": ev.code_mixed}))
            else:
                items.append(_item("call", ev.occurred_at, f"call.{ev.status}", f"Call {ev.status.replace('_', ' ')}",
                                   f"voice:{call.provider}", call.provider, ev.status, {"entity": "voice_call", "id": call.id},
                                   {"result": call.result if ev.status == "completed" else None,
                                    "duration": call.duration_seconds if ev.status == "completed" else None}))
    if case_ids:
        for x in db.scalars(select(IntentExtraction).where(IntentExtraction.ndr_case_id.in_(case_ids))):
            items.append(_item("extraction", x.created_at, "ai.intent_extracted", f"Intent extracted: {x.intent}",
                               x.extractor, "zippyy-agent", x.validation_status, {"entity": "intent_extraction", "id": x.id},
                               {"confidence": x.confidence, "date": iso(x.requested_date), "window": x.requested_window,
                                "language": x.language}))
        for d in db.scalars(select(RuleDecision).where(RuleDecision.ndr_case_id.in_(case_ids))):
            items.append(_item("decision", d.created_at, "ai.rules_evaluated", f"Rules: {d.verdict.replace('_', ' ').lower()}"
                               + (f" ({d.action})" if d.action else ""), "policy-engine", d.rules_version, d.verdict,
                               {"entity": "rule_decision", "id": d.id}, {"reasons": d.reasons, "rules": d.rules_fired,
                                                                         "approval": d.approval_status}))
    for a in db.scalars(select(CarrierAction).where(CarrierAction.shipment_id == shipment.id)):
        for ev in db.scalars(select(CarrierActionEvent).where(CarrierActionEvent.action_id == a.id)):
            items.append(_item("carrier_action", ev.occurred_at, f"carrier.{a.action}.{ev.status}",
                               f"{a.action.title()} {ev.status.replace('_', ' ')}", f"carrier:{a.carrier_code}",
                               a.carrier_code if ev.status not in ("requested",) else "zippyy-agent", ev.status,
                               {"entity": "carrier_action", "id": a.id}, {"detail": ev.detail, "latencyMs": ev.latency_ms,
                                                                          "reference": a.carrier_reference}))
    if case_ids:
        for esc in db.scalars(select(Escalation).where(Escalation.ndr_case_id.in_(case_ids))):
            for n in db.scalars(select(EscalationNote).where(EscalationNote.escalation_id == esc.id)):
                items.append(_item("escalation", n.created_at, f"escalation.{n.kind}",
                                   {"note": "Escalation note", "assignment": "Escalation assigned", "approval": "Action approved",
                                    "rejection": "Action rejected", "resolution": "Escalation resolved",
                                    "supervisor": "Sent to supervisor", "correction": "Preference corrected"}.get(n.kind, n.kind),
                                   "operator" if n.author_id else "zippyy-agent", n.author_id or "zippyy-agent", esc.status,
                                   {"entity": "escalation", "id": esc.id}, {"body": n.body}))
        for t in db.scalars(select(AgentTask).where(AgentTask.ndr_case_id.in_(case_ids))):
            items.append(_item("agent", t.created_at, "agent.task_started", f"{t.task_type.replace('_', ' ').title()} started",
                               "agent", "zippyy-agent", t.status, {"entity": "agent_task", "id": t.id},
                               {"cycle": t.delivery_cycle, "trigger": t.trigger_event}, t.correlation_id))
    for t in db.scalars(select(AgentTask).where(AgentTask.shipment_id == shipment.id, AgentTask.task_type == "pre_delivery")):
        items.append(_item("agent", t.created_at, "agent.pre_delivery_started", "Pre-delivery confirmation started",
                           "agent", "zippyy-agent", t.status, {"entity": "agent_task", "id": t.id},
                           {"outcome": (t.state or {}).get("outcome")}, t.correlation_id))
    items.sort(key=lambda i: (i["at"] or "", _causal_rank(i["type"]), i["id"]))
    return items


# Events recorded in the same instant are ordered by causality, not alphabetically.
_ORDER = ["tracking.", "agent.task_started", "agent.pre_delivery_started", "message.received", "message.queued",
          "call.scheduled", "call.initiated", "call.ringing", "call.answered", "call.language_switch", "call.",
          "ai.intent_extracted", "ai.rules_evaluated", "carrier.", "escalation.", "message.sent", "message.delivered",
          "message.read", "message.failed"]
_CARRIER = ["requested", "unknown", "retrying", "accepted", "rejected", "failed", "timed_out", "completed"]


def _causal_rank(type_: str) -> tuple[int, int]:
    rank = next((i for i, prefix in enumerate(_ORDER) if type_.startswith(prefix)), len(_ORDER))
    sub = next((i for i, st in enumerate(_CARRIER) if type_.endswith("." + st)), 0) if type_.startswith("carrier.") else 0
    return rank, sub


@router.get("/{case_id}/timeline")
def timeline(case_id: str, category: str | None = None, p: Principal = Depends(require("ndr.read")),
             db: Session = Depends(tenant_db)):
    c = _case(db, p, case_id)
    shipment = db.get(Shipment, c.shipment_id)
    case_ids = list(db.scalars(select(NdrCase.id).where(NdrCase.shipment_id == shipment.id)))
    items = build_timeline(db, shipment, case_ids)
    cats = _multi(category)
    if cats:
        items = [i for i in items if i["category"] in cats]
    return {"items": items, "generatedAt": clock.now().isoformat()}


@router.get("/{case_id}/agent-runs")
def case_runs(case_id: str, p: Principal = Depends(require("agent_runs.read")), db: Session = Depends(tenant_db)):
    c = _case(db, p, case_id)
    from app.platform.api.agent_api import serialize_run
    runs = list(db.scalars(select(AgentRun).where(or_(AgentRun.ndr_case_id == c.id, AgentRun.shipment_id == c.shipment_id))
                           .order_by(AgentRun.started_at)))
    steps: dict[str, list] = {}
    if runs:
        for s in db.scalars(select(AgentRunStep).where(AgentRunStep.run_id.in_([r.id for r in runs])).order_by(AgentRunStep.seq)):
            steps.setdefault(s.run_id, []).append(s)
    return {"items": [serialize_run(r, steps.get(r.id, [])) for r in runs]}


@router.get("/{case_id}/conversations")
def case_conversations(case_id: str, p: Principal = Depends(require("conversations.read")), db: Session = Depends(tenant_db)):
    c = _case(db, p, case_id)
    from app.platform.api.comms_api import unified_thread
    return unified_thread(db, p, c.shipment_id)


@router.post("/{case_id}/unmask")
def unmask(case_id: str, body: dict, p: Principal = Depends(require("pii.unmask")), db: Session = Depends(tenant_db)):
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 5:
        raise DomainError("REASON_REQUIRED", "Say why you need the full contact details", 422)
    c = _case(db, p, case_id)
    shipment = db.get(Shipment, c.shipment_id)
    order = db.get(Order, shipment.order_id)
    customer = db.get(Customer, order.customer_id)
    address = db.get(Address, order.address_id) if order.address_id else None
    out = cust_svc.unmask(db, customer, address, p.actor, reason)
    db.commit()
    return out


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(no_response|cancelled)$")
    reason: str = Field(min_length=5, max_length=500)


@router.post("/{case_id}/resolve")
def resolve(case_id: str, body: ResolveIn, p: Principal = Depends(require("ndr.resolve")), db: Session = Depends(tenant_db)):
    """Manual closure is limited to the documented non-delivery outcomes. Delivered and RTO closures only come
    from carrier events."""
    c = _case(db, p, case_id)
    if c.status in ("resolved", "closed_no_response"):
        raise DomainError("ALREADY_CLOSED", "Case is already closed", 409)
    if body.resolution == "cancelled":
        raise DomainError("CARRIER_CONFIRMATION_REQUIRED",
                          "Cancellation must be confirmed by the carrier or merchant system before closing", 409)
    ndr.resolve_case(db, c, body.resolution, p.actor, body.reason)
    from app.platform.workflows.engine import close_task
    for t in db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == c.id, AgentTask.status.in_(("active", "waiting", "escalated")))):
        close_task(db, t, "cancelled", "case closed by operator")
    db.commit()
    return {"ok": True, "status": c.status}


class EscalateIn(BaseModel):
    reason: str = Field(min_length=3, max_length=40, pattern=r"^[a-z_]+$")
    priority: str = Field(pattern="^(low|medium|high|urgent)$")
    summary: str = Field(min_length=5, max_length=1000)


@router.post("/{case_id}/escalate")
def escalate(case_id: str, body: EscalateIn, p: Principal = Depends(require("ndr.act")), db: Session = Depends(tenant_db)):
    c = _case(db, p, case_id)
    esc = escalations.open_escalation(db, c, body.reason, body.priority, body.summary, p.actor)
    db.commit()
    return {"id": esc.id, "code": esc.code}


@router.post("/{case_id}/retry")
def retry(case_id: str, p: Principal = Depends(require("ndr.act")), db: Session = Depends(tenant_db)):
    """Restart the recovery workflow's contact step. Contact policy, opt-outs and attempt limits still apply,
    and idempotency keys prevent duplicate messages or calls for the same step."""
    out = _bulk_retry(db, p, case_id)
    db.commit()
    return {"ok": True, "taskId": out["taskId"], "status": "queued"}


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(retry|escalate)$")
    reason: str | None = Field(default=None, max_length=500)


@router.post("/bulk")
def bulk(body: BulkIn, p: Principal = Depends(require("ndr.act")), db: Session = Depends(tenant_db)):
    """Each case is validated and executed independently; partial failures are reported per case."""
    results = []
    for cid in dict.fromkeys(body.ids):
        try:
            with db.begin_nested():
                if body.action == "retry":
                    out = _bulk_retry(db, p, cid)
                else:
                    c = _case(db, p, cid)
                    escalations.open_escalation(db, c, "operator_bulk", "medium", body.reason or "Bulk escalation", p.actor)
                    out = {"ok": True}
            results.append({"id": cid, "ok": True, **({k: v for k, v in out.items() if k != "ok"} if isinstance(out, dict) else {})})
        except DomainError as exc:
            results.append({"id": cid, "ok": False, "code": exc.code, "message": exc.message})
    db.commit()
    return {"results": results, "succeeded": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results)}


def _bulk_retry(db: Session, p: Principal, cid: str) -> dict:
    c = _case(db, p, cid)
    task = db.scalars(select(AgentTask).where(AgentTask.ndr_case_id == c.id).order_by(AgentTask.created_at.desc())).first()
    if task is None or task.status in ("completed", "cancelled", "superseded") or c.status in ("resolved", "closed_no_response", "rto"):
        raise DomainError("NOT_RETRYABLE", "No active workflow", 409)
    from app.platform.workflows.engine import trigger
    task.status = "active"
    trigger(db, task, "operator_retry", {"by": p.user_id})
    audit.record(db, p.actor, p.merchant_id, "agent_task", task.id, "agent_task.retry_requested")
    return {"taskId": task.id}


__all__ = ["router", "build_timeline", "DeliveryAttempt", "date"]
