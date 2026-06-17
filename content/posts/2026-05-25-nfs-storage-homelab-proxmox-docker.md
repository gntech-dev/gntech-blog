---
title: "NFS Shared Storage — Centralized Homelab with Proxmox and Docker"
description: "Deploy centralized NFS shared storage in your homelab — from server setup on Ubuntu/Debian to Proxmox NFS storage, Docker volume mounts, LXC bind mounts, and performance tuning for 1GbE and 10GbE networks."
date: 2026-05-25T12:00:00-04:00
tags:
  - storage
  - linux
  - docker
  - proxmox
  - networking
keywords:
  - NFS shared storage homelab Proxmox Docker
  - NFS server setup Ubuntu Debian homelab
  - Docker NFS volume mount configuration
  - Proxmox NFS storage add datastore
  - NFS performance tuning 1GbE 10GbE
  - NFS LXC bind mount unprivileged container
  - centralized homelab storage NFS export
summary: "Set up centralized NFS shared storage for your Proxmox homelab with Docker volume mounts, LXC bind mounts, and performance tuning — practical configs for backup storage, media libraries, and container data."
canonical: "https://gntech.dev/posts/nfs-storage-homelab-proxmox-docker/"
---

A homelab with three Proxmox nodes, a dozen LXC containers, and
fifty Docker services quickly outgrows local storage. Backups scatter
across machines. Media libraries duplicate. Container volumes pin
data to specific hosts, making migration painful.

NFS (Network File System) solves this. A single shared storage pool
accessible from every Proxmox host, every LXC container, and every
Docker container means your data lives in one place — and you only
need to back up one place.

This guide walks through deploying NFS shared storage from scratch:
server setup on Debian/Ubuntu, Proxmox storage integration, Docker
volume mounts, LXC bind mounts, and performance tuning for realistic
homelab networks.

---

## Why NFS Instead of Samba or iSCSI?

For a homelab storage backend, three protocols dominate:

| Protocol | Best For                         | Overhead       | Docker Support      | Proxmox Integration      |
|----------|----------------------------------|----------------|---------------------|--------------------------|
| **NFSv4** | Linux-to-Linux, concurrent reads | Low            | Native volume driver| First-class storage type |
| **SMB/CIFS**| Mixed OS (Windows clients)     | Moderate       | Requires CSI driver| Additional mount config  |
| **iSCSI** | Block-level VMs, databases       | Low (block)    | Not supported      | LVM/block storage only   |

In a Linux-only homelab running Proxmox and Docker, NFSv4 is the
natural choice — native kernel client, sub-millisecond latency on
modern networks, no additional software, and first-class support in
both Proxmox (`pvesm`) and Docker (volume `--driver local --type nfs`).

---

## Step 1: NFS Server Setup on Debian/Ubuntu

A minimal VM or LXC container with a large attached disk makes the
best NFS server in a Proxmox homelab. Dedicated hardware is better
for performance but unnecessary for most home labs.

### Install and Configure

```bash
# Install NFS server
apt update && apt install -y nfs-kernel-server

# Create export directory on your storage pool
mkdir -p /srv/nfs/backups
mkdir -p /srv/nfs/media
mkdir -p /srv/nfs/containers

# Set ownership for NFS user mapping
chown -R nobody:nogroup /srv/nfs
chmod 755 /srv/nfs
```

### Configure Exports

Edit `/etc/exports`:

```bash
# /etc/exports — NFS exports file

# Backups: restricted to Proxmox subnet, async for performance
/srv/nfs/backups   10.0.20.0/24(rw,sync,no_subtree_check,no_root_squash)

# Media: read-mostly, allow cross-subnet
/srv/nfs/media     10.0.0.0/16(rw,sync,no_subtree_check,no_root_squash)

# Containers: Docker/LXC data, async for write-heavy DBs
/srv/nfs/containers 10.0.20.0/24(rw,sync,no_subtree_check,no_root_squash)
```

**Export options explained:**

