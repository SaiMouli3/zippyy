"""Shipments, carrier actions and the escalation inbox."""
from datetime import date

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError, not_found
from app.models import Order, Shipment
from app.platform import carrier_actions, clock, escalations
from app.platform.api.common import Page, iso, page_response
from app.platform.api.ndr_api import _action, _decision, build_timeline
from app.platform.auth import Principal, require, tenant_db
from app.platform.models import (AgentTask, CarrierAction, CarrierActionEvent, Customer, DeliveryAttempt,
                                 DeliveryPreference, Escalation, EscalationNote, Message, NdrCase, RuleDecision,
                                 User, VoiceCall, Address)
from app.platform.security import crypto
from app.platform.shipments import ShipmentImport, import_shipment

router = APIRouter(prefix="/api/v1", tags=["operations"])


# ================================================================== shipments
def _ship_row(s: Shipment, o: Order, cu: Customer | None, ad: Address | None, case: NdrCase | None) -> dict:
    return {"id": s.id, "code": s.code, "awb": s.tracking_number, "carrier": s.carrier_code, "status": s.current_status,
            "attempts": s.attempt_count, "orderRef": o.code or o.merchant_order_id, "paymentMode": o.payment_type,
            "codAmountPaise": int(float(o.cod_amount or 0) * 100), "orderValuePaise": o.order_value_paise,
            "customerName": cu.name if cu else None, "phoneMasked": crypto.mask_phone(cu.phone_last4) if cu else None,
            "city": ad.city if ad else None, "state": ad.state if ad else None, "pincode": ad.pincode if ad else o.delivery_pincode,
            "createdAt": iso(s.created_at), "lastEventAt": iso(s.last_event_at), "deliveredAt": iso(s.delivered_at),
            "etaEnd": iso(s.eta_end), "ndrCaseId": case.id if case else None, "ndrCode": case.code if case else None,
            "ndrStatus": case.status if case else None}


@router.get("/shipments")
def list_shipments(page: Page = Depends(), q: str | None = None, status: str | None = None, carrier: str | None = None,
                   hasNdr: bool | None = None, p: Principal = Depends(require("shipments.read")),
                   db: Session = Depends(tenant_db)):
    f = [Shipment.merchant_id == p.merchant_id]
    if status:
        f.append(Shipment.current_status.in_(status.split(",")))
    if carrier:
        f.append(Shipment.carrier_code.in_(carrier.split(",")))
    if q:
        term = q.strip()[:100]
        f.append(Shipment.tracking_number.ilike(f"%{term}%") | Shipment.code.ilike(f"%{term}%")
                 | Shipment.order_id.in_(select(Order.id).where(Order.merchant_id == p.merchant_id,
                                                                (Order.code.ilike(f"%{term}%")) | (Order.merchant_order_id.ilike(f"%{term}%"))))
                 | Shipment.order_id.in_(select(Order.id).join(Customer, Customer.id == Order.customer_id)
                                         .where(Order.merchant_id == p.merchant_id, Customer.name.ilike(f"%{term}%"))))
    if hasNdr is not None:
        sub = select(NdrCase.shipment_id).where(NdrCase.merchant_id == p.merchant_id)
        f.append(Shipment.id.in_(sub) if hasNdr else Shipment.id.not_in(sub))
    total = db.scalar(select(func.count()).select_from(Shipment).where(*f)) or 0
    rows = list(db.execute(select(Shipment, Order).join(Order, Order.id == Shipment.order_id).where(*f)
                           .order_by(Shipment.created_at.desc(), Shipment.id).offset(page.offset).limit(page.size)).all())
    cids = [o.customer_id for _, o in rows if o.customer_id]
    aids = [o.address_id for _, o in rows if o.address_id]
    cust = {c.id: c for c in db.scalars(select(Customer).where(Customer.id.in_(cids)))} if cids else {}
    addr = {a.id: a for a in db.scalars(select(Address).where(Address.id.in_(aids)))} if aids else {}
    cases = {}
    if rows:
        for c in db.scalars(select(NdrCase).where(NdrCase.shipment_id.in_([s.id for s, _ in rows])).order_by(NdrCase.opened_at)):
            cases[c.shipment_id] = c
    return page_response([_ship_row(s, o, cust.get(o.customer_id), addr.get(o.address_id), cases.get(s.id)) for s, o in rows],
                         total, page)


