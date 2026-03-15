import json
import logging
from typing import Any

import asyncpg

from ..config import settings
from .aggregator import AnalyticsAggregator

logger = logging.getLogger(__name__)


def _normalize_dsn(raw_url: str) -> str:
    return raw_url.replace("postgresql+asyncpg://", "postgresql://")


def _items_to_list(raw_items: Any) -> list[dict[str, Any]]:
    if isinstance(raw_items, list):
        return [item for item in raw_items if isinstance(item, dict)]
    if isinstance(raw_items, str):
        try:
            parsed = json.loads(raw_items)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
    return []


async def preload_business_metrics_from_orders(aggregator: AnalyticsAggregator) -> int:
    if not settings.database_url:
        logger.warning("DATABASE_URL no configurado; analytics inicia sin precarga historica")
        return 0

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(_normalize_dsn(settings.database_url))
        rows = await conn.fetch("SELECT order_id, customer, items FROM orders")

        for row in rows:
            aggregator.add_created(
                order_id=str(row["order_id"]),
                customer=str(row["customer"]),
                items=_items_to_list(row["items"]),
                persist_ms=None,
            )

        logger.info("Analytics precargado con %s ordenes historicas", len(rows))
        return len(rows)
    except Exception as exc:
        logger.error("No se pudo precargar analytics desde orders: %s", exc, exc_info=True)
        return 0
    finally:
        if conn is not None:
            await conn.close()
