---
title: "ZFS Pool Design — Mirrors, Recordsize, ARC Tuning for Proxmox"
description: "Design a ZFS pool for your Proxmox homelab — choose mirrors vs RAID-Z, set ashift correctly, tune recordsize and volblocksize, size the ARC, and add SLOG or L2ARC for better performance."
date: 2026-05-26T11:00:00Z
tags:
  - zfs
  - storage
  - performance
  - proxmox
  - homelab
keywords:
  - ZFS pool design Proxmox mirror vs RAID-Z homelab
  - ZFS ashift 12 13 NVMe SSD configuration
  - ZFS recordsize volblocksize VM database tuning
  - ZFS ARC max size 1GB per TB RAM calculation
  - ZFS SLOG NVMe power loss protection ZIL
  - ZFS monitoring arcstat zpool iostat zdb
  - OpenZFS lz4 zstd compression benchmark
summary: "A practical guide to ZFS pool design and performance tuning for Proxmox homelabs — topology selection, ashift, recordsize, compression, ARC sizing, and real-world monitoring with arcstat and zpool iostat."
canonical: "https://blog.gntech.me/posts/zfs-pool-design-proxmox-homelab/"
---

ZFS on Proxmox is not set-and-forget. The defaults work, but they
optimize for nobody. A pool you built with `zpool create tank
/dev/sdb /dev/sdc` is likely running in a suboptimal configuration
— wrong `ashift`, default `recordsize`, uncompressed data, and an
ARC sized for a desktop, not a hypervisor.

This post covers every layer of ZFS tuning that matters for a
Proxmox homelab: pool topology, creation-time parameters, dataset
properties, ARC sizing, and the SLOG/L2ARC decision. Every command
works on Proxmox VE 9.x / Debian 12 with OpenZFS 2.3+.

---

## Step 1 — Pool Topology: Mirrors vs RAID-Z

This is the single most impactful decision you will make. It
determines your IOPS, your capacity, your rebuild speed, and your
resilience profile. There is no universally correct choice.

### Mirror VDEVs — IOPS King

A mirror vdev group (two or more disks, each storing a full copy)
gives you the best random IO performance. Reads can come from any
member. Writes go to all members simultaneously and complete when
the slowest finishes.

```bash
# 6-drive pool — 3 mirror vdevs, usable capacity = 3 × disk size
zpool create tank \
  mirror /dev/sdb /dev/sdc \
  mirror /dev/sdd /dev/sde \
  mirror /dev/sdf /dev/sdg
```

**Good for:**
- VM disk storage (random 4K IOPS matter here)
- Database workloads (PostgreSQL, MySQL)
- Anything latency-sensitive

**Bad for:**
- Capacity efficiency (you lose 50% of raw space)
- Very large pools on a budget

**Rebuild speed:** Fast. ZFS copies data from the surviving mirror
member. A 4 TB drive resilvers in 2–4 hours on a loaded host.

### RAID-Z VDEVs — Capacity Efficient

RAID-Z distributes data and parity across all disks in a single
vdev. RAID-Z2 (double parity) is the sweet spot for homelabs.

```bash
# 6-drive pool — single RAID-Z2 vdev, usable ≈ 4 × disk size
zpool create tank \
  raidz2 /dev/sdb /dev/sdc /dev/sdd /dev/sde /dev/sdf /dev/sdg
```

**Good for:**
- Bulk media storage, ISO libraries, backups
- Sequential write workloads
- Maximizing usable space per dollar

**Bad for:**
- Random IOPS (bottlenecked by a single parity group)
- Mixed VM workloads (latency spikes under contention)

**Rebuild speed:** Slow. Every block must be reconstructed from
parity across all surviving disks. A 4 TB drive in a 6-wide
RAID-Z2 can take 12–24+ hours.

### The Hybrid Approach

Many Proxmox homelabs run two pools:

```bash
# Fast pool — mirrors for VMs and databases
zpool create fastpool \
  mirror nvme0n1 nvme1n1 \
  mirror nvme2n1 nvme3n1

# Bulk pool — RAID-Z2 for media and backups
zpool create bulkpool \
  raidz2 sda sdb sdc sdd sde sdf
```

