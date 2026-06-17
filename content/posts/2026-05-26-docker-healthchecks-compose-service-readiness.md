---
title: "Docker Healthchecks — Service Readiness and Dependencies in Compose"
description: "Configure Docker healthchecks in Compose for real service readiness — depends_on with service_healthy, custom check scripts, practical examples for PostgreSQL, Nginx, Redis, and debugging common failures."
date: 2026-05-26T16:00:00Z
tags:
  - docker
  - docker-compose
  - linux
  - containers
  - troubleshooting
keywords:
  - Docker healthcheck service readiness Compose
  - depends_on condition service_healthy Docker Compose
  - PostgreSQL Nginx Redis healthcheck examples
  - custom healthcheck script Docker container
  - docker inspect health status troubleshooting
  - curl wget healthcheck distroless container
  - Docker Compose startup order dependencies
summary: "A practical guide to Docker healthchecks in Compose — define checks with test, interval, timeout, and start_period, use depends_on condition: service_healthy for ordered startup, and debug health state with docker inspect."
canonical: "https://gntech.dev/posts/docker-healthchecks-compose-service-readiness/"
---

Docker Compose starts all services in a stack simultaneously by
default. If your application depends on PostgreSQL or Redis being
fully ready, you get connection errors, retry loops, and startup
race conditions.

The fix is healthchecks. Not the Dockerfile-level `HEALTHCHECK`
instruction — the full Compose healthcheck block with
`depends_on` + `condition: service_healthy`. This post covers
everything from basic setup to real-world examples for common
homelab services, custom scripts, debugging, and the common
pitfalls.

---

## How Docker Healthchecks Actually Work

A healthcheck is a command that runs **inside the container**
every `interval` seconds. Exit code 0 means healthy. Exit code 1
means unhealthy. If the check fails `retries` times in a row,
Docker marks the container `unhealthy`.

```yaml
services:
  app:
    image: myapp:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

Each field has a specific purpose:

| Field | Default | What it controls |
|---|---|---|
| `test` | `NONE` | Command to run (array form preferred) |
| `interval` | 30s | How often the check runs |
| `timeout` | 30s | Max time for one check before it's a failure |
| `retries` | 3 | Consecutive failures before marking unhealthy |
| `start_period` | 0s | Grace period — no health checks run during this time |

The `start_period` is critical for databases and apps with long
initialization. During this period, Docker treats any exit code
as success so the service has time to boot before health tracking
begins.

---

## `depends_on` with `condition: service_healthy`

Compose's `depends_on` has three conditions:

```yaml
depends_on:
  db:
    condition: service_started    # default — just started the container
  redis:
    condition: service_healthy    # wait until healthcheck passes
```

`service_started` is the default and is practically useless for
ordering — it only means Docker started pulling the image and
creating the container, not that the process inside is listening.

For real dependency ordering, always use `service_healthy` with
a properly configured healthcheck on the dependency.

### Full Example — Web App with PostgreSQL

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: myapp
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://app:changeme@db:5432/myapp
```

The web app will not start until PostgreSQL is accepting
connections. No retry loops, no connection refused errors.

---

## Healthcheck Examples for Common Homelab Services

### PostgreSQL

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U \${POSTGRES_USER:-postgres}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

`pg_isready` ships with PostgreSQL and returns 0 when the server
is accepting connections. It hits the unix socket or TCP port
directly — no extra tools needed.

### Redis

```yaml
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 3s
  retries: 5
  start_period: 10s
```

`redis-cli ping` returns `PONG` when the server is ready. Works
with or without a password (add `-a $REDIS_PASSWORD` if needed).

### Nginx / Caddy

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost/"]
  interval: 15s
  timeout: 5s
  retries: 3
  start_period: 5s
