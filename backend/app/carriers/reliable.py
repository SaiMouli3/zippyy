import re
from datetime import datetime, timezone

from app.carriers.base import CarrierAdapter, CarrierError, HttpCall, money
from app.domain.carrier_types import NdrActionResult, NormalizedEvent, NormalizedRate, NormalizedShipment
from app.domain.enums import ShipmentStatus as S

STATUS_MAP = {
    100: S.SHIPMENT_CREATED,
    200: S.PICKED_UP,
    300: S.IN_TRANSIT,
    400: S.OUT_FOR_DELIVERY,
    450: S.DELIVERY_FAILED,
    500: S.DELIVERED,
    600: S.RTO,
    700: S.RTO_DELIVERED,
}


def parse_eta(eta: str) -> tuple[int | None, int | None]:
    """'4-5 business days' -> (4, 5); '2 business days' -> (2, 2)."""
    nums = [int(n) for n in re.findall(r"\d+", eta or "")]
    if not nums:
        return None, None
    return nums[0], nums[-1]


class ReliableCourierAdapter(CarrierAdapter):
    code = "RELIABLE"
    name = "ReliableCourier"
    webhook_slug = "reliable"

    def build_rate_request(self, order) -> HttpCall:
        return HttpCall(
            "GET",
            "/mock/reliablecourier/shipping-options",
            params={
                "from": order.pickup_pincode,
                "to": order.delivery_pincode,
                "weight": order.weight_grams / 1000,
                "cod": str(order.payment_type == "COD").lower(),
                "amount": float(order.cod_amount),
            },
        )

    def build_shipment_request(self, order, quote) -> HttpCall:
        body = {
            "from": order.pickup_pincode,
            "to": order.delivery_pincode,
            "weight": order.weight_grams / 1000,
            "cod": order.payment_type == "COD",
            "amount": float(order.cod_amount),
            "serviceId": quote.service_code,
            "customer": {"name": order.customer_name, "phone": order.customer_phone},
            "ref": order.id,
        }
        return HttpCall("PUT", "/mock/reliablecourier/orders", json=body)

    def normalize_rate_response(self, response: dict) -> list[NormalizedRate]:
        if response.get("code") != 200:
            return []
        rates = []
        for opt in response.get("data", []):
            r = opt["rate"]
            lo, hi = parse_eta(opt.get("eta", ""))
            rates.append(
                NormalizedRate(
                    carrier_code=self.code,
                    service_code=opt["id"],
                    service_name=opt["name"],
                    base_charge=money(r["base"]),
                    cod_charge=money(r.get("cashCollectionFee", 0)),
                    additional_charges=money(r.get("handling", 0)),
                    tax=money(r["taxAmount"]),
                    total_charge=money(r["grandTotal"]),
                    estimated_min_days=lo,
                    estimated_max_days=hi,
                    quote_reference=None,
                    raw=opt,
                )
            )
        return rates

    def normalize_shipment_response(self, response: dict) -> NormalizedShipment:
        if response.get("result") != "ACCEPTED":
            raise CarrierError("ReliableCourier did not accept the order")
        d = response["deliveryOrder"]
        return NormalizedShipment(self.code, d["id"], d["trackingCode"], S.SHIPMENT_CREATED, response)

    def normalize_webhook(self, payload: dict) -> NormalizedEvent:
        n = payload["notification"]
        return NormalizedEvent(
            carrier_code=self.code,
            tracking_number=n["trackingCode"],
            status=STATUS_MAP[n["code"]],
            carrier_status=str(n["code"]),
            event_id=n.get("id"),
            description=n.get("message"),
            location=n.get("place"),
            event_time=datetime.strptime(n["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            raw=payload,
            reason=n.get("reasonCode"),
        )

    _ACTIONS = {"reattempt": "reattempt", "reschedule": "reschedule", "rto": "rto", "phone_change": "phone"}

    def build_ndr_action_request(self, action, awb, requested_date, window, idempotency_key) -> HttpCall:
        if action not in self._ACTIONS:
            raise CarrierError(f"ReliableCourier does not support {action}")
        return HttpCall("PUT", "/mock/reliablecourier/ndr", json={
            "trackingCode": awb, "op": self._ACTIONS[action], "date": requested_date, "window": window,
            "requestKey": idempotency_key,
        })

    def normalize_ndr_action_response(self, status_code, response) -> NdrActionResult:
        if response.get("code") == 200 and response.get("state") == "accepted":
            return NdrActionResult("accepted", response.get("ref"), raw=response)
        if response.get("code") == 202:
            return NdrActionResult("pending", response.get("ref"), raw=response)
        return NdrActionResult("rejected", response.get("ref"), response.get("message") or "rejected", response)

    def build_ndr_status_request(self, idempotency_key, reference) -> HttpCall:
        return HttpCall("GET", f"/mock/reliablecourier/ndr/{idempotency_key}")
