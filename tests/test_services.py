import os

os.environ["DB_DRIVER"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from database import Base
from services import create_user, get_user_by_email


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_create_user_is_idempotent_and_normalizes_input(db_session, monkeypatch):
    monkeypatch.setattr("services.publish_user_created", lambda *args, **kwargs: None)

    first = create_user(" USER@EXAMPLE.COM ", " CRM ", db_session)
    second = create_user("user@example.com", "crm", db_session)

    assert first.master_uuid == second.master_uuid
    assert first.email == "user@example.com"
    assert first.created_by == "crm"


def test_create_user_rejects_invalid_email(db_session, monkeypatch):
    monkeypatch.setattr("services.publish_user_created", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="Invalid email"):
        create_user("not-an-email", "crm", db_session)


def test_create_user_rejects_invalid_source_system(db_session, monkeypatch):
    monkeypatch.setattr("services.publish_user_created", lambda *args, **kwargs: None)

    with pytest.raises(ValueError, match="Invalid source_system"):
        create_user("user@example.com", "CRM PROD", db_session)


def test_create_user_still_succeeds_when_event_publish_fails(db_session, monkeypatch):
    def _fail_publish(*args, **kwargs):
        raise RuntimeError("rabbit down")

    monkeypatch.setattr("services.publish_user_created", _fail_publish)

    user = create_user("user2@example.com", "crm", db_session)
    assert user.email == "user2@example.com"


def test_get_user_by_email_normalizes_input(db_session, monkeypatch):
    monkeypatch.setattr("services.publish_user_created", lambda *args, **kwargs: None)

    created = create_user("user3@example.com", "crm", db_session)
    found = get_user_by_email(" USER3@EXAMPLE.COM ", db_session)

    assert found is not None
    assert found.master_uuid == created.master_uuid
    assert found.email == "user3@example.com"


def test_get_user_by_email_rejects_invalid_email(db_session):
    with pytest.raises(ValueError, match="Invalid email"):
        get_user_by_email("not-an-email", db_session)
