---
title: "Test Concurrent Workers on a PostgreSQL Stream Checkpoint"
description: "Hold a receiver transaction open, verify another worker times out on the same stream, and prove an independent stream can still commit."
date: 2026-11-19T17:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, operations, homelab]
keywords: [PostgreSQL row lock lab, concurrent event workers, stream checkpoint contention]
summary: "A two-terminal drill for stream lock contention, bounded waiting, duplicate delivery, and transaction rollback."
cover:
  image: "/images/posts/stream-checkpoint-workers/featured.webp"
  alt: "Two mechanical arms hold brass keys beside one lock on a homelab desk, with a separate open lock nearby."
  caption: "AI-generated conceptual editorial artwork; not a database diagram."
  relative: false
---

A receiver can enforce event order in a single session and still behave badly when two workers arrive together. Test the transaction boundary deliberately: hold one stream's checkpoint lock, try a second delivery, and check whether unrelated work can finish.

This standalone operations lab complements the [GNTECH security and operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/). It focuses on contention and rollback rather than replay pacing or queue leasing. Use a disposable Linux host with Docker Engine, Compose v2, Bash and OpenSSL. The database is PostgreSQL 16; the commands below describe expected results, not a GNTECH production deployment or a runtime-verified benchmark.

## 1. Prepare a private database

In Terminal B, create a fresh directory and save the following files. Keep Terminal B's Bash shell open throughout the drill.

```bash
mkdir stream-lock-lab
cd stream-lock-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
cat > compose.yaml <<'YAML'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
YAML
docker compose -p stream-lock-lab up -d
```

There is no published database port. Repeat this readiness check until it succeeds, then define the SQL helper in the same shell.

```bash
docker compose -p stream-lock-lab exec -T db pg_isready -h 127.0.0.1
lab_sql() {
  docker compose -p stream-lock-lab exec -T db \
    psql -XqAt -U lab -d lab -v ON_ERROR_STOP=1 "$@"
}
```

## 2. Put the effect and checkpoint in one transaction

Save this as `setup.sql`. Each stream has its own checkpoint row. A stream's sequence starts at 1 and has no intentional gaps. An event identity belongs to one immutable stream, sequence and payload; the fixture omits payloads so the concurrency behavior is visible.

```sql
CREATE TABLE checkpoint (
    stream text PRIMARY KEY,
    last_applied bigint NOT NULL DEFAULT 0 CHECK (last_applied >= 0)
);
CREATE TABLE effect (
    stream text NOT NULL REFERENCES checkpoint,
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    event_id text NOT NULL UNIQUE,
    PRIMARY KEY (stream, sequence_no)
);
INSERT INTO checkpoint (stream) VALUES ('order-A'), ('order-B');

CREATE FUNCTION apply_event(p_stream text, p_seq bigint, p_id text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    current_seq bigint;
    accepted_id text;
BEGIN
    IF p_seq IS NULL OR p_seq < 1 OR p_id IS NULL OR p_id = '' THEN
        RAISE EXCEPTION 'invalid event envelope';
    END IF;
    SELECT last_applied INTO STRICT current_seq FROM checkpoint
    WHERE stream = p_stream FOR UPDATE;
    IF p_seq <= current_seq THEN
        SELECT event_id INTO STRICT accepted_id FROM effect
        WHERE stream = p_stream AND sequence_no = p_seq;
        IF accepted_id IS DISTINCT FROM p_id THEN
            RAISE EXCEPTION 'sequence identity conflict';
        END IF;
        RETURN 'duplicate';
    END IF;
    IF p_seq <> current_seq + 1 THEN
        RETURN 'gap';
    END IF;
    INSERT INTO effect VALUES (p_stream, p_seq, p_id);
    UPDATE checkpoint SET last_applied = p_seq WHERE stream = p_stream;
    RETURN 'accepted';
END;
$$;
```

Load the fixture once into the fresh database:

```bash
lab_sql -f - < setup.sql
```

The function obtains the checkpoint row lock before deciding what can be applied. Under PostgreSQL's default Read Committed isolation, a waiter obtains the updated row after the holder commits. The effect insert and checkpoint update share the caller's transaction. All writers must obey this protocol; the function does not protect against an administrator changing tables directly.

## 3. Hold order-A open in Terminal A

Open a second terminal in the same directory. Start an interactive SQL session:

```bash
docker compose -p stream-lock-lab exec db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1
```

At its SQL prompt run the following, then leave the session open **without committing**:

```sql
BEGIN ISOLATION LEVEL READ COMMITTED;
SET LOCAL idle_in_transaction_session_timeout = '10min';
SELECT apply_event('order-A', 1, 'A1');
```

Expect `accepted`. That return value is provisional: another session cannot yet see the effect, and the row lock remains held until the transaction ends. The ten-minute timeout limits an accidentally abandoned lab session. If it expires, restart the drill with a fresh database.

