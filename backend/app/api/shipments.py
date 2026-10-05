from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import shipments as ship_svc

router = APIRouter(prefix="/api", tags=["shipments"])


@router.get("/shipments")
def list_shipments(db: Session = Depends(get_db)):
    """Admin listing (used by the dashboard)."""
    return [
        {
            "shipmentId": s.id, "orderId": s.order_id, "carrier": s.carrier_code,
            "trackingNumber": s.tracking_number, "currentStatus": s.current_status,
            "quotedAmount": float(s.quoted_amount),
        }
        for s in ship_svc.list_shipments(db)
    ]
