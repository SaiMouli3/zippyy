"""Overview KPIs, trends, queues and analytics.

Rules: every rate states its numerator and denominator; a comparison is returned only when the previous period
has data; costs come only from measured provider/carrier figures; anything not measurable is `available: false`
with a reason rather than a guessed number.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import Shipment, ShipmentEvent
from app.platform import clock
from app.platform.api.common import iso, time_range
from app.platform.api.ndr_api import ACTIVE_FOR_SLA, OPEN, build_filters
from app.platform.auth import Principal, require, tenant_db
from app.platform.models import (AgentRun, AgentRunStep, AgentTask, CarrierAction, Customer, DeliveryOutcome,
                                 DeliveryPreference, IntentExtraction, Job, Message, NdrCase, ProviderCall, VoiceCall,
                                 VoiceCallEvent)
from app.platform.security import crypto

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def _count(db: Session, model, *f) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*f)) or 0


def _metric(value, prev=None, unit: str = "count", basis: str = "measured", href: str | None = None, note: str | None = None,
            numerator=None, denominator=None) -> dict:
    out = {"value": value, "unit": unit, "basis": basis, "href": href, "note": note}
    if prev is not None:
        out["previous"] = prev
    if numerator is not None:
        out["numerator"], out["denominator"] = numerator, denominator
    return out


def _period(db: Session, p: Principal, start: datetime, end: datetime) -> dict:
    m = p.merchant_id
    ships = _count(db, Shipment, Shipment.merchant_id == m, Shipment.created_at >= start, Shipment.created_at < end)
    opened = _count(db, NdrCase, NdrCase.merchant_id == m, NdrCase.opened_at >= start, NdrCase.opened_at < end)
    recovered = _count(db, DeliveryOutcome, DeliveryOutcome.merchant_id == m, DeliveryOutcome.attribution == "recovered_after_contact",
                       DeliveryOutcome.determined_at >= start, DeliveryOutcome.determined_at < end)
    resolved = _count(db, NdrCase, NdrCase.merchant_id == m, NdrCase.resolved_at >= start, NdrCase.resolved_at < end)
    contacts = _count(db, Message, Message.merchant_id == m, Message.direction == "inbound", Message.created_at >= start,
                      Message.created_at < end) + _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status == "completed",
                                                         VoiceCall.created_at >= start, VoiceCall.created_at < end)
    calls_failed = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status == "failed", VoiceCall.created_at >= start, VoiceCall.created_at < end)
    calls_unanswered = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status.in_(("no_answer", "busy")),
                              VoiceCall.created_at >= start, VoiceCall.created_at < end)
    wa_failed = _count(db, Message, Message.merchant_id == m, Message.delivery_status == "failed", Message.created_at >= start, Message.created_at < end)
    predelivery = _count(db, DeliveryPreference, DeliveryPreference.merchant_id == m, DeliveryPreference.ndr_case_id.is_(None),
                         DeliveryPreference.status.in_(("confirmed_available", "carrier_confirmed", "noted")),
                         DeliveryPreference.created_at >= start, DeliveryPreference.created_at < end)
    rto_init = db.scalar(select(func.count()).select_from(ShipmentEvent).join(Shipment, Shipment.id == ShipmentEvent.shipment_id).where(
        Shipment.merchant_id == m, ShipmentEvent.normalized_status == "RTO", ShipmentEvent.event_time >= start, ShipmentEvent.event_time < end)) or 0
    rto_done = db.scalar(select(func.count()).select_from(ShipmentEvent).join(Shipment, Shipment.id == ShipmentEvent.shipment_id).where(
        Shipment.merchant_id == m, ShipmentEvent.normalized_status == "RTO_DELIVERED", ShipmentEvent.event_time >= start, ShipmentEvent.event_time < end)) or 0
    value = db.scalar(select(func.coalesce(func.sum(DeliveryOutcome.order_value_paise), 0)).where(
        DeliveryOutcome.merchant_id == m, DeliveryOutcome.attribution == "recovered_after_contact",
        DeliveryOutcome.determined_at >= start, DeliveryOutcome.determined_at < end)) or 0
    msg_cost = db.scalar(select(func.sum(Message.cost_paise)).where(Message.merchant_id == m, Message.created_at >= start, Message.created_at < end))
    call_cost = db.scalar(select(func.sum(VoiceCall.cost_paise)).where(VoiceCall.merchant_id == m, VoiceCall.created_at >= start, VoiceCall.created_at < end))
    fee = db.scalar(select(func.sum(CarrierAction.fee_paise)).where(CarrierAction.merchant_id == m, CarrierAction.requested_at >= start, CarrierAction.requested_at < end))
    return {"ships": ships, "opened": opened, "recovered": recovered, "resolved": resolved, "contacts": contacts,
            "calls_failed": calls_failed, "calls_unanswered": calls_unanswered, "wa_failed": wa_failed,
            "predelivery": predelivery, "rto_init": rto_init, "rto_done": rto_done, "value": int(value),
            "costs": [msg_cost, call_cost, fee]}


@router.get("/summary")
def summary(range: str = "7d", p: Principal = Depends(require("dashboard.read")), db: Session = Depends(tenant_db)):
    start, end = time_range(range)
    span = end - start
    cur = _period(db, p, start, end)
    prev = _period(db, p, start - span, start)
    has_prev = prev["ships"] > 0 or prev["opened"] > 0

    def pv(key):
        return prev[key] if has_prev else None

    now = clock.now()
    m = p.merchant_id
    open_now = _count(db, NdrCase, NdrCase.merchant_id == m, NdrCase.status.in_(OPEN))
    urgent = _count(db, NdrCase, *build_filters(p, queue="urgent"))
    breached = _count(db, NdrCase, NdrCase.merchant_id == m, NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at < now)
    at_risk = _count(db, NdrCase, NdrCase.merchant_id == m, NdrCase.status.in_(ACTIVE_FOR_SLA), NdrCase.sla_due_at >= now,
                     NdrCase.sla_due_at < now + timedelta(hours=4))
    pending_actions = _count(db, CarrierAction, CarrierAction.merchant_id == m, CarrierAction.status.in_(("requested", "unknown", "retrying")))
    measured_costs = [c for c in cur["costs"] if c is not None]
    cost = int(sum(measured_costs)) if measured_costs else None
    return {
        "range": {"start": iso(start), "end": iso(end), "label": range},
        "comparisonAvailable": has_prev,
        "metrics": {
            "totalShipments": _metric(cur["ships"], pv("ships"), href="/shipments"),
            "openNdr": _metric(open_now, note="current", href="/ndr?queue=open"),
            "needsAttention": _metric(urgent, note="current: urgent priority or past SLA", href="/ndr?queue=urgent"),
            "recovered": _metric(cur["recovered"], pv("recovered"), href="/ndr?queue=recovered",
                                 note="Delivered after an NDR with evidence of customer contact"),
            "preDeliveryConfirmations": _metric(cur["predelivery"], pv("predelivery"), href="/pre-delivery"),
            "successfulContacts": _metric(cur["contacts"], pv("contacts"), note="Customer replies + answered calls",
                                          href="/conversations"),
            "pendingCarrierActions": _metric(pending_actions, note="current", href="/ndr?queue=awaiting_carrier"),
            "failedCalls": _metric(cur["calls_failed"], pv("calls_failed"), href="/calls?status=failed",
                                   note=f"{cur['calls_unanswered']} more not answered or busy"),
            "failedWhatsApp": _metric(cur["wa_failed"], pv("wa_failed"), href="/conversations"),
            "slaAtRisk": _metric(at_risk, note="current: due within 4 hours", href="/ndr?sla=due_4h"),
            "slaBreached": _metric(breached, note="current", href="/ndr?sla=breached"),
            "rtoInitiated": _metric(cur["rto_init"], pv("rto_init"), href="/ndr?rto=initiated"),
            "rtoCompleted": _metric(cur["rto_done"], pv("rto_done"), href="/ndr?rto=completed"),
            "recoveredOrderValue": _metric(cur["value"], pv("value"), unit="paise", basis="measured",
                                           note="Order value of deliveries attributed to Zippyy contact (not modelled savings)"),
            "attributableCosts": _metric(cost, unit="paise", basis="measured" if cost is not None else "unavailable",
                                         note="Provider and carrier charges reported for this period"
                                         if cost is not None else "No provider has reported costs for this period"),
        },
        "generatedAt": now.isoformat(),
    }


def _days(start: datetime, end: datetime) -> list[str]:
    out, d = [], start.date()
    while d <= end.date():
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@router.get("/trends")
def trends(range: str = "14d", p: Principal = Depends(require("dashboard.read")), db: Session = Depends(tenant_db)):
    start, end = time_range(range)
    m = p.merchant_id
    days = _days(start, end)
    day = func.date(NdrCase.opened_at)
    opened = dict(db.execute(select(day, func.count()).where(NdrCase.merchant_id == m, NdrCase.opened_at >= start)
                             .group_by(day)).all())
    rday = func.date(NdrCase.resolved_at)
    resolved = dict(db.execute(select(rday, func.count()).where(NdrCase.merchant_id == m, NdrCase.resolved_at >= start)
                               .group_by(rday)).all())
    oday = func.date(DeliveryOutcome.determined_at)
    recovered = dict(db.execute(select(oday, func.count()).where(
        DeliveryOutcome.merchant_id == m, DeliveryOutcome.attribution == "recovered_after_contact",
        DeliveryOutcome.determined_at >= start).group_by(oday)).all())
    pday = func.date(AgentTask.created_at)
    pre_started = dict(db.execute(select(pday, func.count()).where(AgentTask.merchant_id == m, AgentTask.task_type == "pre_delivery",
                                                                   AgentTask.created_at >= start).group_by(pday)).all())
    cday = func.date(DeliveryPreference.created_at)
    pre_conf = dict(db.execute(select(cday, func.count()).where(
        DeliveryPreference.merchant_id == m, DeliveryPreference.ndr_case_id.is_(None),
        DeliveryPreference.status.in_(("confirmed_available", "carrier_confirmed", "noted")),
        DeliveryPreference.created_at >= start).group_by(cday)).all())

    def k(v):
        return str(v)[:10]
    opened, resolved, recovered = ({k(a): b for a, b in x.items()} for x in (opened, resolved, recovered))
    pre_started, pre_conf = ({k(a): b for a, b in x.items()} for x in (pre_started, pre_conf))
    series = []
    for d in days:
        res = resolved.get(d, 0)
        ps = pre_started.get(d, 0)
        series.append({"date": d, "ndrOpened": opened.get(d, 0), "ndrResolved": res, "recovered": recovered.get(d, 0),
                       "recoveryRate": round(recovered.get(d, 0) / res, 4) if res else None,
                       "preDeliveryStarted": ps, "preDeliveryConfirmed": pre_conf.get(d, 0),
                       "preDeliveryRate": round(pre_conf.get(d, 0) / ps, 4) if ps else None})
    return {"series": series, "dayBasis": "UTC",
            "definitions": {"recoveryRate": "recovered after contact ÷ NDR cases resolved that day",
                            "preDeliveryRate": "availability confirmed or preference captured ÷ pre-delivery workflows started"},
            "generatedAt": clock.now().isoformat()}


@router.get("/queues")
def queues(p: Principal = Depends(require("dashboard.read")), db: Session = Depends(tenant_db)):
    out = {}
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.merchant_id == p.merchant_id)).all())
    for q in ("urgent", "awaiting_carrier", "carrier_unknown", "callback", "call_failures", "low_confidence", "restricted",
              "escalated", "near_deadline"):
        f = build_filters(p, queue=q)
        total = _count(db, NdrCase, *f)
        top = list(db.scalars(select(NdrCase).where(*f).order_by(NdrCase.sla_due_at).limit(5)))
        out[q] = {"total": total, "items": [{"id": c.id, "code": c.code, "customerName": names.get(c.customer_id),
                                             "reason": c.reason, "carrier": c.carrier_code, "slaDueAt": iso(c.sla_due_at),
                                             "status": c.status, "pendingAction": c.pending_action} for c in top]}
    return {"queues": out, "generatedAt": clock.now().isoformat()}


@router.get("/analytics")
def analytics(range: str = "30d", p: Principal = Depends(require("analytics.read")), db: Session = Depends(tenant_db)):
    start, end = time_range(range)
    m = p.merchant_id
    in_range = and_(NdrCase.merchant_id == m, NdrCase.opened_at >= start, NdrCase.opened_at < end)
    reasons = [{"reason": r, "count": c} for r, c in db.execute(
        select(NdrCase.reason, func.count()).where(in_range).group_by(NdrCase.reason).order_by(func.count().desc())).all()]
    by_carrier = []
    for carrier, total, rec, rto, still_open in db.execute(select(
            NdrCase.carrier_code, func.count(),
            func.sum(case((NdrCase.recovery_outcome == "recovered_after_contact", 1), else_=0)),
            func.sum(case((NdrCase.resolution == "rto", 1), else_=0)),
            func.sum(case((NdrCase.status.in_(OPEN), 1), else_=0))).where(in_range).group_by(NdrCase.carrier_code)).all():
        closed = (total or 0) - (still_open or 0)
        by_carrier.append({"carrier": carrier, "cases": total, "recovered": int(rec or 0), "rto": int(rto or 0),
                           "open": int(still_open or 0), "closed": closed,
                           "recoveryRate": round((rec or 0) / closed, 4) if closed else None,
                           "rtoRate": round((rto or 0) / closed, 4) if closed else None})
    rto_by_reason = []
    for reason, closed, rto in db.execute(select(NdrCase.reason, func.count(), func.sum(case((NdrCase.resolution == "rto", 1), else_=0)))
                                          .where(in_range, NdrCase.status.in_(("resolved", "closed_no_response")))
                                          .group_by(NdrCase.reason)).all():
        rto_by_reason.append({"reason": reason, "closed": closed, "rto": int(rto or 0),
                              "rtoRate": round((rto or 0) / closed, 4) if closed else None})

    wa_sent = _count(db, Message, Message.merchant_id == m, Message.direction == "outbound", Message.created_at >= start,
                     Message.created_at < end, Message.delivery_status != "queued")
    wa_delivered = _count(db, Message, Message.merchant_id == m, Message.direction == "outbound", Message.created_at >= start,
                          Message.created_at < end, Message.delivery_status.in_(("delivered", "read")))
    wa_read = _count(db, Message, Message.merchant_id == m, Message.direction == "outbound", Message.created_at >= start,
                     Message.created_at < end, Message.delivery_status == "read")
    convs_contacted = db.scalar(select(func.count(func.distinct(Message.conversation_id))).where(
        Message.merchant_id == m, Message.direction == "outbound", Message.created_at >= start, Message.created_at < end)) or 0
    convs_replied = db.scalar(select(func.count(func.distinct(Message.conversation_id))).where(
        Message.merchant_id == m, Message.direction == "inbound", Message.created_at >= start, Message.created_at < end)) or 0
    calls_total = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.created_at >= start, VoiceCall.created_at < end,
                         VoiceCall.status.not_in(("queued", "cancelled")))
    calls_answered = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.created_at >= start, VoiceCall.created_at < end,
                            VoiceCall.status == "completed")
    call_outcomes = [{"outcome": o or "pending", "count": c} for o, c in db.execute(
        select(func.coalesce(VoiceCall.result, VoiceCall.status), func.count()).where(
            VoiceCall.merchant_id == m, VoiceCall.created_at >= start, VoiceCall.created_at < end)
        .group_by(func.coalesce(VoiceCall.result, VoiceCall.status))).all()]

    contacted_cases = select(Message.ndr_case_id).where(Message.merchant_id == m, Message.direction == "inbound")
    answered_cases = select(VoiceCall.ndr_case_id).where(VoiceCall.merchant_id == m, VoiceCall.status == "completed")
    with_contact = _count(db, NdrCase, in_range, NdrCase.status.in_(("resolved", "closed_no_response")),
                          NdrCase.id.in_(contacted_cases) | NdrCase.id.in_(answered_cases))
    delivered_after_contact = _count(db, NdrCase, in_range, NdrCase.resolution == "delivered",
                                     NdrCase.id.in_(contacted_cases) | NdrCase.id.in_(answered_cases))

    res_rows = db.execute(select(NdrCase.opened_at, NdrCase.resolved_at).where(in_range, NdrCase.resolved_at.is_not(None))).all()
    hours = [(clock.as_utc(b) - clock.as_utc(a)).total_seconds() / 3600 for a, b in res_rows if a and b]
    recovered = _count(db, DeliveryOutcome, DeliveryOutcome.merchant_id == m, DeliveryOutcome.attribution == "recovered_after_contact",
                       DeliveryOutcome.determined_at >= start, DeliveryOutcome.determined_at < end)
    costs = db.execute(select(func.sum(DeliveryOutcome.contact_cost_paise), func.sum(DeliveryOutcome.carrier_fee_paise)).where(
        DeliveryOutcome.merchant_id == m, DeliveryOutcome.attribution == "recovered_after_contact",
        DeliveryOutcome.determined_at >= start, DeliveryOutcome.determined_at < end)).one()
    measured_cost = int((costs[0] or 0) + (costs[1] or 0))
    return {
        "range": {"start": iso(start), "end": iso(end)},
        "reasons": reasons,
        "byCarrier": by_carrier,
        "rtoByReason": rto_by_reason,
        "channels": {
            "whatsapp": {"sent": wa_sent, "delivered": wa_delivered, "read": wa_read,
                         "deliveryRate": round(wa_delivered / wa_sent, 4) if wa_sent else None,
                         "conversationsContacted": convs_contacted, "conversationsReplied": convs_replied,
                         "replyRate": round(convs_replied / convs_contacted, 4) if convs_contacted else None},
            "voice": {"placed": calls_total, "answered": calls_answered,
                      "answerRate": round(calls_answered / calls_total, 4) if calls_total else None},
        },
        "callOutcomes": call_outcomes,
        "deliveryAfterContact": {"closedWithContact": with_contact, "delivered": delivered_after_contact,
                                 "rate": round(delivered_after_contact / with_contact, 4) if with_contact else None},
        "resolution": {"resolvedCases": len(hours), "avgHours": round(sum(hours) / len(hours), 1) if hours else None,
                       "medianHours": round(sorted(hours)[len(hours) // 2], 1) if hours else None},
        "costPerRecovered": {"available": recovered > 0 and measured_cost > 0,
                             "valuePaise": int(measured_cost / recovered) if recovered and measured_cost else None,
                             "recovered": recovered, "measuredCostPaise": measured_cost,
                             "note": "Measured provider and carrier charges only" if measured_cost else
                             "No measured costs reported for recovered deliveries in this period"},
        "generatedAt": clock.now().isoformat(),
    }


@router.get("/languages")
def languages(range: str = "30d", p: Principal = Depends(require("analytics.read")), db: Session = Depends(tenant_db)):
    start, end = time_range(range)
    m = p.merchant_id
    in_range = and_(NdrCase.merchant_id == m, NdrCase.opened_at >= start, NdrCase.opened_at < end)
    inferred = [{"language": l, "count": c} for l, c in db.execute(
        select(NdrCase.language_predicted, func.count()).where(in_range, NdrCase.language_predicted.is_not(None))
        .group_by(NdrCase.language_predicted)).all()]
    confirmed = [{"language": l, "count": c} for l, c in db.execute(
        select(NdrCase.language_confirmed, func.count()).where(in_range, NdrCase.language_confirmed.is_not(None))
        .group_by(NdrCase.language_confirmed)).all()]
    sources = [{"source": s or "none", "count": c} for s, c in db.execute(
        select(Customer.predicted_language_source, func.count()).where(Customer.merchant_id == m)
        .group_by(Customer.predicted_language_source)).all()]
    turn_langs = {}
    for l, c, conf in db.execute(select(VoiceCallEvent.language, func.count(), func.avg(VoiceCallEvent.language_confidence)).where(
            VoiceCallEvent.merchant_id == m, VoiceCallEvent.kind == "turn", VoiceCallEvent.speaker == "customer",
            VoiceCallEvent.occurred_at >= start).group_by(VoiceCallEvent.language)).all():
        turn_langs[l or "unknown"] = {"voiceTurns": c, "avgConfidence": round(conf, 3) if conf else None}
    for l, c, conf in db.execute(select(Message.language, func.count(), func.avg(Message.language_confidence)).where(
            Message.merchant_id == m, Message.direction == "inbound", Message.created_at >= start).group_by(Message.language)).all():
        turn_langs.setdefault(l or "unknown", {})
        turn_langs[l or "unknown"].update({"messages": c, "messageAvgConfidence": round(conf, 3) if conf else None})
    completed = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status == "completed", VoiceCall.created_at >= start)
    switched = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status == "completed", VoiceCall.created_at >= start,
                      VoiceCall.language_switch_count > 0)
    same_lang = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.status == "completed", VoiceCall.created_at >= start,
                       VoiceCall.final_language == VoiceCall.start_language)
    code_mixed = _count(db, VoiceCallEvent, VoiceCallEvent.merchant_id == m, VoiceCallEvent.kind == "turn",
                        VoiceCallEvent.code_mixed.is_(True), VoiceCallEvent.occurred_at >= start)
    unsupported = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.result == "unsupported_language", VoiceCall.created_at >= start)
    unrecognised = _count(db, VoiceCall, VoiceCall.merchant_id == m, VoiceCall.result.in_(("unresolved", "no_response")), VoiceCall.created_at >= start)
    by_lang_calls = [{"language": l, "calls": c, "avgDurationSeconds": round(d, 1) if d else None, "costPaise": int(cost) if cost else None}
                     for l, c, d, cost in db.execute(select(VoiceCall.final_language, func.count(), func.avg(VoiceCall.duration_seconds),
                                                            func.sum(VoiceCall.cost_paise)).where(
                         VoiceCall.merchant_id == m, VoiceCall.status == "completed", VoiceCall.created_at >= start)
                         .group_by(VoiceCall.final_language)).all()]
    clar = [{"language": l, "extractions": n, "clarificationRate": round((amb or 0) / n, 4) if n else None}
            for l, n, amb in db.execute(select(IntentExtraction.language, func.count(),
                                               func.sum(case((IntentExtraction.validation_status != "valid", 1), else_=0))).where(
                IntentExtraction.merchant_id == m, IntentExtraction.created_at >= start).group_by(IntentExtraction.language)).all()]
    lang_col = func.coalesce(NdrCase.language_confirmed, NdrCase.language_predicted)
    recovery = [{"language": l, "closed": closed, "recovered": int(rec or 0),
                 "recoveryRate": round((rec or 0) / closed, 4) if closed else None}
                for l, closed, rec in db.execute(select(lang_col, func.count(),
                                                        func.sum(case((NdrCase.recovery_outcome == "recovered_after_contact", 1), else_=0))).where(
                    in_range, NdrCase.status.in_(("resolved", "closed_no_response"))).group_by(lang_col)).all()]
    return {
        "inferred": inferred, "confirmed": confirmed, "predictionSources": sources,
        "detectedPerTurn": [{"language": k, **v} for k, v in turn_langs.items()],
        "calls": {"completed": completed, "withSwitch": switched, "switchRate": round(switched / completed, 4) if completed else None,
                  "completedInStartLanguage": same_lang, "codeMixedTurns": code_mixed, "unsupportedLanguage": unsupported,
                  "unrecognised": unrecognised},
        "byLanguageCalls": by_lang_calls, "clarificationByLanguage": clar, "recoveryByLanguage": recovery,
        "intentAccuracy": {"available": False, "note": "Accuracy needs human-labelled conversations; clarification rate is shown instead"},
        "generatedAt": clock.now().isoformat(),
    }


@router.get("/agent-health")
def agent_health(range: str = "7d", p: Principal = Depends(require("analytics.read")), db: Session = Depends(tenant_db)):
    start, _ = time_range(range)
    m = p.merchant_id
    runs = _count(db, AgentRun, AgentRun.merchant_id == m, AgentRun.started_at >= start)
    failed_runs = _count(db, AgentRun, AgentRun.merchant_id == m, AgentRun.started_at >= start, AgentRun.status == "failed")
    with_failures = _count(db, AgentRun, AgentRun.merchant_id == m, AgentRun.started_at >= start, AgentRun.has_failures.is_(True))
    tools = [{"tool": t, "calls": n, "failed": int(f or 0), "failureRate": round((f or 0) / n, 4) if n else None,
              "avgMs": round(ms, 1) if ms is not None else None}
             for t, n, f, ms in db.execute(select(AgentRunStep.tool_name, func.count(),
                                                  func.sum(case((AgentRunStep.status.in_(("failed", "timed_out")), 1), else_=0)),
                                                  func.avg(AgentRunStep.duration_ms)).where(
                 AgentRunStep.merchant_id == m, AgentRunStep.kind == "tool_call", AgentRunStep.started_at >= start)
                 .group_by(AgentRunStep.tool_name).order_by(func.count().desc())).all()]
    fallbacks = _count(db, IntentExtraction, IntentExtraction.merchant_id == m, IntentExtraction.created_at >= start,
                       IntentExtraction.extractor.like("%fallback%"))
    extractions = _count(db, IntentExtraction, IntentExtraction.merchant_id == m, IntentExtraction.created_at >= start)
    dead = _count(db, Job, Job.merchant_id == m, Job.status == "dead", Job.created_at >= start)
    retried = _count(db, Job, Job.merchant_id == m, Job.attempts > 1, Job.created_at >= start)
    return {"runs": runs, "failedRuns": failed_runs, "runsWithFailedSteps": with_failures, "tools": tools,
            "structuredOutputFallbacks": fallbacks, "extractions": extractions, "deadJobs": dead, "retriedJobs": retried,
            "generatedAt": clock.now().isoformat()}


__all__ = ["router", "ProviderCall", "crypto"]
