# Identity Service

Central Master UUID management microservice for the Integration Project.

## Overview

The Identity Service is the **single source of truth** for Master UUIDs across all systems in the Integration Project. It ensures that users created across different services (CRM, Facturatie, Kassa, Planning, etc.) are identified by a single consistent UUID.

## Architecture

- **Language**: Python 3.11
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **Messaging**: RabbitMQ only (request/reply + event publishing)
- **UUID Format**: UUID v7 (time-ordered)
- **Serialization**: XML only (no JSON contracts)

## Features

- **Idempotent User Creation**: Multiple create requests with the same email return the same UUID
- **Event Publishing**: Broadcasts `UserCreated` via RabbitMQ fanout exchange
- **RabbitMQ RPC Support**: Create and lookup operations exposed through durable RabbitMQ queues
- **XML Contracts**: All inter-service payloads are XML

## Communication model (RabbitMQ only)

Inter-service communication must use RabbitMQ only.

### Request queues (RPC style)

- `identity.user.create.request`
- `identity.user.lookup.email.request`
- `identity.user.lookup.uuid.request`

Each request message must provide:
- `reply_to`
- `correlation_id`

### Event exchange

- Exchange: `user.events`
- Type: `fanout`
- Durable: `true`

### Health endpoint

`GET /health` exists for operational liveness checks only and is not part of service-to-service business communication.

## RabbitMQ Integration

### XML request examples

Create/get user request to `identity.user.create.request`:

```xml
<identity_request>
  <email>user@example.com</email>
  <source_system>crm</source_system>
</identity_request>
```

Lookup by email request to `identity.user.lookup.email.request`:

```xml
<identity_request>
  <email>user@example.com</email>
</identity_request>
```

Emails are normalized to trimmed lowercase before lookup, so teams may send canonical email addresses without worrying about casing differences.

Lookup by UUID request to `identity.user.lookup.uuid.request`:

```xml
<identity_request>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
</identity_request>
```

### XML response example

```xml
<identity_response>
  <status>ok</status>
  <user>
    <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
    <email>user@example.com</email>
    <created_by>crm</created_by>
    <created_at>2026-04-05T12:00:00+00:00</created_at>
  </user>
</identity_response>
```

### UserCreated event (XML)

When a user is created, the service publishes this XML event to `user.events`:

```xml
<user_event>
  <event>UserCreated</event>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
  <email>user@example.com</email>
  <source_system>crm</source_system>
  <timestamp>2026-04-05T12:00:00+00:00</timestamp>
</user_event>
```

**Exchange**: `user.events` (fanout, durable)
**Delivery Mode**: Persistent (mode=2)
**Content-Type**: `application/xml`

## Environment Variables

See `.env.example` for a complete list:

```env
# Database
DB_DRIVER=postgresql
DB_HOST=postgres_identity
DB_PORT=5432
DB_NAME=identity_service
DB_USER=postgres
DB_PASSWORD=postgres

# RabbitMQ
RABBITMQ_HOST=rabbitmq_broker
RABBITMQ_PORT=30000
RABBITMQ_USER=identity_rabbitmq
RABBITMQ_PASSWORD=change-me
RABBITMQ_VHOST=/

# Docker host mapping port (must be from Infra-approved range)
IDENTITY_HOST_PORT=30070
```

### GitHub configuration for deployment

Configure these in your GitHub repository before tagging a release:

- **Repository variables**
  - `RABBITMQ_HOST` = your RabbitMQ DNS name
  - `RABBITMQ_USER` = `identity_rabbitmq`
- **Repository secrets**
  - `RABBITMQ_PASSWORD` = your RabbitMQ password

## Database Schema

### Table: `user_registry`

| Column | Type | Constraints |
|--------|------|-------------|
| `master_uuid` | UUID | PRIMARY KEY |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL |
| `created_by` | VARCHAR(100) | NOT NULL |
| `created_at` | TIMESTAMP | DEFAULT NOW(), NOT NULL |

Indexes:
- `idx_user_registry_email`: Fast lookup by email
- `idx_user_registry_created_by`: Lookup by source system

