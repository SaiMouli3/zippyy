"""Request/response models. These drive the generated OpenAPI docs (/docs, /openapi.json)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _camel(s: str) -> str:
    h, *r = s.split("_")
    return h + "".join(x.capitalize() for x in r)


class CamelIn(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


# ------------------------------------------------------------------ requests
class OrderIn(CamelIn):
    merchant_id: str | None = Field(None, description="Defaults to the demo merchant. Part of the idempotency key and the rate cache key.")
    merchant_order_id: str | None = Field(None, max_length=64,
        description="Merchant's own order reference. Repeating (merchantId, merchantOrderId) never creates a second order.")
    customer_name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\d{10}$")
    address: str = ""
    pickup_pincode: str = Field(pattern=r"^\d{6}$")
    delivery_pincode: str = Field(pattern=r"^\d{6}$")
    weight_grams: int = Field(gt=0, le=100_000)
    length_cm: int = Field(gt=0, le=300)
    width_cm: int = Field(gt=0, le=300)
    height_cm: int = Field(gt=0, le=300)
    payment_mode: str = Field(pattern=r"^(COD|PREPAID)$", description="COD or PREPAID")
    cod_amount: float = Field(default=0, ge=0, description="Required (> 0) when paymentMode is COD")

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, json_schema_extra={"examples": [{
        "merchantId": "MRC-100", "merchantOrderId": "SHOP-5001", "customerName": "Rahul Sharma",
        "phone": "9876543210", "address": "12 MG Road, Connaught Place, New Delhi",
        "pickupPincode": "560001", "deliveryPincode": "110001", "weightGrams": 1500,
        "lengthCm": 20, "widthCm": 15, "heightCm": 10, "paymentMode": "COD", "codAmount": 2500}]})


class SelectIn(CamelIn):
    carrier: str = Field(description="FASTSHIP | QUICKEXPRESS | RELIABLECOURIER")
    service: str
    price: float | None = Field(None, description="Optional echo of the quoted price. If supplied and different from the stored quote the call is rejected (409): the quoted amount cannot be modified.")

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True,
                              json_schema_extra={"examples": [{"carrier": "FASTSHIP", "service": "FAST-AIR"}]})


class MessageIn(CamelIn):
    message: str = Field(min_length=1)
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True,
                              json_schema_extra={"examples": [{"message": "Yes tomorrow evening after 6"}]})


# ----------------------------------------------------------------- responses
class ErrorOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    error: str


class OrderOut(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "id": "ZPY-ORD-10002", "merchantId": "MRC-100", "merchantOrderId": "SHOP-5001",
        "customerName": "Rahul Sharma", "phone": "9876543210", "address": "12 MG Road, New Delhi",
        "pickupPincode": "560001", "deliveryPincode": "110001", "weightGrams": 1500, "lengthCm": 20,
        "widthCm": 15, "heightCm": 10, "paymentMode": "COD", "codAmount": 2500.0, "status": "CREATED",
        "selectedCarrier": None, "selectedService": None, "quotedPrice": None,
        "createdAt": "2026-10-05T17:18:01Z", "duplicate": False}]})
    id: str
    merchantId: str
    merchantOrderId: str | None = None
    customerName: str
    phone: str
    address: str = ""
    pickupPincode: str
    deliveryPincode: str
    weightGrams: int
    lengthCm: int
    widthCm: int
    heightCm: int
    paymentMode: str
    codAmount: float
    status: str
    selectedCarrier: str | None = None
    selectedService: str | None = None
    quotedPrice: float | None = None
    createdAt: datetime
    duplicate: bool | None = Field(None, description="true when this call replayed an existing (merchantId, merchantOrderId)")


class RateOut(BaseModel):
    carrier: str
    carrierName: str
    service: str
    serviceName: str
    price: float
    etaMinDays: int
    etaMaxDays: int


class CarrierFailure(BaseModel):
    carrier: str
    code: str = Field(description="TIMEOUT | HTTP_ERROR | UNREACHABLE | BAD_RESPONSE")
    message: str
    durationMs: float


class RatesOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "rates": [{"carrier": "FASTSHIP", "carrierName": "FastShip", "service": "FAST-AIR", "serviceName": "Fast Air",
                   "price": 182.9, "etaMinDays": 2, "etaMaxDays": 2},
                  {"carrier": "RELIABLECOURIER", "carrierName": "ReliableCourier", "service": "RC-SURFACE",
                   "serviceName": "Surface", "price": 159.3, "etaMinDays": 4, "etaMaxDays": 5}],
        "errors": [{"carrier": "QUICKEXPRESS", "code": "TIMEOUT",
                    "message": "QuickExpress did not respond within 3000 ms", "durationMs": 3012.4}],
        "partial": True, "cached": False, "cacheStatus": "MISS",
        "cacheKey": "zippy:rates:MRC-100:560001:110001:1500:20:15:10:COD:2500"}]})
    rates: list[RateOut]
    errors: list[CarrierFailure]
    partial: bool = Field(description="true when at least one carrier failed")
    cached: bool
    cacheStatus: str = Field(description="HIT | MISS | REFRESH | UNAVAILABLE (Redis down; carriers were called directly)")
    cacheKey: str


class ShipmentOut(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "id": 2, "orderId": "ZPY-ORD-10002", "carrier": "FASTSHIP", "service": "FAST-AIR",
        "carrierShipmentId": "FS-857907", "trackingNumber": "FST725470278", "status": "SHIPMENT_CREATED",
        "createdAt": "2026-10-05T17:18:01Z", "updatedAt": "2026-10-05T17:18:01Z"}]})
    id: int
    orderId: str
    carrier: str
    service: str
    carrierShipmentId: str
    trackingNumber: str
    status: str
    createdAt: datetime
    updatedAt: datetime


class TrackingEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str
    reason: str | None = None
    eventId: str
    occurredAt: datetime


class TrackingOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "orderId": "ZPY-ORD-10002", "carrier": "FASTSHIP", "service": "FAST-AIR", "trackingNumber": "FST725470278",
        "carrierShipmentId": "FS-857907", "shipmentId": 2, "currentStatus": "PICKED_UP",
        "statusHistory": [{"status": "SHIPMENT_CREATED", "reason": None, "eventId": "created", "occurredAt": "2026-10-05T17:18:01Z"},
                          {"status": "PICKED_UP", "reason": None, "eventId": "8ed739ed81fc", "occurredAt": "2026-10-05T17:19:00Z"}]}]})
    orderId: str
    carrier: str
    service: str
    trackingNumber: str
    carrierShipmentId: str
    shipmentId: int
    currentStatus: str
    statusHistory: list[TrackingEvent]


class WebhookOut(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [
        {"status": "processed", "duplicate": False, "shipmentStatus": "OUT_FOR_DELIVERY", "ndrCaseId": None},
        {"status": "duplicate", "duplicate": True, "message": "Event already processed"},
        {"status": "quarantined", "reason": "UNKNOWN_TRACKING_NUMBER",
         "message": "No shipment with tracking number FST000; event stored for investigation"},
        {"status": "quarantined", "reason": "INVALID_TRANSITION", "currentStatus": "DELIVERED", "from": "DELIVERED",
         "to": "IN_TRANSIT", "allowedFromCurrent": [], "message": "DELIVERED -> IN_TRANSIT is not a valid transition; shipment unchanged"}]})
    status: str = Field(description="processed | duplicate | quarantined | rejected")
    duplicate: bool | None = None
    reason: str | None = None
    message: str | None = None
    shipmentStatus: str | None = None
    ndrCaseId: str | None = None


class QuarantineOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    carrier: str
    trackingNumber: str | None = None
    reason: str
    detail: dict | None = None
    raw: Any = None
    normalized: dict | None = None
    requestId: str | None = None
    receivedAt: datetime


class NdrSummaryOut(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "id": "NDR-1001", "orderId": "ZPY-ORD-10002", "reason": "CUSTOMER_UNAVAILABLE", "attemptNumber": 1,
        "status": "OPEN", "createdAt": "2026-10-05T17:20:00Z", "customerName": "Rahul Sharma",
        "carrier": "FASTSHIP", "trackingNumber": "FST725470278"}]})
    id: str
    orderId: str
    reason: str
    attemptNumber: int
    status: str
    customerName: str
    carrier: str
    trackingNumber: str
    createdAt: datetime


class NdrDetailOut(BaseModel):
    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "id": "NDR-1001", "orderId": "ZPY-ORD-10002", "reason": "CUSTOMER_UNAVAILABLE", "attemptNumber": 1,
        "status": "RESOLVED", "customerName": "Rahul Sharma", "carrier": "FASTSHIP",
        "lastIntent": {"intent": "RESCHEDULE_DELIVERY", "date": "tomorrow", "time": "evening",
                       "timeWindow": "After 6 PM", "confidence": 0.95},
        "lastDecision": {"outcome": "ALLOWED", "reasons": ["Same address and phone", "Reschedule within 2 days"],
                         "action": "REATTEMPT", "requestedDate": "2026-10-06", "requestedWindow": "After 6 PM"},
        "messages": [{"id": 1, "sender": "AGENT", "message": "Hi Rahul, your parcel could not be delivered today ...",
                      "timestamp": "2026-10-05T17:21:00Z"}],
        "actions": [{"id": 1, "actionType": "REATTEMPT", "status": "CARRIER_ACCEPTED"}],
        "audit": [{"event": "NDR_CREATED", "details": {}, "createdAt": "2026-10-05T17:20:00Z"}]}]})
    id: str
    orderId: str
    reason: str
    attemptNumber: int
    status: str
    customerName: str
    carrier: str
    trackingNumber: str
    lastIntent: dict | None = None
    lastDecision: dict | None = None
    messages: list[dict]
    actions: list[dict]
    audit: list[dict]
