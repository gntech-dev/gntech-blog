---
title: "Proxmox LXC Resource Management — CPU, Memory, and Disk I/O Limits"
description: "Complete guide to Proxmox LXC resource management — CPU pinning and cgroups CPU quotas, memory limits and swap control, disk I/O throttling, and ZFS quota/refquota tuning for containers."
date: 2026-05-24T07:00:00-04:00
tags:
  - proxmox
  - linux
  - homelab
  - performance
  - storage
keywords:
  - Proxmox LXC CPU pinning cgroups CPU quota
  - Proxmox container memory limit swap control
  - Proxmox LXC disk I/O throttling IOPS limit
  - Proxmox LXC ZFS quota refquota configuration
  - Proxmox LXC cgroups resource limits tuning
  - Proxmox container resource contention prevention
  - LXC resource limits homelab Proxmox VE 8
summary: "Master Proxmox LXC resource management — configure CPU pinning with cgroups, set memory and swap limits, throttle disk I/O, and apply ZFS quotas to prevent noisy-neighbor contention in your homelab containers."
canonical: "https://gntech.dev/posts/proxmox-lxc-resource-management/"
---

Your Proxmox host runs ten LXCs — a Pi-hole, a database container,
a reverse proxy, Authentik, Gitea, and six more. Everything works
until one container decides to consume all available RAM or peg
every CPU core. Suddenly your DNS starts timing out, the reverse
proxy returns 502s, and the database container gets OOM-killed
before the culprit even notices.

This is the noisy-neighbor problem in virtualization. Proxmox
provides per-container resource limits out of the box, but most
homelab setups leave them at defaults — which effectively means
no limits at all.

This guide covers every LXC resource control available in Proxmox
VE 8.x+: CPU pinning and cgroup CPU quotas, memory and swap caps,
disk I/O throttling, and ZFS storage quotas. Every config includes
the Proxmox CLI command, the UI path, and runtime verification.

---

## Why Default LXC Resource Limits Aren't Enough

When you create an LXC in Proxmox, the defaults are:

```text
CPU units:   1024
CPU limit:   0 (unlimited)
Memory:      unlimited
Swap:        unlimited
Disk:        size of the rootfs volume
```

The only real constraint is the rootfs disk size. CPU and memory
are shared freely. On a busy host with 16 GB RAM and eight LXCs,
a single misbehaving container can exhaust memory and trigger the
OOM killer. The kernel picks a victim — and it's rarely the one
you wanted killed.

Proxmox exposes LXC resource controls through two layers:
- **cgroups** (v1 and v2) — kernel-level CPU, memory, and I/O
  limits enforced by the container runtime
- **Storage quotas** — ZFS, LVM, or directory-level size
  restrictions on the root filesystem

The commands in this guide use `pct set`, which maps directly
to cgroup parameters. All configs persist across container
restarts and host reboots.

---

## CPU Resource Controls

Proxmox LXCs support three CPU controls: CPU units (weight),
CPU limits (ceiling), and CPU pinning (affinity).

### CPU Units — Relative Weight

CPU units set proportional weight, not a hard cap. A container
with 2048 units gets roughly twice the CPU time of a container
with 1024 units when both are busy. When only one container is
active, it can burst to 100%.

```bash
# Set CPU weight to 2048 (double the default of 1024)
pct set 100 --cpulimit 2048

# Set CPU weight to 512 (half the default)
pct set 101 --cpulimit 512
```

The default of 1024 is reasonable for general-purpose containers.
Reserve higher weights for latency-sensitive services (DNS,
reverse proxy, databases). Assign lower weights to batch or
testing containers.

Use case | CPU units
----------|----------
Latency-critical (DNS, proxy, auth) | 2048
Standard workload (Gitea, dashboards) | 1024
Background/batch (backup tools, sync) | 512
Testing/experimental | 256

### CPU Limit — Hard Cap

CPU limit (`cpulimit`) enforces a hard ceiling as a percentage of
a single core. A limit of 50 means the container cannot exceed
50% of one core — or 400 for four full cores.

```bash
# Limit container 100 to 2 CPU cores
pct set 100 --cpulimit 2

# Limit to 50% of one core
pct set 101 --cpulimit 0.5
```

