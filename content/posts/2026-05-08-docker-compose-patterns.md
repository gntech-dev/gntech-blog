---
title: "Docker Compose Patterns for Homelab Stacks"
description: "Practical Docker Compose patterns for running multi-service stacks in a homelab — environment management, networking, secrets, health checks, backups, and real configs from an existing Proxmox deployment."
date: 2026-05-08T12:00:00-04:00
tags:
  - docker
  - docker-compose
  - containers
  - homelab
  - devops
categories:
  - homelab
  - containers
---

Docker Compose is the default orchestration tool for most homelab setups. It's not Kubernetes, but it doesn't need to be — a well-structured Compose file with proper environment management, networking, and health checks will serve a single-host stack for years without drama.

This post covers the patterns I use across my Proxmox Docker hosts. These aren't theoretical — they're what's running right now on the homelab.

> **Note:** Some examples are partial Compose snippets meant to demonstrate one pattern at a time. When copying them into a real `compose.yml`, make sure referenced services, images, secrets, volumes, and networks are also defined.

---

## Directory Layout

Every service gets its own directory with a consistent structure:

```
/opt/docker/
├── frigate/
│   ├── compose.yml
│   ├── .env
│   ├── config/
│   │   ├── config.yml
│   │   └── mosquitto/
│   └── storage/
├── cloudflared/
│   ├── compose.yml
│   └── .env
├── uptime-kuma/
│   ├── compose.yml
│   ├── .env
│   └── data/
├── nginx/
│   ├── compose.yml
│   ├── .env
│   ├── conf.d/
│   └── certs/
└── shared/
    └── .env  (common env vars)
```

Each stack is self-contained. No monorepo-style mega `docker-compose.yml` with 20 services — you lose the ability to restart services independently and the file becomes unreadable.

**Rule:** One compose file per domain. Frigate is its own compose. Nginx proxy is its own compose. Monitoring stack is its own compose. If two services genuinely depend on each other (e.g., Grafana + Prometheus + Loki), bundle them in one compose.

---

## Compose File Template

```yaml
# /opt/docker/example-service/compose.yml
services:
  app:
    image: example/image:latest
    container_name: example-app
    restart: unless-stopped
    environment:
      - TZ=${TZ:-America/Santo_Domingo}
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
    volumes:
      - ./data:/data
      - /etc/localtime:/etc/localtime:ro
    networks:
      - internal
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  internal:
    driver: bridge
    internal: true  # no external access unless explicitly added
```

Key points:

- **`container_name`** — explicit naming avoids confusion when `docker ps` shows 10 containers
- **`restart: unless-stopped`** — recovers from crashes and host reboots, but respects manual `docker stop`
- **`volumes`** always use relative paths (`./data`) — the compose file is the source of truth for data locations
- **`networks: internal: true`** by default — services don't need internet access unless you add an external network
- **`healthcheck`** — critical for depend-on conditions and monitoring
- **`logging`** with rotation — prevents /var from filling up

---

## Environment Management

### The .env File

Docker Compose automatically loads `.env` from the same directory as the compose file. Use it for variable data — secrets, ports, versions:

```bash
# /opt/docker/frigate/.env
TZ=America/Santo_Domingo
FRIGATE_VERSION=stable
MQTT_USER=frigate
MQTT_PASSWORD=<secret>
CAMERA_USER=<secret>
CAMERA_PASSWORD=<secret>
```

The compose file references these with `${VAR}` syntax:

```yaml
services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:${FRIGATE_VERSION:-stable}
    environment:
      - FRIGATE_MQTT_USER=${MQTT_USER}
      - FRIGATE_MQTT_PASSWORD=${MQTT_PASSWORD}
```

**Never commit `.env` to git.** Add it to `.gitignore`. Instead, commit `.env.example` with placeholder values:

```bash
# .env.example — copy to .env and fill in secrets
TZ=America/Santo_Domingo
FRIGATE_VERSION=stable
MQTT_USER=frigate
MQTT_PASSWORD=change-me
CAMERA_PASSWORD=change-me
```

### Shared .env Across Stacks

When multiple stacks need the same values (timezone, UID/GID, internal domain), use a shared `.env`:

