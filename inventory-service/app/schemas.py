from pydantic import BaseModel


class OrderItem(BaseModel):
    sku: str
    qty: int


class OrderCreatedEvent(BaseModel):
    order_id: str
    items: list[OrderItem]
