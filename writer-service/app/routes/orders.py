import logging
import time
from datetime import datetime, timezone
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..redis_client import get_redis
from ..repositories.orders_repo import upsert_order, validate_stock, list_orders_by_customer, list_all_orders
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
        try:
            await publisher.publish_order_error(
                {
                    "order_id": str(order.order_id),
                    "stage": "validation",
                    "error": "; ".join(stock_errors),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar order.error (validation): %s", publish_exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": stock_errors},
        )

    try:
        persist_started = time.perf_counter()
        inserted = await upsert_order(
            session=db,
            order_id=order.order_id,
            customer=order.customer,
            items=[{"sku": item.sku, "qty": item.qty} for item in order.items],
        )
        persist_ms = (time.perf_counter() - persist_started) * 1000
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "FAILED", "last_update", now)
        try:
            await publisher.publish_order_error(
                {
                    "order_id": str(order.order_id),
                    "stage": "persist",
                    "error": str(exc),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar order.error (persist): %s", publish_exc)
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

    now = datetime.now(timezone.utc).isoformat()
    await redis.execute_command("HSET", redis_key, "status", "PERSISTED", "last_update", now)

    try:
        publish_started = time.perf_counter()
        item_names = {}
        for item in order.items:
            product_name = await redis.hget(item.sku, "name")
            item_names[item.sku] = product_name if product_name else item.sku
        await publisher.publish_order_created(
            {
                "order_id": str(order.order_id),
                "customer": order.customer,
                "phone_number": order.phone_number,
                "items": [{"sku": item.sku, "qty": item.qty} for item in order.items],
                "names": item_names,
                "persist_ms": round(persist_ms, 2),
            }
        )
        publish_ms = (time.perf_counter() - publish_started) * 1000

        await publisher.publish(
            "order.processing",
            {
                "order_id": str(order.order_id),
                "service": "writer",
                "status": "success",
                "metric": "publish",
                "duration_ms": round(publish_ms, 2),
            },
        )
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        await redis.execute_command("HSET", redis_key, "status", "FAILED", "last_update", now)
        try:
            await publisher.publish_order_error(
                {
                    "order_id": str(order.order_id),
                    "stage": "publish",
                    "error": str(exc),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar order.error (publish): %s", publish_exc)
        logger.exception(
            "Error publishing order.created order_id=%s [X-Request-Id: %s]: %s",
            order.order_id,
            correlation_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error publishing order event",
        ) from exc

    logger.info(
        "Orden persistida inserted=%s order_id=%s persist_ms=%.2f publish_ms=%.2f [X-Request-Id: %s]",
        inserted,
        order.order_id,
        persist_ms,
        publish_ms,
        correlation_id,
    )
    return {"order_id": str(order.order_id), "status": "PERSISTED"}


@router.get("/my_orders", status_code=status.HTTP_200_OK)
async def get_my_orders(request: Request, db: AsyncSession = Depends(get_db)):
    customer = request.headers.get("X-Customer")
    if not customer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Customer header")

    orders = await list_orders_by_customer(db, customer)
    return orders


@router.get("", status_code=status.HTTP_200_OK)
async def list_orders(db: AsyncSession = Depends(get_db)):
    orders = await list_all_orders(db)
    return orders
    
