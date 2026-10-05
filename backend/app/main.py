from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Body, FastAPI, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .carriers.registry import ADAPTERS
from .logs import RequestIdMiddleware, log, setup_logging
from .mock_carriers.router import router as mock_router
from .schemas import (ErrorOut, MessageIn, NdrDetailOut, NdrSummaryOut, OrderIn, OrderOut, QuarantineOut,
                      RatesOut, SelectIn, ShipmentOut, TrackingOut, WebhookOut)
from .seed import seed
from .services import dashboard, ndr, orders, rates, shipments
from .util import ApiError, out

DESCRIPTION = """
Zippy logistics + NDR agent MVP. Normalises three differently-shaped carrier APIs (FastShip, QuickExpress,
ReliableCourier), caches rates in Redis, ingests idempotent carrier webhooks and runs an NDR recovery flow
(simulated WhatsApp -> intent -> rules -> carrier reattempt).

All JSON uses camelCase. Every response carries an `X-Request-ID` header (send your own to correlate logs).
Errors are `{"error": "<message>", ...details}`.
"""
TAGS = [
    {"name": "Orders", "description": "Create orders (idempotent on merchantId + merchantOrderId)."},
    {"name": "Rates", "description": "Aggregated, normalised carrier quotes with Redis caching."},
    {"name": "Shipments", "description": "Carrier selection, shipment creation and tracking."},
    {"name": "Webhooks", "description": "Carrier status webhooks (idempotent; unknown/invalid events are quarantined)."},
    {"name": "NDR", "description": "Non-delivery cases, simulated WhatsApp, intent + rules, carrier reattempt."},
    {"name": "Mock carriers", "description": "Local mock carrier APIs and controls used for the demo and tests."},
    {"name": "System", "description": "Health and dashboard."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    db.init_pool()
    db.migrate()
    if config.SEED_DEMO:
        seed()
    log("APP_STARTED", carrierTimeoutMs=config.CARRIER_TIMEOUT_MS, rateCacheTtl=config.RATE_CACHE_TTL,
        partialRateCacheTtl=config.PARTIAL_RATE_CACHE_TTL)
    yield


# Swagger UI assets are vendored under app/static so /docs works without internet access.
app = FastAPI(title="Zippy MVP API", version="1.0.0", description=DESCRIPTION, openapi_tags=TAGS, lifespan=lifespan,
              docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Zippy MVP API - Swagger UI",
                               swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
                               swagger_css_url="/static/swagger-ui/swagger-ui.css",
                               swagger_favicon_url="/static/swagger-ui/favicon-32x32.png")

app.add_middleware(RequestIdMiddleware)
app.include_router(mock_router)


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(out({"error": e.message, **e.extra}), status_code=e.status)


def E(status: int, description: str, example: dict) -> dict:
    return {"model": ErrorOut, "description": description, "content": {"application/json": {"example": example}}}


NOT_FOUND_ORDER = E(404, "Order not found", {"error": "Order ZPY-ORD-99999 not found"})
BAD_REQUEST = {422: {"description": "Validation error (FastAPI standard body)"}}


@app.get("/api/health", tags=["System"], summary="Health check")
def health():
    return {"status": "ok", "carriers": [a.name for a in ADAPTERS]}


@app.get("/api/dashboard", tags=["System"], summary="Dashboard counters and recent activity")
def get_dashboard():
    return out(dashboard.summary())


@app.post("/api/orders", tags=["Orders"], summary="Create an order (idempotent)", status_code=201,
          response_model=OrderOut,
          responses={200: {"model": OrderOut, "description": "Idempotent replay: an order already exists for this (merchantId, merchantOrderId); it is returned with `duplicate: true`."},
                     409: E(409, "Same merchantOrderId reused with different order details",
                            {"error": "merchantOrderId 'SHOP-5001' was already used for order ZPY-ORD-10002 with different details",
                             "existingOrderId": "ZPY-ORD-10002", "differingFields": ["weight_grams"]}),
                     **BAD_REQUEST})
def create_order(body: OrderIn):
    order, duplicate = orders.create_order(body.model_dump())
    return JSONResponse(out({**order, "duplicate": duplicate}), status_code=200 if duplicate else 201)


@app.get("/api/orders", tags=["Orders"], summary="List recent orders")
def list_orders():
    return out(orders.list_orders())


@app.get("/api/orders/{order_id}", tags=["Orders"], summary="Get an order (with its shipment, if any)",
         response_model=OrderOut, responses={404: NOT_FOUND_ORDER})
def get_order(order_id: str):
    return out(orders.order_detail(order_id))


RATE_ERRORS = {404: NOT_FOUND_ORDER,
               502: E(502, "Every carrier failed", {"error": "No carrier returned a rate", "errors": [
                   {"carrier": "FASTSHIP", "code": "TIMEOUT", "message": "FastShip did not respond within 3000 ms", "durationMs": 3004.1}]})}
RATE_DOC = ("Calls all carriers concurrently, each bounded by `CARRIER_TIMEOUT_MS`. Carriers that fail or time out are "
            "listed in `errors` and the rest are still returned (`partial: true`). Served from Redis when possible "
            "(`cacheStatus: HIT`); `refresh=true` bypasses and replaces the cache. If Redis is down the request still "
            "succeeds (`cacheStatus: UNAVAILABLE`). Complete results are cached for `RATE_CACHE_TTL`, partial ones "
            "for the shorter `PARTIAL_RATE_CACHE_TTL`.")


@app.post("/api/orders/{order_id}/rates", tags=["Rates"], summary="Get normalised rates", description=RATE_DOC,
          response_model=RatesOut, responses=RATE_ERRORS)
def post_rates(order_id: str, refresh: bool = Query(False, description="Ignore the cache and re-query carriers")):
    return out(rates.get_rates(order_id, refresh))


@app.get("/api/orders/{order_id}/rates", tags=["Rates"], summary="Get normalised rates (GET)",
         description=RATE_DOC, response_model=RatesOut, responses=RATE_ERRORS)
def get_rates(order_id: str, refresh: bool = Query(False, description="Ignore the cache and re-query carriers")):
    return out(rates.get_rates(order_id, refresh))


@app.post("/api/orders/{order_id}/select-carrier", tags=["Shipments"], summary="Select a quoted carrier/service",
          description="The price is taken from the stored quote; it cannot be set or changed by the client.",
          response_model=OrderOut,
          responses={400: E(400, "Carrier/service not in the stored quotes", {"error": "No stored quote for FASTSHIP/NOPE; fetch rates first"}),
                     404: NOT_FOUND_ORDER,
                     409: E(409, "Shipment already exists, or the client tried to change the quoted amount",
                            {"error": "Quoted amount cannot be modified", "quotedPrice": 182.9, "submittedPrice": 1.0}),
                     **BAD_REQUEST})
def select_carrier(order_id: str, body: SelectIn):
    return out(rates.select_carrier(order_id, body.carrier, body.service, body.price))


@app.post("/api/orders/{order_id}/shipment", tags=["Shipments"], summary="Create the shipment with the selected carrier",
          status_code=201, response_model=ShipmentOut,
          responses={404: NOT_FOUND_ORDER,
                     409: E(409, "No carrier selected, or a shipment already exists", {"error": "Select a carrier before creating a shipment"}),
                     502: E(502, "Carrier failed to create the shipment", {"error": "FastShip failed to create the shipment: FastShip returned HTTP 503", "code": "HTTP_ERROR"})})
def create_shipment(order_id: str):
    return out(shipments.create_shipment(order_id))


@app.get("/api/orders/{order_id}/tracking", tags=["Shipments"], summary="Current status and full status history",
         response_model=TrackingOut,
         responses={404: E(404, "Order or shipment not found", {"error": "No shipment for this order yet"})})
def get_tracking(order_id: str, includeRaw: bool = Query(False, description="Include each event's raw carrier payload and normalized form")):
    return out(shipments.tracking(order_id, includeRaw))


@app.get("/api/shipments", tags=["Shipments"], summary="List shipments")
def list_shipments():
    return out(shipments.list_shipments())


WEBHOOK_EXAMPLES = {
    "fastship": {"summary": "FastShip", "value": {"trackingNumber": "FST123456789", "status": "OFD", "eventId": "evt-1"}},
    "fastship_ndr": {"summary": "FastShip NDR", "value": {"trackingNumber": "FST123456789", "status": "NDR", "eventId": "evt-2", "reasonCode": "CUST_NA"}},
    "quickexpress": {"summary": "QuickExpress", "value": {"awb": "QXP1234567890", "id": "9f2c", "event": {"code": "OUT_FOR_DELIVERY"}}},
    "reliable": {"summary": "ReliableCourier", "value": {"reference": "RLC123456789", "seq": "17", "state": "Out For Delivery"}},
}


@app.post("/api/webhooks/{carrier}", tags=["Webhooks"], summary="Receive a carrier status webhook",
          description="`carrier` is `fastship`, `quickexpress` or `reliable`; each has its own payload shape. "
                      "Events are idempotent on carrier + trackingNumber + status + eventId. The raw payload and the "
                      "normalised event are both stored. Unknown tracking numbers and invalid status transitions are "
                      "quarantined (HTTP 202) and never change a shipment.",
          response_model=WebhookOut,
          responses={202: {"model": WebhookOut, "description": "Quarantined: unknown tracking number or invalid transition"},
                     400: {"model": WebhookOut, "description": "Unparseable payload (stored in quarantine)",
                           "content": {"application/json": {"example": {"status": "rejected", "reason": "UNPARSEABLE_PAYLOAD", "message": "Payload is not a valid FastShip webhook; stored for investigation"}}}},
                     404: E(404, "Unknown carrier slug", {"error": "Unknown carrier nope"})})
def webhook(carrier: str, payload: dict = Body(..., openapi_examples=WEBHOOK_EXAMPLES)):
    body, status = shipments.handle_webhook(carrier, payload)
    return JSONResponse(out(body), status_code=status)


@app.get("/api/webhook-quarantine", tags=["Webhooks"], summary="Investigation log of quarantined webhook events",
         response_model=list[QuarantineOut])
def quarantine():
    return out(shipments.list_quarantine())


@app.get("/api/ndr", tags=["NDR"], summary="List NDR cases", response_model=list[NdrSummaryOut])
def list_ndr():
    return out(ndr.list_cases())


NDR_404 = {404: E(404, "NDR case not found", {"error": "NDR case NDR-9999 not found"})}


@app.get("/api/ndr/{case_id}", tags=["NDR"], summary="NDR case detail (conversation, intent, decision, actions, audit)",
         response_model=NdrDetailOut, responses=NDR_404)
def get_ndr(case_id: str):
    return out(ndr.case_detail(case_id))


@app.post("/api/ndr/{case_id}/contact", tags=["NDR"], summary="Contact the buyer (sends the first simulated WhatsApp message)",
          response_model=NdrDetailOut, responses=NDR_404)
def contact(case_id: str):
    return out(ndr.contact_buyer(case_id))


@app.post("/api/ndr/{case_id}/message", tags=["NDR"], summary="Buyer reply (simulated WhatsApp) -> intent -> rules decision",
          response_model=NdrDetailOut,
          responses={**NDR_404, 409: E(409, "Case already acted on", {"error": "Case is RESOLVED; no further buyer requests accepted"}), **BAD_REQUEST})
def message(case_id: str, body: MessageIn):
    return out(ndr.buyer_message(case_id, body.message))


@app.post("/api/ndr/{case_id}/reattempt", tags=["NDR"], summary="Request a carrier reattempt (only if the rules engine allows it)",
          description="The buyer is told the request was *submitted* before the carrier is called, and that it was "
                      "*accepted* only after the carrier replies ACCEPTED.",
          response_model=NdrDetailOut,
          responses={**NDR_404, 409: E(409, "Not allowed by the rules engine, or case not in a state that permits it",
                                       {"error": "Rules engine does not allow an automatic reattempt",
                                        "decision": {"outcome": "REQUIRES_APPROVAL", "reasons": ["Address / pincode changes need approval"]}})})
def reattempt(case_id: str):
    return out(ndr.reattempt(case_id))
