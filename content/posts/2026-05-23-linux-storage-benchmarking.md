---
title: "Linux Storage Benchmarking — fio, ioping, and Homelab Disk Tests"
description: "Benchmark storage performance in your homelab with fio, ioping, hdparm, and dd. Measure raw disk IOPS, ZFS pool throughput, NFS mount latency, and Docker volume performance with real commands and repeatable scripts."
date: 2026-05-23T12:00:00-04:00
tags:
  - linux
  - storage
  - homelab
  - performance
keywords:
  - fio storage benchmark Linux homelab
  - ioping disk latency testing
  - ZFS pool performance benchmark
  - NFS mount throughput testing
  - Docker volume IOPS benchmark
  - sequential vs random IO test fio
  - Proxmox storage performance baseline
summary: "Learn to benchmark storage in your homelab using fio, ioping, hdparm, and dd — raw disks, ZFS pools, NFS mounts, and Docker volumes. Includes repeatable test scripts and how to interpret results for real-world workloads."
canonical: "https://gntech.dev/posts/linux-storage-benchmarking/"
---

Your Proxmox host has NVMe, SATA SSDs, and maybe spinning rust
for bulk storage. Your NFS share feels slow during backups.
Docker PostgreSQL writes take longer than expected. Without
storage benchmarks, every performance complaint is a guessing
game.

FIO (Flexible I/O Tester) is the gold standard for Linux storage
benchmarking — it's what cloud providers use to validate their
disk performance claims. Combined with ioping for latency,
hdparm for drive info, and dd for quick checks, you can baseline
every storage tier in your homelab.

This guide covers practical storage benchmarking for homelab
scenarios: raw disks, ZFS pools, NFS mounts, and Docker volumes.
Every command runs on standard Debian/Ubuntu without special
kernel modules.

---

## Install the Tools

```bash
sudo apt update
sudo apt install -y fio ioping hdparm smartmontools sysstat
```

- **fio** — Full I/O benchmarking (IOPS, bandwidth, latency percentiles)
- **ioping** — Quick latency checks (useful for NFS and Docker volumes)
- **hdparm** — Drive info and quick read tests
- **smartmontools** — Drive health status (context for benchmark results)
- **sysstat** — System utilization during tests (iostat, pidstat)

Basic disk info before any tests:

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL
sudo hdparm -I /dev/nvme0n1 | grep -E "Model|Firmware|Speed|Version"
sudo smartctl -a /dev/sda | grep -E "SMART overall-health|Reallocated_Sector|Power_On_Hours"
```

Knowing the drive model, firmware version, and health status
prevents you from benchmarking a dying disk and misinterpreting
the results.

---

## Quick Baseline with dd (But Don't Trust It)

`dd` gives a rough throughput number but lies about latency and
random I/O — it only tests sequential writes with a single thread
and a tiny block count. Use it only as a sanity check:

```bash
# Sequential write test (1 GB, 1M block size)
dd if=/dev/zero of=/tmp/dd-test bs=1M count=1024 conv=fdatasync status=progress

# Sequential read test
dd if=/tmp/dd-test of=/dev/null bs=1M count=1024 status=progress
```

Expected output for an NVMe drive:

```
1073741824 bytes (1.1 GB, 1.0 GiB) copied, 0.643 s, 1.7 GB/s
```

A SATA SSD should hit 400–550 MB/s sequential. Spinning disks
top out at 150–250 MB/s sequential throughput. If your NVMe
shows 200 MB/s sequential, check the PCIe lane width or whether
the drive is throttling.

**Why dd is insufficient:** Docker databases and ZFS workloads
are random I/O with mixed read/write patterns. A drive that does
1.7 GB/s sequential might deliver only 20 MB/s random 4K writes.
Only fio exposes this gap.

---

## FIO — Proper Storage Benchmarking

FIO generates configurable I/O workloads and reports bandwidth,
IOPS, and latency at multiple percentiles. Every test here uses
the `--output-format=json` flag so results are machine-parseable.

### Sequential Throughput (Large Files)

Media streaming, ISO transfers, and backup restores benefit from
sequential throughput:

```bash
# Sequential read (128 KB blocks, 32 depth, 60 seconds)
fio --name=seq-read --ioengine=libaio --direct=1 --bs=128k \
    --rw=read --iodepth=32 --size=4G --numjobs=1 \
    --runtime=60 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json

