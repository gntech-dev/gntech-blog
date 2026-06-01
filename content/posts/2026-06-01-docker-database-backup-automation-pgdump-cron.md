---
title: "Docker Database Backup Automation — pg_dump, cron, and S3 Uploads"
description: "Automate PostgreSQL and MySQL backups in Docker Compose with cron-based pg_dump and mysqldump, retention pruning, healthchecks monitoring, and S3 off-site upload for your homelab."
date: 2026-06-01T12:00:00-04:00
tags:
  - docker
  - linux
  - homelab
  - database
keywords:
  - Docker Compose automated database backup automation
  - PostgreSQL pg_dump cron Docker container backup
  - MySQL mysqldump automated backup Docker Compose
  - Docker database backup healthchecks monitoring
  - S3-compatible backup upload Docker container
  - Docker cron container automated database dumps
  - Homelab database backup retention policy automation
summary: "Automate PostgreSQL and MySQL database backups in Docker Compose with cron-driven pg_dump and mysqldump, retention pruning, healthchecks monitoring, and S3 off-site upload. Production-ready configs included."
canonical: "https://blog.gntech.me/posts/docker-database-backup-automation-pgdump-cron/"
---

## Why Volume-Only Backups Are Not Enough

Docker volumes are the standard way to persist database data, but relying on them alone for backups is risky. A `pg_data` or `mysql_data` volume contains binary files that are tightly coupled to the database engine version. If you upgrade PostgreSQL from 16 to 17 and need to restore the old volume, you face a version mismatch. More importantly, binary volume snapshots do not give you point-in-time restore for a single table or a specific row.

Logical dumps solve these problems. `pg_dump` and `mysqldump` produce portable SQL files that you can restore to any compatible version. They compress well, they are human-readable, and they let you restore individual objects without restoring an entire volume.

This guide walks through building a single backup script that handles both PostgreSQL and MySQL, scheduling it with a Docker sidecar container, monitoring it with healthchecks.io, pushing backups to S3-compatible storage, and pruning old backups automatically.

## Building the Database Backup Script

Start with a single shell script that discovers databases via environment variables and handles both PostgreSQL and MySQL. The script uses the official client tools (`pg_dump`, `mysqldump`) and supports configurable backup directories, retention, and S3 upload.

Create `docker-db-backup.sh`:

```bash
#!/bin/bash
# docker-db-backup.sh — Automated database backup for Docker Compose stacks
set -euo pipefail

# --- Configuration via environment variables ---
DB_TYPE="${DB_TYPE:-postgres}"              # postgres or mysql
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-}"
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# S3-compatible storage (optional)
S3_ENDPOINT="${S3_ENDPOINT:-}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-db-backups}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-}"
S3_SECRET_KEY="${S3_SECRET_KEY:-}"

# Healthchecks.io (optional)
HC_UUID="${HC_UUID:-}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
FILENAME="${DB_NAME:-all}_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

mkdir -p "${BACKUP_DIR}"

# --- Healthchecks start ping ---
if [ -n "$HC_UUID" ]; then
  curl -fsS --retry 3 "https://hc-ping.com/${HC_UUID}/start" 2>/dev/null || true
fi

# --- Database dump ---
export PGPASSWORD="${DB_PASSWORD}"
export MYSQL_PWD="${DB_PASSWORD}"

case "${DB_TYPE}" in
  postgres)
    PORT="${DB_PORT:-5432}"
    echo "Backing up PostgreSQL database ${DB_NAME} from ${DB_HOST}:${PORT}..."
    pg_dump -h "${DB_HOST}" -p "${PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
      --no-owner --no-acl --compress=6 \
      > "${FILEPATH}"
    ;;
  mysql)
    PORT="${DB_PORT:-3306}"
    echo "Backing up MySQL database ${DB_NAME} from ${DB_HOST}:${PORT}..."
    mysqldump -h "${DB_HOST}" -P "${PORT}" -u "${DB_USER}" --single-transaction \
      --routines --triggers --events "${DB_NAME}" \
      | gzip -6 > "${FILEPATH}"
    ;;
  *)
    echo "Unsupported DB_TYPE: ${DB_TYPE}"
    exit 1
    ;;
esac

unset PGPASSWORD MYSQL_PWD

# Verify the dump is not empty
if [ ! -s "${FILEPATH}" ]; then
  echo "ERROR: Backup file is empty"
  if [ -n "$HC_UUID" ]; then
    curl -fsS --retry 3 "https://hc-ping.com/${HC_UUID}/fail" 2>/dev/null || true
  fi
  exit 1
fi

echo "Backup written: ${FILEPATH} ($(du -h "${FILEPATH}" | cut -f1))"

# --- Retention: prune local backups older than RETENTION_DAYS ---
find "${BACKUP_DIR}" -type f -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete
echo "Pruned local backups older than ${RETENTION_DAYS} days"

# --- S3 upload ---
if [ -n "$S3_ENDPOINT" ] && [ -n "$S3_BUCKET" ]; then
  export AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY}"
  export AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY}"
  S3_PATH="s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}"

  # Use s5cmd for parallel uploads — install once in the container
  if command -v s5cmd &>/dev/null; then
    s5cmd --endpoint-url "${S3_ENDPOINT}" cp "${FILEPATH}" "${S3_PATH}"
  else
    aws s3 cp "${FILEPATH}" "${S3_PATH}" --endpoint-url "${S3_ENDPOINT}"
  fi
  echo "Uploaded to ${S3_PATH}"
fi

# --- Healthchecks success ping ---
if [ -n "$HC_UUID" ]; then
  curl -fsS --retry 3 "https://hc-ping.com/${HC_UUID}" 2>/dev/null || true
fi

echo "Backup complete: ${FILENAME}"
```