Register each as a separate storage in Proxmox (`Datacenter →
Storage → Add → ZFS`). This lets you pin each VM and CT to the
right tier.

---

## Step 2 — ashift: The Most Common Mistake

`ashift` controls ZFS's logical sector size. The default is 0
(auto-detect), which reads the physical sector size reported by
the drive. The problem: almost every SSD and many modern HDDs
*lie* and report 512 bytes when their real sector size is 4 KB
or 8 KB.

Running ashift=9 (512 bytes) on a 4 KB-native drive causes ZFS to
issue 8× more IOs than needed, thrashing the drive with partial
sector writes. Performance loss is 20–50% on random writes.

### What ashift Value to Use

| Drive type | Recommended ashift | Notes |
|---|---|---|
| Modern NVMe (Samsung PM9A3, Kioxia CD8, etc.) | 13 (8 KB) | Most enterprise NVMes use 8 KB pages |
| Consumer NVMe (Samsung 990 Pro, WD SN850X) | 12 (4 KB) or 13 | Test both — check with `nvme id-ns` |
| SATA SSD (870 Evo, MX500) | 12 (4 KB) | Universally correct |
| SATA HDD, Advanced Format (≥2011) | 12 (4 KB) | All modern HDDs use 4 KB sectors |
| Legacy HDD (pre-2010, 512 byte native) | 12 (4 KB) still safe | Minor overhead, enables future drive swaps |

**Set ashift at pool creation time. It is immutable afterward.**

```bash
# Correct: create pool with ashift=12 on SATA SSDs
zpool create -o ashift=12 tank mirror sda sdb

# Correct: create pool with ashift=13 on modern NVMe
zpool create -o ashift=13 tank mirror nvme0n1 nvme1n1
```

### Verify After Creation

```bash
zdb -C tank | grep ashift
# Output: ashift: 12  (means 2^12 = 4096 bytes)
```

If you built a pool without setting ashift and suspect it is wrong,
unfortunately the only fix is to destroy and recreate. Backup your
data, destroy the pool, recreate with the right ashift, and restore.

---

## Step 3 — Compression: Always Enable lz4 (or zstd)

Compression in ZFS is essentially free on modern CPUs. LZ4 can
compress at 1–2 GB/s per core. Enabling it reduces storage usage,
lowers write amplification on SSDs, and frequently *improves* read
latency because less data is fetched from disk.

```bash
# Enable globally on the pool
zfs set compression=lz4 tank

# Verify
zfs get compression tank
```

### lz4 vs zstd

| Algorithm | Speed | Ratio | When to use |
|---|---|---|---|
| lz4 | 3–4 GB/s per core | 2–3× on text/logs | Default everywhere |
| zstd-1..3 | 1–2 GB/s per core | 2–4× | Media metadata, container images |
| zstd-6..9 | 200–500 MB/s per core | 3–5× | Cold storage, backups (save space, accept CPU cost) |
| zstd-10..19 | <100 MB/s per core | Up to 6× | Archival only |
| gzip-9 | Slow | Comparable to zstd-3 | Legacy — use zstd instead |

For a homelab running VMs, databases, and media:

```bash
# Default for everything
zfs set compression=lz4 fastpool
zfs set compression=lz4 bulkpool

# For backup datasets on the bulk pool — zstd for better ratio
zfs set compression=zstd-3 bulkpool/backups
```

### Real-World Compression Ratios

```bash
# Check compression on a dataset
zfs get compressratio bulkpool/media
# Output: compressratio 1.48x

# See per-file estimates
zfs list -o name,compressratio,used,logicalused
```

Typical numbers:
- VM disk images (qemu raw/img): 1.1–1.3×
- ISO backups: 1.0× (already compressed)
- Docker overlay2 data: 1.8–2.5×
- PostgreSQL databases: 1.5–2.0×
- Logs and config files: 3–5×

---

## Step 4 — recordsize and volblocksize

