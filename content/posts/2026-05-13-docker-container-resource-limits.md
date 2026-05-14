---
title: "Docker Container Resource Limits — CPU, Memory, and I/O Constraints for Homelabs"
description: "Master Docker container resource limits for homelabs — CPU pinning, memory caps, swap control, block I/O throttling, cgroup v2. Real Compose configs for Postgres, Plex, Frigate, and Jellyfin."
date: 2026-05-13T15:00:00-04:00
tags:
  - docker
  - linux
  - performance
  - homelab
  - devops
keywords:
  - Docker container limits
  - CPU memory I/O constraints
  - Docker Compose resource management
  - cgroup v2 Docker
  - homelab Docker optimization
summary: "Practical Docker container resource limits guide for homelabs — CPU quota/pinning, memory hard/soft limits, swap control, block I/O throttling, cgroup v2 differences, and Docker Compose examples."
canonical: "https://gntech.dev/posts/docker-container-resource-limits/"
---

If you run more than ten containers on a single Docker host — and in a
homelab you almost certainly do — you've seen the problem. One container
hogs CPU compiling something, Plex stutters. A misconfigured service
leaks memory, the OOM killer takes down Postgres instead. Database I/O
starves every other container on the same drive.

Docker doesn't enforce limits by default. Every container can consume
all available CPU, all RAM, and saturate the disk. That's fine for
development. It's a problem for production — and your homelab is
production for the services your family depends on.

This post covers how to constrain Docker containers by CPU, memory,
and block I/O, with real-world examples for common homelab services.

---

## Why Bother? The "But I Have 16 Cores" Trap

A lack of limits causes three concrete problems:

**Noisy neighbors.** One runaway process impacts every other container.
A Python script in your Frigate container goes infinite loop — now your
Home Assistant dashboard takes 30 seconds to load.

**OOM roulette.** The Linux OOM killer doesn't target the leaky
container first. It scores processes by a heuristic (oom_score) that
rewards long-running, low-memory containers. Your Postgres or database
container often dies before the actual memory hog.

**Disk saturation.** A database container doing a backup or reindex can
push disk latency from 2 ms to 200 ms, making every other container
that touches storage feel sluggish.

Resource limits turn "hoping for the best" into predictable behavior.
Every container gets its fair share, and no container takes down the
host.

---

## Memory Limits — The Most Important Constraint

Memory is the resource you absolutely must cap. An unconstrained
container that grows until swap fills will lock up the entire host.

### `--memory` (Hard Limit)

The hard limit on physical memory. The container cannot allocate more
than this. When it tries, the kernel reclaims memory — or kills the
container process.

```yaml
services:
  myservice:
    image: myservice:latest
    deploy:
      resources:
        limits:
          memory: 512M
```

### `--memory-reservation` (Soft Limit)

A soft limit — the kernel tries to keep memory usage at or below this
value, but allows bursts up to `--memory`. This is the right choice for
services that are usually quiet but can spike.

```yaml
services:
  webapp:
    image: nginx:latest
    deploy:
      resources:
        reservations:
          memory: 128M
        limits:
          memory: 512M
```

In plain Docker:
```bash
docker run -d --name nginx \
  --memory="512m" \
  --memory-reservation="128m" \
  nginx:latest
```

### `--memory-swap` (Swap Control)

Controls how much total memory + swap the container can use. By default,
a container with `--memory=512M` gets unlimited swap. That means when
RAM fills, the kernel swaps — and performance tanks.

```bash
# 512M RAM, no swap
docker run --memory="512m" --memory-swap="512m" myservice

# 512M RAM, 256M swap (total 768M)
docker run --memory="512m" --memory-swap="768m" myservice
```

In Compose:
```yaml
services:
  db:
    image: postgres:16
    deploy:
      resources:
        limits:
          memory: 1G
    # Compose doesn't directly support memory-swap in deploy.resources
    # Use the long syntax with oom_kill_disable or --memory-swap via docker-compose.override.yml
```

**Pro tip:** Always set `--memory-swap` equal to `--memory` to disable
swap for critical services. You want OOM kill, not swap death.

### OOM Killer Priority

Docker assigns an oom_score_adj of -500 to dockerd and 0 to containers
by default. You can bias which container the kernel kills first:

```bash
# This container dies first under pressure
docker run --oom-kill-disable=false --oom-score-adj=1000 my-cache

# This container should never be killed (database!)
docker run --oom-kill-disable=true postgres:16
```

**Warning:** `--oom-kill-disable` without a `--memory` limit is
dangerous — the kernel can't reclaim memory from the container and the
host runs out of RAM.

---

## CPU Limits — Shares vs Quotas

Docker offers two CPU constraint mechanisms with very different behavior.

### `--cpus` (CPU Quota — Hard Limit)

Limits the container to a fraction of a CPU core. A container with
`--cpus=1.5` gets 150% of one core — equivalent to 1.5 full cores.

```bash
docker run -d --name nginx --cpus="0.5" nginx:latest
```

Under the hood this sets `cpu.cfs_quota_us` in cgroups. The kernel
throttles the container when it exceeds the quota. This is a **hard cap**
— the container cannot use more than this, even if the CPU is idle.

```yaml
services:
  heavy-task:
    image: my-batch-processor
    deploy:
      resources:
        limits:
          cpus: '0.5'
```

### `--cpu-shares` (Relative Weight — Soft Limit)

Relative CPU priority. The default is 1024. A container with 2048 gets
~twice the CPU of a container with 1024 when there's contention. With
idle CPU, every container can burst to 100%.

```yaml
services:
  database:
    image: postgres:16
    deploy:
      resources:
        reservations:
          cpus: '2'
  web:
    image: nginx:latest
    deploy:
      resources:
        reservations:
          cpus: '1'
```

**Key difference:** `--cpus` throttles hard. `--cpu-shares` only
matters during contention. Use `--cpus` for batch jobs and uploads.
Use `--cpu-shares` for daemons that should be fair but can burst.

### `--cpuset-cpus` (CPU Pinning)

Pins the container to specific physical cores. Useful for:
- Real-time audio/video encoding
- Consistent cache behavior (L1/L2 stays warm)
- Avoiding NUMA cross-socket latency

```bash
# Pin to CPU cores 0 and 2
docker run --cpuset-cpus="0,2" --name transcode jellyfin/jellyfin
```

In Compose:
```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    deploy:
      resources:
        limits:
          cpus: '2'
    # cpuset requires the long resource format or docker-compose.override
```

---

## Block I/O Limits — The Overlooked Bottleneck

CPU and memory limits are common. Block I/O limits are rare — and your
homelab needs them more than you think.

### `--device-read-bps` / `--device-write-bps`

Throttle read or write throughput in bytes per second:

```bash
# Limit this container to 50 MB/s write, 100 MB/s read
docker run -d \
  --device-write-bps /dev/sda:50mb \
  --device-read-bps /dev/sda:100mb \
  --name torrent-client \
  transmission:latest
```

### `--device-read-iops` / `--device-write-iops`

Throttle by IOPS instead of bandwidth:

```bash
# Limit to 1000 read IOPS, 500 write IOPS
docker run -d \
  --device-write-iops /dev/sda:500 \
  --device-read-iops /dev/sda:1000 \
  --name database \
  postgres:16
```

Compose does not support portable block I/O throttling through the modern
Compose Specification. The `deploy.resources` section can set CPU and memory,
but not per-device disk I/O limits.

Use `docker run` for block I/O throttling, or apply host-level controls with
systemd/cgroups for the Docker service. If you see old examples using
`device_write_bps` or `device_read_bps` in Compose files, test them on your
Compose version first — recent `docker compose` releases reject those keys.

---

## Real-World Examples

### Postgres Database (Memory Critical)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: postgres
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
          cpus: '1.0'
    environment:
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - PGDATA=/var/lib/postgresql/data/pgdata
    volumes:
      - pgdata:/var/lib/postgresql/data
    # Remember: shared_buffers in postgresql.conf should be ~25% of the memory limit
    # With a 2G limit, set shared_buffers = 512MB

volumes:
  pgdata:
```

No swap (`--memory-swap=2G` via docker-compose.override if needed).
OOM kill enabled (default) — getting killed is better than swapping.

### Jellyfin / Plex (CPU Intensive, Memory Hungry)

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2.0'
        reservations:
          memory: 2G
    devices:
      - /dev/dri:/dev/dri  # Intel QuickSync
    # Pin to physical cores 0-3 for stable transcoding
```

