---
title: "ZFS on Proxmox — Pool Layout, Snapshots, and Backup Strategies"
description: "Practical ZFS configuration for Proxmox VE — pool design decisions, automated snapshot rotation with sanoid, ZFS send/receive replication, and recovery patterns from an existing homelab."
date: 2026-05-08T12:00:00-04:00
tags:
  - proxmox
  - zfs
  - storage
  - backup
  - homelab
categories:
  - homelab
  - storage
---

ZFS is the default filesystem on Proxmox VE for good reason — checksumming, snapshots, compression, and built-in replication. But "default" doesn't mean one-size-fits-all. Pool layout, recordsize, snapshot cadence, and backup strategy all depend on your workload.

This post covers the ZFS setup on my Proxmox host (SRV1), the snapshot pipeline, and how ZFS send/receive + sanoid handle retention and offsite recovery.

---

## Pool Layout

```
System: HP ProDesk 600 G4 DM (i5-8500T, 32 GB RAM)
Disks: 1× NVMe (OS + VMs), 1× SATA SSD (bulk storage)
```

### Boot/OS Pool — rpool

Standard Proxmox installation creates `rpool` on the boot disk. No RAID, no redundancy — just a single NVMe:

```bash
# Typical layout from Proxmox installer
# Device: /dev/nvme0n1
# Pool: rpool
# Datasets: rpool/ROOT, rpool/data, rpool/swap

zpool status rpool
```

```
  pool: rpool
 state: ONLINE
config:

        NAME                                  STATE     READ WRITE CKSUM
        rpool                                 ONLINE       0     0     0
          nvme0n1p3                           ONLINE       0     0     0
```

Proxmox puts VMs/LXCs in `rpool/data` by default. This works, but separating bulk storage from OS avoids filling the root dataset.

### Bulk Storage Pool — tank

Second disk, dedicated to VM disks, backups, and media:

```bash
zpool create -o ashift=12 \
    -O compression=lz4 \
    -O atime=off \
    -O xattr=sa \
    -O acltype=posixacl \
    tank /dev/sda
```

| Flag | Why |
|------|-----|
| `ashift=12` | 4K sector alignment for modern SSDs |
| `compression=lz4` | Near-zero CPU cost, huge space savings |
| `atime=off` | No access time updates — less write overhead |
| `xattr=sa` | Stores extended attributes in the inode — faster for SMB/NFS |
| `acltype=posixacl` | Required for Proxmox ACL support |

### Dataset Layout

```bash
tank
├── tank/vms           # VM disk images (raw/zvol)
├── tank/ct            # LXC container rootfs
├── tank/backup        # vzdump backup storage
├── tank/media         # General bulk storage
└── tank/sanoid        # Sanoid snapshot management dataset
```

Created with:

```bash
zfs create tank/vms
zfs create tank/ct
zfs create tank/backup
zfs create tank/media
zfs create tank/sanoid
```

For VM/LXC storage on `tank`, set recordsize and enable the ZFS block allocator:

```bash
zfs set recordsize=64K tank/vms
zfs set recordsize=8K  tank/ct
```

**Why different recordsizes:**
- **64K** for VM block storage — matches qemu/kvm virtio block alignment
- **8K** for LXC — better matches filesystem metadata, small writes, and container overlays
- **1M** (default) for media/bulk — sequential reads benefit from larger blocks

---

## Compression Savings

LZ4 is free on modern CPUs. Here's the real-world gain on my setup:

```bash
$ zfs get compressratio tank
```

| Dataset | Compressratio |
|---------|--------------|
| tank/vms | 1.28x |
| tank/ct  | 1.45x |
| tank/media | 1.12x |
| tank/backup | 2.10x |

VM disk images compress less (already compressed inside), but container rootfs and uncompressable media get decent ratios. vzdump backups compress the most since they're tar streams.

---

## Snapshot Strategy with Sanoid

