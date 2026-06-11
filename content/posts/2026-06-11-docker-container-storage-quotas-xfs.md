---
title: "Docker Container Storage Quotas — Limit Disk Usage with XFS"
description: "Limit Docker container disk usage with XFS project quotas and overlay2 size options. Prevent runaway storage in your homelab with per-container and per-volume disk caps."
date: 2026-06-11T17:00:00-04:00
tags:
  - docker
  - homelab
  - storage
  - linux
  - devops
keywords:
  - Docker container storage quota XFS project quota homelab
  - Prevent Docker container filling disk space Linux
  - Docker overlay2 size limit per container configuration
  - XFS prjquota Docker daemon storage options setup
  - Docker storage-opt disk space limitation containers
  - Linux disk quota management Docker volumes bind mounts
  - Dockerd daemon.json overlay2.size storage cap configuration
summary: "Set up XFS project quotas and Docker overlay2 size limits to prevent any single container from filling your homelab storage. Covers daemon.json config, XFS prjquota, per-container size caps, and volume quota strategies."
canonical: "https://blog.gntech.me/posts/docker-container-storage-quotas-xfs/"
---

One container writes logs at an insane rate. A database import fills every available sector. A media scanner generates thumbnails until the disk shows zero bytes free. Your Proxmox host locks up. VMs freeze. SSH stops responding. You reboot and scramble to free space.

The root cause: Docker does not enforce disk limits by default. A single `docker run` with an over-ambitious application can consume your entire storage pool. This guide shows you how to prevent that with XFS project quotas and Docker's overlay2 size limit — no third-party tools required.

## How Overlay2 Storage Works and Where Quotas Fit

Docker defaults to the overlay2 storage driver on modern Linux systems. It uses a layered filesystem: each image layer is a read-only lower directory, and the container's writable layer is an upper directory mounted via overlayfs. All container writes land in `/var/lib/docker/overlay2/<container-id>/diff`.

The backing filesystem for `/var/lib/docker` matters. On ext4, overlay2 has no built-in per-container size limit. On XFS with project quotas enabled (`prjquota`), Docker can apply a global size cap per container through the `overlay2.size` storage option. Each container gets its own XFS project ID automatically, and Docker sets the quota at container creation time.

This is not virtual disk thin provisioning — it is a hard filesystem quota. When a container hits the limit, writes fail with `ENOSPC` (No space left on device) instead of exhausting the host disk.

## Checking Your Current Docker Backing Filesystem

Before making changes, verify your setup:

```bash
df -T /var/lib/docker
```

If the type column shows `xfs`, you are on XFS. If `ext4`, you can still use XFS project quotas on separate data mounts (see the volume section below), but the global `overlay2.size` option only works with XFS backing the Docker root.

```bash
# Check if XFS quotas are already enabled
mount | grep /var/lib/docker
```

Look for `prjquota` or `pquota` in the mount options. If missing you can either remount or (cleaner) set up a dedicated XFS partition.

## Preparing XFS with Project Quotas

If your Docker root is on ext4 or XFS without quotas, the cleanest approach is a dedicated partition. Assuming a spare disk or partition at `/dev/sdb1`:

```bash
# Format as XFS with project quota support baked in
mkfs.xfs /dev/sdb1

# Create mount point and add to fstab
mkdir -p /var/lib/docker
echo "/dev/sdb1 /var/lib/docker xfs defaults,noatime,prjquota 0 2" >> /etc/fstab

# Move existing data if any
systemctl stop docker
mv /var/lib/docker /var/lib/docker.old
mkdir -p /var/lib/docker
mount /var/lib/docker

# Copy existing data back
rsync -av /var/lib/docker.old/ /var/lib/docker/
rm -rf /var/lib/docker.old
systemctl start docker
```

Verify quotas are active:

```bash
xfs_quota -x -c 'state' /var/lib/docker
```

The output should show `Project quotas on` and `Enforcement ON`.

## Setting a Global Container Size Cap

With XFS project quotas active, add the `overlay2.size` storage option to Docker's daemon configuration:

```bash
cat > /etc/docker/daemon.json << 'EOF'
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.size=10G"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
```

The `10G` value is the hard limit per container — adjust based on your workload and available disk. A database container might need 20-50G. A simple web app might be fine with 2G.

Restart Docker and confirm:

```bash
systemctl restart docker
docker info | grep -A5 "Storage Driver"
```

Look for `Size: 10G` under the Storage Driver section. Now run a test:

```bash
docker run -d --name disk-test alpine sleep 3600
docker exec disk-test df -h /
```

The root filesystem inside the container will show the 10G size. Try to exceed it:

