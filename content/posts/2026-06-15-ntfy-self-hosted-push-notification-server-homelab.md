---
title: "ntfy Self-Hosted Push Notification Server for Homelab Alerts"
description: "Deploy ntfy.sh on Docker for unified push notifications across your homelab. Integrate with Uptime Kuma, Prometheus Alertmanager, and cron scripts for real-time mobile alerts."
date: 2026-06-15T11:00:00-04:00
tags:
  - docker
  - monitoring
  - selfhosting
  - homelab
  - automation
keywords:
  - ntfy self-hosted push notification server Docker deployment
  - Homelab unified alerting system ntfy sh
  - Send push notifications from bash scripts ntfy API
  - Uptime Kuma ntfy integration homelab monitoring
  - Prometheus Alertmanager ntfy webhook receiver
  - Docker compose ntfy setup authentication access control
  - Unified notification system homelab monitoring stack
summary: "Deploy ntfy.sh on Docker for push notifications across your entire homelab. From Uptime Kuma to Prometheus Alertmanager, get real-time mobile alerts for everything with a single HTTP POST."
canonical: "https://blog.gntech.me/posts/ntfy-self-hosted-push-notification-server-homelab/"
---

Your homelab runs monitoring checks, backups, health probes, and automation workflows — each one generating output that you need to see. The typical approach is checking dashboards, tailing logs, or waiting for an email that might land in spam. In 2026, with homelabs running dozens of services, reactive monitoring is dead. You need push notifications that reach your pocket instantly.

ntfy.sh is the simplest self-hosted push notification server you can run. A single HTTP POST sends a notification to your phone. No SDKs, no SDK registration, no per-app tokens. One `curl` command and you're done.

This guide covers deploying ntfy on Docker Compose, setting up authentication, and wiring it into your monitoring stack — Uptime Kuma, Prometheus Alertmanager, Grafana, cron jobs, and every script you've ever written.

## Why ntfy Instead of Gotify, Apprise, or Pushover

There are several options for self-hosted notifications. Here's how they compare:

- **ntfy.sh** — Single-binary server with a dead-simple HTTP API. Push via `curl -d "message" ntfy.sh/topic`. No client library needed. Native Android and iOS apps with persistent connections. Open source (Apache 2.0), ~10MB binary.
- **Gotify** — Mature, websocket-based. Requires a client app on the phone. Docker container ~15MB. Excellent, but the push mechanism is slightly more involved (requires the Gotify client to maintain a websocket).
- **Apprise** — A notification library, not a server. Wraps dozens of providers (Slack, Telegram, email). Great as a relay, but you still need something to trigger it.
- **Pushover** — Hosted service, $5/mo. Works great but locks you into a third party.

ntfy wins for sheer simplicity. The entire API is `POST /{topic}` with the message body. It supports priorities, tags, markdown, click actions, and attachments — all via HTTP headers. For a homelab where you want notifications from bash scripts without installing anything, ntfy is the clear choice.

## Deploying ntfy on Docker Compose

Here is the complete docker-compose.yml for a production-ready ntfy deployment behind Traefik:

```yaml
services:
  ntfy:
    image: binwiederhier/ntfy:latest
    container_name: ntfy
    restart: unless-stopped
    volumes:
      - ./data/ntfy/cache:/var/cache/ntfy
      - ./data/ntfy/auth:/var/lib/ntfy
      - ./data/ntfy/config:/etc/ntfy
    environment:
      - TZ=America/Santo_Domingo
      - NTFY_BASE_URL=https://ntfy.gntech.me
      - NTFY_BEHIND_PROXY=true
      - NTFY_CACHE_FILE=/var/cache/ntfy/cache.db
      - NTFY_AUTH_FILE=/var/lib/ntfy/auth.db
      - NTFY_AUTH_DEFAULT_ACCESS=deny-all
    healthcheck:
      test: ["CMD", "wget", "-q", "--tries=1", "--spider", "http://localhost:80/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - proxy

  # Optional: subscribe topic for mobile test
  ntfy-sub:
    image: alpine:latest
    entrypoint: ["/bin/sh", "-c", "apk add curl; while true; do sleep 86400; done"]
    profiles: ["tools"]
    networks:
      - proxy

networks:
  proxy:
    external: true
```

### Nginx Proxy or Traefik Configuration

If you use Traefik, add these labels:

```yaml
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.ntfy.rule=Host(`ntfy.gntech.me`)"
      - "traefik.http.routers.ntfy.entrypoints=https"
      - "traefik.http.routers.ntfy.tls.certresolver=letsencrypt"
      - "traefik.http.services.ntfy.loadbalancer.server.port=80"
```

For Caddy, a minimal Caddyfile:

```
ntfy.gntech.me {
    reverse_proxy ntfy:80
}
```

### Authentication Setup

