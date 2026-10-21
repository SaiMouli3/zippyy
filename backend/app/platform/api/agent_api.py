from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError, not_found
from app.platform import audit, clock
from app.platform.api.common import Page, iso, page_response
from app.platform.auth import Principal, require, tenant_db
from app.platform.models import AgentRun, AgentRunStep, AgentTask, NdrCase

router = APIRouter(prefix="/api/v1/agent-runs", tags=["agent"])


def serialize_step(s: AgentRunStep) -> dict:
    return {"id": s.id, "seq": s.seq, "kind": s.kind, "purpose": s.purpose, "tool": s.tool_name,
            "toolVersion": s.tool_version, "provider": s.provider, "status": s.status, "input": s.input,
            "output": s.output, "decisionId": s.decision_id, "extractionId": s.extraction_id,
            "carrierActionId": s.carrier_action_id, "messageId": s.message_id, "callId": s.call_id,
            "policyRule": s.policy_rule, "languageBefore": s.language_before, "languageAfter": s.language_after,
            "confidence": s.confidence, "retryCount": s.retry_count, "error": s.error,
            "startedAt": iso(s.started_at), "finishedAt": iso(s.finished_at), "durationMs": s.duration_ms}


def serialize_run(r: AgentRun, steps: list[AgentRunStep] | None = None) -> dict:
    out = {"id": r.id, "agent": r.agent_name, "trigger": r.trigger, "status": r.status, "taskId": r.task_id,
           "ndrCaseId": r.ndr_case_id, "shipmentId": r.shipment_id, "correlationId": r.correlation_id,
           "stepCount": r.step_count, "hasFailures": r.has_failures, "humanInvolved": r.human_involved,
           "nextAction": r.next_action, "nextActionAt": iso(r.next_action_at), "error": r.error,
           "startedAt": iso(r.started_at), "finishedAt": iso(r.finished_at),
           "durationMs": int((clock.as_utc(r.finished_at) - clock.as_utc(r.started_at)).total_seconds() * 1000)
           if r.finished_at else None}
    if steps is not None:
        out["steps"] = [serialize_step(s) for s in steps]
    return out


@router.get("")
def list_runs(page: Page = Depends(), trigger: str | None = None, agent: str | None = None, status: str | None = None,
              tool: str | None = None, provider: str | None = None, failed: bool = False, human: bool | None = None,
              rule: str | None = None, language: str | None = None, retries: bool = False, caseId: str | None = None,
              start: datetime | None = None, end: datetime | None = None,
              p: Principal = Depends(require("agent_runs.read")), db: Session = Depends(tenant_db)):
    f = [AgentRun.merchant_id == p.merchant_id]
    if trigger:
        f.append(AgentRun.trigger == trigger)
    if agent:
        f.append(AgentRun.agent_name == agent)
    if status:
        f.append(AgentRun.status == status)
    if failed:
        f.append(AgentRun.has_failures.is_(True))
    if human is not None:
        f.append(AgentRun.human_involved.is_(human))
    if caseId:
        f.append(AgentRun.ndr_case_id == caseId)
    if start:
        f.append(AgentRun.started_at >= start)
    if end:
        f.append(AgentRun.started_at < end)
    step_f = []
    if tool:
        step_f.append(AgentRunStep.tool_name == tool)
    if provider:
        step_f.append(AgentRunStep.provider.like(f"%{provider}%"))
    if rule:
        step_f.append(AgentRunStep.policy_rule.like(f"%{rule}%"))
    if language:
        step_f.append(or_(AgentRunStep.language_after == language, AgentRunStep.language_before == language))
    if retries:
        step_f.append(AgentRunStep.status == "retrying")
    if step_f:
        f.append(exists().where(AgentRunStep.run_id == AgentRun.id, *step_f))
    total = db.scalar(select(func.count()).select_from(AgentRun).where(*f)) or 0
    runs = list(db.scalars(select(AgentRun).where(*f).order_by(AgentRun.started_at.desc(), AgentRun.id)
                           .offset(page.offset).limit(page.size)))
    codes = dict(db.execute(select(NdrCase.id, NdrCase.code).where(NdrCase.id.in_([r.ndr_case_id for r in runs if r.ndr_case_id]))).all()) if runs else {}
    items = []
    for r in runs:
        d = serialize_run(r)
        d["ndrCode"] = codes.get(r.ndr_case_id)
        items.append(d)
    return page_response(items, total, page)


