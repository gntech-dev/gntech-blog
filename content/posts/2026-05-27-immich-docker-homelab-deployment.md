---
title: "Immich Docker Deployment — Self-Hosted Google Photos Alternative"
description: "Complete Immich Docker Compose deployment guide for homelab — PostgreSQL, Redis, hardware transcoding, ML face detection, Traefik reverse proxy, and automated backup strategy."
date: 2026-05-27T09:30:00-04:00
tags:
  - docker
  - immich
  - selfhosting
  - media
  - storage
keywords:
  - Immich Docker Compose deployment guide homelab
  - Immich PostgreSQL Redis setup self-hosted photo backup
  - Immich hardware transcoding Intel QuickSync NVIDIA GPU
  - Immich machine learning face detection Docker GPU acceleration
  - Immich backup strategy database photos restic
  - Immich Traefik reverse proxy configuration SSL
  - self-hosted Google Photos alternative open source 2026
summary: "Deploy Immich as a self-hosted Google Photos alternative with Docker Compose — PostgreSQL, Redis, hardware-accelerated transcoding, ML-based search, and Traefik reverse proxy for secure remote access."
canonical: "https://gntech.dev/posts/immich-docker-homelab-deployment/"
---

Google Photos is convenient until you hit the 15 GB cap or realise
your entire photo library is being used to train someone else's
models. Immich solves both problems: it gives you Google Photos-grade
functionality — automatic backup, facial recognition, smart search,
album sharing — entirely self-hosted on your own hardware.

This guide walks through a production-grade Immich deployment with
Docker Compose: PostgreSQL for metadata, Redis for job queues,
hardware-accelerated transcoding, ML model GPU acceleration, Traefik
reverse proxy with automatic SSL, and a restic-based backup strategy
for both photos and the database.

All commands target Debian 12 / Ubuntu 24.04 with Docker Engine
27+ and Docker Compose v2.

---

## 1. Infrastructure Layout

Immich has four runtime components that need to coordinate:

| Service       | Role                                      |
|---------------|-------------------------------------------|
| immich-server | Main API server and web frontend          |
| immich-microservices | Background tasks — transcoding, ML   |
| postgres      | Metadata database — albums, users, tags   |
| redis         | Job queue and cache                        |
| immich-machine-learning | Facial recognition, smart search   |

Two optional but highly recommended additions are hardware transcoding
(for HEVC/AV1 video thumbnails) and GPU ML acceleration (for fast
face detection and CLIP-based search).

For storage, plan for: a fast SSD volume for Postgres data and Redis,
and a large HDD or NAS share for library storage (photos, videos,
thumbnails).

---

## 2. Directory Layout and Environment

Create the project tree:

```bash
mkdir -p /opt/immich/{db,redis,library,profile,backups}
cd /opt/immich
```

Create `.env` with your initial configuration:

```bash
cat > .env << 'EOF'
# ── Immich Environment ──────────────────────────────────
IMMICH_VERSION=release
TZ=America/Santo_Domingo
COMPOSE_PROJECT_NAME=immich

# ── PostgreSQL ───────────────────────────────────────────
DB_HOSTNAME=immich-postgres
DB_USERNAME=immich
DB_PASSWORD=$(openssl rand -base64 32)
DB_DATABASE_NAME=immich

# ── Redis ────────────────────────────────────────────────
REDIS_HOSTNAME=immich-redis

# ── Upload ───────────────────────────────────────────────
UPLOAD_LOCATION=./library

# ── Internal URLs ────────────────────────────────────────
IMMICH_MICROSERVICES_URL=http://immich-microservices:3001
IMMICH_MACHINE_LEARNING_URL=http://immich-machine-learning:3003

# ── Traefik / Domain (set your domain) ──────────────────
IMMICH_DOMAIN=photos.yourdomain.com
EOF
```

Store the DB password somewhere safe — you will need it for backups.

---

## 3. Docker Compose Configuration

