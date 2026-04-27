import asyncio
import logging
import threading
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import AsyncSessionLocal, engine
from .models import Base, Notification
from .schemas import NotificationMessage, OrderCreatedEvent, OrderErrorEvent
from .services.rabbit_publisher import publish_processing_event
from .services.rabbit_subscriber import start_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
logging.getLogger("pika").setLevel(logging.WARNING)

EXCHANGE = "orders"
QUEUE = "notification.order.events"
ROUTING_KEYS = ["order.created", "order.error"]

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
    return f"Hola!, \ntu orden de:\n{items_text}\nfue realizada con exito."


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


async def _send_telegram_message(phone_number: str, text: str) -> None:
    url = f"{settings.telegram_bot_service_url.rstrip('/')}/internal/messages"
    payload = {"phone_number": phone_number, "text": text}
    timeout = httpx.Timeout(10.0, connect=3.0, read=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Error llamando telegram-bot: {exc}") from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"telegram-bot respondió {response.status_code}: {response.text}"
        )


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


async def _save_created_error_notification(
    event: OrderCreatedEvent, error_description: str
) -> None:
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
    message_text = _build_message(event)
    notification = NotificationMessage(
        order_id=event.order_id,
        customer=event.customer,
        event_type="order.created",
        message=message_text,
        reason=None,
    )

    try:
        await _send_telegram_message(
            phone_number=event.phone_number,
            text=notification.message,
        )
    except Exception as exc:
        await _save_created_error_notification(event, str(exc))
        raise

    logger.info(
        "Telegram: mensaje enviado order_id=%s phone_number=%s",
        event.order_id,
        event.phone_number,
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


async def _async_runtime(stop_event: threading.Event) -> None:
    await _init_db()
    _ASYNC_RUNTIME_READY.set()
    while not stop_event.is_set():
        await asyncio.sleep(1)


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
            created_event = OrderCreatedEvent.model_validate_json(body)
            order_id = created_event.order_id
            logger.info("order.created recibido order_id=%s", created_event.order_id)
            coroutine = notify(created_event)
        elif routing_key == "order.error":
            error_event = OrderErrorEvent.model_validate_json(body)
            order_id = error_event.order_id
            logger.info(
                "order.error recibido order_id=%s stage=%s",
                error_event.order_id,
                error_event.stage,
            )
            coroutine = save_error_notification(error_event)
        else:
            raise ValueError(f"routing_key no soportado: {routing_key}")

        if not _ASYNC_RUNTIME_READY.wait(timeout=20):
            raise RuntimeError("Async runtime no está inicializado")
        if _ASYNC_LOOP is None:
            raise RuntimeError("Async loop no disponible")

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
            logger.warning(
                "No se pudo publicar evento de error de notification: %s", publish_exc
            )
        logger.error(
            "Error procesando %s: %s", routing_key or "evento", exc, exc_info=True
        )
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
