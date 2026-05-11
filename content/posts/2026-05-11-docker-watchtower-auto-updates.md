---
title: "Auto-Update Docker Containers — Watchtower with Selective Rules, Notifications, and Graceful Rollouts"
description: "Watchtower deployment for automatic Docker container updates — selective update rules, Telegram notifications, manual rollback, and zero-downtime strategies. All configs, no theory."
date: 2026-05-11T11:00:00-04:00
tags:
  - docker
  - homelab
  - automation
  - devops
---

Keeping Docker containers updated is the kind of chore you automate once
and forget about — until a container silently runs a four-month-old image
with five CVEs because you forgot to `docker compose pull && up -d`.

Watchtower solves this. It watches your running containers, checks for
new images, and restarts them with the latest tag — all on a cron
schedule. But a naive "update everything" setup will break your
database container and nuke your uptime.

This post covers a production-grade Watchtower deployment for a homelab:
selective update rules, Telegram push notifications, manual rollback,
and patterns for zero-downtime containers.

---

## Architecture Overview

```
┌───────────────────────────────────────────────────┐
│                   Docker Host                       │
│                                                     │
│   ┌────────────┐       ┌──────────────────────┐    │
│   │ Watchtower  │──────▶│ Container Registry   │    │
│   │  :poll every │      │ (Docker Hub / GHCR)  │    │
│   │   6h        │       └──────────────────────┘    │
│   └──────┬─────┘                                    │
│          │ scans containers                         │
│          ▼                                          │
│   ┌──────────────────┐      ┌──────────────┐      │
│   │ traefik (auto)   │      │ postgres (skip) │      │
│   │ frigate (auto)   │      │              │      │
│   │ monitoring (auto)│      │ valkey (skip)│      │
│   └──────────────────┘      └──────────────┘      │
│                                                     │
│   Push: Telegram notification on each update       │
│   Rollback: docker compose pull <tag> && up -d    │
└───────────────────────────────────────────────────┘
```

---

## Why Watchtower (Not DIY Cron)

You could script:

```bash
docker compose pull && docker compose up -d
```

But this has problems:
- Updates **all** services, including databases (risky)
- No notification when something changes
- No way to pin specific images
- No scheduling beyond basic cron
- Restarts every container even if no change

Watchtower gives you per-container control, scheduling, notifications,
and only restarts containers whose images actually changed.

---

## 1. Deploy Watchtower

```yaml
# compose.yml
services:
  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_REMOVE_VOLUMES=false
      - WATCHTOWER_INCLUDE_STOPPED=false
      - WATCHTOWER_REVIVE_STOPPED=false
      - WATCHTOWER_POLL_INTERVAL=21600
      - TZ=America/Santo_Domingo
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
```

That's the baseline. Deploy with:

```bash
docker compose up -d
```

By default, Watchtower polls Docker Hub every 24 hours. I set
`POLL_INTERVAL=21600` (6 hours) for a balance between freshness and
rate limits.

---

## 2. Selective Update Control — Skip Databases

The most important config: tell Watchtower **not** to update stateful
containers. A database restart on an image update is a database
outage — you want to do that manually with proper migration checks.

**Mark containers to skip** with a label on their own compose file:

```yaml
# postgres/compose.yml
services:
  postgres:
    image: postgres:16
    labels:
      - "com.centurylinklabs.watchtower.enable=false"
```

```yaml
# valkey/compose.yml  
services:
  valkey:
    image: valkey/valkey:7.2
    labels:
      - "com.centurylinklabs.watchtower.enable=false"
```

Check which containers are excluded:

```bash
docker inspect $(docker ps -q) \
  --format '{{.Name}} → {{index .Config.Labels "com.centurylinklabs.watchtower.enable"}}'
# Output:
# /watchtower → true
# /traefik → true
# /postgres → false
# /valkey → false
# /prometheus → <no value> (inherits default = true)
```

Labels without explicit value default to `true` in Watchtower, so only
containers you explicitly mark `false` get skipped.

---

## 3. Notifications — Telegram on Every Update

Watchtower supports a dozen notification backends. Telegram is the most
practical for a homelab — push notifications to your phone with what
changed.

```yaml
# compose.yml — add to watchtower service
services:
  watchtower:
    environment:
      - WATCHTOWER_NOTIFICATIONS=telegram
      - WATCHTOWER_NOTIFICATION_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - WATCHTOWER_NOTIFICATION_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - WATCHTOWER_NOTIFICATIONS_HOSTNAME=srv1
```

