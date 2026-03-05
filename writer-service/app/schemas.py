from uuid import UUID

from pydantic import BaseModel, Field

class OrderItem(BaseModel):

    sku: str = Field(..., min_length=1, description="Referencia del producto")
    qty: int = Field(..., gt=0, description="Cantidad (> 0)")


class InternalOrder(BaseModel):
    
    order_id: UUID = Field(
        ...,
        description="UUID v4 generado por el api-gateway (36 caracteres con guiones)",
    )
    customer: str = Field(..., min_length=1)
    items: list[OrderItem] = Field(..., min_length=1)


