---
title: "Test PostgreSQL Connection Pool Recovery After a Container Replacement"
description: "Keep the application running while replacing PostgreSQL at the same Compose DNS name with a different IP."
date: 2026-11-15T00:00:00-04:00
draft: false
ShowToc: true
tags: [docker, postgresql, python, disaster-recovery]
keywords: [Psycopg connection pool recovery, Docker Compose DNS, PostgreSQL container replacement]
summary: "Warm a Psycopg pool, deliberately move the database IP, and verify that the same app process reads data from the replacement."
cover:
  image: "/images/posts/postgres-pool-recovery/featured.webp"
  alt: "A hand holds a blue Ethernet cable beside lab servers."
  caption: "AI-generated editorial artwork."
  relative: false
---

A Compose service name can lead to the replacement database, but DNS cannot move a TCP connection that the application already has open. Test those two things separately. Warm the application pool, replace PostgreSQL at a different IP, and watch whether the same process opens a new connection and reads its data again.

This lab builds on the [Compose networking guide](/posts/2026-05-15-docker-compose-networking-patterns/). It uses Docker Compose v2, PostgreSQL 16 and Psycopg 3 on a disposable host. No ports are published. The replacement reuses the existing named volume, so this exercise measures reconnection rather than rebuilding data from a backup.

## 1. Set up the isolated project

Choose a subnet that does not overlap your host or Docker networks. If you change the sample subnet, change both database addresses below. In a new directory, generate a lab password.

```bash
mkdir pool-reconnect-drill
cd pool-reconnect-drill
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save as `compose.yaml`.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: recovery
      POSTGRES_USER: recovery
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
    volumes:
      - data:/var/lib/postgresql/data
    networks:
      default:
        ipv4_address: "${LAB_DB_IP:-172.28.254.10}"
  app:
    build: .
    environment:
      PGHOST: db
      PGDATABASE: recovery
      PGUSER: recovery
      PGPASSWORD: "${LAB_PASSWORD:?Generate a lab password}"
      PGCONNECT_TIMEOUT: "2"
      PGOPTIONS: "-c statement_timeout=2000"
networks:
  default:
    ipam:
      config:
        - subnet: 172.28.254.0/24
          ip_range: 172.28.254.128/25
volumes:
  data:
```

The static addresses make this test deterministic. The application still connects by name. Save this as `Dockerfile`.

```dockerfile
FROM python:3.13-slim-bookworm
RUN pip install --no-cache-dir "psycopg[binary]>=3.2,<4" "psycopg_pool>=3.2,<4"
WORKDIR /app
COPY probe.py .
USER nobody
CMD ["python", "-u", "probe.py"]
```

Save as `probe.py`.

```python
from datetime import datetime, timezone
from time import sleep

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout


def log(message):
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"), message, flush=True)


with ConnectionPool(
    conninfo="",
    min_size=1,
    max_size=1,
    timeout=3,
    reconnect_timeout=15,
    check=ConnectionPool.check_connection,
    kwargs={"autocommit": True},
    open=False,
) as pool:
    while True:
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT host(inet_server_addr()), value FROM recovery_marker WHERE id = 1"
                ).fetchone()
            if row is None or row[1] != "pool-fixture":
                log("NOT READY: marker missing or unexpected")
            else:
                log(f"READY db_ip={row[0]} marker={row[1]}")
        except (PoolTimeout, psycopg.Error) as exc:
            log(f"NOT READY: {type(exc).__name__}")
        sleep(2)
```

Psycopg can check a pooled connection before handing it out. A connection can still break after checkout, so the probe handles both pool timeouts and query errors. Each iteration is a new read-only observation. Application writes need their own retry policy because a dropped connection can leave the commit result unknown.

## 2. Establish the baseline

Use the same project name throughout.

```bash
docker compose -p pool-reconnect up -d db
docker compose -p pool-reconnect exec -T db pg_isready -h 127.0.0.1
```

Wait for PostgreSQL to accept TCP connections, then seed the marker and start the probe.

```bash
docker compose -p pool-reconnect exec -T db \
  psql -X -U recovery -d recovery -v ON_ERROR_STOP=1 -f - <<'SQL'
CREATE TABLE recovery_marker (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO recovery_marker VALUES (1, 'pool-fixture');
SQL

docker compose -p pool-reconnect up -d --build app
app_id="$(docker compose -p pool-reconnect ps -q app)"
docker inspect --format '{{.State.StartedAt}} {{.RestartCount}}' "$app_id"
docker compose -p pool-reconnect logs --tail 15 app
```

Wait for repeated `READY db_ip=172.28.254.10 marker=pool-fixture` lines. Record the application ID and start time. In a second terminal follow `docker compose -p pool-reconnect logs -f app` from the project directory.

## 3. Make the pool recover

In the original terminal, stop the database and wait for at least one `NOT READY` line. Then recreate just the database with the new IP. Keep the environment override for subsequent Compose commands that manage the database.

```bash
docker compose -p pool-reconnect stop db
# Wait for NOT READY in the log terminal before continuing.
export LAB_DB_IP=172.28.254.11
docker compose -p pool-reconnect up -d --no-deps --force-recreate db
```

Pause between the stop and the replacement. Without that pause, the poll can miss a brief outage. Look for `READY db_ip=172.28.254.11 marker=pool-fixture` after PostgreSQL becomes available. Then check the application identity again.

```bash
test "$app_id" = "$(docker compose -p pool-reconnect ps -q app)"
docker inspect --format '{{.State.StartedAt}} {{.RestartCount}}' "$app_id"
docker compose -p pool-reconnect exec -T app getent ahostsv4 db
```

The passing result is the new database IP in the query output, the original marker, and an unchanged application ID, start time and restart count. If DNS shows the new IP but queries still fail, inspect the database logs, pool timeouts and credentials. If DNS still resolves the old address, check the app's network attachment, resolver and any custom address overrides. A successful name lookup and a successful pooled query provide different evidence.

Measure the gap from the first failed poll to the first successful query on the new IP and note the deliberate hold and polling interval. Keep those observations separate from a production failover target. When finished, `docker compose -p pool-reconnect down --volumes` removes the disposable project and its database volume.

## References

- [Docker Compose networking and container replacement](https://docs.docker.com/compose/how-tos/networking/)
- [Psycopg pool behavior and connection checks](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [PostgreSQL session information functions](https://www.postgresql.org/docs/16/functions-info.html)
