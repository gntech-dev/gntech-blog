---
title: "Vaultwarden Docker Deployment — Self-Hosted Password Manager Guide"
description: "Deploy Vaultwarden with Docker Compose and Traefik — a lightweight Bitwarden-compatible password manager for your homelab. Covers setup, admin panel, backups, and security hardening."
date: 2026-05-17T07:00:00-04:00
tags:
  - docker
  - docker-compose
  - security
  - homelab
  - linux
keywords:
  - Vaultwarden Docker Compose setup guide
  - self-hosted Bitwarden alternative Vaultwarden
  - Vaultwarden Traefik reverse proxy configuration
  - Vaultwarden admin panel security hardening
  - Vaultwarden SQLite backup strategy
  - Vaultwarden Docker deployment homelab
  - self-hosted password manager Docker 2026
summary: "Deploy Vaultwarden, a lightweight Bitwarden-compatible password server, with Docker Compose and Traefik in your homelab. Covers admin panel setup, automated backups, SMTP configuration, and security hardening."
canonical: "https://gntech.dev/posts/vaultwarden-docker-deployment/"
---

Bitwarden's recent announcement about eliminating the freemium tier,
combined with the April 2026 CLI compromise incident, has pushed more
homelab operators toward self-hosted password management.

Vaultwarden is the natural answer. It's a lightweight, Rust-based
reimplementation of the Bitwarden server API that runs in under 50 MB
of RAM, works with every official Bitwarden client (browser extensions,
desktop, iOS, Android), and gives you full control over your vault
data.

This guide covers a production-ready Vaultwarden deployment with Docker
Compose and Traefik, including the admin panel, automated backups, SMTP
notifications, and security hardening. The result is a password manager
that matches the official Bitwarden feature set without the
subscription or resource overhead.

---

## Why Vaultwarden Over Official Bitwarden

The official Bitwarden self-hosted option requires Docker with
Microsoft SQL Server, consumes 2+ GB of RAM, and demands regular
maintenance. Vaultwarden uses SQLite, runs on a Raspberry Pi Zero, and
is a single binary.

| Feature | Official Bitwarden | Vaultwarden |
|---------|------------------|-------------|
| RAM usage | 2-4 GB | ~50 MB |
| Database | SQL Server | SQLite |
| Image size | ~2 GB | ~50 MB |
| Setup time | 30-60 minutes | 5 minutes |
| Client compatibility | Full | Full |
| Organizations | Premium only | Included |
| Admin panel | Web UI | Web UI |

If you're already running Docker in your homelab, Vaultwarden takes
five minutes to deploy and uses fewer resources than most of your other
containers.

---

## Step 1: Directory Structure and Environment File

Create the project directory and environment configuration:

```bash
mkdir -p /opt/vaultwarden
cd /opt/vaultwarden
```

**Environment file — `/opt/vaultwarden/vaultwarden.env`:**

```env
# Required: Admin token to access /admin panel
# Generate with: openssl rand -base64 48
ADMIN_TOKEN=your-generated-token-here

# Domain and port
DOMAIN=https://vault.gntech.dev

# Database path inside container
DATABASE_URL=/data/db.sqlite3

# SMTP for invitation emails and password resets
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=vaultwarden@gntech.dev
SMTP_FROM_NAME=Vaultwarden

# Security settings
SIGNUPS_ALLOWED=false      # Disable after creating your account
INVITATIONS_ALLOWED=true   # Allow sending invites via email

# Token expiration (seconds)
SESSION_TIMEOUT=3600

# WebSocket notifications for real-time sync
WEBSOCKET_ENABLED=true

# Attachment storage
DATA_FOLDER=/data
ATTACHMENTS_FOLDER=/data/attachments
```

Generate the admin token:

```bash
openssl rand -base64 48
# Copy the output into ADMIN_TOKEN in the env file
```

**Why disable signups immediately:** Create your account before setting
`SIGNUPS_ALLOWED=false`. After that, new users join only via email
invitation through the admin panel. This prevents random internet
traffic from creating accounts if Vaultwarden is exposed (it shouldn't
be — see Traefik security below).

---

## Step 2: Docker Compose Configuration

**`/opt/vaultwarden/docker-compose.yml`:**