def _shipment(db: Session, p: Principal, sid: str) -> Shipment:
    s = db.get(Shipment, sid) or db.scalars(select(Shipment).where(
        (Shipment.tracking_number == sid) | (Shipment.code == sid))).first()
    if s is None or s.merchant_id != p.merchant_id:
        raise not_found("Shipment")
    return s


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, p: Principal = Depends(require("shipments.read")), db: Session = Depends(tenant_db)):
    s = _shipment(db, p, shipment_id)
    o = db.get(Order, s.order_id)
    case = db.scalars(select(NdrCase).where(NdrCase.shipment_id == s.id).order_by(NdrCase.opened_at.desc())).first()
    out = _ship_row(s, o, db.get(Customer, o.customer_id) if o.customer_id else None,
                    db.get(Address, o.address_id) if o.address_id else None, case)
    task = db.scalars(select(AgentTask).where(AgentTask.shipment_id == s.id, AgentTask.task_type == "pre_delivery")).first()
    out["preDelivery"] = {"status": task.status, "outcome": (task.state or {}).get("outcome")} if task else None
    pref = db.scalars(select(DeliveryPreference).where(DeliveryPreference.shipment_id == s.id)
                      .order_by(DeliveryPreference.created_at.desc())).first()
    out["preference"] = {"date": iso(pref.requested_date), "window": pref.requested_window, "status": pref.status,
                         "channel": pref.source_channel} if pref else None
    return out


@router.get("/shipments/{shipment_id}/timeline")
def shipment_timeline(shipment_id: str, p: Principal = Depends(require("shipments.read")), db: Session = Depends(tenant_db)):
    s = _shipment(db, p, shipment_id)
    case_ids = list(db.scalars(select(NdrCase.id).where(NdrCase.shipment_id == s.id)))
    return {"items": build_timeline(db, s, case_ids), "generatedAt": clock.now().isoformat()}


@router.get("/shipments/{shipment_id}/attempts")
def shipment_attempts(shipment_id: str, p: Principal = Depends(require("shipments.read")), db: Session = Depends(tenant_db)):
    s = _shipment(db, p, shipment_id)
    rows = db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.shipment_id == s.id).order_by(DeliveryAttempt.attempt_no))
    return {"items": [{"attemptNo": a.attempt_no, "outcome": a.outcome, "reason": a.reason_code,
                       "courierRemark": a.courier_remark, "at": iso(a.attempted_at)} for a in rows]}


@router.post("/shipments/import", status_code=201)
def import_one(body: ShipmentImport, idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               p: Principal = Depends(require("shipments.import")), db: Session = Depends(tenant_db)):
    shipment, created = import_shipment(db, p.merchant_id, body, p.actor)
    db.commit()
    return {"id": shipment.id, "code": shipment.code, "awb": shipment.tracking_number, "created": created}


# ================================================================== carrier actions
def _action_row(a: CarrierAction, case_code: str | None) -> dict:
    return {**_action(a), "ndrCaseId": a.ndr_case_id, "ndrCode": case_code, "shipmentId": a.shipment_id}


@router.get("/carrier-actions")
def list_actions(page: Page = Depends(), status: str | None = None, carrier: str | None = None, action: str | None = None,
                 p: Principal = Depends(require("carrier_actions.read")), db: Session = Depends(tenant_db)):
    f = [CarrierAction.merchant_id == p.merchant_id]
    if status:
        f.append(CarrierAction.status.in_(status.split(",")))
    if carrier:
        f.append(CarrierAction.carrier_code == carrier)
    if action:
        f.append(CarrierAction.action == action)
    total = db.scalar(select(func.count()).select_from(CarrierAction).where(*f)) or 0
    rows = list(db.scalars(select(CarrierAction).where(*f).order_by(CarrierAction.requested_at.desc(), CarrierAction.id)
                           .offset(page.offset).limit(page.size)))
    codes = dict(db.execute(select(NdrCase.id, NdrCase.code).where(NdrCase.id.in_([a.ndr_case_id for a in rows if a.ndr_case_id]))).all()) if rows else {}
    return page_response([_action_row(a, codes.get(a.ndr_case_id)) for a in rows], total, page)


def _get_action(db: Session, p: Principal, action_id: str) -> CarrierAction:
    a = db.get(CarrierAction, action_id)
    if a is None or a.merchant_id != p.merchant_id:
        raise not_found("Carrier action")
    return a


@router.get("/carrier-actions/{action_id}")
def get_action(action_id: str, p: Principal = Depends(require("carrier_actions.read")), db: Session = Depends(tenant_db)):
    a = _get_action(db, p, action_id)
    events = db.scalars(select(CarrierActionEvent).where(CarrierActionEvent.action_id == a.id).order_by(CarrierActionEvent.occurred_at))
    return {**_action_row(a, None), "decision": _decision(db.get(RuleDecision, a.decision_id)),
            "events": [{"status": e.status, "detail": e.detail, "latencyMs": e.latency_ms, "at": iso(e.occurred_at)} for e in events]}


