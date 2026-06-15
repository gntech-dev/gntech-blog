---
title: "Docker Overlay2 Storage Driver — Layers, Disk Usage, Troubleshooting"
description: "Deep dive into Docker's overlay2 storage driver on Linux — how layers work, managing disk space, troubleshooting common issues, and performance tuning for homelab deployments."
date: 2026-06-15T18:30:00-04:00
tags:
  - docker
  - linux
  - storage
  - homelab
  - troubleshooting
keywords:
  - Docker overlay2 storage driver Linux deep dive
  - Docker container layer management disk space
  - Docker overlay2 troubleshooting homelab storage
  - Docker storage driver performance tuning ZFS
  - Docker overlay2 df disk usage analysis
  - Container layer size docker system df inspect
  - Docker storage driver overlay2 vs aufs devicemapper
summary: "Everything about Docker's overlay2 storage driver — how overlay layers work, tracking disk usage by layer, recovering space from dangling layers, and performance tuning on ZFS-backed Proxmox hosts. Real commands, real output."
canonical: "https://blog.gntech.me/posts/docker-overlay2-storage-driver-linux-guide/"
---

Every Docker homelab eventually hits a storage wall. Containers stop writing. `docker-compose up` fails with "no space left on device". You check `df -h` and there's 40% free. The culprit? Docker's overlay2 storage driver and its layer-based architecture — a system where disk usage isn't always visible through traditional filesystem tools.

Docker overlay2 is the default storage driver on modern Linux distributions. It's fast, stable, and efficient thanks to overlay filesystem support built into the Linux kernel since version 4.0. But its copy-on-write layer model means container disk usage behaves differently than traditional filesystems. Understanding how overlay2 works is essential for any homelab running Docker on Proxmox, bare metal, or VPS.

This guide covers the overlay2 architecture from the ground up — how layers are structured, how to measure real disk usage, how to troubleshoot the most common storage failures, and how to tune performance when Docker is backed by ZFS on a Proxmox host.

## How Overlay2 Works — Layer Architecture

Docker overlay2 uses the Linux kernel's overlay filesystem to present a unified view of multiple directory layers. Each container image is built from a stack of read-only layers, with a thin read-write layer on top for the container itself.

### The Four Directories

Every running container with overlay2 has four directories in `/var/lib/docker/overlay2/<layer-id>/`:

- **lowerdir** — the base image layers (read-only, shared across containers)
- **upperdir** — the container's writable layer (one per container)
- **mergeddir** — the unified view presented to the container
- **workdir** — internal overlay filesystem metadata

Check the active overlay mounts on your system:

```bash
cat /proc/mounts | grep overlay | head -5
```

Example output from a homelab Docker host:

```
overlay /var/lib/docker/overlay2/a1b2c3d4e5f6/merged overlay rw,relatime,lowerdir=/var/lib/docker/overlay2/l/ABC123:/var/lib/docker/overlay2/l/DEF456,upperdir=/var/lib/docker/overlay2/a1b2c3d4e5f6/diff,workdir=/var/lib/docker/overlay2/a1b2c3d4e5f6/work 0 0
```

Each container gets its own overlay mount. The `diff` directory under each layer ID is where container writes actually land.

### Copy-on-Write in Practice

When a container modifies a file from the image, Docker copies that file from the lower (read-only) layer into the upper (writable) layer — this is copy-on-write (CoW). The original layer remains intact and shareable across containers running the same image.

```bash
# See which layers an image uses
docker inspect alpine:latest --format '{{.GraphDriver.Data}}'
```

For a running container:

```bash
docker inspect <container-name> --format '{{.GraphDriver.Data}}'
```

You'll see something like:

```
map[LowerDir:/var/lib/docker/overlay2/.../diff MergedDir:/var/lib/docker/overlay2/.../merged UpperDir:/var/lib/docker/overlay2/.../diff WorkDir:/var/lib/docker/overlay2/.../work]
```

The lower directories form a chain of read-only layers. Docker composes them using `:` as a separator in the kernel's overlay mount.

## Inspecting and Managing Disk Usage

Standard `du` and `df` don't tell the full story with overlay2. Build cache, dangling layers, and shared image layers all consume space that `df` on the host filesystem sees, but `du` in a container does not.

### Docker System DF — Your Primary Tool

```bash
docker system df
```

Output:

```
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          34        16        8.712GB   2.145GB (24%)
Containers      22        11        348.2MB   156.8MB (45%)
Local Volumes   12        8         1.234GB   0B (0%)
Build Cache     17        0         4.567GB   4.567GB (100%)
```

For a per-layer breakdown:

```bash
docker system df -v
```

The Build Cache entry is often the biggest surprise. Docker build cache can consume gigabytes of space that `df` attributes to "used" but no container actually needs.

### Layer-Level Inspection

Check how much each image layer adds:

```bash
docker history --no-trunc nginx:latest
```

Find the largest layers across all images:

```bash
docker history --no-trunc nginx:latest | awk '{print $2, $1}' | sort -h | tail -10
```

Check actual disk usage by overlay2 directories:

```bash
sudo du -sh /var/lib/docker/overlay2/*/diff | sort -rh | head -15
```

This shows which container writable layers are consuming the most space. If a container writes large files, its `diff` directory grows independently of the image layers.

### Cleanup Strategies

```bash
# Remove all unused containers, networks, images, and dangling build cache
docker system prune -a --volumes

# Remove only build cache
docker buildx prune --all

# Selective prune — keep images used in the last 24h
docker image prune -a --filter "until=24h"
```

For homelabs running nightly or weekly builds (Renovate, Watchtower), the build cache accumulates rapidly. Schedule a weekly prune:

```bash
docker system prune -a -f --filter "until=48h"
```

Add this to a cron job or systemd timer to keep disk usage under control without disrupting active containers.

### Zombie Layers — The Overlay2 Leftover

When Docker prunes an image but a container still references one of its layers, the layer sticks around in `/var/lib/docker/overlay2/`. These are called "zombie layers" — they show up in `du` but not in `docker system df`. If your overlay2 directory seems larger than the Docker-reported total, check for these:

```bash
# Compare Docker-reported usage with actual directory size
docker system df --format '{{.Type}}: {{.Size}}'
sudo du -sh /var/lib/docker/
```

A big discrepancy means orphaned layers. A Docker restart or a full prune usually reclaims them:

```bash
sudo systemctl restart docker
docker system prune -a -f
```

## Troubleshooting Common Overlay2 Issues

### Inode Exhaustion — The Silent Killer

The most common overlay2 failure in homelabs isn't disk space — it's inode exhaustion. Docker overlay2 creates thousands of metadata entries per container. On ext4, the default inode count can be too low for heavy container usage.

```bash
# Check inode usage
df -i /var/lib/docker
```

If `IUse%` is near 100% while `Use%` is low, you've hit the inode wall:

```
Filesystem     Inodes  IUsed   IFree IUse% Mounted on
/dev/sda1      2M      1.98M   20K   99%   /var/lib/docker
```

**Fix:** Move Docker storage to a filesystem with more inodes (XFS) or re-create ext4 with a larger inode ratio:

```bash
mkfs.ext4 -T news /dev/sdX1   # larger inode table
```

For Proxmox homelabs running Docker in a VM or LXC, ensure the disk backing `overlay2` uses XFS or ext4 with adequate inodes.

### ZFS Dataset Full

On Proxmox, Docker storage often sits on a ZFS dataset or zvol. ZFS has its own quota system separate from the filesystem:

```bash
# Check ZFS quotas and reservations
zfs get quota,refquota,reservation,refreservation storage/docker

# Check actual space used
zfs list storage/docker
```

```bash
# Set a quota if one doesn't exist
zfs set quota=50G storage/docker
```

If you see a "disk full" error in a container but `df -h` inside the container shows free space, the underlying ZFS dataset may have hit its quota.

### Docker Daemon Logs

When container writes fail, the Docker daemon logs often contain the real error:

```bash
journalctl -u docker -n 50 --no-pager | grep -i error
```

Common error patterns:

```
Error processing tar file: archive/tar: invalid tar header
no space left on device
failed to mount overlay: no such file or directory
```

The "no such file or directory" on overlay mount usually means a kernel module is missing or the overlay filesystem isn't supported. Check with:

```bash
lsmod | grep overlay
modprobe overlay
```

### Container-Specific Troubleshooting

When a single container reports "no space left" but everything else works:

```bash
# Check the container's writable layer size
sudo du -sh /var/lib/docker/overlay2/$(docker inspect <container> --format '{{.GraphDriver.Data.UpperDir}}' | xargs dirname | xargs basename)/diff

# Check the container itself
docker exec <container> df -h
docker exec <container> df -i
```