Deploy first with `NTFY_AUTH_DEFAULT_ACCESS=deny-all` (as shown above), then create users and tokens:

```bash
# Access the container shell
docker exec -it ntfy /bin/sh

# Create admin user (interactive)
ntfy user add --role=admin admin

# Create a token for monitoring tools (non-interactive)
ntfy token add --label=uptime-kuma --role=read-write alerts
ntfy token add --label=backup-scripts backup-notify

# List existing tokens
ntfy token list
```

Store the tokens securely. Each token grants access to specific topics. The format is: `tk_xxxxxxxxxxxxx`.

Without auth enabled, anyone who can reach your ntfy instance can publish. With `deny-all` as default, you control exactly which services can push and which topics they can access.

## Publishing Notifications — The API

ntfy's API is refreshingly simple. No JSON body required unless you need structured content:

```bash
# Basic notification
curl -d "Backup of PostgreSQL completed successfully" \
  https://ntfy.gntech.me/alerts

# With priority and tags
curl -H "Priority: urgent" \
  -H "Tags: floppy_disk" \
  -H "Title: Backup Failed" \
  -d "ZFS snapshot replication to offsite failed - check /var/log/zfs" \
  https://ntfy.gntech.me/alerts

# Markdown body with click action
curl -H "Content-Type: text/markdown" \
  -H "Click: https://grafana.gntech.me/d/backups" \
  -H "Tags: warning" \
  -d "**Backup warning:** Last run took 3x normal time.\n\nSee the [dashboard](https://grafana.gntech.me/d/backups) for details." \
  https://ntfy.gntech.me/alerts

# Authenticated request (token as Bearer or Basic)
curl -H "Authorization: Bearer tk_xxxxxxxxxxxxx" \
  -H "Priority: high" \
  -H "Tags: fire" \
  -d "CPU temperature exceeded 85°C on SRV1" \
  https://ntfy.gntech.me/backup-notify
```

Priority levels available: `urgent`, `high`, `default`, `low`, `min`. Each maps to how aggressively your phone notifies you — urgent bypasses Do Not Disturb on Android.

## Integrating with Your Monitoring Stack

### Uptime Kuma

Uptime Kuma natively supports ntfy as a notification provider:

1. Go to **Settings > Notifications**
2. Click **Add Notification**
3. Select **ntfy** from the provider list
4. Set **URL** to your ntfy instance: `https://ntfy.gntech.me`
5. Set **Topic** to `alerts`
6. Set **Token** if authentication is enabled
7. Select priority (default: high)
8. Click **Test** — you should receive a test notification

Kuma sends status changes (down → up, up → down) directly to your phone with the service name and current status.

### Prometheus Alertmanager

Alertmanager supports generic webhook receivers, which work perfectly with ntfy. Add this to `alertmanager.yml`:

```yaml
route:
  receiver: ntfy-alerts
  repeat_interval: 4h

receivers:
- name: ntfy-alerts
  webhook_configs:
  - url: https://ntfy.gntech.me/alerts
    http_config:
      headers:
        Authorization: "Bearer tk_xxxxxxxxxxxxx"
    send_resolved: true
```

Alertmanager will POST each alert group as JSON. ntfy will render the JSON body, which is readable enough. For cleaner messages, use Alertmanager's `text` template field or pipe through a small middleware.

### Grafana Contact Points

Grafana supports webhook contact points:

1. **Alerting > Contact points** → **Add contact point**
2. Name: `ntfy`
3. Integration: **Webhook**
4. URL: `https://ntfy.gntech.me/alerts`
5. HTTP method: `POST`
6. Add custom header: `Authorization: Bearer tk_xxxxxxxxxxxxx`
7. **Optional message template** — Grafana's templating lets you build cleaner notifications:

```
{{ define "ntfy/message" }}
{{ range .Alerts }}
**{{ .Labels.alertname }}**
Severity: {{ .Labels.severity }}
Instance: {{ .Labels.instance }}
{{ .Annotations.summary }}
{{ end }}
{{ end }}
```

### Docker Container Healthchecks

Docker healthchecks can push to ntfy on failure. Add this to any compose service:

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

Then a separate cron or watchdog checks health status and alerts:

```bash
#!/bin/bash
# /usr/local/bin/ntfy-healthwatch.sh
NTFY_URL="https://ntfy.gntech.me/alerts"
NTFY_TOKEN="tk_xxxxxxxxxxxxx"

docker ps --filter "health=unhealthy" --format "{{.Names}}" | while read container; do
  curl -s -H "Authorization: Bearer $NTFY_TOKEN" \
    -H "Priority: high" \
    -H "Tags: warning" \
    -H "Title: Container Unhealthy" \
    -d "Container $container is unhealthy on $(hostname)" \
    "$NTFY_URL"
done
```

