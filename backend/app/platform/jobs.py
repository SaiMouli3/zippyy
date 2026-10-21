"""Durable job queue on Postgres.

* `enqueue` inserts in the caller's transaction (so jobs exist iff the business change committed).
* `claim` takes due jobs with FOR UPDATE SKIP LOCKED and stamps a lease; a crashed worker's jobs become
  claimable again when the lease expires, and they count as an attempt.
* Failures retry with exponential backoff and jitter until max_attempts, then go to `dead` (dead-letter).
* `dedupe_key` (partial unique index over queued/running jobs) prevents duplicate pending work.
"""
import logging
import random
import socket
import os
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.platform import clock
from app.platform.models import Job

log = logging.getLogger("zippy.jobs")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


class RetryLater(Exception):
    """Raise from a handler to reschedule without counting as a failure (e.g. waiting on a provider)."""

    def __init__(self, seconds: float, reason: str = ""):
        super().__init__(reason)
        self.seconds = seconds


class PermanentError(Exception):
    """Raise from a handler when retrying cannot help (bad payload): goes straight to dead-letter."""


def enqueue(db: Session, kind: str, payload: dict, merchant_id: str | None = None, run_at=None,
            dedupe_key: str | None = None, max_attempts: int = 5, correlation_id: str | None = None) -> Job | None:
    if dedupe_key is not None:
        existing = db.scalars(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running")))).first()
        if existing is not None:
            return None
    job = Job(kind=kind, payload=payload, merchant_id=merchant_id, run_at=run_at or clock.now(),
              dedupe_key=dedupe_key, max_attempts=max_attempts, correlation_id=correlation_id)
    if dedupe_key is None:
        db.add(job)
        return job
    try:
        with db.begin_nested():
            db.add(job)
    except IntegrityError:
        return None
    return job


def cancel(db: Session, dedupe_key: str) -> int:
    res = db.execute(update(Job).where(Job.dedupe_key == dedupe_key, Job.status == "queued")
                     .values(status="cancelled", finished_at=clock.now()))
    return res.rowcount or 0


def backoff_seconds(attempt: int, base: float = 30, cap: float = 3600) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1))) * (0.8 + random.random() * 0.4)


def claim(db: Session, limit: int, kinds: tuple[str, ...] | None = None) -> list[Job]:
    """Must be called inside system context (jobs span tenants). Commits the claim."""
    now = clock.now()
    lease = now + timedelta(seconds=get_settings().job_lease_seconds)
    q = (select(Job)
         .where(or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now)), Job.run_at <= now)
         .order_by(Job.run_at, Job.id).limit(limit))
    if kinds:
        q = q.where(Job.kind.in_(kinds))
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    jobs = list(db.scalars(q))
    for job in jobs:
        job.status = "running"
        job.locked_by = WORKER_ID
        job.lease_until = lease
        job.attempts += 1
    db.commit()
    return jobs


def run_job(session_factory: Callable[..., Session], job: Job, handlers: dict[str, Callable]) -> str:
    """Executes one claimed job in its own tenant-bound session and records the outcome."""
    handler = handlers.get(job.kind)
    db = session_factory(job.merchant_id)
    outcome = "done"
    try:
        if handler is None:
            raise PermanentError(f"no handler for job kind {job.kind}")
        handler(db, job)
        db.commit()
    except RetryLater as exc:
        db.rollback()
        outcome = "retry_later"
        _finish(session_factory, job, "queued", None, clock.now() + timedelta(seconds=exc.seconds), refund=True)
        return outcome
    except PermanentError as exc:
        db.rollback()
        log.warning("job %s (%s) dead: %s", job.id, job.kind, exc)
        _finish(session_factory, job, "dead", str(exc)[:500])
        return "dead"
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded, never lost
        db.rollback()
        err = f"{type(exc).__name__}: {str(exc)[:400]}"
        if job.attempts >= job.max_attempts:
            log.error("job %s (%s) dead after %s attempts: %s", job.id, job.kind, job.attempts, err)
            _finish(session_factory, job, "dead", err)
            return "dead"
        log.warning("job %s (%s) attempt %s failed: %s", job.id, job.kind, job.attempts, err)
        _finish(session_factory, job, "queued", err, clock.now() + timedelta(seconds=backoff_seconds(job.attempts)))
        return "retry"
    finally:
        db.close()
    _finish(session_factory, job, "done", None)
    return outcome


def _finish(session_factory, job: Job, status: str, error: str | None, run_at=None, refund: bool = False) -> None:
    db = session_factory(None, system=True)
    try:
        values = {"status": status, "last_error": error, "lease_until": None, "locked_by": None}
        if status in ("done", "dead"):
            values["finished_at"] = clock.now()
        if run_at is not None:
            values["run_at"] = run_at
        if refund:
            values["attempts"] = Job.attempts - 1
        db.execute(update(Job).where(Job.id == job.id).values(**values))
        db.commit()
    finally:
        db.close()
