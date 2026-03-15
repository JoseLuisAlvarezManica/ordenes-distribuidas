import logging
import threading
from collections.abc import Callable

import pika

from ..config import settings

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_connection: pika.BlockingConnection | None = None


def run_consumer(
    exchange: str,
    queue: str,
    routing_keys: list[str],
    on_message: Callable[[pika.adapters.blocking_connection.BlockingChannel, any, any, bytes], None],
) -> None:
    global _connection
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 0
    _connection = pika.BlockingConnection(params)
    channel = _connection.channel()
    channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
    channel.queue_declare(queue=queue, durable=True)

    for routing_key in routing_keys:
        channel.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key)

    channel.basic_qos(prefetch_count=50)
    channel.basic_consume(queue=queue, on_message_callback=on_message)
    logger.info("Analytics escuchando routing_keys=%s queue=%s", routing_keys, queue)
    channel.start_consuming()


def start_subscriber(
    exchange: str,
    queue: str,
    routing_keys: list[str],
    on_message: Callable[[pika.adapters.blocking_connection.BlockingChannel, any, any, bytes], None],
) -> None:
    global _thread
    _thread = threading.Thread(
        target= run_consumer,
        args=(exchange, queue, routing_keys, on_message),
        daemon=True,
        name="rabbit-consumer-analytics",
    )
    _thread.start()


def stop_subscriber() -> None:
    if _connection and not _connection.is_closed:
        _connection.close()
        logger.info("Analytics subscriber desconectado")
