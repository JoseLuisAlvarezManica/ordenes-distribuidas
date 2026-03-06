from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, status, Depends, HTTPException
from fastapi.responses import JSONResponse

import redis.asyncio as aioredis
from .redis_client import close_redis, get_redis
from .schemas import CreateOrderRequest, CreateOrderResponse, OrderStatusResponse

from .services.writer_client import get_writer_client, WriterClient
from uuid import UUID, uuid4


writer_dependency = Annotated[WriterClient, Depends(get_writer_client)]
redis_dependency = Annotated[aioredis.Redis, Depends(get_redis)]

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="api-gateway", lifespan=lifespan)

@app.get("/health", tags=["ops"])
async def health(redis: redis_dependency) -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc: 
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content={"status": "ok" if all_ok else "degraded", "checks": checks}, status_code=http_status)

@app.post("/orders", status_code=status.HTTP_202_ACCEPTED, tags=["orders"])
async def create_order(order_data: CreateOrderRequest, writer_client: writer_dependency, redis: redis_dependency):
    order_id = str(uuid4())
    request_id = str(uuid4())
    redis_key = f"order:{order_id}"
    now = datetime.now(timezone.utc).isoformat()

    # HSET status = RECEIVED
    await redis.hset(redis_key, mapping={"status": "RECEIVED", "last_update": now})

    try:
        order_payload = {
            "order_id": order_id,
            "customer": order_data.customer,
            "items": [{"sku": item.sku, "qty": item.qty} for item in order_data.items]
        }
        await writer_client.post("/internal/orders", order_payload, headers={"X-Request-Id": request_id})
    except Exception:
        # Si writer falla: HSET status = FAILED
        now = datetime.now(timezone.utc).isoformat()
        await redis.hset(redis_key, mapping={"status": "FAILED", "last_update": now})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "Writer service unavailable", "order_id": order_id},
        )

    return CreateOrderResponse(order_id=order_id, status="RECEIVED")

@app.get("/orders/{id}", status_code=status.HTTP_200_OK, tags=["orders"])
async def get_order(id: UUID, redis: redis_dependency) -> OrderStatusResponse:
    data = await redis.hgetall(f"order:{id}")
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderStatusResponse(order_id=str(id), **data)