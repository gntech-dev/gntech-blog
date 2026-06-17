---
title: "Linux Cgroups v2 Guide — Docker Container Resource Management"
description: "Deep dive into Linux cgroups v2 for Docker container resource control — memory.max/high, CPU quotas, I/O weights, PSI monitoring, and docker-compose deploy.resources configurations for homelab."
date: 2026-06-17T13:30:00-04:00
tags:
  - linux
  - docker
  - containers
  - performance
  - homelab
keywords:
  - Linux cgroups v2 Docker container resource limits
  - cgroups v2 memory max high pressure stall Docker
  - Docker compose CPU memory I/O quota cgroups v2
  - Container OOM kill prevention cgroups v2 swap limit
  - Linux PSI pressure stall monitoring Docker containers
  - cgroups v2 unified hierarchy Docker resource control
  - Docker compose deploy resources section cgroups
summary: "Learn Linux cgroups v2 for Docker resource control: memory.max and memory.hard limits, CPU quotas, I/O throttling, PSI monitoring, and compose deploy.resources configs. Includes real container debugging and OOM prevention."
canonical: "https://blog.gntech.me/posts/cgroups-v2-docker-container-resource-limits/"
---

Every homelab running Docker eventually hits the wall where one misbehaving container — a database spike, a CI build, a Plex transcode — starves every other service. You throw a `--memory=512m` flag on the compose file and hope. But under the hood, what actually limits your containers is the **cgroups v2 unified hierarchy**.

Modern Linux distributions (Ubuntu 22.04+, Debian 12+, Fedora 37+) ship with cgroups v2 as the default. Docker 20.10+ uses it automatically. Yet most guides still reference the old v1 approach with separate subsystems and double accounting. This post covers the v2-specific knobs that actually matter: `memory.high`, `memory.swap.max`, `io.max`, PSI pressure monitoring, and how to map these to Docker Compose resources.

## Checking Your Cgroups Version and Setup

Before tuning anything, verify which cgroup version your system uses:

```bash
# Should return "cgroup2fs" on a v2 system
stat -fc %T /sys/fs/cgroup/

# Available cgroup controllers
cat /proc/filesystems | grep cgroup

# Docker's cgroup driver
docker info | grep -i cgroup
```

Output from a healthy v2 setup:

```
cgroup2fs
cgroup2
 Cgroup Driver: systemd
 Cgroup Version: 2
```

If you're still on v1, you can switch at boot by adding to your kernel command line in `/etc/default/grub`:

```
GRUB_CMDLINE_LINUX_DEFAULT="cgroup_no_v1=all systemd.unified_cgroup_hierarchy=1"
```

Then run `update-grub` and reboot. Docker will automatically detect the unified hierarchy.

The kernel needs these config options enabled (all present in stock Ubuntu/Debian/Fedora kernels):

| Option | Purpose |
|--------|---------|
| `CONFIG_CGROUPS` | Core cgroup support |
| `CONFIG_MEMCG` | Memory controller |
| `CONFIG_BLK_CGROUP` | Block I/O controller |
| `CONFIG_CFS_BANDWIDTH` | CPU bandwidth limiting |
| `CONFIG_PSI` | Pressure stall information |

## Cgroups v2 Resource Controllers — The Key Files

Cgroups v2 consolidates all controllers under the unified hierarchy at `/sys/fs/cgroup/`. Each Docker container gets its own cgroup, typically at `/sys/fs/cgroup/system.slice/docker-<container-id>.scope/`.

Find a running container's cgroup path:

```bash
# Get container's full ID
CID=$(docker inspect --format '{{.Id}}' my-container)
echo /sys/fs/cgroup/system.slice/docker-$CID.scope/
```

The key control files inside each container cgroup:

