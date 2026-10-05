from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.carriers.registry import get_adapter_by_slug
from app.db import get_db
from app.services import tracking as track_svc

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _handle(slug: str, payload: dict, db: Session) -> dict:
    adapter = get_adapter_by_slug(slug)
    try:
        event = adapter.normalize_webhook(payload)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"unrecognised {adapter.name} webhook payload: {exc!r}")
    r = track_svc.ingest_event(db, event)
    # Always 200 for duplicates / ignored events so carriers don't retry them forever.
    return {"outcome": r.outcome, "currentStatus": r.current_status, "reason": r.reason}


@router.post("/fastship")
def fastship(payload: dict = Body(...), db: Session = Depends(get_db)):
    return _handle("fastship", payload, db)


@router.post("/quickexpress")
def quickexpress(payload: dict = Body(...), db: Session = Depends(get_db)):
    return _handle("quickexpress", payload, db)


@router.post("/reliable")
def reliable(payload: dict = Body(...), db: Session = Depends(get_db)):
    return _handle("reliable", payload, db)
