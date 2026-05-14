---
title: "Proxmox ZFS ARC Tuning — Optimize Cache for VM Performance"
description: "Master Proxmox ZFS ARC tuning with practical configs for homelab nodes — set deterministic cache limits, add L2ARC SSDs correctly, and avoid common memory starvation pitfalls that slow down your VMs."
date: 2026-05-14T12:00:00-04:00
tags:
  - proxmox
  - zfs
  - storage
  - performance
  - homelab
keywords:
  - Proxmox ZFS ARC tuning
  - ZFS ARC max size configuration
  - L2ARC SSD Proxmox homelab
  - Proxmox ZFS performance optimization
  - ZFS ARC memory budget
  - Proxmox ZFS recordsize tuning
  - ZFS compression lz4 vm storage
summary: "Set deterministic ZFS ARC limits, add L2ARC without wasting RAM on metadata, and tune recordsize and compression for your Proxmox homelab VMs."
canonical: "https://gntech.dev/posts/proxmox-zfs-arc-tuning/"
---

Your Proxmox host has 64 GB of RAM. You allocated 48 GB to VMs. So
where did the other 16 GB go? If you're running ZFS, the answer is
almost certainly the ARC — and it may be using more than you think.

ZFS's Adaptive Replacement Cache is aggressive by design. It will
consume up to 50% of your system RAM by default and keep growing
until it hits the kernel's `zfs_arc_max` limit. On a Proxmox host
running multiple VMs, this creates a silent competition: the ARC
keeps growing, the kernel reclaims it under pressure, VMs get
paged, and I/O latency spikes unpredictably.

This post covers how to take control of your ZFS ARC allocation,
when L2ARC actually helps, and what settings your Proxmox VM
datasets should use for maximum throughput.

---

## Step 1: Budget Your ARC Before Adding VMs

ARC sizing on Proxmox is a capacity planning problem, not a tuning
exercise. You need to decide upfront how much RAM ZFS can use and
stick to it.

The default Proxmox behavior sets `zfs_arc_max` to 50% of system
RAM, capped at 16 GiB. This is defensive, not optimal. On a 128 GiB
host, ZFS will eat up to 16 GiB by default — fine. But on a 32 GiB
host running a dozen containers, 16 GiB of ARC means only 16 GiB
for your entire workload.

Here's the process:

1. **Reserve RAM for your VMs and Proxmox.** Add up your VM
   allocations (not what they use, what they're assigned). Add 2-4 GiB
   for Proxmox itself.
2. **What's left is your ZFS budget.** Of that, give most to ARC.
   Leave ~4-8 GiB for kernel page cache, networking buffers, and
   system services.
3. **Set a hard ARC cap.** Never let ZFS fight VMs for memory.

Example: 128 GiB node with 96 GiB assigned to VMs:

- VM + Proxmox reservation: ~100 GiB
- Remaining for system: 28 GiB
- ARC cap: 24 GiB
- Kernel/systems buffer: 4 GiB

```
# /etc/modprobe.d/zfs.conf
options zfs zfs_arc_max=25769803776   # 24 GiB
options zfs zfs_arc_min=8589934592    # 8 GiB minimum
```

The `zfs_arc_min` prevents the kernel from reclaiming ARC too
aggressively during transient memory pressure. Without it, a
short-lived VM spike can flush your hot cache, tanking performance
until the ARC warms back up.

Apply and reboot:

```bash
update-initramfs -u -k all
reboot
```

Verify after boot:

```bash
cat /sys/module/zfs/parameters/zfs_arc_max
# Should show 25769803776

arc_summary -s arc | grep "ARC size"
# Should be at or near the minimum initially
```

---

## Step 2: Validate ARC Sizing by Node Capacity

Here are practical ARC caps for common homelab node sizes. These
assume the node is running mixed VM workloads with typical I/O
patterns (web servers, databases, media, containers).

| Node RAM | Suggested ARC Max | Guest Budget | Notes                         |
|----------|-------------------|--------------|-------------------------------|
| 32 GiB   | 8 GiB             | ~20 GiB      | Tight — monitor hit ratio     |
| 64 GiB   | 16 GiB            | ~42 GiB      | Sweet spot for most homelabs  |
| 128 GiB  | 24-48 GiB         | ~72-96 GiB   | Depends on VM density         |
| 256 GiB  | 64-96 GiB         | ~150-180 GiB | L2ARC becomes useful here     |

The key metric is your ARC hit ratio. If you're running at 95%+
hit ratio, your ARC is well-sized for your workload. If it's below
80%, you either need more ARC or you've got working sets too large
for RAM — that's when L2ARC enters the conversation.

```bash
# Check ARC hit ratio
arc_summary -s arc | grep -E "hit ratio|miss ratio"
# Goal: > 90% for read-heavy workloads
```

---

## Step 3: When and How to Add L2ARC

L2ARC extends the ARC onto a fast SSD. Every block evicted from RAM
ARC can be written to the L2ARC device instead of being discarded.
If it's accessed again, ZFS reads it from the fast SSD instead of
the slow pool.

**L2ARC helps when:**
- Your ARC hit ratio is already high (85%+) — meaning ARC is doing
  its job and filling up
- Your working set doesn't fit in RAM but fits on a moderately sized SSD
- Your pool is HDD-based and the L2ARC device is NVMe

**L2ARC does NOT help when:**
- Your ARC hit ratio is low — fix ARC sizing first
- Your pool is already all-SSD — the gap between ARC and pool latency
  is too small to matter
- You don't have spare ARC RAM for the L2ARC index (see below)

### The L2ARC Index Tax

This is the most overlooked cost of L2ARC. Every block stored in
L2ARC requires an index entry in ARC memory. The overhead depends
on your recordsize:

| Recordsize | Index overhead per TiB of L2ARC |
|------------|--------------------------------|
| 8 KiB      | ~8960 MiB                       |
| 32 KiB     | ~2240 MiB                       |
| 128 KiB    | ~571 MiB                        |

If you add a 1 TiB L2ARC with 8 KiB records (Proxmox zvol default),
that's nearly 9 GiB of ARC RAM consumed just for metadata. If your
ARC cap is 16 GiB, more than half goes to index overhead. That
cannibalizes your hot cache for the sake of extending it — a net
loss.

**Rule of thumb:** Don't let L2ARC index overhead exceed 1/3 of your
ARC cap. For a 24 GiB ARC, cap L2ARC at roughly 920 GiB (8 KiB
records) to 15 TiB (128 KiB records).

### Adding L2ARC to a Pool

```bash
# Identify the SSD (use by-id for persistence)
ls -la /dev/disk/by-id/ | grep nvme

# Add as cache vdev
zpool add rpool cache /dev/disk/by-id/nvme-Samsung_SSD_970_EVO_plus_S1234567

# Verify
zpool status rpool
# Look for "cache" section with the device listed
```

The L2ARC populates automatically over time as ARC evictions occur.
There's no warmup phase — it fills as blocks are pushed out of RAM.

### SLOG: Separate from L2ARC

SLOG is often confused with L2ARC. A SLOG (Separate Intent Log) is
a dedicated device for ZFS synchronous write transactions — not a
cache. It accelerates writes for NFS, databases, and VMs with sync
enabled. A small, power-protected NVMe or Optane drive (10-20 GiB)
is ideal. A large SLOG is wasted space; ZFS only writes the
current transaction group (typically 5-10 seconds of writes).

```bash
# Add a SLOG device (mirror recommended for safety)
zpool add rpool log mirror \
  /dev/disk/by-id/nvme-Optane_MEMPEK1J016GA_XXXX \
  /dev/disk/by-id/nvme-Optane_MEMPEK1J016GA_YYYY

# Never use the same SSD for SLOG and L2ARC
```

---

## Step 4: Tune Recordsize for Your Datasets

ZFS recordsize determines the maximum block size for files in a
dataset. Match it to your workload for optimal performance.

| Workload         | Recommended Recordsize | Why                                         |
|------------------|------------------------|---------------------------------------------|
| VM disks (zvols) | 8-16 KiB (default)     | Matches guest block I/O patterns            |
| Databases        | 16-32 KiB              | PostgreSQL/MariaDB default page sizes       |
| Container rootfs | 8-16 KiB               | Similar to VMs — random small I/O           |
| Media storage    | 1 MiB                  | Large sequential reads benefit big blocks   |
| Backups          | 1 MiB                  | Sequential, compression-friendly            |
| ISO/Template     | 1 MiB                  | Sequential reads, rarely modified           |

```bash
# Check current recordsize
zfs get recordsize rpool/data/vm-100-disk-0

# Set for a container dataset
zfs set recordsize=16K rpool/data/subvol-101-disk-0

# Set for media storage
zfs set recordsize=1M tank/media
zfs set compression=lz4 tank/media
```

Recordsize only affects new writes. Existing data keeps its original
block size. To apply a new recordsize to existing data, recreate the
dataset and copy the data back.

---

## Step 5: Enable Compression — Always

ZFS compression with `lz4` is nearly free in CPU cost and provides
significant I/O reduction. For compressible data like VM disks, log
files, and text-based workloads, it reduces disk reads and writes
by 20-40% in practice. The CPU overhead is typically below 1% on
modern hardware.

```bash
# Enable on the root pool
zfs set compression=lz4 rpool

# Verify
zfs get compression rpool

# Check compression ratio for each dataset
zfs get compressratio rpool/data
```

`lz4` is the right default for Proxmox. Don't use `gzip` — the CPU
cost outweighs the space savings for VM workloads. `zstd` is viable
for archival datasets where compression ratio matters more than
throughput.

---

## Practical Config: Full ARC Budget Example

Here's a complete configuration for a 128 GiB Proxmox node with
mixed HDD pool + NVMe L2ARC:

```bash
# /etc/modprobe.d/zfs.conf
options zfs zfs_arc_max=25769803776    # 24 GiB
options zfs zfs_arc_min=8589934592     # 8 GiB

# After reboot, add L2ARC to HDD pool
zpool add tank cache \
  /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_2TB_XXXX

# Set dataset properties
zfs set compression=lz4 tank
zfs set recordsize=1M tank/media
zfs set recordsize=16K tank/vm
zfs set atime=off tank
zfs set xattr=sa tank

# Disable access time — no benefit for VM storage
# xattr=sa stores extended attributes in the inode (faster for ACLs)
```

Verify everything took effect:

```bash
# ARC settings
cat /sys/module/zfs/parameters/zfs_arc_max
cat /sys/module/zfs/parameters/zfs_arc_min

# Pool layout
zpool status -v

# ARC performance
arc_summary -s arc

# Dataset properties
zfs get compression,recordsize,atime,xattr tank
```

---

## Monitoring: Catch Problems Before VMs Stutter

Track these metrics weekly, especially after significant VM changes:

### ARC Hit Ratio

```bash
# Quick check
arc_summary -s arc | grep -E "hit ratio|miss ratio"

# Detailed breakdown
arcstat 1 10
```

If hit ratio drops below 80%, your ARC is undersized or your
workload changed. Consider increasing `zfs_arc_max` or adding L2ARC.

### ARC Size vs Pressure

```bash
# Current ARC size
echo $(cat /proc/spl/kstat/zfs/arcstats | grep size | head -1 | awk '{print $3}')

# How often ARC is being evicted
cat /proc/spl/kstat/zfs/arcstats | grep "evict"
```

High eviction rates with low hit ratio = ARC too small.

### Memory Pressure on VMs

```bash
# Check Proxmox host memory
free -h
# If available memory is near zero and swap is used,
# your ARC cap may be too high

# Check individual VM ballooning
qm list | awk '{print $1}' | tail -n +2 | while read vmid; do
  echo "VM $vmid: $(qm balloon $vmid 2>/dev/null || echo 'no balloon')"
done
```

If VMs are ballooning aggressively (reducing their memory below
what you allocated), the host is starving. Reduce `zfs_arc_max`.

---

## Common Mistakes

### Mistake 1: No ARC Cap at All

Without `zfs_arc_max`, ZFS eats up to 50% of RAM. Your VMs compete
for the remaining half. On a 64 GiB host, that's 32 GiB for ZFS
and 32 GiB for everything else. Your VMs will balloon, swap, and run
slow.

Fix: Set `zfs_arc_max` to a deliberate value. Even the conservative
Proxmox default of 16 GiB is better than nothing.

### Mistake 2: L2ARC on a Pool That's Already All-SSD

L2ARC adds overhead for minimal gain when the underlying pool is
already fast NVMe. The index entries consume ARC RAM. The read
latency gap between ARC and NVMe is tiny. L2ARC becomes a net
negative.

Fix: Skip L2ARC on all-flash pools. Use the budget for more RAM.

### Mistake 3: SLOG and L2ARC on the Same Device

SLOG wants low latency, power-protected writes. L2ARC wants high
capacity for reads. Putting both on a single consumer NVMe means
neither is optimal — and writes to the SLOG compete with L2ARC reads.

Fix: Separate devices, or skip SLOG entirely if you don't have
synchronous write workloads (NFS exports or databases with sync
commit).

### Mistake 4: Using `gzip` Compression on Active VM Datasets

`gzip` at level 6+ consumes significant CPU. A 16-thread VM
workload writing to a gzip-compressed zvol will bottleneck on
the compression thread. `lz4` achieves similar real-world ratios
for VM disk images with 10x less CPU.

Fix: Always use `lz4` for active datasets. Use `zstd` or `gzip`
only for cold archival datasets.

---

## Summary

ZFS ARC tuning on Proxmox comes down to a single principle: decide
how much RAM ZFS gets, configure it explicitly, and never let it
fight your VMs.

1. **Budget first** — reserve RAM for VMs, give the rest to ARC
2. **Set `zfs_arc_max` and `zfs_arc_min`** — no defaults, no guesses
3. **Add L2ARC only if** ARC hit ratio is high (85%+) and your pool
   is HDD
4. **Track the L2ARC index tax** — it consumes ARC RAM
5. **Enable `lz4` compression everywhere** — free performance
6. **Match recordsize to workload** — 8-16K for VMs, 1M for media

On a 128 GiB node with 24 GiB of dedicated ARC and lz4 compression,
expect 90-95% ARC hit ratios for typical mixed workloads. Your VMs
get predictable memory, your ZFS pool gets efficient caching, and
your weekend doesn't get derailed by mysterious I/O latency spikes.
