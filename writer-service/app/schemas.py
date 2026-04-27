from uuid import UUID
import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")


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


class InternalOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    _control_chars: ClassVar[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")

    order_id: UUID = Field(
        ...,
        description="UUID v4 generado por el api-gateway (36 caracteres con guiones)",
    )
    customer: str = Field(..., min_length=1, max_length=100)
    phone_number: str = Field(..., min_length=8, max_length=16)
    items: list[OrderItem] = Field(..., min_length=1, max_length=100)

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
    def validate_phone_number(cls, value: str) -> str:
        normalized = value.strip().replace(" ", "").replace("-", "")
        if not PHONE_PATTERN.fullmatch(normalized):
            raise ValueError("phone_number debe tener formato internacional valido")
        if not normalized.startswith("+"):
            normalized = f"+{normalized}"
        return normalized