```yaml
# /opt/immich/docker-compose.yml
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION}
    container_name: immich-server
    command: ["start.sh", "immich"]
    volumes:
      - ${UPLOAD_LOCATION}:/usr/src/app/upload:z
      - /etc/localtime:/etc/localtime:ro
    environment:
      - NODE_ENV=production
    env_file:
      - .env
    depends_on:
      - immich-redis
      - immich-postgres
    restart: unless-stopped
    networks:
      - immich-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.immich.rule=Host(`${IMMICH_DOMAIN}`)"
      - "traefik.http.routers.immich.entrypoints=websecure"
      - "traefik.http.routers.immich.tls.certresolver=letsencrypt"
      - "traefik.http.services.immich.loadbalancer.server.port=2283"

  immich-microservices:
    image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION}
    container_name: immich-microservices
    command: ["start.sh", "microservices"]
    volumes:
      - ${UPLOAD_LOCATION}:/usr/src/app/upload:z
      - /etc/localtime:/etc/localtime:ro
    environment:
      - NODE_ENV=production
    env_file:
      - .env
    depends_on:
      - immich-redis
      - immich-postgres
    restart: unless-stopped
    networks:
      - immich-net

  immich-machine-learning:
    image: ghcr.io/immich-app/immich-machine-learning:${IMMICH_VERSION}
    container_name: immich-ml
    volumes:
      - ./model-cache:/cache:z
    env_file:
      - .env
    restart: unless-stopped
    networks:
      - immich-net
    # ── GPU acceleration (optional) ──────────────
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]

  immich-postgres:
    image: tensorchord/pgvecto-rs:pg14-v0.3.0
    container_name: immich-postgres
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_USER: ${DB_USERNAME}
      POSTGRES_DB: ${DB_DATABASE_NAME}
    volumes:
      - ./db:/var/lib/postgresql/data:z
    restart: unless-stopped
    networks:
      - immich-net
    healthcheck:
      test: pg_isready --dbname='${DB_DATABASE_NAME}' --username='${DB_USERNAME}' || exit 1
      interval: 10s
      timeout: 5s
      retries: 5

  immich-redis:
    image: redis:7-alpine
    container_name: immich-redis
    volumes:
      - ./redis:/data:z
    restart: unless-stopped
    networks:
      - immich-net
    healthcheck:
      test: redis-cli ping || exit 1
      interval: 10s
      timeout: 3s
      retries: 5

networks:
  immich-net:
    name: immich-net
    external: true
```

Create the external Docker network if it does not already exist:

```bash
docker network create immich-net
```

---

## 4. Traefik Reverse Proxy Integration

If you already run Traefik as your edge router, add the Traefik
network to the Immich Compose file and let Traefik handle SSL.

Add this to the bottom of the services section in
`docker-compose.yml`:

```yaml
networks:
  immich-net:
    name: immich-net
    external: true
```

Then connect Immich to your Traefik network:

```bash
docker network connect traefik-net immich-server
```

The labels on the `immich-server` service (shown above) assume
Traefik's `letsencrypt` certificate resolver is configured. If you
use Caddy or Nginx Proxy Manager instead, configure a reverse proxy
pass to `http://immich-server:2283`.

---

## 5. First Boot and Initial Setup

Pull images and start the stack:

```bash
cd /opt/immich
docker compose pull
docker compose up -d
```

Wait 30-60 seconds for Postgres to initialise, then check logs:

```bash
docker compose logs -f immich-server
```

You should see `Immich Server is running on port 3001` once it is
ready.

Open `https://photos.yourdomain.com` (or `http://localhost:2283`
locally) and create the initial admin account. This account is the
system administrator — store the credentials in your password
manager immediately.

### 5.1 Postgres Tuning for Immich

Immich generates a lot of writes during upload and ML processing.
Tune Postgres inside the container:

```bash
docker exec -it immich-postgres \
  sh -c "echo 'shared_buffers=512MB' >> /var/lib/postgresql/data/postgresql.conf"
docker exec -it immich-postgres \
  sh -c "echo 'effective_cache_size=2GB' >> /var/lib/postgresql/data/postgresql.conf"
docker exec -it immich-postgres \
  sh -c "echo 'maintenance_work_mem=256MB' >> /var/lib/postgresql/data/postgresql.conf"
docker compose restart immich-postgres
```

Adjust `shared_buffers` to 25% of available RAM, and
`effective_cache_size` to 75% of available RAM.

---

## 6. Hardware Transcoding

Immich transcodes video thumbnails on the fly. Without hardware
acceleration, a 4K HEVC to WebP thumbnail conversion drains CPU.
Enable GPU passthrough in the `immich-microservices` service.

### 6.1 Intel QuickSync (QSV)

Add to the `immich-microservices` service:

```yaml
  immich-microservices:
    # ... existing config ...
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "44"  # video group
```

Then in the Immich admin panel:
**Administration → Video Transcoding Settings → Hardware Acceleration → Intel QSV**

### 6.2 NVIDIA GPU

Add to `immich-microservices`:

```yaml
  immich-microservices:
    # ... existing config ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, video]
```

The `video` capability enables NVENC/NVDEC for hardware video
encoding and decoding.

In the admin panel:
**Hardware Acceleration → NVIDIA NVENC/NVDEC**

### 6.3 Verify Transcoding

Upload a short HEVC video through the Immich web UI, then check that
the microservice used the GPU:

```bash
# Intel
docker exec immich-microservices ls /dev/dri

# NVIDIA
docker exec immich-microservices nvidia-smi
```

---

## 7. Machine Learning Acceleration

The `immich-machine-learning` container handles facial recognition,
object detection (CLIP), and smart search embeddings. These are
computationally expensive — expect 1-3 seconds per image on CPU, or
50-100 ms on GPU.

Enable GPU for the ML container by uncommenting the `deploy` block
in the `immich-machine-learning` service section of the compose file,
then restart:

```bash
docker compose up -d --force-recreate immich-machine-learning
```

After enabling, go to **Administration → Machine Learning Settings**
and set:

- Facial Recognition → Enabled
- CLIP Search → Enabled  
- Scene Detection → Enabled

Trigger a full re-extraction on existing photos:

**Administration → Jobs → All → Click the gear icon → Run All**

Monitor progress from the command line:

```bash
docker compose logs -f immich-microservices
```

---

## 8. Mobile App Configuration

Immich has native apps for Android and iOS. Configure them to
connect to your Traefik domain:

1. Install the Immich app from the app store
2. **Connection → Server Endpoint → `https://photos.yourdomain.com`**
3. Log in with your admin credentials
4. Enable **Background Backup** (Android) or **Backup over Cellular**
   (both platforms)

The app syncs new photos within minutes of being taken. You can
check sync status from the app's **Backup** tab.

---

## 9. Backup Strategy

Immich stores two types of data: the PostgreSQL database (metadata)
and uploaded files (raw photos and videos on disk). A proper backup
strategy covers both.

### 9.1 Database Backup with pg_dump

Create a backup script:

```bash
#!/bin/bash
# /opt/immich/scripts/backup-db.sh
set -euo pipefail

BACKUP_DIR="/opt/immich/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=14
source /opt/immich/.env

mkdir -p "$BACKUP_DIR"
docker exec immich-postgres \
  pg_dump -U "$DB_USERNAME" -d "$DB_DATABASE_NAME" \
  --format=custom --compress=9 \
  -f "/tmp/immich-${TIMESTAMP}.dump"
docker cp "immich-postgres:/tmp/immich-${TIMESTAMP}.dump" \
  "${BACKUP_DIR}/immich-${TIMESTAMP}.dump"
docker exec immich-postgres \
  rm "/tmp/immich-${TIMESTAMP}.dump"

find "$BACKUP_DIR" -name "immich-*.dump" -mtime +$RETENTION_DAYS -delete
echo "DB backup: immich-${TIMESTAMP}.dump"
```

Make it executable and schedule it:

```bash
chmod +x /opt/immich/scripts/backup-db.sh
```

### 9.2 Systemd Timer for Daily Backups

```ini
# /etc/systemd/system/immich-backup.service
[Unit]
Description=Immich Database Backup
After=docker.service

[Service]
Type=oneshot
ExecStart=/opt/immich/scripts/backup-db.sh
User=root
```

```ini
# /etc/systemd/system/immich-backup.timer
[Unit]
Description=Daily Immich DB backup

[Timer]
OnCalendar=03:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now immich-backup.timer
```

### 9.3 Restic Backup for Library Files

Use restic to back up the library directory to an S3-compatible
storage endpoint (MinIO, Backblaze B2, or Wasabi):

```bash
# /opt/immich/scripts/backup-library.sh
#!/bin/bash
set -euo pipefail

export RESTIC_REPOSITORY="s3:https://s3.yourdomain.com/immich-library"
export RESTIC_PASSWORD="<your-restic-password>"
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."

restic backup /opt/immich/library \
  --tag immich-library \
  --exclude "*.tmp" \
  --verbose

restic forget \
  --tag immich-library \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --prune
```

Schedule with a second systemd timer, or combine both jobs into a
single service file for simplicity.

---

## 10. Performance Tuning and Resource Limits

Immich can use significant resources during initial ML processing
and first-time transcoding. Set container-level resource limits to
prevent it from starving other services:

```yaml
  immich-server:
    # ... existing config ...
    deploy:
      resources:
        limits:
          memory: 2G

  immich-microservices:
    # ... existing config ...
    deploy:
      resources:
        limits:
          memory: 4G

  immich-machine-learning:
    # ... existing config ...
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "4"
```

For the initial library import (first upload of thousands of photos),
raise the microservices limit temporarily, then dial it back.

### 10.1 Docker System Pruning

Immich generates many intermediate objects during transcoding and
thumbnail generation. Schedule a weekly prune:

```bash
# /etc/cron.weekly/immich-cleanup
#!/bin/bash
docker system prune -f --filter "until=72h"
```

---

## 11. Updating Immich

Immich releases frequently — typically monthly. Update with zero
downtime using rolling restarts:

```bash
cd /opt/immich
docker compose pull
docker compose up -d --remove-orphans
docker image prune -f
```

Check the [Immich release notes](https://github.com/immich-app/immich/releases)
before updating — major releases sometimes require manual database
migration steps or version-specific upgrade paths.

---

## 12. Final Checks

After deployment, verify the full stack is running:

```bash
docker compose ps
docker compose logs --tail=20 immich-server
```

Open the web UI, upload a test photo, trigger a smart search,
and confirm facial recognition detects a known face. If everything
works, enable the mobile app backups and point your family to
the Immich URL.

Immich replaces Google Photos without the privacy trade-off. Your
photos stay on your drives, your face data stays on your server,
and the features — timeline view, album sharing, partner sharing,
smart search — match or exceed what the cloud offers. Set up backups
early and the rest takes care of itself.