ZFS issues IOs in chunks called *records* (for datasets) and
*blocks* (for zvols). The size of these chunks has a massive
impact on performance.

### Dataset recordsize (for file storage)

Use this for SMB/NFS shares, backup directories, and media stores.

```bash
# Default is 128K — fine for most file workloads
zfs set recordsize=128K bulkpool/media

# Small files (git repos, code): 64K
zfs set recordsize=64K bulkpool/projects

# Dump/backup datasets: 1M for sequential throughput
zfs set recordsize=1M bulkpool/backups
```

### zvol volblocksize (for VM block storage)

This is the size ZFS uses when the VM issues a write. Proxmox VM
disks are zvols by default. Mismatching this to the guest workload
is the #2 ZFS performance mistake (after ashift).

```bash
# Default is 8K — reasonable for mixed VM workloads

# For database VMs (PostgreSQL, MySQL): 4K or 8K
# The guest DB engine issues 8K random writes

# For media/file-server VMs: 16K or 32K
# Sequential streaming benefits from larger blocks

# For backup-target VMs: 64K
# Pure sequential write pattern
```

Set it at zvol creation. Unlike dataset recordsize, you cannot
efficiently change volblocksize after data exists.

To check the volblocksize of an existing VM disk:

```bash
zdb -dddd fastpool/vm-100-disk-0 2>/dev/null | grep volblocksize
# Output: volblocksize = 8192
```

If you want to change it, the practical approach in Proxmox is:

1. Shut down the VM
2. Create a new zvol with the desired volblocksize
3. `dd` the old zvol to the new one (or use `qemu-img convert`)
4. Detach the old disk, attach the new one

---

## Step 5 — ARC Sizing

ZFS uses Adaptive Replacement Cache (ARC) as an in-memory read
cache. It competes with your VMs and containers for RAM.

### How the Default Works

By default, ZFS will consume up to 50% of system RAM for the ARC.
On a 64 GB host, that is 32 GB of RAM locked by ZFS, leaving only
32 GB for VMs and the OS.

### Tuning ARC max

```bash
# Set ARC max to 8 GB
echo 8589934592 > /sys/module/zfs/parameters/zfs_arc_max

# Make it permanent
cat > /etc/modprobe.d/zfs.conf << 'EOF'
# Limit ZFS ARC to 8 GB on a 64 GB host
options zfs zfs_arc_max=8589934592
EOF

# Regenerate initramfs
update-initramfs -u
```

### How Much ARC Is Enough?

General guidance for Proxmox:

| System RAM | Suggested ARC max | Notes |
|---|---|---|
| 8 GB | 1 GB | Bare minimum — monitor arcstats |
| 16 GB | 2–4 GB | Good for 2–3 light VMs |
| 32 GB | 4–8 GB | Good for 4–6 VM/CT workloads |
| 64 GB | 8–16 GB | Typical Proxmox single node |
| 128 GB | 16–32 GB | Heavy VM density |
| 256 GB+ | 32–64 GB | ARC will grow but VMs matter more |

### Monitor ARC Effectiveness

Install and run `arcstat`:

```bash
apt install sysstat  # Provides sar, also arcstat on Proxmox

# Watch ARC in real time, every 2 seconds
arcstat -f time,read,hits,miss,hit%,dhit%,l2hits,l2miss,l2asize 2

# Key metrics:
# hit%  — ARC read hit rate (target >90%)
# miss  — reads that hit disk (want these low)
# dhit% — demand-data hit rate (important — excludes prefetch)
```

If `hit%` is below 85% and you have free RAM, increase ARC.
If `dhit%` is above 95%, your ARC is doing its job. Decreasing it
may free RAM for VMs without a significant performance penalty.

---

## Step 6 — SLOG and L2ARC: When and Whether

### SLOG (Separate ZFS Intent Log)

A SLOG is a dedicated NVMe device for synchronous write
operations. It does *not* cache reads. It only absorbs the ZIL
(ZFS Intent Log) to accelerate `fsync()` and `O_SYNC` writes
from databases and journaling filesystems.