| File | What it does |
|------|-------------|
| `cpu.max` | CPU quota and period: `$quota $period` |
| `cpu.weight` | Relative CPU weight (1-10000) |
| `memory.max` | Hard memory limit in bytes (OOM kill) |
| `memory.high` | Soft throttle limit in bytes (reclaim) |
| `memory.low` | Protection floor (reclaim stops here) |
| `memory.min` | Absolute protection floor |
| `memory.swap.max` | Max swap usage in bytes |
| `io.max` | Per-device bandwidth/iops limits |
| `io.weight` | Relative I/O weight (1-10000) |
| `pids.max` | Max number of processes |
| `memory.events` | PSI-like event counters |
| `memory.pressure` | Per-cgroup PSI memory pressure |

Read the effective limits for a running container:

```bash
CID=$(docker inspect --format '{{.Id}}' my-container)
CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
echo "CPU: $(cat $CG/cpu.max)"
echo "Mem max: $(cat $CG/memory.max)"
echo "Mem high: $(cat $CG/memory.high)"
echo "Swap max: $(cat $CG/memory.swap.max)"
echo "PIDs max: $(cat $CG/pids.max)"
```

## Docker Compose Resource Limits

Docker Compose maps to cgroups v2 through the `deploy.resources` section. In recent `docker compose` v2 releases, this works outside swarm mode:

```yaml
services:
  database:
    image: postgres:16
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 1G
        reservations:
          cpus: "0.5"
          memory: 256M
    environment:
      - POSTGRES_DB=app
    volumes:
      - pgdata:/var/lib/postgresql/data
```

What this translates to in cgroups v2:

- **`cpus: "2.0"`** → `cpu.max` set to `200000 100000` (2 cores per 100ms period)
- **`memory: 1G`** → `memory.max` set to `1073741824`
- **`reservations.memory: 256M`** → `memory.low` set to `268435456` (not memory.min)

For `docker run` directly:

```bash
docker run -d \
  --name database \
  --cpus="2.0" \
  --memory="1g" \
  --memory-reservation="256m" \
  --memory-swap="1g" \
  --blkio-weight=500 \
  postgres:16
```

The `--memory-swap="1g"` flag (same value as `--memory`) disables swap for that container in cgroups v2 by setting `memory.swap.max = memory.max`.

## Memory Management — Hard and Soft Limits

The v2 memory controller provides four tiers of control, not just the hard limit from v1:

**memory.max** — Hard limit. Exceeding it triggers an immediate OOM kill. Equivalent to `--memory` in Docker.

**memory.high** — Soft throttle. When usage exceeds this value, the kernel aggressively reclaims memory from the cgroup. Processes experience higher latency (page reclaim) but aren't killed. Docker sets `memory.high` when you use `--memory-reservation`.

**memory.low** — Protection floor. During global memory pressure, the kernel tries not to reclaim below this threshold. Not a reservation — it doesn't guarantee the memory is available, but the cgroup gets priority over others above the low line.

**memory.min** — Hard protection. The kernel will never reclaim below this value, even if the host is OOM. Use sparingly — it can prevent the host from reclaiming memory it desperately needs.

### Practical Example

```bash
# Run a container with both hard and soft limits
docker run -d --name mem-demo \
  --memory=512m \
  --memory-reservation=256m \
  alpine sleep 3600

CID=$(docker inspect --format '{{.Id}}' mem-demo)
CG=/sys/fs/cgroup/system.slice/docker-$CID.scope

echo "--- Cgroup v2 memory config ---"
echo "memory.max:     $(cat $CG/memory.max)"
echo "memory.high:    $(cat $CG/memory.high)"
echo "memory.low:     $(cat $CG/memory.low)"
```

Output:

```
--- Cgroup v2 memory config ---
memory.max:     536870912
memory.high:    268435456
memory.low:     268435456
```

The reservation maps to both `memory.high` and `memory.low`. When the container exceeds 256MB, reclaim kicks in — the process slows but doesn't crash. At 512MB, the OOM killer terminates it.

Watch `memory.events` to see if throttling is happening:

```bash
watch -n 2 cat $CG/memory.events
```

Expected output under light load:

```
low=0 high=0 max=0 oom=0 oom_kill=0
```

If `high` increments, your container is hitting the soft throttle — consider raising the reservation or optimizing memory usage. If `max` or `oom_kill` increments, the hard limit was breached.

