---
title: "Linux Disk I/O Tuning — IO Schedulers, Mount Options, and cgroup Throttling"
description: "Optimize Linux disk I/O for your homelab — choose the right IO scheduler for NVMe vs HDD, tune mount options for latency, monitor with iostat/ioping, and throttle container IO with cgroups."
date: 2026-05-25T18:30:00Z
tags:
  - linux
  - storage
  - performance
  - homelab
  - docker
keywords:
  - Linux disk IO scheduler tuning NVMe SSD
  - Linux mount options noatime performance
  - iostat ioping disk latency monitoring
  - cgroup v2 IO throttling Docker containers
  - Linux IO scheduler none vs mq-deadline vs bfq
  - Linux block device queue parameters tuning
  - Proxmox disk IO performance optimization
summary: "A practical guide to Linux disk I/O performance tuning for homelab servers — IO scheduler selection for NVMe, SSD, and HDD, mount option optimization, real-time monitoring with iostat and ioping, and container IO throttling with cgroup v2."
canonical: "https://gntech.dev/posts/linux-disk-io-performance-tuning/"
---

Disk I/O is the most common bottleneck in a homelab. A misconfigured
IO scheduler can add 5–10 ms of latency to every write. Wrong mount
options silently double metadata writes. And one noisy container can
starve every other service on the box.

Most Linux distributions ship conservative defaults that work on
anything from a Raspberry Pi to a 48-bay storage server. That means
they are tuned for nobody. Your homelab deserves better.

This guide covers the three layers of disk I/O tuning that matter:

1. **IO schedulers** — which one for NVMe, SATA SSD, and spinning rust
2. **Mount options** — `noatime`, `commit`, `discard`, and `nobarrier`
3. **cgroup IO throttling** — taming container I/O with cgroup v2

Every command and config here works on Debian 12, Ubuntu 24.04,
Proxmox VE 9.x, and the current Linux 7.x kernel series.

---

## Step 1 — Understanding Your IO Scheduler

The IO scheduler sits between the block layer and the storage driver.
Its job: reorder, merge, and dispatch I/O requests to maximize
performance. The right choice depends entirely on your hardware.

### Check What You Are Running

```bash
# Show the current scheduler for every block device
cat /sys/block/*/queue/scheduler

# Typical output for NVMe (kernel 6.8+ defaults to none):
# nvme0n1 — [none] mq-deadline kyber bfq
#
# Typical for SATA SSD/HDD:
# sda — none [mq-deadline] kyber bfq
```

The bracket shows the active scheduler. Modern Linux on NVMe defaults
to `none` (noop), which is correct. SATA drives often default to
`mq-deadline`. Both are sane, but not always optimal.

### Which Scheduler When

| Hardware | Recommended Scheduler | Why |
|---|---|---|
| NVMe SSD (datacenter grade) | `none` | NVMe controllers have native command queuing. Adding a scheduler just burns CPU. Leave it alone. |
| NVMe SSD (consumer / DRAM-less) | `mq-deadline` | These benefit from write-merging. Test both. |
| SATA SSD (Samsung 870, MX500, etc.) | `mq-deadline` or `kyber` | Deadline gives latency guarantees. Kyber is leaner. |
| SATA HDD (spinning disks, bulk storage) | `bfq` | BFQ provides fair I/O bandwidth sharing. Crucial for multi-VM hosts sharing one HDD. |
| RAID controller (HBA, LSI, etc.) | `none` | The controller handles ordering. Schedulers add overhead. |

### Changing the Scheduler

Temporary change (live, no reboot):

```bash
# Set NVMe drive to none
echo none > /sys/block/nvme0n1/queue/scheduler

# Set spinning HDD to bfq
echo bfq > /proc/sys/kernel/iosched_bfq  # only if module loaded
echo bfq > /sys/block/sda/queue/scheduler
```

Permanent change via udev rule:

```bash
cat > /etc/udev/rules.d/60-ioscheduler.rules << 'EOF'
# NVMe SSDs — no scheduler needed
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]", ATTR{queue/scheduler}="none"

# SATA SSDs — deadline for balanced latency
ACTION=="add|change", KERNEL=="sd*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"

# Spinning disks — bfq for fair multi-tenant IO
ACTION=="add|change", KERNEL=="sd*", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"
EOF
```

The `queue/rotational` attribute is the kernel's way to distinguish
HDDs (rotational=1) from SSDs (rotational=0). The udev rule applies
on boot and on hotplug.

---

## Step 2 — Tuning Block Device Queue Parameters

Beyond the scheduler, every device exposes tunables under
`/sys/block/<dev>/queue/`. These four make the biggest difference:

### nr_requests — Queue Depth

Controls how many I/O requests the block layer queues before
throttling the application. Higher values improve throughput under
load but increase per-request latency.

```bash
# NVMe: keep it low for latency-sensitive workloads
echo 128 > /sys/block/nvme0n1/queue/nr_requests

# HDD: higher for sequential throughput
echo 512 > /sys/block/sda/queue/nr_requests
```

### read_ahead_kb — Prefetch Window

How many kilobytes the kernel reads ahead on sequential access.
Default 128 KB is conservative. For media storage and backup targets,
increase it.

```bash
# Media storage: 4 MB read-ahead
echo 4096 > /sys/block/sdb/queue/read_ahead_kb

# Boot/OS drives: keep default (128 KB)
# Database workloads: 512 KB–1 MB
```

### max_sectors_kb — Maximum I/O Size

Largest single I/O request the block layer will issue. Modern NVMe
drives can handle 2 MB+ IOs. The default is often 1280 sectors
(~640 KB). Raise it for sequential workloads.

```bash
# NVMe backup drives: allow large IOs
echo 4096 > /sys/block/nvme1n1/queue/max_sectors_kb
```

### nomerges — Disable I/O Merging

For NVMe drives where the native controller does merging better than
the kernel, you can skip block-layer merging to save CPU.

```bash
# 0 = merging enabled (default), 2 = completely disabled
echo 2 > /sys/block/nvme0n1/queue/nomerges
```

**Persist these** through the same udev rule, or use a systemd tmpfiles
d entry:

```bash
w /sys/block/nvme0n1/queue/nr_requests - - - - 128
w /sys/block/nvme0n1/queue/read_ahead_kb - - - - 256
w /sys/block/sda/queue/nr_requests - - - - 512
w /sys/block/sda/queue/read_ahead_kb - - - - 4096
```

---

## Step 3 — Filesystem Mount Options That Matter

Mount options are the highest-impact, lowest-effort tuning you can
do. These apply to `ext4`, `xfs`, `btrfs`, and `zfs` (in different
ways).

### noatime — Skip Access Time Updates

Every file read used to write an `atime` update — a metadata write for
every read. `noatime` eliminates this. Safe to use everywhere unless
you rely on `atime` for mail spools or backup tools.

```bash
# /etc/fstab — add noatime to every filesystem
UUID=xxx-xxx  /  ext4  defaults,noatime,nodiratime  0  1
```

For databases or container storage, combine with `nobarrier` only if
you have battery-backed RAID or ZFS with a SLOG.

### commit= — Dirty Writeback Interval

Controls how often the kernel flushes dirty pages to disk. Default is
5 seconds (ext4) or 30 seconds (XFS). Lower = better crash safety.
Higher = better sequential throughput.

```bash
# Database server: flush every 5s
defaults,noatime,commit=5

# Backup/media store: flush every 30s for write coalescing
defaults,noatime,commit=30
```

### discard — Online TRIM

Enable for SSD/NVMe filesystems. Modern kernels use
`discard=async` (ext4) or `discard` (XFS), which queues TRIM
commands without blocking writes.

```bash
# ext4 on SSD
defaults,noatime,discard=async

# XFS on SSD
defaults,noatime,discard
```

### relatime — The Compromise

If you need POSIX-compliant access times for some reason, use
`relatime`. It updates atime only when the file was accessed more
recently than the last modification — vastly fewer writes than
default `atime`.

