---
title: "Quarantine a Failing Outbox Event and Keep the Queue Moving"
description: "Bound retries for a rejected PostgreSQL outbox event, preserve its failure history, and verify that a healthy event still completes."
date: 2026-11-18T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, docker, homelab]
keywords: [outbox quarantine, poison message, bounded retries, PostgreSQL queue]
summary: "Use a disposable queue to test delayed retries, quarantine after three failures, and a controlled release after fixing the receiver."
cover:
  image: "/images/posts/outbox-quarantine/featured.webp"
  alt: "An amber folder sits apart from white cards in trays beside a homelab server."
  caption: "AI-generated editorial artwork."
  relative: false
---

An event that always fails can consume the worker's attention while useful work waits behind it. Give retries a limit, keep the failed event available for investigation, and verify that unrelated events still complete.

This companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) uses PostgreSQL 16 and Docker Compose v2. A database function simulates a receiver that accepts one event type and rejects another. It processes the receiver effect and queue state in the same database transaction. For a remote receiver, use delivery leases and receiver-side deduplication as part of the worker design.

The lab allows independent events to pass each other. Use it for work whose business rules allow that ordering. If later events depend on the failed event, pause that sequence or message group while the operator investigates.

## 1. Create the disposable project

Generate a lab password in a fresh directory and save the Compose configuration.

```bash
mkdir outbox-quarantine-lab
cd outbox-quarantine-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save as `compose.yaml`. All SQL uses the container's local socket.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
```

Start PostgreSQL and repeat its readiness check until it accepts TCP connections. Define the Bash helper for the remaining steps.

```bash
docker compose -p outbox-quarantine-lab up -d
docker compose -p outbox-quarantine-lab exec -T db pg_isready -h 127.0.0.1

lab_sql() {
  docker compose -p outbox-quarantine-lab exec -T db \
    psql -X -qAt -U lab -d lab -v ON_ERROR_STOP=1 "$@"
}
```

## 2. Keep failure history with the event

Save as `setup.sql`, then run `lab_sql -f - < setup.sql`. The two fixture rows represent independent work. The first has a type that the simulated receiver does not support yet.

```sql
CREATE TABLE accepted_kind (kind text PRIMARY KEY);
INSERT INTO accepted_kind VALUES ('known');

CREATE TABLE outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL,
    failures integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    quarantined_at timestamptz,
    sent_at timestamptz
);
CREATE TABLE failure_log (
    event_id bigint NOT NULL REFERENCES outbox(id),
    failed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    reason text NOT NULL
);
CREATE TABLE receiver_effect (event_id bigint PRIMARY KEY);

INSERT INTO outbox (kind) VALUES ('legacy'), ('known');

CREATE FUNCTION process_one() RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    event outbox%ROWTYPE;
BEGIN
    SELECT * INTO event FROM outbox
    WHERE sent_at IS NULL AND quarantined_at IS NULL
      AND next_attempt_at <= clock_timestamp()
    ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF NOT FOUND THEN
        RETURN 'idle';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM accepted_kind WHERE kind = event.kind) THEN
        INSERT INTO failure_log (event_id, reason)
        VALUES (event.id, 'unsupported kind');
        UPDATE outbox
        SET failures = failures + 1,
            next_attempt_at = clock_timestamp() + interval '2 seconds',
            quarantined_at = CASE WHEN failures + 1 >= 3
                                  THEN clock_timestamp() ELSE NULL END
        WHERE id = event.id;
        RETURN format('rejected %s', event.id);
    END IF;

    INSERT INTO receiver_effect VALUES (event.id) ON CONFLICT DO NOTHING;
    UPDATE outbox SET sent_at = clock_timestamp() WHERE id = event.id;
    RETURN format('completed %s', event.id);
END;
$$;
```

The failure counter measures observed rejections. The two-second retry delay makes the fixture quick to run. Choose production delays and limits from the failure type and expected recovery window. Record a bounded error category and keep sensitive payloads out of ordinary logs.

This example uses an explicit validation result. An unexpected SQL error aborts the call, so the queue state and receiver effect roll back together. If you catch SQL exceptions in a real worker, make sure the failure record is committed after the failed work has rolled back.

## 3. Prove that healthy work passes the rejected event

Run each call in autocommit through the helper. The sleeps make the rejected event eligible again.

```bash
lab_sql -c 'SELECT process_one()'
lab_sql -c 'SELECT process_one()'
sleep 3
lab_sql -c 'SELECT process_one()'
sleep 3
lab_sql -c 'SELECT process_one()'
lab_sql -c 'SELECT process_one()'

lab_sql -c 'SELECT id, failures, quarantined_at IS NOT NULL, sent_at IS NOT NULL
            FROM outbox ORDER BY id'
lab_sql -c 'SELECT event_id, count(*) FROM failure_log GROUP BY event_id'
lab_sql -c 'TABLE receiver_effect'
```

| Check | Expected result on a fresh lab |
| --- | --- |
| First two calls | Reject event 1, then complete event 2. |
| Third and fourth calls | Reject event 1 twice more. |
| Fifth call | Return idle because event 1 is quarantined. |
| Queue state | Event 1 has three failures, quarantine true and sent false. Event 2 has sent true. |
| Evidence | Three failure records for event 1. The receiver effect contains only event 2. |

Save the failure records before deciding whether to release the event. Also count quarantined rows in monitoring. Otherwise, a pending-age query that excludes quarantine could become quiet while failed work still needs attention.

## 4. Fix the cause before releasing the event

For this lab, update the receiver's supported types and release only the known quarantined row. Keep its ID and failure history intact.

```bash
lab_sql -f - <<'SQL'
BEGIN;
INSERT INTO accepted_kind VALUES ('legacy');
UPDATE outbox
SET quarantined_at = NULL, next_attempt_at = clock_timestamp()
WHERE id = 1 AND quarantined_at IS NOT NULL AND sent_at IS NULL;
COMMIT;
SQL

lab_sql -c 'SELECT process_one()'
lab_sql -c 'SELECT id, failures, sent_at IS NOT NULL FROM outbox ORDER BY id'
lab_sql -c 'TABLE receiver_effect'
```

Expect event 1 to complete with its three historical failures still recorded, and one receiver-effect row per event. A further rejection after release would quarantine it again because the lifetime failure limit is already reached. A production release policy should state whether an operator grants a new retry budget and record who approved that decision.

When applying this pattern to a real service, make release an audited action, limit how quickly work returns to the queue, and observe the receiver after replay. Clean up the disposable project with `docker compose -p outbox-quarantine-lab down --volumes`.

## References

- [PostgreSQL 16 SELECT and SKIP LOCKED](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [PostgreSQL 16 transaction behavior](https://www.postgresql.org/docs/16/tutorial-transactions.html)
- [AWS dead-letter queue and retry guidance](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)
