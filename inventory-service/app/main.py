import asyncio
import logging
import threading


from .schemas import OrderCreatedEvent
from .services.inventory_service import discount_inventory
from .services.rabbit_subscriber import start_subscriber, stop_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

EXCHANGE = "orders"
QUEUE = "inventory.order.created"
ROUTING_KEY = "order.created"


def on_order_created(channel, method, properties, body: bytes) -> None:
    try:
        event = OrderCreatedEvent.model_validate_json(body)
        logger.info("order.created recibido order_id=%s", event.order_id)
        asyncio.run(discount_inventory(event.items))
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:
        logger.error("Error procesando order.created: %s", exc, exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


start_subscriber(EXCHANGE, QUEUE, ROUTING_KEY, on_order_created)
threading.Event().wait()