Every current Linux distribution defaults to `relatime`. If your
fstab uses `defaults`, check with `mount | grep relatime` — you
might already have it.

### Putting It Together

```bash
# /etc/fstab for a Proxmox ZFS dataset (zfs handles its own mount opts)
# For ext4 data volume on SSD:
UUID=abcd-1234  /mnt/data  ext4  defaults,noatime,nodiratime,discard=async,commit=15  0  2

# For XFS backup volume on HDD:
UUID=efgh-5678  /mnt/backup  xfs  defaults,noatime,commit=30  0  2
```

Apply without reboot:

```bash
mount -o remount /mnt/data
mount -o remount /mnt/backup
```

---

## Step 4 — Monitoring I/O in Real Time

You cannot tune what you do not measure. These four commands will
diagnose 90% of homelab I/O problems.

### iostat — Aggregate Device Stats

```bash
# Every 2 seconds, show device utilization and latency
iostat -x 2

# Key columns:
# %util   — fraction of time device was busy (warning at >90%)
# await   — average I/O latency in ms (target <5 ms for SSD)
# r_await / w_await  — read vs write latency separately
# avgqu-sz — average queue length (>1 suggests saturation)
```

### ioping — Direct Latency Probing

`ioping` bypasses caches and filesystems to test raw device latency.

```bash
# Install
apt install ioping

# Test raw device latency (NVMe should be <100 µs)
ioping -c 20 /dev/nvme0n1

# Test with 1 MB requests for throughput approximation
ioping -c 10 -s 1M /mnt/data/test.img

# Watch latency over time (every 1 second)
ioping -i 1 -c 60 /dev/sda
```

Target latencies:
- NVMe direct: 50–150 µs
- SATA SSD direct: 100–400 µs
- SATA HDD direct: 4–12 ms
- NFS over 1GbE: 200–600 µs

### iotop — Per-Process I/O

```bash
# Show top I/O consumers, accumulated
iotop -oPa

# Output example:
# TID  PRIO  USER     DISK READ  DISK WRITE  SWAPIN    IO>    COMMAND
# 2345 be/4  postgres  12.45 M/s  3.21 M/s   0.00 %   15.23 %  postgres: writer
```

### blktrace — Deep Block-Level Tracing

For when you need to trace a specific I/O request through the block
layer. Heavyweight, but irreplaceable for debugging.

```bash
# Trace sda for 5 seconds
blktrace -d /dev/sda -o - | blkparse -i -

# Or use the friendlier btt to analyze seek patterns
btt < trace output
```

---

## Step 5 — Container I/O Throttling with cgroup v2

In a homelab running Docker, your databases, media servers, download
clients, and monitoring containers all share the same disks. Without
throttling, a runaway transcoder can tank database queries.

### Checking cgroup Version

```bash
# cgroup v2 is required for Docker's --device-*-bps/--device-*-iops
stat -fc %T /sys/fs/cgroup/
# Should print "cgroup2fs"
```

Docker Engine 25+ defaults to cgroup v2 on modern kernels. Proxmox 9.x
also uses cgroup v2 by default.

### Throttle by Bandwidth (Bytes Per Second)

```bash
# Limit a Jellyfin or Plex container to 100 MB/s reads, 50 MB/s writes
docker run -d \
  --name jellyfin \
  --device-read-bps /dev/sda:100mb \
  --device-write-bps /dev/sda:50mb \
  jellyfin/jellyfin

# In Docker Compose v3.8+
services:
  jellyfin:
    image: jellyfin/jellyfin
    device_read_bps: /dev/sda:100mb
    device_write_bps: /dev/sda:50mb
```

### Throttle by IOPS (Operations Per Second)

For SSDs where latency matters more than sequential throughput,
cap by IOPS instead:

```bash
docker run -d \
  --name postgres \
  --device-read-iops /dev/nvme0n1:5000 \
  --device-write-iops /dev/nvme0n1:3000 \
  postgres:17

# Compose equivalent
services:
  postgres:
    image: postgres:17
    device_read_iops: /dev/nvme0n1:5000
    device_write_iops: /dev/nvme0n1:3000
```

