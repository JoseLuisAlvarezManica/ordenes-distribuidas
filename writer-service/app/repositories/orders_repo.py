from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order


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