# Sequential write
fio --name=seq-write --ioengine=libaio --direct=1 --bs=128k \
    --rw=write --iodepth=32 --size=4G --numjobs=1 \
    --runtime=60 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json
```

**What to read in the JSON output:**

```json
{
  "jobs": [{
    "read": {
      "bw_bytes": 1750663680,
      "iops": 13360,
      "clat_ns": {
        "p50": 2324480,
        "p99": 5879808,
        "p99.9": 13238272
      }
    }
  }]
}
```

- `bw_bytes` — Throughput in bytes/sec (divide by 1024³ for GB/s)
- `iops` — I/O operations per second
- `clat_ns` — Completion latency percentiles in nanoseconds

For an NVMe drive on PCIe 3.0 x4, expect 1.5–3.5 GB/s sequential
read. For a SATA SSD, 450–550 MB/s. For a single spinning disk,
150–250 MB/s.

### Random 4K IOPS (The Database Workload)

Databases (PostgreSQL, MariaDB) and ZFS do random 4K reads and
writes. This is the test that separates good storage from great
storage:

```bash
# Random 4K read (QD32, 60 seconds)
fio --name=rand-read --ioengine=libaio --direct=1 --bs=4k \
    --rw=randread --iodepth=32 --size=4G --numjobs=1 \
    --runtime=60 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json

# Random 4K write
fio --name=rand-write --ioengine=libaio --direct=1 --bs=4k \
    --rw=randwrite --iodepth=32 --size=4G --numjobs=1 \
    --runtime=60 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json

# Mixed 70/30 read/write (realistic database load)
fio --name=rand-mixed --ioengine=libaio --direct=1 --bs=4k \
    --rw=randrw --rwmixread=70 --iodepth=32 --size=4G \
    --numjobs=1 --runtime=60 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json
```

**Reference numbers for 4K random read (QD32):**

| Drive Type | IOPS | Latency (p50) |
|---|---|---|
| Enterprise NVMe (Optane/P5800X) | 800K–1M+ | < 20 µs |
| Consumer NVMe (Samsung 990 Pro) | 400K–800K | 50–80 µs |
| SATA SSD (Samsung 870 EVO) | 80K–100K | 150–300 µs |
| SD Card / USB Flash | 2K–5K | 2–10 ms |
| Spinning HDD (single) | 100–200 | 8–15 ms |
| RAID 10 (4× HDD) | 400–800 | 5–10 ms |

If your Docker PostgreSQL container sits on a single 7200 RPM
drive and gets 150 4K random write IOPS, every `INSERT` statement
takes 6–10 ms. That's why your web app feels slow.

### Multi-Job Workload (Simulate Real Load)

Single-job benchmarks are optimistic. Real homelabs have multiple
VMs, containers, and backups contending for the same disk:

```bash
fio --name=multi-job --ioengine=libaio --direct=1 --bs=4k \
    --rw=randrw --rwmixread=70 --iodepth=8 --size=2G \
    --numjobs=4 --runtime=120 --time_based --group_reporting \
    --filename=/tmp/fio-test --output-format=json
```

With `--numjobs=4`, four processes hammer the disk simultaneously.
The resulting IOPS and latency numbers are closer to what you see
during peak homelab usage. If 4K read latency jumps from 80 µs
(single job) to 5 ms (4 jobs), your disk can't handle concurrent
container workloads.

---

## Ioping — Latency in Microseconds

Ioping measures storage latency with sub-millisecond precision.
It's the fastest way to tell if an NFS mount or Docker volume
has high latency:

```bash
# Ping the local filesystem (10 requests)
ioping -c 10 /