### Verify Throttling Is Active

```bash
# Check the cgroup IO limits directly
cat /sys/fs/cgroup/system.slice/docker-<container-id>.scope/io.max
# Output: 8:0 rbps=104857600 wbps=52428800 riops=5000 wiops=3000
```

Use `docker stats` to confirm actual IO stays below the limit:

```bash
docker stats jellyfin

# Block IO column shows MB/s in/out
```

### A Practical Throttling Strategy

For a typical homelab with one NVMe root drive and one HDD for
storage:

```yaml
services:
  # Database — priority access, low latency critical
  postgres:
    image: postgres:17
    device_write_bps: /dev/nvme0n1:200mb
    device_read_bps: /dev/nvme0n1:200mb
    volumes:
      - pgdata:/var/lib/postgresql/data

  # Media server — no need for high priority
  jellyfin:
    image: jellyfin/jellyfin
    device_read_bps: /dev/sda:80mb
    device_write_bps: /dev/sda:40mb
    volumes:
      - media:/media

  # Download client — cap hard to avoid saturating disk
  transmission:
    image: ghcr.io/linuxserver/transmission
    device_read_bps: /dev/sda:50mb
    device_write_bps: /dev/sda:30mb
    volumes:
      - downloads:/downloads
```

---

## Step 6 — Proxmox-Specific I/O Tuning

If you run Proxmox, the host handles I/O for every VM and container.
Three settings matter most:

### ZFS Recordsize

For VM storage on ZFS, set `recordsize=64K` (not the default 128K).
VM disk images use 4K–64K blocks. Larger recordsizes waste ARC memory
and amplify write latency.

```bash
zfs set recordsize=64K rpool/data/vm-disks
```

### KVM IO Threads

Pin IO threads to dedicated CPU cores to prevent vCPU scheduling
from blocking disk operations:

```bash
# In VM config /etc/pve/qemu-server/<VMID>.conf
args: -object iothread,id=iothread1 -device virtio-blk-pci,drive=drive0,iothread=iothread1
```

### LXC IO Limits

LXC containers support disk I/O throttling natively. Set it in the
container resource tab or via CLI:

```bash
# Limit LXC container 101 to 50 MB/s writes
pct set 101 --dev0 /dev/sda,mp=/storage,acl=1 --dev1 /dev/sdb,mp=/backups,acl=1
# Then apply cgroup limits manually:
echo "8:0  rbps=100000000 wbps=50000000" > /sys/fs/cgroup/lxc/101/io.max
```

---

## Verification Checklist

Run these benchmarks before and after tuning to confirm improvements:

```bash
# Sequential read speed
ioping -c 10 -s 1M /mnt/data/testfile

# Random 4K IOPS (what matters for databases)
fio --randrepeat=1 --ioengine=libaio --direct=1 --gtod_reduce=1 \
  --name=test --bs=4k --iodepth=32 --size=1G \
  --readwrite=randwrite --filename=/mnt/data/fio-test

# Latency percentile distribution
ioping -c 100 -i 0.1 /dev/nvme0n1
```

Target numbers for a well-tuned NVMe on a modern Linux kernel:
- Sequential read: 3000–7000 MB/s (depends on drive)
- Random 4K write: 50K–200K IOPS
- Direct latency (ioping): <150 µs P99

---

## Summary

Disk I/O tuning in a homelab is a three-act play:

1. **Pick the right IO scheduler** for each device — `none` for
   NVMe, `mq-deadline` for SATA SSD, `bfq` for HDDs, and persist
   it with a udev rule.
2. **Set mount options** — `noatime` everywhere, `commit=` to
   control writeback cadence, `discard=async` for SSDs.
3. **Throttle containers** with cgroup v2 `--device-*-bps` and
   `--device-*-iops` to keep one noisy service from tanking the
   whole host.

The monitoring commands — `iostat -x`, `ioping`, `iotop -oPa` —
will tell you when something is wrong. The knobs in this post will
let you fix it.