```bash
# /opt/docker/shared/.env
TZ=America/Santo_Domingo
PUID=1000
PGID=1000
DOCKER_NET=10.0.20.0/24
DOMAIN=lab.gntech.me
```

Reference it in each compose file with `env_file`:

```yaml
services:
  app:
    env_file:
      - ../shared/.env
      - ./.env  # local overrides take precedence
```

The shared `.env` defines common defaults. Each stack's local `.env` overrides or adds secrets.

---

## Networking Patterns

### Internal Bridge (Default)

Most services don't need direct network access. Use an internal bridge:

```yaml
networks:
  internal:
    driver: bridge
    internal: true
```

Services can talk to each other by service name (Compose DNS resolution), but nothing from outside the Docker network can reach them — including other Docker containers on the same host.

### External Network for Inter-Stack Communication

When service A needs to talk to service B across different compose stacks (e.g., Frigate → MQTT), create a shared external network:

```bash
# Create once
docker network create shared-net
```

```yaml
# compose.yml for frigate
services:
  frigate:
    networks:
      - internal
      - shared

networks:
  internal:
    driver: bridge
    internal: true
  shared:
    external: true
    name: shared-net
```

```yaml
# compose.yml for mosquitto (separate stack)
services:
  mosquitto:
    networks:
      - internal
      - shared

networks:
  internal:
    driver: bridge
  shared:
    external: true
    name: shared-net
```

Now Frigate can reach Mosquitto by service name (`mosquitto`) even though they're in different compose stacks, as long as they're on the same Docker host.

### MACVLAN for Direct VLAN Access

For services that need to live on a specific physical VLAN (e.g., Frigate on VLAN 50 for CCTV, or a reverse proxy on the same subnet as your LAN), use a MACVLAN network:

```yaml
networks:
  cctv:
    driver: macvlan
    driver_opts:
      parent: eth0.50  # host VLAN interface
    ipam:
      config:
        - subnet: 10.0.50.0/24
          gateway: 10.0.50.1
          ip_range: 10.0.50.200/28
```

The container gets its own MAC and IP on VLAN 50. It looks like a physical device to the rest of the network. This is how Frigate connects directly to cameras without NAT.

**Caveat:** MACVLAN doesn't allow host-to-container communication unless you add a second network or use `ipvlan`. The container can reach the network but the Docker host can't reach it via the MACVLAN IP. Use a second internal network for host-to-container access if needed.

### Host Network Mode (Use Sparingly)

```yaml
services:
  adguard:
    network_mode: host
```

The container shares the host's network stack — no bridge, no port mapping. Useful for DNS servers (need port 53 on host), but avoid it for most services. It breaks Compose DNS resolution and isolation.

---

## Health Checks and Dependencies

### Health Checks

Every service that exposes an HTTP endpoint should have a health check:

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

For services without HTTP (databases):

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres || exit 1"]
  interval: 15s
  timeout: 5s
  retries: 5
```

### depends_on

Use `condition: service_healthy` for hard dependencies:

```yaml
services:
  app:
    depends_on:
      db:
        condition: service_healthy
  db:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
```

This is better than a raw `depends_on` (which only waits for the container to start, not for the service inside it to be ready). Compose v2.20+ supports this natively.

---

## Secrets and Configuration

### Avoid Environment Variables for Secrets

Environment variables leak into `docker inspect`, logs, and child processes. For sensitive values (API keys, database passwords):

**Option 1: Docker Secrets (Swarm mode only)**

```yaml
secrets:
  db_password:
    file: ./secrets/db_password.txt

services:
  app:
    secrets:
      - db_password
    environment:
      - DB_PASSWORD_FILE=/run/secrets/db_password
```

The secret is mounted as a file at `/run/secrets/db_password` inside the container. Other processes can't read it via `/proc`.

**Option 2: File-based Config**

```yaml
services:
  app:
    volumes:
      - ./config.yml:/app/config.yml:ro
