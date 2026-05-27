---
title: "n8n Docker Deployment — Self-Hosted Workflow Automation Guide"
description: "Deploy n8n with Docker Compose for self-hosted workflow automation in your homelab — PostgreSQL backend, Traefik reverse proxy, persistent workflows, and production-ready security."
date: 2026-05-27T12:00:00-04:00
tags:
  - docker
  - selfhosting
  - automation
  - homelab
  - n8n
keywords:
  - n8n Docker Compose homelab deployment
  - self-hosted workflow automation n8n guide
  - n8n PostgreSQL Docker persistent data
  - n8n Traefik reverse proxy production setup
  - n8n Docker container security hardening
  - n8n workflow automation homelab use cases
  - n8n Ollama AI integration self-hosted
summary: "Complete guide to deploying n8n with Docker Compose in your homelab — PostgreSQL backend, persistent workflows, Traefik SSL, security hardening, and practical workflow automation examples."
canonical: "https://gntech.dev/posts/n8n-docker-deployment-homelab-automation/"
---

If you've used Zapier, Make (formerly Integromat), or IFTTT,
you know how powerful no-code automation can be. You also know
the pain: tiered pricing, execution caps, and your data flowing
through third-party servers. n8n solves all three problems by
giving you a self-hosted, fair-code workflow automation platform
with 400+ integrations, visual node-based editing, and full code
support when you need it.

In this guide, I'll deploy n8n with Docker Compose using a
PostgreSQL backend for production reliability, wire it up behind
Traefik with automatic SSL, apply security hardening, and walk
through practical homelab automation workflows. Every command
and config file has been tested on Docker 27+ and Compose 2.30+.

---

## Prerequisites for n8n Docker Deployment

Before starting, make sure you have the following:

- **Docker Engine 24+** and **Docker Compose v2** installed on your Linux host
- A domain (or subdomain) pointed at your server — we'll use `n8n.gntech.dev` in examples
- Traefik running as your reverse proxy (or adapt the labels for Caddy / nginx)
- At least **1 GB RAM**, **1 vCPU**, and **10 GB disk** for n8n + PostgreSQL data
- Basic familiarity with `docker-compose.yml` and environment variables

If you're deploying for local-only access without a public domain,
you can skip the Traefik section and access n8n directly on
port 5678 via your LAN IP.

## Production-Grade Docker Compose Setup

Here's the full `docker-compose.yml` configured for production —
PostgreSQL backend, persistent volumes, Traefik integration,
and security hardening from the start.

```yaml
# docker-compose.yml — n8n with PostgreSQL and Traefik
services:
  postgres:
    image: postgres:16-alpine
    container_name: n8n-postgres
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=n8n
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?err}
      - POSTGRES_DB=n8n
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U n8n"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - n8n-internal

  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - n8n_data:/home/node/.n8n
      - ./local-files:/files
    environment:
      # Core
      - N8N_PORT=5678
      - N8N_HOST=${N8N_HOST:?err}
      - N8N_PROTOCOL=https
      - N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY:?err}
      - N8N_DISABLE_PRODUCTION_MAIN_PROCESS=false
      - EXECUTIONS_DATA_PRUNE=true
      - EXECUTIONS_DATA_MAX_AGE=168

      # PostgreSQL
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_PORT=5432
      - DB_POSTGRESDB_DATABASE=n8n
      - DB_POSTGRESDB_USER=n8n
      - DB_POSTGRESDB_PASSWORD=${POSTGRES_PASSWORD:?err}

      # Security
      - N8N_BLOCK_FILE_ACCESS_TO_N8N_FOLDER_FILES=true
      - N8N_METRICS=false
      - N8N_PERSONALIZATION_ENABLED=false
      - N8N_AI_ENABLED=false
    networks:
      - n8n-internal
      - traefik-public
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.n8n.rule=Host(`${N8N_HOST}`)"
      - "traefik.http.routers.n8n.entrypoints=websecure"
      - "traefik.http.routers.n8n.tls=true"
      - "traefik.http.routers.n8n.tls.certresolver=letsencrypt"
      - "traefik.http.services.n8n.loadbalancer.server.port=5678"
      - "traefik.http.middlewares.n8n-headers.headers.framedeny=true"
      - "traefik.http.middlewares.n8n-headers.headers.sslredirect=true"
      - "traefik.http.middlewares.n8n-headers.headers.stsincludesubdomains=true"
      - "traefik.http.middlewares.n8n-headers.headers.stspreload=true"
      - "traefik.http.middlewares.n8n-headers.headers.contenttypenosniff=true"
      - "traefik.http.routers.n8n.middlewares=n8n-headers"

volumes:
  postgres_data:
  n8n_data:

networks:
  n8n-internal:
    internal: true
  traefik-public:
    external: true
```

Create a `.env` file in the same directory with your secrets:

```env
# .env — n8n secrets, never commit this file
POSTGRES_PASSWORD=your-strong-password-here
N8N_HOST=n8n.gntech.dev
N8N_ENCRYPTION_KEY=your-32-char-plus-encryption-key
```

Generate a strong encryption key:

```bash
openssl rand -hex 32
```

## Traefik Dynamic Configuration Notes

