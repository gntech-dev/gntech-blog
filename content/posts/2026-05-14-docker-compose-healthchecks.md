---
title: "Docker Compose Health Checks — Reliable Service Startup Orchestration"
description: "Master Docker Compose health checks with depends_on condition patterns — ensure databases are ready before apps connect, with real homelab Compose examples for PostgreSQL, MySQL, Redis, and web services."
date: 2026-05-14T13:30:00-04:00
tags:
  - docker
  - docker-compose
  - devops
  - homelab
  - linux
keywords:
  - Docker Compose health checks
  - depends_on condition service healthy
  - Docker startup orchestration
  - container health check best practices
  - PostgreSQL Docker health check
  - wait-for-it Docker alternative
  - service dependency management docker
summary: "Stop using sleep and wait-for-it scripts. Use Docker Compose health checks with proper conditions to orchestrate service startup in your homelab reliably."
canonical: "https://gntech.dev/posts/docker-compose-healthchecks/"
---

Every homelab has a service that depends on a database. Your web app
starts before PostgreSQL finishes initializing. Your API gateway tries
to reach Redis before it's accepting connections. Your monitoring stack
fails to start because InfluxDB isn't ready yet.

The typical fix is a hack: `sleep 30`, a `wait-for-it.sh` script, or
manual restarts. These work inconsistently and slow down deployments.

Docker Compose health checks solve this properly. Combined with
`depends_on` conditions, they let you define exactly when a service
is considered ready — not just "running," but "accepting connections."

This post covers how to implement health checks for the most common
homelab services, with real Compose configurations you can drop into
your stack today.

---

## How Docker Health Checks Work

A health check tells Docker how to verify a container is functioning
correctly. Docker runs the check command periodically, and the
container's state changes based on the result:

- `starting` — container started, initial grace period
- `healthy` — the check command exited with code 0
- `unhealthy` — the check command failed (non-zero exit) past the
  retry threshold

In `docker ps`, you'll see the status column show `healthy` or
`unhealthy` when health checks are configured:

```bash
$ docker ps
CONTAINER ID   STATUS
abc123         Up 2 seconds (healthy)
def456         Up 10 seconds (unhealthy: 3/4)
```

The key Compose health check parameters:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
  interval: 30s       # How often to run the check
  timeout: 10s        # Max time for a single check
  retries: 3          # Failures before marking unhealthy
  start_period: 40s   # Grace period before first check
  start_interval: 5s  # (Compose v3.9+) Poll freq during start_period
```

The `start_period` is critical. During this window, failures don't
count toward the retry threshold. A database that takes 30 seconds to
initialize won't be flagged as unhealthy — Docker just waits.

---

## depends_on with Conditions

The real power comes from combining health checks with `depends_on`
conditions:

```yaml
services:
  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
```

This tells Compose: "Don't start `app` until `postgres` reports
`healthy`." No more sleep hacks. No more wait scripts. The dependency
is driven by actual service readiness.

Without `condition: service_healthy`, `depends_on` only waits for the
container to start — which means "the process is running" not "the
service is ready." That's why your app crashes at startup even with
`depends_on` in place.

---

## Example 1: Web App with PostgreSQL

This is the most common pattern. A web application that connects to
PostgreSQL. The database can take 15-60 seconds to initialize,
especially on the first run when it creates data directories.

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: postgres
    restart: unless-stopped
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: ${DB_PASSWORD:?required}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  app:
    build: ./app
    container_name: myapp
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: postgres://myapp:${DB_PASSWORD}@postgres:5432/myapp
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pgdata:
```

The `pg_isready` command is built into the PostgreSQL image and exits
with code 0 when the server is accepting connections. It's the correct
health check for PostgreSQL — not a TCP port check, not a custom HTTP
endpoint.

---

## Example 2: Redis Cache with Application

Redis starts almost instantly, but on first boot with AOF persistence
enabled, it may take a moment to load data. A `PING` check confirms
the server is responding:

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: redis
    restart: unless-stopped
    volumes:
      - redisdata:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s

  api:
    build: ./api
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      REDIS_URL: redis://redis:6379
    depends_on:
      redis:
        condition: service_healthy

volumes:
  redisdata:
```

`redis-cli ping` returns `PONG` when the server is ready. Simple,
reliable, built into the image.

---

## Example 3: MySQL / MariaDB with Application

MySQL's health check uses `mysqladmin ping`, which requires credentials:

```yaml
services:
  mariadb:
    image: mariadb:11
    container_name: mariadb
    restart: unless-stopped
    volumes:
      - mariadbdata:/var/lib/mysql
    environment:
      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD:?required}
      MARIADB_DATABASE: myapp
      MARIADB_USER: myapp
      MARIADB_PASSWORD: ${MARIADB_PASSWORD:?required}
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p${MARIADB_ROOT_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 40s

  app:
    build: ./app
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      DB_HOST: mariadb
      DB_USER: myapp
      DB_PASSWORD: ${MARIADB_PASSWORD}
      DB_NAME: myapp
    depends_on:
      mariadb:
        condition: service_healthy

volumes:
  mariadbdata:
```

Note the password is passed via environment variable interpolation.
The health check command runs inside the container where the
environment is available, so `${MARIADB_ROOT_PASSWORD}` resolves
correctly.

---

## Example 4: Nginx with Backend Service Dependency

In a reverse proxy setup, you want Nginx to wait for the backend
application to be healthy before it's marked as ready:

```yaml
services:
  backend:
    build: ./backend
    container_name: backend
    restart: unless-stopped
    expose:
      - "3000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  nginx:
    image: nginx:alpine
    container_name: nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      backend:
        condition: service_healthy
```

The backend exposes a `/health` endpoint that checks database
connectivity, cache connectivity, and internal state. Nginx waits
until the backend returns HTTP 200 before starting.

---

## Custom Health Checks with curl

For services that don't have a built-in health check command, `curl`
inside the container is the universal fallback. Most Alpine-based
images don't include curl by default, so you need to install it:

```dockerfile
# Dockerfile
FROM node:20-alpine

# Install curl for health checks
RUN apk add --no-cache curl

WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY . .

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

EXPOSE 3000
CMD ["node", "dist/index.js"]
```

Or handle it in Compose if you prefer not to modify the Dockerfile:

```yaml
services:
  app:
    build: .
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "wget -qO- http://localhost:3000/health || exit 1",
        ]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