```yaml
services:
  vaultwarden:
    image: vaultwarden/server:latest
    container_name: vaultwarden
    restart: unless-stopped
    env_file: vaultwarden.env
    volumes:
      - vaultwarden_data:/data
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.vaultwarden.rule=Host(`vault.gntech.dev`)"
      - "traefik.http.routers.vaultwarden.entrypoints=websecure"
      - "traefik.http.routers.vaultwarden.tls.certresolver=letsencrypt"
      - "traefik.http.services.vaultwarden.loadbalancer.server.port=80"
      - "traefik.http.routers.vaultwarden.middlewares=vaultwarden-ipwhitelist"

  # Database backup container — runs daily
  vaultwarden-backup:
    image: alpine:latest
    container_name: vaultwarden-backup
    restart: unless-stopped
    entrypoint: |
      sh -c "
      apk add --no-cache sqlite >/dev/null 2>&1
      while true; do
        sqlite3 /data/db.sqlite3 '.backup /backup/db-\\\$(date +%Y%m%d-%H%M%S).sqlite3'
        find /backup -name 'db-*.sqlite3' -mtime +14 -delete
        sleep 86400
      done
      "
    volumes:
      - vaultwarden_data:/data:ro
      - vaultwarden_backups:/backup
    depends_on:
      - vaultwarden

volumes:
  vaultwarden_data:
    name: vaultwarden_data
  vaultwarden_backups:
    name: vaultwarden_backups

networks:
  proxy:
    external: true
```

This compose file does three things in one stack:

1. **Vaultwarden** — The password server itself. Connects to your
   existing Traefik proxy network for automatic TLS. The label
   `vaultwarden-ipwhitelist` is optional — add a middleware to restrict
   access to your home IP if you don't need remote access.
2. **Backup container** — A lightweight Alpine container that runs a
   `sqlite3 .backup` every 24 hours. The backup is a live, consistent
   snapshot that doesn't require stopping the Vaultwarden container.
3. **Separate volumes** — `vaultwarden_data` for the live database and
   attachments, `vaultwarden_backups` for daily backups. This keeps
   backups isolated from the live data.

---

## Step 3: Deploy and Create Your Account

```bash
cd /opt/vaultwarden

# Pull and start Vaultwarden (signups still enabled)
docker compose up -d vaultwarden

# Check the logs to confirm it started
docker compose logs vaultwarden
```

Vaultwarden starts on port 80 inside the container. Traefik routes
`vault.gntech.dev` to it and provisions a Let's Encrypt certificate
automatically.

**Create your account:**

1. Open `https://vault.gntech.dev` in your browser
2. Create your account with email and master password
3. Log in, verify everything works
4. **Immediately disable open signups:**

```bash
# Edit vaultwarden.env and set:
SIGNUPS_ALLOWED=false

# Restart to apply
docker compose up -d vaultwarden
```

**Install Bitwarden clients:**

Every official Bitwarden app supports custom server URLs. Point them
at your Vaultwarden domain:

- **Browser extension:** Settings → Self-hosted → `https://vault.gntech.dev`
- **iOS/Android:** Settings → Self-hosted → `https://vault.gntech.dev`
- **Desktop app:** File → Settings → Self-hosted → `https://vault.gntech.dev`

Once connected, your vault syncs in real-time via WebSocket (enabled by
`WEBSOCKET_ENABLED=true` in the env file). Changes in the browser
extension appear on your phone within seconds.

---

## Step 4: Admin Panel Configuration

The admin panel at `https://vault.gntech.dev/admin` gives you
server-wide management without needing to edit the env file.

**What the admin panel lets you do:**

- View all users and their vault status
- Send email invitations to new users
- Disable or delete user accounts
- View server configuration and diagnostics
- Check database and attachment storage usage
- Enable/disable 2FA requirements per organization

Access it with the `ADMIN_TOKEN` from your env file. It's the single
password for the admin area — keep it long and generated via
`openssl rand -base64 48`.

**Security note on the admin panel:** Don't expose the `/admin` path to
the public internet without additional protection. The Traefik
whitelist middleware restricts by source IP:

```yaml
# In Traefik dynamic config or labels
labels:
  - "traefik.http.middlewares.vaultwarden-ipwhitelist.ipwhitelist.sourcerange=10.0.0.0/8,192.168.0.0/16"
  - "traefik.http.routers.vaultwarden.middlewares=vaultwarden-ipwhitelist"
```

If you need remote access, use a WireGuard tunnel back to your
homelab instead of opening the admin panel to the internet.

---

## Step 5: Automated Backup and Restore

The backup container in the compose file runs `sqlite3 .backup` daily
and keeps 14 days of snapshots. SQLite's `.backup` command produces a
consistent, transaction-safe copy without downtime.

**Verify backup is running:**

```bash
# Check the backup container logs
docker compose logs vaultwarden-backup

# List backup files
docker run --rm -v vaultwarden_backups:/backup alpine ls -la /backup/

# Should show files like:
# db-20260516-030000.sqlite3
# db-20260515-030000.sqlite3
```

**Restore a backup:**

```bash
# Stop Vaultwarden
docker compose down vaultwarden

# Copy a backup snapshot into the live data volume
docker run --rm \
  -v vaultwarden_backups:/backup \
  -v vaultwarden_data:/data \
  alpine \
  sh -c "cp /backup/db-20260516-030000.sqlite3 /data/db.sqlite3"

# Start Vaultwarden
docker compose up -d vaultwarden
```

