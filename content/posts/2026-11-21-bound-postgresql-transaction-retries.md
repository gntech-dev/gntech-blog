---
title: "Bound PostgreSQL Transaction Retries with an Attempt Budget and Jitter"
description: "Retry selected transaction-abort errors with capped randomized waits, then test recovery, exhaustion and permanent failures separately."
date: 2026-11-21T05:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, python, reliability, operations]
keywords: [PostgreSQL retry budget, Psycopg transaction retry, full jitter, 40P01, 40001]
summary: "A small retry policy with deterministic tests and a disposable database exercise that checks rollback before retry."
cover:
  image: "/images/posts/postgresql-retry-budget/featured.webp"
  alt: "A brass metronome and three brass tokens spaced unevenly on a blue mat beside a homelab server."
  caption: "AI-generated conceptual editorial artwork."
  relative: false
---

Retrying a failed transaction can help a worker recover from contention. Retrying indefinitely can turn a temporary conflict into a sustained workload. Give each operation a finite attempt budget, wait outside its transaction, and make the retry decision from the error code.

This standalone companion to the [GNTECH operations chapter](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/) implements the policy rather than reproducing a lock cycle. Use Python 3.12, Psycopg 3.2.13 and PostgreSQL 16. The policy tests need no database. The separate Compose exercise checks database rollback using deliberately injected failures; it does not generate real concurrent deadlocks or prove production recovery.

Preparation status: the five deterministic policy tests passed with Psycopg 3.2.13. The PostgreSQL/Compose exercise was not executed; its row counts are expected results.

## 1. Decide which failures may be retried

| Result | Policy in this example |
| --- | --- |
| `40P01`: deadlock detected | Retry the whole operation in a new transaction, within the attempt limit. |
| `40001`: serialization failure | Retry the whole operation, including reads and decisions. |
| Constraint failure | Propagate immediately; do not assume another attempt can repair the input. |
| Connection failure or unknown commit outcome | Propagate; investigate outcome and idempotency separately. |

One attempt includes connection setup, all business SQL, and commit. The callback must return only after that boundary completes. Keep the logical request identity stable. Do not place an HTTP side effect inside a callback that can run repeatedly unless it has a separate delivery/idempotency design.

## 2. Write the retry policy

Create a fresh directory, then save the following as `retry_policy.py`.

```bash
mkdir retry-budget-lab
cd retry-budget-lab
```

```python
import random
import time
from psycopg.errors import DeadlockDetected, SerializationFailure


def retry_transaction(operation, *, attempts=3,
                      sleep=time.sleep, uniform=random.uniform):
    if not isinstance(attempts, int) or not 1 <= attempts <= 10:
        raise ValueError("attempts must be between 1 and 10")
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (DeadlockDetected, SerializationFailure):
            if attempt == attempts:
                raise
            ceiling = min(0.5, 0.1 * 2 ** (attempt - 1))
            sleep(uniform(0.0, ceiling))
```

Three attempts means the first call plus **two** retries. After the first failure, the delay is sampled from 0 to 0.1 seconds; after the second, from 0 to 0.2 seconds. Larger configured budgets cap each delay at 0.5 seconds. Sampling across the entire interval is commonly called full jitter. It spreads retry timings but does not guarantee fairness or prevent another collision.

The final failure is re-raised without sleeping again. This is an attempt budget, **not a wall-clock deadline**: database calls, network waits and scheduling take time too. Set connection and statement limits separately, and enforce an overall deadline at the worker/request boundary when required. A statement timeout alone does not bound an entire multi-statement transaction.

## 3. Test the policy without a database

Install the chosen lab dependency in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'psycopg[binary]==3.2.13'
```

Save as `test_retry_policy.py`. The fake operations test decisions and delays; they do not model PostgreSQL locks or commit behavior. The injected random function returns each upper bound, so assertions are deterministic and no real sleep occurs.

```python
import unittest
from psycopg import OperationalError
from psycopg.errors import (
    DeadlockDetected, SerializationFailure, CheckViolation,
)
from retry_policy import retry_transaction


class RetryTests(unittest.TestCase):
    def run_case(self, failures, attempts=3):
        calls, waits = [], []
        def operation():
            calls.append(len(calls) + 1)
            if len(calls) <= len(failures):
                raise failures[len(calls) - 1]
            return "committed"
        def run():
            return retry_transaction(
                operation, attempts=attempts, sleep=waits.append,
                uniform=lambda low, high: high,
            )
        return run, calls, waits

    def test_first_attempt_success(self):
        run, calls, waits = self.run_case([])
        self.assertEqual(run(), "committed")
        self.assertEqual((len(calls), waits), (1, []))

    def test_both_retryable_codes_then_success(self):
        run, calls, waits = self.run_case([
            DeadlockDetected("injected"), SerializationFailure("injected")])
        self.assertEqual(run(), "committed")
        self.assertEqual((len(calls), waits), (3, [0.1, 0.2]))

    def test_exhaustion_has_no_final_sleep(self):
        failures = [DeadlockDetected("injected") for _ in range(3)]
        run, calls, waits = self.run_case(failures)
        with self.assertRaises(DeadlockDetected) as caught:
            run()
        self.assertIs(caught.exception, failures[-1])
        self.assertEqual((len(calls), waits), (3, [0.1, 0.2]))

    def test_permanent_and_unknown_outcome_are_not_retried(self):
        for error in [CheckViolation("injected"), OperationalError("lost")]:
            with self.subTest(error=type(error).__name__):
                run, calls, waits = self.run_case([error])
                with self.assertRaises(type(error)):
                    run()
                self.assertEqual((len(calls), waits), (1, []))

    def test_delay_ceiling(self):
        run, calls, waits = self.run_case(
            [DeadlockDetected("injected") for _ in range(5)], attempts=6)
        self.assertEqual(run(), "committed")
        self.assertEqual(waits, [0.1, 0.2, 0.4, 0.5, 0.5])


