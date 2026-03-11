from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from ..redis_client import get_redis
from ..schemas import CreateOrderRequest, CreateOrderResponse, OrderStatusResponse
from ..services.writer_client import WriterClient, get_writer_client

router = APIRouter(prefix="/orders", tags=["orders"])

writer_dependency = Annotated[WriterClient, Depends(get_writer_client)]
redis_dependency = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_order(
    order_data: CreateOrderRequest,
    writer_client: writer_dependency,
    redis: redis_dependency,
) -> CreateOrderResponse:
    order_id = str(uuid4())
    request_id = str(uuid4())
    redis_key = f"order:{order_id}"
    now = datetime.now(timezone.utc).isoformat()

    await redis.execute_command("HSET", redis_key, "status", "RECEIVED", "last_update", now)

    try:
        
        order_payload = {
            "order_id": order_id,
            "customer": order_data.customer,
            "items": [{"sku": item.sku, "qty": item.qty} for item in order_data.items],
        }
        await writer_client.post("/internal/orders", order_payload, headers={"X-Request-Id": request_id})
    
    except Exception:
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "FAILED", "last_update", now)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Writer service or database unavailable", "order_id": order_id},
        )

    return CreateOrderResponse(order_id=order_id, status="RECEIVED")


@router.get("/{id}", status_code=status.HTTP_200_OK)
async def get_order(id: UUID, redis: redis_dependency) -> OrderStatusResponse:
    raw = await redis.execute_command("HGETALL", f"order:{id}")

    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, (list, tuple)):
        data = dict(zip(raw[::2], raw[1::2])) if raw else {}
    else:
        data = {}

    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderStatusResponse(order_id=str(id), **data)
