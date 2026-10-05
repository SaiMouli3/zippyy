from datetime import datetime, timezone

from app.carriers.base import CarrierAdapter, CarrierError, HttpCall, money
from app.domain.carrier_types import NormalizedEvent, NormalizedRate, NormalizedShipment
from app.domain.enums import ShipmentStatus as S

STATUS_MAP = {
    "SHIPMENT_CREATED": S.SHIPMENT_CREATED,
    "PICKUP_DONE": S.PICKED_UP,
    "IN_TRANSIT": S.IN_TRANSIT,
    "OUT_FOR_DELIVERY": S.OUT_FOR_DELIVERY,
    "DELIVERED": S.DELIVERED,
    "DELIVERY_ATTEMPT_FAILED": S.DELIVERY_FAILED,
    "RTO_INITIATED": S.RTO,
}


class QuickExpressAdapter(CarrierAdapter):
    code = "QUICKEXPRESS"
    name = "QuickExpress"
    webhook_slug = "quickexpress"

    def _common(self, order) -> dict:
        return {
            "pickupPincode": order.pickup_pincode,
            "deliveryPincode": order.delivery_pincode,
            "weightInGrams": order.weight_grams,
            "dimensions": {"length": order.length_cm, "breadth": order.width_cm, "height": order.height_cm},
            "isCod": order.payment_type == "COD",
            "collectableAmount": float(order.cod_amount),
        }

    def build_rate_request(self, order) -> HttpCall:
        return HttpCall("POST", "/mock/quickexpress/rates/check", json=self._common(order))

    def build_shipment_request(self, order, quote) -> HttpCall:
        body = self._common(order) | {
            "quoteId": quote.quote_reference,
            "product": quote.service_code,
            "receiver": {"fullName": order.customer_name, "mobile": order.customer_phone},
            "clientReference": order.id,
        }
        return HttpCall("POST", "/mock/quickexpress/booking/create", json=body)

    def normalize_rate_response(self, response: dict) -> list[NormalizedRate]:
        if response.get("status") != "AVAILABLE":
            return []
        ch = response["charges"]
        est = response["deliveryEstimate"]
        return [
            NormalizedRate(
                carrier_code=self.code,
                service_code=response["product"],
                service_name=f"QuickExpress {response['product'].title()}",
                base_charge=money(ch["shipping"]),
                cod_charge=money(ch.get("cod", 0)),
                additional_charges=money(ch.get("fuelSurcharge", 0)),
                tax=money(ch["gst"]),
                total_charge=money(response["payable"]),
                estimated_min_days=est["minimumDays"],
                estimated_max_days=est["maximumDays"],
                quote_reference=response["quoteId"],
                raw=response,
            )
        ]

    def normalize_shipment_response(self, response: dict) -> NormalizedShipment:
        if response.get("bookingStatus") != "CONFIRMED":
            raise CarrierError("QuickExpress did not confirm the booking")
        b = response["booking"]
        return NormalizedShipment(self.code, b["bookingId"], b["awb"], STATUS_MAP[b["currentState"]], response)

    def normalize_webhook(self, payload: dict) -> NormalizedEvent:
        return NormalizedEvent(
            carrier_code=self.code,
            tracking_number=payload["awb"],
            status=STATUS_MAP[payload["state"]],
            carrier_status=payload["state"],
            event_id=payload.get("eventId"),
            description=payload.get("note"),
            location=(payload.get("hub") or {}).get("city"),
            event_time=datetime.fromtimestamp(payload["occurredAt"] / 1000, tz=timezone.utc),  # epoch millis
            raw=payload,
        )
