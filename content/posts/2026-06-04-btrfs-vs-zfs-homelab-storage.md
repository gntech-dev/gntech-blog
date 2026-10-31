---
title: "Btrfs vs ZFS for Homelab Storage — Proxmox and Docker Guide"
description: "Compare filesystem support, checksums, memory, Docker storage, expansion and recovery using the versions and workloads actually deployed."
date: 2026-06-04T14:30:00-04:00
lastmod: 2026-10-31
draft: false
tags: [storage, linux, homelab, proxmox, docker]
keywords: [Btrfs vs ZFS homelab, Proxmox filesystem choice, Docker storage backend, filesystem recovery]
summary: "Choose a supported storage design from workload and recovery requirements rather than blanket filesystem rankings."
---

Btrfs and OpenZFS both offer checksums, snapshots and compression, but that does not make them interchangeable. The host distribution, storage layout, kernel, management tools and recovery procedure matter as much as the filesystem name.

There is no universal rule to use ZFS for every hypervisor and Btrfs for every Docker volume. Start with the platform's supported configuration and a tested recovery workflow.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official references below reviewed on October 31, 2026. |
| Examples | Read-only inventory commands; Bash syntax checked. |
| Runtime | No filesystem creation, migration, expansion, benchmark, quota or recovery test executed. |
| Recommendation scope | Decision framework, not measured performance or a promise of support across releases. |

## 1. Record the installed stack

Run applicable commands on the host that owns the storage. A guest's filesystem does not identify the hypervisor's backing pool.

```bash
uname -r
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
```

On a PVE host with ZFS:

```bash
pveversion -v
zfs --version
zpool status
zfs list -o name,type,used,available,mountpoint
```

On a Btrfs host, inspect the actual mount:

```bash
btrfs version
read -r -p 'Existing Btrfs mount path: ' btrfs_mount
sudo btrfs filesystem show "$btrfs_mount"
sudo btrfs filesystem usage "$btrfs_mount"
```

Btrfs user-space tools and kernel implementation have separate versions. OpenZFS is maintained outside the mainline Linux kernel, but packaging varies: do not assume every PVE kernel upgrade performs a local DKMS rebuild. Use the distribution's supported kernel/module packages.

## 2. Compare operational requirements

| Question | OpenZFS | Btrfs |
|---|---|---|
| Storage organization | Pools, vdevs, filesystems and zvols | Filesystems, devices and subvolumes |
| Snapshot scope | Dataset or zvol | Subvolume |
| Cache model | ARC plus other system memory consumers | Linux page-cache-based operation |
| Repair opportunity | Requires an available correct copy or recoverable redundancy | Requires an available correct copy or recoverable redundancy |
| Capacity changes | Depend on topology, features and version | Depend on allocation profiles, free space and version |
| Docker suitability | Check the actual image store and mounted data paths | Check the actual image store and mounted data paths |

A checksum can detect damage without being able to repair it. Neither a snapshot on the same storage nor a redundant layout is an independent backup.

