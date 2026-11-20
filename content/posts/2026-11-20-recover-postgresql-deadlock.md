---
title: "Reproduce a PostgreSQL Deadlock and Retry the Whole Transaction"
description: "Create a two-row deadlock, identify SQLSTATE 40P01, and retry the aborted transfer with a consistent row-lock order."
date: 2026-11-20T18:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, troubleshooting, homelab]
keywords: [PostgreSQL deadlock lab, 40P01, whole transaction retry, consistent lock order]
summary: "A controlled two-session failure drill with a request ledger and balance assertions before and after recovery."
cover:
  image: "/images/posts/postgresql-deadlock/featured.webp"
  alt: "Interlocking brass puzzle pieces and a separate piece on a blue mat beside a homelab server and laptop."
  caption: "AI-generated conceptual editorial artwork; not a database diagram."
  relative: false
---

A deadlock differs from a worker waiting behind one slow transaction. Two transactions can each own a row the other needs, leaving neither able to continue. PostgreSQL breaks the cycle by aborting one transaction. Recovery must replay that transaction's complete operation, including the statements that appeared to succeed before the error.

This standalone companion to the [GNTECH operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/) deliberately transfers small integer units between two fixture accounts. A request ledger makes a partial retry visible. Use a disposable Linux host with Docker Engine, Compose v2, Bash and OpenSSL. The database is PostgreSQL 16. All observations below are expected lab results; the database drill was not executed during preparation and does not describe a GNTECH deployment.

## 1. Prepare a disposable fixture

Use three terminals in the same fresh directory. Terminal C is the verification shell.

```bash
mkdir deadlock-lab
cd deadlock-lab
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
docker compose -p deadlock-lab up -d
```

There is no published database port. Repeat the readiness command until it succeeds. Define the helper in Terminal C's Bash shell, then load the tables once.

```bash
docker compose -p deadlock-lab exec -T db pg_isready -h 127.0.0.1
lab_sql() {
  docker compose -p deadlock-lab exec -T db \
    psql -XqAt -U lab -d lab -v ON_ERROR_STOP=1 "$@"
}
lab_sql <<'SQL'
CREATE TABLE account (
    id integer PRIMARY KEY,
    units integer NOT NULL CHECK (units >= 0)
);
CREATE TABLE transfer_request (
    request_id text PRIMARY KEY,
    source_id integer NOT NULL REFERENCES account,
    target_id integer NOT NULL REFERENCES account,
    units integer NOT NULL CHECK (units > 0),
    CHECK (source_id <> target_id)
);
INSERT INTO account VALUES (1, 100), (2, 100);
SQL
```

The image's bootstrap user is a superuser for this isolated fixture. Real application roles need scoped permissions. These tables demonstrate transaction behavior, not a complete financial ledger or payment service.

## 2. Take the first row in opposite orders

In Terminal A, open an interactive SQL session:

```bash
docker compose -p deadlock-lab exec -e PGAPPNAME=deadlock-A db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 -v VERBOSITY=verbose
```

Start transfer A from account 1 to account 2, but stop after its debit:

```sql
SET statement_timeout = '5min';
SET lock_timeout = '0';
SET idle_in_transaction_session_timeout = '10min';
BEGIN;
INSERT INTO transfer_request VALUES ('transfer-A', 1, 2, 10);
UPDATE account SET units = units - 10 WHERE id = 1;
```

In Terminal B, open a separate session:

```bash
docker compose -p deadlock-lab exec -e PGAPPNAME=deadlock-B db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 -v VERBOSITY=verbose
```

Start transfer B in the opposite direction, also stopping after its debit:

```sql
SET statement_timeout = '5min';
SET lock_timeout = '0';
SET idle_in_transaction_session_timeout = '10min';
BEGIN;
INSERT INTO transfer_request VALUES ('transfer-B', 2, 1, 10);
UPDATE account SET units = units - 10 WHERE id = 2;
```

Both debits should return `UPDATE 1`. Neither is committed. The foreign-key checks on the account IDs do not prevent this fixture's non-key balance updates from reaching the intended row-lock conflict.

## 3. Complete the cycle

In Terminal A, submit the credit to account 2. It should wait; do not cancel it.

```sql
UPDATE account SET units = units + 10 WHERE id = 2;
```

While A is waiting, submit B's credit in Terminal B:

```sql
UPDATE account SET units = units + 10 WHERE id = 1;
```

![Session A holds the account 1 row and waits for account 2; session B holds account 2 and waits for account 1. Blue arrows show held rows and red arrows show requested rows.](/images/posts/postgresql-deadlock/cycle.svg)

PostgreSQL should detect the cycle and report `40P01` (`deadlock_detected`) in one session. The other session's credit should return `UPDATE 1`. **Do not assume B is the victim.** Record which session received the error and preserve its error detail.

