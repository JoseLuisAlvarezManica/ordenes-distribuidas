from uuid import UUID
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

    customer: str = Field(..., min_length=1, max_length=100, description="Nombre del cliente")
    phone_number: str | None = Field(
        default=None,
        min_length=8,
        max_length=16,
        description="Telefono del cliente en formato internacional",
    )
    items: list[OrderItem] = Field(..., min_length=1, max_length=100, description="Lista de ítems")

    @field_validator("customer")
    @classmethod
    def validate_customer(cls, value: str) -> str:
        if cls._control_chars.search(value):
            raise ValueError("customer contiene caracteres de control")
        if "<" in value or ">" in value:
            raise ValueError("customer contiene caracteres no permitidos")
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().replace(" ", "").replace("-", "")
        if not PHONE_PATTERN.fullmatch(normalized):
            raise ValueError("phone_number debe tener formato internacional valido")
        if not normalized.startswith("+"):
            normalized = f"+{normalized}"
        return normalized

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
