import os

os.environ["DB_DRIVER"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"

from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from rabbitmq_service import (
    MAX_XML_PAYLOAD_BYTES,
    _build_error_response,
    _build_ok_response,
    _parse_xml_payload,
    _publish_rpc_response,
    _safe_error_message,
)


class DummyChannel:
    def __init__(self):
        self.calls = []

    def basic_publish(self, **kwargs):
        self.calls.append(kwargs)


def test_parse_xml_payload_valid():
    root = _parse_xml_payload(b"<identity_request><email>user@example.com</email></identity_request>")
    assert root.findtext("email") == "user@example.com"


def test_parse_xml_payload_rejects_oversized_payload():
    oversized = b"a" * (MAX_XML_PAYLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="Payload too large"):
        _parse_xml_payload(oversized)


def test_safe_error_message_hides_non_validation_details():
    assert _safe_error_message(RuntimeError("db password leaked")) == "Internal server error"
    assert _safe_error_message(ValueError("Invalid email")) == "Invalid email"


def test_publish_rpc_response_skips_when_no_reply_to():
    channel = DummyChannel()
    props = SimpleNamespace(reply_to=None, correlation_id="abc")

    _publish_rpc_response(channel, props, "<identity_response />")

    assert channel.calls == []


def test_build_ok_and_error_response_structure():
    dummy_user = SimpleNamespace(
        master_uuid="0195f9b6-eab7-7b0c-9ac5-f8f3e0af02d0",
        email="user@example.com",
        created_by="crm",
        created_at=datetime.now(timezone.utc),
    )

    ok_xml = _build_ok_response(dummy_user)
    error_xml = _build_error_response("NOT_FOUND", "User not found")

    assert "<status>ok</status>" in ok_xml
    assert "<email>user@example.com</email>" in ok_xml
    assert "<status>error</status>" in error_xml
    assert "<error_code>NOT_FOUND</error_code>" in error_xml