Run it every 5 minutes via a systemd timer or crontab:

```bash
*/5 * * * * /usr/local/bin/ntfy-healthwatch.sh
```

### Shell Script Notification Function

Add this to your `.bashrc` or common library:

```bash
ntfy_send() {
  local topic="${1:-alerts}"
  local message="$2"
  local priority="${3:-default}"
  local title="${4:-Notification}"
  local tags="${5:-}"
  local token="${NTFY_TOKEN:-}"

  curl -s -o /dev/null \
    ${token:+-H "Authorization: Bearer $token"} \
    -H "Priority: $priority" \
    -H "Title: $title" \
    ${tags:+-H "Tags: $tags"} \
    -d "$message" \
    "https://ntfy.gntech.me/$topic"
}

# Usage
ntfy_send "backup-notify" "Restic backup completed - 1.2GB uploaded" "default" "Backup OK" "white_check_mark"
```

One function, zero dependencies, works from any shell script.

## Advanced Configuration

### Topic-Based Access Control

Fine-tune who can publish and subscribe to each topic:

```bash
# Create a read-only subscriber for dashboards
ntfy token add --label=dashboard-monitor --role=read-only server-status

# Create a write-only publisher for backup scripts
ntfy token add --label=backup-agent --role=write-only backup-notify
```

Topic reservations ensure only authorized tokens can use specific topic names:

```bash
# Run in container
ntfy topic add alerts
ntfy topic add backup-notify
ntfy topic add server-status
```

### Rate Limiting and Caching

ntfy caches messages by default so new subscribers see recent notifications. Control cache size in `server.yml`:

```yaml
# /etc/ntfy/server.yml (bind-mounted)
cache-file: /var/cache/ntfy/cache.db
cache-duration: 12h
cache-startup-queries-as-seen: false
message-delay-interval: 5s
rate-limit: 60
rate-limit-burst: 120
visitor-subscription-rate-limit: 10
visitor-request-tokens-burst: 120
```

### Behind Traefik with Rate Limiting

Add a middleware to protect ntfy from abuse:

```yaml
    labels:
      - "traefik.http.middlewares.ntfy-ratelimit.ratelimit.average=30"
      - "traefik.http.middlewares.ntfy-ratelimit.ratelimit.burst=60"
      - "traefik.http.routers.ntfy.middlewares=ntfy-ratelimit"
```

## Mobile Setup — Push Where It Matters

1. Install **ntfy** from F-Droid, Google Play, or Apple App Store
2. Tap **Add topic**
3. Enter your server URL: `https://ntfy.gntech.me`
4. Topic: `alerts`
5. If auth is enabled, add your read token
6. Configure per-topic settings:
   - **alerts**: priority threshold "high" (only wake me for real problems)
   - **backup-notify**: priority threshold "default" (backup completion, not urgent)
   - **server-status**: mute during night (silent maintenance messages)

## Security Hardening

Secure your ntfy instance against unwanted access:

```bash
# Block direct IP access, force through reverse proxy
# In server.yml
behind-proxy: true
base-url: "https://ntfy.gntech.me"

# Firewall: only allow from Docker proxy network
ufw deny from any to 10.0.20.50 port 2586
```

If you don't want authentication, restrict by network instead:

```yaml
    # Only accept connections from your reverse proxy
    networks:
      - proxy
    # Do NOT expose ports directly
    expose:
      - "80"
```

For the reverse proxy, add IP allowlists:

```
# Caddy
ntfy.gntech.me {
    @internal remote_ip 10.0.0.0/8 192.168.0.0/16 172.16.0.0/12
    handle @internal {
        reverse_proxy ntfy:80
    }
    respond 403
}
```

## Monitoring ntfy Itself

ntfy exposes a health endpoint at `/v1/health`:

```bash
curl https://ntfy.gntech.me/v1/health
# Returns {"health": true, "uptime": 123456}
```

Add this to your Uptime Kuma monitor or Prometheus blackbox target:

```yaml
# prometheus.yml
scrape_configs:
- job_name: ntfy-health
  metrics_path: /v1/health
  static_configs:
    - targets: ["ntfy.gntech.me"]
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
```

## Conclusion

Self-hosted push notifications with ntfy transform how you interact with your homelab. Instead of checking dashboards, notifications come to you. Instead of email gateways that silently fail, a single `curl` command reaches your phone with priority, tags, and actionable links.

The setup is minimal — one Docker Compose file, one `docker compose up -d`, and a few tokens. The integrations cover Uptime Kuma, Prometheus Alertmanager, Grafana, and every cron job or script you write. For a service that costs nothing to run, ntfy pays for itself the first time it alerts you to a failed backup before your data is gone.

Start with a simple deployment, add authentication, then wire in your monitoring tools one by one. Your homelab will thank you — and so will your sleep when only the urgent alerts wake you up.
