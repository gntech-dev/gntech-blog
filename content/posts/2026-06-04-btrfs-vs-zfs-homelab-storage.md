---
title: "Btrfs vs ZFS for Homelab Storage — Proxmox and Docker Guide"
description: "Compare Btrfs vs ZFS for homelab storage on Proxmox and Docker. Performance, features, memory use, snapshots, and practical recommendations for choosing your filesystem."
date: 2026-06-04T14:30:00-04:00
tags:
  - storage
  - linux
  - homelab
  - proxmox
  - docker
keywords:
  - Btrfs vs ZFS homelab Proxmox comparison guide
  - ZFS vs Btrfs Docker storage overlay2 performance
  - Btrfs file system features compression snapshots quotas
  - ZFS ARC memory tuning homelab best practices
  - Docker overlay2 storage driver ZFS performance
  - Btrfs send receive incremental snapshot backup
  - Proxmox ZFS Btrfs filesystem choice recommendation
summary: "Compare Btrfs and ZFS for homelab storage on Proxmox and Docker. Architecture, memory, snapshots, compression, and practical recommendations."
canonical: "https://blog.gntech.me/posts/btrfs-vs-zfs-homelab-storage/"
---

## Btrfs vs ZFS for Homelab Storage — Which Filesystem Should You Choose?

If you run a homelab with Proxmox and Docker, you will eventually face the Btrfs vs ZFS question. Both are advanced copy-on-write filesystems with checksumming, snapshots, and compression. Both have passionate advocates. And both work with Proxmox VE.

The short answer: **use ZFS for your hypervisor storage and Btrfs for your Docker container volumes**. But the full picture depends on your hardware, workload, and comfort with tuning.

This guide compares both filesystems across the metrics that actually matter in a homelab: memory use, Docker compatibility, snapshot workflows, compression performance, and pool management flexibility.

## Architecture and Kernel Integration

The first difference is architectural. ZFS is not part of the Linux kernel — it ships as an external DKMS module maintained by the OpenZFS project. Every kernel update triggers a rebuild of `zfs.ko` and `spl.ko`. On Proxmox this is handled automatically, but you will occasionally hit a delay between a kernel release and the matching ZFS module.

Btrfs lives in the Linux kernel tree, maintained by kernel developers. It compiles as part of `btrfs.ko` and is always compatible with whatever kernel you are running.

```bash
# Check your ZFS version
zfs --version

# Check Btrfs version (kernel module)
modinfo btrfs | grep version

# Check available Btrfs features
btrfs filesystem show /mnt/storage
```

For daily use, most people will never notice the difference. The DKMS rebuild takes a few seconds during upgrades. But if you run custom kernels or frequent edge releases, Btrfs wins on simplicity.

## Memory Usage — The ZFS ARC Tax

This is the area where Btrfs has a clear advantage in RAM-constrained homelabs.

ZFS uses an Adaptive Replacement Cache (ARC) that eagerly consumes available memory. By default, ZFS can claim up to 50% of system RAM. On a 16 GB Proxmox host, that means 8 GB reserved for the ARC before any VMs start. You can clamp it:

```bash
# Check current ARC size
cat /proc/spl/kstat/zfs/arcstats | grep -E "^c |^size |^c_max"

# Set ARC max in /etc/modprobe.d/zfs.conf (adjust to your system)
options zfs zfs_arc_max=2147483648   # 2 GB

# Apply without reboot
echo 2147483648 > /sys/module/zfs/parameters/zfs_arc_max
```

Btrfs uses the standard Linux page cache. It does not pre-allocate memory, does not have an ARC, and yields memory to applications when needed. On a 4 GB or 8 GB homelab node, Btrfs will leave noticeably more RAM for your workloads.

**The rule of thumb**: ZFS can be used comfortably with 8 GB+ RAM. Below that, running ZFS becomes a tradeoff. Btrfs works well on anything with 2 GB or more.

## Data Integrity and Checksumming

Both filesystems checksum data and metadata. Both can detect and repair silent data corruption when redundancy is available.

ZFS checksums every block via a Merkle tree. When configured with mirrors or raidz, it performs automatic self-healing — if one copy is corrupt, ZFS fetches a good copy and repairs the bad one.

