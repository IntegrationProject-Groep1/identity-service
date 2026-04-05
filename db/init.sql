-- Identity Service database schema
-- The service also calls SQLAlchemy Base.metadata.create_all() on startup,
-- so this file documents the expected database shape for a fresh PostgreSQL database.

CREATE TABLE IF NOT EXISTS user_registry (
    master_uuid UUID PRIMARY KEY NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_registry_email ON user_registry (email);
CREATE INDEX IF NOT EXISTS idx_user_registry_created_by ON user_registry (created_by);
