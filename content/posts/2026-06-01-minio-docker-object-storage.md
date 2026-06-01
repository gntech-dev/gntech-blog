---
title: "MinIO Docker Deployment — Self-Hosted S3-Compatible Object Storage"
description: "Deploy MinIO with Docker Compose for self-hosted S3-compatible object storage in your homelab. Configure buckets, access policies, Traefik reverse proxy, and backup workflows."
date: 2026-06-01T16:00:00-04:00
tags:
  - docker
  - storage
  - homelab
  - docker-compose
  - selfhosting
keywords:
  - MinIO Docker Compose homelab deployment
  - Self-hosted S3-compatible object storage Docker configuration
  - MinIO Traefik reverse proxy SSL setup
  - Homelab object storage bucket access policy
  - MinIO console web UI Docker setup
  - MinIO multi-drive erasure coding deployment
  - Docker S3 storage backup and migration
summary: "Deploy MinIO with Docker Compose for self-hosted S3-compatible object storage. Covers single-node and multi-drive setups, Traefik reverse proxy, bucket policies, and backup strategies."
canonical: "https://blog.gntech.me/posts/minio-docker-object-storage/"
---

## Why MinIO for Homelab Object Storage

The S3 API has become the universal interface for object storage. From backup tools like restic and duplicati, to applications like Immich, Mattermost, and Grafana Loki — everything speaks S3. Running a MinIO instance in your homelab gives you that API locally without depending on AWS, Wasabi, or Backblaze.

MinIO is a high-performance, S3-compatible object store written in Go. It runs as a single binary or Docker container, supports erasure coding for data protection, and ships with a web UI for management. Unlike hosted S3, you control the data, there are no egress fees, and it works perfectly on a single server or a cluster of homelab nodes.

**Key features for homelab use:**
- S3 API compatibility (works with all S3 SDKs and CLI tools)
- Built-in web console for management
- Erasure coding with configurable parity (N/2 and N/4)
- Bucket versioning and object locking (WORM)
- Identity management with IAM policies
- Prometheus metrics for monitoring
- Lightweight — ~50 MB RAM at idle

Use cases in a homelab include:
- **Backup target** for restic, borg, duplicati
- **Application storage** for Immich photos, Mattermost files, Grafana Loki chunks
- **Static file hosting** with public bucket policies
- **S3-compatible test environment** before deploying to production AWS

## Docker Compose Single-Node Deployment

MinIO is designed to run on a single machine or a cluster. For most homelabs, a single-node deployment with one or more drives is sufficient.

### Basic Docker Compose Setup

Create a directory and add this `docker-compose.yml`:

```yaml
services:
  minio:
    image: quay.io/minio/minio:latest
    container_name: minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ./data:/data
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: changeme-minio-2026
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3
```

The `command` line is critical: `server /data` starts MinIO serving on port 9000 (API), and `--console-address ":9001"` starts the web UI on port 9001. Without `--console-address`, the console and API share port 9000 with path-based routing, which is less clean for reverse proxy setups.

Replace `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` with strong credentials. Store these in your password manager — they are the admin keys for the entire instance.

Deploy with:

```bash
docker compose up -d
```

Verify the API is healthy:

```bash
curl -s http://localhost:9000/minio/health/live
```

A healthy response is an HTTP 200 with body `{"status":"alive"}`.

## Traefik Reverse Proxy Setup

Exposing MinIO through your Traefik reverse proxy gets you automatic Let's Encrypt TLS, a clean subdomain, and middleware security. MinIO exposes two services — the S3 API on port 9000 and the Console web UI on port 9001 — so you need two router definitions.

Add labels to the compose service and switch to an internal-only port mapping:

```yaml
services:
  minio:
    image: quay.io/minio/minio:latest
    container_name: minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - ./data:/data
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: changeme-minio-2026
      MINIO_SERVER_URL: https://s3.gntech.me
      MINIO_BROWSER_REDIRECT_URL: https://minio.gntech.me
    networks:
      - traefik-public
    labels:
      - "traefik.enable=true"
      # S3 API router
      - "traefik.http.routers.minio-s3.rule=Host(`s3.gntech.me`)"
      - "traefik.http.routers.minio-s3.entrypoints=websecure"
      - "traefik.http.routers.minio-s3.tls.certresolver=letsencrypt"
      - "traefik.http.services.minio-s3.loadbalancer.server.port=9000"
      # Console UI router
      - "traefik.http.routers.minio-ui.rule=Host(`minio.gntech.me`)"
      - "traefik.http.routers.minio-ui.entrypoints=websecure"
      - "traefik.http.routers.minio-ui.tls.certresolver=letsencrypt"
      - "traefik.http.services.minio-ui.loadbalancer.server.port=9001"
      - "traefik.http.routers.minio-ui.middlewares=secHeaders@file"

networks:
  traefik-public:
    external: true
```

