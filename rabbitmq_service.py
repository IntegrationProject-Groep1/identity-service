import json
import pika
import os
import logging
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger(__name__)

# RabbitMQ configuration
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

EXCHANGE_NAME = "user.events"


def get_rabbitmq_connection():
    """Create a RabbitMQ connection with credentials."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        connection_attempts=3,
        retry_delay=2,
    )
    return pika.BlockingConnection(parameters)


def declare_exchange(connection):
    """Declare the user.events fanout exchange."""
    channel = connection.channel()
    channel.exchange_declare(
        exchange=EXCHANGE_NAME,
        exchange_type="fanout",
        durable=True,
        auto_delete=False,
    )
    channel.close()


def publish_user_created(master_uuid: UUID, email: str, source_system: str):
    """Publish a UserCreated event to RabbitMQ."""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()

        # Declare exchange with durable and persistent settings
        channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="fanout",
            durable=True,
            auto_delete=False,
        )

        # Build event payload
        event_payload = {
            "event": "UserCreated",
            "master_uuid": str(master_uuid),
            "email": email,
            "source_system": source_system,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Publish message with persistent delivery
        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key="",  # fanout ignores routing key
            body=json.dumps(event_payload),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                content_type="application/json",
            ),
        )

        logger.info(
            f"Published UserCreated event for {email} with UUID {master_uuid}"
        )
        channel.close()
        connection.close()

    except Exception as e:
        logger.error(f"Failed to publish UserCreated event: {e}")
        raise
