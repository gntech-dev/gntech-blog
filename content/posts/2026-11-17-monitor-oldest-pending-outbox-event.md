---
title: "Alert When the Oldest Outbox Event Stops Moving"
description: "Export PostgreSQL outbox backlog and event age, then test delivery and collector failures separately."
date: 2026-11-17T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, prometheus, monitoring, reliability]
keywords: [outbox monitoring, oldest pending event, PostgreSQL backlog, node exporter]
summary: "Detect a stalled event even when the queue is small, and check that a broken collector cannot look like an empty queue."
cover:
  image: "/images/posts/outbox-delivery-age/featured.webp"
  alt: "An analog clock and a stack of work order cards beside a server on a warmly lit desk."
  caption: "AI-generated editorial artwork."
  relative: false
---

A queue can contain one event for hours while the worker process looks healthy. Count the pending events and track when the oldest was created. Together, those values show whether delivery meets the delay your application can tolerate.

This standalone lab connects the [monitoring approach in Part 11](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) to a disposable PostgreSQL 16 outbox. It uses Docker Compose v2, Python 3 and Node Exporter's textfile collector on a Linux host. The collector queries inventory. A delivery record still needs to represent acknowledgment by the intended receiver in your application.

## 1. Create the fixture and a read role

In a new directory, generate a disposable password and save the Compose file.

```bash
mkdir outbox-age-lab
cd outbox-age-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save this as `compose.yaml`. The database has no published port.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lab
      POSTGRES_USER: lab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a disposable lab password}"
```

Start the container and repeat the readiness command until PostgreSQL accepts TCP connections.

```bash
docker compose -p outbox-age-lab up -d
docker compose -p outbox-age-lab exec -T db pg_isready -h 127.0.0.1

docker compose -p outbox-age-lab exec -T db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 -f - <<'SQL'
CREATE TABLE outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz
);
CREATE ROLE observer LOGIN;
GRANT CONNECT ON DATABASE lab TO observer;
GRANT USAGE ON SCHEMA public TO observer;
GRANT SELECT ON outbox TO observer;
INSERT INTO outbox (created_at)
VALUES (clock_timestamp() - interval '20 minutes');
SQL
```

The official image permits local socket access in this disposable fixture. The observer has SELECT permission on the table. The host account running Docker commands controls the container, so this is a convenient lab boundary. For production, run the query through a dedicated database connection with a scoped identity, TLS and managed credentials.

## 2. Export the timestamp and collector health

Enable Node Exporter with `--collector.textfile.directory` pointing at an existing directory. Give the collector account write permission there and the exporter read permission. Keep the scrape endpoint restricted to your monitoring network. Save the script below as `collect-outbox.py` in the Compose project directory.

```python
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

query = """
SELECT json_build_object(
    'pending', count(*),
    'oldest', extract(epoch FROM min(created_at))
)
FROM public.outbox WHERE sent_at IS NULL
"""
command = [
    "docker", "compose", "-p", "outbox-age-lab", "exec", "-T", "db",
    "psql", "-XqAt", "-U", "observer", "-d", "lab",
    "-v", "ON_ERROR_STOP=1", "-c", query,
]
destination = Path(os.environ["OUTBOX_METRIC"])
try:
    response = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=20
    )
    sample = json.loads(response.stdout)
    count, oldest = sample["pending"], sample["oldest"]
    if type(count) is not int or count < 0:
        raise ValueError("invalid count")
    if count == 0:
        if oldest is not None:
            raise ValueError("empty queue has a timestamp")
    elif (
        type(oldest) not in (int, float)
        or not 0 < oldest <= time.time() + 300
    ):
        raise ValueError("invalid timestamp or clock skew")
except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
    print(f"Outbox query failed: {type(exc).__name__}")
    lines = ["gntech_outbox_query_success 0"]
else:
    lines = [
        "gntech_outbox_query_success 1",
        f"gntech_outbox_pending {count}",
    ]
    if count:
        lines.append(f"gntech_outbox_oldest_pending_timestamp_seconds {oldest}")

lines.append(f"gntech_outbox_collector_timestamp_seconds {int(time.time())}")
with tempfile.NamedTemporaryFile(
    dir=destination.parent, mode="w", delete=False
) as output:
    temporary = Path(output.name)
    output.write("\n".join(lines) + "\n")
try:
    temporary.chmod(0o644)
    temporary.replace(destination)
finally:
    temporary.unlink(missing_ok=True)
```

Run the collector from this directory with an absolute metric path.

```bash
export OUTBOX_METRIC=/var/lib/node_exporter/textfile_collector/outbox_age.prom
python3 collect-outbox.py
cat "$OUTBOX_METRIC"
```

Expect success equal to 1, pending equal to 1 and an oldest timestamp about twenty minutes before the database clock. The SQL uses one statement so both aggregates describe the same snapshot. An empty queue returns count zero and a null minimum. The exporter omits the oldest timestamp for that case.

On a failed query, the file contains the failure signal and the collector timestamp. Schedule the collector once a minute with the same working directory, environment and account. Keep one writer per output file. The temporary file and replacement share a directory so Node Exporter reads a complete file.

## 3. Alert on delayed delivery and failed observation

Use these expressions in Prometheus alert rules, replacing the sample instance with your Node Exporter scrape label. The five-minute delivery limit is an example to adjust to your application.

| Condition | PromQL expression |
| --- | --- |
| Event older than five minutes | `time() - gntech_outbox_oldest_pending_timestamp_seconds{instance="queue-monitor:9100"} > 300` |
| Query failed | `gntech_outbox_query_success{instance="queue-monitor:9100"} == 0` |
| Collector missing or stopped | `absent(gntech_outbox_collector_timestamp_seconds{instance="queue-monitor:9100"}) or (time() - gntech_outbox_collector_timestamp_seconds{instance="queue-monitor:9100"} > 180)` |

Use a short `for` interval if the condition should persist before notification. An old event can mean a stopped worker, repeated receiver errors, an event stuck in a lease, or a request that always fails validation. Query failure points first to the collector, connectivity or privileges. The collector timestamp catches a stopped job that leaves a readable old metric file behind. Keep clocks synchronized.

## 4. Rehearse resolution and loss of visibility

For the fixture only, mark its event sent and rerun the collector.

```bash
docker compose -p outbox-age-lab exec -T db \
  psql -X -U lab -d lab -v ON_ERROR_STOP=1 \
  -c 'UPDATE outbox SET sent_at = clock_timestamp() WHERE sent_at IS NULL'
python3 collect-outbox.py
```

Expect pending zero and no oldest timestamp. After the next scrape and rule evaluation, the old-event alert should resolve. This manual update stands in for a delivery acknowledgment in the lab.

Next stop only the lab database and rerun the collector. Expect query success zero, with the pending and oldest samples absent. Confirm the query-failure alert fires. Start the database again, rerun the collector and verify success returns. Finally stop the collector schedule for longer than three minutes and confirm its stale-timestamp alert. Validate the resulting notifications in your configured receiver.

Record the event-age threshold, scrape interval, rule delay and observed alert timing. Keep event IDs and error details in logs so metric labels remain stable. On a large outbox, evaluate a partial index on pending rows and inspect query cost against representative data. Clean up the disposable database with `docker compose -p outbox-age-lab down --volumes` after saving the drill results.

## References

- [PostgreSQL 16 aggregate functions](https://www.postgresql.org/docs/16/functions-aggregate.html)
- [Node Exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Prometheus absence queries](https://prometheus.io/docs/prometheus/latest/querying/functions/#absent)
