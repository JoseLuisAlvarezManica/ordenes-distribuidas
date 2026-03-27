import asyncio
import logging
import re
import threading
import time

import telegram
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import NetworkError, TimedOut

from .config import settings
from .db import AsyncSessionLocal, engine
from .models import Base, Notification
from .schemas import NotificationMessage, OrderCreatedEvent, OrderErrorEvent
from .services.rabbit_publisher import publish_processing_event
from .services.rabbit_subscriber import start_subscriber
from .services.register_user import get_chat_id_by_phone, register_user

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
logging.getLogger("pika").setLevel(logging.WARNING)

EXCHANGE = "orders"
QUEUE = "notification.order.events"
ROUTING_KEYS = ["order.created", "order.error"]
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")
START_PATTERN = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$")

_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_LOOP_READY = threading.Event()
_ASYNC_RUNTIME_READY = threading.Event()


def _build_message(event: OrderCreatedEvent) -> str:
    items_text = "\n".join(
        f"{index}) {event.names.get(item.sku, item.sku)}: {item.qty}"
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


def _build_error_message(event: OrderErrorEvent) -> str:
    stage_labels = {
        "validation": "validacion de la orden",
        "persist": "guardado de la orden",
        "publish": "publicacion del evento",
    }
    stage_label = stage_labels.get(event.stage, f"etapa {event.stage}")
    if event.order_id:
        return f"Error en {stage_label} para la orden {event.order_id}."
    return f"Error en {stage_label} para una orden sin id informado."


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


async def _save_notification(
    session: AsyncSession, notification: NotificationMessage
) -> None:
    record = Notification(
        order_id=notification.order_id,
        customer=notification.customer,
        event_type=notification.event_type,
        message=notification.message,
        reason=notification.reason,
    )
    session.add(record)
    await session.commit()


async def _save_created_error_notification(event: OrderCreatedEvent, error_description: str) -> None:
    notification = NotificationMessage(
        order_id=event.order_id,
        customer=event.customer,
        event_type="notification.error",
        message="No se pudo enviar la notificacion de la orden a Telegram.",
        reason=error_description,
    )

    async with AsyncSessionLocal() as session:
        await _save_notification(session, notification)

    logger.info(
        "DB: error de notificacion persistido order_id=%s customer=%s",
        event.order_id,
        event.customer,
    )


async def notify(event: OrderCreatedEvent) -> None:
    chat_id = await _get_chat_id_for_phone(event.phone_number)
    if not chat_id:
        reason = f"No hay chat_id asociado para phone_number={event.phone_number}"
        await _save_created_error_notification(event, reason)
        raise RuntimeError(reason)

    message_text = _build_message(event)
    notification = NotificationMessage(
        order_id=event.order_id,
        customer=event.customer,
        event_type="order.created",
        message=message_text,
        reason=None,
    )

    try:
        await _send_telegram_message(chat_id=chat_id, text=notification.message)
    except Exception as exc:
        await _save_created_error_notification(event, str(exc))
        raise

    logger.info(
        "Telegram: mensaje enviado order_id=%s chat_id=%s",
        event.order_id,
        chat_id,
    )

    async with AsyncSessionLocal() as session:
        await _save_notification(session, notification)

    logger.info(
        "DB: notificación persistida order_id=%s customer=%s",
        event.order_id,
        event.customer,
    )


async def save_error_notification(event: OrderErrorEvent) -> None:
    notification = NotificationMessage(
        order_id=event.order_id or "N/A",
        customer="SYSTEM",
        event_type="order.error",
        message=_build_error_message(event),
        reason=event.error,
    )

    async with AsyncSessionLocal() as session:
        await _save_notification(session, notification)

    logger.info(
        "DB: error persistido order_id=%s stage=%s",
        event.order_id,
        event.stage,
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
        while not stop_event.is_set():
            await asyncio.sleep(1)
        return

    bot = telegram.Bot(settings.telegram_bot_token)
    offset: int | None = None
    retry_delay = settings.telegram_poll_seconds

    async with bot:
        while not stop_event.is_set():
            try:
                if offset is None:
                    me = await bot.get_me(
                        connect_timeout=settings.telegram_connect_timeout,
                        read_timeout=settings.telegram_read_timeout,
                    )
                    logger.info("Bot autenticado: @%s (id=%s)", me.username, me.id)

                updates = await bot.get_updates(
                    offset=offset,
                    timeout=settings.telegram_poll_timeout,
                    connect_timeout=settings.telegram_connect_timeout,
                    read_timeout=settings.telegram_read_timeout,
                )
                retry_delay = settings.telegram_poll_seconds
                for update in updates:
                    if isinstance(update.update_id, int):
                        offset = update.update_id + 1

                    message = update.message or update.edited_message
                    if message is None:
                        continue
                    await _process_start_command(message.to_dict())
            except TimedOut:
                logger.warning("Timeout en polling de Telegram. Reintentando...")
            except NetworkError as exc:
                logger.warning(
                    "Error de red en Telegram: %s. Reintentando en %.1fs",
                    exc,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, settings.telegram_retry_backoff_max)
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
    if not settings.postgres_notifications_url:
        raise RuntimeError("POSTGRES_NOTIFICATIONS_URL no está configurado")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def on_order_event(channel, method, properties, body: bytes) -> None:
    started = time.perf_counter()
    routing_key = getattr(method, "routing_key", "")
    order_id: str | None = None
    try:
        if routing_key == "order.created":
            event = OrderCreatedEvent.model_validate_json(body)
            order_id = event.order_id
            logger.info("order.created recibido order_id=%s", event.order_id)
        elif routing_key == "order.error":
            event = OrderErrorEvent.model_validate_json(body)
            order_id = event.order_id
            logger.info("order.error recibido order_id=%s stage=%s", event.order_id, event.stage)
        else:
            raise ValueError(f"routing_key no soportado: {routing_key}")

        if not _ASYNC_RUNTIME_READY.wait(timeout=20):
            raise RuntimeError("Async runtime no está inicializado")
        if _ASYNC_LOOP is None:
            raise RuntimeError("Async loop no disponible")

        coroutine = notify(event) if routing_key == "order.created" else save_error_notification(event)
        future = asyncio.run_coroutine_threadsafe(coroutine, _ASYNC_LOOP)
        future.result(timeout=30)

        duration_ms = (time.perf_counter() - started) * 1000
        publish_processing_event(
            {
                "order_id": order_id,
                "service": "notification",
                "status": "success",
                "metric": routing_key,
                "duration_ms": round(duration_ms, 2),
            }
        )
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            publish_processing_event(
                {
                    "order_id": order_id,
                    "service": "notification",
                    "status": "error",
                    "metric": routing_key or None,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar evento de error de notification: %s", publish_exc)
        logger.error("Error procesando %s: %s", routing_key or "evento", exc, exc_info=True)
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

    start_subscriber(EXCHANGE, QUEUE, ROUTING_KEYS, on_order_event)
    logger.info("Notification service iniciado")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        stop_event.set()


if __name__ == "__main__":
    main()