## Local Development

1. **Setup Python environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure database**
   ```bash
   cp .env.example .env
   # Edit .env with your database credentials
   ```

3. **Run migrations**
   ```bash
   # Migrations run automatically on startup
   ```

4. **Start the service**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Verify health**
  - http://localhost:${IDENTITY_HOST_PORT:-30070}/health

## Docker Deployment

```bash
docker build -t identity-service:latest .

docker run -d \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=identity_service \
  -e DB_USER=postgres \
  -e DB_PASSWORD=your_secret_password \
  -e RABBITMQ_HOST=rabbitmq \
  -e RABBITMQ_PORT=5672 \
  -e RABBITMQ_USER=guest \
  -e RABBITMQ_PASSWORD=your_secret_password \
  -e RABBITMQ_VHOST=/ \
  -p 30070:8000 \
  identity-service:latest
```

> **Note**: Port `30070` is allocated from the project's port block (`30070–30100`). Adjust as needed per Infra approval.

## Integration with Other Services

Each service that needs to use Master UUIDs should:

1. **Add Consumer**: Listen to `user.events` exchange
2. **Store Master UUID**: Add `master_uuid` column to local user tables
3. **Migration Script**: Populate existing users via RabbitMQ XML RPC (`identity.user.create.request` / lookup queues)

Canonical email rule: downstream services should normalize emails with trim + lowercase before matching local rows or building reconciliation scripts.

## ⚠️ Mandatory for all other teams

Only `identity-service` is being shared to GitHub, so every team must implement using this contract.

### Source of truth rule

- `identity-service` is the **only** component that may generate a Master UUID.
- Other services may store a local copy of `master_uuid`, but must never generate one themselves.

### Required implementation pattern per service

1. Create/alter local user schema:
  - add `master_uuid`
  - set `UNIQUE` + index
  - enforce `NOT NULL` for new records
2. Add RabbitMQ consumer:
  - declare exchange `user.events` as `fanout` with `durable=true`
  - declare queue `<service-name>.user_created` with `durable=true`
  - bind queue to exchange
3. Handle incoming `UserCreated` events idempotently:
  - lookup local user by `email`
  - if exists: update `master_uuid`
  - if not exists: store in staging or create minimal local record
4. Create migration script (idempotent):
  - iterate existing local users by email
  - publish XML request to `identity.user.create.request`
  - store returned `master_uuid`

### Event contract (must match exactly)

`<...>` values are placeholders in this documentation. They are not literal values.

```xml
<user_event>
  <event>UserCreated</event>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
  <email>user@example.com</email>
  <source_system>crm</source_system>
  <timestamp>2026-04-05T12:00:00+00:00</timestamp>
</user_event>
```

Important: teams must not generate UUIDs locally. They only consume/store UUIDs from `identity-service`.

### Team checklist

- [ ] `master_uuid` field exists in local user model/table
- [ ] Unique index exists on `master_uuid`
- [ ] Consumer queue `<service>.user_created` is durable and bound to `user.events`
- [ ] Upsert on email conflict updates `master_uuid`
- [ ] Migration script is safe to run multiple times
- [ ] No local UUID generation remains in service code

For a copy-paste ready onboarding guide for teams, see `TEAM_ONBOARDING.md` in this same folder.
For concrete RabbitMQ XML request/reply examples (including Drupal/PHP frontend), see `RPC_EXAMPLES.md`.

## Error Handling

- **400 Bad Request**: Invalid UUID format or missing required fields
- **404 Not Found**: User not found
- **500 Internal Server Error**: Database or RabbitMQ connection failure

## Monitoring

- Health check: `GET /health`
- Logs: Check container/service logs for errors
- Database: Monitor connection pool and query performance
- RabbitMQ: Monitor exchange bindings and message throughput

## Testing

Unit tests are included under `tests/` and cover:

- input validation and idempotency in user creation
- safe XML payload parsing and payload-size guard
- RPC response behavior and safe error exposure

Run tests:

```bash
pytest tests/
```

## License

Proprietary - Integration Project 2025-2026