## 4. Prove independent progress and bounded waiting

Back in Terminal B, run these checks while Terminal A still holds its transaction. The first two SQL calls should finish without waiting for Terminal A.

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c "SELECT apply_event('order-B', 1, 'B1')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT count(*) FROM effect WHERE stream='order-A'")" == 0 ]]
  if lab_sql -v VERBOSITY=verbose \
      -c "SET lock_timeout='1s'; SELECT apply_event('order-A', 1, 'A1');" \
      > blocked.log 2>&1; then
    printf 'FAIL: same-stream call unexpectedly succeeded\n' >&2
    exit 1
  fi
  [[ "$(cat blocked.log)" == *55P03* ]]
  printf 'Independent stream committed; same-stream lock wait timed out\n'
)
cat blocked.log
```

The SQLSTATE `55P03` identifies the lock acquisition failure. A connection error or syntax error also produces a nonzero exit, which is why the assertion checks the code as well. The one-second `lock_timeout` applies to lock acquisition, not total query runtime. Use a separate `statement_timeout` when bounding total work.

The failed call does not advance order-A. Do not treat a timeout as a successful acknowledgment, create a new event identity, or skip to the next sequence. A worker should roll back its failed transaction, apply bounded backoff and retry the same envelope. This lab uses a new SQL session for each helper invocation, so a failed session is closed automatically.

## 5. Commit, retry, then test rollback

In Terminal A, release the first transaction:

```sql
COMMIT;
```

In Terminal B, the retried identity should now be a duplicate. The next event should apply once.

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c "SELECT apply_event('order-A', 1, 'A1')")" == duplicate ]]
  [[ "$(lab_sql -c "SELECT apply_event('order-A', 2, 'A2')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT last_applied FROM checkpoint WHERE stream='order-A'")" == 2 ]]
  [[ "$(lab_sql -c 'SELECT count(*) FROM effect')" == 3 ]]
  printf 'Committed identity was deduplicated; next sequence applied\n'
)
```

Now use Terminal A to apply a third event and deliberately abandon the transaction:

```sql
BEGIN;
SELECT apply_event('order-A', 3, 'A3');
ROLLBACK;
```

In Terminal B, verify that neither the effect nor its checkpoint survived that rollback. A fresh delivery can then apply A3.

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c "SELECT last_applied FROM checkpoint WHERE stream='order-A'")" == 2 ]]
  [[ "$(lab_sql -c "SELECT count(*) FROM effect WHERE event_id='A3'")" == 0 ]]
  [[ "$(lab_sql -c "SELECT apply_event('order-A', 3, 'A3')")" == accepted ]]
  [[ "$(lab_sql -c "SELECT last_applied FROM checkpoint WHERE stream='order-A'")" == 3 ]]
  [[ "$(lab_sql -c 'SELECT count(*) FROM effect')" == 4 ]]
  printf 'Rollback preserved consistency; retry committed\n'
)
```

| Observation | What it demonstrates |
| --- | --- |
| B1 commits while A1 remains open | Different checkpoint rows can progress independently in this fixture. |
| A1 retry returns SQLSTATE 55P03 while locked | A competing worker cannot bypass the stream lock. |
| A1 returns duplicate after commit | The checkpoint and accepted identity agree. |
| A3 disappears after rollback | Database effect and checkpoint share a transaction boundary. |

This is a controlled lock-contention test, not a throughput test or a proof that every receiver is safe. Real implementations also need canonical payload comparison, deduplication retention, producer sequence allocation, and a policy for missing events. Unique event identities can create additional contention if incorrectly reused across streams. Keep external HTTP calls outside the database lock where possible; their side effects cannot roll back with PostgreSQL. Design downstream idempotency separately. For operations that lock several streams, use a consistent lock order and handle deadlock errors by retrying the whole transaction.

## 6. Record evidence and clean up

Record `blocked.log`, checkpoint values, effect counts and any unexpected SQLSTATE. Investigate a missing timeout before accepting the drill: confirm Terminal A is still connected and has not committed, rolled back or exceeded its idle timeout. A failed assertion is a failed drill, not permission to proceed as though it passed.

Exit Terminal A with `\q`. Remove only this disposable Compose project:

```bash
docker compose -p stream-lock-lab down --volumes
```

## References

Official documentation reviewed November 19, 2026:

- [PostgreSQL 16 row locks and deadlocks](https://www.postgresql.org/docs/16/explicit-locking.html)
- [PostgreSQL 16 Read Committed behavior](https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED)
- [PostgreSQL 16 lock and session timeouts](https://www.postgresql.org/docs/16/runtime-config-client.html)
- [PostgreSQL 16 SQLSTATE error codes](https://www.postgresql.org/docs/16/errcodes-appendix.html)
