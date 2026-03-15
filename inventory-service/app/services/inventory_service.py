import logging

from sqlalchemy import select

from ..db import AsyncSessionLocal
from ..models import Product
from ..schemas import OrderItem

logger = logging.getLogger(__name__)


async def discount_inventory(items: list[OrderItem]) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for item in items:
                result = await session.execute(
                    select(Product).where(Product.sku == item.sku).with_for_update()
                )
                product = result.scalar_one_or_none()
                if product is None:
                    raise ValueError(f"SKU {item.sku} no encontrado.")
                if product.stock < item.qty:
                    raise ValueError(
                        f"Stock insuficiente SKU {item.sku} "
                        f"(disponible: {product.stock}, solicitado: {item.qty})."
                    )
                product.stock -= item.qty
                logger.info("SKU %s: descontado %d (restante: %d).", item.sku, item.qty, product.stock)