# Ping with 4K requests (matching database block size)
ioping -c 20 -s 4K /

# Ping an NFS mount
ioping -c 20 -s 4K /mnt/nfs-backups

# Ping a Docker volume (from host)
ioping -c 20 -s 4K /var/lib/docker/volumes/postgres-data/_data
```

**Typical output:**

```
4 KiB <<< /mnt/nfs-backups >>>: request=1 time=342.9 us (warmup)
4 KiB <<< /mnt/nfs-backups >>>: request=2 time=287.1 us
...
--- /mnt/nfs-backups (nfs) statistics ---
20 requests completed in 19.0 s, 80 KiB read, 1.05 iops, 4.21 KiB/s
generated 20 requests in 19.1 s, 80 KiB, 1.05 iops, 4.18 KiB/s
min/avg/max/mdev = 287.1 us / 951.8 us / 3.45 ms / 944.4 us
```

**What's acceptable:**

| Storage Tier | 4K Latency (avg) | Verdict |
|---|---|---|
| Local NVMe | 20–100 µs | Excellent |
| Local SATA SSD | 100–500 µs | Good |
| NFS over 1 GbE (SSD backed) | 200–800 µs | Acceptable |
| NFS over 1 GbE (HDD backed) | 2–10 ms | Slow |
| CIFS/SMB share | 1–5 ms | Marginal |
| Remote cloud storage | 10–50 ms | Backup only |

If your Docker Compose stack stores databases on an NFS mount
with 3 ms latency, expect slow queries and frequent timeouts
under load. Move database volumes to local storage and use NFS
only for bulk media and backups.

---

## Benchmarking ZFS Pools

ZFS adds ARC (adaptive replacement cache), ZIL (ZFS intent log),
and compression — all of which affect benchmark results. Always
test with `direct=1` and also with the pool's real workload:

```bash
# Create a test dataset (no compression for baseline)
zfs create -o compression=off -o mountpoint=/mnt/zfstest tank/bench

# Test with ARC warm (run twice, read the second result)
fio --name=zfs-bench --ioengine=libaio --direct=1 --bs=4k \
    --rw=randread --iodepth=32 --size=8G \
    --runtime=60 --time_based --group_reporting \
    --filename=/mnt/zfstest/fio-test --output-format=json

# Test with compression + recordsize=1M (media storage)
zfs set compression=lz4 tank/media
zfs set recordsize=1M tank/media

fio --name=zfs-media --ioengine=libaio --direct=1 --bs=1M \
    --rw=read --iodepth=16 --size=8G \
    --runtime=60 --time_based --group_reporting \
    --filename=/tank/media/fio-test --output-format=json

# Clean up
zfs destroy tank/bench
rm -f /tank/media/fio-test
```

**ZFS key metrics to watch:**

- Write IOPS with sync=always (default) — ZFS writes via ZIL. For
  database workloads on spinning disks, sync writes can be 10x
  slower than async writes. Adding a dedicated log device (SLOG)
  on an NVMe dramatically improves sync write performance.

  ```bash
  zfs get sync tank/data
  zfs set sync=standard tank/data  # default, safest
  ```

- ARC hit rate — Run `arc_summary` or check `/proc/spl/kstat/zfs/arcstats`
  after a benchmark. If ARC hit rate is below 80%, add more RAM.

  ```bash
  grep "hit_rate\|size" /proc/spl/kstat/zfs/arcstats
  ```

- Compression ratio — `zfs get compressratio tank/data`. If the
  dataset stores media files, lz4 compression adds almost no CPU
  overhead (1–3%) and often reduces storage by 10–40%.

---

## Benchmarking NFS Mounts

NFS performance depends on network latency, server-side disk
speed, and mount options. Test from the client:

```bash
# Create test files on the NFS server side first (prevents
# client-side caching from distorting results)
ssh nas-server "dd if=/dev/zero of=/volume1/nfs-test bs=1M count=4096"

