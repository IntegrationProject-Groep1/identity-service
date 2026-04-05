# RabbitMQ XML RPC Examples

This document provides copy-paste oriented examples for teams integrating with `identity-service`.

## 1) RabbitMQ topology

### Request queues (RPC)

- `identity.user.create.request`
- `identity.user.lookup.email.request`
- `identity.user.lookup.uuid.request`

### Event exchange

- Exchange: `user.events`
- Type: `fanout`
- Durable: `true`

### Service event queues

- CRM: `crm.user_created`
- Facturatie: `facturatie.user_created`
- Kassa: `kassa.user_created`
- Planning: `planning.user_created`
- Frontend: `frontend.user_created`

All queues must be durable.

## 2) XML request/response formats

### 2.1 Create/get user request

Publish to `identity.user.create.request`.

```xml
<identity_request>
  <email>user@example.com</email>
  <source_system>frontend</source_system>
</identity_request>
```

### 2.2 Lookup by email request

Publish to `identity.user.lookup.email.request`.

```xml
<identity_request>
  <email>user@example.com</email>
</identity_request>
```

### 2.3 Lookup by UUID request

Publish to `identity.user.lookup.uuid.request`.

```xml
<identity_request>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
</identity_request>
```

### 2.4 Success response

```xml
<identity_response>
  <status>ok</status>
  <user>
    <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
    <email>user@example.com</email>
    <created_by>frontend</created_by>
    <created_at>2026-04-05T12:00:00+00:00</created_at>
  </user>
</identity_response>
```

### 2.5 Error response

```xml
<identity_response>
  <status>error</status>
  <error_code>NOT_FOUND</error_code>
  <message>User not found</message>
</identity_response>
```

### 2.6 UserCreated event

Published by identity-service to `user.events`.

```xml
<user_event>
  <event>UserCreated</event>
  <master_uuid>01890a5d-ac96-7ab2-80e2-4536629c90de</master_uuid>
  <email>user@example.com</email>
  <source_system>frontend</source_system>
  <timestamp>2026-04-05T12:00:00+00:00</timestamp>
</user_event>
```

## 3) Frontend (Drupal/PHP) integration example

The frontend must never call identity endpoints over HTTP for inter-service communication.
Use RabbitMQ request/reply with XML.

### 3.1 PHP RPC request pattern (conceptual)

```php
<?php
use PhpAmqpLib\Connection\AMQPStreamConnection;
use PhpAmqpLib\Message\AMQPMessage;

$connection = new AMQPStreamConnection($host, $port, $user, $pass, '/');
$channel = $connection->channel();

// reply queue
list($replyQueue, ,) = $channel->queue_declare('', false, false, true, true);

$correlationId = bin2hex(random_bytes(16));
$responseBody = null;

$channel->basic_consume($replyQueue, '', false, true, false, false,
    function ($msg) use (&$responseBody, $correlationId) {
        if ($msg->get('correlation_id') === $correlationId) {
            $responseBody = $msg->body;
        }
    }
);

$xml = '<identity_request>'
     . '<email>user@example.com</email>'
     . '<source_system>frontend</source_system>'
     . '</identity_request>';

$request = new AMQPMessage($xml, [
    'content_type' => 'application/xml',
    'delivery_mode' => 2,
    'reply_to' => $replyQueue,
    'correlation_id' => $correlationId,
]);

$channel->basic_publish($request, '', 'identity.user.create.request');

$start = microtime(true);
while ($responseBody === null && (microtime(true) - $start) < 10) {
    $channel->wait(null, false, 1.0);
}

if ($responseBody === null) {
    throw new \RuntimeException('Identity RPC timeout');
}

$xmlResponse = simplexml_load_string($responseBody);
if ((string)$xmlResponse->status !== 'ok') {
    throw new \RuntimeException('Identity RPC failed: ' . (string)$xmlResponse->message);
}

$masterUuid = (string)$xmlResponse->user->master_uuid;
// Persist $masterUuid with local frontend user
```

### 3.2 Frontend event consumer pattern

```php
<?php
$channel->exchange_declare('user.events', 'fanout', false, true, false);
$channel->queue_declare('frontend.user_created', false, true, false, false);
$channel->queue_bind('frontend.user_created', 'user.events');

$channel->basic_consume('frontend.user_created', '', false, false, false, false,
    function ($msg) use ($channel) {
        $event = simplexml_load_string($msg->body);
        if ($event === false) {
            $msg->nack(false, false);
            return;
        }

        if ((string)$event->event !== 'UserCreated') {
            $msg->ack();
            return;
        }

        $email = (string)$event->email;
        $masterUuid = (string)$event->master_uuid;

        // Upsert local user by email, set master_uuid
        // ...

        $msg->ack();
    }
);
```

## 4) Migration pattern (all teams, including frontend)

1. Query users where `master_uuid` is null.
2. For each email, publish XML request to `identity.user.create.request`.
3. Wait for XML response and extract `<master_uuid>`.
4. Update local user with `master_uuid`.
5. Continue on error, report summary.
6. Re-run safely (idempotent behavior required).

## 5) Critical rules

- Only identity-service generates `master_uuid`.
- No inter-service HTTP/REST.
- No JSON contracts between services.
- Use durable queues/exchanges and persistent messages.
- Ack only after local DB write succeeds.