```

Requires `curl` in the image. For Alpine-based images, install
it in your Dockerfile:

```dockerfile
RUN apk add --no-cache curl
```

### MariaDB / MySQL

```yaml
healthcheck:
  test: ["CMD-SHELL", "mysqladmin ping -h localhost -u root -p\${MYSQL_ROOT_PASSWORD}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

`mysqladmin ping` returns 0 when the server is alive. On MariaDB
official images, `healthcheck.sh` is provided:

```yaml
healthcheck:
  test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

### RabbitMQ

```yaml
healthcheck:
  test: ["CMD-SHELL", "rabbitmq-diagnostics -q ping"]
  interval: 15s
  timeout: 10s
  retries: 5
  start_period: 60s
```

RabbitMQ ships `rabbitmq-diagnostics` which does a full cluster
health check — not just port availability.

### MinIO

```yaml
healthcheck:
  test: ["CMD", "mc", "ready", "local"]
  interval: 15s
  timeout: 5s
  retries: 5
  start_period: 15s
```

Requires the MinIO client (`mc`) inside the container. The MinIO
official image includes it.

### Vaultwarden (Bitwarden)

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:80/alive"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

---

## Custom Healthcheck Scripts

When a single command is not enough, mount a script or use the
`CMD-SHELL` form to chain commands.

### Example — Multi-Condition Check for a Web App

```yaml
healthcheck:
  test: |
    ["CMD-SHELL", "curl -f http://localhost:8080/api/health && curl -f http://localhost:8080/static/index.html"]
  interval: 30s
  timeout: 15s
  retries: 3
  start_period: 60s
```

### Mounted Script Pattern

For complex checks that need branching logic:

```bash
#!/bin/sh
# healthcheck.sh — check app health via multiple endpoints

# Check main health endpoint
curl -sf http://localhost:8080/health || exit 1

# Check database connectivity via app endpoint
curl -sf http://localhost:8080/health/db || exit 1

# Check cache
curl -sf http://localhost:8080/health/cache || exit 1

exit 0
```

Mount it into the container and reference it:

```yaml
services:
  app:
    image: myapp:latest
    volumes:
      - ./healthcheck.sh:/usr/local/bin/healthcheck.sh
    healthcheck:
      test: ["CMD", "healthcheck.sh"]
      interval: 30s
      timeout: 15s
      retries: 3
      start_period: 60s
```

---

## Dockerfile-Level vs Compose-Level Healthchecks

You can define healthchecks in two places, and they work
differently.

### Dockerfile HEALTHCHECK

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

**Pros:**
- Bundled with the image — every container gets it automatically
- Works without Compose (raw `docker run`)

**Cons:**
- Can't use `depends_on` with `condition: service_healthy` on the
  Dockerfile-level check unless Compose is also involved
- Less flexible per-instance

### Compose-Level healthcheck

```yaml
healthcheck:
  test: ...
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 30s
```

**When to use which:**

- **Dockerfile HEALTHCHECK** — base images that always need the
  same check (e.g., your custom application base image)
- **Compose healthcheck** — environment-specific overrides,
  services you don't control the image for, stacks where you
  need `depends_on: condition: service_healthy`

**Compose healthcheck overrides the Dockerfile one** when both
are defined. This is useful when a database config difference
changes the healthcheck endpoint.

---

## The `curl` Problem — Healthchecks Without curl

Many minimal images (Alpine, distroless, scratch) do not ship
`curl` or `wget`. Installing them defeats the purpose of a small
image. Alternatives:

### Use wget Instead

```yaml
healthcheck:
  test: ["CMD", "wget", "-qO-", "http://localhost:8080/health"]
```

`wget` is smaller than `curl` and available on more base images.

### Use the Application's Built-in Check

PostgreSQL has `pg_isready`. Redis has `redis-cli ping`.
MySQL has `mysqladmin ping`. Prefer the service's native tool
when it exists.

### Use `/dev/tcp` (Bash Built-in)

For pure-shell environments without curl or wget:

```yaml
healthcheck:
  test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/5432 && echo 1 >&3 && read -u 3 && exec 3>&-"]
  interval: 15s
  timeout: 5s
  retries: 5
  start_period: 20s
```

This opens a TCP connection using bash's `/dev/tcp` virtual
filesystem. Works on any image with bash (not Alpine's busybox
sh by default — needs `bash` installed).

### Use a Dedicated Health HTTP Server

For custom apps, embed a tiny health server:

```yaml
healthcheck:
  test: ["CMD", "/healthz"]
```

Where `/healthz` is a compiled binary or script that checks
TCP ports, file descriptors, and returns 0 or 1. The Go standard
library's `net/http/pprof` serves this pattern well.

---

## Debugging Healthcheck Failures

Healthchecks fail silently unless you know where to look. Here is
the diagnostic workflow.

### 1. Check Container Health State

```bash
docker ps --filter "health=unhealthy"

# See all containers and their health
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Output includes the health status in the STATUS column: `(healthy)`,
`(unhealthy)`, or `(starting)` during `start_period`.

### 2. Inspect Health Log

```bash
docker inspect --format='{{json .State.Health}}' container_name | jq .
```

This shows the full health history — every check, its exit code,
and output:

```json
{
  "Status": "unhealthy",
  "FailingStreak": 5,
  "Log": [
    {
      "Start": "2026-05-26T15:30:00Z",
      "End": "2026-05-26T15:30:05Z",
      "ExitCode": 1,
      "Output": "curl: (7) Failed to connect to localhost port 8080: Connection refused"
    }
  ]
}
```

The `Output` field is gold — it tells you exactly why the check
failed.

### 3. Run the Check Command Manually

```bash
docker exec -it container_name curl -f http://localhost:8080/health
```

This reproduces the exact same environment the healthcheck runs
in. If it fails here, the check is correctly detecting a real
problem. If it succeeds but the healthcheck still fails, check:

- Did `start_period` expire?
- Is the command in `$PATH` inside the container?
- Does the command use a shell feature not available in `sh`?

### 4. Common Failures and Fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl: not found` | No curl in minimal image | Use native tool or install curl |
| `Connection refused` | Service not listening on localhost | Check `bind 127.0.0.1` config |
| `pg_isready: command not found` | Wrong user or PATH | Use `/usr/bin/pg_isready` |
| `(starting)` never becomes `healthy` | `start_period` too short | Increase `start_period` |
| `unhealthy` after booting fine | `interval` too fast for GC pauses | Increase interval to 30-60s |

---

## Advanced Pattern — Intra-Stack Dependency Chains

In complex stacks, you need to chain dependencies through
multiple levels.

### Layered Services Example

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 10s

  api:
    build: ./api
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  nginx:
    build: ./nginx
    ports:
      - "80:80"
    depends_on:
      api:
        condition: service_healthy

  monitoring:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    depends_on:
      postgres:
        condition: service_healthy
```

Compose resolves this dependency graph at startup. PostgreSQL
and Redis start first. API waits for both. Nginx waits for API.
Monitoring waits only for PostgreSQL.

### Healthcheck Propagation in Compose Watch

Compose Watch (v2.27+) can wait for healthchecks before
restarting dependent services during development:

```yaml
services:
  api:
    build: ./api
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 5s
      timeout: 3s
      retries: 3
      start_period: 10s
    develop:
      watch:
        - action: sync
          path: ./api/src
          target: /app/src
          ignore:
            - node_modules/
            - .env

  nginx:
    image: nginx:alpine
    depends_on:
      api:
        condition: service_healthy
```

When `api` source files change, Compose Watch syncs them and
waits for the API healthcheck to pass before signaling nginx
that the dependency is ready.

---

## Avoiding the Retry Spiral — Graceful Degradation

Even with perfect healthchecks, services crash. The container
runtime will restart them per the `restart` policy, and the
healthcheck will detect when they recover. But transient
failures during the restart window can cascade.

Set `restart: unless-stopped` on all services and configure
your application code to retry connections with exponential
backoff:

```python
# Python example — reconnect with exponential backoff
import time
import psycopg2
from psycopg2 import OperationalError

def wait_for_db(max_retries=10, base_delay=1):
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                host="db", dbname="myapp",
                user="app", password="pass"
            )
            return conn
        except OperationalError:
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)
    raise RuntimeError("Database not available")
```

The combination of Docker healthchecks on the infrastructure
side + application-level retry logic on the app side gives you
reliable recovery from any failure scenario.

---

## Summary

Docker healthchecks are the difference between a stack that
seems to work sometimes and one that boots reliably every time.

**The four rules:**

1. **Always use `depends_on` with `condition: service_healthy`**
   for databases and services your app requires at startup
2. **Set `start_period` to match your service's boot time** —
   underestimate this and the check fails before it should
3. **Prefer native tools** (`pg_isready`, `redis-cli ping`)
   over curl for database healthchecks
4. **Debug with `docker inspect`** — the health log output
   tells you exactly why the check failed

Copy the examples for PostgreSQL, Redis, Nginx, MariaDB, and
others into your compose files and your applications will start
in the right order, every time.