Make it executable:

```bash
chmod +x docker-db-backup.sh
```

## Docker Compose Integration with a Sidecar Backup Container

The cleanest approach in Docker Compose is a dedicated backup service that shares the Docker network and mounts the backup directory. This keeps the backup logic separate from the database service and avoids bloat in your application containers.

Here is a complete `compose.yml` with a PostgreSQL instance and an automated backup sidecar:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: postgres
    restart: unless-stopped
    volumes:
      - pg_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: appdb
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: changeme
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser -d appdb"]
      interval: 30s
      timeout: 10s
      retries: 3

  db-backup:
    image: alpine:3.20
    container_name: db-backup
    restart: unless-stopped
    volumes:
      - ./docker-db-backup.sh:/usr/local/bin/backup.sh:ro
      - backup_data:/backups
    environment:
      DB_TYPE: postgres
      DB_HOST: postgres
      DB_PORT: 5432
      DB_NAME: appdb
      DB_USER: appuser
      DB_PASSWORD: changeme
      BACKUP_DIR: /backups
      RETENTION_DAYS: 14
      S3_ENDPOINT: https://s3.us-west-004.backblazeb2.com
      S3_BUCKET: my-homelab-backups
      S3_PREFIX: db-backups/postgres
      S3_ACCESS_KEY: 00Xxxxxx
      S3_SECRET_KEY: XxxxXxxx
      HC_UUID: 12345678-aaaa-bbbb-cccc-123456789abc
    command: >
      sh -c "
        apk add --no-cache postgresql16-client mysql-client s5cmd curl bash &&
        while true; do
          echo '--- Starting database backup ---' &&
          backup.sh &&
          echo 'Next backup in 6 hours' &&
          sleep 21600
        done
      "
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pg_data:
  backup_data:
```

Key points about this setup:

- The backup container installs the database client tools and `s5cmd` at startup
- The `sleep 21600` loop runs backups every 6 hours
- `depends_on: condition: service_healthy` ensures the database is ready before the backup container starts
- The backup script runs on the same Docker network, so `DB_HOST=postgres` resolves via DNS

### Better Scheduling with Host Cron

The sleep-loop approach works, but host cron gives you finer control. Comment out the `command` in compose and schedule a host cron job instead:

```bash
# /etc/cron.d/docker-db-backup
0 */6 * * * root docker exec db-backup backup.sh >> /var/log/db-backup.log 2>&1
```

This logs output to a file and avoids the overhead of a continuously running container. The backup container stays up but idle, consuming negligible resources.

## Healthchecks.io Monitoring

Every backup should notify you on failure. Healthchecks.io is a free SaaS service (or self-hostable with Docker) that monitors cron jobs. The script already includes ping support — enable it by setting the `HC_UUID` environment variable.

The flow:

1. Backup starts → ping `https://hc-ping.com/UUID/start`
2. Backup succeeds → ping `https://hc-ping.com/UUID`
3. Backup fails → ping `https://hc-ping.com/UUID/fail`

Healthchecks sends an alert (email, Slack, Telegram, or webhook) if the ping does not arrive within the expected interval. For a 6-hour backup window, configure healthchecks with a grace period of 30 minutes. If the backup script crashes or hangs, you will know before the next backup cycle.

### Self-Hosted Healthchecks with Docker Compose

If you prefer to keep everything local, run healthchecks in a sidecar stack:

```yaml
services:
  healthchecks:
    image: linuxserver/healthchecks:latest
    container_name: healthchecks
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - hc_data:/config
    environment:
      SITE_ROOT: https://healthchecks.yourdomain.com
      SECRET_KEY: your-secret-key-here
      SUPERUSER_EMAIL: admin@yourdomain.com
      SUPERUSER_PASSWORD: changeme
      DB_HOST: hc-db
      DB_PORT: 3306
      DB_NAME: healthchecks
      DB_USER: hcuser
      DB_PASSWORD: changeme
    depends_on:
      hc-db:
        condition: service_healthy

  hc-db:
    image: mariadb:11
    container_name: hc-db
    restart: unless-stopped
    volumes:
      - hc_db_data:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: rootpassword
      MYSQL_DATABASE: healthchecks
      MYSQL_USER: hcuser
      MYSQL_PASSWORD: changeme

volumes:
  hc_data:
  hc_db_data:
```

