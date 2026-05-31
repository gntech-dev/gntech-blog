---
title: "Proxmox VM Disk Performance — virtio-blk, iothreads, cache modes, and async IO"
description: "Optimize Proxmox VM disk performance with virtio-blk vs virtio-scsi, iothread pinning, cache mode selection, and async IO tuning for ZFS and NVMe storage. Real configuration examples included."
date: 2026-05-31T07:30:00-04:00
tags:
  - proxmox
  - virtualization
  - linux
  - homelab
  - storage
keywords:
  - Proxmox VM disk performance optimization virtio-blk virtio-scsi configuration
  - Proxmox iothread pinning multi-queue disk IO performance
  - Proxmox VM disk cache mode none writeback writethrough comparison
  - Proxmox virtio-scsi block device queue depth async IO tuning
  - Proxmox ZFS thick provisioning thin provisioning disk performance
  - Proxmox KVM disk discard trim NVMe SSD pass-through
  - Proxmox VM disk benchmark fio iodepth direct IO QEMU
summary: "A practical guide to tuning Proxmox VM disk performance — covering virtio disk controller selection, iothread pinning, cache modes, discard/trim, and async IO settings for maximum throughput on ZFS and NVMe storage."
canonical: "https://blog.gntech.me/posts/proxmox-vm-disk-performance-optimization/"
---

Your Proxmox host has NVMe SSDs, a ZFS pool tuned to the gills, and plenty of RAM. But your VMs still feel sluggish under disk-heavy workloads — database commits take too long, file transfers stall, and `iowait` climbs uncomfortably high.

The default Proxmox VM configuration is safe but leaves significant performance on the table. A few targeted tweaks to the disk controller, iothread configuration, cache settings, and async IO engine can double or triple your VM's disk throughput without spending a cent on hardware.

This guide walks through each tuning knob in order of impact: controller selection → iothreads → cache mode → discard/trim → async IO → benchmarking. Apply the ones that match your storage layout, measure results, and keep what works.

## Choosing the Right Disk Controller — virtio-blk vs virtio-scsi

Proxmox offers two virtio-based disk controller families for Linux guests. The choice directly affects queue depth, parallelism, and overall throughput.

**virtio-blk** is the simpler option. It is baked into the Linux kernel since 2.6.24, requires zero extra drivers, and introduces minimal overhead. By default it exposes a single I/O queue. That single queue limits parallelism when multiple processes or threads hit the disk simultaneously. Starting with QEMU 6.0 and Proxmox 8, virtio-blk supports multi-queue via the `num-queues` property, which matches the number of vCPUs assigned to the VM.

**virtio-scsi** is the more modern choice. It supports multiple I/O queues out of the box, a default queue depth of 256 (versus 128 for virtio-blk), and better integration with SCSI-3 persistent reservations. The `virtio-scsi-single` controller model creates one IOThread per disk — ideal for workloads with concurrent access patterns.

**When to use each:**

| Criterion | virtio-blk | virtio-scsi |
|---|---|---|
| Overhead | Lowest | Very low |
| Default queue depth | 128 | 256 |
| Multi-queue | Manual (`num-queues=N`) | Built-in |
| Best for | Single-process, low-concurrency workloads | Databases, file servers, multi-threaded apps |
| Pass-through features | Limited | Full SCSI support, TRIM pass-through |

For most homelab VMs running Docker, databases, or file storage, virtio-scsi-single is the better default. For minimal-overhead single-user VMs (e.g., a build runner), virtio-blk with multi-queue is fine.

```shell
# Switch to virtio-scsi-single controller
qm set <VMID> --scsihw virtio-scsi-single

# Attach a disk to the scsi controller
qm set <VMID> --scsi0 <storage>:32,iothread=1

# Or keep virtio-blk with multi-queue (num-queues = number of vCPUs)
qm set <VMID> --virtio0 <storage>:32,iothread=1
# Enable multi-queue via the VM config file
echo 'args: -device virtio-blk-pci,drive=drive-virtio0,iothread=iothread-virtio0,num-queues=4' >> /etc/pve/nodes/<node>/qemu-server/<VMID>.conf
```

Check your current controller with:

```shell
qm config <VMID> | grep -E '(scsihw|virtio|scsi)'
```

## IOThreads — Dedicated I/O Processing Pins

By default, QEMU handles disk I/O on the main vCPU thread pool. When a heavy write operation blocks, it steals cycles from the guest's compute. IOThreads carve out dedicated threads for I/O processing, isolating storage latency from CPU-bound workloads.

Enable iothreads per disk:

```shell
qm set <VMID> --virtio0 iothread=1
```

Then verify the iothread is running on the host:

```shell
ps aux | grep iothread
```

For maximum benefit, pin iothreads to physical cores that are not shared with vCPUs. On a 6-core Proxmox host, a sensible layout reserves cores 4-5 for iothreads:

Edit `/etc/pve/nodes/<node>/qemu-server/<VMID>.conf` and add after the iothread lines:

```
cpuunits: 1024
cpulimit: 4
affinity: 0-3
```

Then pin iothread processes via `taskset`:

```shell
# Find iothread PIDs
ps -eo pid,comm | grep iothread

# Pin to cores 4-5
taskset -cp 4-5 <PID>
```

