from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import config, db
from .carriers.registry import ADAPTERS
from .mock_carriers.router import router as mock_router
from .seed import seed
from .services import dashboard, ndr, orders, rates, shipments
from .util import ApiError, out


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool()
    db.migrate()
    if config.SEED_DEMO:
        seed()
    yield


app = FastAPI(title="Zippy MVP", lifespan=lifespan)
app.include_router(mock_router)


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(out({"error": e.message, **e.extra}), status_code=e.status)


def _camel(s: str) -> str:
    h, *r = s.split("_")
    return h + "".join(x.capitalize() for x in r)


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class OrderIn(Camel):
    customer_name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\d{10}$")
    address: str = ""
    pickup_pincode: str = Field(pattern=r"^\d{6}$")
    delivery_pincode: str = Field(pattern=r"^\d{6}$")
    weight_kg: float = Field(gt=0, le=100)
    payment_mode: str = Field(pattern=r"^(COD|PREPAID)$")
    cod_amount: float = Field(default=0, ge=0)


class SelectIn(Camel):
    carrier: str
    service: str


class MessageIn(Camel):
    message: str


@app.get("/api/health")
def health():
    return {"status": "ok", "carriers": [a.name for a in ADAPTERS]}


@app.get("/api/dashboard")
def get_dashboard():
    return out(dashboard.summary())


@app.post("/api/orders", status_code=201)
def create_order(body: OrderIn):
    return out(orders.create_order(body.model_dump()))


@app.get("/api/orders")
def list_orders():
    return out(orders.list_orders())


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    return out(orders.order_detail(order_id))


@app.post("/api/orders/{order_id}/rates")
def post_rates(order_id: str, refresh: bool = False):
    return out(rates.get_rates(order_id, refresh))


@app.get("/api/orders/{order_id}/rates")
def get_rates(order_id: str, refresh: bool = False):
    return out(rates.get_rates(order_id, refresh))


@app.post("/api/orders/{order_id}/select-carrier")
def select_carrier(order_id: str, body: SelectIn):
    return out(rates.select_carrier(order_id, body.carrier, body.service))


@app.post("/api/orders/{order_id}/shipment", status_code=201)
def create_shipment(order_id: str):
    return out(shipments.create_shipment(order_id))


@app.get("/api/orders/{order_id}/tracking")
def get_tracking(order_id: str):
    return out(shipments.tracking(order_id))


@app.get("/api/shipments")
def list_shipments():
    return out(shipments.list_shipments())


@app.post("/api/webhooks/{carrier}")
def webhook(carrier: str, payload: dict = Body(...)):
    return out(shipments.handle_webhook(carrier, payload))


@app.get("/api/ndr")
def list_ndr():
    return out(ndr.list_cases())


@app.get("/api/ndr/{case_id}")
def get_ndr(case_id: str):
    return out(ndr.case_detail(case_id))


@app.post("/api/ndr/{case_id}/contact")
def contact(case_id: str):
    return out(ndr.contact_buyer(case_id))


@app.post("/api/ndr/{case_id}/message")
def message(case_id: str, body: MessageIn):
    return out(ndr.buyer_message(case_id, body.message))


@app.post("/api/ndr/{case_id}/reattempt")
def reattempt(case_id: str):
    return out(ndr.reattempt(case_id))
