---
title: "Reclaim an Expired PostgreSQL Outbox Lease"
description: "Use two workers to check that an expired delivery lease can be reclaimed and that the original worker can no longer acknowledge it."
date: 2026-11-17T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, docker, homelab]
keywords: [PostgreSQL outbox lease, SKIP LOCKED, stale acknowledgment, fencing token]
summary: "Reproduce a stalled worker and verify that only the current lease can mark an event delivered."
cover:
  image: "/images/posts/postgres-outbox-leases/featured.webp"
  alt: "Two small servers and a timer on a warmly lit homelab workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A worker claims an event, then stops making progress. If the claim never expires, nobody else can deliver it. If the lease can expire, another worker can take over, but the first worker might resume and try to acknowledge the event using an old claim. This drill checks that the database rejects that stale acknowledgment.

This lab uses PostgreSQL 16, Docker Compose v2 and Bash. The worker labels identify the two roles in the exercise. Both connect through the same disposable database account. The lab checks the claim and acknowledgment state in PostgreSQL. A real receiver still needs to deduplicate deliveries by the stable event ID.

## 1. Create an isolated queue

Create a fresh project and use a generated password. The database port stays private.

```bash
mkdir outbox-lease-lab
cd outbox-lease-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save this as `compose.yaml`.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lease_lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a disposable password}"
```

Start the service, then repeat the readiness check until the server accepts TCP connections.

```bash
docker compose -p outbox-lease-lab up -d
docker compose -p outbox-lease-lab exec -T db pg_isready -h 127.0.0.1
```

Keep the following shell function available throughout the drill.

```bash
lab_sql() {
  docker compose -p outbox-lease-lab exec -T db \
    psql -X -qAt -U lab -d lease_lab -v ON_ERROR_STOP=1 "$@"
}

lab_sql -f - <<'SQL'
CREATE TABLE outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payload text NOT NULL,
    lease_owner text,
    lease_until timestamptz,
    claim_version bigint NOT NULL DEFAULT 0,
    sent_at timestamptz
);

INSERT INTO outbox (payload) VALUES ('inspect lab backup');
SQL
```

## 2. Claim in one statement

Save this as `claim.sql`. PostgreSQL locks the selected row for the statement, skips rows already locked by other transactions, and records the lease before releasing the lock. The claim version increments every time a worker takes the row.

```sql
WITH candidate AS (
    SELECT id
    FROM outbox
    WHERE sent_at IS NULL
      AND (lease_until IS NULL OR lease_until <= clock_timestamp())
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE outbox AS event
SET lease_owner = :'worker',
    lease_until = clock_timestamp() + make_interval(secs => :'lease_seconds'::integer),
    claim_version = event.claim_version + 1
FROM candidate
WHERE event.id = candidate.id
RETURNING event.id, event.claim_version;
```

Run the statement in autocommit as shown below. Commit the claim before delivering the event so a remote call does not hold a database transaction open. Preserve the returned ID and version together. An empty response means no row was claimed during that poll.

## 3. Acknowledge only with a current claim

Save this as `ack.sql`. In a real worker, run it after the receiver accepts the event.

```sql
UPDATE outbox
SET sent_at = clock_timestamp(), lease_owner = NULL, lease_until = NULL
WHERE id = :'event_id'::bigint
  AND sent_at IS NULL
  AND lease_owner = :'worker'
  AND claim_version = :'version'::bigint
  AND lease_until > clock_timestamp()
RETURNING id;
```

The version check matters even if worker names get reused. If the statement returns no row, the worker no longer has authority to acknowledge that claim. Treat the event ID as stable across attempts and use the version only for ownership checks.

## 4. Stall the first worker and replay the claim

Use a fresh lab instance. These commands verify each result before continuing. The second worker first polls while the lease is active, then claims again after the database clock passes the lease's expiry.

```bash
(
  set -euo pipefail
  first="$(lab_sql -v worker=A -v lease_seconds=15 -f - < claim.sql)"
  [[ "$first" == '1|1' ]]
  early="$(lab_sql -v worker=B -v lease_seconds=120 -f - < claim.sql)"
  [[ -z "$early" ]]

  sleep 16
  second="$(lab_sql -v worker=B -v lease_seconds=120 -f - < claim.sql)"
  [[ "$second" == '1|2' ]]

  stale="$(lab_sql -v worker=A -v event_id=1 -v version=1 -f - < ack.sql)"
  [[ -z "$stale" ]]

  current="$(lab_sql -v worker=B -v event_id=1 -v version=2 -f - < ack.sql)"
  [[ "$current" == '1' ]]
  final="$(lab_sql -c 'SELECT id, claim_version, sent_at IS NOT NULL FROM outbox')"
  [[ "$final" == '1|2|t' ]]
  printf 'Reclaimed event 1 and rejected the stale acknowledgment\n'
)
```

If the early poll returns a row, check whether the first lease expired before the second command reached PostgreSQL. Increase both the first lease and the sleep on a slow lab host. Inspect the stored state to distinguish timing from an incorrect acknowledgment.

```bash
lab_sql -c 'SELECT id, lease_owner, lease_until, claim_version, sent_at FROM outbox'
```

A lease can expire while the old worker is still delivering. The acknowledgment check protects the sender's state, while receiver-side idempotency protects against the same event arriving twice. In a real worker, bound delivery time, size the lease accordingly, and use the same ownership checks on any lease renewal. Track expired claims and repeated failures so an event that keeps timing out can be investigated.

After recording the result, remove only the disposable project with `docker compose -p outbox-lease-lab down --volumes`.

## References

- [PostgreSQL 16 locking clauses and SKIP LOCKED](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [PostgreSQL 16 timestamp functions](https://www.postgresql.org/docs/16/functions-datetime.html)
- [AWS guidance on transactional outboxes and duplicate deliveries](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