```bash
docker exec disk-test dd if=/dev/zero of=/fill bs=1M count=12000
```

The write will fail around the 10G mark instead of filling your host disk.

**Important:** The size cap is set at container creation time and covers the union filesystem (writable layer + image layers). If your image is 8G and the cap is 10G, the container only has 2G of writable space. Plan accordingly.

## Per-Container and Per-Service Volume Quotas with XFS

The overlay2.size is a global default — Docker does not support `--storage-opt size=` at `docker run` or compose level. For granular control per service, use XFS project quotas on bind-mounted data directories.

This is the pattern for databases, media libraries, and log-heavy containers:

```bash
# Create a directory structure for each service
mkdir -p /data/docker/postgres
mkdir -p /data/docker/jellyfin
mkdir -p /data/docker/prometheus

# Register XFS projects
cat >> /etc/projects << 'PROJ'
100:/data/docker/postgres
101:/data/docker/jellyfin
102:/data/docker/prometheus
PROJ

cat >> /etc/projid << 'PROJID'
postgres:100
jellyfin:101
prometheus:102
PROJID

# Apply hard limits (bhard) per project
xfs_quota -x -c 'limit -p bhard=20G postgres' /data
xfs_quota -x -c 'limit -p bhard=100G jellyfin' /data
xfs_quota -x -c 'limit -p bhard=30G prometheus' /data

# Initialize project quota tracking on the directories
xfs_quota -x -c 'project -s postgres' /data
xfs_quota -x -c 'project -s jellyfin' /data
xfs_quota -x -c 'project -s prometheus' /data
```

Now reference these in your Docker Compose file with bind mounts:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - /data/docker/postgres:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 2G

  jellyfin:
    image: jellyfin/jellyfin:latest
    volumes:
      - /data/docker/jellyfin:/config
      - /path/to/media:/media:ro

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - /data/docker/prometheus:/prometheus
```

Any writes these containers make to their bind mounts hit the XFS project quota. When Jellyfin's media cache hits 100G, writes fail — but the rest of the host stays operational.

## Applying Quotas to Named Docker Volumes

If you prefer named volumes over bind mounts, create them with a device path and apply the quota to the backing directory:

```bash
# Create the backing directory with project quota
mkdir -p /data/volumes/grafana
echo "200:/data/volumes/grafana" >> /etc/projects
echo "grafana:200" >> /etc/projid
xfs_quota -x -c 'limit -p bhard=5G grafana' /data
xfs_quota -x -c 'project -s grafana' /data

# Create a Docker volume pointing to that directory
docker volume create \
  --driver local \
  --opt type=none \
  --opt device=/data/volumes/grafana \
  --opt o=bind \
  grafana-storage
```

In compose, reference it directly:

```yaml
volumes:
  grafana-storage:
    external: true

services:
  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana-storage:/var/lib/grafana
```

## Monitoring Quota Usage

Track your quotas and container disk usage regularly:

```bash
# XFS project quota report
xfs_quota -x -c 'report -p' /data

# Docker global disk usage
docker system df

# Per-container writable layer (real rather than quota size)
du -sh /var/lib/docker/overlay2/*/diff

# Simple threshold alert
LIMIT=90
USAGE=$(df /data | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$USAGE" -gt "$LIMIT" ]; then
  echo "WARNING: /data is ${USAGE}% full"
fi
```

Add the threshold check to a cron job or systemd timer for automatic notifications.

## Caveats and Limitations

- **overlay2.size requires XFS with prjquota** — it does not work on ext4, btrfs, or ZFS. For ZFS, use per-dataset quotas instead.
- **Non-Linux platforms** — Docker Desktop on macOS or Windows does not support this option.
- **Bind mounts are not governed by overlay2.size** — any directory mounted with `-v /host/path:/container/path` bypasses the overlay2 quota entirely. This is why XFS project quotas on the host are necessary for data-heavy workloads.
- **Existing containers are not retroactively limited** — the overlay2.size option only applies to containers created after the daemon change.
- **Image layers count toward the cap** — a 5G base image leaves only 5G of writable space with a 10G global limit.

## Summary

One runaway container should never take down your entire homelab. XFS project quotas combined with Docker's overlay2.size option give you hard storage limits that are built into the kernel — no agent, no sidecar, no overlay filesystem hack.

Start with a global 10G cap in daemon.json, then apply per-service project quotas to directories housing your largest data stores. Add a cron-based monitoring check and you have a zero-maintenance storage safety net that works whether you run five containers or fifty.

The disk will fill gracefully — one container at a time — and you will know exactly which one to blame.