- `rw` — read-write access
- `sync` — writes acknowledged after disk commit (safer, slightly slower)
- `async` — writes acknowledged before disk commit (faster, minor crash risk)
- `no_subtree_check` — disables subtree checking, improves reliability
- `no_root_squash` — allows root on client to keep root privileges
  (required for Proxmox backups. For Docker/LXC, use `root_squash` for
  security and map UIDs instead)

### Apply and Verify

```bash
exportfs -ra
showmount -e localhost

# Output:
# Export list for localhost:
# /srv/nfs/backups    10.0.20.0/24
# /srv/nfs/media      10.0.0.0/16
# /srv/nfs/containers 10.0.20.0/24
```

Firewall rule if using UFW:

```bash
ufw allow from 10.0.0.0/16 to any port nfs
ufw reload
```

### Secure with NFSv4 Only

Modern NFSv4.2 is more secure than v3 — single protocol port, strong
auth, and Kerberos support. Disable v3 on the server:

```bash
# /etc/default/nfs-kernel-server
RPCNFSDCOUNT=8
RPCMOUNTDOPTS="--no-nfs-version 3"
```

Restart:

```bash
systemctl restart nfs-kernel-server
```

NFSv4 uses TCP port 2049. No more rpcbind portmap surprises.

---

## Step 2: Add NFS Storage to Proxmox

Proxmox supports NFS as a first-class storage backend. Adding an NFS
share makes it available for VM/CT backups, ISO templates, container
storage, and even live VM disks.

### Via Web UI

1. Navigate to **Datacenter → Storage → Add → NFS**
2. Fill in:
   - **ID:** `nfs-backups`
   - **Server:** `10.0.20.10` (your NFS server IP)
   - **Export:** `/srv/nfs/backups`
   - **Content:** `VZDump backup`, `ISO image`, `Container template`
3. Click **Add**

### Via CLI

```bash
pvesm add nfs nfs-backups \
  --server 10.0.20.10 \
  --export /srv/nfs/backups \
  --content backup,iso,vztmpl \
  --options vers=4.2,hard,timeo=600,retrans=3
```

### Verify

```bash
pvesm status
# Output:
# Name              Type     Status   Total     Used     Available   %
# nfs-backups       nfs      active   1904G     342G     1562G      18%

# Test a backup to NFS store
vzdump 100 --storage nfs-backups --mode snapshot
```

### Mount Options for Proxmox NFS

Add these to `/etc/pve/storage.cfg` under the NFS section:

```ini
nfs: nfs-backups
    path /mnt/pve/nfs-backups
    server 10.0.20.10
    export /srv/nfs/backups
    options vers=4.2,hard,intr,timeo=600,retrans=3,noatime
    content backup,iso,vztmpl
    maxfiles 7
```

- `hard` — retry indefinitely on server outage (preferred for backups;
  use `soft` for non-critical data)
- `intr` — allow interrupt of hung operations (Linux 5.x+, signals work
  with `hard` mounts)
- `timeo=600` — 60-second timeout before retry
- `retrans=3` — retry 3 times before major timeout
- `noatime` — skip access time updates, reduces NFS traffic

---

## Step 3: Mount NFS Shares in LXC Containers

LXC containers benefit from NFS for shared data that multiple
containers access — media libraries, download directories, shared
configurations.

### Bind Mount Inside a Privileged Container

On the Proxmox host, edit the container's config:

```bash
# /etc/pve/lxc/101.conf — add at the end
mp0: /srv/nfs/media,mp=/media
mp1: /srv/nfs/containers,mp=/data/containers
```

Then inside the container:

```bash
# Inside the LXC
mount -a  # or restart the container
df -h /media
# 10.0.20.10:/srv/nfs/media  2.0T  342G  1.6T  18%  /media
```

### For Unprivileged Containers (Best Practice)

Unprivileged containers require UID mapping so the container's root
maps to a non-root user on the host. Mount the NFS share on the
*Proxmox host* first, then bind-mount it into the container:

```bash
# On Proxmox host — add fstab entry
echo "10.0.20.10:/srv/nfs/containers /mnt/nfs-container nfs4 noauto,vers=4.2,hard,intr,noatime 0 0" >> /etc/fstab
mkdir -p /mnt/nfs-container
mount /mnt/nfs-container

# Bind mount into unprivileged LXC — /etc/pve/lxc/102.conf
mp0: /mnt/nfs-container,mp=/data
```