```

Read-only bind mounts for config files are the simplest approach. The config file lives outside the image — you edit it, restart the service, it picks up the changes.

**Option 3: .env (acceptable for local homelab)**

For a single-user homelab where the threat model is "internet randos, not physical attackers," `.env` files are fine. Just don't commit them.

### Config File Management

Keep configuration in the compose directory, organized by service:

```
/opt/docker/frigate/
├── compose.yml
├── .env
├── config/
│   ├── config.yml
│   ├── mosquitto/
│   │   └── mosquitto.conf
│   └── pwfile
└── storage/
    ├── recordings/
    └── clips/
```

The compose file mounts these as read-only when possible:

```yaml
volumes:
  - ./config/config.yml:/config/config.yml:ro
  - /etc/localtime:/etc/localtime:ro
```

Read-only mounts prevent the container from modifying its own config — a common source of "why did my config change" confusion.

---

## Volume Management

### Named Volumes vs Bind Mounts

| Aspect | Named Volume | Bind Mount |
|--------|-------------|------------|
| Managed by | Docker | User |
| Location | `/var/lib/docker/volumes/` | Anywhere |
| Backup | Needs extra step | Straight file copy |
| Permissions | Docker handles them | Host permissions apply |
| Sharing across hosts | Needs volume driver | NFS/Samba works |

**Use bind mounts for configuration** (you edit config files directly). **Use named volumes for databases and state** (easier to manage, Docker handles permissions):

```yaml
services:
  postgres:
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro

volumes:
  pgdata:
```

### Backing Up Bind Mounts

Since bind mounts are just directories on the host, backup is a simple rsync or ZFS snapshot:

```bash
# ZFS dataset for docker data
zfs snapshot tank/docker@weekly

# Or plain rsync to backup target
rsync -av /opt/docker/ backup-host:/backups/docker/
```

For databases with named volumes, use `docker run --volumes-from` or pg_dump:

```bash
# Dump a Postgres database from a named volume container
docker exec postgres pg_dump -U myuser mydb > backup.sql
```

---

## Logging

Default Docker logging writes to a JSON file per container without rotation — it will fill your disk given enough time.

### Per-Service Logging

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

This keeps at most 30 MB of logs per service — 3 files × 10 MB each. Tune `max-size` based on how chatty the service is. Frigate logs are verbose; 10m works. A DNS server might need 5m.

### Centralized Logging (Optional)

For the serious homelab, forward logs to Loki + Grafana:

```yaml
logging:
  driver: "loki"
  options:
    loki-url: "http://loki:3100/loki/api/v1/push"
    loki-retries: "2"
    max-size: "50m"
```

Requires the Loki Docker driver plugin. Overkill for a single-host lab, but nice if you have multiple hosts.

---

## Version Pinning

Always pin major/minor versions. `:latest` will break your stack at 3 AM when the upstream maintainer changes something:

```yaml
# Good
image: postgres:17-alpine
image: nginx:1.27-alpine
image: grafana/grafana:11.5

# Risky
image: postgres:latest
image: nginx:latest
```

Use Renovate or Dependabot to get PRs when updates are available — review and update deliberately instead of waking up to a broken service.

For immich and similar fast-moving projects, pin to a specific release (e.g., `immich/server:v1.120.0`). For stable projects like Nginx or Postgres, the minor version tag (`nginx:1.27`) is sufficient.

---

## Backup Strategy for Compose Stacks

### The Three-Layer Approach

```
Layer 1: Compose files + config  → git repo
Layer 2: Persistent data          → ZFS snapshots + rsync
Layer 3: Database dumps          → cron + rclone
```

**Layer 1** is the compose definition itself. Push to a private git repo:

```bash
cd /opt/docker
git init && git add */compose.yml */config */.env.example
git commit -m "Initial docker stacks"
```

`.env` files with secrets stay in `.gitignore`. Everything else is versioned.

**Layer 2** uses ZFS snapshots on the dataset hosting `/opt/docker`:

```bash
zfs snapshot tank/docker@$(date +%Y%m%d_%H%M)
```

Sanoid handles automatic rotation (covered in the [ZFS post](/posts/2026-05-08-zfs-snapshot-strategies/)).

**Layer 3** is a nightly cron that dumps databases and syncs to offsite storage:

```bash
#!/bin/bash
# /etc/cron.d/docker-backup
0 4 * * * root /opt/scripts/docker-backup.sh

