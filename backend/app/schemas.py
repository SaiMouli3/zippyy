"""API request/response models. JSON is camelCase; snake_case input is accepted too."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class Api(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class OrderCreate(Api):
    merchant_id: str | None = None
    merchant_order_id: str | None = None
    customer_name: str = Field(min_length=1, max_length=200)
    customer_phone: str
    pickup_pincode: str
    delivery_pincode: str
    weight_grams: int = Field(gt=0, le=50_000)
    length_cm: int = Field(default=20, gt=0, le=200)
    width_cm: int = Field(default=15, gt=0, le=200)
    height_cm: int = Field(default=10, gt=0, le=200)
    payment_type: Literal["PREPAID", "COD"]
    cod_amount: float = Field(default=0, ge=0)

    @field_validator("pickup_pincode", "delivery_pincode")
    @classmethod
    def _pincode(cls, v: str) -> str:
        if not re.fullmatch(r"[1-9]\d{5}", v):
            raise ValueError("must be a 6-digit pincode")
        return v

    @field_validator("customer_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        if not re.fullmatch(r"\+?\d{10,15}", v):
            raise ValueError("must be 10-15 digits, optional leading +")
        return v

    @model_validator(mode="after")
    def _cod(self):
        if self.payment_type == "COD" and self.cod_amount <= 0:
            raise ValueError("cod_amount must be > 0 for COD orders")
        if self.payment_type == "PREPAID":
            self.cod_amount = 0
        return self


class OrderOut(Api):
    id: str
    merchant_id: str
    merchant_order_id: str
    customer_name: str
    customer_phone: str
    pickup_pincode: str
    delivery_pincode: str
    weight_grams: int
    length_cm: int
    width_cm: int
    height_cm: int
    payment_type: str
    cod_amount: float
    status: str
    created_at: datetime
    updated_at: datetime


class ShippingOptionOut(Api):
    quote_id: str
    carrier_code: str
    carrier_name: str
    service_code: str
    service_name: str
    base_charge: float
    cod_charge: float
    additional_charges: float
    tax: float
    total_charge: float
    estimated_min_days: int | None
    estimated_max_days: int | None
    quote_reference: str | None
    expires_at: datetime


class FailedCarrierOut(Api):
    carrier_code: str
    carrier_name: str
    reason: str


class RatesOut(Api):
    order_id: str
    shipping_options: list[ShippingOptionOut]
    failed_carriers: list[FailedCarrierOut]
    cached: bool = False


class SelectCarrierIn(Api):
    carrier_code: str
    service_code: str
    quoted_amount: float


class SelectionOut(Api):
    order_id: str
    shipment_id: str
    carrier: str
    service_code: str
    quoted_amount: float
    status: str


class ShipmentOut(Api):
    shipment_id: str
    carrier: str
    tracking_number: str
    status: str


class TrackingEventOut(Api):
    status: str
    timestamp: datetime
    location: str | None = None
    description: str | None = None


class TrackingOut(Api):
    tracking_number: str
    carrier: str
    current_status: str
    history: list[TrackingEventOut]


class AgentMessageIn(Api):
    conversation_id: str
    message: str
    customer_name: str | None = None
    customer_phone: str | None = None


class AgentMessageOut(Api):
    reply: str
    tool_calls: list[dict]


class MockCallIn(Api):
    utterances: list[str]
    caller_phone: str | None = None