```bash
# .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=1064959513
```

Restart Watchtower and trigger a manual check to test:

```bash
docker compose up -d

# Manual check
docker exec watchtower watchtower --run-once
```

You'll see output in logs:

```bash
docker logs watchtower --tail 20
# TIME="2026-05-11T10:30:00Z" level=info msg="Found new traefik:latest image (abcdef)"
# TIME="2026-05-11T10:30:01Z" level=info msg="Restarting /traefik"
# TIME="2026-05-11T10:30:05Z" level=info msg="Notification: Updated traefik → abcdef"
```

Expected Telegram message:

```
🐳 srv1 — Watchtower
Updated: traefik:latest (abcdef12345)
Updated: frigate:stable (12345abcde)
```

No news between updates means nothing changed — exactly what you want.

---

## 4. Schedule Instead of Poll Interval

If you prefer exact scheduling (e.g., daily at 3 AM), use cron syntax
over the generic poll interval:

```yaml
services:
  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_SCHEDULE=0 0 3 * * *
      - TZ=America/Santo_Domingo
      - WATCHTOWER_NOTIFICATIONS=telegram
      - WATCHTOWER_NOTIFICATION_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - WATCHTOWER_NOTIFICATION_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
```

`WATCHTOWER_SCHEDULE=0 0 3 * * *` = daily at 3:00 AM local time
(requires `TZ` to be set correctly). Remove `POLL_INTERVAL` if using
`SCHEDULE` — they conflict.

**Note:** Containers with `restart: always` or `unless-stopped` get
restarted cleanly at 3 AM. If a container takes > 30s to restart, adjust
the default timeout:

```yaml
    environment:
      - WATCHTOWER_TIMEOUT=120s
```

---

## 5. Rolling Back a Bad Update

Watchtower updates the running container, but it doesn't pin the previous
image tag. This is the **one gap** you need to cover manually.

**When a bad update happens:**

```bash
# 1. Find the previous working image
docker inspect traefik --format '{{.Config.Image}}'
# → traefik:v3.2

# 2. Check image history
docker images traefik
# REPOSITORY  TAG   IMAGE ID     CREATED      SIZE
# traefik     v3.3  abc123       2 hours ago  150MB
# traefik     v3.2  def456       2 weeks ago  145MB

# 3. Pin to previous version
docker tag traefik:v3.2 traefik:latest
docker compose up -d

# Or better: update your compose.yml to pin explicitly:
# image: traefik:v3.2
# then docker compose up -d
```

**Prevent it:** Pin major versions in compose files and let Watchtower
only handle patch updates:

```yaml
# Instead of:
image: traefik:latest

# Use:
image: traefik:v3.2
```

Watchtower will update `traefik:v3.2` when a new `v3.2.x` patch is
published, but won't jump you to `v3.3` automatically. This is the
safest pattern for datastore-adjacent containers.

---

## 6. Full Example — Selective Updates with Notifications

```yaml
# /opt/docker/watchtower/compose.yml
services:
  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_REMOVE_VOLUMES=false
      - WATCHTOWER_INCLUDE_STOPPED=false
      - WATCHTOWER_REVIVE_STOPPED=false
      - WATCHTOWER_SCHEDULE=0 0 3 * * *
      - WATCHTOWER_TIMEOUT=60s
      - WATCHTOWER_NOTIFICATIONS=telegram
      - WATCHTOWER_NOTIFICATION_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - WATCHTOWER_NOTIFICATION_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - WATCHTOWER_NOTIFICATIONS_HOSTNAME=srv1
      - TZ=America/Santo_Domingo
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

```bash
# .env (same dir as compose.yml)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=1064959513
```

Deploy:

```bash
mkdir -p /opt/docker/watchtower
cd /opt/docker/watchtower
# Create compose.yml and .env, then:
docker compose up -d

# Verify
docker logs watchtower --tail 10
# Should see: "Scheduling first run: ... daily at 03:00"
```

---

## 7. Excluding Containers — What to Skip

| Container | Auto-update? | Reason |
|-----------|-------------|--------|
| **Traefik** | ✅ Yes | Proxy downtime = brief blip, stateless |
| **Frigate** | ✅ Yes | Pulls new model weights, fast restart |
| **Grafana / Prometheus** | ⚠️ Cautiously | Pin major version (image: grafana/grafana:11.3) |
| **Loki** | ⚠️ Cautiously | Schema version matters — pin major |
| **Postgres / MySQL** | ❌ No | Manual migration on version bumps |
| **ValKey / Redis** | ❌ No | Breaking config changes between majors |
| **Watchtower itself** | ✅ Yes | Self-updating is fine |
| **PBS client / restic** | ✅ Yes | Stateless, always pull latest |

**The rule:** Stateless containers auto-update. Stateful containers with
persistent data — update manually after reviewing release notes.

---

## 8. Zero-Downtime Considerations

Watchtower stops a container, pulls the new image, and starts it again.
For a single-replica setup, there's brief downtime (~5-15 seconds).

If you need true zero-downtime updates for a web service:

**Option A: Docker Compose scale + health check**

```yaml
services:
  app:
    deploy:
      replicas: 2
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