@router.post("/carrier-actions/{action_id}/reconcile")
def reconcile(action_id: str, p: Principal = Depends(require("carrier_actions.reconcile")), db: Session = Depends(tenant_db)):
    a = _get_action(db, p, action_id)
    if a.status not in ("unknown", "requested", "timed_out", "failed"):
        raise DomainError("NOTHING_TO_RECONCILE", f"Action is {a.status}; the carrier already answered", 409)
    outcome = carrier_actions.reconcile(db, a, 0, actor=p.actor)
    db.commit()
    return {"outcome": outcome, "status": a.status}


# ================================================================== escalations
def _esc_row(e: Escalation, case: NdrCase | None, names: dict, users: dict) -> dict:
    return {"id": e.id, "code": e.code, "reason": e.reason, "priority": e.priority, "status": e.status,
            "summary": e.summary, "assignedTo": e.assigned_to, "assigneeName": users.get(e.assigned_to),
            "supervisorRequested": e.supervisor_requested, "pendingDecisionId": e.pending_decision_id,
            "slaDueAt": iso(e.sla_due_at), "createdAt": iso(e.created_at), "resolvedAt": iso(e.resolved_at),
            "resolution": e.resolution_outcome, "resolutionReason": e.resolution_reason,
            "ndrCaseId": e.ndr_case_id, "ndrCode": case.code if case else None, "shipmentId": case.shipment_id if case else None,
            "awb": case.awb if case else None, "carrier": case.carrier_code if case else None,
            "ndrReason": case.reason if case else None, "customerName": names.get(case.customer_id) if case else None}


@router.get("/escalations")
def list_escalations(page: Page = Depends(), status: str = "open,assigned", priority: str | None = None,
                     mine: bool = False, p: Principal = Depends(require("escalations.read")), db: Session = Depends(tenant_db)):
    f = [Escalation.merchant_id == p.merchant_id]
    if status:
        f.append(Escalation.status.in_(status.split(",")))
    if priority:
        f.append(Escalation.priority.in_(priority.split(",")))
    if mine:
        f.append(Escalation.assigned_to == p.user_id)
    total = db.scalar(select(func.count()).select_from(Escalation).where(*f)) or 0
    from sqlalchemy import case as sa_case
    prio = sa_case({"urgent": 0, "high": 1, "medium": 2, "low": 3}, value=Escalation.priority)
    rows = list(db.scalars(select(Escalation).where(*f).order_by(prio, Escalation.sla_due_at, Escalation.id)
                           .offset(page.offset).limit(page.size)))
    cases = {c.id: c for c in db.scalars(select(NdrCase).where(NdrCase.id.in_([e.ndr_case_id for e in rows])))} if rows else {}
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.id.in_([c.customer_id for c in cases.values() if c.customer_id]))).all()) if cases else {}
    users = dict(db.execute(select(User.id, User.name).where(User.id.in_([e.assigned_to for e in rows if e.assigned_to]))).all()) if rows else {}
    return page_response([_esc_row(e, cases.get(e.ndr_case_id), names, users) for e in rows], total, page)


@router.get("/escalations/{escalation_id}")
def get_escalation(escalation_id: str, p: Principal = Depends(require("escalations.read")), db: Session = Depends(tenant_db)):
    e = db.get(Escalation, escalation_id)
    if e is None or e.merchant_id != p.merchant_id:
        raise not_found("Escalation")
    case = db.get(NdrCase, e.ndr_case_id)
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.id == case.customer_id)).all()) if case.customer_id else {}
    users = dict(db.execute(select(User.id, User.name)).all())
    notes = db.scalars(select(EscalationNote).where(EscalationNote.escalation_id == e.id).order_by(EscalationNote.created_at))
    excerpts = list(db.scalars(select(Message).where(Message.ndr_case_id == case.id).order_by(Message.created_at.desc()).limit(6)))
    calls = list(db.scalars(select(VoiceCall).where(VoiceCall.ndr_case_id == case.id).order_by(VoiceCall.created_at.desc()).limit(4)))
    actions = list(db.scalars(select(CarrierAction).where(CarrierAction.ndr_case_id == case.id).order_by(CarrierAction.requested_at.desc())))
    return {**_esc_row(e, case, names, users),
            "notes": [{"kind": n.kind, "body": n.body, "author": users.get(n.author_id) or ("Zippyy agent" if not n.author_id else n.author_id),
                       "at": iso(n.created_at)} for n in notes],
            "pendingDecision": _decision(db.get(RuleDecision, e.pending_decision_id)) if e.pending_decision_id else None,
            "excerpts": [{"direction": m.direction, "body": m.body[:400], "language": m.language, "at": iso(m.created_at),
                          "status": m.delivery_status} for m in reversed(excerpts)],
            "calls": [{"id": c.id, "code": c.code, "status": c.status, "result": c.result, "at": iso(c.created_at),
                       "language": c.final_language} for c in calls],
            "attempts": case.attempt_no, "lastCarrierResponse": _action(actions[0]) if actions else None,
            "carrierActions": [_action(a) for a in actions], "caseSlaDueAt": iso(case.sla_due_at)}