This avoids UID mapping issues because the mount happens at the kernel
level on the host, then is bind-mounted into the container's namespace.

---

## Step 4: Docker NFS Volume Mounts

Docker supports NFS natively through the `local` volume driver with
`type: nfs`. This is the cleanest way to share storage across Docker
hosts without any CSI plugins.

### In Docker Compose

```yaml
# docker-compose.yml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    volumes:
      - media-data:/media
      - jellyfin-config:/config
    ports:
      - "8096:8096"

volumes:
  media-data:
    driver: local
    driver_opts:
      type: nfs4
      o: "addr=10.0.20.10,nolock,soft,rw,vers=4.2,noatime"
      device: ":/srv/nfs/media"
  jellyfin-config:
    driver: local
    driver_opts:
      type: nfs4
      o: "addr=10.0.20.10,nolock,soft,rw,vers=4.2"
      device: ":/srv/nfs/containers/jellyfin"
```

### With Docker Run

```bash
docker volume create \
  --driver local \
  --opt type=nfs4 \
  --opt o=addr=10.0.20.10,nolock,soft,rw,vers=4.2,noatime \
  --opt device=:/srv/nfs/media \
  media-shared

docker run -d \
  --name jellyfin \
  -v media-shared:/media \
  jellyfin/jellyfin:latest
```

### NFS Volume Options for Docker

