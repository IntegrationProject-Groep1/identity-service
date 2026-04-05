import logging
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models import UserRegistry
from rabbitmq_service import publish_user_created

logger = logging.getLogger(__name__)


def create_user(email: str, source_system: str, db: Session) -> UserRegistry:
    """
    Create a new user with a Master UUID.
    Idempotent: if email already exists, return existing user.
    """
    try:
        # Check if user already exists
        existing_user = db.query(UserRegistry).filter(
            UserRegistry.email == email
        ).first()

        if existing_user:
            logger.info(f"User with email {email} already exists")
            return existing_user

        # Generate UUID v7 (time-ordered)
        # Using uuid4() as base - in production, use a proper UUID v7 library
        master_uuid = UUID(int=uuid4().int)

        # Create new user
        new_user = UserRegistry(
            master_uuid=master_uuid,
            email=email,
            created_by=source_system,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(f"Created new user with email {email} and UUID {master_uuid}")

        # Publish event
        try:
            publish_user_created(master_uuid, email, source_system)
        except Exception as e:
            logger.error(f"Failed to publish event, but user was created: {e}")
            # Don't fail the user creation if event publishing fails

        return new_user

    except IntegrityError as e:
        db.rollback()
        # Race condition: another request created the same user
        existing_user = db.query(UserRegistry).filter(
            UserRegistry.email == email
        ).first()
        if existing_user:
            logger.info(f"User was created by another request: {email}")
            return existing_user
        raise


def get_user_by_uuid(master_uuid: UUID, db: Session) -> UserRegistry | None:
    """Retrieve a user by Master UUID."""
    return db.query(UserRegistry).filter(
        UserRegistry.master_uuid == master_uuid
    ).first()


def get_user_by_email(email: str, db: Session) -> UserRegistry | None:
    """Retrieve a user by email."""
    return db.query(UserRegistry).filter(
        UserRegistry.email == email
    ).first()
