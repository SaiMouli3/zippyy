from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.carriers.registry import get_adapter
from app.db import get_db
from app.services import orders as order_svc
from app.services import rates as rate_svc
from app.services import shipments as ship_svc
from app.services import tracking as track_svc

router = APIRouter(prefix="/api", tags=["orders"])


def rates_out(result: rate_svc.RatesResult) -> schemas.RatesOut:
    return schemas.RatesOut(
        order_id=result.order_id,
        shipping_options=[
            schemas.ShippingOptionOut(
                quote_id=q.id, carrier_name=get_adapter(q.carrier_code).name,
                **{k: getattr(q, k) for k in (
                    "carrier_code", "service_code", "service_name", "base_charge", "cod_charge",
                    "additional_charges", "tax", "total_charge", "estimated_min_days", "estimated_max_days",
                    "quote_reference", "expires_at")},
            )
            for q in result.quotes
        ],
        failed_carriers=[
            schemas.FailedCarrierOut(carrier_code=f["carrierCode"], carrier_name=f["carrierName"], reason=f["reason"])
            for f in result.failed
        ],
        cached=result.cached,
    )


@router.post("/orders", response_model=schemas.OrderOut, status_code=201)
def create_order(body: schemas.OrderCreate, db: Session = Depends(get_db)):
    return order_svc.create_order(db, body.model_dump(exclude_none=True))


@router.get("/orders", response_model=list[schemas.OrderOut])
def list_orders(db: Session = Depends(get_db)):
    return order_svc.list_orders(db)


@router.get("/orders/{order_id}", response_model=schemas.OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    return order_svc.get_order(db, order_id)


@router.post("/orders/{order_id}/rates", response_model=schemas.RatesOut)
async def fetch_rates(order_id: str, refresh: bool = False, db: Session = Depends(get_db)):
    return rates_out(await rate_svc.fetch_rates(db, order_id, refresh=refresh))


@router.get("/orders/{order_id}/rates", response_model=schemas.RatesOut)
def get_rates(order_id: str, db: Session = Depends(get_db)):
    return rates_out(rate_svc.stored_rates(db, order_id))


@router.post("/orders/{order_id}/select-carrier", response_model=schemas.SelectionOut)
def select_carrier(order_id: str, body: schemas.SelectCarrierIn, db: Session = Depends(get_db)):
    s = ship_svc.select_carrier(db, order_id, body.carrier_code, body.service_code, body.quoted_amount)
    return schemas.SelectionOut(
        order_id=order_id, shipment_id=s.id, carrier=s.carrier_code, service_code=s.selected_service_code,
        quoted_amount=s.quoted_amount, status=s.current_status,
    )


@router.post("/orders/{order_id}/shipment", response_model=schemas.ShipmentOut)
async def create_shipment(order_id: str, db: Session = Depends(get_db)):
    s = await ship_svc.create_shipment(db, order_id)
    return schemas.ShipmentOut(
        shipment_id=s.id, carrier=s.carrier_code, tracking_number=s.tracking_number, status=s.current_status
    )


@router.get("/orders/{order_id}/tracking", response_model=schemas.TrackingOut)
def tracking(order_id: str, db: Session = Depends(get_db)):
    return track_svc.get_tracking(db, order_id)
