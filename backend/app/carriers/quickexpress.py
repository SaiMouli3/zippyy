from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent, http

SERVICE_NAMES = {"EXPRESS": "Express"}
STATUS = {"PICKUP_DONE": "PICKED_UP", "IN_TRANSIT": "IN_TRANSIT", "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
          "DELIVERED": "DELIVERED", "DELIVERY_FAILED": "NDR"}
REASON = {"RECIPIENT_NOT_AVAILABLE": "CUSTOMER_UNAVAILABLE", "RECIPIENT_REFUSED": "CUSTOMER_REFUSED",
          "BAD_ADDRESS": "ADDRESS_ISSUE", "PHONE_NOT_REACHABLE": "PHONE_UNREACHABLE",
          "CASH_NOT_READY": "COD_NOT_READY"}


class QuickExpressAdapter(CarrierAdapter):
    code, slug, name = "QUICKEXPRESS", "quickexpress", "QuickExpress"

    @staticmethod
    def normalize_rates(raw: dict) -> list[NormalizedRate]:
        est = raw["deliveryEstimate"]
        # QuickExpress quotes a single "deliver by" day count; treat it as a 1-day window.
        return [NormalizedRate(carrier="QUICKEXPRESS", carrierName="QuickExpress", service=raw["product"],
                               serviceName=SERVICE_NAMES.get(raw["product"], raw["product"]),
                               price=round(raw["payable"], 2),
                               etaMinDays=max(1, est - 1), etaMaxDays=est)]

    def get_rates(self, order):
        r = http.post(f"{self.base}/rates", json={
            "from_pin": order["pickup_pincode"], "to_pin": order["delivery_pincode"],
            "weight_grams": int(round(order["weight_kg"] * 1000)),
            "payment_mode": order["payment_mode"]})
        r.raise_for_status()
        return self.normalize_rates(r.json())

    def create_shipment(self, order, service):
        r = http.post(f"{self.base}/bookings", json={
            "reference": order["id"], "product": service,
            "receiver": {"full_name": order["customer_name"], "mobile": order["phone"],
                         "pin": order["delivery_pincode"]},
            "cod_value": order["cod_amount"], "weight_grams": int(round(order["weight_kg"] * 1000))})
        r.raise_for_status()
        b = r.json()["booking"]
        return ShipmentResult(b["id"], b["tracking"])

    def parse_webhook(self, p):
        ev = p["event"]
        return WebhookEvent(p["awb"], STATUS[ev["code"]], str(p["id"]), REASON.get(ev.get("reason")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        r = http.post(f"{self.base}/ndr/{tracking_number}/reattempt", json={
            "preferred_date": requested_date, "preferred_window": window, "attempt": attempt})
        r.raise_for_status()
        d = r.json()
        return ReattemptResult("ACCEPTED" if d["result"] == "OK" else "REJECTED", d["note"], d)
