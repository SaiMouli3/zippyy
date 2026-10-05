"""The tool surface shared by every conversational channel (WhatsApp, voice, future ones).

Tools call Zippy's application services. They never touch carrier APIs or carrier JSON.
`TOOL_SCHEMAS` is what you hand to an LLM provider for function calling.
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.carriers.registry import get_adapter
from app.config import get_settings
from app.domain.errors import DomainError
from app.services import orders as order_svc
from app.services import rates as rate_svc
from app.services import shipments as ship_svc
from app.services import tracking as track_svc

TOOL_SCHEMAS = [
    {
        "name": "create_order",
        "description": "Create a shipment order from the customer's details.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
                "pickup_pincode": {"type": "string"},
                "delivery_pincode": {"type": "string"},
                "weight_grams": {"type": "integer"},
                "payment_type": {"type": "string", "enum": ["PREPAID", "COD"]},
                "cod_amount": {"type": "number"},
            },
            "required": ["customer_name", "customer_phone", "pickup_pincode", "delivery_pincode", "weight_grams", "payment_type"],
        },
    },
    {
        "name": "get_shipping_rates",
        "description": "Get normalized shipping options from all carriers for an order.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
    {
        "name": "select_carrier",
        "description": "Choose one of the quoted options.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "carrier_code": {"type": "string"},
                "service_code": {"type": "string"},
                "quoted_amount": {"type": "number"},
            },
            "required": ["order_id", "carrier_code", "service_code", "quoted_amount"],
        },
    },
    {
        "name": "create_shipment",
        "description": "Book the selected carrier and get a tracking number.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
    {
        "name": "get_tracking",
        "description": "Current status and history of the order's shipment.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
]


def _option(q) -> dict:
    return {
        "quoteId": q.id,
        "carrierCode": q.carrier_code,
        "carrierName": get_adapter(q.carrier_code).name,
        "serviceCode": q.service_code,
        "serviceName": q.service_name,
        "totalCharge": float(q.total_charge),
        "estimatedMinDays": q.estimated_min_days,
        "estimatedMaxDays": q.estimated_max_days,
    }


class ZippyTools:
    """One instance per request/turn. Records every call so the API can return `toolCalls`."""

    def __init__(self, db: Session):
        self.db = db
        self.calls: list[dict] = []

    async def call(self, name: str, **args) -> dict:
        name = {"get_rates": "get_shipping_rates"}.get(name, name)
        try:
            result = await getattr(self, name)(**args)
        except DomainError as exc:
            result = {"error": exc.code, "message": exc.message}
        self.calls.append({"name": name, "arguments": args, "result": result})
        return result

    async def create_order(self, **fields) -> dict:
        fields.setdefault("merchant_id", get_settings().default_merchant_id)
        order = order_svc.create_order(self.db, fields)
        return {"orderId": order.id, "status": order.status}

    async def get_shipping_rates(self, order_id: str, refresh: bool = False) -> dict:
        r = await rate_svc.fetch_rates(self.db, order_id, refresh=refresh)
        return {"options": [_option(q) for q in r.quotes], "failedCarriers": r.failed, "cached": r.cached}

    async def select_carrier(self, order_id: str, carrier_code: str, service_code: str, quoted_amount: float) -> dict:
        s = ship_svc.select_carrier(self.db, order_id, carrier_code, service_code, Decimal(str(quoted_amount)))
        return {"shipmentId": s.id, "carrier": s.carrier_code, "quotedAmount": float(s.quoted_amount)}

    async def create_shipment(self, order_id: str) -> dict:
        s = await ship_svc.create_shipment(self.db, order_id)
        return {"shipmentId": s.id, "carrier": s.carrier_code, "trackingNumber": s.tracking_number, "status": s.current_status}

    async def get_tracking(self, order_id: str) -> dict:
        t = track_svc.get_tracking(self.db, order_id)
        return {
            **t,
            "history": [{**h, "timestamp": h["timestamp"].isoformat()} for h in t["history"]],
        }
