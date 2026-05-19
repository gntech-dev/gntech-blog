---
title: "Restic Automated Backups — Encrypted Offsite Docker Backup for Homelab"
description: "Automate encrypted Docker volume backups with restic — local snapshots, S3-compatible offsite storage, cron scheduling, retention policies, and disaster recovery for homelab containers."
date: 2026-05-19T17:00:00-04:00
tags:
  - docker
  - backup
  - homelab
  - automation
  - storage
keywords:
  - restic Docker volume backup homelab
  - automated encrypted backup S3 Docker
  - Docker Compose restic cron schedule
  - restic backup retention policy homelab
  - Docker volume backup restore restic
  - restic MinIO S3 offsite backup
  - Docker container data backup strategy
summary: "Complete guide to automating encrypted Docker volume backups with restic — local snapshots with deduplication, S3-compatible offsite storage, cron scheduling, retention policies, and disaster recovery for homelab containers."
canonical: "https://gntech.dev/posts/restic-docker-backup-strategy/"
---

Your Docker containers generate data — Postgres databases, Gitea
repositories, Vaultwarden vaults, Grafana dashboards, Authentik
configurations. If any of this data disappears, how fast can you
recover?

If the answer is "uh, I should probably back that up," this guide
is for you.

Restic is an open-source backup tool purpose-built for this
scenario. It encrypts every snapshot, deduplicates data across
backup runs, supports multiple storage backends (local, S3, SFTP,
REST server, Backblaze B2), and integrates cleanly into Docker
environments without installing anything on your host.

This guide covers deploying restic as a Docker container,
configuring automated daily backups to both a local repository and
an S3-compatible offsite target, setting retention policies, and
walking through a full disaster recovery exercise.

---

## Why Restic Over Other Backup Tools

| Feature | Restic | Borg | Duplicati | rsync + tar |
|---------|--------|------|-----------|-------------|
| **Deduplication** | Yes | Yes | Yes | No |
| **Encryption** | Native AES-256-GCM | Native | Native | External |
| **S3/B2/SFTP** | Native | SFTP only | Yes | Via piping |
| **Docker native** | Explicit | Via wrapper | Yes | Manual |
| **Restore speed** | Fast | Moderate | Slow | Fast |
| **Single-file restore** | Yes (mount as FUSE) | Yes (FUSE mount) | Web UI only | Full archive |
| **Docker image** 50MB | Yes | No official | Yes | N/A |
| **Learning curve** | Low | Medium | Low | Low |

**When to choose restic:** You want Docker-native backup with
deduplication, encryption, cloud offsite storage, and simple CLI
restore. If you only need local incremental tar archives,
consider `docker run` with tar. If you need a web UI, look at
Duplicati or Kopia.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Docker Host                            │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Postgres │  │  Gitea   │  │ Nextcloud│  ...          │
│  │  volume  │  │  volume  │  │  volume  │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │             │             │                     │
│       └─────────────┼─────────────┘                     │
│                     │                                   │
│              ┌──────▼──────┐                            │
│              │   Restic    │  Daily cron backup          │
│              │  Container  │◄── runs docker exec         │
│              │             │    on volume containers     │
│              └──────┬──────┘                            │
│                     │                                   │
│        ┌────────────┼────────────┐                      │
│        ▼            ▼            ▼                      │
│  ┌──────────┐ ┌────────────┐ ┌──────────────┐          │
│  │  Local   │ │  MinIO/S3  │ │  B2/SFTP/    │          │
│  │ Backup   │ │  (offsite) │ │  REST Server │          │
│  └──────────┘ └────────────┘ └──────────────┘          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

The restic container runs on a cron schedule. Each run:

1. Uses `docker exec` to trigger database dumps inside running
   containers (Postgres, MySQL)
2. Mounts every Docker volume as read-only
3. Creates a restic snapshot with deduplication
4. Prunes old snapshots per retention policy
5. Forgets and removes expired snapshots

