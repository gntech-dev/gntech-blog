---
title: "Uptime Kuma Docker Deployment — Self-Hosted Monitoring Dashboard"
description: "Deploy Uptime Kuma with Docker Compose for homelab uptime monitoring. Status pages, Telegram alerts, Traefik reverse proxy, and SQLite persistence in minutes."
date: 2026-06-01T16:00:00-04:00
tags:
  - docker
  - monitoring
  - homelab
  - docker-compose
  - selfhosting
keywords:
  - Uptime Kuma Docker Compose homelab deployment guide
  - Self-hosted uptime monitoring dashboard Docker configuration
  - Uptime Kuma Traefik reverse proxy setup SSL
  - Homelab status page Uptime Kuma Docker setup
  - Uptime Kuma Telegram notification alerts configuration
  - Docker container monitor uptime push proxy types
  - Uptime Kuma SQLite backup persistence volumes
summary: "Deploy Uptime Kuma with Docker Compose for real-time homelab monitoring. Configure Traefik reverse proxy, Telegram notifications, status pages, and SQLite-backed persistence in minutes."
canonical: "https://blog.gntech.me/posts/uptime-kuma-docker-monitoring-dashboard/"
---

## Why Uptime Kuma for Homelab Monitoring

You run Proxmox, a dozen Docker Compose stacks, a MikroTik router, and various self-hosted services. When something goes down — the NAS goes offline, the reverse proxy stops responding, or a database container crashes — you want to know immediately, not when a user complains.

**Uptime Kuma** is a lightweight, self-hosted monitoring tool that checks your services and sends alerts when they fail. It is a single Node.js application with SQLite persistence, runs in under 100 MB of RAM, and supports more monitor types than most alternatives:

- **HTTP/HTTPS** monitors with keyword validation
- **Ping** and TCP port checks
- **Push monitors** (receive health pings from scripts or cron jobs)
- **Certificate expiry** tracking (SSL/TLS)
- **Docker container** health via socket
- **DNS, Steam Game Server, MySQL, PostgreSQL, Redis, MongoDB** and more

Compared to hosted solutions like Pingdom or Better Uptime, Uptime Kuma is fully self-contained. You own the data, there are no monthly fees, and the status page can be public or internal.

## Docker Compose Deployment

The deployment is a single Docker Compose service. Create a directory and drop in this configuration:

```yaml
# docker-compose.yml
services:
  uptime-kuma:
    image: louislam/uptime-kuma:latest
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    volumes:
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - UPTIME_KUMA_PORT=3001
      - UPTIME_KUMA_DISABLE_FRAME_SAMEORIGIN=true
    healthcheck:
      test: ["CMD", "node", "extra/healthcheck.js"]
      interval: 30s
      timeout: 10s
      retries: 3
```

The `./data` volume holds the SQLite database and configuration. The Docker socket bind mount is optional — it gives Uptime Kuma the ability to list running containers and monitor their health states directly. If you use a **Docker socket proxy** for security (recommended), point the volume to the proxy socket instead:

```yaml
volumes:
  - ./data:/app/data
  - /var/run/docker-proxy.sock:/var/run/docker.sock:ro
```

Deploy with:

```bash
docker compose up -d
```

Uptime Kuma will be available at `http://<your-host>:3001` on first run.

## Traefik Reverse Proxy Setup

Exposing Uptime Kuma through your Traefik reverse proxy enables HTTPS with Let's Encrypt, clean subdomain URLs, and middleware security. Add labels to the compose service:

```yaml
services:
  uptime-kuma:
    # ... image, restart, volumes as above
    networks:
      - traefik-public
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.uptime.rule=Host(`status.gntech.me`)"
      - "traefik.http.routers.uptime.entrypoints=websecure"
      - "traefik.http.routers.uptime.tls.certresolver=letsencrypt"
      - "traefik.http.services.uptime.loadbalancer.server.port=3001"
      - "traefik.http.routers.uptime.middlewares=secHeaders@file,rateLimit@file"

networks:
  traefik-public:
    external: true
```

Remove the `ports` mapping if Uptime Kuma only needs to be reachable through Traefik — the container is still reachable on the internal Docker network:

```yaml
ports:
  - "3001:3001"   # remove this line if using Traefik only
```

After redeploying `docker compose up -d`, visit `https://status.gntech.me` to create your admin account.

## First Configuration Walkthrough

### 1. Admin Setup

On the first visit, Uptime Kuma prompts you to create an admin account with a username and password. Store this in your password manager — there is no password reset flow built in (back up the SQLite database instead).

### 2. Adding Monitors

Click **Add Monitor** and configure:

- **Type:** HTTP(s) for web services
- **Friendly Name:** e.g., "Proxmox Web UI"
- **URL:** `https://10.0.20.30:8006`
- **Interval:** 60 seconds (default)
- **Retries:** 0 (notify on first failure)
- **Resend Notification:** 5 minutes (aggregate alerts)