```bash
# ZFS scrub to verify and repair data
zpool scrub rpool

# Monitor scrub progress
zpool status -v rpool
```

Btrfs also checksums data and metadata. Self-healing works on RAID levels 1, 10, and (with caveats) 5 and 6.

```bash
# Btrfs scrub
btrfs scrub start /mnt/storage

# Status
btrfs scrub status /mnt/storage
```

In practice, both handle data integrity well. ZFS is more battle-tested here, especially at scale. Btrfs has had RAID56 corruption issues that are still being resolved — if you need RAID5/6, pick ZFS.

## Docker Storage Drivers

If you run Docker containers heavily, the storage driver matters.

**Docker on ZFS**: The `zfs` storage driver creates a ZFS dataset per image layer. It works well but does not support `overlay2` — Docker skips the overlay layer model entirely. Performance is generally good, but container writes go through ZFS datasets instead of the overlay union filesystem.

```json
{
  "storage-driver": "zfs"
}
```

**Docker on Btrfs**: Docker uses the native `overlay2` driver with Btrfs as the backing filesystem. Snapshots are used for layer management. This is the same code path as ext4/XFS but with Btrfs-level snapshot capabilities.

```json
{
  "storage-driver": "overlay2"
}
```

For container-heavy workloads, Btrfs + overlay2 is measurably faster for layer operations and is the simpler configuration. Docker's own documentation recommends overlay2 as the preferred driver.

```bash
# Check your current Docker storage driver
docker info | grep "Storage Driver"

# Docker performance with Btrfs — layer pulls are faster
docker pull nginx:latest
```

If you run Docker inside a Proxmox LXC container (which many homelabbers do), the container itself uses a ZFS dataset. But inside that LXC, Docker writes to ext4 or Btrfs depending on how the LXC is configured. Btrfs gives you the overlay2 path natively.

## Compression Performance

Both filesystems offer transparent compression. On modern hardware with AES-NI and multi-core CPUs, compression is essentially free for data workloads.

**ZFS** uses lz4 by default, which is incredibly fast. Newer pools can use zstd at compression levels 1 through 19.

```bash
# Enable lz4 compression on a ZFS dataset
zfs set compression=lz4 tank/data

# Check current compression ratio
zfs get compressratio tank/data
```

**Btrfs** supports zstd, lzo, and zlib. Zstd at level 1 (`zstd:1`) is the recommended balance of speed versus compression.

```bash
# Enable zstd compression on a Btrfs subvolume
btrfs filesystem defrag -czstd /mnt/data

# Set compression on mount in /etc/fstab
UUID=your-uuid /mnt/data btrfs defaults,compress=zstd:1 0 0

# Check compression ratio
btrfs filesystem usage /mnt/data
```

In benchmarks, lz4 (ZFS) and zstd:1 (Btrfs) offer comparable performance. Zstd typically compresses 5-15% better than lz4 at level 1, with similar CPU cost.

## Snapshot and Replication Workflows

This is where both filesystems really shine. Native snapshots and send/receive are the killer features that make them worth choosing over ext4 or XFS.

**ZFS snapshots** are instant, space-efficient, and can be sent incrementally via `zfs send -i`.

```bash
# Create a snapshot
zfs snapshot tank/data@backup-$(date +%Y%m%d)

# Send to a backup target (incremental from previous snapshot)
zfs send -i tank/data@backup-20260601 tank/data@backup-20260604 | \
  ssh backup-server zfs receive backup/data

# Automate with sanoid
# /etc/sanoid/sanoid.conf
[tank/data]
    use_template = production
    recursive = yes

[template_production]
    hourly = 24
    daily = 30
    monthly = 3
```

**Btrfs snapshots** are also instant. Send/receive works similarly but uses a different syntax.

```bash
# Create a read-only snapshot
btrfs subvolume snapshot -r /mnt/data /mnt/data/.snapshots/backup-20260604

# Send to a backup target
btrfs send /mnt/data/.snapshots/backup-20260604 | \
  ssh backup-server btrfs receive /backup/data

# Automate with btrbk
# /etc/btrbk/btrbk.conf
volume /mnt/data
    snapshot_dir .snapshots
    snapshot_create hourly
    snapshot_retain_min 2d
    snapshot_retain_max 3m
    target ssh://backup-server//backup/data
```