---

## Step 1 — Directory Structure and Environment

```bash
mkdir -p /opt/restic/{scripts,data}
cd /opt/restic
```

Create the environment file:

```bash
# /opt/restic/.env
# === Repository Locations ===
# Local repository (on a big disk or NAS mount)
RESTIC_REPOSITORY_LOCAL=/data/restic-repo

# S3-compatible offsite repository
RESTIC_REPOSITORY_S3=s3:https://s3.example.com/backups/docker-homelab

# === Credentials ===
# Generate with: openssl rand -base64 32
RESTIC_PASSWORD_FILE=/run/secrets/restic-password

# S3 credentials
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# === Backup Sources ===
# Comma-separated list of Docker volumes to back up
BACKUP_VOLUMES=postgres_data,gitea_data,grafana_data,authentik_postgres

# Docker containers that need pre-backup commands (database dumps, etc.)
PRE_BACKUP_CONTAINERS=postgres:pg_dumpall -U authentik -f /tmp/backup.sql

# === Retention Policy ===
RESTIC_KEEP_DAILY=7
RESTIC_KEEP_WEEKLY=4
RESTIC_KEEP_MONTHLY=6
RESTIC_KEEP_YEARLY=2

# === Notifications ===
# Optional: Healthchecks.io ping URL for monitoring
HEALTHCHECKS_URL=
```

Generate the repository password:

```bash
openssl rand -base64 32 > /opt/restic/restic-password
chmod 600 /opt/restic/restic-password
```

---

## Step 2 — Docker Compose Stack

```yaml
# /opt/restic/docker-compose.yml
services:
  restic:
    image: restic/restic:latest
    container_name: restic-backup
    restart: unless-stopped
    environment:
      - RESTIC_REPOSITORY=${RESTIC_REPOSITORY_LOCAL}
      - RESTIC_PASSWORD_FILE=/run/secrets/restic-password
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - TZ=America/Santo_Domingo
    volumes:
      # Mount the local backup target
      - /data/backups:/data/backups:rw
      # Mount every Docker volume you want to back up
      - postgres_data:/volumes/postgres_data:ro
      - gitea_data:/volumes/gitea_data:ro
      - grafana_data:/volumes/grafana_data:ro
      - authentik_postgres:/volumes/authentik_postgres:ro
      # Mount the Docker socket for pre-backup exec commands
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Mount scripts
      - ./scripts:/scripts:ro
      # Mount the password file
      - ./restic-password:/run/secrets/restic-password:ro
    secrets:
      - restic-password
    command: ["sleep", "infinity"]
    # Health check to ensure the container is running
    healthcheck:
      test: ["CMD", "restic", "version"]
      interval: 30s
      timeout: 10s
      retries: 3

secrets:
  restic-password:
    file: ./restic-password

volumes:
  postgres_data:
    external: true
  gitea_data:
    external: true
  grafana_data:
    external: true
  authentik_postgres:
    external: true
```

### Mount Additional Volumes

Find all Docker volumes on your host:

```bash
docker volume ls --format '{{.Name}}' | sort
```

For each volume you want backed up, add it to the compose file with
`external: true`. The mount path inside the container should map
cleanly: volume `myapp_data` → `/volumes/myapp_data`.

---

## Step 3 — Initialization Script

Restic repositories need to be initialized. The init script also
creates the offsite S3 repository if configured:

```bash
#!/bin/bash
# /opt/restic/scripts/init.sh
set -euo pipefail

source /opt/restic/.env 2>/dev/null || true

echo "=== Initializing Local Repository ==="
restic -r "$RESTIC_REPOSITORY_LOCAL" init
echo "Local repo initialized: $RESTIC_REPOSITORY_LOCAL"

if [ -n "${RESTIC_REPOSITORY_S3:-}" ]; then
  echo "=== Initializing S3 Repository ==="
  restic -r "$RESTIC_REPOSITORY_S3" init
  echo "S3 repo initialized: $RESTIC_REPOSITORY_S3"
fi

echo "=== Repositories Ready ==="
restic -r "$RESTIC_REPOSITORY_LOCAL" snapshots
```

