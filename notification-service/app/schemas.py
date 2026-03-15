import re

from pydantic import BaseModel, field_validator


PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")


class OrderItem(BaseModel):
    sku: str
    qty: int


class OrderCreatedEvent(BaseModel):
    phone_number: str
    order_id: str
    items: list[OrderItem]

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        normalized = value.strip().replace(" ", "").replace("-", "")
        if not PHONE_PATTERN.fullmatch(normalized):
            raise ValueError("phone_number debe tener formato internacional valido")
        if not normalized.startswith("+"):
            normalized = f"+{normalized}"
        return normalized
