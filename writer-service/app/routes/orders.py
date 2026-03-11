import logging
from datetime import datetime, timezone
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..redis_client import get_redis
from ..repositories.orders_repo import upsert_order, validate_stock
from ..schemas import InternalOrder
from ..rabbit_publisher import RabbitPublisher, get_publisher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/orders", tags=["internal-orders"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_internal_order(
    order: InternalOrder,
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    publisher: RabbitPublisher = Depends(get_publisher),
    request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, str]:
    correlation_id = request_id or "N/A"
    redis_key = f"order:{order.order_id}"

    stock_errors = await validate_stock(db, [{"sku": item.sku, "qty": item.qty} for item in order.items])
    if stock_errors:
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "FAILED", "last_update", now)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": stock_errors},
        )

    try:
        inserted = await upsert_order(
            session=db,
            order_id=order.order_id,
            customer=order.customer,
            items=[{"sku": item.sku, "qty": item.qty} for item in order.items],
        )
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "PERSISTED", "last_update", now)
        await publisher.publish_order_created({
            "order_id": str(order.order_id),
            "customer": order.customer,
            "items": [{"sku": item.sku, "qty": item.qty} for item in order.items],
        })
        logger.info(
            "Orden persistida inserted=%s order_id=%s [X-Request-Id: %s]",
            inserted,
            order.order_id,
            correlation_id,
        )
        return {"order_id": str(order.order_id), "status": "PERSISTED"}
    
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "FAILED", "last_update", now)
        logger.exception(
            "Error persisting order_id=%s [X-Request-Id: %s]: %s",
            order.order_id,
            correlation_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error persisting order",
        ) from exc