Btrfs profiles have different support status. The upstream [feature-status table](https://btrfs.readthedocs.io/en/latest/Status.html) currently marks RAID56 unstable. Do not treat all Btrfs RAID profiles as equivalent or infer your older kernel's support from the newest table.

## 3. Check platform support before choosing

PVE documents both ZFS and a Btrfs storage backend. The earlier statement that Btrfs has no platform integration was too broad. Read the documentation matching the installed release, including feature limitations and installer support.

The [PVE Btrfs backend](https://github.com/proxmox/pve-docs/blob/master/pve-storage-btrfs.adoc) describes how raw guest disks use subvolumes for snapshot support. That is different from placing a Btrfs filesystem inside a guest.

For a PVE deployment, evaluate the [PVE ZFS guidance](https://github.com/proxmox/pve-docs/blob/master/local-zfs.adoc), required guest-storage features, maintenance support and available recovery skills. PBS backups do not require choosing ZFS for every source guest or host filesystem.

For Docker, choose a deployment boundary you can support. A VM provides its own kernel and filesystem stack; an LXC shares the host kernel and introduces nesting and permission constraints. Do not infer a supported Docker layout merely from the outer host's filesystem.

## 4. Separate Docker image storage from application data

On the Docker host:

```bash
docker version
docker info
```

Record the active storage backend and backing filesystem. New Docker Engine 29 installations use the containerd image store by default; upgraded installations can retain classic storage drivers. Consult [Docker storage selection](https://docs.docker.com/engine/storage/drivers/select-storage-driver/).

The classic native Btrfs driver uses subvolumes and snapshots. It is not the same implementation as overlay2. Neither Btrfs nor ZFS alone proves that a particular overlay or snapshotter combination is supported. See the [Btrfs driver documentation](https://docs.docker.com/engine/storage/drivers/btrfs-driver/).

Named volumes and bind mounts are separate from a container's writable layer. Evaluate application data on its actual backing storage, not from an image-layer benchmark. Do not change Docker's storage configuration on a populated host without a migration and rollback plan.

## 5. Measure memory and compression

ARC's maximum is a cache limit, not a fixed allocation reserved before guests start. Defaults and distribution tuning vary. Observe memory pressure, guest demand and ARC behavior before setting a smaller limit; an arbitrary 2 GiB cap is not a universal improvement.

Btrfs also uses memory for caches and filesystem work. Neither filesystem has a single RAM threshold that predicts performance for every workload.

Compression consumes CPU and saves space only where the data is compressible. Check actual properties, files and measured workload behavior. Do not promise a fixed percentage gain or call compression free.

Btrfs compression options affect file extents; a defragment/recompress operation rewrites existing data and can unshare extents. It is not a harmless way to toggle a subvolume setting. See [Btrfs compression](https://btrfs.readthedocs.io/en/latest/Compression.html) and [filesystem operations](https://btrfs.readthedocs.io/en/latest/btrfs-filesystem.html).

## 6. Plan expansion and quotas by feature

The old claim that ZFS can never add a disk to an existing vdev is incorrect. On supporting versions, [zpool attach](https://openzfs.github.io/openzfs-docs/man/master/8/zpool-attach.8.html) can add a mirror member or expand a RAID-Z group. RAID-Z expansion does not increase its parity level. Check installed features, topology, capacity behavior and recovery implications first.

Btrfs device addition and removal are also constrained operations. Removal needs enough space and readable or reconstructable data; it is not a guarantee that arbitrary disks can be removed safely.

For quotas, select documented ZFS dataset/user limits or Btrfs quota mechanisms and test snapshot accounting. Do not apply ext4/XFS project-quota mount advice to Btrfs as a substitute for its own quota documentation.

This comparison intentionally includes no pool creation, formatting, balancing, device removal or live cache-tuning commands.

## 7. Decide from recovery evidence

| Need | Practical next step |
|---|---|
| PVE-managed guest storage | Compare release-specific backend features and support first. |
| Docker application persistence | Test the actual mounted path and application's consistency requirements. |
| Frequent disk-layout changes | Model permitted operations, free-space needs and rebuild exposure. |
| Strict data protection | Test checks, alerts, independent copies and recovery on replacement hardware. |
| Performance problem | Benchmark a controlled workload before changing filesystem or hardware. |

Document the selected versions, topology, included data, maintenance procedures and recovery credentials. Test an isolated restore before moving important services. Snapshot send/receive is a transfer mechanism, not proof that a complete application can be recovered.

## Continue reading

- [Storage benchmarking](/posts/2026-05-23-linux-storage-benchmarking/) — Record a bounded baseline.
- [ZFS snapshots and recovery](/posts/2026-05-08-zfs-snapshot-strategies/) — Separate dataset recovery from guest backups.
- [Backup strategy](/posts/2026-05-23-proxmox-backup-strategies/) — Plan independent copies and recovery targets.
