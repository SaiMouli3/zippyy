from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent, http

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
        r = http.get(f"{self.base}/rates", params={
            "pickup": order["pickup_pincode"], "drop": order["delivery_pincode"], "wt": order["weight_kg"]})
        r.raise_for_status()
        return self.normalize_rates(r.json())

    def create_shipment(self, order, service):
        r = http.post(f"{self.base}/consignments", json={
            "customerRef": order["id"], "serviceCode": service,
            "to": {"name": order["customer_name"], "phone": order["phone"], "pincode": order["delivery_pincode"]},
            "collectOnDelivery": order["cod_amount"], "weight": order["weight_kg"]})
        r.raise_for_status()
        d = r.json()
        return ShipmentResult(d["consignmentNo"], d["trackingRef"])

    def parse_webhook(self, p):
        return WebhookEvent(p["reference"], STATUS[p["state"]], str(p["seq"]), REASON.get(p.get("undeliveredCode")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        r = http.post(f"{self.base}/consignments/{tracking_number}/redeliver", json={
            "when": {"date": requested_date, "window": window}, "attemptNo": attempt})
        r.raise_for_status()
        d = r.json()
        return ReattemptResult("ACCEPTED" if d["accepted"] else "REJECTED", d["msg"], d)
