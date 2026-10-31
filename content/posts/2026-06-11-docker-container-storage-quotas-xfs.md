---
title: "Docker Storage Quotas — Check the Backend and the Data Path First"
description: "Distinguish classic overlay2 writable-layer limits from application volume quotas and plan XFS changes without deleting Docker data."
date: 2026-06-11T17:00:00-04:00
tags:
  - docker
  - homelab
  - storage
  - linux
  - devops
keywords:
  - Docker storage quotas
  - XFS project quotas
  - overlay2 containerd backend
summary: "Distinguish classic overlay2 writable-layer limits from application volume quotas and plan XFS changes without deleting Docker data."
lastmod: 2026-10-31
---

A container can consume space through its writable layer, persistent volumes, bind mounts, and logs. Limiting one path does not limit the others. Start by identifying the active Docker backend and the filesystem holding each kind of data.

## Verification status

| Area | Evidence and limits |
|---|---|
| Source review | Docker storage and per-container storage-option references reviewed on October 31, 2026. |
| Runtime | No filesystem creation, migration, quota assignment, or disk-filling test was executed. |
| Scope | Backend and capacity planning; changes require a disposable storage lab and a recovery plan. |

## Inspect the actual host

```bash
docker info
docker system df -v
findmnt -T /var/lib/docker -o TARGET,SOURCE,FSTYPE,OPTIONS
df -hT /var/lib/docker
df -i /var/lib/docker
```

If `docker info` reports a different Docker root, inspect that path instead. `findmnt -T` also identifies a filesystem inherited from a parent mount; grepping for a dedicated `/var/lib/docker` mount can miss it.

Fresh Docker Engine 29 installations use the containerd image store by default; upgraded systems may retain classic `overlay2`. These backends are different. This article's classic `overlay2.size` discussion does not establish support for a containerd snapshotter. See [Docker's containerd storage guide](https://docs.docker.com/engine/storage/containerd/).

## What each limit covers

| Data path | Limit to investigate |
|---|---|
| Classic overlay2 writable layer | Supported storage-driver size option on a compatible XFS filesystem with project quotas. |
| Bind-mounted application directory | Filesystem project quota or a separately sized filesystem on that directory's actual backing store. |
| Named volume | Identify its driver and backing path; a writable-layer limit does not cap volume content. |
| Container logs | Logging-driver rotation, log delivery, and host capacity monitoring. |

The classic overlay2 quota applies to the writable upper layer, not the sum of all shared lower image layers. Lower layers still occupy host space. Docker documents a **per-container** `--storage-opt size=...` option for supported drivers; the earlier claim that it was unavailable was incorrect. Compose also exposes service `storage_opt`; verify support against the installed backend.

See [Docker run storage options](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container---storage-opt) and the [classic overlay2 prerequisites](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/). An XFS `ftype=1` capability and project-quota mount options are distinct checks. Filesystem creation alone does not enable mounted quota enforcement.

## Plan storage changes before applying them

Do not format a guessed `/dev/sdb1`, overwrite `daemon.json`, or delete an old Docker directory as a preparation step. First inventory the real Docker/containerd paths, mounts, daemon configuration, named volumes, image digests, and application recovery materials.

Prepare a separately identified spare device in a disposable environment. Check existing XFS project IDs and names before allocating any new ones; `/etc/projects` and `/etc/projid` are shared host configuration. A directory can only be managed as part of the intended project's filesystem hierarchy. Verify accounting and enforcement with the installed `xfs_quota` documentation before starting writers.

A production storage migration needs stopped writers and an explicit plan for Docker service/socket activation, metadata-preserving copying, mount persistence, application verification, and rollback. Keep the original data until restore and rollback have been tested. Changing storage drivers can make existing images and containers inaccessible even though their files remain on disk.

In a quota lab, start with a small, bounded workload and monitor free space outside the container. A missing quota can turn a multi-gigabyte `dd` test into a host outage. Confirm the observed failure is the intended quota, not exhaustion elsewhere. This guide provides no command that deliberately fills a production filesystem.

## Backups and monitoring

A quota prevents one kind of growth; it does not supply a backup. Use the [database recovery lab](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/) for consistent PostgreSQL dumps and the [Restic recovery guide](/posts/2026-05-19-restic-docker-backup-strategy/) for encrypted archive recovery.

Monitor bytes, inodes, quota usage, database write errors, log growth, and successful backup age. A quota can protect host headroom while still making the limited application fail writes; test that application's response before relying on the limit.