| Option            | Purpose                               | Recommended     |
|-------------------|---------------------------------------|-----------------|
| `nolock`          | Disable NFS locking (Docker doesn't support `lockd`) | Always set     |
| `soft`            | Report I/O error instead of hanging   | Docker volumes  |
| `vers=4.2`        | Use NFSv4.2 for best performance      | Always          |
| `noatime`         | Skip access time updates              | Media/read-only |
| `rsize=1048576`   | Read buffer size (1 MB)               | 1GbE+ networks  |
| `wsize=1048576`   | Write buffer size (1 MB)              | 1GbE+ networks  |

### Full Example: Jellyfin with NFS Media

```yaml
# /opt/jellyfin/docker-compose.yml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
    volumes:
      - type: volume
        source: media
        target: /media
        volume:
          nocopy: true
      - type: volume
        source: config
        target: /config
        volume:
          nocopy: true
    ports:
      - "8096:8096"
      - "8920:8920"
    restart: unless-stopped

volumes:
  media:
    driver: local
    driver_opts:
      type: nfs4
      o: "addr=10.0.20.10,nolock,soft,rw,vers=4.2,noatime"
      device: ":/srv/nfs/media"
  config:
    driver: local
    driver_opts:
      type: nfs4
      o: "addr=10.0.20.10,nolock,soft,rw,vers=4.2"
      device: ":/srv/nfs/containers/jellyfin"
```

---

## Step 5: NFS Performance Tuning

NFS performance in a homelab depends on three knobs: network, server
storage, and mount options.

### rsize/wsize — The Single Biggest Lever

NFS read and write buffer sizes default to 1 MB in modern kernels,
but older clients may negotiate smaller. Set them explicitly:

```bash
# /etc/fstab mount
10.0.20.10:/srv/nfs/media    /mnt/media   nfs4   rsize=1048576,wsize=1048576,noatime,nolock,vers=4.2   0 0
```

On 1GbE networks (125 MB/s theoretical), 1 MB buffers are optimal.
On 10GbE, increase to 2 MB:

```bash
rsize=2097152,wsize=2097152
```

### Server-Side Tuning

```ini
# /etc/sysctl.d/90-nfs.conf
# Increase NFS server thread count
# Default: 8 threads per CPU core — increase for many concurrent clients
# Formula: min(128, max(8, clients * 2)) for most workloads

# Network buffer tuning for NFS
net.core.rmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_default = 262144
net.core.wmem_max = 16777216

# Increase max NFS server threads (RPCNFSDCOUNT in defaults file)
```

Apply:

```bash
sysctl -p /etc/sysctl.d/90-nfs.conf
```

### NFS Server Thread Count

On the NFS server, each `nfsd` kernel thread handles one concurrent
request. For a homelab with fewer than 10 clients, 8 threads is
plenty. For 20+ concurrent services hitting the same server:

```bash
# /etc/default/nfs-kernel-server
RPCNFSDCOUNT=32
```

### Storage Backend Matters

The NFS server's disk subsystem is the actual bottleneck. ZFS with
ARC and L2ARC provides excellent NFS performance:

```bash
# ZFS tuning for NFS server
zfs set recordsize=1M pool/nfs-data
zfs set atime=off pool/nfs-data
zfs set compression=lz4 pool/nfs-data
zfs set xattr=sa pool/nfs-data
```

- `recordsize=1M` — matches NFS rsize, reduces fragmentation
- `atime=off` — eliminates access-time writes on every read
- `compression=lz4` — near-zero overhead compression

### Benchmarking NFS Performance

Before and after tuning, benchmark from a client:

```bash
# Sequential write test
dd if=/dev/zero of=/mnt/nfs/test bs=1M count=1000 conv=fdatasync

# Sequential read test
dd if=/mnt/nfs/test of=/dev/null bs=1M count=1000

# Fio random I/O test
apt install -y fio
fio --name=nfs-test --directory=/mnt/nfs --size=1G \
  --rw=randrw --bs=4K --iodepth=16 --numjobs=4 \
  --runtime=30 --time_based --group_reporting

# Quick network throughput test (between server and client)
# On server: iperf3 -s
# On client:
iperf3 -c 10.0.20.10 -t 30
```

Expected results on 1GbE:
- Sequential read: 110–118 MB/s (near wire speed)
- Sequential write: 100–112 MB/s (sync=slow, async=faster)
- 4K random read: 8,000–15,000 IOPS (depends on server storage)

If sequential throughput is below 80 MB/s on 1GbE, check:
1. Switch or cable negotiation (`ethtool eth0`)
2. NFS version negotiation (`mount | grep nfs` — confirm v4.2)
3. rsize/wsize values
4. Server disk utilization (`iostat -x 1`)

---

## Step 6: Backup Strategy for NFS Storage

Centralizing storage means you only need to back up one server.
NFS volumes are not a backup themselves — the server's disks can
fail too.

### Automated Snapshot with ZFS

If the NFS server runs on ZFS:

```bash
#!/bin/bash
# /usr/local/bin/nfs-snapshot.sh
# Run daily via systemd timer

DATASET="pool/nfs-data"
KEEP_DAILY=7
KEEP_WEEKLY=4

zfs snapshot "${DATASET}@nfs-$(date +%Y%m%d-%H%M)"

# Prune daily snapshots older than 7 days
zfs list -H -o name -t snapshot -r "${DATASET}" | \
  grep "nfs-" | \
  while read snap; do
    ts=$(echo "$snap" | grep -oP '\d{8}-\d{4}')
    if [[ $ts < $(date -d "7 days ago" +%Y%m%d-%H00) ]]; then
      zfs destroy "$snap"
    fi
  done
```

### Rsync to Off-Site

For critical data (Docker configs, databases), rsync from the NFS
server to an off-site destination:

```bash
#!/bin/bash
# /usr/local/bin/nfs-offsite-backup.sh
rsync -az --delete \
  --exclude 'downloads/' \
  --exclude 'cache/' \
  /srv/nfs/containers/ \
  user@offsite-backup.example.com:/backup/nfs-containers/
```

---

## Common Pitfalls and Solutions

### Permission Denied on Docker NFS Volumes

**Problem:** Container writes to NFS volume fail with "Permission denied".

**Fix:** Ensure UID/GID in the container matches the NFS server's file
ownership. NFS maps root (UID 0) to `nobody` by default unless you
enable `no_root_squash` on the export.

```bash
# On NFS server, set ownership for the service's UID
chown -R 1000:1000 /srv/nfs/containers/jellyfin
```

Then in the Docker compose service, set `PUID=1000 PGID=1000` matching
the server.

### LXC Container Can't Mount NFS

**Problem:** `mount.nfs: access denied` inside an unprivileged container.

**Fix:** Mount NFS on the Proxmox host, then bind-mount it into the
container via `mp0:` in the CT config. Unprivileged containers lack
the `CAP_SYS_ADMIN` needed for direct NFS mounts.

### NFS Volume Not Available at Docker Start

**Problem:** Container starts before the NFS server is reachable,
volume mount fails.

**Fix:** Add `restart: unless-stopped` to the compose service and
configure the Docker host to mount NFS volumes early:

```bash
# /etc/fstab — mount on boot so Docker always sees it
10.0.20.10:/srv/nfs/containers   /mnt/nfs-containers   nfs4   _netdev,noatime,nolock,vers=4.2   0 0
```

The `_netdev` option tells systemd to wait for networking before
mounting.

### Poor Write Performance with sync

**Problem:** Writes are slow (20 MB/s on 1GbE).

**Fix:** The export uses `sync` by default. Switch to `async` for
workloads where a tiny data loss window on crash is acceptable
(e.g., media libraries, download directories):

```bash
# /etc/exports
/srv/nfs/media  10.0.0.0/16(rw,async,no_subtree_check,no_root_squash)
```

For databases and critical data, keep `sync` and add a ZFS SLOG
device to absorb the synchronous write overhead.

---

## Full Reference: NFS Server Checklist

```bash
# ----- Server Setup -----
apt install nfs-kernel-server
mkdir -p /srv/nfs/{backups,media,containers}
chown nobody:nogroup /srv/nfs

# ----- Exports (/etc/exports) -----
/srv/nfs/backups    10.0.20.0/24(rw,sync,no_subtree_check,no_root_squash)
/srv/nfs/media      10.0.0.0/16(rw,async,no_subtree_check,no_root_squash)
/srv/nfs/containers 10.0.20.0/24(rw,sync,no_subtree_check,no_root_squash)

# ----- Apply -----
exportfs -ra
systemctl enable --now nfs-server
ufw allow from 10.0.0.0/16 to any port nfs

# ----- Client Mount Test -----
mount -t nfs4 -o vers=4.2,noatime,nolock 10.0.20.10:/srv/nfs/media /mnt/media
df -h /mnt/media

# ----- Docker Verify -----
docker volume create --driver local \
  --opt type=nfs4 \
  --opt o=addr=10.0.20.10,nolock,soft,rw,vers=4.2 \
  --opt device=:/srv/nfs/containers test-nfs
docker run --rm -v test-nfs:/data alpine ls -la /data

# ----- Performance Check -----
dd if=/dev/zero of=/mnt/media/test bs=1M count=1000 conv=fdatasync 2>&1 | tail -1
# Expect: >100 MB/s on 1GbE, >500 MB/s on 10GbE
```

---

## Summary

Centralized NFS shared storage transforms a multi-node homelab from
a collection of isolated machines into a unified cluster where data
flows freely between Proxmox, LXC containers, and Docker services:

1. **Start with a dedicated NFS server** — a simple Debian VM or LXC
   with a ZFS dataset provides all the performance most homelabs need.
2. **Use NFSv4.2 exclusively** — single port (TCP 2049), better
   performance, and simpler firewall rules than NFSv3.
3. **Add NFS storage to Proxmox** for unified VM/CT backup targets
   and ISO/CT template storage accessible from all nodes.
4. **Mount NFS on the Proxmox host** then bind-mount into unprivileged
   LXC containers to avoid UID mapping complexity.
5. **Use Docker's native NFS volume driver** with `driver_opts` for
   per-service NFS mounts — no CSI plugins required.
6. **Tune rsize/wsize for your network** — 1 MB for 1GbE, 2 MB for 10GbE.
7. **Benchmark before and after tuning** with `dd` and `fio` — if
   throughput is below 80% of wire speed, something is misconfigured.
8. **Back up the NFS server** — centralization concentrates risk.
   ZFS snapshots plus off-site rsync cover both local corruption
   and physical disaster.

A properly configured NFS setup is the backbone of a scalable
homelab. It takes an hour to stand up and saves you weeks of
scattered storage management over the life of your lab.
