from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..decorators import must_be_logged_in, bearer_scheme, must_be_admin
from ..config import settings
from ..redis_client import get_redis
from ..schemas import CreateOrderRequest, CreateOrderResponse, OrderStatusResponse
from ..services.writer_client import WriterClient, get_writer_client

router = APIRouter(prefix="/orders", tags=["orders"])

writer_dependency = Annotated[WriterClient, Depends(get_writer_client)]
redis_dependency = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(bearer_scheme)])
@must_be_logged_in
async def create_order(
    request: Request,
    order_data: CreateOrderRequest,
    writer_client: writer_dependency,
    redis: redis_dependency,
) -> CreateOrderResponse:
    phone_number = request.state.phone_number or settings.support_number
    if not phone_number:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No phone_number in payload and SUPPORT_NUMBER is not configured",
        )

    order_id = str(uuid4())
    request_id = str(uuid4())
    redis_key = f"order:{order_id}"
    now = datetime.now(timezone.utc).isoformat()

    await redis.execute_command("HSET", redis_key, "status", "RECEIVED", "last_update", now)

    try:
        
        order_payload = {
            "order_id": order_id,
            "customer": request.state.username,
            "phone_number": phone_number,
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


@router.get("/my_orders", status_code=status.HTTP_200_OK, dependencies=[Depends(bearer_scheme)])
@must_be_logged_in
async def get_my_orders(request: Request, writer_client: writer_dependency):
    data = await writer_client.get("/internal/orders/my_orders", headers={"X-Customer": request.state.username})
    return data


@router.get("/", status_code=status.HTTP_200_OK, dependencies=[Depends(bearer_scheme)])
@must_be_admin
async def list_orders(request: Request, writer_client: writer_dependency):
    data = await writer_client.get("/internal/orders")
    return data