### Swap Control

Control swap per-container with `--memory-swap`:

```bash
# Total (memory + swap) = 768m, so swap max = 256m
docker run --memory=512m --memory-swap=768m nginx

# Disable swap entirely for this container
docker run --memory=512m --memory-swap=512m nginx
```

In cgroups v2, this sets `memory.swap.max` to the delta between the two values. Disabling swap is often desirable for database containers — you want an OOM kill over swap-induced latency spikes.

## CPU Quotas and Throttling

Docker translates `--cpus` to a quota/period pair in `cpu.max`. The quota is the number of microseconds the container can run per period (default 100ms).

```bash
docker run -d --name cpu-demo --cpus="1.5" alpine md5sum /dev/urandom

CID=$(docker inspect --format '{{.Id}}' cpu-demo)
cat /sys/fs/cgroup/system.slice/docker-$CID.scope/cpu.max
```

Output: `150000 100000`

The container gets 150ms of CPU time per 100ms window — effectively 1.5 cores at 100% utilization. Under load, the kernel enforces this strictly.

**CPU shares vs quota** — use both for best results:

- **`--cpus` (quota)**: Absolute ceiling. No container can exceed this, even if the host is idle.
- **`--cpu-shares` (weight)**: Relative priority under contention. A container with 2048 shares gets twice the CPU of one with 1024 — but only when other containers are competing.

```yaml
services:
  important-worker:
    image: my-worker
    deploy:
      resources:
        limits:
          cpus: "4.0"
    # 1024 is default weight, nothing extra needed

  background-task:
    image: my-batch
    deploy:
      resources:
        limits:
          cpus: "2.0"
    # implicit cpu-shares=1024, so both get equal weight under quota
```

For CPU pinning, use `--cpuset-cpus`:

```bash
docker run --cpuset-cpus="0-3" --cpus="4.0" nginx
```

This locks the container to physical cores 0-3 and uses the full capacity. Combine with `--cpus` to limit within the pinned set.

## I/O Control with io.weight and io.max

Docker's I/O controls in cgroups v2 work through `io.max` (absolute limits) and `io.weight` (relative shares). Docker exposes these through `--device-read-bps`, `--device-write-bps`, `--device-read-iops`, `--device-write-iops`, and `--blkio-weight`.

```bash
# Limit backup container to 50MB/s read, 25MB/s write on /dev/sdb
docker run -d --name backup \
  --device-read-bps /dev/sdb:50mb \
  --device-write-bps /dev/sdb:25mb \
  --blkio-weight=200 \
  backup-image
```

Behind the scenes, this writes to `io.max`:

```
8:16 rbps=52428800 wbps=26214400
```

Where `8:16` is the major:minor device number for `/dev/sdb` (verify with `lsblk`).

In a compose context, you must use `docker run` flags since `docker compose deploy.resources` doesn't yet expose `device-read-bps` in the compose spec. Alternatively, set limits directly via cgroupfs:

```bash
CID=$(docker inspect --format '{{.Id}}' backup)
CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
echo "8:16 rbps=52428800 wbps=26214400" | sudo tee $CG/io.max
```

**Practical scenario:** Your nightly backup container that streams to an external disk should never saturate the same disk your media server uses. Set its write limit to 50MB/s so Plex/Jellyfin streams stay smooth.

## PSI — Pressure Stall Information

PSI is the most useful monitoring feature added alongside cgroups v2. It measures how long processes stall waiting for resources.

System-wide PSI is available in `/proc/pressure/`:

```bash
cat /proc/pressure/memory
```

Output:

```
some avg10=0.12 avg60=0.05 avg300=0.02 total=548290312
full avg10=0.01 avg60=0.01 avg300=0.00 total=43210987
```

- **some**: At least one task was stalled on memory
- **full**: All tasks were stalled (resource fully saturated)
- **avg10/60/300**: Weighted averages over 10s, 60s, 300s
- **total**: Cumulative stalled microseconds

Per-cgroup PSI gives per-container visibility:

