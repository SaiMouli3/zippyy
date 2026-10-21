"""Durable agent workflow engine.

* An `AgentTask` is the persistent state of one workflow (pre-delivery or NDR recovery) for one delivery cycle.
* Every stimulus (NDR opened, customer replied, call finished, carrier answered, timer fired, operator acted)
  is a `trigger`, delivered as an `agent_task` job. The handler locks the task row, so triggers for the same
  task are processed one at a time even with many workers.
* Each trigger produces one `AgentRun` whose ordered, append-only `AgentRunStep`s are what the operator sees:
  what was looked at, which tool was called with which (sanitized) inputs, what came back, which rule decided.
* Timers are jobs with a dedupe key so they can be cancelled when they become obsolete (e.g. customer replied,
  parcel delivered). A trigger reaching a finished task is dropped and recorded: obsolete follow-ups never
  contact the customer.
"""
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform import audit, clock, jobs, outbox
from app.platform.ids import correlation_id
from app.platform.models import AgentRun, AgentRunStep, AgentTask, Job

log = logging.getLogger("zippy.agent")
TERMINAL_TASK = ("completed", "cancelled", "failed", "superseded")
_MAX_FIELD = 2000


def _clip(value):
    if isinstance(value, str):
        return value if len(value) <= _MAX_FIELD else value[:_MAX_FIELD] + "…"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value[:50]]
    return value


class StepHandle:
    def __init__(self, step: AgentRunStep):
        self.step = step

    def set(self, **fields) -> None:
        for k, v in fields.items():
            if k in ("input", "output"):
                v = _clip(audit.scrub(v))
            setattr(self.step, k, v)


class RunRecorder:
    def __init__(self, db: Session, task: AgentTask | None, merchant_id: str, agent_name: str, trigger: str,
                 ndr_case_id: str | None = None, shipment_id: str | None = None):
        self.db = db
        self.merchant_id = merchant_id
        self.run = AgentRun(merchant_id=merchant_id, task_id=task.id if task else None,
                            ndr_case_id=ndr_case_id or (task.ndr_case_id if task else None),
                            shipment_id=shipment_id or (task.shipment_id if task else None), agent_name=agent_name,
                            trigger=trigger, correlation_id=task.correlation_id if task else correlation_id())
        db.add(self.run)
        db.flush()
        self._seq = 0

    def _new(self, kind: str, purpose: str, status: str, **fields) -> AgentRunStep:
        self._seq += 1
        for k in ("input", "output"):
            if k in fields:
                fields[k] = _clip(audit.scrub(fields[k]))
        step = AgentRunStep(merchant_id=self.merchant_id, run_id=self.run.id, seq=self._seq, kind=kind,
                            purpose=purpose[:300], status=status, **fields)
        step.finished_at = clock.now()
        step.duration_ms = 0
        self.db.add(step)
        self.run.step_count = self._seq
        if status in ("failed", "timed_out", "rejected"):
            self.run.has_failures = True
        return step

    def note(self, kind: str, purpose: str, status: str = "completed", **fields) -> AgentRunStep:
        return self._new(kind, purpose, status, **fields)

    @contextmanager
    def tool(self, name: str, purpose: str, version: str = "1", input: dict | None = None, provider: str | None = None):
        step = self._new("tool_call", purpose, "requested", tool_name=name, tool_version=version, input=input or {},
                         provider=provider)
        step.started_at = clock.now()
        started = time.perf_counter()
        handle = StepHandle(step)
        try:
            yield handle
            if step.status == "requested":
                step.status = "completed"
        except Exception as exc:
            step.status = "failed"
            step.error = f"{type(exc).__name__}: {str(exc)[:250]}"
            self.run.has_failures = True
            raise
        finally:
            step.duration_ms = int((time.perf_counter() - started) * 1000)
            step.finished_at = clock.now()
            if step.status in ("failed", "timed_out", "rejected"):
                self.run.has_failures = True

    def finish(self, status: str = "completed", next_action: str | None = None, next_action_at: datetime | None = None,
               error: str | None = None) -> None:
        self.run.status = status
        self.run.finished_at = clock.now()
        self.run.next_action = next_action
        self.run.next_action_at = next_action_at
        self.run.error = error[:300] if error else None


