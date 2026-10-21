"""Carrier tracking webhooks. Raw body is kept for signature verification and the webhook inbox."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.db import new_session
from app.platform.ingest import IngestError, ingest_webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _ingest(source: str, headers: dict, raw: bytes, query: dict) -> dict:
    db = new_session(system=True)
    try:
        return ingest_webhook(db, source, headers, raw, query)
    finally:
        db.close()


async def _handle(slug: str, request: Request) -> dict:
    raw = await request.body()
    try:
        r = await run_in_threadpool(_ingest, f"carrier:{slug}", dict(request.headers), raw, dict(request.query_params))
    except IngestError as exc:
        raise HTTPException(exc.status, exc.message)
    # Always 200 for duplicates / ignored events so carriers don't retry them forever.
    return {"outcome": r["outcome"], "currentStatus": r.get("currentStatus"), "reason": r.get("reason")}


@router.post("/fastship")
async def fastship(request: Request):
    return await _handle("fastship", request)


@router.post("/quickexpress")
async def quickexpress(request: Request):
    return await _handle("quickexpress", request)


@router.post("/reliable")
async def reliable(request: Request):
    return await _handle("reliable", request)