Or use a systemd service or crontab @reboot script for persistence. In Proxmox 8.1+, CPU pinning for iothreads can also be set through the GUI under the VM's hardware options.

## Disk Cache Mode Comparison

The disk cache mode controls how QEMU interacts with the host page cache and how it reports write completion to the guest. Proxmox offers five modes — in a homelab with ZFS, only two matter:

**cache=none** — the Proxmox default since version 2.x. QEMU opens the disk with `O_DIRECT`, bypassing the host page cache entirely. The guest sees a writeback cache (so it sends flushes when needed), and ZFS handles all caching through its ARC. This avoids double-caching and is the recommended mode when the backing storage is ZFS.

**cache=writeback** — data lands in the host page cache before being written to disk. Writes complete faster from the guest's perspective, but the host page cache adds another layer. On hardware RAID with battery-backed write cache (BBU), this is fine. On ZFS without a UPS, a power loss can lose data sitting in the host page cache.

**ZFS recommendation:** Use `cache=none`. ZFS ARC already caches frequently accessed data in RAM. Adding the host page cache on top wastes memory that ARC could put to better use.

```shell
# Set cache mode per disk
qm set <VMID> --virtio0 cache=none

# For NVMe without ZFS:
qm set <VMID> --virtio0 cache=writeback
```

## Enabling Discard / TRIM for Thin-Provisioned Storage

If you use thin provisioning on ZFS datasets or qcow2 images, discarded blocks in the guest should be forwarded to the host so ZFS can reclaim space. Without discard, deleted files inside the VM leave allocated blocks on the host forever.

Enable discard on the Proxmox disk:

```shell
qm set <VMID> --virtio0 discard=on
```

Inside the guest (Linux), run an immediate trim and enable the periodic timer:

```shell
fstrim -av
systemctl enable fstrim.timer --now
```

For Debian/Ubuntu guests, the `fstrim.timer` runs weekly by default. On Proxmox hosts using ZFS, verify that discard is freeing space:

```shell
zpool get freeing rpool
```

A non-zero `freeing` value means blocks are actively being reclaimed.

## Async I/O Engine Selection — threads vs native

QEMU can dispatch disk I/O using two engines:

- **threads** (default) — spawns a POSIX thread per I/O request. Simple and compatible with all storage backends, but context-switching overhead shows at high IOPS.
- **native** — uses Linux kernel AIO (`io_submit`/`io_getevents`). Lower overhead per I/O, better for high-queue-depth workloads.

Switch to native AIO on ZFS or raw block devices:

```shell
qm set <VMID> --virtio0 aio=native
```

**Caveat:** Some older Linux kernels (pre-5.4) and Ceph RBD backends have issues with `aio=native`. If your host kernel is 5.15+ (standard on Proxmox 8.x and 9.x), native AIO is safe and recommended.

## Benchmarking Disk Performance — fio and qemu-img

Never apply tuning blindly. Measure before and after with real workloads.

**Inside the guest** — fio is the standard benchmark tool:

```shell
# Install fio on Debian/Ubuntu guest
apt install fio

# 4K random read/write — simulates database IO
fio --name=rand --ioengine=libaio --iodepth=32 --rw=randrw \
    --bs=4k --direct=1 --size=1G --numjobs=4 \
    --group_reporting --runtime=60 --time_based

# Sequential throughput test
fio --name=seq --ioengine=libaio --iodepth=64 --rw=read \
    --bs=1M --direct=1 --size=4G --numjobs=2 \
    --group_reporting --runtime=30 --time_based
```

**On the host** — benchmark the raw block device through QEMU's block layer:

```shell
# QEMU built-in benchmark
qemu-img bench -c 1024 -d 64 -p -f raw /dev/zvol/rpool/data/vm-<VMID>-disk-0
```

Key metrics to track:
- **4K random IOPS** — the single best indicator of real-world VM performance
- **99th percentile latency** — matters more than average for databases
- **Sequential throughput** — important for file transfers and backups

A tuned VM on consumer NVMe (e.g., Samsung 990 Pro) through Proxmox with ZFS should hit 150k-200k+ random read IOPS with sub-millisecond p99 latency.

## Putting It All Together

For a production homelab VM on ZFS-backed storage, here is the complete tuning command:

```shell
qm set <VMID> \
  --scsihw virtio-scsi-single \
  --scsi0 local-zfs:32,iothread=1,cache=none,discard=on,aio=native
```

| Setting | ZFS (recommended) | Raw NVMe | Ceph/RBD |
|---|---|---|---|
| Controller | virtio-scsi-single | virtio-blk (multi-queue) | virtio-scsi-single |
| Cache mode | none | writeback | none |
| IOThread | yes | yes | yes |
| Discard | on | on | off |
| aio | native | native | threads |

Test each change independently on your actual workloads. Storage topology, CPU count, and RAM all interact with these settings. There is no universal "fastest" config — only the best config for *your* specific workload on *your* specific hardware.

For deeper reading, see the [Proxmox VE Performance Tweaks Wiki](https://pve.proxmox.com/wiki/Performance_Tweaks) and the QEMU block layer documentation.
