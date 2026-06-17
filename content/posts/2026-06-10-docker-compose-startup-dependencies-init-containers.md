---
title: "Docker Compose Startup Dependencies and Init Container Patterns"
description: "Master Docker Compose startup ordering with depends_on, healthcheck conditions, and init container patterns for reliable multi-service homelab stacks."
date: 2026-06-10T14:30:00-04:00
tags:
  - docker
  - docker-compose
  - homelab
  - devops
  - containers
keywords:
  - Docker Compose depends_on startup ordering homelab guide
  - Docker init container pattern Compose healthcheck condition
  - Docker compose service dependency management best practices
  - wait-for-it script Docker container startup ordering
  - Docker Compose restart policy startup sequence multi-service
  - Docker compose healthcheck condition service_healthy
  - Docker compose startup order database migration pattern
summary: "A practical guide to Docker Compose startup ordering — covering depends_on conditions, healthcheck-based readiness, init container patterns with wait-for-it, and real-world compose examples for multi-service homelab stacks."
canonical: "https://blog.gntech.me/posts/docker-compose-startup-dependencies-init-containers/"
---

You write a shiny `compose.yml`, run `docker compose up -d`, and everything starts at once. Postgres is still initializing when your web app tries to connect. The migration container runs before the database accepts queries. Redis is listed as a dependency, but your cache-dependent service crashes three times before it finds the port open.

This is the startup order problem — and it is one of the most common pain points in homelab Docker deployments.

Docker Compose gives you the tools to solve it, but the defaults (`depends_on` without conditions) only guarantee container start order, not service readiness. This guide covers every option from basic to advanced: `depends_on` conditions, healthcheck-based gating, init container patterns, and the classic `wait-for-it` script approach.

## depends_on — What It Actually Does and Does Not Do

The simplest form of `depends_on` tells Compose to start one container after another:

```yaml
services:
  app:
    image: my-app:latest
    depends_on:
      - db
  db:
    image: postgres:17
```

Without any condition, `depends_on` only guarantees that the `db` container is *started* before `app`. It does **not** wait for Postgres to be ready to accept connections. On a fast machine with local volumes, this *usually* works. On a homelab with spinning disks or during first boot when databases initialize, it fails reliably.

Compose v2.20+ (included in Docker Desktop 4.25+ and Docker Engine 25+) supports conditional `depends_on`:

```yaml
services:
  app:
    image: my-app:latest
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
```

Three conditions are available:

- **`service_started`** — the default; starts after the dependency container is running  
- **`service_healthy`** — waits until the dependency passes its healthcheck  
- **`service_completed_successfully`** — waits until the dependency runs and exits with code 0 (init container pattern)

The `service_healthy` and `service_completed_successfully` conditions are what turn `depends_on` from a simple ordering hint into a real readiness gate.

## Healthcheck-Based Startup Ordering

The most reliable pattern for production is pairing `depends_on` with `healthcheck` on the dependency service. Docker runs the healthcheck command periodically and marks the container as `healthy` or `unhealthy`. The dependent service waits until `healthy` before starting.

Here is a complete example with Postgres, Redis, and a web application:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: myapp
      POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3
    restart: unless-stopped

  app:
    build: .
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://myapp:${DB_PASSWORD:-changeme}@postgres:5432/myapp
      REDIS_URL: redis://redis:6379
    restart: unless-stopped

volumes:
  pgdata:
```

Key decisions in this config:

- **`start_period: 30s`** gives Postgres time to initialize on first boot before healthcheck failures count toward `retries`. Without this, a cold Postgres init could exhaust retries before the server is ready.
- **`interval: 5s`** balances quick detection with reasonable overhead — every 5 seconds is fine for homelab, even with many containers.
- **`restart: unless-stopped`** ensures the application retries if it fails while waiting for dependencies. Compose starts the app, the healthcheck is still pending, the app crashes, Docker restarts it, and eventually the healthcheck passes.

### Starting Additional Dependencies by Service Type

Homelab stacks often need MariaDB or MySQL instead of Postgres:

```yaml
  mariadb:
    image: mariadb:11-lts
    environment:
      MARIADB_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MARIADB_DATABASE: myapp
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 60s
```

MariaDB's official image bundles `healthcheck.sh` with `--innodb_initialized` — safer than a raw MySQL ping because it also verifies InnoDB recovery completed.

## Init Container Pattern in Docker Compose

Kubernetes has native init containers: they run to completion before the main pod starts. Docker Compose has no built-in init container type, but you can simulate the pattern cleanly with `depends_on` and `condition: service_completed_successfully`.

Use this for:

- Database schema migrations (Alembic, Flyway, Prisma)
- Seed data loading
- Terraform / Pulumi provisioning
- File permission setup on shared volumes

Here is a real example with Alembic migrations for a FastAPI app:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: myapp
      POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 30s
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  migrations:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgres://myapp:${DB_PASSWORD:-changeme}@postgres:5432/myapp
    command: alembic upgrade head
    # This service runs once and exits — no restart needed

  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
    depends_on:
      migrations:
        condition: service_completed_successfully
    environment:
      DATABASE_URL: postgres://myapp:${DB_PASSWORD:-changeme}@postgres:5432/myapp
    restart: unless-stopped

volumes:
  pgdata:
```

