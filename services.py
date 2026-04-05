import logging
import re
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid_utils import uuid7
from models import UserRegistry
from rabbitmq_service import publish_user_created

logger = logging.getLogger(__name__)

EMAIL_MAX_LENGTH = 255
SOURCE_SYSTEM_MAX_LENGTH = 100
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SOURCE_SYSTEM_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{1,99}$")


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("Invalid email")
    if len(normalized) > EMAIL_MAX_LENGTH:
        raise ValueError("Invalid email")
    if not EMAIL_REGEX.fullmatch(normalized):
        raise ValueError("Invalid email")
    return normalized


def _validate_source_system(source_system: str) -> str:
    normalized = source_system.strip().lower()
    if not normalized:
        raise ValueError("Invalid source_system")
    if len(normalized) > SOURCE_SYSTEM_MAX_LENGTH:
        raise ValueError("Invalid source_system")
    if not SOURCE_SYSTEM_REGEX.fullmatch(normalized):
        raise ValueError("Invalid source_system")
    return normalized


def create_user(email: str, source_system: str, db: Session) -> UserRegistry:
    """
    Create a new user with a Master UUID.
    Idempotent: if email already exists, return existing user.
    """
    normalized_email = _validate_email(email)
    normalized_source_system = _validate_source_system(source_system)

    try:
        # Check if user already exists
        existing_user = db.query(UserRegistry).filter(
            UserRegistry.email == normalized_email
        ).first()

        if existing_user:
            logger.info(f"User with email {normalized_email} already exists")
            return existing_user

        # Generate UUID v7 (time-ordered)
        generated_uuid = uuid7()
        master_uuid = generated_uuid if isinstance(generated_uuid, UUID) else UUID(str(generated_uuid))

        # Create new user
        new_user = UserRegistry(
            master_uuid=master_uuid,
            email=normalized_email,
            created_by=normalized_source_system,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(f"Created new user with email {normalized_email} and UUID {master_uuid}")

        # Publish event
        try:
            publish_user_created(master_uuid, normalized_email, normalized_source_system)
        except Exception as e:
            logger.error(f"Failed to publish event, but user was created: {e}")
            # Don't fail the user creation if event publishing fails

        return new_user

    except IntegrityError as e:
        db.rollback()
        # Race condition: another request created the same user
        existing_user = db.query(UserRegistry).filter(
            UserRegistry.email == normalized_email
        ).first()
        if existing_user:
            logger.info(f"User was created by another request: {normalized_email}")
            return existing_user
        raise


def get_user_by_uuid(master_uuid: UUID, db: Session) -> UserRegistry | None:
    """Retrieve a user by Master UUID."""
    return db.query(UserRegistry).filter(
        UserRegistry.master_uuid == master_uuid
    ).first()


def get_user_by_email(email: str, db: Session) -> UserRegistry | None:
    """Retrieve a user by email."""
    normalized_email = _validate_email(email)
    return db.query(UserRegistry).filter(
        UserRegistry.email == normalized_email
    ).first()