CPUs across all containers on the host should sum to roughly
the total available cores × 1.0-1.5 overhead. On an 8-core host
with ten containers, keep each under 6-8 cores to allow headroom
for Proxmox itself.

### CPU Pinning — Affinity

CPU pinning locks a container to specific physical cores. This
prevents cache thrashing when containers migrate between cores
and ensures consistent performance for real-time workloads.

```bash
# Pin container 100 to CPU cores 0 and 1
pct set 100 --cpulimit 2 --cpuunits 2048
# Pin via cgroup directly on the host
echo "0-1" > /sys/fs/cgroup/cpuset/lxc/100/cpuset.cpus
```

Alternatively, set CPU affinity in the container's config file:

```bash
# /etc/pve/lxc/100.conf
lxc.cgroup2.cpuset.cpus: 0-1
lxc.cgroup2.cpuset.mems: 0
```

**When to pin:**
- Database containers that benefit from dedicated L2/L3 cache
- Real-time audio or video processing
- Containers with hard real-time requirements

**When not to pin:** Most general workloads. Pinning reduces
scheduler flexibility and can leave cores idle while other
containers wait.

Verify CPU assignments:

```bash
# Check per-container CPU usage from the host
pct exec 100 -- cat /proc/stat | grep cpu

# View cgroup CPU stats
cat /sys/fs/cgroup/cpu,lxc/100/cpu.stat
```

---

## Memory and Swap Limits

Memory limits prevent a single container from starving the host.
Proxmox enforces memory caps through cgroup memory controllers.

### Hard Memory Limit

Set a hard cap that the container cannot exceed. When reached,
the container's processes start getting OOM-killed rather than
the host deciding victims.

```bash
# Limit container 100 to 2 GB RAM
pct set 100 --memory 2048

# Limit to 512 MB
pct set 101 --memory 512
```

If you set `--memory 0` (default), the container can use all
host memory. On a 16 GB host with eight containers, that means
any single one can eat 14+ GB before the OOM killer fires.

### Swap Limit

Swap works differently in LXCs than in VMs. The swap limit
controls the amount of swap the container can use on the host.

```bash
# Set 512 MB swap maximum for container 100
pct set 100 --swap 512

# Disable swap entirely for a container
pct set 100 --swap 0
```

Most homelab containers don't need swap. Databases should never
swap. Disable swap for critical LXCs:

```bash
# Disable swap inside the container too
pct exec 100 -- swapoff -a
echo 'swapoff -a' >> /etc/cron.d/disable-swap
```

### Practical Memory Budget for a Homelab Host

On an 8-core, 32 GB RAM Proxmox host with ten LXCs:

```text
Container         | RAM   | Swap | Notes
DNS (Pi-hole)     | 256M  | 0    | Minimal footprint
Reverse proxy     | 256M  | 0    | Traefik or Nginx
Auth (Authentik)  | 2G    | 512M | Python-heavy, needs room
Database (Postgres)| 4G   | 0    | Never swap databases
Gitea             | 1G    | 256M |
Monitoring stack  | 2G    | 512M | Prometheus + Grafana
File syncing      | 512M  | 256M | Syncthing or Nextcloud
Backup tools      | 512M  | 256M | Restic, rclone
Dev/test LXC      | 1G    | 512M |
Media (Jellyfin)  | 4G    | 0    | ffmpeg needs RAM
                  |       |      |
Host reserve      | 4G+   |      | Proxmox + ZFS ARC
```

Sum allocated: ~16 GB. The host reserve of 4+ GB covers ZFS ARC,
Proxmox services, and the kernel. Leave at least 20% headroom.

### Memory Hot-Plug for LXCs

Proxmox supports live memory changes on running containers
without restart:

```bash
# Increase memory to 4 GB on a running container
pct set 100 --memory 4096

# Reduce back to 2 GB (if current usage is under the limit)
pct set 100 --memory 2048
```

This works because cgroup limits are dynamic. The container
kernel sees available memory shrink but handles it gracefully
unless it was already using more than the new limit.

---

## Disk I/O Throttling

CPU and memory limits prevent compute contention, but disk I/O is
often the real bottleneck. Ten containers fighting over a single
NVMe drive can cause latency spikes even if CPU is idle.

### IOPS Limits

Set read and write IOPS limits per container:

```bash
# Limit container 100 to 500 read IOPS, 200 write IOPS
pct set 100 --iolimit "read=500,write=200"

# Remove I/O limits
pct set 100 --iolimit 0
```

This uses cgroup I/O controllers (`io.max` v2 or `blkio.throttle`
v1). The limit applies to the container's rootfs device.

### Bandwidth Limits

Cap read and write throughput by bytes per second:

```bash
# Limit container 100 to 50 MB/s read, 20 MB/s write
pct set 100 --iobwlimit "read=52428800,write=20971520"

# Remove bandwidth limits
pct set 100 --iobwlimit 0
```

Always round to reasonable values for your storage hardware:

Drive type           | Sequential read | Sequential write | Random IOPS
---------------------|-----------------|------------------|------------
NVMe (Gen 4)         | 5000 MB/s       | 4000 MB/s        | 500K+
SATA SSD             | 500 MB/s        | 450 MB/s         | 80K
HDD (7200 RPM)       | 180 MB/s        | 150 MB/s         | 150
ZFS mirror (NVMe)    | 3000 MB/s       | 2000 MB/s        | 300K+

For ZFS pools, leave at least 20% I/O headroom for the ARC
flush, ZIL writes, and scrub operations.

### I/O Priority by Container Type

A practical priority scheme for a 7-container homelab on NVMe:

```bash
# Database — high priority, needs consistent I/O
pct set 101 --iolimit "read=200000,write=100000"
pct set 101 --iobwlimit "read=2147483648,write=1073741824"

# Media server — high reads, moderate writes
pct set 102 --iolimit "read=100000,write=50000"
pct set 102 --iobwlimit "read=4294967296,write=536870912"

# General services — moderate everything
pct set 103 --iolimit "read=50000,write=25000"
pct set 103 --iobwlimit "read=1073741824,write=268435456"

# Backup containers — dampen impact on other services
pct set 104 --iolimit "read=10000,write=5000"
pct set 104 --iobwlimit "read=268435456,write=134217728"
```

The backup container is the key one to restrict. During nightly
backups, restic and rclone can saturate the disk and degrade
everything else. A 10K read / 5K write IOPS limit and
~250 MB/s read / 125 MB/s write bandwidth cap keeps backups
slightly slower but prevents disruption.

---

## ZFS Quotas and Refquota

For containers on ZFS storage — the default Proxmox
configuration — two quota types apply: `quota` limits the
total space including snapshots, while `refquota` limits only
the container's active data (excluding snapshots).

```bash
# Set a 50 GB quota (including snapshots)
pct set 100 --quota 50

# Set a 40 GB refquota (snapshots don't count)
pct set 100 --refquota 40
```

Use `refquota` for containers where snapshot churn could fill
the volume. A Gitea container with 10 GB of git data and 50 GB
of weekly snapshots should have at least a 20 GB refquota plus
enough quota headroom for snapshots:

```bash
pct set 103 --refquota 20 --quota 60
```

This container can use 20 GB of active data. Snapshots can
accumulate up to 40 GB before hitting the 60 GB quota wall —
which gives you time to prune old snapshots.

### View ZFS Quota Usage

```bash
# Check ZFS usage for a container dataset
zfs get all rpool/data/subvol-100-disk-0 | grep -E "quota|refquota|used|available"

# Output:
# rpool/data/subvol-100-disk-0  quota         50G   local
# rpool/data/subvol-100-disk-0  refquota      20G   local
# rpool/data/subvol-100-disk-0  used          12G   -
# rpool/data/subvol-100-disk-0  available     38G   -
```

### Resize ZFS Disk on the Fly

Need to grow a container's disk? Proxmox resizes the ZFS
subvolume online:

```bash
# Grow container 100 rootfs to 80 GB
pct resize 100 rootfs 80G

# Shrink (dangerous — requires unmount)
pct resize 100 rootfs 40G --shrink
```

Shrinking ZFS volumes requires the filesystem inside to be
smaller than the target. Always `pct exec 100 -- df -h` first
to verify actual usage.

---

## Comprehensive Resource Profile

Combine everything into a single profile for a container:

