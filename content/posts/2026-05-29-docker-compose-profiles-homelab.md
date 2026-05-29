---
title: "Docker Compose Profiles — Selective Service Management for Homelab"
description: "Master Docker Compose profiles to manage multi-service homelab stacks — selective startup, dev vs prod profiles, per-service configs, and real-world docker-compose.yml examples."
date: 2026-05-29T16:00:00-04:00
tags:
  - docker
  - devops
  - homelab
  - orchestration
keywords:
  - Docker Compose profiles homelab multi-service management
  - Docker Compose profiles selective service startup
  - Docker Compose profiles dev production examples
  - Docker Compose profiles homelab docker-compose.yml configuration
  - Docker Compose profiles conditional service deployment
  - Docker Compose profiles monitoring profile compose example
  - Docker Compose profiles infrastructure management guide
summary: "Learn how Docker Compose profiles let you start only the services you need — enable monitoring, disable dev tools in production, and keep a single docker-compose.yml for your entire homelab stack."
canonical: "https://blog.gntech.me/posts/docker-compose-profiles-homelab/"
---

Your homelab's `docker-compose.yml` starts small. Traefik, PostgreSQL,
maybe a Redis cache. Then you add Grafana for dashboards. Prometheus
and Node Exporter for metrics. Loki collects container logs. Adminer
makes database queries convenient. Portainer gives you a web UI for
containers. Watchtower auto-updates everything.

Suddenly you have twenty services in one file, and `docker compose up`
starts *every single one*. Your 8 GB Proxmox LXC hits swap before
you can disable the monitoring stack you only need for debugging.
The dev tools you forgot to stop eat RAM all night.

Docker Compose profiles fix this. They let you tag services into
groups and start only the groups you need. Same compose file, zero
duplication, full control over what runs when.

## How Docker Compose Profiles Work

The `profiles` attribute on a service defines which profile names
activate it. A service with no profiles always starts with a plain
`docker compose up`. A service with at least one profile only starts
when that profile is explicitly requested.

```yaml
services:
  app:
    image: nginx:alpine
    profiles: ["frontend"]
    ports:
      - "8080:80"

  db:
    image: postgres:16-alpine
    # no profiles — always starts with `docker compose up`
    environment:
      POSTGRES_PASSWORD: changeme
```

Run `docker compose up -d` and only `db` starts. Run
`docker compose --profile frontend up -d` and both services start.

This small mechanism unlocks a clean organization pattern for homelabs
running a dozen or more containers on a single Docker host.

## Homelab Infrastructure Stack with Profiles

The most practical setup defines service tiers as profiles. Core
infrastructure runs automatically. Monitoring, dev tools, and batch
jobs start on demand.

Here is the complete structure I run on a Proxmox LXC at home:

```yaml
# /opt/homelab/docker-compose.yml
services:
  # === Always-on core services ===
  traefik:
    image: traefik:v3.3
    container_name: homelab-traefik
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik:/etc/traefik:ro
    ports:
      - "80:80"
      - "443:443"

  postgres:
    image: postgres:16-alpine
    container_name: homelab-postgres
    restart: unless-stopped
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?err}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: homelab-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data

  # === Infrastructure profile — dashboards and observability ===
  prometheus:
    image: prom/prometheus
    container_name: homelab-prometheus
    profiles: ["infra", "monitoring"]
    restart: unless-stopped
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus-data:/prometheus

  grafana:
    image: grafana/grafana
    container_name: homelab-grafana
    profiles: ["infra"]
    restart: unless-stopped
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro

  loki:
    image: grafana/loki:3.4
    container_name: homelab-loki
    profiles: ["infra"]
    restart: unless-stopped
    volumes:
      - ./loki:/etc/loki:ro
      - loki-data:/loki

  # === Monitoring agent profile — per-host exporters ===
  node-exporter:
    image: prom/node-exporter
    container_name: homelab-node-exporter
    profiles: ["monitoring"]
    restart: unless-stopped
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - "--path.procfs=/host/proc"
      - "--path.rootfs=/rootfs"
      - "--path.sysfs=/host/sys"

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    container_name: homelab-cadvisor
    profiles: ["monitoring"]
    restart: unless-stopped
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro

  # === Dev tools profile — admin interfaces ===
  adminer:
    image: adminer
    container_name: homelab-adminer
    profiles: ["dev"]
    restart: unless-stopped
    ports:
      - "127.0.0.1:8081:8080"

  portainer:
    image: portainer/portainer-ce:2-lts
    container_name: homelab-portainer
    profiles: ["dev"]
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - portainer-data:/data
    ports:
      - "127.0.0.1:9000:9000"

  # === Batch profile — periodic housekeeping ===
  watchtower:
    image: containrrr/watchtower
    container_name: homelab-watchtower
    profiles: ["batch"]
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_SCHEDULE: "0 0 4 * * *"
      WATCHTOWER_INCLUDE_STOPPED: "false"

volumes:
  pgdata:
  redis-data:
  prometheus-data:
  grafana-data:
  loki-data:
  portainer-data:
```

### What This Setup Achieves

| Profile | Services | Start Command | When to Use |
|---------|----------|--------------|-------------|
| *(none)* | Traefik, PostgreSQL, Redis | `docker compose up -d` | Always on — boot with the host |
| `infra` | Prometheus, Grafana, Loki | `--profile infra` | Daily monitoring |
| `monitoring` | Node Exporter, cAdvisor | `--profile monitoring` | Debug or capacity planning |
| `dev` | Adminer, Portainer | `--profile dev` | Active development sessions |
| `batch` | Watchtower | `--profile batch` | Nightly updates |