Run it once:

```bash
docker compose run --rm restic /scripts/init.sh
```

Store the resulting repository ID and password in your password
manager. Without the password, your backups are unrecoverable.

---

## Step 4 — The Backup Script

This is the core. The script runs `docker exec` commands inside
database containers before backing up volumes, then creates
deduplicated snapshots:

```bash
#!/bin/bash
# /opt/restic/scripts/backup.sh
set -euo pipefail

# === Configuration ===
LOG_FILE="/var/log/restic-backup.log"
TIMESTAMP=$(date +%Y-%m-%d_%H:%M:%S)

log() {
  echo "[$TIMESTAMP] $*" | tee -a "$LOG_FILE"
}

log "=== Starting Backup ==="

# === Step A: Pre-backup commands ===
# Run database dumps inside active containers
log "Running pre-backup commands..."

# Postgres: dump all databases
if docker ps --format '{{.Names}}' | grep -q '^postgres$'; then
  log "  → Dumping Postgres databases"
  docker exec postgres pg_dumpall -U authentik -f /tmp/pre-backup.sql 2>/dev/null || \
    log "  ⚠ Postgres dump skipped or failed"
fi

# Gitea: run its dump command
if docker ps --format '{{.Names}}' | grep -q '^gitea$'; then
  log "  → Dumping Gitea data"
  docker exec gitea gitea dump -c /data/gitea/conf/app.ini -f /tmp/gitea-dump.zip \
    --type zip --skip-attachment-data 2>/dev/null || \
    log "  ⚠ Gitea dump skipped or failed"
fi

# === Step B: Create snapshots ===
log "Creating local snapshot..."
restic backup \
  --verbose \
  --host "$(hostname)" \
  --tag "daily" \
  /volumes/

if [ -n "${RESTIC_REPOSITORY_S3:-}" ]; then
  log "Creating S3 snapshot..."
  restic -r "$RESTIC_REPOSITORY_S3" backup \
    --verbose \
    --host "$(hostname)" \
    --tag "daily" \
    /volumes/
fi

# === Step C: Prune old snapshots ===
log "Pruning local snapshots..."
restic forget \
  --keep-daily "${RESTIC_KEEP_DAILY:-7}" \
  --keep-weekly "${RESTIC_KEEP_WEEKLY:-4}" \
  --keep-monthly "${RESTIC_KEEP_MONTHLY:-6}" \
  --keep-yearly "${RESTIC_KEEP_YEARLY:-2}" \
  --prune

if [ -n "${RESTIC_REPOSITORY_S3:-}" ]; then
  log "Pruning S3 snapshots..."
  restic -r "$RESTIC_REPOSITORY_S3" forget \
    --keep-daily "${RESTIC_KEEP_DAILY:-7}" \
    --keep-weekly "${RESTIC_KEEP_WEEKLY:-4}" \
    --keep-monthly "${RESTIC_KEEP_MONTHLY:-6}" \
    --keep-yearly "${RESTIC_KEEP_YEARLY:-2}" \
    --prune
fi

# === Step D: Check repository integrity ===
log "Checking local repository integrity..."
restic check --read-data-subset=5% 2>/dev/null || log "  ⚠ Check found issues"

# === Step E: Notify Healthchecks.io ===
if [ -n "${HEALTHCHECKS_URL:-}" ]; then
  curl -fsS -m 10 "$HEALTHCHECKS_URL" >/dev/null 2>&1 || true
fi

log "=== Backup Complete ==="
```

Make it executable:

```bash
chmod +x /opt/restic/scripts/backup.sh
```

---

## Step 5 — Cron Schedule