```bash
# Container 101 — Postgres database
pct set 101 \
  --cpulimit 4 \
  --cpuunits 2048 \
  --memory 4096 \
  --swap 0 \
  --iolimit "read=200000,write=100000" \
  --iobwlimit "read=2147483648,write=1073741824" \
  --refquota 30 \
  --quota 80

# Container 102 — Jellyfin media server  
pct set 102 \
  --cpulimit 6 \
  --cpuunits 1024 \
  --memory 4096 \
  --swap 0 \
  --iolimit "read=100000,write=50000" \
  --iobwlimit "read=4294967296,write=536870912" \
  --refquota 50 \
  --quota 100

# Container 105 — Backup worker (restic/rclone)
pct set 105 \
  --cpulimit 2 \
  --cpuunits 256 \
  --memory 512 \
  --swap 256 \
  --iolimit "read=10000,write=5000" \
  --iobwlimit "read=268435456,write=134217728" \
  --refquota 10 \
  --quota 30
```

The backup container profile is the most restrained: low CPU
weight so it yields to everything else, minimal IOPS to avoid
disrupting database and media reads, and small RAM since backup
operations are streaming, not memory-bound.

---

## Monitoring Resource Pressure

After setting limits, verify they work under load:

```bash
# Watch container CPU and memory in real time
pct top

# Check container I/O stats from the host
cat /sys/fs/cgroup/io.stat/lxc/101

# View cgroup memory pressure
cat /sys/fs/cgroup/memory/lxc/101/memory.pressure

# Inside the container: check if limits are binding
pct exec 101 -- free -h
pct exec 101 -- cat /proc/meminfo | grep -i swap
```

The `memory.pressure` file shows PSI (Pressure Stall Information).
A `some avg10` value over 50 means the container is frequently
waiting on memory. Raise the limit or investigate the workload.

For CPU pressure:

```bash
cat /sys/fs/cgroup/cpu/lxc/101/cpu.pressure
```

A `full avg10` over 10 indicates the container is CPU-bound and
hitting its cgroup ceiling. Consider raising `--cpulimit` or
pinning the container to dedicated cores.

---

## Proxmoz UI vs CLI — When to Use Each

Most resource limits can be set from the Proxmox web UI:

**Container → Resources → Add** (or double-click an existing row):

- Memory, Swap, CPU units, CPU limit — all available in the UI
- I/O limits — available in the UI under "IO Limit" and "IO
  Bandwidth"
- CPU pinning — **not** available in the UI, must use CLI or
  edit `lxc.cgroup2` in `/etc/pve/lxc/<CTID>.conf`

For bulk operations across containers, use the CLI:

```bash
# Apply standard limits to multiple containers
for ctid in 101 102 103; do
  pct set $ctid --memory 2048 --swap 256 --cpulimit 2
done
```

Or better, script it with a config file:

```bash
#!/bin/bash
# /usr/local/bin/apply-lxc-limits.sh
declare -A LIMITS
LIMITS[100]="--memory 512 --swap 0 --cpulimit 1"
LIMITS[101]="--memory 4096 --swap 0 --cpulimit 4"
LIMITS[102]="--memory 4096 --swap 0 --cpulimit 6"
LIMITS[105]="--memory 512 --swap 256 --cpulimit 2"

for ctid in "${!LIMITS[@]}"; do
  if pct status $ctid &>/dev/null; then
    echo "Setting limits for CT $ctid..."
    pct set $ctid ${LIMITS[$ctid]}
  fi
done
```

Run this from a cron job or Ansible to enforce consistency.

---

## Summary

A methodical approach to LXC resource management prevents the
noisy-neighbor problem in dense Proxmox homelabs:

1. **CPU** — Set `cpuunits` for proportional weight; use
   `cpulimit` for hard caps on noisy containers; pin only for
   databases and real-time workloads
2. **Memory** — Always set a hard `--memory` limit on every
   container; disable swap for databases and latency-sensitive
   services
3. **I/O** — Cap backup workers to 10K IOPS to prevent nightly
   contention; leave database and media containers with higher
   limits
4. **Disk** — Use `refquota` for active data limits and `quota`
   for total-with-snapshots; resize from CLI with `pct resize`

Start with conservative limits: 2 GB RAM, 2 CPU cores, 50 GB
disk for most containers. Monitor pressure indicators with
`pct top` and cgroup PSI files. Adjust upward only when the
container shows genuine need.

Every container gets a hard limit. No container gets to steal
resources from the rest of your lab.
