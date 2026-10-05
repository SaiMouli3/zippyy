from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent

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
        d = self.call("RATE_REQUEST", "POST", "/rates", order["id"], json={
            "from_pin": order["pickup_pincode"], "to_pin": order["delivery_pincode"],
            "weight_grams": order["weight_grams"],
            "dimensions_cm": {"l": order["length_cm"], "w": order["width_cm"], "h": order["height_cm"]},
            "payment_mode": order["payment_mode"], "cod_value": order["cod_amount"]})
        return self.normalize_rates(d)

    def create_shipment(self, order, service):
        d = self.call("CREATE_SHIPMENT", "POST", "/bookings", order["id"], json={
            "reference": order["id"], "product": service,
            "receiver": {"full_name": order["customer_name"], "mobile": order["phone"],
                         "pin": order["delivery_pincode"]},
            "cod_value": order["cod_amount"], "weight_grams": order["weight_grams"]})
        b = d["booking"]
        return ShipmentResult(b["id"], b["tracking"])

    def parse_webhook(self, p):
        ev = p["event"]
        return WebhookEvent(p["awb"], STATUS[ev["code"]], str(p["id"]), REASON.get(ev.get("reason")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        d = self.call("NDR_REATTEMPT", "POST", f"/ndr/{tracking_number}/reattempt", json={
            "preferred_date": requested_date, "preferred_window": window, "attempt": attempt})
        return ReattemptResult("ACCEPTED" if d["result"] == "OK" else "REJECTED", d["note"], d)
