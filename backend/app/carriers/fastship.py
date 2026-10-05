from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent, http

SERVICE_NAMES = {"FAST-AIR": "Fast Air"}
STATUS = {"PKD": "PICKED_UP", "INT": "IN_TRANSIT", "OFD": "OUT_FOR_DELIVERY", "DLV": "DELIVERED", "NDR": "NDR"}
REASON = {"CUST_NA": "CUSTOMER_UNAVAILABLE", "CUST_REF": "CUSTOMER_REFUSED", "ADDR_BAD": "ADDRESS_ISSUE",
          "PHONE_NR": "PHONE_UNREACHABLE", "COD_NR": "COD_NOT_READY"}


class FastShipAdapter(CarrierAdapter):
    code, slug, name = "FASTSHIP", "fastship", "FastShip"

    @staticmethod
    def normalize_rates(raw: dict) -> list[NormalizedRate]:
        return [NormalizedRate(carrier="FASTSHIP", carrierName="FastShip", service=raw["service"],
                               serviceName=SERVICE_NAMES.get(raw["service"], raw["service"]),
                               price=round(raw["price"], 2),
                               etaMinDays=raw["etaDays"], etaMaxDays=raw["etaDays"])]

    def get_rates(self, order):
        r = http.post(f"{self.base}/rates", json={
            "origin": order["pickup_pincode"], "destination": order["delivery_pincode"],
            "weightKg": order["weight_kg"], "cod": order["payment_mode"] == "COD"})
        r.raise_for_status()
        return self.normalize_rates(r.json())

    def create_shipment(self, order, service):
        r = http.post(f"{self.base}/shipments", json={
            "orderRef": order["id"], "service": service,
            "consignee": {"name": order["customer_name"], "phone": order["phone"],
                          "pincode": order["delivery_pincode"]},
            "codAmount": order["cod_amount"], "weightKg": order["weight_kg"]})
        r.raise_for_status()
        d = r.json()
        return ShipmentResult(d["shipmentId"], d["awb"])

    def parse_webhook(self, p):
        return WebhookEvent(p["trackingNumber"], STATUS[p["status"]], str(p["eventId"]),
                            REASON.get(p.get("reasonCode")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        r = http.post(f"{self.base}/ndr-action", json={
            "awb": tracking_number, "action": "REATTEMPT", "date": requested_date,
            "slot": window, "attempt": attempt})
        r.raise_for_status()
        d = r.json()
        return ReattemptResult(d["status"], d["message"], d)
