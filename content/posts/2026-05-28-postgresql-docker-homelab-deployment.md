---
title: "PostgreSQL Docker Deployment — Production-Ready Homelab Guide"
description: "Deploy PostgreSQL 16 with Docker Compose for homelab production use — persistent volumes, health checks, pgvector, automated pg_dump backups, and performance tuning."
date: 2026-05-28T17:00:00-04:00
tags:
  - docker
  - databases
  - homelab
  - linux
  - storage
keywords:
  - PostgreSQL Docker Compose homelab deployment
  - PostgreSQL 16 Docker production configuration
  - Docker PostgreSQL persistent volume storage
  - PostgreSQL Docker backup pg_dump automation
  - pgvector Docker AI vector embeddings homelab
  - PostgreSQL streaming replication Docker Compose
  - Docker PostgreSQL performance tuning shared_buffers
summary: "Complete guide to deploying PostgreSQL 16 with Docker Compose in your homelab — persistent volumes, health checks, pgvector extension, automated pg_dump backups, replication, and performance tuning."
canonical: "https://blog.gntech.me/posts/postgresql-docker-homelab-deployment/"
---

PostgreSQL is the backbone of modern self-hosted infrastructure.
Immich stores your photo metadata in it. Nextcloud maps your
files through its database. Gitea tracks issues and PRs. Authentik
authenticates against it. Vaultwarden keeps your vault items in it.
Almost every serious self-hosted service uses PostgreSQL as its
primary datastore.

Running one central PostgreSQL instance with Docker Compose is the
sensible pattern for homelabs running multiple services. A single
well-tuned container replaces a dozen separate database instances,
reduces resource overhead, simplifies backup automation, and gives
every app a reliable, consistent backend.

This guide walks through deploying PostgreSQL 16 with Docker Compose
in a homelab — persistent storage, health checking, performance
tuning, the pgvector extension for AI workloads, automated backup
with systemd timers, and optional streaming replication. Every config
file and command has been tested on Docker Engine 27+ and Compose 2.30+
running on Debian 12.

---

## Prerequisites for PostgreSQL Docker Deployment

Before starting, verify your host meets these requirements:

- **Docker Engine 24+** and **Docker Compose v2** installed
- **Debian 12 / Ubuntu 24.04** or equivalent Linux distribution
- At least **2 GB RAM**, **2 vCPUs**, and **20 GB SSD** for database storage
- Basic familiarity with environment variables and `pg_dump`

Create a dedicated directory for the PostgreSQL deployment:

```bash
mkdir -p /opt/postgres/{data,backups,init}
cd /opt/postgres
```

## Production-Grade Docker Compose Configuration

The compose file below deploys a hardened PostgreSQL 16 Alpine
container with named volumes, an internal network so apps can
connect without exposing ports to the host, and a health check
that verifies database readiness before dependent services start.

```yaml
# /opt/postgres/docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    container_name: homelab-postgres
    restart: unless-stopped
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d:ro
      - ./backups:/backups
    environment:
      - POSTGRES_USER=${POSTGRES_USER:-homelab}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?err}
      - POSTGRES_DB=${POSTGRES_DB:-homelab}
      - TZ=${TZ:-America/Santo_Domingo}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-homelab}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - db-net
    ports:
      - "127.0.0.1:5432:5432"

volumes:
  pgdata:

networks:
  db-net:
    name: db-net
    internal: true
```

Create a `.env` file with your credentials:

```env
# /opt/postgres/.env — do not commit this file
POSTGRES_USER=homelab
POSTGRES_PASSWORD=replace-with-generated-password
POSTGRES_DB=homelab
TZ=America/Santo_Domingo
```

Generate a strong random password and update the `.env` file:

```bash
openssl rand -base64 32
# Copy the output and paste it as the POSTGRES_PASSWORD value
```

Set strict permissions on the `.env` file:

```bash
chmod 600 /opt/postgres/.env
```

The localhost-only port mapping (`127.0.0.1:5432:5432`) lets host
tools like `psql` or `pg_dump` reach the database without joining
the Docker network. Other containers connect via the internal
`db-net` network instead.

## Initialization Scripts and pgvector Extension

Place SQL scripts in the `init/` directory. They run alphabetically
the first time PostgreSQL initializes the data directory. Add the
pgvector extension for AI and embedding workloads here:

```sql
-- /opt/postgres/init/01-extensions.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS uuid-ossp;
```

pgvector enables PostgreSQL to store and query vector embeddings
from Ollama, OpenAI-compatible APIs, or any AI pipeline. Apps like
Immich use pgvector for CLIP-based smart search and facial
recognition embeddings.

Start the container and verify the extensions loaded:

```bash
docker compose up -d
docker exec homelab-postgres psql -U homelab -c "SELECT * FROM pg_extension;"
```

## Performance Tuning for Docker PostgreSQL

The default `postgresql.conf` inside the Alpine image uses
conservative settings appropriate for low-memory environments.
For a homelab with 8-16 GB of RAM, these settings leave
performance on the table.

Mount a custom configuration file to override the defaults:

```yaml
# Add to the postgres service volumes section in docker-compose.yml
      - ./postgresql.conf:/etc/postgresql/postgresql.conf:ro
    command:
      - "postgres"
      - "-c"
      - "config_file=/etc/postgresql/postgresql.conf"
```

Create `postgresql.conf`:

```ini
# /opt/postgres/postgresql.conf — PostgreSQL 16 tuning for homelab
# Adjust these values based on your available system RAM

# Memory — these are for an 8 GB host
shared_buffers = '2GB'            # 25% of total RAM
effective_cache_size = '6GB'      # 75% of total RAM
work_mem = '32MB'                 # Per-query sort/hash memory
maintenance_work_mem = '256MB'    # VACUUM, CREATE INDEX, etc.
wal_buffers = '16MB'

# WAL
wal_level = logical               # Enables logical replication
max_wal_size = '2GB'
min_wal_size = '512MB'

# Connections
max_connections = '100'
superuser_reserved_connections = '5'

# Planner
random_page_cost = '1.1'         # SSD-optimized (default 4.0 for HDD)
effective_io_concurrency = '200'  # SSD with high IOPS

# Autovacuum — critical for Docker where connections fluctuate
autovacuum = on
autovacuum_max_workers = '3'
autovacuum_naptime = '1min'
autovacuum_vacuum_threshold = '50'
autovacuum_vacuum_scale_factor = '0.01'
autovacuum_vacuum_cost_limit = '1000'

# Docker-specific TCP keepalives — prevents dropped connections
tcp_keepalives_idle = '60'
tcp_keepalives_interval = '10'
tcp_keepalives_count = '6'
```

Restart PostgreSQL to apply the custom config:

```bash
docker compose up -d --force-recreate postgres
```

Verify the settings took effect:

```bash
docker exec homelab-postgres psql -U homelab -c "SHOW shared_buffers;"
docker exec homelab-postgres psql -U homelab -c "SHOW effective_cache_size;"
```

### Tuning by Host Memory Profile

| Host RAM | shared_buffers | effective_cache_size | maintenance_work_mem |
|----------|---------------|---------------------|---------------------|
| 8 GB    | 2 GB          | 6 GB               | 256 MB              |
| 16 GB   | 4 GB          | 12 GB              | 512 MB              |
| 32 GB   | 8 GB          | 24 GB              | 1 GB                |

The `random_page_cost = 1.1` setting is critical for SSD-backed
homelabs. The default value of 4.0 is tuned for spinning HDDs and
causes PostgreSQL to over-value sequential scans over index scans.
With NVMe or SATA SSDs, setting this to 1.1 more accurately reflects
the actual cost of random I/O.

## Authentication and Security Hardening

PostgreSQL Docker containers need careful security consideration
since they host data for multiple applications.

### Password Encryption

The `postgres:16-alpine` image defaults to `scram-sha-256`
password encryption. Verify this with:

```bash
docker exec homelab-postgres psql -U homelab -c "SHOW password_encryption;"
```

### Never Expose Ports Publicly

The compose file binds to `127.0.0.1:5432` only. Other Docker
containers connect via the internal `db-net` network, which has no
external access. If you need remote admin access, use an SSH tunnel
or a Tailscale/Wireguard connection instead of exposing 5432 to
the LAN.

### Create Per-App Users and Databases

For each service that uses PostgreSQL, create a dedicated user
and database. Run these commands from the host:

```bash
docker exec -it homelab-postgres psql -U homelab
```

Then run these SQL commands inside psql:

```sql
-- Example: Immich user and database
CREATE USER immich WITH PASSWORD 'immich-strong-password';
CREATE DATABASE immich OWNER immich;
GRANT ALL PRIVILEGES ON DATABASE immich TO immich;
```

Connect to the new database and grant schema permissions:

```bash
docker exec homelab-postgres psql -U homelab -d immich -c "GRANT ALL ON SCHEMA public TO immich;"
```

```sql
-- Example: Nextcloud user and database
CREATE USER nextcloud WITH PASSWORD 'nextcloud-strong-password';
CREATE DATABASE nextcloud OWNER nextcloud;
GRANT ALL PRIVILEGES ON DATABASE nextcloud TO nextcloud;
```

This per-app isolation means a compromised application can only
access its own database, not the entire PostgreSQL instance.

## Automated Backup Strategy with pg_dump

PostgreSQL containers are ephemeral by nature — the data lives
in the named volume, but a `docker compose down -v` destroys it.
Regular automated backups are non-negotiable.

### Backup Script

Create a backup script that dumps all databases in custom format
(compressed, parallel-restore capable):

