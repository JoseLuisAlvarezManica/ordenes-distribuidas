from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field

# Items que el cliente quiere comprar, con su referencia (sku) y cantidad (qty)
class OrderItem(BaseModel):

    sku: str = Field(..., min_length=1, description="Referencia del producto")
    qty: int = Field(..., gt=0, description="Cantidad (> 0)")

# Request que recibe el API Gateway para crear una orden, con el nombre del cliente y la lista de ítems
class CreateOrderRequest(BaseModel):

    customer: str = Field(..., min_length=1, description="Nombre del cliente")
    items: list[OrderItem] = Field(..., min_length=1, description="Lista de ítems")

# Response al usuario, con el id de la orden y su estado inicial
class CreateOrderResponse(BaseModel):

    order_id: str = Field(..., description="UUID v4 de la nueva orden")
    status: str = Field(..., description="Estado inicial: RECEIVED")

# Response del GET /orders/{id}: order_id viene del path parameter, status y last_update del hash de Redis
class OrderStatusResponse(BaseModel):

    order_id: str
    status: str
    last_update: str | None = None