# Benchmark from the client
fio --name=nfs-bench --ioengine=libaio --direct=1 --bs=1M \
    --rw=read --iodepth=16 --size=4G \
    --runtime=30 --time_based --group_reporting \
    --filename=/mnt/nfs/nfs-test --output-format=json

# Test with small blocks (simulates metadata access)
fio --name=nfs-small --ioengine=psync --direct=0 --bs=4k \
    --rw=randread --iodepth=4 --size=512M \
    --runtime=30 --time_based --group_reporting \
    --filename=/mnt/nfs/nfs-test --output-format=json
```

Note `--ioengine=psync` for small-block NFS tests — libaio has
limited support for network filesystems. Psync is slower but more
accurate for NFS.

**NFS mount options that matter for performance:**

```bash
# Media server (large files, throughput-oriented)
sudo mount -t nfs -o rw,hard,intr,rsize=1048576,wsize=1048576 \
  nas-server:/volume1/media /mnt/nfs

# Backup target (mixed sizes, prioritize throughput over latency)
sudo mount -t nfs -o rw,hard,intr,noatime,nodiratime,rsize=65536,wsize=65536 \
  nas-server:/volume1/backups /mnt/nfs-backups
```

- `rsize/wsize=1048576` — Maximum NFS read/write buffer size (1 MB).
  Default is often 65536 (64 KB) — increasing this improves
  sequential throughput by reducing protocol overhead.
- `noatime/nodiratime` — Skips inode access time updates on reads.
  Critical for NFS performance on mail servers and media libraries.

After testing, check NFS statistics:

```bash
cat /proc/net/rpc/nfsd/proc_stats
nfsstat -c
```

A high ratio of `READ` calls to `READLINK` (metadata) calls
indicates the workload is dominated by bulk data access, not
file metadata scanning. If `READLINK` is high on a media serving
NFS mount, consider caching directory listings locally.

---

## Benchmarking Docker Volumes

Docker volumes add an abstraction layer — overlay2 filesystem,
storage drivers, and potential kernel bottlenecks. Always test
inside a container and on the host for comparison:

```bash
# Host-native baseline
fio --name=host-4k --ioengine=libaio --direct=1 --bs=4k \
    --rw=randread --iodepth=32 --size=2G --runtime=30 \
    --time_based --group_reporting --filename=/tmp/host-fio-test \
    --output-format=json

# Create a Docker volume and test inside a container
docker volume create bench-vol

docker run --rm -v bench-vol:/data ubuntu:24.04 bash -c \
  'apt update && apt install -y -qq fio && \
   fio --name=vol-4k --ioengine=libaio --direct=1 --bs=4k \
       --rw=randread --iodepth=32 --size=2G --runtime=30 \
       --time_based --group_reporting --filename=/data/fio-test \
       --output-format=json'

# Test with bind mount (bypasses volume driver)
docker run --rm -v /tmp:/data ubuntu:24.04 bash -c \
  'apt update && apt install -y -qq fio && \
   fio --name=bind-4k --ioengine=libaio --direct=1 --bs=4k \
       --rw=randread --iodepth=32 --size=2G --runtime=30 \
       --time_based --group_reporting --filename=/data/bind-fio-test \
       --output-format=json'

# Clean up
docker volume rm bench-vol
```

**What to look for:** Docker volume performance should match
within 5–10% of the host baseline for `--storage-driver=overlay2`
(default on modern Docker). If the volume is significantly slower:

- Check if the volume is on an NFS or remote mount
- Verify the storage driver: `docker info | grep Storage`
- Check if disk is nearly full (>90% used, btrfs/zfs behavior changes
  under high utilization)

For production database containers, always use bind mounts or
explicitly pinned local volumes — generic named volumes on slow
backing storage are the #1 cause of "Docker is slow" complaints
that are actually "my disk is slow" complaints.

---

## Repeatable Test Script

Save this as `~/bin/homelab-bench.sh` for a consistent baseline
you can run after hardware changes, ZFS tuning, or kernel updates:

```bash
#!/bin/bash
# homelab-bench.sh — Repeatable storage benchmark suite
# Run as root for best results (bypasses cgroup limits)
set -euo pipefail

