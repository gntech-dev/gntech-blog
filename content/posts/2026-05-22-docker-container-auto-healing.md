---
title: "Docker Container Auto-Healing for Homelab Deployments"
description: "Set up automatic recovery for unhealthy Docker containers in your homelab using docker-autoheal, custom watchdog scripts, systemd integration, and health check webhooks. No Kubernetes required."
date: 2026-05-22T14:30:00-04:00
tags:
  - docker
  - homelab
  - linux
  - selfhosting
  - monitoring
keywords:
  - Docker container auto-healing homelab
  - docker-autoheal unhealthy container restart
  - Docker HEALTHCHECK restart policy guide
  - systemd Docker container watchdog
  - container health monitoring auto-recovery
  - Uptime Kuma webhook container restart
  - self-healing Docker compose stack
summary: "Docker marks unhealthy containers but does not restart them. Build a self-healing homelab with docker-autoheal, systemd watchdog services, custom health scripts, and Uptime Kuma webhooks — no Kubernetes needed."
canonical: "https://gntech.dev/posts/docker-container-auto-healing/"
---

Docker's `HEALTHCHECK` instruction tells you when a container is
broken, but it does nothing about it. A PostgreSQL container
that loses its WAL directory, a web app stuck in a deadlock, or
a Redis instance that silently drops connections — all stay
running in an unhealthy state, serving errors until you notice
and restart them manually.

This is the single biggest reliability gap in standalone Docker
deployments. Kubernetes and Docker Swarm handle this natively,
but if you run plain Docker Compose stacks in your homelab, the
responsibility falls on you.

This guide covers every practical approach to container
auto-healing: from the simplest one-line solution to custom
watchdog scripts for edge cases. You will leave with a
self-healing setup that requires zero manual intervention for
common failure modes.

---

## Docker HEALTHCHECK: The Foundation

Auto-healing starts with good health checks. Without them, no
tool can distinguish a working container from a broken one.

### HEALTHCHECK in a Dockerfile

Embed health checks directly in images you build:

```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY . .

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/health || exit 1

CMD ["node", "server.js"]
```

For databases, use protocol-native checks:

```dockerfile
# PostgreSQL
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD pg_isready -U postgres || exit 1

# Redis
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD redis-cli ping | grep -q PONG || exit 1
```

### HEALTHCHECK at Runtime

For third-party images you cannot modify, pass health check
parameters when running the container:

```bash
docker run -d \
  --name my-app \
  --restart unless-stopped \
  --health-cmd="curl -f http://localhost:8080/health || exit 1" \
  --health-interval=15s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=30s \
  my-app:latest
```

### HEALTHCHECK in Docker Compose

The same pattern in Compose format:

```yaml
services:
  app:
    image: my-app:latest
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s

  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### Checking Health Status

```bash
# Quick status
docker inspect --format='{{.State.Health.Status}}' my-app

# Full health log
docker inspect --format='{{json .State.Health}}' my-app | jq

# Watch health transitions
docker events --filter 'event=health_status' --filter 'type=container'
```

Once these health checks are in place, you can detect failures.
The next step is acting on them.

---

## docker-autoheal: The Simple Solution

[willfarrell/docker-autoheal](https://github.com/willfarrell/docker-autoheal)
is a standalone container that watches Docker events for health
status changes and restarts unhealthy containers automatically.
It is the closest thing to native auto-healing for standalone
Docker.

### Deploy with Compose

```yaml
services:
  autoheal:
    image: willfarrell/autoheal:latest
    container_name: autoheal
    restart: unless-stopped
    environment:
      - AUTOHEAL_CONTAINER_LABEL=all
      - AUTOHEAL_INTERVAL=10
      - AUTOHEAL_START_PERIOD=30
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

This restarts **every container** that becomes unhealthy. For
finer control, label specific containers:

```yaml
services:
  app:
    image: my-app:latest
    labels:
      - autoheal=true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 15s
      retries: 3
      start_period: 30s
```

Then set `AUTOHEAL_CONTAINER_LABEL=autoheal` instead of `all`.

### Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOHEAL_CONTAINER_LABEL` | `autoheal` | Label to filter containers, or `all` |
| `AUTOHEAL_INTERVAL` | `5` | Seconds between health check polls |
| `AUTOHEAL_START_PERIOD` | `0` | Seconds to wait before monitoring |
| `AUTOHEAL_DOCKER_SOCK` | unset | Path to Docker socket inside container |

### Pros and Cons

**Pros:**
- One Docker Compose service, zero config
- Works with any container that has HEALTHCHECK
- Respects restart policies after restart
- Active project, updated regularly

**Cons:**
- Requires mounting the Docker socket (security consideration)
- Race condition if the container restarts itself during heal
- No notification when auto-heal fires

---

## Custom Watchdog Script with Docker API

If you want more control or no-socket alternatives, write a
watchdog script using the Docker SDK. This approach also lets
you add notifications, rate limiting, and selective restart
logic.

### Python Watchdog with Slack Alerts

