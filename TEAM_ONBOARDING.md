# Team Onboarding Guide: Master UUID Integration

This guide is for teams integrating their service with the central `identity-service`.

## 1) Non-negotiable architecture rules

1. `identity-service` is the single source of truth for identities.
2. Only `identity-service` generates Master UUIDs.
3. Other services store replicated `master_uuid` values locally for lookup/performance.
4. All service-to-service communication is RabbitMQ only.
5. XML only for inter-service payloads (no JSON contracts).

## 2) RabbitMQ RPC contract to use

Request queues:

- `identity.user.create.request`
- `identity.user.lookup.email.request`
- `identity.user.lookup.uuid.request`

Every request must set:

- `reply_to`
- `correlation_id`

Create/get request XML:

```xml
<identity_request>
  <email>user@example.com</email>
  <source_system>your-service-name</source_system>
</identity_request>
```

Lookup by email request XML:

```xml
<identity_request>
  <email>user@example.com</email>
</identity_request>
```

Lookup by UUID request XML:

```xml
<identity_request>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
</identity_request>
```

Response XML:

```xml
<identity_response>
  <status>ok</status>
  <user>
    <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
    <email>user@example.com</email>
    <created_by>your-service-name</created_by>
    <created_at>2026-04-05T12:00:00+00:00</created_at>
  </user>
</identity_response>
```

## 3) RabbitMQ event contract (XML)

Exchange:
- name: `user.events`
- type: `fanout`
- durable: `true`

```xml
<user_event>
  <event>UserCreated</event>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
  <email>user@example.com</email>
  <source_system>facturatie</source_system>
  <timestamp>2026-04-05T12:00:00+00:00</timestamp>
</user_event>
```

Only `identity-service` creates `master_uuid` values.

## 4) What every team must implement

## 4.1 Local data model changes

- Add `master_uuid` in local user table/model.
- Add unique index on `master_uuid`.
- Keep `email` indexed and unique if possible.
- For new records, enforce `master_uuid` as required.

SQL example:

```sql
ALTER TABLE users ADD COLUMN master_uuid VARCHAR(36);
CREATE UNIQUE INDEX uq_users_master_uuid ON users(master_uuid);
CREATE INDEX idx_users_master_uuid ON users(master_uuid);
```

## 4.2 Event consumer

Each service must have its own queue:
- queue name: `<service-name>.user_created`
- durable: `true`

Required flow:
1. Declare exchange `user.events` durable fanout.
2. Declare queue `<service-name>.user_created` durable.
3. Bind queue to exchange.
4. On `UserCreated`, upsert local record by email and write `master_uuid`.
5. Ack only after DB write succeeds.

## 4.3 Conflict/upsert logic

Upsert by email must handle existing users:

- if user exists by email: update `master_uuid`
- if no user exists: create placeholder/local mapping record

SQL pattern:

```sql
INSERT INTO users(email, master_uuid)
VALUES (?, ?)
ON CONFLICT(email)
DO UPDATE SET master_uuid = EXCLUDED.master_uuid;
```

(Use equivalent syntax for your DB engine.)

## 4.4 Migration script (idempotent)

Purpose: backfill existing users.

Algorithm:
1. Select users where `master_uuid` is null.
2. For each email: publish XML request to `identity.user.create.request`.
3. Store returned `master_uuid` locally.
4. Continue on errors, report summary.
5. Safe to re-run.

## 5) Definition of done per team

A team is done only when all items are true:

- [ ] Local user model has `master_uuid`
- [ ] `master_uuid` unique + indexed
- [ ] Durable queue `<service>.user_created` consuming from `user.events`
- [ ] Event handling updates existing users by email
- [ ] Migration script exists and is rerunnable
- [ ] No local UUID generation in code

## 6) Quick verification checklist

1. Create test user via Identity Service.
2. Confirm `UserCreated` event appears in RabbitMQ.
3. Confirm your service queue receives event.
4. Confirm local DB row has expected `master_uuid`.
5. Re-send same email and verify UUID remains unchanged.

## 7) Common mistakes to avoid

- Generating UUIDs in service code.
- Non-durable queues or non-durable exchange declarations.
- Acking messages before DB writes.
- Not handling existing user by email conflict.
- One-off migration scripts that fail on second run.
- Using HTTP/REST between services for identity operations.
- Sending JSON payloads for inter-service identity contracts.

## 8) Team handoff template

When your team is done, share this minimal handoff:

- Service name:
- Queue name:
- User table/model updated:
- Migration script path:
- Evidence (logs/screenshots/queries):
  - event received
  - local row updated
  - idempotent rerun result

## 9) Frontend team implementation (Drupal/PHP)

For `IP-groep1-frontend`, implement the same contract with RabbitMQ + XML.

### Required queue/exchange setup

- Consume events from exchange: `user.events` (fanout, durable)
- Frontend queue: `frontend.user_created` (durable)
- For RPC responses, use a private reply queue (exclusive, auto-delete) per worker/request context

### Required data model change

Add `master_uuid` to frontend user storage (`users_field_data` or your custom user profile table):

- `master_uuid` unique + indexed
- For new registrations, ensure `master_uuid` is present before final user persistence

### Registration flow (frontend)

1. User submits registration form in frontend.
2. Frontend publishes XML request to `identity.user.create.request`.
3. Frontend waits for XML RPC response on `reply_to` queue.
4. Frontend persists local user with returned `master_uuid`.
5. Frontend consumer keeps listening to `frontend.user_created` for cross-system reconciliation.

### Frontend migration flow

1. Select frontend users with `master_uuid IS NULL`.
2. For each email, publish XML request to `identity.user.create.request`.
3. Persist returned `master_uuid` locally.
4. Repeat-safe: rerun script without duplicates.

### Frontend done checklist

- [ ] Queue `frontend.user_created` is durable and bound to `user.events`
- [ ] Frontend registration uses RabbitMQ XML RPC (not HTTP)
- [ ] Existing frontend users migrated idempotently
- [ ] `master_uuid` unique/indexed in frontend DB
- [ ] No JSON payloads and no REST calls for identity between services

For concrete XML and RPC examples (including PHP/Drupal pattern), see `RPC_EXAMPLES.md`.
