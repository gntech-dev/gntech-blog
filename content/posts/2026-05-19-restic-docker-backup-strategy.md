---
title: "Restic Docker Backups — Verify a Restore Before Automation"
description: "Create an encrypted Restic repository with Docker Compose, restore a test file into a host-visible directory, and plan consistent Docker application backups."
date: 2026-05-19T17:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [docker, backup, homelab, automation, storage]
keywords: [restic Docker backup, restic restore test, encrypted backups, Docker application backup]
summary: "Prove repository access and file recovery before adding databases, off-site copies, retention, and scheduling."
---

A successful backup command does not prove an application can be recovered. Start with one file, an explicit repository path, and a restore directory you can inspect on the host. Then add application consistency and off-site recovery.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official Restic references below reviewed on October 31, 2026. |
| Static checks | Bash syntax, embedded Compose YAML, and path mappings checked. |
| Runtime | Docker and Restic unavailable in the review environment; no image pull, repository initialization, backup, or restore executed. |
| Scope | Disposable local file lab. Production databases, off-site recovery and scheduling require separate validation. |

## 1. Separate source consistency from encryption

Restic encrypts repository data and deduplicates snapshots. It does not make a live database's changing files application-consistent.

| Source | Preparation before backup |
|---|---|
| Ordinary files | Ensure the selected files represent the state you intend to recover. |
| PostgreSQL or MariaDB | Use a supported database dump or physical backup procedure. |
| Application with database and attachments | Coordinate both parts according to its recovery documentation. |
| Stopped container data | Confirm all writers are stopped and preserve required metadata and configuration. |

A read-only mount prevents that container from writing to the source; it does not freeze other writers. Dump files must actually be included in the selected backup path. Any failed dump must fail the job instead of being logged as a warning followed by a success notification.

## 2. Create a disposable Compose project

Use Bash, Docker Engine, the Compose plugin, and OpenSSL. Select a reviewed official Restic image tag or digest compatible with your repository. The service uses the image's Restic entrypoint; commands after the service name are Restic arguments.

```bash
restic_lab_dir=$(mktemp -d -t restic-file-lab.XXXXXX)
cd "$restic_lab_dir" || exit 1
umask 077
mkdir source repository restored
printf 'restic-restore-check\n' > source/check.txt
openssl rand -base64 32 > restic-password

read -r -p 'Reviewed restic/restic image tag or digest: ' RESTIC_IMAGE
export RESTIC_IMAGE

cat > compose.yaml <<'EOF'
services:
  restic:
    image: ${RESTIC_IMAGE:?Set a reviewed restic/restic image}
    environment:
      RESTIC_REPOSITORY: /repository
      RESTIC_PASSWORD_FILE: /run/secrets/restic-password
    volumes:
      - ./source:/source:ro
      - ./repository:/repository
      - ./restored:/restore
    secrets:
      - restic-password

secrets:
  restic-password:
    file: ./restic-password
EOF

docker compose config --quiet
docker compose run --rm restic version
```

This is a one-shot service, not a sleeping container with a background cron daemon. It needs no Docker socket. The password file is created in a new private directory; do not regenerate the password when reconnecting to an existing repository.

Keep production repository credentials and recovery instructions somewhere accessible if the Docker host is lost. See [repository preparation](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html).

## 3. Initialize once and back up

Run initialization only for this new empty repository. For an existing repository, use its saved password and inspect snapshots instead.

```bash
docker compose run --rm restic init
docker compose run --rm restic backup /source --host restic-file-lab --tag demo
docker compose run --rm restic snapshots
docker compose run --rm restic check
```

Check each command's exit status before continuing. A nonzero backup result requires investigation even if some snapshot data was saved.

The fixed host label avoids grouping every new one-shot container under a different generated hostname. Record the snapshot ID returned by backup. See [backing up](https://restic.readthedocs.io/en/stable/040_backup.html).

## 4. Restore to a host-visible destination

Select the exact demo snapshot ID from the listing:

```bash
read -r -p 'Demo snapshot ID to restore: ' snapshot_id
test -n "$snapshot_id" &&
  docker compose run --rm restic restore "$snapshot_id" --target /restore
cmp source/check.txt restored/source/check.txt
```

Expected result to verify: the restored marker matches the original and cmp exits zero. The snapshot's absolute source path is recreated under the target, so container path `/restore/source/check.txt` corresponds to host path `./restored/source/check.txt`.

Restoring into a container's unmounted /tmp directory would not put files in the host's /tmp directory. Keep mappings explicit. Never test by copying a restore directly over a live database volume.

Use [Restic restore guidance](https://restic.readthedocs.io/en/stable/050_restore.html) for selecting files. The restore --path filter selects snapshots; it does not mean “restore only this directory.” Use documented include/exclude or subtree options when needed.

## 5. Review retention before deleting anything

For the demo group, preview a policy:

```bash
docker compose run --rm restic forget --dry-run \
  --host restic-file-lab --tag demo \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 3
```

Inspect the keep/remove lists and grouping behavior before applying a policy. Forget removes snapshot references; prune reclaims eligible repository data. Do not attach automatic pruning to your first backup exercise.

Plan maintenance windows and verify the repository afterwards. A partial data check does not read every stored pack, and a repository check is not an application restore test. See [retention](https://restic.readthedocs.io/en/stable/060_forget.html).

## 6. Add an independent off-site repository

A repository beside the source on the same host is useful for this exercise, but cannot survive loss of that host.

Choose a supported remote backend, configure its credentials, and initialize a separate repository once. Use Restic's supported copy workflow to transfer selected snapshots between repositories, or run a separate backup against the same prepared source. One backup invocation targets one repository.

With copy, explicitly configure destination access and source repository/password options. Do not assume local and remote passwords are interchangeable. Verify remote snapshots, check the remote repository, and restore from it using only the off-site credentials and recovery materials.

See [working with repositories](https://restic.readthedocs.io/en/stable/045_working_with_repos.html). Retention is independent for each repository. Do not substitute an uncoordinated file mirror of a changing repository for a tested recovery workflow.

## 7. Automate only the verified workflow

Move the validated project to a stable operational path and adapt the source mounts to prepared application data. Before scheduling, require:

- Database dumps written to a mounted staging directory, with errors propagated and partial files excluded.
- A mount check for external backup storage so a missing mount cannot silently redirect writes to the root filesystem.
- A stable host label, explicit source selection, overlap prevention, and retained logs.
- Success notification only after all required backup stages succeed, plus alerts for failed or missing runs.
- Separate retention and integrity checks, and recurring isolated application restore tests.

Test the scheduled command under its actual user and environment. Do not source an arbitrary Compose .env file as shell code or assume a container image includes Bash, Docker CLI, curl, or a scheduler.

Keep the demo files until you have reviewed the restore result. No services remain running after these one-shot commands. Any repository deletion must be a separate, deliberate cleanup decision.

## Continue reading

- [Proxmox backup strategy](/posts/2026-05-23-proxmox-backup-strategies/) — Plan independent copies and recovery targets.
- [Compose health checks](/posts/2026-05-14-docker-compose-healthchecks/) — Understand why a running process is not backup-success evidence.