The chain is: `postgres` becomes healthy → `migrations` runs `alembic upgrade head` and exits 0 → `app` starts knowing the schema is current.

For multi-step init, chain multiple init services:

```yaml
services:
  db-seed:
    build: ./seed
    depends_on:
      migrations:
        condition: service_completed_successfully
    command: node /app/seed.js

  app:
    depends_on:
      db-seed:
        condition: service_completed_successfully
```

## The wait-for-it and wait-for Scripts

Not every image ships with a healthcheck. For third-party images you cannot modify, the `wait-for-it.sh` script (or the simpler `wait-for`) is a practical fallback.

### wait-for-it

Available at [vishnubob/wait-for-it](https://github.com/vishnubob/wait-for-it), this bash script blocks until a TCP port is open:

```yaml
services:
  app:
    image: my-app:latest
    depends_on:
      - db
    volumes:
      - ./wait-for-it.sh:/wait-for-it.sh
    command: ["./wait-for-it.sh", "db:5432", "--", "node", "app.js"]
```

The script polls `db:5432` until it accepts a TCP connection, then executes the command.

### wait-for (Efficient Python Alternative)

The [wait-for](https://github.com/eficode/wait-for) script is a shorter, POSIX-sh alternative that works on Alpine:

```yaml
  app:
    image: alpine:3.21
    depends_on:
      - db
      - redis
    volumes:
      - ./wait-for:/wait-for
    command: >
      sh -c "/wait-for db:5432 -- /wait-for redis:6379 -- node app.js"
```

**Important**: Port-open checks have a race condition. The TCP port can be open before the service is ready (Postgres immediately opens the port, but may reject queries for several seconds during crash recovery). Healthchecks are strictly better. Use port-waiting only when you cannot add a healthcheck.

## Advanced Patterns for Complex Stacks

### Chained Dependencies

```yaml
services:
  db:
    image: postgres:17-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
    restart: unless-stopped

  cache:
    image: redis:7-alpine
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
    restart: unless-stopped

  api:
    build: ./api
    depends_on:
      cache:
        condition: service_healthy
    restart: unless-stopped
```

### Conditional Startup with Profiles

Use Compose profiles to control which services start normally vs. on-demand:

```yaml
services:
  migrations:
    profiles: ["setup"]
    build: .
    depends_on:
      db:
        condition: service_healthy
    command: alembic upgrade head

  app:
    depends_on:
      migrations:
        condition: service_completed_successfully
    build: .
    ports: ["8080:8080"]
```

Run migrations explicitly: `docker compose --profile setup run migrations`. Without the profile flag, `migrations` is skipped, and `app` starts immediately. This pattern is useful when you manage migrations manually.

### Handling Stale Health States

Occasionally Compose caches a stale health check status. When this happens, a container shows as healthy when it is not:

```bash
docker compose down -v && docker compose up -d
```

If the issue persists, check the health status explicitly:

```bash
docker inspect --format='{{.State.Health.Status}}' container_name
```

For a full reset of all health state, restart the Docker daemon — though this is rarely needed.

## Summary and Best Practices

Here is a decision tree for Docker Compose startup ordering in your homelab:

| Situation | Pattern | Condition |
|---|---|---|
| Dependencies start fast (local Alpine images, no init) | `depends_on:` (bare) | `service_started` |
| Database needs to accept queries | `healthcheck` + `depends_on condition` | `service_healthy` |
| Migration must run before app starts | Init container | `service_completed_successfully` |
| Third-party image, no healthcheck | `wait-for-it.sh` | Port check |
| Complex multi-service dependency chain | Chained healthchecks | `service_healthy` each |

**Start with healthchecks and `depends_on condition: service_healthy`.** This covers 80% of homelab scenarios. Add the init container pattern for database migrations. Use `wait-for-it` only as a last resort for images you cannot modify.

Set reasonable `start_period` values — 30-60 seconds for databases, 10 seconds for caches. Use `restart: unless-stopped` on all services that have dependencies so they retry automatically after a crash.

Your Compose stack will boot reliably every time, whether it is the first deploy on bare metal or a restart after a power outage.