Some lightweight images have `wget` instead of `curl`. Alpine includes
`wget` by default but not `curl`. Check what's available before writing
your health check command.

---

## Common Pitfalls and Debugging

### Health Check Never Runs

If you see `starting` status indefinitely, the `start_period` hasn't
elapsed yet. Wait for the full period to pass. If it stays in
`starting` after the period, your health check command is probably
wrong:

```bash
# Enter the container and run the check manually
docker exec -it container_name sh
# Test your check command
curl -f http://localhost:3000/health
echo $?  # Should be 0 for healthy
```

### depends_on condition Not Honored

Compose v2.20+ supports `condition: service_healthy`. Older versions
ignore it silently — the service starts without waiting:

```bash
docker compose version
# Must be v2.20.0+ for condition: service_healthy
# Otherwise, health checks still work but depends_on only waits for "started"
```

### Circular Dependencies

If service A depends on service B and service B depends on service A,
Compose refuses to start. Design your dependency graph as a DAG:

- App → Database (one way)
- Proxy → App → Database (chain)
- Never: App → DB → App

### Health Check Logging

Docker stores the last health check result. View it with:

```bash
# Last 5 health check logs
docker inspect --format='{{json .State.Health}}' container_name | jq .

# Or watch live health transitions
docker events --filter 'event=health_status' --filter 'container=container_name'
```

---

## Advanced: Chained Dependencies

Complex stacks often have multiple layers of dependencies. Here's a
full monitoring stack with proper health chaining:

```yaml
version: "3.8"

services:
  influxdb:
    image: influxdb:2
    container_name: influxdb
    restart: unless-stopped
    volumes:
      - influxdb_data:/var/lib/influxdb2
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_USERNAME: admin
      DOCKER_INFLUXDB_INIT_PASSWORD: ${INFLUXDB_PASSWORD}
      DOCKER_INFLUXDB_INIT_ORG: homelab
      DOCKER_INFLUXDB_INIT_BUCKET: telegraf
      DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: ${INFLUXDB_TOKEN}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8086/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 60s

  telegraf:
    image: telegraf:latest
    container_name: telegraf
    restart: unless-stopped
    volumes:
      - ./telegraf.conf:/etc/telegraf/telegraf.conf:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    depends_on:
      influxdb:
        condition: service_healthy

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clock-panel
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # Telegraf starts after InfluxDB is healthy
  # Grafana starts independently (it can retry InfluxDB connection)
  # This avoids slow cascading startup
```

Grafana doesn't depend on InfluxDB or Telegraf here because Grafana
handles missing data sources gracefully — it starts, serves the UI,
and connects to InfluxDB lazily. This avoids unnecessary sequential
startup delays.

The general rule: **only enforce dependencies that cause crashes on
missing connections.** If a service retries its backend internally,
let it start independently.

---

## When Not to Use Health Check Dependencies

Health check conditions are not always the right tool:

**1. Services with internal retry logic**

Most modern web frameworks (FastAPI, Express, Django, Spring Boot)
have configurable database connection retries. If your app retries
the database for 30 seconds internally, it doesn't need a
`depends_on` condition — it handles the delay itself.

**2. Stateless sidecars and log shippers**

A log aggregator like Loki or Fluentd doesn't depend on any
application. It should start first, not wait for anything.

**3. Reverse proxies with health check endpoints**

Nginx, Caddy, and Traefik can mark backends as down and retry them
automatically. Let the proxy manage availability — don't delay the
proxy startup.

**4. Monitoring targets that should always be running**

Grafana, Prometheus, and alert managers monitor the health of other
services. They shouldn't wait for them. If Grafana starts before
InfluxDB, Grafana logs a connection error and Grafana itself stays
healthy.

**Only block startup when a missing dependency causes a crash loop.**

---

## Testing Your Health Checks

Before deploying to production, validate that your health checks work
correctly:

```bash
# Start services and watch health transitions
docker compose up -d
docker compose ps

# Watch health status events in real time
docker events --filter 'event=health_status' &
sleep 30

# Manually simulate failures
docker exec postgres kill 1
docker compose ps  # Should show unhealthy after retries

# Check the health check log
docker inspect --format='{{json .State.Health}}' postgres | jq .

# Verify app waits for healthy database
docker compose logs app  # Should show connection established
```

If a service doesn't reach `healthy` within the expected time:

1. Increase `start_period` — databases on homelab hardware (especially
   spinning disks or ZFS with slow sync) take longer to initialize
2. Run the health check command inside the container manually to verify
   it works
3. Check the container logs for startup errors
4. Verify the health check command exists in the image (no curl on
   Alpine by default)

---

## Summary

Docker health checks with `depends_on` conditions eliminate the most
common startup failure in homelab deployments: services that start
before their dependencies.

The setup is minimal:

1. Add a `healthcheck:` block to each database service
2. Add `depends_on: db: condition: service_healthy` to each consumer
3. Use the database's native check command (`pg_isready`, `mysqladmin
   ping`, `redis-cli ping`) — not TCP port checks

No more `sleep 30` hacks. No more wait scripts. Your services start
when they're actually ready, not when Docker decides the container is
running.