# ---------------------------------------------------------------- triggers and timers
def trigger(db: Session, task: AgentTask, name: str, data: dict | None = None, at: datetime | None = None,
            dedupe_key: str | None = None) -> None:
    jobs.enqueue(db, "agent_task", {"task_id": task.id, "trigger": name, "data": data or {}},
                 merchant_id=task.merchant_id, run_at=at, dedupe_key=dedupe_key, max_attempts=4,
                 correlation_id=task.correlation_id)


def set_timer(db: Session, task: AgentTask, name: str, at: datetime) -> None:
    key = f"timer:{task.id}:{name}"
    jobs.cancel(db, key)
    trigger(db, task, f"timer:{name}", at=at, dedupe_key=key)
    timers = dict(task.state.get("timers", {}))
    timers[name] = at.isoformat()
    task.state = {**task.state, "timers": timers}
    task.next_run_at = min([datetime.fromisoformat(v) for v in timers.values()], default=None)


def cancel_timer(db: Session, task: AgentTask, name: str) -> None:
    jobs.cancel(db, f"timer:{task.id}:{name}")
    timers = dict(task.state.get("timers", {}))
    timers.pop(name, None)
    task.state = {**task.state, "timers": timers}
    task.next_run_at = min([datetime.fromisoformat(v) for v in timers.values()], default=None)


def cancel_all_timers(db: Session, task: AgentTask) -> list[str]:
    names = list(task.state.get("timers", {}))
    for name in names:
        cancel_timer(db, task, name)
    return names


def close_task(db: Session, task: AgentTask, status: str, reason: str) -> list[str]:
    cancelled = cancel_all_timers(db, task)
    task.status = status
    task.waiting_for = None
    task.current_step = "done"
    task.next_run_at = None
    task.state = {**task.state, "closed_reason": reason}
    outbox.emit(db, task.merchant_id, "agent_task", task.id, f"agent_task.{status}",
                {"taskType": task.task_type, "reason": reason, "ndrCaseId": task.ndr_case_id,
                 "shipmentId": task.shipment_id}, task.correlation_id)
    return cancelled


def load_for_update(db: Session, task_id: str) -> AgentTask | None:
    q = select(AgentTask).where(AgentTask.id == task_id)
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    return db.scalars(q).first()


def handle_agent_task(db: Session, job: Job) -> None:
    from app.platform.workflows import WORKFLOWS

    payload = job.payload
    task = load_for_update(db, payload["task_id"])
    if task is None:
        raise jobs.PermanentError("task not found")
    trigger_name = payload["trigger"]
    if task.status in TERMINAL_TASK:
        # Obsolete follow-up (case resolved, parcel delivered, superseded): record and do nothing.
        rec = RunRecorder(db, task, task.merchant_id, WORKFLOWS[task.task_type].agent_name, trigger_name)
        rec.note("note", f"Ignored '{trigger_name}': task is already {task.status}", status="cancelled",
                 output={"taskStatus": task.status})
        rec.finish("completed", next_action=None)
        return
    workflow = WORKFLOWS[task.task_type](db, task, trigger_name)
    try:
        workflow.handle(trigger_name, payload.get("data") or {})
        workflow.rec.finish("completed", workflow.next_action, task.next_run_at)
    except jobs.RetryLater:
        raise
    except Exception:
        # The transaction is rolled back by the job runner; the failure is recorded on the job (and retried).
        log.exception("workflow %s trigger %s failed", task.id, trigger_name)
        raise
    task.updated_at = clock.now()


def due_soon(minutes: int) -> datetime:
    return clock.now() + timedelta(minutes=minutes)
