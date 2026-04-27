from datetime import datetime, timezone
import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TelegramSubscription

PHONE_PATTERN = re.compile(r"^\d{10}$")


def normalize_phone_number(raw_phone: str) -> str:
    digits = re.sub(r"\D", "", raw_phone)

    if len(digits) > 10:
        digits = digits[-10:]

    if not PHONE_PATTERN.fullmatch(digits):
        raise ValueError("Formato de teléfono inválido")
    return digits


async def register_user(
    session: AsyncSession, phone_number: str, chat_id: str
) -> tuple[bool, str]:
    try:
        phone = normalize_phone_number(phone_number)
        result = await session.execute(
            select(TelegramSubscription)
            .where(
                or_(
                    TelegramSubscription.phone_number == phone,
                    TelegramSubscription.phone_number.like(f"%{phone}"),
                )
            )
            .order_by(TelegramSubscription.updated_at.desc())
        )
        existing = result.scalars().first()

        if existing is None:
            session.add(TelegramSubscription(phone_number=phone, chat_id=chat_id))
        else:
            existing.phone_number = phone
            existing.chat_id = chat_id
            existing.updated_at = datetime.now(timezone.utc)

        await session.commit()
        return True, "Suscripción registrada exitosamente"
    except ValueError:
        return (
            False,
            "Formato de teléfono inválido. Ejemplo válido: /register 3001112233",
        )
    except Exception as exc:
        return False, f"Error al registrar la suscripción: {str(exc)}"
