"""Background worker: `python -m app.platform.worker`

Runs any number of replicas safely: jobs are claimed with FOR UPDATE SKIP LOCKED and leases, so a crashed
replica's work is picked up by another after the lease expires. Each job runs in its own tenant-bound session.
Also publishes the outbox (to in-process consumers) and runs the periodic SLA sweep.
"""
import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.db import new_session
from app.platform import clock, jobs
from app.platform.logging_setup import configure_logging
from app.platform.models import Merchant, OutboxEvent

log = logging.getLogger("zippy.worker")


def _session(merchant_id, system: bool = False):
    # Jobs that may touch several tenants' rows (ingestion, simulation, sweeps) run in system context; everything
    # else is pinned to the job's own tenant so RLS applies.
    return new_session(merchant_id=merchant_id, system=system or merchant_id is None)


def _handlers() -> dict:
    from app.platform import calls, carrier_actions, messaging, ndr
    from app.platform.simulation import carrier_sim, voice_sim, whatsapp_sim
    from app.platform.workflows.engine import handle_agent_task

    return {
        "agent_task": handle_agent_task,
        "send_message": messaging.handle_send_message,
        "place_call": calls.handle_place_call,
        "call_outcome_check": calls.handle_call_outcome_check,
        "dispatch_carrier_action": carrier_actions.handle_dispatch,
        "reconcile_carrier_action": carrier_actions.handle_reconcile,
        "sla_sweep": ndr.sla_sweep,
        # simulators (demo merchants / development only)
        "sim_whatsapp_status": whatsapp_sim.handle_status,
        "sim_whatsapp_inbound": whatsapp_sim.handle_inbound,
        "sim_voice_run": voice_sim.handle_run,
        "sim_carrier_event": carrier_sim.handle_event,
    }


SYSTEM_KINDS = {"sim_whatsapp_status", "sim_whatsapp_inbound", "sim_voice_run", "sim_carrier_event"}
_HANDLERS: dict | None = None


def handlers() -> dict:
    global _HANDLERS
    if _HANDLERS is None:
        _HANDLERS = _handlers()
    return _HANDLERS


def run_claimed(job) -> str:
    system = job.kind in SYSTEM_KINDS
    return jobs.run_job(lambda m, system_=system, **kw: _session(m, kw.get("system", system_)), job, handlers())


def publish_outbox(limit: int = 500) -> int:
    """Marks outbox events published after passing them to in-process consumers (demo carrier simulator).
    The SSE stream reads the outbox directly by id, so delivery to browsers does not depend on this step."""
    from app.platform.simulation import carrier_sim
    db = new_session(system=True)
    try:
        q = select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id).limit(limit)
        if db.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        events = list(db.scalars(q))
        for ev in events:
            carrier_sim.on_outbox(db, ev)
            ev.published_at = clock.now()
        db.commit()
        return len(events)
    finally:
        db.close()


def schedule_periodic() -> None:
    db = new_session(system=True)
    try:
        for m in db.scalars(select(Merchant.id).where(Merchant.status == "active")):
            jobs.enqueue(db, "sla_sweep", {}, merchant_id=m, dedupe_key=f"sla_sweep:{m}",
                         run_at=clock.now() + timedelta(minutes=5))
        db.commit()
    finally:
        db.close()


def drain(max_rounds: int = 10_000, until=None) -> int:
    """Run every due job (and the outbox) until nothing is due at the current clock time. Used by tests and the
    demo scenario runner, which advance a frozen clock between calls."""
    ran = 0
    for _ in range(max_rounds):
        publish_outbox()
        db = new_session(system=True)
        try:
            claimed = jobs.claim(db, get_settings().worker_batch_size)
        finally:
            db.close()
        if not claimed:
            if publish_outbox() == 0:
                return ran
            continue
        for job in claimed:
            run_claimed(job)
            ran += 1
    return ran


def next_job_time():
    from app.platform.models import Job
    db = new_session(system=True)
    try:
        return db.scalar(select(Job.run_at).where(Job.status == "queued").order_by(Job.run_at).limit(1))
    finally:
        db.close()


def recover_stale_leases() -> int:
    """Leases are honoured by `claim`; this just reports how many jobs a crashed worker left behind."""
    from app.platform.models import Job
    db = new_session(system=True)
    try:
        res = db.execute(update(Job).where(Job.status == "running", Job.lease_until < clock.now())
                         .values(status="queued", locked_by=None))
        db.commit()
        return res.rowcount or 0
    finally:
        db.close()


def main() -> None:
    configure_logging()
    settings = get_settings()
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True
        log.info("shutdown requested; finishing current batch")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started (%s)", jobs.WORKER_ID)
    recovered = recover_stale_leases()
    if recovered:
        log.warning("re-queued %s jobs left running by a stopped worker", recovered)
    last_periodic = 0.0
    while not stop["flag"]:
        if time.monotonic() - last_periodic > 300:
            schedule_periodic()
            last_periodic = time.monotonic()
        publish_outbox()
        db = new_session(system=True)
        try:
            claimed = jobs.claim(db, settings.worker_batch_size)
        except Exception:  # noqa: BLE001 - database blip: back off, never crash the loop
            log.exception("claim failed")
            claimed = []
        finally:
            db.close()
        for job in claimed:
            if stop["flag"]:
                break
            run_claimed(job)
        if not claimed:
            time.sleep(settings.worker_poll_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