class AssignIn(BaseModel):
    userId: str | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class DecideIn(BaseModel):
    approve: bool
    reason: str = Field(min_length=5, max_length=500)
    confirm: bool = Field(description="Explicit confirmation for a consequential action")


class ResolveEscIn(BaseModel):
    outcome: str
    reason: str = Field(min_length=5, max_length=500)
    closeCase: bool = False


class SupervisorIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class CorrectIn(BaseModel):
    requestedDate: date | None = None
    requestedWindow: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    language: str | None = Field(default=None, pattern="^(en|hi|te|ta|kn|ml|mr|bn|gu|pa|or)$")
    reason: str = Field(min_length=5, max_length=500)


@router.post("/escalations/{escalation_id}/assign")
def assign(escalation_id: str, body: AssignIn, p: Principal = Depends(require("escalations.act")), db: Session = Depends(tenant_db)):
    e = escalations.assign(db, p.merchant_id, escalation_id, body.userId, p.actor)
    db.commit()
    return {"ok": True, "status": e.status}


@router.post("/escalations/{escalation_id}/notes")
def note(escalation_id: str, body: NoteIn, p: Principal = Depends(require("escalations.act")), db: Session = Depends(tenant_db)):
    escalations.add_note(db, p.merchant_id, escalation_id, body.body, p.actor)
    db.commit()
    return {"ok": True}


@router.post("/escalations/{escalation_id}/decision")
def decide(escalation_id: str, body: DecideIn, p: Principal = Depends(require("escalations.approve")), db: Session = Depends(tenant_db)):
    if not body.confirm:
        raise DomainError("CONFIRMATION_REQUIRED", "Confirm the action explicitly", 422)
    out = escalations.decide_pending(db, p.merchant_id, escalation_id, body.approve, body.reason, p.actor)
    db.commit()
    return out


@router.post("/escalations/{escalation_id}/supervisor")
def supervisor(escalation_id: str, body: SupervisorIn, p: Principal = Depends(require("escalations.act")), db: Session = Depends(tenant_db)):
    escalations.request_supervisor(db, p.merchant_id, escalation_id, body.reason, p.actor)
    db.commit()
    return {"ok": True}


@router.post("/escalations/{escalation_id}/correct-preference")
def correct(escalation_id: str, body: CorrectIn, p: Principal = Depends(require("preferences.correct")), db: Session = Depends(tenant_db)):
    escalations.correct_preference(db, p.merchant_id, escalation_id, body.requestedDate, body.requestedWindow,
                                   body.language, body.reason, p.actor)
    db.commit()
    return {"ok": True}


@router.post("/escalations/{escalation_id}/resolve")
def resolve(escalation_id: str, body: ResolveEscIn, p: Principal = Depends(require("escalations.act")), db: Session = Depends(tenant_db)):
    if body.closeCase and not p.can("ndr.resolve"):
        raise DomainError("FORBIDDEN", "You cannot close cases", 403)
    e = escalations.resolve(db, p.merchant_id, escalation_id, body.outcome, body.reason, p.actor, body.closeCase)
    db.commit()
    return {"ok": True, "status": e.status}


@router.post("/escalations/{escalation_id}/retry")
def retry_task(escalation_id: str, p: Principal = Depends(require("escalations.act", "agent_runs.retry")), db: Session = Depends(tenant_db)):
    e = db.get(Escalation, escalation_id)
    if e is None or e.merchant_id != p.merchant_id:
        raise not_found("Escalation")
    from app.platform.api.ndr_api import _bulk_retry
    out = _bulk_retry(db, p, e.ndr_case_id)
    escalations.add_note(db, p.merchant_id, escalation_id, "Operator restarted the automated contact step", p.actor)
    db.commit()
    return {"ok": True, **out}


__all__ = ["router", "DeliveryPreference"]
