from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent

SERVICE_NAMES = {"RC-SURFACE": "Surface"}
STATUS = {"Picked Up": "PICKED_UP", "In Transit": "IN_TRANSIT", "Out For Delivery": "OUT_FOR_DELIVERY",
          "Delivered": "DELIVERED", "Undelivered": "NDR"}
REASON = {"U01": "CUSTOMER_UNAVAILABLE", "U02": "CUSTOMER_REFUSED", "U03": "ADDRESS_ISSUE",
          "U04": "PHONE_UNREACHABLE", "U05": "COD_NOT_READY"}


class ReliableCourierAdapter(CarrierAdapter):
    code, slug, name = "RELIABLECOURIER", "reliable", "ReliableCourier"

    @staticmethod
    def normalize_rates(raw: dict) -> list[NormalizedRate]:
        return [NormalizedRate(carrier="RELIABLECOURIER", carrierName="ReliableCourier", service=o["code"],
                               serviceName=SERVICE_NAMES.get(o["code"], o["code"]),
                               price=round(o["amount"], 2),
                               etaMinDays=max(1, o["days"] - 1), etaMaxDays=o["days"])
                for o in raw["options"]]

    def get_rates(self, order):
        d = self.call("RATE_REQUEST", "GET", "/rates", order["id"], params={
            "pickup": order["pickup_pincode"], "drop": order["delivery_pincode"],
            "wt": order["weight_grams"] / 1000, "l": order["length_cm"], "b": order["width_cm"],
            "h": order["height_cm"]})
        return self.normalize_rates(d)

    def create_shipment(self, order, service):
        d = self.call("CREATE_SHIPMENT", "POST", "/consignments", order["id"], json={
            "customerRef": order["id"], "serviceCode": service,
            "to": {"name": order["customer_name"], "phone": order["phone"], "pincode": order["delivery_pincode"]},
            "collectOnDelivery": order["cod_amount"], "weight": order["weight_grams"] / 1000})
        return ShipmentResult(d["consignmentNo"], d["trackingRef"])

    def parse_webhook(self, p):
        return WebhookEvent(p["reference"], STATUS[p["state"]], str(p["seq"]), REASON.get(p.get("undeliveredCode")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        d = self.call("NDR_REATTEMPT", "POST", f"/consignments/{tracking_number}/redeliver", json={
            "when": {"date": requested_date, "window": window}, "attemptNo": attempt})
        return ReattemptResult("ACCEPTED" if d["accepted"] else "REJECTED", d["msg"], d)
