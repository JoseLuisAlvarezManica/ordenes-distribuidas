import asyncio
import logging
import threading
import time


from .schemas import OrderCreatedEvent
from .services.inventory_service import discount_inventory
from .services.rabbit_publisher import publish_processing_event
from .services.rabbit_subscriber import start_subscriber, stop_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
logging.getLogger("pika").setLevel(logging.WARNING)

EXCHANGE = "orders"
QUEUE = "inventory.order.created"
ROUTING_KEY = "order.created"

_loop = None

def on_order_created(channel, method, properties, body: bytes) -> None:
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

    started = time.perf_counter()
    event: OrderCreatedEvent | None = None
    try:
        event = OrderCreatedEvent.model_validate_json(body)
        logger.info("order.created recibido order_id=%s", event.order_id)
        _loop.run_until_complete(discount_inventory(event.items))
        duration_ms = (time.perf_counter() - started) * 1000
        publish_processing_event(
            {
                "order_id": event.order_id,
                "service": "inventory",
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
                    "service": "inventory",
                    "status": "error",
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                }
            )
        except Exception as publish_exc:
            logger.warning("No se pudo publicar evento de error de inventory: %s", publish_exc)
        logger.error("Error procesando order.created: %s", exc, exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


start_subscriber(EXCHANGE, QUEUE, ROUTING_KEY, on_order_created)
threading.Event().wait()
