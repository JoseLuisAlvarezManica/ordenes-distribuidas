from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class OrderItem(BaseModel):

    sku: str = Field(..., min_length=1, description="Referencia del producto")
    qty: int = Field(..., gt=0, description="Cantidad (> 0)")


class CreateOrderRequest(BaseModel):

    customer: str = Field(..., min_length=1, description="Nombre del cliente")
    items: list[OrderItem] = Field(..., min_length=1, description="Lista de ítems")


class CreateOrderResponse(BaseModel):

    order_id: str = Field(..., description="UUID v4 de la nueva orden")
    status: str = Field(..., description="Estado inicial: RECEIVED")

class OrderStatusResponse(BaseModel):

    order_id: str
    status: str
    last_update: str | None = None


class InternalOrderRequest(BaseModel):

    order_id: str = Field(..., description="UUID v4 como string")
    customer: str
    items: list[OrderItem]