if __name__ == "__main__":
    unittest.main()
```

Run `python -m unittest -v test_retry_policy`. Expect five passing tests. Keep this evidence separate from a database integration run.

## 4. Exercise rollback and exhaustion in PostgreSQL

Save this as `exercise.py`. The first insert is made on every attempt. A synthetic deadlock exception is raised **after** that insert for the retry scenarios. Psycopg's connection context rolls the transaction back on exception and closes the connection before the policy catches the error. On success it commits before the callback returns. The permanent case deliberately triggers an actual check constraint error after the first insert.

```python
import psycopg
from psycopg.errors import DeadlockDetected, CheckViolation
from retry_policy import retry_transaction


def connect():
    return psycopg.connect(
        connect_timeout=3,
        options="-c statement_timeout=2000 -c lock_timeout=1000",
    )


with connect() as conn:
    conn.execute("""CREATE TABLE IF NOT EXISTS retry_effect (
        request_id text PRIMARY KEY,
        value integer NOT NULL CHECK (value > 0))""")
    conn.execute("TRUNCATE retry_effect")

for mode, expected_calls, expected_rows in [
    ("recover", 3, 1), ("exhaust", 3, 0), ("permanent", 1, 0),
]:
    calls = 0
    def operation():
        global calls
        calls += 1
        with connect() as conn:
            conn.execute("INSERT INTO retry_effect VALUES (%s, 1)", (mode,))
            if mode == "permanent":
                conn.execute("INSERT INTO retry_effect VALUES ('bad', -1)")
            if mode == "exhaust" or (mode == "recover" and calls < 3):
                raise DeadlockDetected("injected after write")
        return "committed"

    try:
        result = retry_transaction(operation)
        assert mode == "recover" and result == "committed"
    except DeadlockDetected:
        assert mode == "exhaust"
    except CheckViolation:
        assert mode == "permanent"
    with connect() as conn:
        rows = conn.execute(
            "SELECT count(*) FROM retry_effect WHERE request_id=%s", (mode,)
        ).fetchone()[0]
    assert calls == expected_calls and rows == expected_rows
    print(f"{mode}: attempts={calls}, committed_rows={rows}")

with connect() as conn:
    assert conn.execute("SELECT count(*) FROM retry_effect").fetchone()[0] == 1
```

Use this only in the disposable project: it truncates its fixture table. Save as `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /lab
RUN pip install --no-cache-dir 'psycopg[binary]==3.2.13'
COPY retry_policy.py exercise.py ./
CMD ["python", "exercise.py"]
```

Generate a private lab password, then save the Compose file:

```bash
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
cat > compose.yaml <<'YAML'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
    healthcheck:
      test: [CMD-SHELL, "pg_isready -U lab -d lab"]
      interval: 2s
      timeout: 3s
      retries: 30
  worker:
    build: .
    environment:
      PGHOST: db
      PGDATABASE: lab
      PGUSER: lab
      PGPASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
    depends_on:
      db:
        condition: service_healthy
YAML
docker compose -p retry-budget-lab up -d --wait db
docker compose -p retry-budget-lab run --rm --build worker
```

Neither service publishes a port. The bootstrap database account is privileged for this isolated fixture; production applications need scoped roles. Python 3.12 and PostgreSQL 16 tags track patch updates, so record the image digests and `python -m pip show psycopg` output with any runtime report.

| Scenario | Expected attempts | Expected committed rows |
| --- | --- | --- |
| Two injected aborts, then success | 3 | 1 |
| Retryable failure on every attempt | 3 | 0 |
| Check constraint failure | 1 | 0 |

A successful process exit and matching row counts demonstrate this fixture's policy/rollback boundary. They do not validate actual lock contention. If a connection fails, a dependency is missing, or an assertion fails, the drill failed; preserve the error and investigate rather than relabeling it as exhaustion.

## 5. Operate the policy with explicit limits

Log the stable request identity, attempt number, SQLSTATE, chosen delay and final outcome. Avoid raw payloads, SQL text or connection strings in broad logs. Alert on exhaustion rates and rising attempts even when requests eventually succeed: retries consume database capacity.

Place retry ownership at one layer. Three attempts in a worker combined with three attempts in its caller can produce nine database attempts. Keep transaction bodies short, preserve a consistent lock order, and fix persistent contention rather than increasing the budget indefinitely. A uniqueness error is not a substitute for an idempotent response protocol, and a lost commit acknowledgment needs its own reconciliation path.

After collecting results, remove the disposable database and worker images when no longer needed:

```bash
docker compose -p retry-budget-lab down --volumes --rmi local
```

## References

Official documentation reviewed November 21, 2026:

- [PostgreSQL 16 transaction failure handling](https://www.postgresql.org/docs/16/mvcc-serialization-failure-handling.html)
- [Psycopg connection context and transaction boundaries](https://www.psycopg.org/psycopg3/docs/basic/usage.html#connection-context)
- [Psycopg error classes and SQLSTATE](https://www.psycopg.org/psycopg3/docs/api/errors.html)
- [Psycopg release notes, including 3.2.13](https://www.psycopg.org/psycopg3/docs/news.html)
- [Python uniform random sampling](https://docs.python.org/3.12/library/random.html#random.uniform)