[Sanoid](https://github.com/jimsalterjrs/sanoid) handles automated snapshot creation and pruning. It's a Perl script — no daemon, no database — just a config file and a cron job.

### Installation

```bash
# On Proxmox host
apt install sanoid
```

### Configuration — /etc/sanoid/sanoid.conf

```ini
[tank]
    use_template = production
    recursive = yes

[tank/vms]
    use_template = production
    recursive = yes

[tank/ct]
    use_template = production
    recursive = yes

[tank/backup]
    use_template = production
    recursive = yes

[tank/media]
    use_template = production
    recursive = yes

[tank/sanoid]
    use_template = production
    recursive = yes
```

### Template — /etc/sanoid/sanoid.defaults.conf

```ini
[production]
    frequently = 0
    hourly = 24
    daily = 30
    weekly = 8
    monthly = 6
    yearly = 0
    autosnap = yes
    autoprune = yes
```

This gives:

| Frequency | Retention | Window |
|-----------|-----------|--------|
| Hourly | 24 | ~1 day |
| Daily | 30 | ~1 month |
| Weekly | 8 | ~2 months |
| Monthly | 6 | ~6 months |

No "frequently" (sub-hourly) — unnecessary for a homelab and burns snapshot slots.

### Cron

Sanoid runs every minute, but only creates snapshots when due:

```bash
# /etc/cron.d/sanoid
* * * * * root /usr/bin/sanoid --cron
```

The `--cron` flag tells sanoid to take any scheduled snapshots and prune expired ones. It's idempotent — running multiple times doesn't duplicate snapshots.

---

## Snapshot Naming

Sanoid creates snapshots with predictable names:

```
tank/vms@autosnap_2026-05-08_00:00:00_hourly
tank/vms@autosnap_2026-05-07_00:00:00_daily
tank/vms@autosnap_2026-05-01_00:00:00_weekly
tank/vms@autosnap_2026-04-08_00:00:00_monthly
```

These are independent of Proxmox's internal snapshot mechanism — Proxmox snapshots (from the UI/API) create their own ZFS snapshots, but sanoid's are retention-guaranteed `autosnap` snapshots that survive VM deletion.

---

## ZFS Send/Receive — Offsite Replication

Sanoid pairs with [syncoid](https://github.com/jimsalterjrs/sanoid#syncoid) for ZFS send/receive replication. Syncoid is included with sanoid.

### On-Site Backup Target

A second Proxmox host (SRV2) serves as a backup target:

```bash
# SRV1 → SRV2 incremental replication
syncoid --recursive --compress=zstd-fast tank/backup root@srv2.local:tank/backup
```

`--recursive` replicates all child datasets. `--compress=zstd-fast` uses ZSTD compression on the wire — saves bandwidth without CPU overhead on modern hardware.

### Offsite (Cold Storage)

For offsite, a portable SSD gets brought in periodically:

```bash
# Mount external USB drive
zpool import -d /mnt/usb-backup

# Replicate last 7 days of hourly snapshots
syncoid --recursive tank/backup backup-pool/backup

# Export when done
zpool export backup-pool
```

The external pool is created once, then exported/imported on each replication cycle:

```bash
zpool create -o ashift=12 backup-pool /dev/sdb

# First run: full send
syncoid --recursive tank/backup backup-pool/backup

# Subsequent runs: incremental
syncoid --recursive tank/backup backup-pool/backup
```

Syncoid automatically picks the newest common snapshot and does an incremental send. First run is always full.

---

## Proxmox vzdump Integration

vzdump is Proxmox's built-in backup tool. When storage is ZFS, vzdump can use **ZFS snapshots** internally — zero-downtime backups without a guest agent:

```bash
# /etc/vzdump.conf
compress: zstd
mode: snapshot
storage: tank-backup
```

- `mode: snapshot` tells vzdump to snapshot the dataset, back up from the snapshot, then destroy it
- `compress: zstd` is faster than gzip with comparable ratios
- Backups land in `/var/lib/vz/dump/` by default, or your configured storage

### Backup Schedule

Via Proxmox GUI or API:

```bash
# Weekly full backup, daily incremental
pvesh create /cluster/backup \
    --storage tank-backup \
    --mode snapshot \
    --compress zstd \
    --vmid 100,101,102,200,201 \
    --schedule "0 3 * * 0" \   # Sunday 3 AM
    --all 0
```

I run a weekly full backup to `tank/backup`, and sanoid handles the finer-grained snapshot retention. This way:
- **vzdump** — application-consistent weekly backups (VM config + disk image)
- **Sanoid** — frequent filesystem snapshots for quick rollback

The two systems overlap but serve different recovery time objectives.

---

## Recovery Patterns

### Quick Rollback (Minutes)

VM starts behaving oddly after an update? Roll back to the last hourly snapshot:

```bash
# List snapshots for a VM dataset
zfs list -t snap -r tank/vms/vm-100-disk-0

# Roll back to the hourly snapshot before the update
zfs rollback tank/vms/vm-100-disk-0@autosnap_2026-05-08_03:00:00_hourly

# VM needs to be stopped first
qm stop 100
qm rollback 100 autosnap_2026-05-08_03:00:00_hourly
qm start 100
```

Proxmox's `qm rollback` handles the full stop/rollback/start sequence if you pass the snapshot name from the GUI.

### Full Restore from vzdump (Hours)

Disaster recovery from a vzdump backup:

```bash
# Restore a VM from backup file
qmrestore /var/lib/vz/dump/vzdump-qemu-100-2026_05_08-03_00_00.vma.zst 100 \
    --storage tank

# Or via Proxmox UI: Datacenter → Storage → tank-backup → select backup → Restore
```

### File-Level Recovery (Minutes)

For individual files, clone a snapshot and mount it:

```bash
# Clone the snapshot to a writable dataset
zfs clone tank/media@autosnap_2026-05-07_00:00:00_daily tank/media-restore

# The clone appears at /tank/media-restore — browse and copy what you need
cp /tank/media-restore/some-file /tank/media/

# Clean up the clone when done
zfs destroy tank/media-restore
```

Clones are instant and don't consume additional disk space (until you modify the data in the clone).

---

## Space Accounting — ZFS Comp

ZFS snapshots don't occupy full dataset space — they only track blocks that changed since the snapshot was taken. This means 30 daily snapshots of a 500 GB dataset might use only 10 GB if the data is mostly static.

Check actual snapshot space:

```bash
zfs list -t snap -o name,used,referenced -r tank/vms
```

```
NAME                                                   USED   REFER
tank/vms@autosnap_2026-05-07_00:00:00_hourly          1.65G     56G
tank/vms@autosnap_2026-05-07_01:00:00_hourly           732M     56G
tank/vms@autosnap_2026-05-07_02:00:00_hourly           280M     56G
```

The `USED` column shows only the unique blocks tracked by that snapshot. The `REFER` column is the total data size at snapshot time. Summing all `USED` values gives total snapshot overhead.

---

## What I Learned the Hard Way

### 1. Don't Keep Snapshots Forever

ZFS snapshots are cheap — until you have 6,000 of them. An over-retained dataset with years of hourly snapshots will degrade `zfs list` performance and make rollbacks slow. Set a max in sanoid and stick to it.

Sanoid's autoprune handles this, but if you manually take snapshots (e.g., before a risky operation), clean them up afterward:

```bash
# Remove all autosnap snapshots older than 90 days
zfs list -H -o name -t snap -r tank | grep autosnap | \
    while read snap; do
        age=$(zfs get -H -o value creation "$snap")
        if [ $(date -d "$age" +%s) -lt $(date -d "90 days ago" +%s) ]; then
            zfs destroy "$snap"
        fi
    done
```

### 2. Snapshot ZFS Datasets, Not Individual Files

I tried scripting file-level snapshots for specific dirs inside a dataset. Don't. ZFS datasets are the unit of snapshot. Create separate datasets for different retention needs.

### 3. Test Your Restores

A backup you never tested is a backup that will fail when you actually need it. At minimum:

```bash
# Monthly: verify vzdump archives are readable
for f in /var/lib/vz/dump/*.zst; do
    zstd -t "$f" || echo "CORRUPT: $f"
done

# Quarterly: do a full restore to a test VM
qmrestore /var/lib/vz/dump/vzdump-qemu-100-*.vma.zst 999
qm start 999
# Verify it boots, then destroy
qm stop 999
qm destroy 999
```

---

## Summary Config

```
Pool         │  rpool          │  tank
Drive        │  NVMe           │  SATA SSD
Role         │  OS + active VMs │  Backups + bulk
Compression  │  lz4            │  lz4
Atime        │  on (default)   │  off
Recordsize   │  64K            │  64K (vms), 8K (ct), 1M (media)
Snapshots    │  Sanoid hourly  │  Sanoid hourly + manual
Backup       │  vzdump weekly  │  N/A (backup target)
Replication  │  —              │  Syncoid → SRV2 + offsite SSD
```

If you're starting fresh with Proxmox, a simple two-disk layout (NVMe for VMs, SATA/HDD for backups) and sanoid for snapshots will take you further than most pre-built backup appliances. ZFS recovers you from the most common failure mode — operator error — with near-zero operational cost.
