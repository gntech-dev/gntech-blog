---
title: "Docker PostgreSQL Backups — Atomic Dumps and an Isolated Restore Test"
description: "Create PostgreSQL custom-format dumps with a host-side script, reject partial files, and verify recovery in a separate disposable instance before scheduling."
date: 2026-06-01T12:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [docker, linux, homelab, database]
keywords: [Docker PostgreSQL backup, pg_dump custom format, pg_restore test, database backup automation]
summary: "A focused PostgreSQL lab with atomic dump publication, error propagation, and a separate restore destination."
---

A database backup needs a consistent dump, a usable recovery format, and a restore test. This guide uses PostgreSQL custom-format archives and a separate PostgreSQL instance to check recovered content.

The old combined PostgreSQL/MySQL script is replaced with one explicit PostgreSQL workflow. MySQL and MariaDB need their own engine-specific procedures.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official PostgreSQL and Docker references reviewed on October 31, 2026. |
| Static checks | Bash syntax and embedded Compose structure checked. |
| Runtime | [Recovery lab run 41244956545](https://github.com/gntech-dev/gntech-blog/actions/runs/41244956545) passed on October 31, 2026: dump, isolated restore, marker assertion, repeated-restore failure, and stopped-source backup failure. That run covered recovery only. |
| Scheduler | [Scheduler lab run 41245987064](https://github.com/gntech-dev/gntech-blog/actions/runs/41245987064) passed on October 31, 2026: manual service execution, accelerated timer activation, lock-contention failure, stopped-source failure, service result/exit status, and journal error details. Tested with systemd 255.4-1ubuntu8.18. The daily calendar was parsed; CI used a two-second timer override. |
| Tested versions | GitHub-hosted Ubuntu 24.04.5 amd64; Docker 28.0.4; Compose 2.38.2; PostgreSQL 16.15. Image digest: `sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`. |
| Scope | Disposable PostgreSQL 16 lab, not a production deployment or point-in-time recovery solution. |

The repository includes an automated replay of this lab in `tools/check-postgres-lab.py`. It runs the article's Bash examples on a disposable Docker host, checks recovery, rejects a repeated restore, and confirms a failed dump preserves existing archives. Check the **PostgreSQL recovery lab** Actions run for runtime evidence; merely adding the test does not establish a passing result. It also tests the generated systemd service and an accelerated timer on a disposable runner. Off-site recovery, external alert delivery, missed-run monitoring, downtime catch-up, and production data remain outside this test.

## 1. Prepare a separate lab

Use Bash, OpenSSL, Docker Engine, the Compose plugin, and host flock. This project publishes no database ports. Its two services have separate data volumes; only the test service is a restore target.

```bash
db_lab_dir=$(mktemp -d -t postgres-backup-lab.XXXXXX)
cd "$db_lab_dir" || exit 1
umask 077
mkdir backups
openssl rand -base64 32 > db-password

cat > compose.yaml <<'EOF'
services:
  source:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: appdb
      POSTGRES_USER: lab
      POSTGRES_PASSWORD_FILE: /run/secrets/db-password
    secrets:
      - db-password
    volumes:
      - source_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "lab", "-d", "appdb"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 10s

  restore_test:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: restoredb
      POSTGRES_USER: lab
      POSTGRES_PASSWORD_FILE: /run/secrets/db-password
    secrets:
      - db-password
    volumes:
      - restore_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "lab", "-d", "restoredb"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 10s

secrets:
  db-password:
    file: ./db-password

volumes:
  source_data:
  restore_data:
EOF

docker compose config --quiet
docker compose up --wait --wait-timeout 120
```

Use a Compose version supporting the wait flags and inspect logs if startup fails. Record image digests: the version-series tag can change.

The official image initializes the lab user on an empty volume. These commands use its local socket from inside the container. Production remote authentication and backup privileges need separate review. See the [official image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md).

## 2. Create a recognizable source record

```bash
docker compose exec -T source psql -X -U lab -d appdb -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE backup_marker (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO backup_marker VALUES (1, 'gntech-restore-check');
SQL
```

This intentionally creates a new table in the disposable source. If you rerun it against the same lab, the existing-table error is expected; inspect the lab state rather than suppressing the error.

## 3. Write an atomic backup script

```bash
cat > backup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")"

# One instance of this workflow at a time.
exec 9>backup.lock
flock -n 9 || { echo "Backup already running" >&2; exit 1; }

test -d backups
partial=$(mktemp "$PWD/backups/appdb-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX.partial")
trap 'rm -f -- "$partial"' EXIT

docker compose exec -T source pg_dump -U lab -d appdb --format=custom > "$partial"
test -s "$partial"

# A readable archive index is useful but is not a full restore test.
docker compose exec -T source pg_restore --list < "$partial" > /dev/null

final="${partial%.partial}.dump"
mv -- "$partial" "$final"
printf 'Published dump: %s\n' "$final"
SCRIPT

chmod 700 backup.sh
./backup.sh
```

A dump or archive-list failure exits nonzero and leaves no published .dump file. The temporary file and final file share a filesystem, allowing publication by rename. Existing successful archives are retained.

The custom archive is already compressed by default and is read by pg_restore; it is not a gzip-compressed SQL script. Plain SQL requires a different restore command. See [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html).

The source database remains available during a logical dump. The dump covers one database, not cluster roles, tablespaces, application attachments, or a coordinated snapshot of multiple databases. Plan those separately.

## 4. Restore a chosen archive into the empty test instance

Run this once against the fresh restore_test database. Select the exact .dump filename printed by backup.sh:

```bash
read -r -p 'Archive path under backups/: ' archive
test -s "$archive" &&
  docker compose exec -T restore_test pg_restore \
    --exit-on-error --single-transaction --no-owner --no-privileges \
    -U lab -d restoredb < "$archive"
```

Stop if the restore fails. Repeating it into a populated database is not an independent recovery test. Do not add clean/drop options or redirect it at source to bypass that problem.

Verify the marker using an assertion that fails on missing or incorrect data:

```bash
docker compose exec -T restore_test psql -X -U lab -d restoredb -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF (SELECT count(*) FROM backup_marker
      WHERE id = 1 AND value = 'gntech-restore-check') <> 1 THEN
    RAISE EXCEPTION 'Restore marker verification failed';
  END IF;
END
$$;
SQL
```

A successful marker test establishes this lab's expected row, not an entire application's correctness. Add schema, data, permissions, extension, and application checks for production. See [pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).

For plain SQL imports, use psql with ON_ERROR_STOP so SQL errors propagate. Do not hide stderr or treat “some tables exist” as a passed restore.

## 5. Schedule after the manual recovery test

Move the validated project to a stable host path before scheduling. Test backup.sh as the scheduler's actual user, using the installed Docker executable and Compose plugin. Confirm its PATH, permissions, mount state, logs, and time zone.

The script already takes a nonblocking lock. Use a host timer or cron job to invoke it once per scheduled run; do not wrap it in a tight retry loop or rely on installing client tools every time a container starts.

Connect failure and missed-run alerts to the actual command result. Send success only after every required stage succeeds, including any required off-site transfer. A notification transport failure should be visible and should not turn a failed dump into success.

Keep retention separate until recovery is proven. Preview candidate archives, verify off-site availability and required recovery history, and scope deletion to this workflow. Do not delete older backups before confirming the new required copy succeeded.

### Install a systemd service and daily timer

Run this section from a root Bash shell on a systemd host, inside the validated project at its stable path. Keep the same Compose project name when moving an existing deployment; changing it can select different volumes. The example assumes a local, root-managed Docker Engine and Python 3 for reading Compose's resolved project name.

The path check keeps generated unit values simple. Use a stable path without spaces, percent signs, or shell metacharacters. Review any existing units with these names before replacing them.

```bash
backup_project_dir=$(pwd -P)
backup_project_name=$(docker compose config --format json |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
[[ "$backup_project_dir" =~ ^/[a-zA-Z0-9_./-]+$ ]] || exit 1
[[ "$backup_project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
test -x "$backup_project_dir/backup.sh" || exit 1

cat > /etc/systemd/system/gntech-postgres-backup.service <<EOF
[Unit]
Description=GNTECH PostgreSQL logical backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=$backup_project_dir
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=COMPOSE_PROJECT_NAME=$backup_project_name
ExecStart=$backup_project_dir/backup.sh
UMask=0077
TimeoutStartSec=30min
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/gntech-postgres-backup.timer <<'EOF'
[Unit]
Description=Daily GNTECH PostgreSQL backup

[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=15min
Persistent=true
Unit=gntech-postgres-backup.service

[Install]
WantedBy=timers.target
EOF

systemd-analyze verify /etc/systemd/system/gntech-postgres-backup.service \
  /etc/systemd/system/gntech-postgres-backup.timer
systemctl daemon-reload
```

The service uses the resolved Compose project explicitly and runs without your interactive shell environment. Root access to Docker is intentional here; these units require review before adapting to a rootless engine or a remote Docker context. All database commands must still target the intended project.

Test the service before enabling the timer:

```bash
systemctl start gntech-postgres-backup.service
systemctl show gntech-postgres-backup.service \
  -p Result -p ExecMainStatus -p ActiveState
journalctl -u gntech-postgres-backup.service --no-pager -n 40
systemctl enable --now gntech-postgres-backup.timer
systemctl list-timers --all gntech-postgres-backup.timer
```

Require `Result=success`, `ExecMainStatus=0`, and a new published archive. A completed oneshot normally becomes inactive; that alone is not a failure. This timer runs at 02:00 in the **host's time zone**, plus up to 15 minutes of random delay. Check `timedatectl`. `Persistent=true` can trigger a catch-up after downtime; it does not replay every missed daily backup.

A nonzero script exit, including lock contention or a stopped source, marks the service failed and records stderr in the journal. Inspect `Result`, `ExecMainStatus`, and the journal before retrying. The timer being active proves only that it is waiting, not that backups are succeeding.

Use these signals in your monitoring system and separately alert on overdue successful archives. This example sends no email or webhook and cannot detect a powered-off host by itself. Avoid `RemainAfterExit=yes`: leaving this oneshot active prevents later timer activations from running it again. See [systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).

To stop this schedule while retaining the units and backups:

```bash
systemctl disable --now gntech-postgres-backup.timer
```

## 6. Add encrypted off-site recovery

Database dumps here are plaintext data in a compressed archive. File permissions restrict local access but are not encryption.

Use the [Restic backup and restore guide](/posts/2026-05-19-restic-docker-backup-strategy/) to protect completed archives. Select only published .dump files, excluding .partial files. Validate the remote repository and restore an archive from that remote copy into another isolated instance.

Keep repository credentials, database versions, extension requirements, application secrets, and recovery instructions outside the original host. Measure recovery time; neither a successful upload nor a nonempty archive proves recoverability.

Logical dumps do not provide arbitrary point-in-time recovery. Review [PostgreSQL backup guidance](https://www.postgresql.org/docs/16/backup-dump.html) and WAL-based recovery requirements when the recovery target demands more than periodic snapshots.

## Stop the lab

```bash
docker compose down
```

This retains the lab volumes and archives for inspection. Removing the disposable volumes is a separate decision after checking recovery evidence. No production database should be attached to this project.

## Continue reading

- [Compose health checks](/posts/2026-05-14-docker-compose-healthchecks/) — Separate startup readiness from job success.
- [Backup strategy](/posts/2026-05-23-proxmox-backup-strategies/) — Define recovery targets and independent copies.
