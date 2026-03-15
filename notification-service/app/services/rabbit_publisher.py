import json
import logging

import pika

from ..config import settings

logger = logging.getLogger(__name__)

EXCHANGE = "orders"


def publish_processing_event(payload: dict) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    try:
        channel = connection.channel()
        channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key="order.processing",
            body=json.dumps(payload).encode(),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )
        logger.info("Published order.processing: %s", payload)
    finally:
        if connection and not connection.is_closed:
            connection.close()