**You need a SLOG if:**
- Your main pool is HDD-based and you run databases inside VMs
- You see high `zil_commit` latency in `zpool iostat -l 1`
- Your pool has NVMe but you want to isolate ZIL traffic

**You do NOT need a SLOG if:**
- Your pool is all-NVMe (native NVMe latency for ZIL is already
  <100 µs)
- You run no sync-heavy workloads (media servers, file shares)

**Hardware requirements for SLOG:**
1. **Power-loss protection** (PLP) — mandatory. Consumer NVMe
   drives lie about flushing writes. If the SLOG lies about a
   write and power fails, your pool is corrupt.
2. Use enterprise NVMe: Intel Optane (best — sold as
   "Intel Optane Memory H10/H20" on eBay), Samsung PM9A3,
   Kioxia CD6, or any NVMe with a supercapacitor.
3. **Mirror it.** A single SLOG is a single point of failure.

```bash
# Add a mirrored SLOG to an existing pool
zpool add tank log mirror /dev/nvme0n1 /dev/nvme1n1

# Verify
zpool status tank
# Look for: logs: mirror-2 (or similar)
```

**SLOG sizing:** The ZIL is a small ring buffer. 10–20 GB per
SLOG device is more than enough for any homelab.

### L2ARC (Level 2 ARC)

L2ARC is a read cache on a secondary device (usually cheaper
SSD/NVMe). Data evicted from ARC is written to L2ARC.

**When it helps:**
- You have a large HDD pool with a small ARC (e.g., 8 GB ARC
  for 40 TB of HDD storage)
- Your working data set is larger than ARC but fits on a single
  SSD

**When it does NOT help:**
- Your ARC hit rate is already >90%
- Your pool is all-NVMe (ARC on NVMe is already fast)
- Your workload is write-heavy (L2ARC is read-only for data)

```bash
# Add an L2ARC device
zpool add tank cache /dev/sdc

# Monitor L2ARC effectiveness
arcstat -f time,l2hits,l2miss,l2hit%,l2asize 2
```

**Opinion:** Most homelabs do not benefit from L2ARC. The ARC
hit rate on a 16 GB ARC serving a few VMs is usually above 95%.
Add more RAM instead. L2ARC only makes sense when you have a
large pool with insufficient ARC and cannot add RAM.

---

## Step 7 — Dataset Properties for Common Homelab Workloads

This table summarizes the recommended `zfs set` properties for
different use cases:

| Workload | recordsize | compression | atime | special notes |
|---|---|---|---|---|
| VM disks (zvol) | 8K (volblocksize) | lz4 | off | `zfs set primarycache=metadata` for DB VMs |
| Docker overlay2 | 64K | lz4 | off | `xattr=sa` for extended attr perf |
| Samba/NFS media | 128K | lz4 | off | `aclmode=passthrough` for NFSv4 ACLs |
| Backup target | 1M | zstd-3 | off | Sequential streaming benefits from large records |
| ISOs/Templates | 128K | lz4 | off | Read mostly, cache trivial |
| PostgreSQL data dir | 8K (zvol) | lz4 | off | `logbias=throughput` to bypass ZIL on async |
| Proxmox container root | 64K | lz4 | off | Container filesystems use small blocks |
| Samba Time Machine | 128K | lz4 | off | `dnodesize=legacy` for macOS compat |

Set these immediately after creating the dataset or zvol:

```bash
zfs create -o recordsize=64K -o compression=lz4 \
  -o atime=off tank/docker-overlay2

zfs create -V 100G -o volblocksize=8K -o compression=lz4 \
  -o atime=off fastpool/vm-200-disk-0
```

---

## Step 8 — Monitoring ZFS Health and Performance

ZFS ships excellent tools. Use them weekly.

### Pool Health

```bash
# Quick health check
zpool status -v tank

# Look for:
#   state: ONLINE             ← good
#   state: DEGRADED           ← failed or removed disk
#   errors: No known data errors
#   scrub: ... with 0 errors  ← last scrub passed

# Detailed error counters
zpool status -v -s tank
# Shows read/write/checksum errors per drive
```

### IO Statistics

