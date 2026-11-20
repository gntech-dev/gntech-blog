---
title: "Find the Transaction Blocking a PostgreSQL Worker"
description: "Use pg_blocking_pids and pg_stat_activity in a disposable three-session lab to identify a blocking transaction and verify recovery."
date: 2026-11-20T06:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, troubleshooting, operations, homelab]
keywords: [pg_blocking_pids, PostgreSQL blocked worker, idle in transaction, transaction age]
summary: "Trace a lock wait to its owning session, preserve useful evidence, and confirm progress after rollback."
cover:
  image: "/images/posts/postgresql-blocker/featured.webp"
  alt: "A brass magnifying glass and padlock beside glowing blue tiles on a warmly lit homelab desk."
  caption: "AI-generated conceptual editorial artwork; not a database diagram."
  relative: false
---

A worker can be connected, show an active query, and still make no progress. Before restarting it, ask whether another transaction is holding a lock it needs. PostgreSQL can report that relationship directly.

This standalone companion to the [GNTECH operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/) uses three sessions: one holds a row change open, one waits to update that row, and one observes both. It diagnoses the owner of a lock wait rather than implementing retries or event ordering.

Use Linux, Docker Engine with Compose v2, Bash and OpenSSL. The database is PostgreSQL 16. The walkthrough gives expected observations; it was not executed against a live GNTECH deployment or a local PostgreSQL server during preparation.

## 1. Create the disposable database

In Terminal C, create a fresh directory and Compose project. Use this directory in all three terminals.

```bash
mkdir blocker-lab
cd blocker-lab
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
docker compose -p blocker-lab up -d
```

The service has no published database port. Repeat the readiness check until it succeeds, then define this helper in Terminal C's Bash shell and load the fixture once.

```bash
docker compose -p blocker-lab exec -T db pg_isready -h 127.0.0.1
lab_sql() {
  docker compose -p blocker-lab exec -T -e PGAPPNAME=blocker-observer db \
    psql -XqAt -U lab -d lab -v ON_ERROR_STOP=1 "$@"
}
lab_sql <<'SQL'
CREATE TABLE work_item (id integer PRIMARY KEY, value integer NOT NULL);
INSERT INTO work_item VALUES (1, 0);
SQL
```

The image's bootstrap `lab` user is a superuser for this disposable fixture. Do not copy that privilege model into an application. A production observer needs appropriate visibility into other sessions; `pg_read_all_stats` exposes statistics that would otherwise be restricted. It can reveal sensitive query text, so grant it only to an approved monitoring identity and protect captured output.

## 2. Hold a transaction open in Terminal A

Open the holder session:

```bash
docker compose -p blocker-lab exec -e PGAPPNAME=blocker-holder db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1
```

At the SQL prompt run:

```sql
BEGIN;
SET LOCAL idle_in_transaction_session_timeout = '10min';
SELECT pg_backend_pid() AS holder_pid;
UPDATE work_item SET value = value + 1 WHERE id = 1;
```

Record the PID. Leave this session open without committing. Its update has completed, but the transaction still owns the row lock. The ten-minute idle timeout limits an abandoned lab session; if it expires, start again with a fresh fixture.

## 3. Start the waiting worker in Terminal B

Open a second interactive session:

```bash
docker compose -p blocker-lab exec -e PGAPPNAME=blocker-waiter db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1
```

Run this SQL. The last statement should wait rather than return an update count.

```sql
SET statement_timeout = '5min';
SET lock_timeout = '0';
SELECT pg_backend_pid() AS waiter_pid;
UPDATE work_item SET value = value + 10 WHERE id = 1;
```

This session uses psql's default autocommit: the update will commit when it finishes. Disabling the lock timeout here is deliberate so the observer has time to inspect the wait. The five-minute statement timeout still bounds the lab query. Production workers need timeout values chosen for their workload.

## 4. Capture the blocking relationship in Terminal C

Save the following query as `blockers.sql`. It returns one row per reported waiter/blocker pair for this lab. The left join retains a reported blocker PID even if its activity row has disappeared by the time the observer reads it.