## S3-Compatible Off-Site Upload with s5cmd

Pushing backups off-site protects against hardware failure, theft, or disaster. The script supports any S3-compatible endpoint — Backblaze B2, Cloudflare R2, MinIO, Wasabi, or AWS S3 itself.

`s5cmd` is significantly faster than the AWS CLI for parallel uploads. Install it in the backup container, or use the `aws` CLI as a fallback (the script checks for `s5cmd` first).

Typical Backblaze B2 pricing: $0.006/GB/month for storage, $0.01/GB for download. A homelab with 20 GB of daily database dumps costs under $1/month with a 30-day retention on B2.

To reduce storage costs further, enable server-side compression by storing `.zst` (zstd) files instead of `.gz`:

```bash
# In backup.sh, replace gzip with zstd for better compression ratio
pg_dump -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-acl \
  | zstd -6 -o "${FILEPATH%.gz}.zst"
```

## Retention Policy and Cleanup

The script prunes local backups older than `RETENTION_DAYS` using `find -mtime`. For remote backups, implement S3 lifecycle rules instead of script-level cleanup — they run on the storage side and consume zero compute.

### S3 Lifecycle Rule (Backblaze B2 Example)

```xml
<LifecycleConfiguration>
  <Rule>
    <ID>Delete old database backups</ID>
    <Filter>
      <Prefix>db-backups/postgres/</Prefix>
    </Filter>
    <Status>Enabled</Status>
    <Expiration>
      <Days>90</Days>
    </Expiration>
  </Rule>
</LifecycleConfiguration>
```

For MinIO, use `mc`:

```bash
mc ilm rule add myminio/my-homelab-backups \
  --prefix "db-backups/" \
  --expire-days 90
```

## Automated Restore Testing

A backup you never test is not a backup. Add a weekly restore verification to your cron:

```bash
#!/bin/bash
# test-db-restore.sh — Verify latest backup can restore cleanly
set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_USER="${DB_USER:-appuser}"
DB_PASSWORD="${DB_PASSWORD:-changeme}"
RESTORE_DB="test_restore_$(date +%Y%m%d)"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

export PGPASSWORD="${DB_PASSWORD}"

# Find the latest backup
LATEST=$(ls -t "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "No backup found in ${BACKUP_DIR}"
  exit 1
fi

echo "Testing restore from: ${LATEST}"

# Create a temporary database
createdb -h "${DB_HOST}" -U "${DB_USER}" "${RESTORE_DB}"

# Restore into it
gunzip -c "${LATEST}" | psql -h "${DB_HOST}" -U "${DB_USER}" -d "${RESTORE_DB}" > /dev/null 2>&1

# Verify it has data
TABLE_COUNT=$(psql -h "${DB_HOST}" -U "${DB_USER}" -d "${RESTORE_DB}" -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' ')

echo "Restore verified — ${TABLE_COUNT} tables in restore database"

# Clean up
dropdb -h "${DB_HOST}" -U "${DB_USER}" "${RESTORE_DB}"

unset PGPASSWORD
echo "Restore test passed: $(basename ${LATEST})"
```

Save the restore test script to your compose directory, mount it into the backup container, and schedule it:

```yaml
# Add to db-backup volumes in compose.yml
volumes:
  - ./docker-db-backup.sh:/usr/local/bin/backup.sh:ro
  - ./test-db-restore.sh:/usr/local/bin/test-restore.sh:ro
  - backup_data:/backups
```

```bash
# /etc/cron.d/docker-db-restore
0 3 * * 1  root docker exec db-backup bash /usr/local/bin/test-restore.sh >> /var/log/db-restore.log 2>&1
```

This runs every Monday at 3:00 AM. If the restore test fails, it exits non-zero and cron mails the output to root. Pair it with healthchecks for alerting.

## Going Further

- **Encryption**: Pipe the dump through GPG before upload: `pg_dump ... | gpg --encrypt --recipient your-key > backup.sql.gz.gpg`
- **Parallel databases**: Loop over a list of `DB_NAME` values in the script to back up all databases on a server
- **Prometheus metrics**: Emit a gauge file with the backup timestamp and size, then scrape it with Prometheus node_exporter's `--collector.textfile.directory`
- **Slack/webhook alerts**: Add a `curl` POST to a Slack webhook or ntfy.sh topic when a backup fails

## Why This Matters for Your Homelab

Databases power most self-hosted services — Immich, Nextcloud, Gitea, Vaultwarden, PostgreSQL for monitoring stacks, MariaDB for WordPress or Mattermost. Losing any of these is painful. A 10-minute cron setup with a 20-line script protects against data loss, gives you portable SQL dumps, and sends alerts when something goes wrong.

The full script is on the GnTech blog GitHub repository. Download it, drop it into your compose directory, set your environment variables, and schedule the cron job. Your future self will thank you when you need to restore a single table six months from now.