```python
#!/usr/bin/env python3
"""Watchdog: restart unhealthy containers and notify."""

import os
import time
import subprocess
import json
import requests

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "15"))

def notify(container_name, status):
    if not SLACK_WEBHOOK:
        return
    message = f"🚨 *{container_name}* is *{status}* — restarting..."
    requests.post(SLACK_WEBHOOK, json={"text": message})

def get_health_status():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}} {{.Names}} {{.Status}}"],
        capture_output=True, text=True, timeout=10
    )
    unhealthy = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3 and "(unhealthy)" in line:
            unhealthy.append({"id": parts[0], "name": parts[1]})
    return unhealthy

def restart_container(name):
    subprocess.run(
        ["docker", "restart", name],
        capture_output=True, timeout=30
    )

if __name__ == "__main__":
    while True:
        for c in get_health_status():
            print(f"[{time.ctime()}] Restarting unhealthy: {c['name']}")
            notify(c["name"], "unhealthy")
            restart_container(c["name"])
            # Cooldown: avoid restart loops
            time.sleep(30)
        time.sleep(CHECK_INTERVAL)
```

Run it as a systemd service:

```ini
[Unit]
Description=Docker auto-heal watchdog
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/docker-watchdog.py
Restart=always
RestartSec=10
Environment=CHECK_INTERVAL=15

[Install]
WantedBy=multi-user.target
```

### Bash Watchdog (Minimal)

For a lighter alternative without Python dependencies:

```bash
#!/bin/bash
while true; do
  for container in $(docker ps --filter "health=unhealthy" --format "{{.Names}}"); do
    echo "$(date) - Restarting unhealthy container: $container"
    docker restart "$container"
  done
  sleep 15
done
```

---

## systemd Docker Service Watchdog

For **critical infrastructure containers** (DNS, reverse proxy,
VPN), bypass Docker's health check entirely and use systemd to
manage the container as a service.

### Create a systemd Service for a Container

```ini
[Unit]
Description=Traefik reverse proxy (managed via systemd)
After=docker.service
Requires=docker.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/docker rm -f traefik
ExecStart=/usr/bin/docker run --rm \
  --name traefik \
  --network=proxy \
  -p 80:80 -p 443:443 \
  -v /opt/traefik/traefik.yml:/etc/traefik/traefik.yml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  traefik:v3.2
ExecStop=/usr/bin/docker stop -t 10 traefik
ExecStopPost=/usr/bin/docker rm -f traefik

[Install]
WantedBy=multi-user.target
```

The key advantages:

- **systemd restarts**: if the Docker daemon fails or restarts,
  systemd respawns the container automatically.
- **Rate limiting**: `StartLimitIntervalSec` and
  `StartLimitBurst` prevent restart loops.
- **Logging**: container logs go to the systemd journal.
- **Health depends on process**: if the container process exits,
  systemd restarts it regardless of Docker restart policies.

### systemd Health Check Extension

You can combine systemd with a timer unit that checks the
container health and restarts the service if unhealthy:

```ini
[Unit]
Description=Health check for traefik
[Timer]
OnCalendar=*-*-* *:0/5:00
Persistent=true
[Install]
WantedBy=timers.target
```

Service file:

```ini
[Unit]
Description=Verify Traefik health every 5 minutes
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'docker inspect --format="{{.State.Health.Status}}" traefik | grep -q healthy || systemctl restart docker-traefik.service'
```

---

## Uptime Kuma Webhook Restart Pattern