Sometimes a container fills its own layer with logs or temp files. If the container writes to a volume mount, the issue is on the host's filesystem handling that volume.

## Performance Tuning

### XFS and d_type

Overlay2 requires the underlying filesystem to support `d_type` (directory entry type). XFS enables this by default. ext4 also supports it. Verify:

```bash
xfs_info /var/lib/docker | grep ftype
```

If `ftype=0`, overlay2 will fall back to a slower compatibility mode. Re-create the filesystem with `ftype=1` to avoid this.

### Docker on ZFS

In Proxmox homelabs, Docker frequently runs inside a VM or LXC backed by ZFS. The performance characteristics depend on the ZFS recordsize and how Docker's overlay2 interacts with ZFS's own CoW:

- **Default ZFS recordsize (128K)**: fine for most containers
- **Database containers (PostgreSQL, MySQL)**: set recordsize to 16K on the dataset
- **Media containers (Jellyfin, Plex)**: set recordsize to 1M on media volumes

```bash
zfs set recordsize=16K storage/docker/db
zfs set recordsize=1M storage/docker/media
```

For the Docker storage directory itself, keep the default recordsize unless you benchmark and find a clear improvement.

### Docker Storage Options

Fine-tune overlay2 behavior through `daemon.json`:

```json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=1",
    "overlay2.size=10G"
  ]
}
```

- `overlay2.override_kernel_check=1` — bypass kernel compatibility checks (use only on up-to-date kernels)
- `overlay2.size=10G` — per-container size limit (10GB writable layer cap)

Apply changes:

```bash
sudo systemctl restart docker
```

### Per-Container Resource Limits

For containers with heavy write workloads, mount a dedicated volume or set per-container storage limits in `docker-compose.yml`:

```yaml
services:
  database:
    image: postgres:16-alpine
    volumes:
      - postgres-data:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 2G

volumes:
  postgres-data:
    driver_opts:
      type: none
      device: /mnt/ssd-fast/postgres
      o: bind
```

This bypasses overlay2 CoW for the database directory entirely, avoiding double-CoW (ZFS CoW + overlay2 CoW).

## Maintenance and Automation

### Daily Prune Cron

```bash
# /etc/cron.daily/docker-cleanup
#!/bin/bash
/usr/bin/docker system prune -a -f --filter "until=24h"
/usr/bin/docker builder prune -a -f
```

```bash
sudo chmod +x /etc/cron.daily/docker-cleanup
```

### Systemd Timer for Weekly Deep Clean

```ini
# /etc/systemd/system/docker-cleanup.service
[Unit]
Description=Docker deep cleanup
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker system prune -a -f --volumes
ExecStartPost=/usr/bin/docker builder prune -a -f
```

```ini
# /etc/systemd/system/docker-cleanup.timer
[Unit]
Description=Weekly Docker cleanup

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now docker-cleanup.timer
```

### Storage Monitoring with Prometheus

For homelabs running Prometheus and node_exporter, enable the textfile collector to track Docker overlay2 usage:

```bash
#!/bin/bash
# /etc/node_exporter/textfile/docker_storage.prom
DOCKER=$(sudo du -sb /var/lib/docker/ 2>/dev/null | cut -f1)
echo "docker_overlay2_usage_bytes $DOCKER" > /var/lib/node_exporter/textfile_collector/docker_storage.prom
echo "docker_overlay2_usage_percent $(df /var/lib/docker/ --output=pcent 2>/dev/null | tail -1 | tr -d ' %')" >> /var/lib/node_exporter/textfile_collector/docker_storage.prom
```

Run this every 5 minutes via cron and graph it in Grafana alongside other host metrics.

## Conclusion

Docker's overlay2 storage driver is fast and reliable, but its layer-based architecture requires a different approach to disk management than traditional filesystems. Understanding the four overlay directories, monitoring build cache accumulation, checking inodes before disk space, and tuning for your ZFS or XFS backend all make the difference between a Docker host that runs for months and one that mysteriously fills up every week.

Start with `docker system df` to see your current state. Check your inode usage with `df -i /var/lib/docker`. Set up automated pruning. And if you're on a Proxmox-backed homelab, pay attention to ZFS dataset quotas and recordsize tuning. Your containers will thank you.