**Extend the backup strategy with offsite copies:**

```bash
#!/bin/bash
# /opt/vaultwarden/backup-offsite.sh
# Run from cron or as a systemd timer

BACKUP_VOLUME="vaultwarden_backups"
RCLONE_DEST="remote:backups/vaultwarden"

# Get the latest backup file
LATEST=$(docker run --rm -v $BACKUP_VOLUME:/backup alpine \
  sh -c "ls -t /backup/db-*.sqlite3 | head -1")

if [ -n "$LATEST" ]; then
  FILENAME=$(basename $LATEST)
  docker run --rm -v $BACKUP_VOLUME:/data alpine \
    sh -c "rclone copy /data/$FILENAME $RCLONE_DEST/$FILENAME"
  echo "Copied $FILENAME to offsite storage"
fi
```

For a complete disaster recovery plan, also back up these items:

- `vaultwarden.env` — Contains SMTP and admin credentials
- `docker-compose.yml` — The compose file itself
- Traefik certificate files — If you need to rebuild from scratch

Store the env file in an encrypted archive (age, GPG, or Ansible Vault)
since it contains the admin token.

---

## Step 6: Security Hardening

Vaultwarden is secure by default, but a few extra steps make it
production-ready.

**1. Use strong admin token**

```bash
# Generate a 64-byte admin token
openssl rand -base64 64
# 88 characters, unguessable
```

**2. Keep Vaultwarden on the internal network only**

Don't expose Vaultwarden to the public internet. Route through
Cloudflare Tunnel or WireGuard instead:

```yaml
# In docker-compose.yml — remove the proxy network
# and use Cloudflare Tunnel sidecar instead
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${TUNNEL_TOKEN}
    networks:
      - proxy
    depends_on:
      - vaultwarden
```

**3. Enable 2FA on your vault**

Bitwarden clients support TOTP, FIDO2/WebAuthn, and YubiKey. Enable
two-step login from the web vault settings:

```
Account Settings → Security → Two-Step Login
```

Even if someone gets your master password, they can't access your
vault without the second factor.

**4. Restrict database file permissions**

```bash
# Ensure the SQLite database has correct permissions
docker run --rm -v vaultwarden_data:/data alpine \
  sh -c "chmod 600 /data/db.sqlite3 && chown 1000:1000 /data/db.sqlite3"
```

**5. Monitor for unusual activity**

Check the Vaultwarden logs periodically:

```bash
docker compose logs vaultwarden | grep -i "failed login\|invalid token\|unauthorized"
```

If you use a monitoring stack, Vaultwarden exposes minimal metrics.
Add a log shipper (Grafana Alloy, Loki, or similar) to watch for
authentication failures.

---

## Step 7: Updates

Vaultwarden releases frequently with security patches and features.
The `:latest` tag is updated on each release. Update with:

```bash
cd /opt/vaultwarden

# Pull the latest image
docker compose pull vaultwarden

# Recreate the container with the updated image
docker compose up -d vaultwarden

# Remove old images
docker image prune -f
```

Check the [Vaultwarden releases page](https://github.com/dani-garcia/vaultwarden/releases)
for changelog highlights before updating.

Consider adding Watchtower or Diun for update notifications:

```yaml
# In your main docker-compose monitoring stack
services:
  diun:
    image: crazymax/diun:latest
    container_name: diun
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - DIUN_PROVIDERS_DOCKER=true
      - DIUN_NOTIF_TELEGRAM_WEBHOOK_URL=${TELEGRAM_WEBHOOK}
```

Diun checks for new images and sends a Telegram notification when an
update is available. Pair it with Watchtower for automatic updates on
non-critical containers.

---

## Summary

Deploying Vaultwarden gives you a full-featured, self-hosted password
manager that works with every Bitwarden client, uses minimal resources,
and gives you complete control over your credentials.

The setup from this guide takes under ten minutes and gives you:

- **Full Bitwarden API compatibility** — All official clients work
- **50 MB RAM footprint** — Runs alongside your other containers
- **Automated daily backups** — 14-day retention with SQLite consistency
- **SMTP notifications** — Email invites, password resets, account setup
- **Admin panel management** — User management without config file edits
- **Traefik TLS** — Automatic Let's Encrypt certificates
- **Disaster recovery** — Offsite backup preparation included

With Bitwarden's freemium tier being phased out and the recent security
incidents, now is the right time to bring password management in-house.
Vaultwarden makes it trivially easy — your passwords stay on your
hardware, under your control, with no subscription required.

The compose file and env template from this guide are available on the
GnTech GitHub repo. Point it at your domain, create your account,
disable signups, and you're done.