Run the backup daily at 2 AM using the host's cron. You can also
run it from within the container using a lightweight cron image,
but host cron is simpler and more reliable:

```bash
sudo crontab -e
```

Add:

```cron
# restic docker backup — daily at 02:00
0 2 * * * cd /opt/restic && docker compose exec -T restic /scripts/backup.sh >> /var/log/restic-cron.log 2>&1
```

Test the cron runs by executing it directly:

```bash
cd /opt/restic && docker compose exec restic /scripts/backup.sh
```

The first run takes longer because restic has to read every byte
and build the initial index. Subsequent runs are fast — typically
seconds to a few minutes depending on how much data changed,
because restic deduplicates at the block level.

---

## Step 6 — Verification and Monitoring

### Snapshot List

```bash
docker compose exec restic restic snapshots
```

Output shows all snapshots with timestamps, host, and tags:

```
repository /data/restic-repo opened successfully
ID        Time                 Host        Tags        Paths
────────────────────────────────────────────────────────────────
a1b2c3d4  2026-05-19 02:00:00  srv1        daily       /volumes
e5f6g7h8  2026-05-18 02:00:00  srv1        daily       /volumes
i9j0k1l2  2026-05-17 02:00:00  srv1        daily       /volumes
```

### Stats Per Snapshot

```bash
docker compose exec restic restic stats latest
docker compose exec restic restic stats a1b2c3d4
```

### Integrate with Healthchecks.io

This is critical for confidence. Setup:

1. Create a check at [healthchecks.io](https://healthchecks.io) (or
   self-host with the `healthchecks/docker` image)
2. Set the ping URL in your `.env`:
   ```
   HEALTHCHECKS_URL=https://hc-ping.com/your-uuid
   ```
3. The backup script pings after successful completion

If the backup doesn't run, Healthchecks sends an alert. This has
caught failed backups within 12 hours for me — way better than
finding out during a disaster.

### Drive Failure Simulation

Test by simulating a full mount failure:

```bash
docker compose exec restic sh -c "ls /volumes/postgres_data"  # should show data
# If this fails, your volume mount broke silently
```

---

## Step 7 — Disaster Recovery Walkthrough

This is the most important section. Test this **now**, not when
something breaks.

### 7a — Restore All Volumes to Latest

```bash
#!/bin/bash
# /opt/restic/scripts/restore-latest.sh
set -euo pipefail

RESTORE_DIR="/tmp/restic-restore"
mkdir -p "$RESTORE_DIR"

echo "=== Restoring latest snapshot ==="
restic restore latest --target "$RESTORE_DIR"

echo "Restored to: $RESTORE_DIR"
ls -la "$RESTORE_DIR/volumes/"
```

Run from inside the container:

```bash
docker compose exec restic /scripts/restore-latest.sh
```

Then copy individual volume data back:

```bash
# For a named Docker volume
docker run --rm -v postgres_data:/target -v /tmp/restic-restore/volumes/postgres_data:/source alpine \
  sh -c "cp -a /source/. /target/"

# Or restore specific directories
docker compose exec restic restic restore latest \
  --path /volumes/postgres_data \
  --target /tmp/restic-restore
```

### 7b — Restore a Specific File

Restic can mount snapshots as a FUSE filesystem for interactive
browsing:

```bash
docker compose exec restic restic mount /mnt/restic
```

In another terminal:

```bash
# List snapshots
ls /mnt/restic/
# Navigate snapshots by ID
ls /mnt/restic/a1b2c3d4/volumes/
# Copy a single file
cp /mnt/restic/a1b2c3d4/volumes/gitea_data/gitea/gitea.db /tmp/
```

Unmount when done:

```bash
docker compose exec restic fusermount -u /mnt/restic
```

### 7c — Full Disaster: Rebuild from Scratch

When the entire Docker host crashes:

