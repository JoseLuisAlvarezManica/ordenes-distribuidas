from pydantic import BaseModel


class OrderItem(BaseModel):
    sku: str
    qty: int


class OrderCreatedEvent(BaseModel):
    order_id: str
    customer: str
    phone_number: str
    items: list[OrderItem]
    persist_ms: float | None = None


class OrderErrorEvent(BaseModel):
    order_id: str | None = None
    stage: str
    error: str | None = None


class OrderProcessingEvent(BaseModel):
    order_id: str | None = None
    service: str
    status: str
    metric: str | None = None
    duration_ms: float | None = None
    error: str | None = None