## Startup Commands for Day-to-Day Usage

Start the core stack at boot:

```bash
docker compose up -d
```

Add the infrastructure dashboard stack:

```bash
docker compose --profile infra up -d
```

Fire up everything for a maintenance session:

```bash
docker compose --profile infra --profile monitoring --profile dev up -d
```

The `--profile` flag accepts multiple values by repeating it. You
can combine any set of profiles depending on what you need right now.

Start *every* profiled and unprofiled service at once:

```bash
docker compose --profile '*' up -d
```

Stop all monitoring services without touching the core stack:

```bash
docker compose --profile monitoring down
```

## Dev vs Production Profiles

Profiles pair naturally with environment-specific overrides. A
typical dev setup exposes database ports and includes query browsers
that should never appear in production.

```yaml
# docker-compose.override.yml — loaded automatically by Compose
services:
  postgres:
    profiles: ["dev"]
    ports:
      - "127.0.0.1:5432:5432"

  redis:
    profiles: ["dev"]
    ports:
      - "127.0.0.1:6379:6379"
```

Now `docker compose --profile dev up -d` starts the core stack and
exposes database ports for external tools like DBeaver or psql.
Without the `--profile dev` flag, the databases run but remain
inaccessible from the Docker host — exactly what you want in
production.

This pattern also works for service variants. Use different images
or tags per profile:

```yaml
services:
  app:
    image: myapp:${APP_TAG:-latest}
    profiles: ["prod"]

  app-dev:
    image: myapp:develop
    profiles: ["dev"]
    ports:
      - "3000:3000"
    volumes:
      - ./src:/app/src:ro
```

## Splitting Large Compose Files with Includes

When a single compose file grows past 300 lines, split it by
profile domain using Docker Compose includes (Compose v2.30+):

```yaml
# /opt/homelab/docker-compose.yml
services:
  traefik:
    # core services here

include:
  - ./infra/monitoring.yml
  - ./infra/devtools.yml
  - ./batch/watchtower.yml
```

Each included file defines its own services with profiles:

```yaml
# /opt/homelab/infra/monitoring.yml
services:
  prometheus:
    image: prom/prometheus
    profiles: ["infra"]

  grafana:
    image: grafana/grafana
    profiles: ["infra"]
```

Profiles work identically across includes — `--profile infra` starts
all services tagged with `infra` regardless of which file they
live in.

## Best Practices for Docker Compose Profiles in Homelab

1. **Default services stay unprofiled.** If a service must run for the
   homelab to function (reverse proxy, auth, database), do not assign a
   profile. It starts automatically.

2. **Name profiles by purpose, not by service.** Use `monitoring`,
   `dev`, `batch`, `experimental` — not `grafana`, `prometheus`, `adminer`.
   This keeps the profile count manageable and the intent clear.

3. **Start everything at boot with `--profile '*'` in your systemd
   service or init script.** The host reboot starts all containers
   regardless of profile:

   ```ini
   # /etc/systemd/system/docker-homelab.service
   [Unit]
   Description=Docker Compose Homelab
   Requires=docker.service
   After=docker.service

   [Service]
   Type=oneshot
   RemainAfterExit=yes
   WorkingDirectory=/opt/homelab
   ExecStart=/usr/bin/docker compose --profile '*' up -d
   ExecStop=/usr/bin/docker compose --profile '*' down
   User=root

   [Install]
   WantedBy=multi-user.target
   ```

4. **Document the profile assignment** in your README or as a comment
   at the top of each compose file. When you return to a project
   after six months, you want to know `--profile monitoring` starts
   which services.

5. **Use environment variables for profile-level configuration.**
   Set `MONITORING_ENABLED=true` in your `.env` and use it to
   conditionally include files or configure service parameters.

## Troubleshooting Common Profile Issues

**Container won't start with `docker compose up`**

Check that the service has a profile. Services with a `profiles`
list are excluded from the default `up`. Start them with
`--profile <name>`.

**Service with `depends_on` fails because its dependency has a
profile**

Compose does not automatically activate profiles for dependencies.
If service A (profiled) depends on service B (profiled), you must
pass both profiles:

```bash
docker compose --profile monitoring --profile infra up -d
```

**Listing which services belong to each profile**

```bash
docker compose config --services
```

Services without profiles appear in the default output. Add
`--profile` to see profiled services:

```bash
docker compose --profile monitoring config --services
```

**Check if a profile is active**

```bash
docker compose --profile dev ps
```

## Conclusion

Docker Compose profiles solve a real problem for growing homelabs.
Instead of maintaining multiple compose files, environment-specific
overrides, or commenting services in and out, you tag each service
with a profile name and start only what you need.

The monitoring stack starts when you want to debug. Dev tools run
only during development sessions. Batch jobs execute on a schedule.
Core infrastructure stays up without interference.

One compose file, one directory, multiple service groups. Your RAM
budget — and your future self — will thank you.

---

### See Also

- [Docker Compose Production Patterns](/posts/docker-compose-production-patterns/)
- [Docker Compose Networking Patterns](/posts/docker-compose-networking-patterns/)
- [Docker Container Resource Limits](/posts/docker-container-resource-limits/)
