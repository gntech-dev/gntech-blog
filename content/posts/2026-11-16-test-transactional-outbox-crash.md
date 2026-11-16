---
title: "Test a Transactional Outbox After the Worker Crashes"
description: "Reproduce a crash after delivery and verify that the consumer applies a retried event only once."
date: 2026-11-16T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, docker, homelab]
keywords: [transactional outbox, idempotent consumer, PostgreSQL event delivery]
summary: "Use two disposable PostgreSQL databases to see what happens when a worker dies after delivery but before acknowledgment."
cover:
  image: "/images/posts/transactional-outbox-crash/featured.png"
  alt: "Two small server appliances and a paper work order on a warmly lit workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A worker delivers an event, then exits before marking it as sent. The receiver has already changed its database. When the worker runs again, it still sees a pending event and delivers it a second time. This drill checks both sides of that failure: the event stays available for retry, and the receiver applies its effect once.

The [GNTECH container platform guide](/posts/2026-11-04-gntech-infrastructure-part-09-docker-traefik/) covers deployment and persistent storage. This standalone lab uses PostgreSQL 16 and Docker Compose v2 to exercise delivery between two databases. Bash takes the place of a worker, and the receiver's SQL commit takes the place of a successful delivery response. The databases share a disposable server but use separate transactions. The outputs below are expected observations.

## 1. Create a sender and receiver

In a new directory, generate a disposable password and save this configuration as `compose.yaml`. Keep the database port private.

```bash
mkdir outbox-crash-lab
cd outbox-crash-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: lab
      POSTGRES_DB: sender
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a disposable lab password}"
```

Start the service. Repeat the readiness command until PostgreSQL accepts TCP connections, then create the tables.

```bash
docker compose -p outbox-crash-lab up -d
docker compose -p outbox-crash-lab exec -T db pg_isready -h 127.0.0.1

lab_sql() {
  docker compose -p outbox-crash-lab exec -T db \
    psql -X -U lab -v ON_ERROR_STOP=1 "$@"
}

lab_sql -d sender -f - <<'SQL'
CREATE DATABASE receiver;

CREATE TABLE work_order (
    id bigint PRIMARY KEY,
    title text NOT NULL
);
CREATE TABLE outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES work_order(id),
    sent_at timestamptz
);

BEGIN;
INSERT INTO work_order VALUES (42, 'Inspect lab backup');
INSERT INTO outbox (order_id) VALUES (42);
COMMIT;
SQL

lab_sql -d receiver -f - <<'SQL'
CREATE TABLE processed_event (id bigint PRIMARY KEY);
CREATE TABLE dispatch_tally (
    order_id bigint PRIMARY KEY,
    dispatches integer NOT NULL
);
SQL
```

The sender creates the work order and pending event together. If either write fails in that transaction, both roll back. The receiver keeps a separate record of each event ID it accepted. In a real receiver that handles more than one producer, use a globally unique event ID or include the producer in the uniqueness constraint.

## 2. Stop between delivery and acknowledgment

Save the following as `worker.sh`. Run a single worker at a time in this lab. It reads one pending event, delivers it to the receiver, and then marks it sent. The optional exit happens after the receiver's transaction commits.

```bash
#!/usr/bin/env bash
set -euo pipefail

sql() {
  docker compose -p outbox-crash-lab exec -T db \
    psql -X -U lab -v ON_ERROR_STOP=1 "$@"
}

pending="$(sql -d sender -At -F '|' -c \
  'SELECT id, order_id FROM outbox WHERE sent_at IS NULL ORDER BY id LIMIT 1')"
if [[ -z "$pending" ]]; then
  printf '%s\n' 'No pending event'
  exit 0
fi
IFS='|' read -r event_id order_id <<< "$pending"
[[ "$event_id" =~ ^[1-9][0-9]*$ && "$order_id" =~ ^[1-9][0-9]*$ ]]

sql -d receiver -v event="$event_id" -v order_id="$order_id" -f - <<'SQL'
BEGIN;
WITH accepted AS (
    INSERT INTO processed_event VALUES (:'event'::bigint)
    ON CONFLICT (id) DO NOTHING
    RETURNING id
)
INSERT INTO dispatch_tally (order_id, dispatches)
SELECT :'order_id'::bigint, 1 FROM accepted
ON CONFLICT (order_id) DO UPDATE
SET dispatches = dispatch_tally.dispatches + 1;
COMMIT;
SQL
printf 'Receiver acknowledged event %s\n' "$event_id"
if [[ "${CRASH_AFTER_DELIVERY:-0}" == 1 ]]; then
  exit 75
fi

sql -d sender -v event="$event_id" -f - <<'SQL'
UPDATE outbox SET sent_at = clock_timestamp()
WHERE id = :'event'::bigint AND sent_at IS NULL;
SQL
```

The receiver inserts its event record and applies the effect in one transaction. On replay, the conflicting insert returns no row, so the tally has nothing to increment. If the transaction had failed midway, the event record would also roll back and a retry could still apply the effect.

## 3. Verify the replay

```bash
status=0
CRASH_AFTER_DELIVERY=1 bash worker.sh || status=$?
test "$status" -eq 75
lab_sql -d sender -c 'SELECT id, sent_at IS NULL AS pending FROM outbox'
lab_sql -d receiver -c 'TABLE dispatch_tally'

bash worker.sh
lab_sql -d sender -c 'SELECT id, sent_at IS NULL AS pending FROM outbox'
lab_sql -d receiver -c 'TABLE dispatch_tally'
bash worker.sh
```

| Observation | Expected result |
| --- | --- |
| First run with forced exit | Sender still shows one pending event. Receiver shows one dispatch for order 42. |
| Second run | The same event ID reaches the receiver. Sender marks it sent. Receiver still shows one dispatch. |
| Third run | No pending event remains. |

If the first run never prints the receiver acknowledgment, inspect the database error before treating it as the simulated crash. If the tally increases on replay, check that the worker reused the event ID and that the receiver applied the effect only when its deduplication insert returned a row.

A real multi-worker design needs a claim or lease, an acknowledgment timeout, and a retry policy. Keep deduplication records for at least the supported replay window. If the effect is an external API call, use a stable downstream idempotency key when the API supports it. This lab demonstrates repeated delivery with one database effect. Clean up the disposable project with `docker compose -p outbox-crash-lab down --volumes`.

## References

- [AWS transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [PostgreSQL 16 INSERT and conflict handling](https://www.postgresql.org/docs/16/sql-insert.html)
- [PostgreSQL 16 transactions](https://www.postgresql.org/docs/16/tutorial-transactions.html)