Two environment variables are important when running behind a reverse proxy:

- `MINIO_SERVER_URL` — tells MinIO the external S3 API URL. S3 clients need this to generate pre-signed URLs correctly.
- `MINIO_BROWSER_REDIRECT_URL` — sets the redirect target for Console authentication callbacks. Without this, MinIO redirects to the internal port after login.

After deploying, access the Console at `https://minio.gntech.me` and the S3 API at `https://s3.gntech.me`.

## Initial MinIO Configuration

### Creating Access Keys and Buckets

Log into the MinIO Console. The left sidebar has menu sections for Buckets, Access Keys, Identity, and Monitoring.

**Create an access key:**
1. Go to **Access Keys** → **Create Access Key**
2. Give it a description (e.g., "restic-backups")
3. Optionally restrict it to specific buckets or paths
4. Save the generated key and secret — MinIO shows them only once

**Create a bucket:**
1. Go to **Buckets** → **Create Bucket**
2. Name it (e.g., `homelab-backups`, `immich-photos`)
3. Enable **Versioning** to protect against accidental overwrites
4. Set **Object Locking** if you need WORM compliance

### Bucket Access Policies

MinIO supports both managed policies and raw S3-style bucket policies. From the Console, you can attach built-in policies:

| Policy | Effect |
|--------|--------|
| `consoleAdmin` | Full admin access to MinIO itself |
| `diagnostics` | Read-only monitoring access |
| `readonly` | Read-only access to all buckets |
| `readwrite` | Read/write to all buckets |
| `writeonly` | Write-only (log sink pattern) |

