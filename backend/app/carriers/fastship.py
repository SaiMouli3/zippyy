from .base import CarrierAdapter, NormalizedRate, ReattemptResult, ShipmentResult, WebhookEvent

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
        d = self.call("RATE_REQUEST", "POST", "/rates", order["id"], json={
            "origin": order["pickup_pincode"], "destination": order["delivery_pincode"],
            "weightGrams": order["weight_grams"],
            "dimensions": {"lengthCm": order["length_cm"], "widthCm": order["width_cm"], "heightCm": order["height_cm"]},
            "cod": order["payment_mode"] == "COD", "codAmount": order["cod_amount"]})
        return self.normalize_rates(d)

    def create_shipment(self, order, service):
        d = self.call("CREATE_SHIPMENT", "POST", "/shipments", order["id"], json={
            "orderRef": order["id"], "service": service,
            "consignee": {"name": order["customer_name"], "phone": order["phone"],
                          "pincode": order["delivery_pincode"]},
            "codAmount": order["cod_amount"], "weightGrams": order["weight_grams"]})
        return ShipmentResult(d["shipmentId"], d["awb"])

    def parse_webhook(self, p):
        return WebhookEvent(p["trackingNumber"], STATUS[p["status"]], str(p["eventId"]),
                            REASON.get(p.get("reasonCode")))

    def request_reattempt(self, tracking_number, requested_date, window, attempt):
        d = self.call("NDR_REATTEMPT", "POST", "/ndr-action", json={
            "awb": tracking_number, "action": "REATTEMPT", "date": requested_date,
            "slot": window, "attempt": attempt})
        return ReattemptResult(d["status"], d["message"], d)