```bash
# Continuous IO throughput and latency
zpool iostat -v tank 2

# Full latency breakdown
zpool iostat -v -l tank 2
# Adds: sync_wait, async_wait, scrub, trim latency

# With queue depth per vdev
zpool iostat -v -q tank 2
```

### Scrubs — Schedule Them

A scrub reads every block and verifies checksums. It is the only
way to detect and repair silent data corruption.

```bash
# Manual scrub
zpool scrub tank

# Check scrub status
zpool status tank
# Shows: scan: scrub in progress since ...
```

Proxmox schedules a monthly scrub by default. Verify:

```bash
cat /etc/cron.d/zfsutils-linux
# Should contain: 0 4 * * 0 root /usr/sbin/zpool scrub -a
```

If not present, add a weekly systemd timer:

```bash
# /etc/systemd/system/zfs-scrub@.service
[Unit]
Description=ZFS scrub on %I
[Service]
Type=oneshot
ExecStart=/usr/sbin/zpool scrub %I
ExecStartPost=/usr/sbin/zpool status %I

# /etc/systemd/system/zfs-scrub@.timer
[Unit]
Description=Weekly ZFS scrub on %I
[Timer]
OnCalendar=Sun 03:00
Persistent=true
[Install]
WantedBy=timers.target
```

### arcstat Quick Reference

```bash
# Watch ARC in real time
arcstat 2

# One-shot summary
arcstat -o -s 2 1
```

Key columns:
- `read` — total ARC reads per second
- `hits` — reads satisfied from ARC
- `miss` — reads that went to disk
- `hit%` — overall hit ratio
- `dhit%` — demand data hit ratio (ignore prefetch)
- `l2hits` / `l2miss` — L2ARC hits and misses (useful only if
  you have L2ARC)

---

## Putting It All Together: A Complete Example

Here is a real configuration for a 64 GB Proxmox host with 4 ×
1 TB NVMe (VM pool) and 6 × 4 TB HDD (bulk storage):

```bash
# --- VM pool: 4x NVMe, 2x mirror vdevs, ashift=13 ---
zpool create -o ashift=13 fastpool \
  mirror nvme0n1 nvme1n1 \
  mirror nvme2n1 nvme3n1

zfs set compression=lz4 fastpool
zfs set atime=off fastpool

# --- Bulk pool: 6x HDD, RAID-Z2, ashift=12 ---
zpool create -o ashift=12 bulkpool \
  raidz2 sda sdb sdc sdd sde sdf

zfs set compression=zstd-3 bulkpool
zfs set atime=off bulkpool

# --- Limit ARC to 16 GB ---
echo 17179869184 > /sys/module/zfs/parameters/zfs_arc_max
cat > /etc/modprobe.d/zfs.conf << 'EOF'
options zfs zfs_arc_max=17179869184
EOF
update-initramfs -u

# --- Create datasets ---
zfs create -o recordsize=64K bulkpool/docker
zfs create -o recordsize=1M -o compression=zstd-6 bulkpool/backups
zfs create -o recordsize=128K bulkpool/media
zfs create -o recordsize=128K fastpool/templates
```

---

## Summary

ZFS is the best storage filesystem for Proxmox, but only if you
configure it intentionally. The checklist from this post:

1. **Choose topology** — mirrors for IOPS, RAID-Z for capacity
2. **Set ashift at pool creation** — 12 for SATA, 13 for NVMe
3. **Enable compression** — lz4 everywhere, zstd on backups
4. **Match recordsize to workload** — 8K for VMs, 64K for Docker,
   128K for media, 1M for backups
5. **Size the ARC** — 1 GB per 8 TB of pool, or whatever your
   VM RAM budget allows
6. **Skip SLOG on all-NVMe pools** — add one only for HDD pools
   with sync-heavy VMs
7. **Monitor weekly** — `zpool status`, `arcstat`, `zpool iostat`

A properly tuned ZFS pool will outlast the hardware it runs on,
migrate seamlessly between Proxmox nodes, and never silently
corrupt a byte of data. That is the point of running ZFS.
