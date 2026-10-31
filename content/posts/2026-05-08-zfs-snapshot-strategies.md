---
title: "ZFS on Proxmox — Snapshots, Replication, and Recovery Boundaries"
description: "Distinguish ZFS filesystem snapshots from VM backups, recover a file through a disposable clone, and plan retention and replication without changing live guest disks."
date: 2026-05-08T12:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [proxmox, zfs, storage, backup, homelab]
categories: [homelab, storage]
aliases:
  - /posts/2026-06-15-proxmox-zfs-snapshot-replication-backup/
---

ZFS snapshots preserve dataset state, but they are only one part of a recovery plan. Pool failure, lost guest configuration, and inconsistent application data need separate protection.

This guide uses a small filesystem lab on an existing test pool. It does not create pools, repartition disks, or roll back running guests.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official OpenZFS and Sanoid references reviewed on October 31, 2026. |
| Static checks | Bash examples syntax checked. |
| Runtime | No ZFS pool, dataset, snapshot, clone, replication, or recovery operation executed for this revision. |
| Scope | Proposed filesystem lab, not a captured host layout or measured performance result. |

## 1. Identify the storage objects

Proxmox offers several installation and storage choices; ZFS is not a universal default. Inspect the actual host before changing properties:

```bash
zpool status
zfs list -o name,type,used,available,mountpoint
zfs list -t volume -o name,volsize,volblocksize
pvesm status
```

A filesystem dataset holds files. A zvol exposes block storage, commonly used for guest disks. Filesystem recordsize and zvol volblocksize are different settings; changing a parent filesystem's recordsize does not retune existing guest zvol blocks.

Do not apply blanket 8K or 64K values to every workload. Compression benefits, block-size choices, redundancy, and capacity needs require measurements and a recovery plan. A single-disk pool has no disk redundancy. Separate datasets still share their pool's failure boundary.