For finer control, use a raw bucket policy in JSON. To make a bucket publicly readable (for static file hosting):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::public-files/*"]
    }
  ]
}
```

Paste this into **Buckets → [bucket name] → Anonymous** in the Console UI.

## Multi-Drive Erasure Coding Setup

For production homelabs, running MinIO with multiple disks provides data durability through erasure coding. MinIO splits objects into data and parity shards across drives, tolerating up to half the drives failing.

### Docker Compose with Multiple Volumes

Mount each physical or logical drive as a separate volume:

```yaml
services:
  minio:
    image: quay.io/minio/minio:latest
    container_name: minio
    restart: unless-stopped
    command: server /data{1...4} --console-address ":9001"
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - /mnt/disk1/minio:/data1
      - /mnt/disk2/minio:/data2
      - /mnt/disk3/minio:/data3
      - /mnt/disk4/minio:/data4
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: changeme-minio-2026
      MINIO_SERVER_URL: https://s3.gntech.me
```

The command `server /data{1...4}` tells MinIO to use all four directories as erasure-coded drives. With 4 drives and default parity (N/2), MinIO tolerates 2 drive failures while still serving reads and writes.

**Parity levels by drive count:**
- 4 drives: EC:4, parity 2 (survives 2 failures)
- 6 drives: EC:6, parity 2-4
- 8 drives: EC:8, parity 2-4
- 12 drives: EC:12, parity 2-6
- 16 drives: EC:16, parity 2-8

MinIO automatically selects optimal parity when not explicitly specified.

## Using the MinIO Client (mc)

The MinIO Client (`mc`) is a command-line tool that works with any S3-compatible service. The easiest way to use it in a homelab is with a Docker alias.

### Configure mc

```bash
# Docker alias for mc
alias mc="docker run --rm -it --network host quay.io/minio/mc"

# Set up an alias pointing to your MinIO instance
mc alias set homelab https://s3.gntech.me YOUR_ACCESS_KEY YOUR_SECRET_KEY
```

### Basic Operations

```bash
# List buckets
mc ls homelab

# List objects in a bucket
mc ls homelab/homelab-backups

# Copy a file to S3
mc cp /path/to/file.tar.gz homelab/homelab-backups/

# Mirror an entire directory (useful for backups)
mc mirror --watch /local/data homelab/homelab-data/

# Set a bucket policy
mc anonymous set public homelab/public-files

# Admin info (cluster status, disk usage)
mc admin info homelab
```

### Scripted Bucket Creation

For automated deployments, script bucket and user creation:

```bash
#!/bin/bash
# setup-minio.sh — run once after MinIO is deployed

mc alias set homelab https://s3.gntech.me "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"

# Create buckets
mc mb homelab/homelab-backups
mc mb homelab/immich-photos
mc mb homelab/logs

# Enable versioning on backup bucket
mc version enable homelab/homelab-backups

# Set lifecycle policy — delete objects older than 90 days
mc ilm import homelab/homelab-backups <<EOF
{
  "Rules": [
    {
      "ID": "expire-old-backups",
      "Status": "Enabled",
      "Expiration": {"Days": 90}
    }
  ]
}
EOF

# Create a restricted user (readwrite for one bucket only)
mc admin user add homelab immich-user MySecurePassword123
mc admin policy attach homelab readwrite --user immich-user
```

## Backup and Migration Strategies

MinIO itself stores S3 data on disk, so you have several backup options.

### Using mc Mirror for Backup

Mirror MinIO data to a local directory for offline backup:

```bash
mc mirror homelab/homelab-backups /backups/minio-mirror/
```

Or to another S3 service (S3-to-S3 replication):

```bash
mc alias set backblaze https://s3.us-west-004.backblazeb2.com B2_KEY B2_SECRET
mc mirror homelab/important-data backblaze/offsite-bucket/
```

### Restic with MinIO Backend

If MinIO is your backup target, configure restic with the S3 backend:

```bash
export AWS_ACCESS_KEY_ID=your_minio_access_key
export AWS_SECRET_ACCESS_KEY=your_minio_secret_key
export RESTIC_REPOSITORY=s3:https://s3.gntech.me/restic-repo

restic init
restic backup /opt/docker-data
```

### MinIO Versioning for Self-Service Recovery

Enable bucket versioning for automatic recovery from accidental deletions:

```bash
mc version enable homelab/homelab-data
```

List and restore object versions:

```bash
mc ls --versions homelab/homelab-data
# Copy a specific version back
mc cp homelab/homelab-data/backup.tar.gz --version-id "UUID" /restored/
```

### Volume-Level Backup

Stop the container and back up the data directory:

```bash
docker compose stop
rsync -av ./data/ /backup/minio-$(date +%Y%m%d)/
docker compose start
```

If your MinIO data directory is on a ZFS dataset, use ZFS snapshots for instant, crash-consistent backups:

```bash
zfs snapshot tank/minio@backup-$(date +%Y%m%d)
zfs send tank/minio@backup-20260601 | ssh backup-server "zfs recv tank/backups/minio"
```

## Prometheus Monitoring

MinIO exposes Prometheus metrics at the `/minio/v2/metrics/cluster` endpoint. Configure Prometheus to scrape it:

```yaml
# In prometheus.yml
scrape_configs:
  - job_name: minio
    metrics_path: /minio/v2/metrics/cluster
    scheme: https
    static_configs:
      - targets:
          - s3.gntech.me
```

Or scrape directly from Docker metrics if you bind the port:

```yaml
scrape_configs:
  - job_name: minio
    static_configs:
      - targets:
          - "10.0.20.30:9000"
```

Key metrics to alert on:
- `minio_disk_storage_bytes` / `minio_disk_free_bytes` — disk space
- `minio_s3_requests_total` — request rate
- `minio_s3_errors_total` — error rate
- `minio_heal_objects_total` — ongoing healing operations

## Resource Usage

MinIO is efficient on modest hardware:

| Resource | Idle | Under Load (10 concurrent clients) |
|----------|------|-----------------------------------|
| RAM | 40–60 MB | 200–400 MB |
| CPU | < 0.5% | 2–5% per core |
| Disk | Depends on data stored | I/O-bound on writes |

A single MinIO instance handles hundreds of concurrent S3 clients. For a homelab with 5–10 services using MinIO, the overhead is negligible.

## Best Practices

- **Use strong credentials** — `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` are the root keys. Do not share them with services. Create restricted access keys per application.
- **Always use HTTPS** — MinIO access keys are sent in plain text over HTTP. Run behind Traefik or provide your own TLS certificate.
- **Set `MINIO_SERVER_URL` correctly** — without this, pre-signed URLs generated by MinIO will point to the internal container address and break for clients hitting the reverse proxy.
- **Enable versioning on backup buckets** — protects against accidental overwrites or ransomware.
- **Use separate access keys per service** — if one service is compromised, revoke its key without affecting others.
- **Monitor disk space** — MinIO continues accepting writes until the disk is full. Set up Prometheus alerting or configure mc admin watchdog thresholds.
- **Pin your MinIO version** — instead of `:latest`, use a specific tag like `:RELEASE.2026-04-01T00-00-00Z` for reproducible deployments.

## Summary

MinIO brings S3-compatible object storage to your homelab with a lightweight Docker deployment. The S3 API is the lingua franca for modern application storage — backup tools, media servers, and analytics pipelines all speak it natively.

In this guide you deployed MinIO with Docker Compose, configured Traefik reverse proxy for both the S3 API and Console UI, set up erasure coding for data protection, learned the `mc` client for management and automation, and established backup strategies including versioning and cross-site replication. Deploy it today and give every service in your homelab its own S3 endpoint.