# /opt/scripts/docker-backup.sh
BACKUP_DIR=/tank/backup/docker-dumps
mkdir -p "$BACKUP_DIR"

# Dump each database
docker exec postgres pg_dump -U homelab homelab_db | \
    gzip > "$BACKUP_DIR/homelab_db_$(date +%Y%m%d).sql.gz"

# Keep 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
```

---

## Resource Limits

Don't let one noisy container starve the rest. Set resource limits:

```yaml
services:
  heavy-service:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

In Compose v2, `deploy.resources` works in standalone mode (not just Swarm). The container won't exceed 2 CPU cores or 2 GB RAM.

For simpler setups, use Docker run flags mapped in compose:

```yaml
services:
  app:
    mem_limit: 1g
    mem_reservation: 512m
    cpus: 1.5
```

These are Docker Compose v2 native keys. Pick one style and stick with it.

---

## Real Stack — Monitoring

Here's a complete monitoring stack demonstrating these patterns:

```yaml
# /opt/docker/monitoring/compose.yml
services:
  uptime-kuma:
    image: louislam/uptime-kuma:1
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=${TZ}
    healthcheck:
      test: ["CMD", "node", "server/server.js", "--health-check"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  grafana:
    image: grafana/grafana:11.5
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    environment:
      - TZ=${TZ}
      - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_admin
    secrets:
      - grafana_admin
    depends_on:
      loki:
        condition: service_healthy
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  loki:
    image: grafana/loki:3.4
    container_name: loki
    restart: unless-stopped
    volumes:
      - ./loki/config.yml:/etc/loki/config.yml:ro
      - loki-data:/loki
    ports:
      - "3100:3100"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3100/ready"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  prometheus:
    image: prom/prometheus:v3.2
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    network_mode: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'

volumes:
  grafana-data:
  loki-data:
  prometheus-data:

secrets:
  grafana_admin:
    file: ./secrets/grafana_admin.txt
```

This stack uses:

- **Environment files** for TZ
- **Docker secrets** for the Grafana admin password
- **Read-only config mounts** for Loki, Prometheus, and Grafana provisioning
- **Named volumes** for database/state (Grafana, Loki, Prometheus)
- **Health checks** on Loki and Uptime Kuma
- **Resource limits** (would add them on a constrained host)
- **Log rotation** on every service
- **Host network mode** for node-exporter (needs host metrics)

---

## Compose File Checklist

Before deploying a new stack:

- [ ] `container_name` is set (don't rely on auto-generated names)
- [ ] `restart: unless-stopped` (or `always` for essential infrastructure)
- [ ] Image tag is pinned (no `:latest` without deliberate reasoning)
- [ ] `.env` file exists and is in `.gitignore`
- [ ] `volumes` use relative paths (`./data`) or named volumes
- [ ] Config files are mounted `:ro` where possible
- [ ] `healthcheck` is defined for service dependencies
- [ ] `logging` has rotation limits (`max-size`, `max-file`)
- [ ] Ports are only exposed when necessary (not publishing every port)
- [ ] Network is `internal: true` unless external access is required
- [ ] Secrets are in files, not env vars (or at least in `.env`, not compose)

---

## Summary

| Pattern | When to Use |
|---------|------------|
| One compose per domain | Always — keeps files readable and manageable |
| `.env` for config | Every stack — separates config from compose |
| External networks | Cross-stack communication (Frigate→MQTT, Grafana→Loki) |
| MACVLAN | Services on a specific physical VLAN (cameras, proxy) |
| Health checks | Services others depend on (databases, APIs) |
| Read-only mounts | Config files — prevents accidental modification |
| Named volumes | Database state, application data |
| Image pinning | Always — `:latest` will bite you |
| Resource limits | Constrained hosts or noisy neighbors |
| Git for compose files | Version control your infrastructure |

Docker Compose won't scale to a 100-node cluster, but for a single-host homelab it's the sweet spot between complexity and control. A well-structured compose file with proper env management and health checks will run reliably for years — and when you need to rebuild, it's `docker compose up -d` and you're back.
