---
title: "Replay Quarantined Events at a Controlled Rate"
description: "Replay an approved PostgreSQL event list one item at a time and pause the batch when a receiver rejects an event."
date: 2026-11-18T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, docker, operations]
keywords: [outbox replay, quarantine recovery, dead letter redrive, controlled event replay]
summary: "Use a small reviewed batch, keep stable event IDs, and test that replay stops when receiver errors return."
cover:
  image: "/images/posts/outbox-controlled-replay/featured.webp"
  alt: "A hand moves a work card between trays beside a timer and a homelab server."
  caption: "AI-generated editorial artwork."
  relative: false
---

After fixing a receiver, releasing every failed event at once can recreate the overload that caused the incident. Start with a small approved list, pace its delivery, and stop when errors return. Keep an audit trail so an operator can see what completed before the pause.

This standalone companion to [the GNTECH operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/) uses PostgreSQL 16, Docker Compose v2 and Bash. A SQL function simulates delivery and acknowledgment in one database transaction. The receiver rejects the second fixture event so you can verify the pause before allowing the rest of the batch through.

## 1. Create the disposable lab

In a fresh directory, generate a lab password and save the configuration.

```bash
mkdir controlled-replay-lab
cd controlled-replay-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save as `compose.yaml`.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
```

Start the service, then repeat the readiness check until it accepts TCP connections.

```bash
docker compose -p controlled-replay-lab up -d
docker compose -p controlled-replay-lab exec -T db pg_isready -h 127.0.0.1
```

## 2. Freeze the approved replay list

Save as `setup.sql`. The batch contains three known quarantined IDs. New events added later stay outside this replay list.

```sql
CREATE TABLE event (
    id bigint PRIMARY KEY,
    quarantined boolean NOT NULL DEFAULT true,
    sent_at timestamptz
);
CREATE TABLE replay_item (
    event_id bigint PRIMARY KEY REFERENCES event(id)
);
CREATE TABLE replay_control (
    id integer PRIMARY KEY CHECK (id = 1),
    paused boolean NOT NULL
);
CREATE TABLE receiver_rejection (event_id bigint PRIMARY KEY);
CREATE TABLE receiver_effect (event_id bigint PRIMARY KEY);
CREATE TABLE replay_log (
    event_id bigint NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    outcome text NOT NULL
);

INSERT INTO event (id) VALUES (1), (2), (3);
INSERT INTO replay_item VALUES (1), (2), (3);
INSERT INTO replay_control VALUES (1, false);
INSERT INTO receiver_rejection VALUES (2);

CREATE FUNCTION replay_one() RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    stopped boolean;
    chosen bigint;
BEGIN
    SELECT paused INTO STRICT stopped FROM replay_control WHERE id = 1 FOR UPDATE;
    IF stopped THEN
        RETURN 'paused';
    END IF;

    SELECT e.id INTO chosen
    FROM replay_item AS r JOIN event AS e ON e.id = r.event_id
    WHERE e.quarantined AND e.sent_at IS NULL
    ORDER BY e.id LIMIT 1 FOR UPDATE OF e;
    IF NOT FOUND THEN
        RETURN 'done';
    END IF;

    IF EXISTS (SELECT 1 FROM receiver_rejection WHERE event_id = chosen) THEN
        INSERT INTO replay_log VALUES (chosen, clock_timestamp(), 'rejected');
        UPDATE replay_control SET paused = true WHERE id = 1;
        RETURN 'paused';
    END IF;

    INSERT INTO receiver_effect VALUES (chosen) ON CONFLICT DO NOTHING;
    UPDATE event SET quarantined = false, sent_at = clock_timestamp()
    WHERE id = chosen;
    INSERT INTO replay_log VALUES (chosen, clock_timestamp(), 'accepted');
    RETURN format('accepted %s', chosen);
END;
$$;
```

The control row serializes state changes and makes the pause persistent. The receiver effect keeps the original event ID as its deduplication key. Run this with one coordinator. The pacing loop below is a limit for that one process. Additional callers would need a shared rate budget.

## 3. Pace one attempt at a time

Save as `replay.sh`. Each call commits before the two-second delay. The script exits when the database pauses the batch or when the approved work is complete.

```bash
#!/usr/bin/env bash
set -euo pipefail

while true; do
  outcome="$(docker compose -p controlled-replay-lab exec -T db \
    psql -XqAt -U lab -d lab -v ON_ERROR_STOP=1 -c 'SELECT replay_one()')"
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$outcome"
  case "$outcome" in
    accepted\ *) sleep 2 ;;
    paused) exit 2 ;;
    done) exit 0 ;;
    *) printf 'Unexpected replay result\n' >&2; exit 1 ;;
  esac
done
```

Initialize the schema, review the manifest, and run the first pass.

```bash
docker compose -p controlled-replay-lab exec -T db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 -f - < setup.sql
docker compose -p controlled-replay-lab exec -T db \
  psql -X -U lab -d lab -c 'TABLE replay_item'

status=0
bash replay.sh || status=$?
test "$status" -eq 2

docker compose -p controlled-replay-lab exec -T db \
  psql -X -U lab -d lab -c 'TABLE replay_log' -c 'TABLE event'
```

Expect event 1 accepted, event 2 rejected, and event 3 untouched. A second run should return paused immediately. The log preserves event 2's rejection, while the event stays quarantined.

## 4. Inspect the rejection before resuming

The fixture's rejection row stands in for an unresolved receiver problem. Remove only that cause and resume the same approved batch.

```bash
docker compose -p controlled-replay-lab exec -T db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 -f - <<'SQL'
BEGIN;
DELETE FROM receiver_rejection WHERE event_id = 2;
UPDATE replay_control SET paused = false WHERE id = 1;
COMMIT;
SQL
bash replay.sh

docker compose -p controlled-replay-lab exec -T db \
  psql -X -U lab -d lab -c 'TABLE receiver_effect' \
  -c 'SELECT event_id, outcome, observed_at FROM replay_log ORDER BY observed_at'
```

Expect one receiver-effect row for each ID. The log should contain three accepted attempts and the earlier rejection. Compare the accepted timestamps to the pacing interval. A completed event remains outside later polls, so restarting the script continues with unfinished work.

For a real receiver, choose a starting rate that leaves capacity for new work. Watch receiver error rate, latency and pending-event age during replay. Pause on a sustained increase in errors or latency, investigate, then resume deliberately. Preserve event identity, payload and the original failure history. If a replay changes payload meaning, define a new operation and review its relationship to any prior delivery.

An external call introduces a gap between receiver acceptance and recording acknowledgment. Use a receiver idempotency key and expiring delivery claims to handle a worker that stops in that gap. Record the approved batch, operator, stop conditions and completion evidence in the runbook. After saving lab results, remove the disposable project with `docker compose -p controlled-replay-lab down --volumes`.

## References

- [AWS dead-letter queue redrive and velocity controls](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html)
- [PostgreSQL 16 row locks](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
- [PostgreSQL 16 transactions](https://www.postgresql.org/docs/16/tutorial-transactions.html)