```bash
CID=$(docker inspect --format '{{.Id}}' my-container)
cat /sys/fs/cgroup/system.slice/docker-$CID.scope/memory.pressure
```

### Monitoring PSI in Your Homelab

**Immediate check:**

```bash
# Top 5 containers by memory pressure
for cg in /sys/fs/cgroup/system.slice/docker-*.scope; do
  pressure=$(cat $cg/memory.pressure 2>/dev/null | grep some | awk '{print $2}')
  name=$(echo $cg | grep -oP 'docker-\K[^.]+')
  [ -n "$pressure" ] && echo "$pressure  $name"
done | sort -t= -k2 -rn | head -5
```

**Netdata** exposes PSI metrics natively — add this to your Netdata config:

```yaml
# /etc/netdata/python.d/psd.conf
psi:
  name : 'psi'
  update_every : 5
```

**Prometheus** node_exporter v1.3+ collects PSI metrics with the `--collector.pressure` flag enabled. Combined with cAdvisor's container-level metrics, you can build a Grafana dashboard that alerts when any container's avg10 memory PSI exceeds 5%.

Alert rule for Alertmanager:

```yaml
groups:
  - name: psi
    rules:
      - alert: ContainerMemoryPressure
        expr: node_pressure_memory_waiting_seconds_total > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory pressure detected on {{ $labels.instance }}"
```

PSI is the best early indicator of a container approaching its limits — well before OOM kills occur.

## Troubleshooting OOM Kills and Throttling

When a container goes down, trace the root cause through cgroups v2 events.

**Step 1 — Check kernel OOM logs:**

```bash
dmesg | grep -i oom | tail -5
journalctl -u docker.service | grep -i "killed\|oom"
```

**Step 2 — Read memory.events from the container cgroup:**

```bash
CID=$(docker inspect --format '{{.Id}}' my-container)
cat /sys/fs/cgroup/system.slice/docker-$CID.scope/memory.events
```

The event counters are cumulative and persistent across container restarts:

| Counter | Meaning |
|---------|---------|
| `low` | Cgroup reclaimed below memory.low threshold |
| `high` | Cgroup exceeded memory.high and is throttling |
| `max` | Cgroup hit memory.max (imminent OOM action) |
| `oom` | OOM killer invoked |
| `oom_kill` | A process was killed |

**Step 3 — Identify the container by PID:**

```bash
# Find the cgroup that experienced the OOM
grep "oom_kill" /sys/fs/cgroup/system.slice/docker-*.scope/memory.events | grep -v "oom_kill=0"

# For each hit, inspect the container
for f in $(grep -l "oom_kill=[1-9]" /sys/fs/cgroup/system.slice/docker-*.scope/memory.events); do
  cid=$(echo $f | grep -oP 'docker-\K[^.]+')
  docker inspect $cid --format '{{.Name}} {{.State.Status}}' 2>/dev/null
done
```

**Real scenario:** A PostgreSQL container kept crashing during nightly VACUUM. `memory.events` showed:

```
low=0 high=2341 max=12 oom=3 oom_kill=3
```

The `high` counter hitting 2341 meant the container was constantly under reclaim pressure. `max=12` showed repeated hard limit hits. The fix: raised `--memory` from 512MB to 1GB and added `--memory-reservation=768m` to give the soft throttle room. PSI monitoring was added to alert if avg10 memory pressure exceeded 3%.

## Conclusion

Cgroups v2 brings a unified, cleaner model for container resource control in Linux. The key improvements over v1 — `memory.high` for soft throttling, `memory.swap.max` for per-container swap limits, `io.max` for device-level I/O constraints, and PSI for proactive pressure monitoring — give homelab operators precise control over noisy neighbors.

Start today: verify your cgroup version, add resource limits to your compose files (or at minimum to heavy containers like databases and media transcode services), and wire up PSI metrics into your monitoring stack. Your containers will be more predictable, your homelab more stable, and your late-night "why is everything slow" investigations will go a lot faster.

For further reading, see the [kernel.org cgroup-v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) and the [Docker resource constraints guide](https://docs.docker.com/config/containers/resource_constraints/).
