import os
import logging
import threading
import time
from datetime import datetime, timezone
from uuid import UUID
import xml.etree.ElementTree as ET

import pika
from defusedxml import ElementTree as DefusedET

from database import SessionLocal

logger = logging.getLogger(__name__)

# RabbitMQ configuration
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

USER_EVENTS_EXCHANGE = "user.events"

RPC_CREATE_QUEUE = "identity.user.create.request"
RPC_LOOKUP_EMAIL_QUEUE = "identity.user.lookup.email.request"
RPC_LOOKUP_UUID_QUEUE = "identity.user.lookup.uuid.request"
MAX_XML_PAYLOAD_BYTES = 64 * 1024
RABBITMQ_RETRY_DELAY_SECONDS = 3


def _xml_text(parent: ET.Element, tag: str, value: str) -> None:
    child = ET.SubElement(parent, tag)
    child.text = value


def _build_ok_response(user) -> str:
    root = ET.Element("identity_response")
    _xml_text(root, "status", "ok")

    user_node = ET.SubElement(root, "user")
    _xml_text(user_node, "master_uuid", str(user.master_uuid))
    _xml_text(user_node, "email", user.email)
    _xml_text(user_node, "created_by", user.created_by)
    _xml_text(user_node, "created_at", user.created_at.isoformat())

    return ET.tostring(root, encoding="unicode")


def _build_error_response(error_code: str, message: str) -> str:
    root = ET.Element("identity_response")
    _xml_text(root, "status", "error")
    _xml_text(root, "error_code", error_code)
    _xml_text(root, "message", message)
    return ET.tostring(root, encoding="unicode")


def _parse_xml_payload(payload: bytes) -> ET.Element:
    if len(payload) > MAX_XML_PAYLOAD_BYTES:
        raise ValueError("Payload too large")
    decoded = payload.decode("utf-8")
    return DefusedET.fromstring(decoded)


def _read_required(root: ET.Element, path: str) -> str:
    value = root.findtext(path)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required field: {path}")
    return value.strip()


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
        heartbeat=30,
        blocked_connection_timeout=30,
        socket_timeout=10,
    )
    return pika.BlockingConnection(parameters)


def declare_exchange(connection):
    """Declare the user.events fanout exchange."""
    channel = connection.channel()
    channel.exchange_declare(
        exchange=USER_EVENTS_EXCHANGE,
        exchange_type="fanout",
        durable=True,
        auto_delete=False,
    )
    channel.close()


def declare_rpc_queues(connection):
    """Declare durable RabbitMQ request queues for XML RPC."""
    channel = connection.channel()
    channel.queue_declare(queue=RPC_CREATE_QUEUE, durable=True)
    channel.queue_declare(queue=RPC_LOOKUP_EMAIL_QUEUE, durable=True)
    channel.queue_declare(queue=RPC_LOOKUP_UUID_QUEUE, durable=True)
    channel.close()


def declare_infrastructure(connection):
    """Declare all RabbitMQ artifacts required by this service."""
    declare_exchange(connection)
    declare_rpc_queues(connection)


def publish_user_created(master_uuid: UUID, email: str, source_system: str):
    """Publish a UserCreated event to RabbitMQ as XML."""
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()

        # Declare exchange with durable and persistent settings
        channel.exchange_declare(
            exchange=USER_EVENTS_EXCHANGE,
            exchange_type="fanout",
            durable=True,
            auto_delete=False,
        )

        event_root = ET.Element("user_event")
        _xml_text(event_root, "event", "UserCreated")
        _xml_text(event_root, "master_uuid", str(master_uuid))
        _xml_text(event_root, "email", email)
        _xml_text(event_root, "source_system", source_system)
        _xml_text(event_root, "timestamp", datetime.now(timezone.utc).isoformat())
        xml_payload = ET.tostring(event_root, encoding="utf-8")

        # Publish message with persistent delivery
        channel.basic_publish(
            exchange=USER_EVENTS_EXCHANGE,
            routing_key="",  # fanout ignores routing key
            body=xml_payload,
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                content_type="application/xml",
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


def _publish_rpc_response(channel, properties, response_xml: str) -> None:
    reply_to = properties.reply_to
    correlation_id = properties.correlation_id

    if not reply_to:
        logger.warning("RPC request without reply_to; skipping response publish")
        return

    channel.basic_publish(
        exchange="",
        routing_key=reply_to,
        body=response_xml.encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/xml",
            correlation_id=correlation_id,
            delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
        ),
    )


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    return "Internal server error"