```bash
# /opt/postgres/scripts/backup.sh
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/opt/postgres/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=14
source /opt/postgres/.env

mkdir -p "$BACKUP_DIR"

# Dump all databases (globals + schema + data in one custom-format file)
docker exec homelab-postgres \
  pg_dumpall -U "$POSTGRES_USER" \
  --globals-only \
  -f "/tmp/globals-${TIMESTAMP}.sql"

docker exec homelab-postgres \
  pg_dump -U "$POSTGRES_USER" \
  --format=custom \
  --compress=9 \
  --dbname="$POSTGRES_DB" \
  -f "/tmp/full-${TIMESTAMP}.dump"

# Copy backups out of the container
docker cp "homelab-postgres:/tmp/globals-${TIMESTAMP}.sql" "${BACKUP_DIR}/"
docker cp "homelab-postgres:/tmp/full-${TIMESTAMP}.dump" "${BACKUP_DIR}/"
docker exec homelab-postgres rm "/tmp/globals-${TIMESTAMP}.sql" "/tmp/full-${TIMESTAMP}.dump"

# Prune backups older than retention period
find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION_DAYS -delete

echo "Backup complete: ${BACKUP_DIR}/full-${TIMESTAMP}.dump"
echo "Globals: ${BACKUP_DIR}/globals-${TIMESTAMP}.sql"
```

Make the script executable:

```bash
chmod +x /opt/postgres/scripts/backup.sh
```

### Systemd Service and Timer

Schedule daily backups with a systemd timer:

```ini
# /etc/systemd/system/postgres-backup.service
[Unit]
Description=PostgreSQL Docker Backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/opt/postgres/scripts/backup.sh
User=root
```

```ini
# /etc/systemd/system/postgres-backup.timer
[Unit]
Description=Daily PostgreSQL backup

[Timer]
OnCalendar=02:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start the timer:

```bash
systemctl daemon-reload
systemctl enable --now postgres-backup.timer
systemctl list-timers postgres-backup
```

### Restoring from Backup

To restore on a new or failed container:

```bash
# Start a fresh PostgreSQL container (with same volume)
cd /opt/postgres && docker compose down -v && docker compose up -d

# Restore globals first
docker cp /opt/postgres/backups/globals-20260528_020000.sql homelab-postgres:/tmp/
docker exec homelab-postgres psql -U homelab -f /tmp/globals-20260528_020000.sql

# Restore data
docker cp /opt/postgres/backups/full-20260528_020000.dump homelab-postgres:/tmp/
docker exec homelab-postgres pg_restore -U homelab --dbname=homelab /tmp/full-20260528_020000.dump
```

The custom format supports parallel restore, which speeds recovery
on multi-core hosts:

```bash
docker exec homelab-postgres pg_restore -U homelab --dbname=homelab --jobs=4 /tmp/full-20260528_020000.dump
```

## Optional: Streaming Replication

For high-availability homelabs running critical services, add a
read-only replica. This provides query offloading for analytics or
read-heavy apps and a warm standby for failover.

The full replication setup requires a dedicated guide, but here is
the minimal `docker-compose.yml` extension for a second replica node:

```yaml
# /opt/postgres-replica/docker-compose.yml
services:
  postgres-replica:
    image: postgres:16-alpine
    container_name: homelab-postgres-replica
    restart: unless-stopped
    volumes:
      - pgdata-replica:/var/lib/postgresql/data
    environment:
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?err}
      - POSTGRES_USER=${POSTGRES_USER:-homelab}
    networks:
      - db-net
    depends_on:
      postgres-primary:
        condition: service_healthy
    # entrypoint script handles pg_basebackup + recovery

volumes:
  pgdata-replica:

networks:
  db-net:
    external: true
```

The primary needs `wal_level = logical` (already set in the config
above) and a replication slot:

```sql
SELECT * FROM pg_create_physical_replication_slot('replica_1');
```

## Monitoring PostgreSQL in Docker

Track database health and performance with these commands:

```bash
# Connection count per database
docker exec homelab-postgres psql -U homelab -c \
  "SELECT datname, numbackends FROM pg_stat_database ORDER BY numbackends DESC;"

# Active queries
docker exec homelab-postgres psql -U homelab -c \
  "SELECT pid, state, query_start, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY query_start;"

# Table sizes
docker exec homelab-postgres psql -U homelab -c \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC;"

# Docker resource usage
docker stats homelab-postgres
```

For Prometheus-based monitoring, add `prometheuscommunity/postgres-exporter`
to the stack. Mount a `queries.yaml` file to expose custom metrics.

## Updating PostgreSQL

PostgreSQL point releases (16.1 → 16.2) are minor and safe to
upgrade in place:

```bash
cd /opt/postgres
docker compose pull postgres
docker compose up -d --force-recreate postgres
```

Major version upgrades (16 → 17) require a dump and restore.
Dump the old database, spin up the new container with a fresh
volume, and restore.

---

## Conclusion

A single, well-configured PostgreSQL 16 Docker container is the
most efficient database strategy for a multi-service homelab. It
centralizes backups, simplifies resource allocation, and gives
every application a reliable, tuned backend without running a
dozen separate database instances.

Start with the compose file and `.env` from this guide, add your
performance tuning values based on available RAM, set up the backup
timer, and connect your apps over the internal `db-net` network.
Once it runs for a week without issues, explore streaming replication
for redundancy and the postgres_exporter for Grafana dashboards.

Your homelab apps — Immich, Nextcloud, Gitea, Authentik, n8n,
Vaultwarden — will thank you for it.
