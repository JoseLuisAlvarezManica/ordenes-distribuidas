import asyncio
import logging
import re
import threading
import time

import telegram
from sqlalchemy import String, column, select, table

from .config import settings
from .db import AsyncSessionLocal, engine
from .models import Base
from .services.register_user import get_chat_id_by_phone, register_user
from .services.rabbit_publisher import publish_processing_event
from .schemas import OrderCreatedEvent
from .services.rabbit_subscriber import start_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

EXCHANGE = "orders"
QUEUE = "notification.order.created"
ROUTING_KEY = "order.created"
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")
START_PATTERN = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$")

_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_READY = threading.Event()
_ASYNC_RUNTIME_READY = threading.Event()


def _build_message(event: OrderCreatedEvent, product_names: dict[str, str]) -> str:
    items_text = "\n".join(
        f"{index}) {product_names.get(item.sku, item.sku)}: {item.qty}"
        for index, item in enumerate(event.items, start=1)
    )
    if not items_text:
        items_text = "(sin ítems)"
    return (
        "Hola!, \n"
        f"tu orden de:\n"
        f"{items_text}\n"
        "fue realizada con exito."
    )


def _normalize_phone_number(raw_phone: str) -> str:
    normalized = raw_phone.strip().replace(" ", "").replace("-", "")
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("Formato de teléfono inválido")
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"
    return normalized


async def _send_telegram_message(chat_id: str, text: str) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado")

    bot = telegram.Bot(settings.telegram_bot_token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=text)


async def _register_subscription(phone_number: str, chat_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await register_user(session, phone_number=phone_number, chat_id=chat_id)


async def _get_chat_id_for_phone(phone_number: str) -> str | None:
    async with AsyncSessionLocal() as session:
        return await get_chat_id_by_phone(session, phone_number=phone_number)


async def _get_product_names_by_sku(skus: list[str]) -> dict[str, str]:
    if not skus:
        return {}

    products = table(
        "products",
        column("sku", String),
        column("name", String),
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(products.c.sku, products.c.name).where(products.c.sku.in_(skus))
        )
        rows = result.all()

    return {sku: name for sku, name in rows}


async def notify(event: OrderCreatedEvent) -> None:
    chat_id = await _get_chat_id_for_phone(event.phone_number)
    if not chat_id:
        logger.warning(
            "No hay chat_id asociado para phone_number=%s. Se omite notificación.",
            event.phone_number,
        )
        return

    product_names = await _get_product_names_by_sku([item.sku for item in event.items])
    await _send_telegram_message(chat_id=chat_id, text=_build_message(event, product_names))

    logger.info(
        "Notificación enviada order_id=%s phone_number=%s",
        event.order_id,
        event.phone_number,
    )


async def _process_start_command(message: dict) -> None:
    text = (message.get("text") or "").strip()
    match = START_PATTERN.match(text)
    if not match:
        return

    chat_id = str(((message.get("chat") or {}).get("id") or "")).strip()
    if not chat_id:
        return

    phone_arg = (match.group(1) or "").strip()
    if not phone_arg:
        await _send_telegram_message(
            chat_id=chat_id,
            text="Usa: /start <telefono>. Ejemplo: /start +573001112233",
        )
        return

    try:
        phone_number = _normalize_phone_number(phone_arg)
    except ValueError:
        await _send_telegram_message(
            chat_id=chat_id,
            text="Formato inválido. Ejemplo válido: /start +573001112233",
        )
        return

    await _register_subscription(phone_number=phone_number, chat_id=chat_id)
    await _send_telegram_message(
        chat_id=chat_id,
        text=f"Listo. Tu chat quedó asociado al número {phone_number}",
    )
    logger.info("Suscripción registrada phone_number=%s chat_id=%s", phone_number, chat_id)


async def _poll_telegram_updates(stop_event: threading.Event) -> None:
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado. /start deshabilitado.")
        return

    bot = telegram.Bot(settings.telegram_bot_token)
    offset: int | None = None

    async with bot:
        me = await bot.get_me()
        logger.info("Bot autenticado: @%s (id=%s)", me.username, me.id)

        while not stop_event.is_set():
            try:
                updates = await bot.get_updates(offset=offset, timeout=30)
                for update in updates:
                    if isinstance(update.update_id, int):
                        offset = update.update_id + 1

                    message = update.message or update.edited_message
                    if message is None:
                        continue
                    await _process_start_command(message.to_dict())
            except Exception as exc:
                logger.error("Error en polling de Telegram: %s", exc, exc_info=True)
                await asyncio.sleep(settings.telegram_poll_seconds)


async def _async_runtime(stop_event: threading.Event) -> None:
    await _init_db()
    _ASYNC_RUNTIME_READY.set()
    await _poll_telegram_updates(stop_event)


def _run_async_runtime(stop_event: threading.Event) -> None:
    global _ASYNC_LOOP
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ASYNC_LOOP = loop
    _ASYNC_LOOP_READY.set()

    try:
        loop.run_until_complete(_async_runtime(stop_event))
    finally:
        loop.run_until_complete(engine.dispose())
        loop.close()


async def _init_db() -> None:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL no está configurado")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def on_order_created(channel, method, properties, body: bytes) -> None:
    started = time.perf_counter()
    event: OrderCreatedEvent | None = None
    try:
        event = OrderCreatedEvent.model_validate_json(body)
        logger.info("order.created recibido order_id=%s", event.order_id)

        if not _ASYNC_RUNTIME_READY.wait(timeout=20):
            raise RuntimeError("Async runtime no está inicializado")
        if _ASYNC_LOOP is None:
            raise RuntimeError("Async loop no disponible")

        future = asyncio.run_coroutine_threadsafe(notify(event), _ASYNC_LOOP)
        future.result(timeout=30)

        duration_ms = (time.perf_counter() - started) * 1000
        publish_processing_event(
            {
                "order_id": event.order_id,
                "service": "notification",
                "status": "success",
                "duration_ms": round(duration_ms, 2),
            }
        )
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            publish_processing_event(
                {
                    "order_id": event.order_id if event else None,
                    "service": "notification",
                    "status": "error",
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar evento de error de notification: %s", publish_exc)
        logger.error("Error procesando order.created: %s", exc, exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main() -> None:
    stop_event = threading.Event()

    async_runtime_thread = threading.Thread(
        target=_run_async_runtime,
        args=(stop_event,),
        daemon=True,
        name="notification-async-runtime",
    )
    async_runtime_thread.start()

    if not _ASYNC_LOOP_READY.wait(timeout=10):
        raise RuntimeError("No se pudo iniciar el loop async")

    if not _ASYNC_RUNTIME_READY.wait(timeout=20):
        raise RuntimeError("No se pudo inicializar el runtime async")

    start_subscriber(EXCHANGE, QUEUE, ROUTING_KEY, on_order_created)
    logger.info("Notification service iniciado")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        stop_event.set()


if __name__ == "__main__":
    main()
