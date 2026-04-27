import asyncio
import functools
import json
import logging
import time

import pika
import pika.adapters.blocking_connection
from pika.exceptions import AMQPConnectionError, ChannelWrongStateError, StreamLostError

from .config import settings

logger = logging.getLogger(__name__)

EXCHANGE = "orders"  # topic exchange: enruta por routing key

# Singleton: chequeo de conectividad en startup/shutdown
_connection: pika.BlockingConnection | None = None


def rabbit_connect() -> None:
    """Chequea conectividad a RabbitMQ y declara el exchange."""
    global _connection
    params = pika.URLParameters(settings.rabbitmq_url)
    # Conexion de verificacion (startup): no deja un socket ocioso con heartbeat activo.
    params.heartbeat = 0
    _connection = pika.BlockingConnection(params)
    channel = _connection.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    _connection.close()
    _connection = None
    logger.info("RabbitMQ connected, exchange '%s' ready.", EXCHANGE)


def rabbit_close() -> None:
    if _connection and not _connection.is_closed:
        _connection.close()
        logger.info("RabbitMQ connection closed.")


class RabbitPublisher:
    def __init__(self, rabbitmq_url: str):
        self._rabbitmq_url = rabbitmq_url

    def _publish_once(self, routing_key: str, body: bytes) -> None:
        connection = pika.BlockingConnection(pika.URLParameters(self._rabbitmq_url))
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=EXCHANGE, exchange_type="topic", durable=True
            )
            channel.basic_publish(
                exchange=EXCHANGE,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=pika.DeliveryMode.Persistent,
                    content_type="application/json",
                ),
            )
        finally:
            if connection and not connection.is_closed:
                connection.close()

    def _publish_sync(self, routing_key: str, body: bytes) -> None:
        # pika es bloqueante: se ejecuta en un thread para no bloquear asyncio.
        # Se reintenta una vez ante cierres transitorios de conexión/canal.
        for attempt in range(2):
            try:
                self._publish_once(routing_key, body)
                return
            except (
                AMQPConnectionError,
                StreamLostError,
                ChannelWrongStateError,
            ) as exc:
                if attempt == 1:
                    raise
                logger.warning(
                    "Rabbit publish failed (attempt %s): %s", attempt + 1, exc
                )
                time.sleep(0.2)

    async def publish(self, routing_key: str, payload: dict) -> None:
        body = json.dumps(payload).encode()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, functools.partial(self._publish_sync, routing_key, body)
        )

    async def publish_order_created(self, payload: dict) -> None:
        await self.publish("order.created", payload)
        logger.info("Published order.created: %s", payload)

    async def publish_order_error(self, payload: dict) -> None:
        await self.publish("order.error", payload)
        logger.info("Published order.error: %s", payload)


def get_publisher() -> RabbitPublisher:
    return RabbitPublisher(settings.rabbitmq_url)