@router.get("/failed-steps")
def failed_steps(page: Page = Depends(), p: Principal = Depends(require("agent_runs.read")), db: Session = Depends(tenant_db)):
    """Focused view for support: every failed / timed-out / rejected tool step with its run and case."""
    f = [AgentRunStep.merchant_id == p.merchant_id, AgentRunStep.status.in_(("failed", "timed_out", "rejected"))]
    total = db.scalar(select(func.count()).select_from(AgentRunStep).where(*f)) or 0
    rows = db.execute(select(AgentRunStep, AgentRun).join(AgentRun, AgentRun.id == AgentRunStep.run_id).where(*f)
                      .order_by(AgentRunStep.started_at.desc()).offset(page.offset).limit(page.size)).all()
    codes = dict(db.execute(select(NdrCase.id, NdrCase.code).where(NdrCase.id.in_([r.ndr_case_id for _, r in rows if r.ndr_case_id]))).all()) if rows else {}
    items = [{**serialize_step(s), "runId": r.id, "agent": r.agent_name, "trigger": r.trigger, "ndrCaseId": r.ndr_case_id,
              "ndrCode": codes.get(r.ndr_case_id), "retryable": _retryable(db, r)} for s, r in rows]
    return page_response(items, total, page)


def _retryable(db: Session, run: AgentRun) -> bool:
    if not run.task_id:
        return False
    task = db.get(AgentTask, run.task_id)
    return task is not None and task.status in ("active", "waiting", "escalated", "failed")


def _run(db: Session, p: Principal, run_id: str) -> AgentRun:
    r = db.get(AgentRun, run_id)
    if r is None or r.merchant_id != p.merchant_id:
        raise not_found("Agent run")
    return r


@router.get("/{run_id}")
def get_run(run_id: str, p: Principal = Depends(require("agent_runs.read")), db: Session = Depends(tenant_db)):
    r = _run(db, p, run_id)
    steps = list(db.scalars(select(AgentRunStep).where(AgentRunStep.run_id == r.id).order_by(AgentRunStep.seq)))
    return serialize_run(r, steps)


@router.get("/{run_id}/events")
def run_events(run_id: str, p: Principal = Depends(require("agent_runs.read")), db: Session = Depends(tenant_db)):
    r = _run(db, p, run_id)
    return {"items": [serialize_step(s) for s in db.scalars(select(AgentRunStep).where(AgentRunStep.run_id == r.id)
                                                              .order_by(AgentRunStep.seq))]}


@router.post("/{run_id}/retry")
def retry_run(run_id: str, p: Principal = Depends(require("agent_runs.retry")), db: Session = Depends(tenant_db)):
    """Re-delivers the run's trigger to its task. Safe because every consequential step is idempotent (same
    idempotency keys) and the contact guard and policy engine re-check everything."""
    r = _run(db, p, run_id)
    if not r.task_id or not _retryable(db, r):
        raise DomainError("NOT_RETRYABLE", "This run's workflow is finished; nothing to retry", 409)
    if r.trigger.startswith("timer:") or r.trigger in ("start", "operator_retry", "message_failed"):
        trigger_name = "operator_retry" if r.trigger in ("start", "operator_retry") else r.trigger
    else:
        raise DomainError("NOT_RETRYABLE", f"Runs triggered by '{r.trigger}' are not safely retryable; use the case retry", 409)
    task = db.get(AgentTask, r.task_id)
    if task.status == "failed":
        task.status = "active"
    from app.platform.workflows.engine import trigger
    trigger(db, task, trigger_name, {"retryOf": r.id})
    audit.record(db, p.actor, p.merchant_id, "agent_run", r.id, "agent_run.retry_requested")
    db.commit()
    return {"ok": True, "status": "queued"}