1. Install Docker and Docker Compose on a new machine
2. Set up the restic container with the same `.env` and password
3. Initialize won't overwrite — it errors if the repo exists
4. Restore:

```bash
cd /opt/restic
docker compose up -d restic
docker compose exec restic restic restore latest --target /tmp/restore
```

5. For each volume, recreate and populate:

```bash
docker volume create postgres_data
docker run --rm -v postgres_data:/data -v /tmp/restore/volumes/postgres_data:/source alpine \
  sh -c "cp -a /source/. /data/"
```

6. Deploy the original compose stacks — data is waiting in the
   restored volumes

### 7d — Offsite Restore from S3

If the local machine is gone, restore from S3:

```bash
docker compose exec restic \
  restic -r "$RESTIC_REPOSITORY_S3" restore latest --target /tmp/restore-s3
```

The same commands work — just point at the S3 repository URL.

---

## Step 8 — Advanced Patterns

### Multiple Tags and Retention Policies

Use different tags for different backup tiers:

```bash
# Daily backup with "daily" tag
restic backup --tag "daily" /volumes/

# Before major changes, create a "pre-upgrade" tag
restic backup --tag "pre-upgrade" --tag "gitea-2.4" /volumes/gitea_data/

# Weekly full with "weekly" tag (same dedup, different tag)
restic backup --tag "weekly" /volumes/
```

Forget with tag filters:

```bash
# Keep all "pre-upgrade" snapshots indefinitely
restic forget --tag "pre-upgrade" --keep-daily 30

# Keep only 7 daily, 4 weekly for regular backups
restic forget --tag "daily" --keep-daily 7 --keep-weekly 4
```

### Excluding Non-Essential Data

Some volumes have cache or temp directories that don't need backup:

```bash
restic backup \
  --exclude /volumes/grafana_data/.cache \
  --exclude /volumes/**/tmp/ \
  --exclude '*.log' \
  /volumes/
```

### Parallel Backup to Multiple Destinations

The script already handles local + S3. Add more:

```bash
# After the local backup completes:
restic -r "$RESTIC_REPOSITORY_S3" backup /volumes/
restic -r "sftp:backup@nas.local:/backups/restic" backup /volumes/
restic -r "b2:my-bucket:homelab" backup /volumes/
```

Each repository has its own independent retention policy. The local
repo keeps more snapshots for fast recovery; the S3 repo keeps
fewer to save on storage cost.

### Pre-Backup Hooks for Database Dumps

For databases that don't have `docker exec` access mounted in the
compose file, use a sidecar pattern:

```yaml
# In your postgres docker-compose.yml
services:
  postgres-backup:
    image: postgres:16-alpine
    container_name: postgres-backup
    entrypoint: |
      sh -c 'pg_dumpall -h postgres -U authentik > /backups/dump.sql'
    environment:
      PGPASSWORD: ${PG_PASS}
    volumes:
      - postgres_backups:/backups
    depends_on:
      postgres:
        condition: service_healthy
```

Then have restic back up `postgres_backups` volume instead of the
raw Postgres data directory. This guarantees a consistent SQL-level
dump instead of a potentially inconsistent binary copy.

---

## Step 9 — Hardening the Setup

### Volume Mount Permissions

Restic runs as the `root` user in the container (by default). This
is necessary to read all Docker volumes. If you want to tighten it:

```yaml
services:
  restic:
    image: restic/restic:latest
    user: "0:0"  # explicitly root
```

### Encrypt the Restic Password

The restic password is stored in a file with `chmod 600`. For extra
security, use a secrets manager:

```bash
# Store password in Bitwarden/Vaultwarden and fetch at runtime
# This requires bw-cli in the container — extend the Dockerfile
```

### Backup the Backup

The restic local repository at `/data/backups/restic-repo` itself
should be included in your Proxmox backup strategy. It's just files
on disk — Proxmox Backup Server or ZFS snapshots handle this level.