[Uptime Kuma](https://github.com/louislam/uptime-kuma) monitors
HTTP endpoints and can trigger webhooks on failure. Pair it with
a lightweight webhook receiver that restarts the failing
container.

### Deploy the Webhook Receiver

Create a simple webhook handler with a shell script:

```bash
#!/bin/bash
# /usr/local/bin/kuma-webhook.sh
PORT=${PORT:-8080}

echo "Listening on port $PORT for Kuma webhooks..."
while true; do
  request=$(nc -l -p "$PORT" -q 1 2>/dev/null)
  container=$(echo "$request" | grep -oP 'container=\K[a-zA-Z0-9_-]+')

  if [ -n "$container" ]; then
    echo "$(date) - Kuma alert: restarting $container"
    docker restart "$container"
  fi
done
```

Or use a dedicated webhook service like
[webhook](https://github.com/adnanh/webhook) with a minimal
config:

```yaml
# /etc/webhook/hooks.yaml
- id: restart-container
  execute-command: /usr/local/bin/restart-container.sh
  command-working-directory: /tmp
  response-message: "Restart triggered"
```

In Uptime Kuma, configure the monitor's **Notification** to send
a POST webhook to `http://your-watchdog:8080/hooks/restart-container`
with the container name in the payload.

---

## Self-Healing Docker Compose Stack: Complete Example

Here is a real-world auto-healing stack combining all the
techniques above:

```yaml
services:
  # Core database with native health check
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
    labels:
      - autoheal=true

  # Application with HTTP health endpoint
  app:
    image: my-app:latest
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8080:3000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
    labels:
      - autoheal=true

  # Auto-heal daemon
  autoheal:
    image: willfarrell/autoheal:latest
    restart: unless-stopped
    environment:
      - AUTOHEAL_CONTAINER_LABEL=autoheal
      - AUTOHEAL_INTERVAL=5
      - AUTOHEAL_START_PERIOD=30
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

secrets:
  db_password:
    file: ./secrets/db_password.txt

volumes:
  pgdata:
```

---

## Restart Policy Deep Dive

Docker provides four restart policies. Understanding their
interaction with auto-healing is critical:

| Policy | Behavior | Auto-Heal Required |
|--------|----------|--------------------|
| `no` | Never restart | Yes |
| `on-failure[:max-retries]` | Restart on non-zero exit | Yes (unhealthy ≠ exit) |
| `unless-stopped` | Restart unless manually stopped | Yes |
| `always` | Always restart | Yes |

**Key insight:** none of these trigger on health status. A
container exiting with code 0 then immediately entering an idle
loop will not restart — unless you add a HEALTHCHECK that fails
and an auto-heal mechanism that acts on it.

For containers that crash frequently, combine restart policies
with auto-heal:

```yaml
services:
  flaky-service:
    image: flaky:latest
    restart: on-failure:5
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 10s
      retries: 3
    labels:
      - autoheal=true
```

This handles both crash loops (Docker restart on exit) and stuck
processes (autoheal restart on unhealthy).

---

## Handling System Restarts and Daemon Failures

Auto-healing containers do nothing if the Docker daemon itself
crashes or the host reboots. For a fully self-healing setup:

### 1. Enable Docker Restart on Boot

```bash
systemctl enable --now docker
```

### 2. Use restart: unless-stopped on All Services

This ensures all containers restart after a daemon restart.

### 3. Use systemd for Critical Infrastructure

As described above, systemd services survive Docker daemon
failures better than pure Docker restart policies:

```bash
systemctl enable docker-traefik.service
```

### 4. Monitor the Auto-Heal Daemon Itself

The auto-heal container has no one to heal it. Use a simple cron
job or systemd timer:

```bash
# /etc/cron.d/autoheal-health
* * * * * root docker inspect --format='{{.State.Health.Status}}' autoheal | grep -q healthy && exit 0 || docker restart autoheal
```

Or run the watchdog script as a systemd service so systemd
restarts it if it crashes.

---

## Notification and Observability

When auto-heal fires, you want to know about it. Wire up
notifications to catch patterns before they become chronic:

### docker-autoheal with Webhook

docker-autoheal can call a webhook after each restart. Set the
`AUTOHEAL_WEBHOOK_URL` environment variable:

```yaml
services:
  autoheal:
    image: willfarrell/autoheal:latest
    environment:
      - AUTOHEAL_CONTAINER_LABEL=all
      - AUTOHEAL_WEBHOOK_URL=https://hooks.slack.com/services/xxx
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

### Log Aggregation

Forward Docker events to your logging stack:

```bash
docker events --filter 'event=health_status' --format '{{json .}}' | \
  while read event; do
    echo "$event" | logger -t docker-health
  done
```

### Prometheus Metrics

Expose container health as Prometheus metrics using
[prometheus-health-exporter](https://github.com/maxmcd/google-health-exporter)
or a custom exporter:

```bash
#!/bin/bash
# Simple health metrics exporter for Prometheus node_exporter textfile
while true; do
  echo "# HELP docker_container_health Docker container health status"
  echo "# TYPE docker_container_health gauge"
  docker ps --format '{{.Names}}\t{{.Status}}' | while IFS=$'\t' read name status; do
    case "$status" in
      *healthy*)   health=1 ;;
      *unhealthy*) health=0 ;;
      *)           health=-1 ;;
    esac
    echo "docker_container_health{container=\"$name\"} $health"
  done > /var/lib/node_exporter/textfile/docker_health.prom.$$
  mv /var/lib/node_exporter/textfile/docker_health.prom.$$ \
     /var/lib/node_exporter/textfile/docker_health.prom
  sleep 15
done
```

---

## When Not to Auto-Heal

Auto-healing is not always the right answer. Consider the
following before enabling it on every container:

- **Stateful databases**: restarting a corrupted database
  container may make things worse. Prefer manual investigation.
- **One-shot jobs**: containers that run to completion should
  not be auto-healed.
- **Rate-limited services**: if a container is unhealthy due to
  API rate limiting, restarting resets the timer but does not
  solve the root cause.
- **Config errors**: a container that fails at startup due to a
  bad config file will fail again after restart. Fix the config.

Use labels selectively. Apply `autoheal=true` only to containers
where automatic recovery is safe and desirable.

---

## Summary

Docker provides excellent health detection but no built-in
recovery. For a truly self-healing homelab:

1. **Add HEALTHCHECK** to every service — in Dockerfiles, Compose
   files, or runtime flags.
2. **Deploy docker-autoheal** for zero-config auto-restart on
   healthy labeled containers.
3. **Use systemd services** for critical infrastructure that
   must survive Docker daemon failures.
4. **Add notifications** — Slack, webhook, or Prometheus — so you
   know when auto-heal fires.
5. **Label selectively** — not every container should auto-heal.

The five minutes it takes to add health checks and auto-heal to
your Compose file pays for itself the first time a container
fails at 3 AM.
