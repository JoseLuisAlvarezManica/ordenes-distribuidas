from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order, Product


async def upsert_order(
    session: AsyncSession,
    order_id: UUID,
    customer: str,
    items: list[dict],
) -> bool:

    order_id_str = str(order_id)
    try:
        result = await session.execute(
            select(Order).where(Order.order_id == order_id_str)
        )
        if result.scalar_one_or_none() is not None:
            return False

        new_order = Order(
            order_id=order_id_str,
            customer=customer,
            items=items,
        )
        session.add(new_order)
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        raise

async def validate_stock(session: AsyncSession, items: list[dict]) -> list[str]:
    errors = []
    for item in items:
        result = await session.execute(select(Product).where(Product.sku == item["sku"]))
        product = result.scalar_one_or_none()
        if product is None:
            errors.append(f"SKU '{item['sku']}' no existe")
        elif product.stock < item["qty"]:
            errors.append(f"SKU '{item['sku']}' stock insuficiente (disponible: {product.stock}, solicitado: {item['qty']})")
    return errors

async def list_orders_by_customer(session: AsyncSession, customer: str) -> list[Order]:
    result = await session.execute(select(Order).where(Order.customer == customer))
    return result.scalars().all() if result else []

async def list_all_orders(session: AsyncSession) -> list[Order]:
    result = await session.execute(select(Order))
    return result.scalars().all() if result else []