For the offsite S3, ensure bucket versioning is enabled. If
ransomware encrypts your host and the backup script runs, restic
will snapshot the encrypted data as a "valid" backup. Versioning
lets you roll back to pre-encryption snapshots.

### Alert on Failure

Add a failure notification to the backup script:

```bash
# At the top
trap 'curl -fsS -m 10 "${HEALTHCHECKS_URL}/fail" 2>/dev/null || true' ERR
```

This pings Healthchecks with `/fail` if any command exits
non-zero, immediately alerting you.

---

## Step 10 — Monitoring Dashboard

Add a restic exporter to Prometheus for visualized backup
monitoring:

```bash
docker run -d \
  --name restic-exporter \
  --restart unless-stopped \
  -v /opt/restic/restic-password:/run/secrets/restic-password:ro \
  -e RESTIC_REPOSITORY=/data/restic-repo \
  -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  -v /data/backups:/data/restic-repo:ro \
  -p 9752:9752 \
  ghcr.io/tsaarni/restic-exporter:latest
```

Add a Prometheus scrape target:

```yaml
# /opt/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'restic'
    static_configs:
      - targets: ['10.0.20.30:9752']
```

Then build a Grafana dashboard showing:
- Last successful backup timestamp
- Snapshot count over time
- Repository size growth
- Backup duration
- Integrity check results

---

## The Cost Argument

Let's be concrete about what this setup costs:

- **restic container:** 50MB RAM, negligible CPU (runs 2-5 minutes
  daily)
- **Local storage:** ~5-15GB for 30 days of snapshots of 20GB of
  Docker volumes (deduplication works well for databases)
- **S3 storage:** ~2-10GB/month at $0.023/GB = $0.05-$0.23/month
- **Backblaze B2:** Same data at ~$0.006/GB = $0.01-$0.06/month
- **Healthchecks.io:** Free tier

For under $1/month, you get encrypted, deduplicated, offsite
backups with 30-day retention and instant alerting if backups fail.
Compare that to the cost of losing your Vaultwarden password vault,
Gitea repositories, or Grafana dashboards.

---

## Putting It All Together

**Step-by-step deployment checklist:**

1. Create directory structure: `mkdir -p /opt/restic/{scripts,data}`
2. Write `.env` with repository locations and credentials
3. Generate a 32-byte random password for restic
4. Write `docker-compose.yml` mounting all Docker volumes
5. Write `scripts/init.sh` and run it to create repositories
6. Write `scripts/backup.sh` with pre-backup, backup, prune, and
   check steps
7. Add cron entry to run the backup script daily at 02:00
8. Set up Healthchecks.io for failure alerting
9. Test a restore by running `restic restore latest`
10. Document the password securely — without it, backups are
    unrecoverable

**Recovery time objectives with this setup:**

| Scenario | RTO | RPO |
|----------|-----|-----|
| Accidentally deleted volume data | 10 minutes | Up to 24 hours |
| Docker host drive failure | 1-2 hours | Up to 24 hours |
| Full site disaster (use S3 backup) | 2-4 hours | Up to 24 hours |
| Ransomware (restore from S3 versioned) | 2-4 hours | Variable |

---

## Summary

A homelab without backups is a time bomb. Restic removes every
excuse for avoiding them:

- **Docker-native** — runs as a container, mounts volumes read-only,
  does not require agent installation inside application containers
- **Encrypted by default** — AES-256-GCM with a single password.
  No plaintext data ever hits disk or S3
- **Deduplicated** — 20 daily snapshots of changing databases take
  about as much space as the latest full backup plus the daily diffs
- **Multi-destination** — backup to local disk, S3, B2, SFTP, or
  any rest-server target in one run
- **Scriptable restore** — full disaster recovery is a shell script
  away. No proprietary tools, no vendor lock-in

Set it up once, test the restore, and stop worrying about losing
data. The $0.10/month for S3 storage is the cheapest insurance
your homelab will ever have.
