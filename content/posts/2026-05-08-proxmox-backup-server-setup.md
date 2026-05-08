---
title: "Proxmox Backup Server — Installation, Datastore Tuning, and Garbage Collection"
description: "Install Proxmox Backup Server on Debian, create a datastore with proper verification and GC intervals, prune backups, and integrate with a Proxmox VE host for automated VM/CT backups."
date: 2026-05-08T04:00:00-04:00
tags:
  - proxmox
  - backup
  - pbs
  - storage
  - homelab
categories:
  - homelab
  - storage
---

Proxmox Backup Server (PBS) is purpose-built backup storage for Proxmox VE. It does one thing and does it well: store, deduplicate, verify, and garbage-collect VM and container backups. No more cramming vzdump archives onto a NFS share and hoping they survive.

This guide covers installing PBS on Debian 12, creating a datastore with sane retention, connecting a PVE host, and avoiding the gotchas that'll eat your disk space.

---

## Why PBS Instead of a Simple NFS Export

| Capability | NFS vzdump | PBS |
|------------|-----------|-----|
| Deduplication | None | Chunk-level, across all backups |
| Incremental backups | Full dump each time | Changed blocks only |
| Integrity verification | None | Auto-verify after backup |
| Garbage collection | None | Prunes orphaned chunks |
| Restore granularity | Full restore only | File-level, single disk, or full VM |

For a homelab with multiple VMs and LXCs, the deduplication alone saves hours of transfer and disk space. Incremental backups mean daily backups take seconds, not minutes.

---

## Installation

PBS ships as a standalone ISO, but I'm installing it on Debian 12 running in a Proxmox VM for flexibility.

### VM Specs

| Setting | Value |
|---------|-------|
| OS | Debian 12 (Bookworm) |
| vCPUs | 2 |
| RAM | 4 GB |
| System disk | 32 GB (OS + PBS metadata) |
| Backup storage | 500 GB raw disk passed as `/dev/vdb` |
| IP | 10.0.20.50/24 (VLAN 20 LAB) |

The backup storage disk is separate from the OS disk. This matters: if the OS disk dies, your backup data doesn't disappear with it.

### Add PBS Repository

```bash
echo "deb http://download.proxmox.com/debian/pbs bookworm pbs-no-subscription" > /etc/apt/sources.list.d/pbs.list
```

Fetch the repo key:

```bash
curl -fsSL https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg -o /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg
```

Install:

```bash
apt update && apt install -y proxmox-backup-server
```

The service starts on port 8007. Point a browser at `https://10.0.20.50:8007` and you'll get the web UI.

> **HTTPS is required.** PBS uses a self-signed cert by default. Accept it in your browser or upload a trusted cert under Administration → Certificates.

---

## Datastore Creation

A datastore is a directory managed by PBS with its own chunk store, verification schedule, and GC policy. Create one on the backup disk:

```bash
mkdir -p /backup/pbs-datastore
```

In the web UI: Datastore → Add Datastore

| Field | Value |
|-------|-------|
| Name | `main` |
| Path | `/backup/pbs-datastore` |
| GC Schedule | daily at 02:00 |
| Verification Schedule | daily at 03:00 |
| Verify New | Yes |

The datastore path should be a **dedicated disk or filesystem**, not the OS root. ZFS is ideal for the datastore (compression, checksums), but ext4 works fine.

---

## Storage Under the Hood

PBS stores backups as chunk-addressed blobs inside `.chunks/`. A 500 GB datastore with deduplication typically holds the equivalent of 2—3 TB of raw VM disk data before compression.

On disk:

```
/backup/pbs-datastore/
├── .chunks/           # Deduplicated data chunks
├── .gc-candidates/    # Orphaned chunks pending GC
├── ct/                # LXC backups
└── <PBS_ID>/          # VM or CT backup index
```

The chunk store is content-addressed: each chunk is named by its SHA-256 hash. Identical blocks across VMs and versions collapse to one copy.

---

## Retention Policies

PBS uses **prune** rules to keep your backup count manageable. I run two schedule-level policies:

### Prune Job — Keep

```
Keep last 7 daily
Keep last 4 weekly
Keep last 3 monthly
```

This gives a month of recovery granularity without filling the disk. The prune runs nightly and removes backup snapshots according to the rule.

Prune only removes backup snapshots, not the underlying data chunks. That's where garbage collection comes in.

---

## Garbage Collection

GC reclaims space from chunks that are no longer referenced by any backup. PBS uses a mark-and-sweep approach:

1. **Mark phase** — walks all backup snapshots and marks each referenced chunk
2. **Sweep phase** — deletes unmarked chunks

Set GC to run daily (or weekly for smaller datastores). PBS disables GC by default:

Web UI → Datastore → main → Options → GC Schedule → `daily 02:00`

During GC, backups can still proceed, but deduplication won't find new matching chunks for the current operation.

---

## Connecting PVE to PBS

On the Proxmox VE host, add the PBS storage:

Datacenter → Storage → Add → Proxmox Backup Server

| Field | Value |
|-------|-------|
| ID | `pbs-main` |
| Server | `10.0.20.50` |
| Datastore | `main` |
| Username | `root@pam` (or a dedicated user) |
| Password | (your PBS root password) |
| Fingerprint | (paste from PBS Dashboard → Server Fingerprint) |

The fingerprint is your TLS trust anchor. Paste it instead of disabling certificate verification. Copy it from the PBS web UI under Administration → Server Fingerprint.

### Verify the Connection

```bash
pvesm status
```

You should see `pbs-main` with `Active 1` and the datastore's usage stats.

---

## Running Backups

Create a backup job through the PVE web UI:

Datacenter → Backup → Add

| Field | Value |
|-------|-------|
| Storage | `pbs-main` |
| Schedule | `daily 00:00` |
| Selection mode | All (or specific VMs/CTs) |
| Backup type | Snapshot |
| Compression | Zstandard (zstd) |
| Mode | Stop if running VM (or snapshot) |

### Important: Backup Mode

- **Stop mode** — shuts down the VM briefly for a consistent snapshot. Fast but causes downtime.
- **Snapshot mode** — live backup with QEMU dirty bitmap. No downtime but slightly higher disk I/O during backup.
- **Suspend mode** — hybrid, suspends the VM during snapshot.

For LXCs, snapshot mode is the default and works well. For production VMs, snapshot mode is the safer choice.

---

## Restore Scenarios

### Full VM Restore

In PVE web UI, select a backup → Restore. PBS restores the full VM to any node in the cluster.

### File-Level Restore

For Linux VMs: Right-click the backup → File Restore. PBS spawns a small QEMU that mounts the backup image and serves it over HTTP (port 10000). You browse and download individual files through the browser.

### Reinstall PBS from Scratch

Backup metadata lives in the datastore itself. If the PBS VM dies:

1. Reinstall PBS on a new VM
2. Reattach the backup disk
3. Go to Datastore → Add Datastore → point at the existing path
4. Run `proxmox-backup-manager verify` to reindex everything

Your datastore is portable. The only thing you lose is the server config (users, ACLs), not the backup data.

---

## Performance Tuning

### ZFS on the Datastore

If the backup disk is backed by ZFS, enable compression:

```bash
zfs set compression=zstd-3 backup-pool/pbs
zfs set atime=off backup-pool/pbs
```

PBS already deduplicates at the application level, so ZFS dedup is wasteful. Stick to compression only.

### I/O Threads

In PBS datastore options, increase the verification I/O threads from 1 to 4 for faster checksumming on multi-core systems.

### Network

If backing up over a 1 Gbps link, consider jumbo frames (MTU 9000) between PVE and PBS. With VLAN-segmented networking, this means configuring MTU 9000 on both the bridge and the VLAN interface.

---

## Monitoring

PBS exposes a REST API at `https://<PBS-IP>:8007/api2/json/`. Useful endpoints:

```
GET /api2/json/admin/datastore — datastore usage
GET /api2/json/nodes/localhost/tasks — active tasks
GET /api2/json/nodes/localhost/tasks?status=running — running tasks
```

For Telegram alerts, poll the tasks endpoint for failed backup jobs. Or use PVE's built-in notification system to relay to PBS.

---

## Gotchas

**Don't let the datastore fill to 100%.** PBS can't run GC when the disk is full, which means you can't reclaim space. Set a disk usage alarm at 85%.

**Slow initial backup is expected.** The first backup of a VM sends all data. Subsequent backups send only changed chunks. Expect the first run to take 5x—10x longer.

**PBS doesn't compress chunks on disk by default.** Enable ZFS compression at the pool level for space savings without a CPU penalty.

**Don't share the datastore path.** PBS assumes exclusive ownership of the `.chunks/` directory. Writing to it from outside PBS will corrupt the chunk store.

---

## Summary

PBS replaces fragile vzdump-to-NFS with chunk-level deduplication, incremental forever backups, and automated verification. For a homelab with 5-10 VMs and LXCs, a 500 GB datastore running daily backups with monthly retention is more than sufficient.

Key takeaways:
- Separate OS disk from backup storage
- Enable GC and verification schedules
- Use snapshot backup mode for live VMs
- Restoring a file is as easy as right-click → File Restore
- The datastore survives PBS reinstalls — the data stays portable
