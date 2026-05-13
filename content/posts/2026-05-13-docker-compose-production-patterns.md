---
title: "Docker Compose Production Patterns for Homelabs — Healthchecks, Profiles, Secrets"
description: "Advanced Docker Compose patterns for homelab deployments — healthchecks with depends_on condition, profiles for optional services, secrets management, extension fields, and restart policies."
date: 2026-05-13T17:00:00-04:00
tags:
  - docker
  - docker-compose
  - homelab
  - security
  - containers
keywords:
  - Docker Compose healthcheck patterns
  - Docker Compose depends_on condition
  - Docker Compose profiles homelab
  - Docker secrets management
  - Docker Compose extension fields
  - Docker restart policies pmax
  - production docker compose configuration
summary: "Practical Docker Compose patterns for reliable homelab deployments. Healthchecks, conditional dependencies, profiles for optional services, secrets management, extension fields, and restart policies with real compose files."
canonical: "https://gntech.dev/posts/docker-compose-production-patterns-for-homelabs/"
---

Most `docker-compose.yml` files you find in tutorials are minimal. They
work for `docker compose up -d` on a fresh system, but they don't handle
service startup order, container crashes, secrets, or configuration
reuse — all things that matter when your stack runs for months.

This post covers the patterns that turn a throwaway compose file into
something you can deploy, forget, and trust. Every pattern includes a
real example you can drop into your existing stack.

---

## 1. Healthchecks — Know When a Container Is Actually Ready

The default Docker healthcheck is: "is the process running?" That's not
the same as "is the service accepting traffic?"

A PostgreSQL container can start with the process running while it's
still recovering the WAL. A Traefik container can bind port 80 while
loading its configuration. Healthchecks solve this.

