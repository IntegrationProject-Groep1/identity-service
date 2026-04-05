from sqlalchemy import Column, String, DateTime, Index, Uuid, text
from sqlalchemy.sql import func
from database import Base
from uuid import UUID
from datetime import datetime


class UserRegistry(Base):
    """Central user registry with Master UUIDs."""
    __tablename__ = "user_registry"

    master_uuid = Column(Uuid(as_uuid=True), primary_key=True, nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    created_by = Column(String(100), nullable=False)  # source_system name
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_user_registry_email", "email"),
        Index("idx_user_registry_created_by", "created_by"),
    )

    def to_dict(self):
        return {
            "master_uuid": str(self.master_uuid),
            "email": self.email,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