Add this to Watchtower to enable rolling restart:

```yaml
environment:
  - WATCHTOWER_ROLLING_RESTART=true
```

Watchtower will stop one replica, pull, start, wait for the health check
to pass, then move to the next.

**Option B: Use a load balancer in front** (Traefik with multiple
backends) — Watchtower's rolling restart + health check is the simpler
homelab solution.

---

## 9. Lifecycle Hooks — Run Commands Before/After Updates

Watchtower supports prerestart and postrestart commands via labels:

```yaml
# frigate/compose.yml
services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:stable
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
      - "com.centurylinklabs.watchtower.lifecycle.prerestart=echo 'Stopping frigate for update'"
      - "com.centurylinklabs.watchtower.lifecycle.postrestart=s6-svwait /run/service"
```

Useful for services that need graceful shutdown:

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    labels:
      - "com.centurylinklabs.watchtower.enable=true"
      - "com.centurylinklabs.watchtower.lifecycle.prerestart=ha core stop"
```

---

## 10. Monitoring Watchtower

Add a Prometheus blackbox probe or simply monitor the `watchtower`
container's last-seen timestamp:

```bash
# Quick check — when did Watchtower last run?
docker exec watchtower cat /var/run/watchtower/state.json 2>/dev/null || \
  echo "No state file (first run pending)"

# Check container uptime
docker inspect watchtower --format '{{.State.StartedAt}}'
```

Better: expose Watchtower's metrics endpoint. Mount a port:

```yaml
services:
  watchtower:
    ports:
      - "10.0.20.50:8099:8080"  # LAN only
```

Then add to Prometheus:

```yaml
scrape_configs:
  - job_name: 'watchtower'
    static_configs:
      - targets: ['10.0.20.50:8099']
```

---

## 11. Alternative: Diun (Notification-Only)

If you don't want Watchtower touching your containers at all (just
notifying you about available updates), use **Diun** instead:

```yaml
services:
  diun:
    image: crazymax/diun:latest
    container_name: diun
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./diun/data:/data
    environment:
      - TZ=America/Santo_Domingo
      - DIUN_WATCH_WORKERS=20
      - DIUN_WATCH_SCHEDULE=0 0 * * * *
      - DIUN_NOTIF_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - DIUN_NOTIF_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    labels:
      - "com.centurylinklabs.watchtower.enable=false"
```

Diun sends a Telegram message when a new image is available but does
nothing else. You decide when to pull the trigger. This is the
conservative approach.

---

## Summary

```bash
# Fast deploy (with Telegram notifications and daily 3 AM schedule)
mkdir -p /opt/docker/watchtower && cd $_
cat <<'EOF' > compose.yml
services:
  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_SCHEDULE=0 0 3 * * *
      - WATCHTOWER_NOTIFICATIONS=telegram
      - WATCHTOWER_NOTIFICATION_TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - WATCHTOWER_NOTIFICATION_TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - WATCHTOWER_NOTIFICATIONS_HOSTNAME=srv1
      - TZ=America/Santo_Domingo
EOF
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env
echo "TELEGRAM_CHAT_ID=your_chat_id" >> .env
docker compose up -d

# Mark stateful containers to skip
# Add to postgres/compose.yml and valkey/compose.yml:
#   labels:
#     - "com.centurylinklabs.watchtower.enable=false"

# Verify
docker logs watchtower --tail 5
# → "Watchtower 1.7.1 starting..."
# → "Scheduling first run: 2026-05-12 03:00:00 -04 EDT"
```

Watchtower isn't optional once you have more than five containers. A
3 AM daily check with Telegram push means you wake up to a notification
like "Updated traefik, frigate, prometheus" — or nothing at all. Manual
rollback is a `docker compose pull <version>` away. Skip your database
containers, pin major versions on stateful workloads, and let the rest
update themselves.