TARGET="${1:-/tmp}"
RESULTS="${2:-/root/storage-bench-$(hostname)-$(date +%Y%m%d).json}"

echo "=== Homelab Storage Benchmark ==="
echo "Target: $TARGET"
echo "Results: $RESULTS"
echo ""

# Sequential throughput
for rw in read write; do
  echo "Sequential $rw (128K, QD32)..."
  fio --name="seq-${rw}" --ioengine=libaio --direct=1 \
      --bs=128k --rw="${rw}" --iodepth=32 --size=4G \
      --runtime=60 --time_based --numjobs=1 \
      --group_reporting --filename="${TARGET}/fio-bench" \
      --output-format=json >> "$RESULTS"
done

# Random 4K
for rw in randread randwrite; do
  echo "Random $rw (4K, QD32)..."
  fio --name="rand-${rw}" --ioengine=libaio --direct=1 \
      --bs=4k --rw="${rw}" --iodepth=32 --size=4G \
      --runtime=60 --time_based --numjobs=1 \
      --group_reporting --filename="${TARGET}/fio-bench" \
      --output-format=json >> "$RESULTS"
done

# Multi-job mixed workload
echo "Multi-job mixed 70/30 (4K, QD8, 4 jobs)..."
fio --name=multi-mixed --ioengine=libaio --direct=1 \
    --bs=4k --rw=randrw --rwmixread=70 --iodepth=8 \
    --size=2G --runtime=120 --time_based --numjobs=4 \
    --group_reporting --filename="${TARGET}/fio-bench" \
    --output-format=json >> "$RESULTS"

# Latency
echo "Latency check (ioping)..."
ioping -c 20 -s 4K "$TARGET" >> "$RESULTS"

echo ""
echo "Benchmark complete. Results: $RESULTS"
```

Make it executable and create a baseline:

```bash
chmod +x ~/bin/homelab-bench.sh
sudo ~/bin/homelab-bench.sh /mnt/zfs-pool \
  ~/baselines/after-zfs-tuning.json
```

Re-run after any hardware or configuration change and diff the
results with `jq`:

```bash
# Compare 4K random read IOPS between two baselines
jq '[.jobs[] | select(.jobname == "rand-randread") | .read.iops]' \
  after-zfs-tuning.json after-kernel-update.json
```

---

## Interpreting Results for Real Workloads

Benchmark numbers don't matter in isolation. Map them to your
actual homelab workloads:

| Workload | Relevant Test | Target |
|---|---|---|
| Docker PostgreSQL | 4K random write IOPS | >10K IOPS per container |
| Plex/Jellyfin transcoding | Sequential read throughput | >200 MB/s per concurrent stream |
| ZFS backup pool (restic) | Sequential write throughput | >400 MB/s |
| NFS media share | Sequential read (1M block) | >800 Mb/s (100 MB/s) on 1 GbE |
| Immich photo library | 4K mixed 70/30 read/write | >5K IOPS with <2 ms latency |
| Git server (Gitea) | 4K random read latency | <200 µs p50 |

**When to upgrade:**

- 4K random read latency >2 ms on your Docker volume → move to SSD
- Sequential throughput <100 MB/s on NFS → check link speed and
  mount options before upgrading hardware
- Multi-job IOPS drop >50% from single-job → disk contention issue;
  consider separating workloads across physical drives or adding
  a faster caching tier (ZFS special device or L2ARC)
- Ioping latency >1 ms on local SSD → check for TRIM support and
  filesystem fragmentation

Run this benchmark suite quarterly. Post the results somewhere
accessible — a Markdown file in your Gitea or a pinned note in
your dashboard. When something breaks six months from now, you'll
know exactly what performance looked like before the problem
started.
