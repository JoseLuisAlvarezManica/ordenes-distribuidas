import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .schemas import OrderCreatedEvent, OrderErrorEvent, OrderProcessingEvent
from .services.aggregator import AnalyticsAggregator
from .services.bootstrap_loader import preload_business_metrics_from_orders
from .services.rabbit_subscriber import start_subscriber, stop_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

EXCHANGE = "orders"
QUEUE = "analytics.order.events"
ROUTING_KEYS = ["order.created", "order.error", "order.processing"]

aggregator = AnalyticsAggregator()


def on_order_event(channel, method, properties, body: bytes) -> None:
    try:
        routing_key = getattr(method, "routing_key", "")

        if routing_key == "order.created":
            event = OrderCreatedEvent.model_validate_json(body)
            aggregator.add_created(
                order_id=event.order_id,
                customer=event.customer,
                items=[{"sku": item.sku, "qty": item.qty} for item in event.items],
                persist_ms=event.persist_ms,
            )
        elif routing_key == "order.error":
            event = OrderErrorEvent.model_validate_json(body)
            aggregator.add_error(stage=event.stage)
        elif routing_key == "order.processing":
            event = OrderProcessingEvent.model_validate_json(body)
            aggregator.add_processing(
                service=event.service,
                status=event.status,
                metric=event.metric,
                duration_ms=event.duration_ms,
            )

        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:
        logger.error("Error procesando evento analytics: %s", exc, exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await preload_business_metrics_from_orders(aggregator)
    start_subscriber(EXCHANGE, QUEUE, ROUTING_KEYS, on_order_event)
    yield
    stop_subscriber()


app = FastAPI(title="analytics-service", lifespan=lifespan)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/analytics", tags=["analytics"])
async def get_analytics() -> dict:
    return aggregator.snapshot()