def _process_once(connection, channel) -> None:
    connection.process_data_events(time_limit=1)


def start_rpc_server(stop_event: threading.Event):
    """
    Start RabbitMQ XML-RPC consumers.

    Supported queues:
    - identity.user.create.request
    - identity.user.lookup.email.request
    - identity.user.lookup.uuid.request
    """
    def handle_create(ch, method, properties, body):
        db = SessionLocal()
        try:
            from services import create_user

            root = _parse_xml_payload(body)
            email = _read_required(root, "email")
            source_system = _read_required(root, "source_system")

            user = create_user(email, source_system, db)
            response_xml = _build_ok_response(user)
            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as exc:
            logger.error(f"RPC create failed: {exc}")
            response_xml = _build_error_response("CREATE_FAILED", _safe_error_message(exc))
            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        finally:
            db.close()

    def handle_lookup_email(ch, method, properties, body):
        db = SessionLocal()
        try:
            from services import get_user_by_email

            root = _parse_xml_payload(body)
            email = _read_required(root, "email")
            user = get_user_by_email(email, db)

            if user is None:
                response_xml = _build_error_response("NOT_FOUND", "User not found")
            else:
                response_xml = _build_ok_response(user)

            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as exc:
            logger.error(f"RPC lookup by email failed: {exc}")
            response_xml = _build_error_response("LOOKUP_FAILED", _safe_error_message(exc))
            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        finally:
            db.close()

    def handle_lookup_uuid(ch, method, properties, body):
        db = SessionLocal()
        try:
            from services import get_user_by_uuid

            root = _parse_xml_payload(body)
            uuid_raw = _read_required(root, "master_uuid")
            user = get_user_by_uuid(UUID(uuid_raw), db)

            if user is None:
                response_xml = _build_error_response("NOT_FOUND", "User not found")
            else:
                response_xml = _build_ok_response(user)

            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as exc:
            logger.error(f"RPC lookup by uuid failed: {exc}")
            response_xml = _build_error_response("LOOKUP_FAILED", _safe_error_message(exc))
            _publish_rpc_response(ch, properties, response_xml)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        finally:
            db.close()

    while not stop_event.is_set():
        connection = None
        channel = None
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()

            declare_infrastructure(connection)
            channel.basic_qos(prefetch_count=1)

            channel.basic_consume(queue=RPC_CREATE_QUEUE, on_message_callback=handle_create)
            channel.basic_consume(queue=RPC_LOOKUP_EMAIL_QUEUE, on_message_callback=handle_lookup_email)
            channel.basic_consume(queue=RPC_LOOKUP_UUID_QUEUE, on_message_callback=handle_lookup_uuid)

            logger.info("Identity XML RPC server started on RabbitMQ queues")

            while not stop_event.is_set():
                _process_once(connection, channel)

        except Exception as exc:
            logger.error(f"RPC server connection loop error: {exc}")
            if not stop_event.is_set():
                time.sleep(RABBITMQ_RETRY_DELAY_SECONDS)
        finally:
            try:
                if channel and channel.is_open:
                    channel.close()
            except Exception:
                pass
            try:
                if connection and connection.is_open:
                    connection.close()
            except Exception:
                pass

    logger.info("Identity XML RPC server stopped")
