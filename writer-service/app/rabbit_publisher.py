import asyncio
import functools
import json
import logging

import pika
import pika.adapters.blocking_connection

from .config import settings

logger = logging.getLogger(__name__)

EXCHANGE = "orders"  # topic exchange: enruta por routing key

# Singleton: conexion y canal compartidos por toda la app
_connection: pika.BlockingConnection | None = None
_channel: pika.adapters.blocking_connection.BlockingChannel | None = None


def rabbit_connect() -> None:
    """Conecta a RabbitMQ y declara el exchange."""
    global _connection, _channel
    _connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    _channel = _connection.channel()
    _channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    logger.info("RabbitMQ connected, exchange '%s' ready.", EXCHANGE)


def rabbit_close() -> None:
    if _connection and not _connection.is_closed:
        _connection.close()
        logger.info("RabbitMQ connection closed.")


class RabbitPublisher:
    def __init__(self, channel: pika.adapters.blocking_connection.BlockingChannel):
        self._channel = channel

    def _publish_sync(self, routing_key: str, body: bytes) -> None:
        # pika es bloqueante: se ejecuta en un thread para no bloquear asyncio
        self._channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )

    async def publish_order_created(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, functools.partial(self._publish_sync, "order.created", body)
        )
        logger.info("Published order.created: %s", payload)


def get_publisher() -> RabbitPublisher:
    return RabbitPublisher(_channel)