Both workflows are production-grade. ZFS send/receive is more widely documented, but Btrfs send/receive has matured significantly and works reliably across machines.

## Pool Management and RAID

ZFS pools consist of vdevs. You cannot add a single disk to an existing vdev — you add an entire vdev (mirror or raidz). You cannot shrink a pool. Pool expansion is planned in OpenZFS but not yet stable.

```bash
# ZFS: create a 3-disk raidz1 pool
zpool create tank raidz1 /dev/sda /dev/sdb /dev/sdc

# Add a mirror vdev
zpool add tank mirror /dev/sdd /dev/sde
```

Btrfs allows adding and removing devices from an existing filesystem. You can start with two disks in RAID1 and add a third later.

```bash
# Btrfs: create a 2-disk RAID1 filesystem
mkfs.btrfs -d raid1 -m raid1 /dev/sda /dev/sdb

# Add a third disk
btrfs device add /dev/sdc /mnt/storage

# Rebalance to RAID1 across all three
btrfs balance start -dconvert=raid1 -mconvert=raid1 /mnt/storage

# Remove a device (if space allows)
btrfs device remove /dev/sdb /mnt/storage
```

For flexibility with mixed disk sizes, Btrfs is the clear winner. For fixed, redundant pools you will never change, ZFS is equally capable.

## Quotas and Resource Limits

ZFS quotas are mature and reliable:

```bash
# Set a dataset quota (hard limit)
zfs set quota=500G tank/data/website

# Refquota limits the dataset itself, not snapshots
zfs set refquota=500G tank/data/website

# User quota
zfs set userquota@www-data=100G tank/data/website
```

Btrfs qgroups have a history of inconsistency, especially with snapshots. They work for basic cases but can produce surprising results under snapshot-heavy workloads. For Docker use cases, the standard filesystem-level quotas (`quota` mount option with project quotas) are more reliable.

```bash
# Btrfs subvolume quota (use with caution)
btrfs qgroup limit 500G /mnt/data/website

# More reliable: use standard project quotas
mount -o prjquota,compress=zstd:1 /dev/sda /mnt/data
```

If quotas are critical for multi-tenant setups, ZFS wins here.

## Proxmox Integration

Proxmox VE installs with either ext4, XFS, or ZFS as the root filesystem. Btrfs is not an installer option but can be configured manually.

For the hypervisor itself, ZFS is the recommended choice because:
- It integrates with Proxmox Backup Server natively
- It provides boot environments for safe upgrades
- Proxmox manages ZFS datasets for VM/LXC storage automatically

```bash
# Add a ZFS storage to Proxmox
pvesm add zfspool storage --pool tank --content images,rootdir
```

For Docker workloads inside Proxmox, running Docker in a LXC container with Btrfs storage (or even on its own Btrfs-formatted disk) gives you the overlay2 performance advantage.

A common hybrid strategy:
- **Proxmox host**: ZFS for VM/LXC storage and hypervisor reliability
- **Docker LXC**: Btrfs subvolume or disk for container storage

## Decision Matrix

| Factor | ZFS | Btrfs |
|--------|-----|-------|
| Memory usage | High (ARC) | Low (page cache) |
| Docker storage driver | Non-overlay (zfs) | overlay2 native |
| Data integrity | Battle-tested, mature | Mature for RAID1/10 |
| Snapshots | Excellent | Excellent |
| Quotas | Mature, reliable | Qgroups still maturing |
| Pool flexibility | Cannot add single disk | Add/remove disks freely |
| Kernel integration | DKMS module | In-kernel |
| RAID5/6 | Production grade | Experimental |
| Compression | lz4 (fast), zstd | zstd:1 (best ratio) |
| Proxmox integration | Native installer option | Manual setup |

Choose **ZFS** when: You have 8 GB+ RAM, need RAID5/6, require reliable quotas, or want the most battle-tested data integrity for the hypervisor.

Choose **Btrfs** when: You are RAM-constrained, run Docker heavily, want the flexibility to add and remove disks, or prefer deep kernel integration.

The best homelab configuration uses both: ZFS for your Proxmox storage pool and VMs, Btrfs for your Docker container volumes inside a dedicated LXC. You get the reliability of ZFS where it matters and the performance of overlay2 where Docker workloads count.
