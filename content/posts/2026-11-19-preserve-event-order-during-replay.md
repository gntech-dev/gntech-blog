---
title: "Preserve Event Order When Replaying a Failed Event"
description: "Use a per-stream sequence checkpoint to block later events behind a missing predecessor while independent streams continue."
date: 2026-11-19T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, operations, homelab]
keywords: [ordered event replay, PostgreSQL sequence checkpoint, event stream ordering]
summary: "Test a sequence gap, an independent stream, and duplicate delivery in a disposable PostgreSQL receiver."
cover:
  image: "/images/posts/ordered-event-replay/featured.webp"
  alt: "A hand positions a plain card beside two separate rows of cards on a warmly lit homelab workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A replayed event can arrive after events that depend on it. If a receiver applies an order update before the order creation, retrying the creation later cannot repair every possible side effect. Give each business stream a sequence and have the receiver apply only its next expected event.

This standalone lab extends the [GNTECH operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/). It uses PostgreSQL 16, Docker Compose v2 and Bash. A database function models the receiver's acceptance transaction. One stream has a rejected first event and an early second event. Another stream can still complete. All observations below are expected results for the lab.

## 1. Define the ordering boundary

Choose the smallest stream that needs ordering, such as one order or one account. Each stream starts at sequence 1. The producer must assign sequences consistently and publish every committed event required by that stream. A global identity column can have gaps and mixes unrelated work, so use a deliberate per-stream business sequence.

| Delivery | Receiver decision |
| --- | --- |
| Sequence equals checkpoint plus one | Apply the effect and advance the checkpoint in one transaction. |
| Sequence is ahead of that value | Return a gap and keep the checkpoint unchanged. |
| Sequence has already been applied | Check the stored event identity and return duplicate. |

Keep a blocked event available for investigation. Removing it from a sender queue does not give the receiver permission to skip its sequence. Stream recovery needs the missing event or an explicitly approved repair to the business state and checkpoint.

## 2. Prepare a disposable receiver

Create a fresh directory, generate a password and save the Compose file.

```bash
mkdir ordered-replay-lab
cd ordered-replay-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save as `compose.yaml`. The database has no published port.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
```

Start the service, then repeat the readiness check until PostgreSQL accepts connections. Keep the helper function in the same Bash shell.

```bash
docker compose -p ordered-replay-lab up -d
docker compose -p ordered-replay-lab exec -T db pg_isready -h 127.0.0.1

lab_sql() {
  docker compose -p ordered-replay-lab exec -T db \
    psql -XqAt -U lab -d lab -v ON_ERROR_STOP=1 "$@"
}
```

## 3. Lock the stream before checking its sequence

Save as `setup.sql`, then run `lab_sql -f - < setup.sql`. The fixture event table represents immutable incoming envelopes. The effect table represents receiver changes and preserves the accepted identity at each sequence.

```sql
CREATE TABLE stream_checkpoint (
    stream text PRIMARY KEY,
    last_applied bigint NOT NULL DEFAULT 0 CHECK (last_applied >= 0)
);
CREATE TABLE incoming_event (
    event_id text PRIMARY KEY,
    stream text NOT NULL REFERENCES stream_checkpoint(stream),
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    UNIQUE (stream, sequence_no)
);
CREATE TABLE rejection (event_id text PRIMARY KEY REFERENCES incoming_event);
CREATE TABLE applied_effect (
    stream text NOT NULL,
    sequence_no bigint NOT NULL,
    event_id text NOT NULL UNIQUE,
    PRIMARY KEY (stream, sequence_no)
);

INSERT INTO stream_checkpoint (stream) VALUES ('order-A'), ('order-B');
INSERT INTO incoming_event VALUES
    ('A1', 'order-A', 1),
    ('A2', 'order-A', 2),
    ('B1', 'order-B', 1);
INSERT INTO rejection VALUES ('A1');

CREATE FUNCTION accept_event(p_event_id text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    envelope incoming_event%ROWTYPE;
    checkpoint bigint;
    stored_id text;
BEGIN
    SELECT * INTO STRICT envelope FROM incoming_event WHERE event_id = p_event_id;
    SELECT last_applied INTO STRICT checkpoint FROM stream_checkpoint
    WHERE stream = envelope.stream FOR UPDATE;

    IF envelope.sequence_no <= checkpoint THEN
        SELECT event_id INTO STRICT stored_id FROM applied_effect
        WHERE stream = envelope.stream AND sequence_no = envelope.sequence_no;
        IF stored_id IS DISTINCT FROM envelope.event_id THEN
            RAISE EXCEPTION 'sequence identity conflict';
        END IF;
        RETURN 'duplicate';
    END IF;

    IF envelope.sequence_no <> checkpoint + 1 THEN
        RETURN 'gap';
    END IF;
    IF EXISTS (SELECT 1 FROM rejection WHERE event_id = envelope.event_id) THEN
        RETURN 'rejected';
    END IF;

    INSERT INTO applied_effect VALUES
        (envelope.stream, envelope.sequence_no, envelope.event_id);
    UPDATE stream_checkpoint SET last_applied = envelope.sequence_no
    WHERE stream = envelope.stream;
    RETURN 'accepted';
END;
$$;
```

Run calls at PostgreSQL's default Read Committed isolation. A second transaction for the same stream waits for the checkpoint row lock, then checks the updated checkpoint. Independent streams lock different rows. The effect and checkpoint commit together, so a failure before commit rolls both back. Unknown IDs and inconsistent receiver records raise an error.

## 4. Deliver out of order, then repair the cause

In a fresh lab, run this assertion block. The early A2 stays unapplied. B1 completes despite the problem in order-A.

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c "SELECT accept_event('A2')")" == gap ]]
  [[ "$(lab_sql -c "SELECT accept_event('B1')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT accept_event('A1')")" == rejected ]]
  [[ "$(lab_sql -c "SELECT last_applied FROM stream_checkpoint WHERE stream='order-A'")" == 0 ]]
  [[ "$(lab_sql -c 'SELECT count(*) FROM applied_effect')" == 1 ]]
  printf 'Gap held; independent stream completed\n'
)
```

The rejection row represents an unresolved receiver problem. Remove that cause, then replay the original event identities in sequence.

```bash
lab_sql -c "DELETE FROM rejection WHERE event_id='A1'"
(
  set -euo pipefail
  [[ "$(lab_sql -c "SELECT accept_event('A1')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT accept_event('A2')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT accept_event('A1')")" == duplicate ]]
  [[ "$(lab_sql -c 'SELECT count(*) FROM applied_effect')" == 3 ]]
  printf 'Replay completed with one effect per event\n'
)
lab_sql -c 'SELECT * FROM stream_checkpoint ORDER BY stream'
lab_sql -c 'SELECT * FROM applied_effect ORDER BY stream, sequence_no'
```

Expect order-A at checkpoint 2 and order-B at checkpoint 1. In a real receiver, compare the canonical payload or its digest on duplicate identity as well. This fixture stores only identity and sequence. Preserve the deduplication records for the supported replay window.

Track sequence gaps and blocked-stream age separately from total queue depth. A global backlog can fall while one business stream remains stuck. Record the missing sequence and event identity in logs, and give any repair action an audit record. For external effects, combine sequence enforcement with downstream idempotency because the remote acknowledgment and local commit have separate failure boundaries.

After recording results, remove the disposable project with `docker compose -p ordered-replay-lab down --volumes`.

## References

- [PostgreSQL 16 row locks](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
- [PostgreSQL 16 Read Committed behavior](https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED)
- [AWS transactional outbox guidance on ordering and duplicates](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