### Database Healthcheck

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
```

- `start_period`: gives the container 30s grace before healthchecks count.
  PostgreSQL needs this on first start — it initializes the data directory
  before accepting connections.
- `interval`: check every 10 seconds.
- `retries`: mark unhealthy after 5 consecutive failures.

### Web Service Healthcheck

```yaml
services:
  nginx:
    image: nginx:alpine
    healthcheck:
      test: ["CMD", "nginx", "-t"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

For HTTP services, use `curl`:

```yaml
services:
  app:
    image: myapp:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 15s
      timeout: 3s
      retries: 3
      start_period: 15s
```

The container must have `curl` installed. Use a `curl`-based image or
install it in your Dockerfile:

```dockerfile
FROM alpine:3.20
RUN apk add --no-cache curl
```

### View Health Status

```bash
# Show health status for all containers
docker compose ps

# Filter to unhealthy containers only
docker compose ps --status unhealthy

# See healthcheck log output
docker inspect --format='{{json .State.Health}}' <container_name>
```

A container marked `(unhealthy)` won't receive traffic from other
services using `depends_on: condition: service_healthy`.

---

## 2. Depends On with Conditions — Real Startup Ordering

The old `depends_on` only waited for a container to start, not for it
to be ready. Compose v2.20+ supports conditions, and when combined with
healthchecks, you get real ordering.

### Service-Healthy Dependencies

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser -d appdb"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 20s

  api:
    image: myapi:latest
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 10s
    environment:
      DATABASE_URL: "postgres://appuser:password@postgres:5432/appdb"

  nginx:
    image: nginx:alpine
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "80:80"
```

This creates a chain: nginx waits for api, api waits for postgres.
Each service starts exactly when its dependency reports healthy.

### Service-Started (Default) vs Service-Healthy

```yaml
services:
  # Only needs to start after redis starts the process (default)
  cache-worker:
    image: myworker:latest
    depends_on:
      - redis

  # Must wait until postgres accepts connections
  app:
    image: myapp:latest
    depends_on:
      postgres:
        condition: service_healthy
```

Use `service_started` (the default) for fast dependencies like Redis or
Memcached. Use `service_healthy` for databases, message queues, and
anything with startup initialization.

---

## 3. Restart Policies — Survive Crashes Gracefully

Don't leave containers set to `restart: unless-stopped` without
understanding the failure modes.

```yaml
services:
  # Core services that must stay up
  traefik:
    image: traefik:v3.3
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"

  # One-shot or batch jobs — never restart
  db-migrate:
    image: myapp:latest
    restart: no
    command: ["npm", "run", "migrate"]

  # Services that can crash briefly but should retry fast
  monitoring-agent:
    image: grafana/agent:latest
    restart: on-failure:5
    # Max 5 retries, then give up
```

### Restart Strategy Decision Table

| Restart Policy | Use Case | Behavior |
|---------------|----------|----------|
| `no` | Batch jobs, migrations, cron containers | Never restarts |
| `always` | Critical infrastructure, reverse proxies | Restarts regardless of exit code |
| `unless-stopped` | Long-running services you might manually stop | Restarts unless manually stopped |
| `on-failure:N` | Services with occasional transient failures | Restarts only on non-zero exit, up to N times |

### Resource Limits Prevent Restart Loops

A container that OOM-kills and restarts in a loop will keep getting
killed unless you constrain memory:

```yaml
services:
  buggy-app:
    image: myapp:latest
    restart: on-failure:3
    deploy:
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

With memory limits, the container is killed for exceeding 256 MB rather
than exhausting host memory and triggering the OOM killer. The `on-failure:3`
cap prevents infinite restart loops if the app keeps crashing.

---

## 4. Profiles — Optional Services Without Separate Compose Files

Profiles let you define services that only start when explicitly
requested. Perfect for debugging tools, admin panels, or services you
only need occasionally.

### Define Profiles

```yaml
services:
  # Main stack — always starts
  postgres:
    image: postgres:16-alpine
    # no profiles = always included

  api:
    image: myapi:latest
    depends_on:
      - postgres

  # Debug console — only with --profile debug
  pgadmin:
    image: dpage/pgadmin4:latest
    profiles:
      - debug
    depends_on:
      - postgres
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@homelab.local
      PGADMIN_DEFAULT_PASSWORD_FILE: /run/secrets/pgadmin_pass
    secrets:
      - pgadmin_pass

  # Performance testing tools
  k6:
    image: grafana/k6:latest
    profiles:
      - loadtest
      - debug
    # k6 belongs to both profiles
```

### Usage

```bash
# Start normal stack
docker compose up -d

# Start with debug tools
docker compose --profile debug up -d

# Start with load testing tools
docker compose --profile loadtest up -d

# Start everything
docker compose --profile "*" up -d
```

### Real Homelab Use Case: Monitoring vs Debug

```yaml
services:
  # Always running
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus:/etc/prometheus

  grafana:
    image: grafana/grafana:latest
    depends_on:
      - prometheus

  # On-demand query explorer
  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:latest
    profiles:
      - diagnostics
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATA_SOURCE_NAME: "postgresql://exporter:pass@postgres:5432/appdb?sslmode=disable"

  # On-demand slow query log viewer
  pghero:
    image: ankane/pghero:latest
    profiles:
      - diagnostics
      - debug
    depends_on:
      - postgres
```

Start your stack normally. When you need to troubleshoot database
performance, run `docker compose --profile diagnostics up -d` and
pgHero + postgres-exporter appear in your monitoring stack. Shut them
down with `docker compose --profile diagnostics down` when done.

---

## 5. Secrets Management — Stop Putting Passwords in Compose Files

Docker Compose has built-in secret support since v2.x. Secrets are
files mounted into `/run/secrets/` inside containers, readable only
by the UID the container runs as.

### Define Secrets

```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
  api_key:
    file: ./secrets/api_key.txt
  tls_cert:
    file: ./certs/homelab.crt
  tls_key:
    file: ./certs/homelab.key
```

### Use Secrets in Services

```yaml
services:
  postgres:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      # This works because postgres reads POSTGRES_PASSWORD_FILE at init

  api:
    image: myapi:latest
    secrets:
      - db_password
      - api_key
    environment:
      DATABASE_URL: "postgresql://appuser@postgres:5432/appdb"
      # Read password from secret
      # The app reads /run/secrets/db_password
      API_KEY_FILE: /run/secrets/api_key
```

### Service-Specific Secret Access

Only mount secrets to services that need them:

```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt
  pgadmin_pass:
    file: ./secrets/pgadmin_pass.txt
  grafana_admin_pass:
    file: ./secrets/grafana_admin.txt

services:
  postgres:
    secrets:
      - db_password

  pgadmin:
    profiles:
      - debug
    secrets:
      - pgadmin_pass
    # pgadmin cannot read db_password or grafana_admin_pass

  grafana:
    secrets:
      - grafana_admin_pass
    # grafana cannot read db_password or pgadmin_pass
```

This is least-privilege in practice. A compromised pgadmin container
cannot read your database password or Grafana admin credentials.

### Directory Layout for Secrets

```
docker/
├── compose.yml
├── secrets/
│   ├── db_password.txt
│   ├── api_key.txt
│   ├── pgadmin_pass.txt
│   └── grafana_admin.txt
├── certs/
│   ├── homelab.crt
│   └── homelab.key
└── config/
    ├── traefik.yml
    └── prometheus.yml
```

**Gitignore secrets but keep the structure:**

```gitignore
# .gitignore
secrets/*.txt
certs/*.key
```

Commit `.gitkeep` files to preserve the directory structure:

```bash
find secrets certs -type d -exec touch {}/.gitkeep \;
```

---

## 6. Extension Fields — DRY Your Compose Files

Extension fields use the `x-` prefix and let you define reusable blocks
that YAML anchors can reference.

### Common Labels

```yaml
x-common-labels: &common-labels
  labels:
    - "monitoring=prometheus"
    - "backup=daily"
    - "owner=homelab"

x-logging: &logging
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"

services:
  postgres:
    image: postgres:16-alpine
    <<: *common-labels
    <<: *logging

  api:
    image: myapi:latest
    <<: *common-labels
    <<: *logging
    depends_on:
      postgres:
        condition: service_healthy
```

### Reusable Healthcheck Definitions

```yaml
x-db-healthcheck: &db-healthcheck
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s

x-http-healthcheck: &http-healthcheck
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost/health"]
    interval: 15s
    timeout: 3s
    retries: 3
    start_period: 10s

services:
  postgres:
    image: postgres:16-alpine
    <<: *db-healthcheck

  api:
    image: myapi:latest
    <<: *http-healthcheck
```

### Network and Volume Definitions

```yaml
x-networks: &networks
  networks:
    internal:
    proxy:

services:
  app:
    image: myapp:latest
    <<: *networks
    # app is on both internal and proxy

  postgres:
    image: postgres:16-alpine
    networks:
      - internal
      # postgres is internal-only — not exposed to proxy
```

---

## 7. Multiple Compose Files — Split by Concern

Instead of one monster compose file, split by domain and use `-f`:

```bash
docker compose \
  -f compose.base.yml \
  -f compose.monitoring.yml \
  -f compose.media.yml \
  up -d
```

### base.yml — Shared Infrastructure

```yaml
# compose.base.yml
services:
  traefik:
    image: traefik:v3.3
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config/traefik:/etc/traefik
      - ./certs:/certs

networks:
  proxy:
    external: true
    name: proxy
```

### monitoring.yml — Monitoring Stack

```yaml
# compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:latest
    restart: unless-stopped
    volumes:
      - ./config/prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    networks:
      - proxy
      - monitoring

  grafana:
    image: grafana/grafana:latest
    restart: unless-stopped
    volumes:
      - grafana_data:/var/lib/grafana
    secrets:
      - grafana_admin_pass
    networks:
      - proxy

  node-exporter:
    image: prom/node-exporter:latest
    restart: unless-stopped
    networks:
      - monitoring
    pid: "host"

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring:
    internal: true
```

The `-f` approach means you can update monitoring (`docker compose -f compose.monitoring.yml pull && docker compose -f compose.monitoring.yml up -d`) without touching the media stack.

---

## 8. Restart Limits and Backoff

Docker's default restart behavior has an exponential backoff: 100ms,
200ms, 400ms, doubling up to a max of 5 minutes between attempts. This
is sensible, but you should understand it.

Monitor restart count:

```bash
# Check how many times a container has restarted
docker inspect --format '{{.RestartCount}}' <container_name>

# Watch restart events in real time
docker events --filter 'type=container' --filter 'event=restart'
```

### Prevent Crash Loops with Deregistration

A service that keeps crashing and restarting is still registered in
service discovery (Traefik, Consul, etc.). If your reverse proxy sees
the container, it will route traffic to it during its brief healthy
window.

```yaml
services:
  app:
    image: myapp:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 5s
      retries: 2
      start_period: 5s
    restart: on-failure:3
```

After 3 crash-restart cycles, Docker stops trying. The healthcheck
ensures Traefik deregisters the container before the healthcheck fails
permanently.

---

## 9. Complete Production Compose File

Here's a real compose.yml that combines all the patterns:

```yaml
# compose.yml — Production homelab stack
x-logging: &logging
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"

x-restart-policy: &restart-policy
  restart: unless-stopped

x-networks: &networks
  networks:
    - proxy

secrets:
  db_root_password:
    file: ./secrets/db_root_password.txt
  db_app_password:
    file: ./secrets/db_app_password.txt
  api_key:
    file: ./secrets/api_key.txt

services:
  postgres:
    image: postgres:16-alpine
    <<: *restart-policy
    <<: *logging
    volumes:
      - pgdata:/var/lib/postgresql/data
    secrets:
      - db_root_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_root_password
      POSTGRES_USER: postgres
      POSTGRES_DB: appdb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - internal

  app:
    image: myapp:latest
    <<: *restart-policy
    <<: *logging
    depends_on:
      postgres:
        condition: service_healthy
    secrets:
      - db_app_password
      - api_key
    environment:
      DATABASE_URL: "postgresql://appuser@postgres:5432/appdb"
      API_KEY_FILE: /run/secrets/api_key
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 15s
      timeout: 3s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits:
          memory: 256M
    <<: *networks

  traefik:
    image: traefik:v3.3
    <<: *restart-policy
    <<: *logging
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./config/traefik:/etc/traefik
    <<: *networks
    depends_on:
      app:
        condition: service_healthy

volumes:
  pgdata:

networks:
  internal:
    internal: true
  proxy:
    external: true
    name: proxy
```

---

## Summary

| Pattern | Key Takeaway |
|---------|-------------|
| Healthchecks | Poll a real readiness endpoint, not "process is running" |
| depends_on condition | Use `condition: service_healthy` for databases and API servers |
| Restart policies | `unless-stopped` for long-lived, `on-failure:N` with a cap for crashable services |
| Profiles | Keep debug/admin tools in `--profile debug`, not in a separate compose file |
| Secrets | Use `secrets: file:` instead of environment variables for passwords and keys |
| Extension fields | `x-*` blocks with YAML anchors keep repetitive configs DRY |
| Multi-file compose | Split by domain (infra, monitoring, media) with `-f` flag |
| Resource limits | Always set `deploy.resources.limits.memory` to prevent OOM crash loops |

The difference between a homelab stack that runs for 3 days and one
that runs for 3 years is mostly these patterns — startup ordering,
failure handling, and secret hygiene. Apply them one at a time, and
your compose files will survive reboots, crashes, and the inevitable
"what happens when this container runs out of memory?" question.
