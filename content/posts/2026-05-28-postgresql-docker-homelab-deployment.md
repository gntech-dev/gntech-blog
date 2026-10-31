---
title: "PostgreSQL with Docker Compose — Deployment and Recovery Boundaries"
description: "Start a private PostgreSQL 16 instance, verify persistence, separate application roles, and follow the tested backup and restore lab."
date: 2026-05-28T17:00:00-04:00
tags:
  - docker
  - databases
  - homelab
  - linux
  - storage
keywords:
  - PostgreSQL Docker Compose
  - PostgreSQL persistent storage
  - PostgreSQL backup restore
summary: "Start a private PostgreSQL 16 instance, verify persistence, separate application roles, and follow the tested backup and restore lab."
lastmod: 2026-10-31
---

PostgreSQL needs persistent storage and a recovery procedure before applications depend on it. A shared instance can save resources, but also couples maintenance, extensions, and failures across applications. Follow each application's supported database version and extension requirements; a shared server is not always suitable.

## Verification status

| Area | Evidence and limits |
|---|---|
| Source review | Compose and SQL examples reviewed against the references below on October 31, 2026. |
| Runtime | This deployment example has not been executed in this audit. The separate backup lab has linked CI recovery evidence. |
| Scope | A new, isolated PostgreSQL 16 instance. No claim of production certification, HA, pgvector installation, or universal tuning. |

## Start a separate instance

Use Bash, OpenSSL, Docker Engine, and a Compose plugin supporting `up --wait`. These commands create a new private project directory. Keep its path and Compose project name stable for subsequent runs.

```bash
postgres_dir=$(mktemp -d -t postgres-deployment.XXXXXX)
cd "$postgres_dir" || exit 1
umask 077
openssl rand -base64 32 > postgres-password
cat > compose.yaml <<'EOF'
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: labadmin
      POSTGRES_DB: appdb
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres-password
    secrets:
      - postgres-password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "labadmin", "-d", "appdb"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 10s
secrets:
  postgres-password:
    file: ./postgres-password
volumes:
  pgdata:
EOF
docker compose config --quiet
docker compose up --wait --wait-timeout 120
docker compose exec -T postgres psql -X -U labadmin -d appdb -v ON_ERROR_STOP=1 \
  -c 'SELECT current_database(), version();'
```

There is no published database port. Host administration uses `docker compose exec`; applications in another project need an explicitly planned private network. Do not publish port 5432 just to solve a missing network attachment.

The official image initializes its bootstrap user as a superuser on an **empty** data volume. Its local socket authentication permits the administrative command above. Changing the password file later does not rotate an initialized database password. See the [official image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md).

## Give applications their own roles

Do not give an application the bootstrap superuser credential. Open an interactive administrative session:

```bash
docker compose exec postgres psql -X -U labadmin -d appdb -v ON_ERROR_STOP=1
```

For one new example application, run the following **inside psql**. `\password` prompts for its password without embedding it in shell history:

```sql
CREATE ROLE example_app LOGIN;
\password example_app
CREATE DATABASE example_app OWNER example_app;
```

Database ownership alone does not establish full tenant isolation. Review `CONNECT`, schema privileges, role memberships, and `pg_hba.conf`, and test access that should be denied. Use separate instances when extension, version, or trust boundaries require them.

## Extensions and tuning

The stock `postgres:16-alpine` image does **not** provide pgvector's extension files. An initialization SQL statement cannot install missing extension binaries. Follow the [pgvector project's installation instructions](https://github.com/pgvector/pgvector) or the application's supported database image. The quoted extension identifier `"uuid-ossp"` is distinct from an unquoted identifier containing a hyphen.

```bash
docker compose exec -T postgres psql -X -U labadmin -d appdb -v ON_ERROR_STOP=1 \
  -c "SELECT name, default_version, installed_version FROM pg_available_extensions ORDER BY name;"
```

Size memory settings for the database's actual memory limit and concurrent workload. `work_mem` can be used by multiple operations per query and multiple sessions. Do not copy a host-RAM percentage into every database container. Measure before changing planner costs or WAL settings. Physical streaming replication normally needs `wal_level=replica` or higher; selecting `logical` is not a complete replica setup. Replication requires authentication, a base backup, standby configuration, WAL retention monitoring, and a tested failover procedure. It does not replace backups.

## Back up and recover before upgrading

Use the [atomic dump, systemd scheduling, and isolated database recovery lab](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/). It records actual recovery evidence and includes a separately encrypted Restic copy exercise.

A `pg_dump` archive covers one database. Cluster roles and tablespaces require separate planning with [pg_dumpall](https://www.postgresql.org/docs/16/app-pg-dumpall.html). Restore into a **new** volume and verify application data before any cutover. Keep the original instance and backup materials intact; deleting the original volume is not a recovery prerequisite.

For minor updates, review release notes, back up, test the selected image, and recreate in a maintenance window. Major upgrades require an appropriate dump/restore or `pg_upgrade` plan and compatible extensions; changing the image's major tag against an old data directory is not that plan. See [PostgreSQL upgrades](https://www.postgresql.org/docs/16/upgrading.html).

To stop this example while retaining its data:

```bash
docker compose down
```

Before moving the project, record its resolved name, volume identity, image digest, credentials, and recovery instructions. A volume name is a reference to data on a particular Docker daemon; copying that name to another machine does not copy the database.