The labels in the compose file assume your Traefik instance is
running on a Docker network called `traefik-public` with a
certificate resolver named `letsencrypt`. If you're using a
different proxy, adjust accordingly.

For Caddy, replace the labels section with a `Caddyfile` entry:

```caddy
n8n.gntech.dev {
    reverse_proxy n8n:5678
}
```

For nginx, use a simple location block pointing at the n8n
container on port 5678 with standard SSL termination.

## Deploy and Create Your Admin Account

Start the stack:

```bash
docker compose up -d
```

Check the logs to confirm n8n starts successfully:

```bash
docker compose logs -f n8n
```

Wait for the log line indicating the web server is listening,
then open `https://n8n.gntech.dev` in your browser.

On the first visit, n8n prompts you to:
1. Create an owner account (email + password)
2. Optionally configure usage data collection (disable for privacy)
3. Set your timezone under Settings → Workflow → Timezone

### Executions Data Retention

The environment variables `EXECUTIONS_DATA_PRUNE=true` and
`EXECUTIONS_DATA_MAX_AGE=168` tell n8n to automatically delete
workflow execution history older than 7 days (168 hours). This
prevents the PostgreSQL database from growing unbounded.

## Security Hardening for n8n

n8n runs workflow code that may touch files, APIs, and
databases. Hardening your deployment is critical.

### Disable File Access to the n8n Directory

The variable `N8N_BLOCK_FILE_ACCESS_TO_N8N_FOLDER_FILES=true`
prevents workflows from reading or writing files inside the
`.n8n` data directory. If your workflows need access to specific
files, mount a separate volume (like `local-files` in the
compose file) and use the `Read/Write File From Disk` node with
paths outside `.n8n`.

### Run as Non-Root User

The official `n8nio/n8n` image already runs as the `node` user
(UID 1000). Verify by checking the container:

```bash
docker exec n8n whoami
# → node
```

Avoid overriding the user unless you have a specific reason.

### Use an Environment File

Never hardcode secrets in `docker-compose.yml`. The `.env` file
should be mode 600 and included in `.gitignore`:

```bash
chmod 600 .env
echo ".env" >> .gitignore
```

### Rate Limiting

Add Traefik rate-limiting middleware to protect the login
endpoint:

```yaml
# In your Traefik dynamic config
http:
  middlewares:
    n8n-ratelimit:
      rateLimit:
        average: 10
        burst: 20
```

## Practical Homelab Automation Workflows

Once n8n is running, here are three workflows I use daily
in my homelab.

### 1. Telegram Bot → Docker Container Notifications

Use n8n's **Telegram Trigger** node to listen for commands,
then execute a **Execute Command** node to restart containers
or fetch their status.

```
[Telegram Trigger: /status]
  → [Execute Command: docker ps --format]
    → [Telegram: Send Message with output]
```

### 2. RSS Monitor → Proxmox Backup Status

Poll an RSS feed (or a Proxmox API endpoint) on a schedule,
format the results, and send notifications via Telegram or email.

```
[RSS Feed Read: hourly]
  → [Code: filter new items]
    → [Telegram: notification with title + link]
```

### 3. Ollama AI Integration

Connect n8n to a local Ollama instance for AI-powered
workflows — content summarization, tag generation, or
intelligent routing:

```
[Manual/Webhook trigger]
  → [HTTP Request: POST to Ollama /api/generate]
    → [Code: extract response text]
      → [Telegram: send AI-generated summary]
```

Set the Ollama endpoint in your n8n credentials as
`http://ollama:11434` if it's on the same Docker network,
or `http://10.0.20.30:11434` if on the LAN.

## Backup and Recovery Strategy

### Backing Up n8n

Two things need backup: the PostgreSQL database and the `.n8n`
folder containing workflow definitions and credentials.

```bash
# Backup PostgreSQL database
docker exec n8n-postgres pg_dump -U n8n n8n > n8n-db-$(date +%F).sql

# Backup n8n data folder
docker run --rm -v n8n_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/n8n-data-$(date +%F).tar.gz -C /data .

# Export all workflows as JSON files (optional)
docker exec n8n n8n export:workflow --all --output=/home/node/.n8n/export
```

### Restoring

To restore on a fresh host:

```bash
# Restore data folder
docker run --rm -v n8n_data:/data -v $(pwd):/backup alpine \
  tar xzf /backup/n8n-data-YYYY-MM-DD.tar.gz -C /data

# Restore database
docker exec -i n8n-postgres psql -U n8n n8n < n8n-db-YYYY-MM-DD.sql
```

Then start the stack with `docker compose up -d`.

---

## Conclusion

n8n brings enterprise-grade workflow automation to your homelab
without the subscription costs or data privacy trade-offs of
SaaS alternatives. With Docker Compose, PostgreSQL, and Traefik
you get a production-ready deployment that survives reboots,
handles SSL automatically, and keeps your sensitive data under
your control.

The 400+ built-in integrations mean you can connect just about
anything — Docker, Proxmox, Telegram, email, databases, HTTP
APIs, AI models — into automated pipelines that save you hours
each week. Start with one simple workflow: a Telegram bot that
checks your Proxmox host status. You'll be building complex
multi-step automations before you know it.

For the full n8n documentation, visit
[n8n.io](https://n8n.io) and the
[Docker install docs](https://docs.n8n.io/hosting/installation/docker/).
