import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=150)
    email: EmailStr
    phone_number: str = Field(..., min_length=8, max_length=16)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class MessageResponse(BaseModel):
    detail: str


class MeResponse(BaseModel):
    username: str
    email: EmailStr
    phone_number: str | None = None
    role: str


SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")


# Items que el cliente quiere comprar, con su referencia (sku) y cantidad (qty)
class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(
        ...,
        min_length=1,
        max_length=40,
        description="Referencia del producto",
    )
    qty: int = Field(..., gt=0, le=10000, description="Cantidad (> 0)")

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        if not SKU_PATTERN.fullmatch(value):
            raise ValueError("sku contiene caracteres no permitidos")
        return value


# Request que recibe el API Gateway para crear una orden, con el nombre del cliente y la lista de ítems
class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    _control_chars: ClassVar[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")

    items: list[OrderItem] = Field(
        ..., min_length=1, max_length=100, description="Lista de ítems"
    )


# Response al usuario, con el id de la orden y su estado inicial
class CreateOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(..., description="UUID v4 de la nueva orden")
    status: str = Field(..., description="Estado inicial: RECEIVED")


# Response del GET /orders/{id}: order_id viene del path parameter, status y last_update del hash de Redis
class OrderStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    status: str
    last_update: str | None = None


class TopProduct(BaseModel):
    sku: str
    total_qty: int


class MostFrequentCustomer(BaseModel):
    customer: str
    orders: int


class ErrorRates(BaseModel):
    publish_error_percentage: float
    system_error_percentage: float
    error_events: int


class AvgTimesMs(BaseModel):
    persist_order_postgres: float | None = None
    publish_event_rabbitmq: float | None = None
    notification: float | None = None


class AnalyticsResponse(BaseModel):
    total_orders_seen: int
    top_products: list[TopProduct]
    most_frequent_customer: MostFrequentCustomer | None = None
    error_rates: ErrorRates
    avg_times_ms: AvgTimesMs