For internal services behind Traefik, monitor the Traefik-exposed HTTPS URL directly. For services on the Docker network only, use the container name or internal IP.

### 3. Certificate Expiry Monitoring

Create monitors with type **Certificate** — enter the domain name and port (default 443). Uptime Kuma will warn you when the certificate is within your configured threshold (default 30 days). This catches expiring Let's Encrypt certificates before they cause outages.

### 4. Push Monitors

The **Push** monitor type lets external scripts report their health to Uptime Kuma. This is excellent for cron jobs, systemd timers, and backup scripts. Create a push monitor and Uptime Kuma gives you a unique URL:

```
https://status.gntech.me/api/push/<YOUR_TOKEN>?status=up&msg=OK
```

Use it in a cron job or systemd timer:

```bash
#!/bin/bash
# /usr/local/bin/push-backup-health.sh
BACKUP_STATUS=$(/usr/local/bin/run-backups 2>&1)
if [ $? -eq 0 ]; then
  curl -s -o /dev/null "https://status.gntech.me/api/push/abcd1234?status=up&msg=Backup+OK"
else
  curl -s -o /dev/null "https://status.gntech.me/api/push/abcd1234?status=down&msg=Backup+Failed"
fi
```

If the push endpoint has not received a ping within the configured grace period (e.g., 5 minutes), Uptime Kuma marks it as down. This is a great way to monitor:

- Nightly database dumps
- Off-site backups
- ZFS scrub completion
- systemd timer executions

## Telegram Notifications

Uptime Kuma supports Telegram, Discord, Slack, Email, Webhook, Gotify, and 20+ other notification channels. To configure Telegram:

1. Create a bot via [@BotFather](https://t.me/botfather) — you get a token like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
2. Get your chat ID: send a message to the bot, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. In Uptime Kuma, go to **Settings → Notifications → Add Notification → Telegram**
4. Enter: Bot Token, Chat ID (negative for groups), and a custom message template

Sample message template:

```
🔴 {{NAME}} is DOWN at {{HOSTNAME}}
Time: {{TIME}}
Error: {{ERRORMSG}}
```

Uptime Kuma substitutes these template variables automatically per monitor.

## Status Page Setup

Uptime Kuma includes a built-in public status page. Go to **Settings → Status Page**, create a new page, and assign monitors to it. Features:

- **Custom slug** — e.g., `status.gntech.me/status` or a dedicated subdomain
- **Group monitors** — group related services (Infrastructure, Storage, Network, Applications)
- **Custom CSS** — match your branding colors
- **Incident history** — manually log incidents and maintenance windows
- **Embed badge** — SVG badge showing overall uptime percentage

For a private homelab, you can keep the status page accessible only through your internal network or Traefik IP whitelist middleware.

## Backup and Maintenance

Uptime Kuma stores everything in a single SQLite database at `./data/kuma.db`. Backup is trivial:

```bash
# Backup the database
cp ./data/kuma.db ./backups/kuma.db.$(date +%Y%m%d)
```

Restore by stopping the container, replacing the database file, and restarting:

```bash
docker compose down
cp ./backups/kuma.db.20260601 ./data/kuma.db
docker compose up -d
```

Add a cron job or systemd timer for automated backups. Combine with your existing Docker volume backup strategy (restic, borg, or plain rsync):

```bash
0 4 * * * cp /opt/uptime-kuma/data/kuma.db /opt/uptime-kuma/backups/kuma-$(date +\%Y\%m\%d).db
```

To upgrade Uptime Kuma:

```bash
docker compose pull
docker compose up -d
```

The SQLite schema is backwards-compatible across minor versions.

## Resource Usage and Best Practices

Uptime Kuma is remarkably lightweight. On a Docker host with 30 monitors:

| Resource | Usage |
|----------|-------|
| RAM | 60–90 MB |
| CPU | < 0.5% idle, spikes during checks |
| Disk | ~10 MB for SQLite database |
| Network | Minimal — single HTTP request per check interval |

This makes it suitable to run alongside other services on a single Docker host or on a low-powered device like a Raspberry Pi.

**Best practices:**

- **Use push monitors** for cron/systemd timer health — they catch silent failures
- **Monitor from outside your network** — run a second Uptime Kuma instance on a cheap VPS for external perspective
- **Keep the SQLite database backed up** — the only configuration file you cannot recreate
- **Set resend intervals** — 5-15 minutes prevents alert fatigue
- **Combine with Netdata** for real-time metrics and Uptime Kuma for availability — they complement each other
- **Use a Docker socket proxy** instead of mounting `/var/run/docker.sock` directly

## Summary

Uptime Kuma delivers production-grade uptime monitoring without the complexity of Prometheus and Alertmanager, and without monthly SaaS fees. A single Docker Compose file gets you HTTP monitoring, certificate tracking, push monitors for cron jobs, and a public status page — all backed by SQLite for zero infrastructure overhead.

Deploy it today, add your critical services as monitors, configure Telegram alerts, and you will know within 60 seconds any time something in your homelab goes down.
