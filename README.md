# Identity Service

Central Master UUID management microservice for the Integration Project.

## Overview

The Identity Service is the **single source of truth** for Master UUIDs across all systems in the Integration Project. It ensures that users created across different services (CRM, Facturatie, Kassa, Planning, etc.) are identified by a single consistent UUID.

## Architecture

- **Language**: Python 3.11
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **Messaging**: RabbitMQ (events publishing)
- **UUID Format**: UUID v7 (time-ordered)

## Features

- **Idempotent User Creation**: Multiple requests with the same email return the same UUID
- **Event Publishing**: Broadcasts `UserCreated` events via RabbitMQ
- **Email Lookup**: Fast lookup by email address
- **UUID Lookup**: Direct lookup by Master UUID

## API Endpoints

### Create User
```
POST /users
Content-Type: application/json

{
  "email": "user@example.com",
  "source_system": "crm"
}

Response (201):
{
  "master_uuid": "01890a5d-ac96-7ab2-80e2-4536629c90de",
  "email": "user@example.com",
  "created_by": "crm",
  "created_at": "2025-04-05T10:30:00+00:00"
}
```

### Get User by UUID
```
GET /users/{master_uuid}

Response (200):
{
  "master_uuid": "01890a5d-ac96-7ab2-80e2-4536629c90de",
  "email": "user@example.com",
  "created_by": "crm",
  "created_at": "2025-04-05T10:30:00+00:00"
}
```

### Get User by Email
```
GET /users/by-email/{email}

Response (200):
{
  "master_uuid": "01890a5d-ac96-7ab2-80e2-4536629c90de",
  "email": "user@example.com",
  "created_by": "crm",
  "created_at": "2025-04-05T10:30:00+00:00"
}
```

### Health Check
```
GET /health

Response (200):
{
  "status": "ok"
}
```

## RabbitMQ Integration

### Event Publishing

When a user is created, the service publishes a `UserCreated` event to the `user.events` fanout exchange:

```json
{
  "event": "UserCreated",
  "master_uuid": "01890a5d-ac96-7ab2-80e2-4536629c90de",
  "email": "user@example.com",
  "source_system": "crm",
  "timestamp": "2025-04-05T10:30:00+00:00"
}
```

**Exchange**: `user.events` (fanout, durable)
**Delivery Mode**: Persistent (mode=2)

## Environment Variables

See `.env.example` for a complete list:

```env
# Database
DB_HOST=postgres_identity
DB_PORT=5432
DB_NAME=identity_service
DB_USER=postgres
DB_PASSWORD=postgres

# RabbitMQ
RABBITMQ_HOST=rabbitmq_broker
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/
```

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

5. **Access API docs**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

## Docker Deployment

```bash
docker build -t identity-service:latest .

docker run -d \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e RABBITMQ_HOST=rabbitmq \
  -p 8000:8000 \
  identity-service:latest
```

## Integration with Other Services

Each service that needs to use Master UUIDs should:

1. **Add Consumer**: Listen to `user.events` exchange
2. **Store Master UUID**: Add `master_uuid` column to local user tables
3. **Migration Script**: Populate existing users by calling `POST /users` and `GET /users/by-email/{email}`

See individual service documentation for integration details.

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

(Add testing framework: pytest, httpx)

```bash
pytest tests/
```

## License

Proprietary - Integration Project 2025-2026