See the [OpenZFS property reference](https://openzfs.github.io/openzfs-docs/man/master/7/zfsprops.7.html). Preserve properties required by applications; for example, do not disable access-time updates indiscriminately on storage used by PBS garbage collection.

## 2. Test a snapshot on a new filesystem

Run as root in Bash on a host with an existing **test pool** and free space. Choose a pool you are authorized to modify. The script creates only uniquely named lab datasets and a mount directory; it stops on error and leaves resources for inspection.

```bash
(
set -euo pipefail
read -r -p 'Existing test pool name: ' lab_pool
test -n "$lab_pool"
zpool list "$lab_pool"

lab_root=$(mktemp -d /mnt/gntech-zfs-lab.XXXXXX)
lab_dataset="$lab_pool/$(basename "$lab_root")"
lab_clone="$lab_dataset-recovered"

printf 'Dataset: %s\nClone: %s\nMount directory: %s\n' \
  "$lab_dataset" "$lab_clone" "$lab_root"

zfs create -o mountpoint="$lab_root/source" -o canmount=on \
  -o readonly=off -o quota=64M "$lab_dataset"

printf 'marker-before\n' > "$lab_root/source/check.txt"
zfs snapshot "$lab_dataset@before-change"
printf 'marker-after\n' > "$lab_root/source/check.txt"

zfs clone -o mountpoint="$lab_root/recovered" -o canmount=on \
  -o readonly=on "$lab_dataset@before-change" "$lab_clone"

grep -qx marker-after "$lab_root/source/check.txt"
grep -qx marker-before "$lab_root/recovered/check.txt"
zfs list -t filesystem,snapshot -r "$lab_dataset"
zfs list -o name,origin,mountpoint "$lab_clone"
printf 'Marker checks passed; inspect %s\n' "$lab_root"
)
```

Expected evidence: the live file contains the later marker and the recovered clone contains the earlier one. A successful script exit verifies those assertions for your run, not guest or database recovery.

Snapshots share storage with their source. Clones initially share blocks with their origin snapshot and retain a dependency on it. This example sets the recovery clone read-only to prevent accidental edits during inspection.

Review [snapshot semantics](https://openzfs.github.io/openzfs-docs/man/master/8/zfs-snapshot.8.html) and [clones](https://openzfs.github.io/openzfs-docs/man/master/8/zfs-clone.8.html) against the installed version.

## 3. Keep guest recovery separate

| Mechanism | What it preserves | What still needs verification |
|---|---|---|
| Native filesystem snapshot | Dataset state at a point in time | Application consistency and independent copies |
| Native guest-disk snapshot | Storage-level disk state | Guest configuration, related disks, and application consistency |
| PVE-managed guest snapshot | Guest snapshot state managed through PVE | Storage support, consistency, and recovery procedure |
| PVE backup to PBS or archive storage | Selected guest configuration and backup data | Included disks/mounts and an isolated restore |
| Replicated dataset | Selected data transferred to another location | Destination completeness and recovery access |

A raw snapshot of active database or VM storage is not automatically application-consistent. Coordinate writers or use supported application/guest backup procedures.

Sanoid-created snapshots are not automatically registered as PVE snapshot names. Do not feed their names into qm rollback or modify live guest disks underneath PVE. In-place rollback changes existing data; it is a different operation from copying a file out of a recovery clone.

For guest recovery, follow the [PBS setup and isolated restore guide](/posts/2026-05-08-proxmox-backup-server-setup/) and test a new guest ID on an isolated network.

## 4. Automate retention only after inspecting scope

[Sanoid](https://github.com/jimsalterjrs/sanoid) manages snapshot policy; Syncoid supports ZFS replication. Start with one disposable dataset before selecting production parents recursively.

Keep custom Sanoid policy in its documented configuration file using the supported template syntax. Review the installed package's existing timer or cron job before adding another scheduler. Avoid overlapping parent/child policies unless intentional.

Choose retention from change rate, capacity, and recovery goals. Inspect actual snapshots and pruning candidates before enabling deletion. Do not replace policy management with a broad grep-and-destroy loop.

Snapshot space accounting includes shared blocks and clone dependencies. Summing individual snapshot USED values is not a general measure of all retained snapshot space. Inspect dataset snapshot accounting and pool free space as well as individual snapshots.

## 5. Treat replication as another recovery workflow

Before configuring Syncoid or manual send/receive, identify the exact source datasets, destination pool, access permissions, common snapshot history, and what may be changed or removed on the destination.

A successful transfer is only one gate. Inspect destination datasets and snapshots, recover a known file there, and test how to access that copy if the original host is unavailable. Recursive replication does not by itself mean “copy the last seven days.”

Keep destination retention and credentials deliberate. Do not use destructive receive/rollback options to resolve a mismatch without understanding the data that would be lost. A removable pool also needs a documented import, completed-transfer, and export procedure using the correct device identity.

For PVE-managed guest replication, use the installed release's supported workflow rather than treating a standalone dataset copy as a complete replacement for guest backup and configuration recovery.

### Choose the replication mechanism

| Mechanism | Scope | Check before scheduling |
|---|---|---|
| PVE storage replication | Guest volumes managed by the PVE replication framework | Supported storage, target node, matching storage ID, capacity, and replication logs |
| Syncoid | Selected standalone ZFS datasets and snapshots | Source/target scope, SSH permissions, common history, and destination recovery |

For PVE-managed guests, consult the [storage replication reference](https://github.com/proxmox/pve-docs/blob/master/pvesr.adoc). Inspect cluster health and quorum before a recovery exercise. Replication is asynchronous, so changes after the last successful sync may be lost if a node fails. It is not an independently retained backup history.

For Syncoid, verify options against the installed version. In particular, --no-sync-snap uses existing snapshots rather than creating a new synchronization snapshot. Do not assume a bandwidth option or retention policy from another version applies unchanged.

## 6. Review and clean up only the lab resources

Record the exact dataset, clone, snapshot, and mount directory printed by the lab. Inspect their contents and dependencies before deciding to remove them.

The clone depends on the origin snapshot, so cleanup order matters. Delete only the identified disposable clone, then its snapshot, then its source dataset after verifying nothing useful was added. Keep cleanup separate from the recovery test; no recursive destroy or guessed device command is provided here.

If the test fails halfway through, inspect the printed names and current mount state before retrying. Do not rerun production storage commands just to obtain a clean lab result.

## Continue reading

- [Backup strategy](/posts/2026-05-23-proxmox-backup-strategies/) — Define independent copies and recovery targets.
- [Restic recovery lab](/posts/2026-05-19-restic-docker-backup-strategy/) — Verify encrypted file recovery.
- [PostgreSQL dumps](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/) — Prepare application-consistent database backups.
