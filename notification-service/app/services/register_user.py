from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TelegramSubscription


async def register_user(session: AsyncSession, phone_number: str, chat_id: str) -> None:
    result = await session.execute(
        select(TelegramSubscription).where(TelegramSubscription.phone_number == phone_number)
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        session.add(TelegramSubscription(phone_number=phone_number, chat_id=chat_id))
    else:
        existing.chat_id = chat_id
        existing.updated_at = datetime.now(timezone.utc)

    await session.commit()


async def get_chat_id_by_phone(session: AsyncSession, phone_number: str) -> str | None:
    result = await session.execute(
        select(TelegramSubscription.chat_id).where(
            TelegramSubscription.phone_number == phone_number
        )
    )
    return result.scalar_one_or_none()
