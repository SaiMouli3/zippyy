from datetime import datetime

from app.carriers.base import CarrierAdapter, CarrierError, HttpCall, money
from app.domain.carrier_types import NormalizedEvent, NormalizedRate, NormalizedShipment
from app.domain.enums import ShipmentStatus as S

STATUS_MAP = {
    "BOOKED": S.SHIPMENT_CREATED,
    "PICKED_UP": S.PICKED_UP,
    "IN_TRANSIT": S.IN_TRANSIT,
    "OUT_FOR_DELIVERY": S.OUT_FOR_DELIVERY,
    "DELIVERED": S.DELIVERED,
    "UNDELIVERED": S.DELIVERY_FAILED,
    "RETURNED_TO_ORIGIN": S.RTO,
}


class FastShipAdapter(CarrierAdapter):
    code = "FASTSHIP"
    name = "FastShip"
    webhook_slug = "fastship"

    def _common(self, order) -> dict:
        return {
            "origin_pin": order.pickup_pincode,
            "destination_pin": order.delivery_pincode,
            "weight_kg": order.weight_grams / 1000,
            "payment_mode": order.payment_type,
            "invoice_value": float(order.cod_amount),
        }

    def build_rate_request(self, order) -> HttpCall:
        return HttpCall("POST", "/mock/fastship/api/v1/rate", json=self._common(order))

    def build_shipment_request(self, order, quote) -> HttpCall:
        body = self._common(order) | {
            "service_code": quote.service_code,
            "consignee": {"name": order.customer_name, "phone": order.customer_phone},
            "reference": order.id,
        }
        return HttpCall("POST", "/mock/fastship/api/v1/shipments", json=body)

    def normalize_rate_response(self, response: dict) -> list[NormalizedRate]:
        if not response.get("success"):
            return []  # carrier says it cannot serve this shipment
        s = response["service"]
        return [
            NormalizedRate(
                carrier_code=self.code,
                service_code=s["service_code"],
                service_name=s["service_name"],
                base_charge=money(s["freight_charge"]),
                cod_charge=money(s.get("cod_charge", 0)),
                additional_charges=money(0),
                tax=money(s["tax"]),
                total_charge=money(s["total_amount"]),
                estimated_min_days=s["estimated_days"],
                estimated_max_days=s["estimated_days"],
                quote_reference=None,
                raw=response,
            )
        ]

    def normalize_shipment_response(self, response: dict) -> NormalizedShipment:
        if not response.get("success"):
            raise CarrierError("FastShip rejected the booking")
        return NormalizedShipment(
            self.code, response["shipment_id"], response["tracking_number"], STATUS_MAP[response["status"]], response
        )

    def normalize_webhook(self, payload: dict) -> NormalizedEvent:
        status = STATUS_MAP[payload["status"]]
        return NormalizedEvent(
            carrier_code=self.code,
            tracking_number=payload["tracking_number"],
            status=status,
            carrier_status=payload["status"],
            event_id=payload.get("event_id"),
            description=payload.get("remarks"),
            location=payload.get("location"),
            event_time=datetime.fromisoformat(payload["timestamp"]),
            raw=payload,
        )
