---
title: "Test Whether an Application Recovers When PostgreSQL Starts Late"
description: "Start a recovery copy of an application before its database and check when it can read restored data."
date: 2026-11-15T00:00:00-04:00
draft: false
ShowToc: true
tags: [docker, postgresql, disaster-recovery, homelab]
keywords: [PostgreSQL recovery drill, Docker Compose readiness, application reconnect]
summary: "Distinguish a missing database server, an empty database and an application that can read restored data."
cover:
  image: "/images/posts/late-database-recovery/featured.webp"
  alt: "An operator reaches toward a standby computer beside another computer on a lit workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

Your web process can start before its database has been restored. In that gap the database may be offline, or it may accept connections before the expected tables are present. A recovery drill should exercise both states and check whether the application becomes usable without an operator restarting it.

The [Compose startup-order guide](/posts/2026-06-10-docker-compose-startup-dependencies-init-containers/) covers dependency gates. This exercise deliberately starts services out of order to test runtime behavior. It uses a tiny HTTP application that opens a fresh connection for each readiness request. For an application with a persistent connection pool, repeat the same test against that application's real configuration. The responses below are expected lab results.

## 1. Create a disposable recovery project

Use Docker Compose v2, OpenSSL and curl. Create a new directory. The database has no published port, and the application binds its published port to host loopback. Generate a lab credential locally.

```bash
mkdir late-db-drill
cd late-db-drill
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save this as `compose.yaml`. Use a different host port if 18081 is already in use.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: recovery
      POSTGRES_USER: recovery
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate the lab password first}"
    volumes:
      - data:/var/lib/postgresql/data
  app:
    build: .
    environment:
      PGHOST: db
      PGDATABASE: recovery
      PGUSER: recovery
      PGPASSWORD: "${LAB_PASSWORD:?Generate the lab password first}"
      PGCONNECT_TIMEOUT: "2"
      PGOPTIONS: "-c statement_timeout=2000"
    ports:
      - "127.0.0.1:18081:8080"
volumes:
  data:
```

Save this as `Dockerfile`.

```dockerfile
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app.py .
USER nobody
CMD ["python", "-u", "app.py"]
```

Save this as `app.py`.

```python
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/ready":
            self.send_error(404)
            return

        try:
            query = subprocess.run(
                ["psql", "-XAt", "-v", "ON_ERROR_STOP=1",
                 "-c", "SELECT value FROM recovery_marker WHERE id = 1"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            ready = query.stdout == "restored-fixture\n"
        except (subprocess.SubprocessError, OSError):
            ready = False

        body = b"restored-fixture\n" if ready else b"recovery incomplete\n"
        self.send_response(200 if ready else 503)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
```

The readiness request connects using the configured database identity and checks a specific row. `pg_isready` tells you whether the server is accepting connections, even if the credentials are wrong. The query adds an authentication and data check. The lab uses the bootstrap database role for setup and reads. For an existing application, exercise its actual application role and keep restore privileges separate.

## 2. Start the application first

Use the same project name throughout. Build the application before starting the drill so download time stays outside the recovery measurement. Once the application responds, expect HTTP 503.

```bash
docker compose -p late-db-drill up -d --build app
app_id="$(docker compose -p late-db-drill ps -q app)"
docker inspect --format '{{.State.StartedAt}} {{.RestartCount}}' "$app_id"
curl -si --max-time 7 http://127.0.0.1:18081/ready
```

If curl initially cannot connect, wait briefly for the web process and retry. A connection failure and an HTTP 503 are distinct observations.

## 3. Start PostgreSQL, then load the data

```bash
docker compose -p late-db-drill up -d db
docker compose -p late-db-drill exec -T db pg_isready -h 127.0.0.1 -U recovery -d recovery
curl -si --max-time 7 http://127.0.0.1:18081/ready
```

Repeat the `pg_isready` command until it reports that connections are accepted. The application should still return 503 because the marker table is missing. Load a small fixture representing the restored data. In an actual rehearsal, import the approved backup using your restore procedure and query a known recovery record.

```bash
docker compose -p late-db-drill exec -T db \
  psql -X -U recovery -d recovery -v ON_ERROR_STOP=1 --single-transaction -f - <<'SQL'
CREATE TABLE recovery_marker (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO recovery_marker VALUES (1, 'restored-fixture');
SQL

curl -si --max-time 7 http://127.0.0.1:18081/ready
test "$app_id" = "$(docker compose -p late-db-drill ps -q app)"
docker inspect --format '{{.State.StartedAt}} {{.RestartCount}}' "$app_id"
```

Expect HTTP 200 and the marker body. Compare the container ID, start time and restart count with step 2. If the service only recovers after a restart, record that manual step and include it in the recovery time. If the database is accepting connections and the application still returns 503, check the application identity, schema name and expected row from the application network.

For a second pass, stop only `db`, confirm the HTTP 503, then start `db` and check for HTTP 200 without reloading the fixture. That tests reconnection after a dependency outage with the restored data already present. In the disposable project, clean up with `docker compose -p late-db-drill down --volumes` after recording your results. This removes the lab database volume.

## References

- [Docker Compose dependency startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [PostgreSQL 16 pg_isready](https://www.postgresql.org/docs/16/app-pg-isready.html)
- [PostgreSQL 16 psql](https://www.postgresql.org/docs/16/app-psql.html)