| Session outcome | Next command in that session |
| --- | --- |
| Received SQLSTATE `40P01` | Run `ROLLBACK;` to clear its failed transaction state. |
| Credit completed with `UPDATE 1` | Run `COMMIT;` to finish the surviving transfer. |

Do not paste `COMMIT` into both terminals and infer success from the prompts. If a timeout or another SQLSTATE occurs instead, roll back both sessions and restart with a fresh fixture. The lab disables `lock_timeout` so it does not preempt deadlock detection, while `statement_timeout` bounds each statement. Do not copy those timeout choices into production without workload-specific limits.

## 4. Verify only the survivor committed

After the survivor commits and the victim rolls back, run in Terminal C:

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c 'SELECT count(*) FROM transfer_request')" == 1 ]]
  [[ "$(lab_sql -c 'SELECT sum(units) FROM account')" == 200 ]]
  [[ "$(lab_sql -c 'SELECT min(units) FROM account')" == 90 ]]
  [[ "$(lab_sql -c 'SELECT max(units) FROM account')" == 110 ]]
  printf 'Exactly one complete transfer committed\n'
)
lab_sql -c 'SELECT * FROM transfer_request ORDER BY request_id'
lab_sql -c 'SELECT * FROM account ORDER BY id'
```

The aborted transaction lost its ledger insert and its earlier debit. Retrying only the final credit would create units without a matching debit. That is why recovery begins at the transaction boundary.

## 5. Retry only the victim, from the beginning

Use the matching block below in the victim's session **after `ROLLBACK` and after the survivor committed**. Execute exactly one block. Both versions first lock account rows in ascending ID order, independent of transfer direction. IDs are immutable in this fixture.

If **A** received `40P01`, retry all of transfer A:

```sql
BEGIN;
SELECT id FROM account WHERE id IN (1, 2) ORDER BY id FOR UPDATE;
INSERT INTO transfer_request VALUES ('transfer-A', 1, 2, 10);
UPDATE account SET units = units - 10 WHERE id = 1;
UPDATE account SET units = units + 10 WHERE id = 2;
COMMIT;
```

If **B** received `40P01`, retry all of transfer B:

```sql
BEGIN;
SELECT id FROM account WHERE id IN (1, 2) ORDER BY id FOR UPDATE;
INSERT INTO transfer_request VALUES ('transfer-B', 2, 1, 10);
UPDATE account SET units = units - 10 WHERE id = 2;
UPDATE account SET units = units + 10 WHERE id = 1;
COMMIT;
```

The request identity stays the same. A unique-key error here means the ledger conflicts with the expected victim selection; stop and inspect rather than generating a new identity or blindly retrying that error.

Verify the completed pair in Terminal C:

```bash
(
  set -euo pipefail
  [[ "$(lab_sql -c 'SELECT count(*) FROM transfer_request')" == 2 ]]
  [[ "$(lab_sql -c "SELECT count(*) FROM transfer_request WHERE request_id IN ('transfer-A','transfer-B')")" == 2 ]]
  [[ "$(lab_sql -c 'SELECT count(*) FROM account WHERE units=100')" == 2 ]]
  [[ "$(lab_sql -c 'SELECT sum(units) FROM account')" == 200 ]]
  printf 'Both requests committed; each account returned to 100 units\n'
)
```

## 6. Carry the recovery rule into a worker

An application should identify `40P01` through its driver's SQLSTATE field, discard the failed transaction, and rerun the complete business operation in a fresh transaction. Reevaluate any reads and decisions inside that attempt. Bound retries and total elapsed time; add backoff with jitter so competing workers do not immediately collide again. Report exhaustion with the request identity and attempt count.

Use the same lock order across **all** participating transaction paths, not just retries. The ascending-row lock step prevents this fixture's opposite-order cycle; it does not prove the absence of other deadlocks involving indexes, foreign keys, triggers or additional resources. Keep transactions short and keep external effects outside the retried transaction unless separately protected by an appropriate delivery and idempotency design. A database rollback cannot undo a completed external HTTP action.

This drill uses manual retries so the abort and recovery boundary remain visible. It does not demonstrate an automated retry loop or safe recovery from an unknown commit outcome after a lost connection.

## 7. Preserve evidence and clean up

Record the original request IDs, victim SQLSTATE and detail, survivor result, intermediate ledger/balances, chosen retry block and final assertions. Exit both SQL sessions with `\q`, then remove only this disposable project:

```bash
docker compose -p deadlock-lab down --volumes
```

## References

Official PostgreSQL 16 documentation reviewed November 20, 2026:

- [Deadlocks, row locks and consistent lock order](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-DEADLOCKS)
- [Failure handling and complete transaction retries](https://www.postgresql.org/docs/16/mvcc-serialization-failure-handling.html)
- [SQLSTATE error codes](https://www.postgresql.org/docs/16/errcodes-appendix.html)
- [Statement, lock and idle transaction timeouts](https://www.postgresql.org/docs/16/runtime-config-client.html)