```sql
SELECT clock_timestamp() AS observed_at,
       w.pid AS waiter_pid,
       w.application_name AS waiter_app,
       w.state AS waiter_state,
       w.wait_event_type,
       w.wait_event,
       clock_timestamp() - w.query_start AS waiter_query_age,
       p.blocker_pid,
       b.application_name AS blocker_app,
       b.state AS blocker_state,
       clock_timestamp() - b.xact_start AS blocker_transaction_age,
       left(b.query, 160) AS blocker_last_query
FROM pg_stat_activity AS w
CROSS JOIN LATERAL unnest(pg_blocking_pids(w.pid)) AS p(blocker_pid)
LEFT JOIN pg_stat_activity AS b ON b.pid = p.blocker_pid
WHERE w.datname = current_database()
  AND w.application_name = 'blocker-waiter'
ORDER BY w.pid, p.blocker_pid;
```

Run it once from the observer shell and preserve the output:

```bash
lab_sql -P fieldsep='|' -f - < blockers.sql > blocking-before.txt
cat blocking-before.txt
```

Expect the waiter PID recorded in Terminal B to point to the holder PID from Terminal A. Do not hard-code sample PID numbers: they change with each connection.

| Field | Expected meaning in this fixture |
| --- | --- |
| `waiter_state = active` | The update is still executing, even though it is waiting. |
| `wait_event_type = Lock` | The worker is waiting in PostgreSQL's heavyweight lock manager. |
| `wait_event` | Often `transactionid` for this row-update conflict; do not require the text `tuple`. |
| `blocker_state = idle in transaction` | The holder finished its statement and is waiting for its client to end the transaction. |
| `blocker_transaction_age` | Time since the holder's transaction started, not the duration of this particular lock wait. |
| `blocker_last_query` | The holder's last statement, which is not necessarily the statement that acquired every lock it owns. |

Likewise, `waiter_query_age` includes any execution before the wait. It is useful context, not an exact lock-wait timer. Rerun the query after a short interval to see whether the relationship persists. Each helper call creates a fresh observer session; a long-lived observer transaction can otherwise retain a statistics snapshot.

`pg_blocking_pids` accounts for conflicting holders and sessions ahead in a lock wait queue. It is preferable to guessing conflict relationships from a self-join of `pg_locks`. In larger systems, inspect each reported blocker in turn: this query shows immediate relationships, not a recursively resolved root cause. Parallel-query mappings can produce duplicate PIDs. A PID of zero can represent a prepared transaction, which has no ordinary live session row; investigate prepared transactions separately.

## 5. Release the owner, then verify progress

For this fixture, the holder's change is intentionally disposable. In **Terminal A**, end its transaction:

```sql
ROLLBACK;
```

Terminal B's update should now finish and commit. Confirm its prompt has returned without an error. In Terminal C, verify both the data and the disappearance of the wait:

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c 'SELECT value FROM work_item WHERE id=1')" == 10 ]]
  lab_sql -f - < blockers.sql > blocking-after.txt
  [[ ! -s blocking-after.txt ]]
  printf 'Holder rolled back; waiter committed; blocking relationship cleared\n'
)
```

A value of 10 matters: the holder's uncommitted increment was undone, while the waiting worker's increment committed. If Terminal B timed out first, this assertion should fail. Preserve the error, confirm the holder transaction ended, and repeat the fixture rather than treating an empty blocking report as proof of successful work.

On a real incident, obtain the owning application's decision to commit or roll back and record the business impact. An old transaction is evidence to investigate, not an automatic instruction to terminate a backend. Canceling an idle holder's query does not end its transaction or release its transaction locks. Session termination has broader consequences and requires a separate, deliberate recovery decision. Recheck PID identity and transaction details before any such intervention; PIDs are not permanent identities.

## 6. Keep an incident record and clean up

Record the observation time, waiter and blocker PIDs, application names, wait type, transaction age, owner, chosen action and the application's recovery check. Keep SQL text out of broadly shared incident notes if it contains private values. Avoid rapid cluster-wide polling: `pg_blocking_pids` briefly accesses lock-manager shared state, and collecting more often is not free.

Exit both interactive sessions with `\q`, then remove only this disposable project:

```bash
docker compose -p blocker-lab down --volumes
```

## References

Official PostgreSQL 16 documentation reviewed November 20, 2026:

- [System information functions: pg_blocking_pids](https://www.postgresql.org/docs/16/functions-info.html)
- [Session activity, transaction timestamps and statistics snapshots](https://www.postgresql.org/docs/16/monitoring-stats.html)
- [Lock inspection and limitations of pg_locks self-joins](https://www.postgresql.org/docs/16/view-pg-locks.html)
- [Predefined monitoring roles](https://www.postgresql.org/docs/16/predefined-roles.html)
- [Server signaling functions](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL)