Also add `--cpuset-cpus="0-3"` for consistent transcode performance.
Without pinning, Linux may bounce the transcode thread between cores,
flushing cache and costing 10-20% overhead.

### Frigate NVR (I/O Heavy, Memory Constrained)

```yaml
services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:stable
    container_name: frigate
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
        reservations:
          memory: 1G
    # Throttle disk writes for recordings
    # Add to docker-compose.override.yml:
    # device_write_bps:
    #   - /dev/sda:30mb
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ${FRIGATE_CONFIG:-./config}:/config
      - ${FRIGATE_STORAGE:-./media}:/media/frigate
      - type: tmpfs
        target: /tmp/cache
        tmpfs:
          size: 256000000
```

The tmpfs for `/tmp/cache` reduces SD card / HDD writes significantly.

### Transmission / qBittorrent (Disk Killer)

```yaml
services:
  transmission:
    image: lscr.io/linuxserver/transmission:latest
    container_name: transmission
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
    # All your docker-compose.override.yml device limits go here
    # device_write_bps: /dev/sda:20mb
    # device_read_bps: /dev/sda:50mb
```

Throttling torrent client disk I/O is the single biggest quality-of-life
improvement for a shared-storage homelab. Without it, a busy torrent
client can saturate the disk for minutes.

---

## Monitoring: What's Actually Happening

### `docker stats` — Quick Live View

```bash
docker stats --no-stream --format \
  "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}"
```

### `docker stats` with All Metrics

```bash
docker stats --no-stream --format \
  "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}"
```

### cgroup v2 Direct Inspection

On modern distros (Debian 12+, Ubuntu 22.04+, Fedora 37+):

```bash
# Memory usage for a container
cat /sys/fs/cgroup/memory/system.slice/docker-<container-id>.scope/memory.current

# CPU usage (microseconds)
cat /sys/fs/cgroup/cpu.system.slice/docker-<container-id>.scope/cpu.stat

# IO stats
cat /sys/fs/cgroup/io.system.slice/docker-<container-id>.scope/io.stat
```

For cgroup v2, Docker also provides `docker inspect`:

```bash
docker inspect <container> --format '{{.HostConfig.Memory}}'
docker inspect <container> --format '{{.HostConfig.NanoCpus}}'
```

---

## cgroup v2 Notes

Debian 12, Ubuntu 22.04+, and all modern kernels default to cgroup v2.
Docker 20.10+ supports it natively, but there are differences:

- **`--memory-swap` behavior changed.** In cgroup v1, `--memory-swap=-1`
  meant unlimited swap. In cgroup v2, swap is 0 by default unless the
  kernel supports memory.swap.max.
- **`--oom-kill-disable` works differently.** In cgroup v2, disabling
  OOM kill means the container is paused when it hits the memory limit
  (tasks get stuck in D state) instead of killed. Most services just
  freeze, which can be worse than an OOM kill.
- **`device_write_bps` needs the right device major:minor.** Use
  `ls -l /dev/sda` or `stat /dev/sda` to find the device numbers.

Check your cgroup version:

```bash
stat -fc %T /sys/fs/cgroup/
# cgroup2fs → cgroup v2
# tmpfs → cgroup v1
```

---

## Putting It All Together — A Safe Default for Any Container

Here's the template I use for every new container in my homelab:

```yaml
services:
  new-service:
    image: some/image:latest
    container_name: new-service
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.25'
          memory: 128M
```

Start conservative. Run for a week with `docker stats` logging. Bump
reservations based on real usage, not guesswork. Document why each
limit exists in your docker-compose.yml comments — future you will
thank present you.

---

## When to Skip Limits

Resource limits aren't free. Setting CPU quotas too low causes
throttling and increased latency (CFS quota mechanism introduces
scheduling delays). Setting memory limits too low triggers constant
reclamation and swap thrashing.

Skip limits when:
- The container is the **only** service on the host
- The container does **bursty compute** that you want to finish fast
  (cron jobs, batch transcodes)
- You're benchmarking or load testing
- The container is a monitoring agent that needs minimal overhead

In every other case: set limits. Your homelab will be more reliable,
your other services will thank you, and you won't wake up at 2 AM to a
host that's OOM-frozen because Frigate had a memory leak.
