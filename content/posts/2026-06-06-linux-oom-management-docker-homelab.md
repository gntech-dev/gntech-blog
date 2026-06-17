---
title: "Linux OOM Management and System Stability for Docker Homelab Hosts"
description: "Prevent OOM killer crashes on Docker homelab hosts. Configure systemd OOMD, cgroups v2 memory limits, oom_score_adj, swap, and earlyoom for reliable container stability."
date: 2026-06-06T16:00:00-04:00
tags:
  - linux
  - docker
  - containers
  - devops
  - homelab
keywords:
  - Linux OOM management Docker homelab host stability guide
  - Prevent OOM killer Docker containers systemd OOMD configuration
  - oom_score_adj Docker containers critical service prioritization
  - cgroups v2 memory limits Docker Compose resource constraints
  - earlyoom userspace OOM daemon homelab setup
  - Linux swap configuration Docker host performance tuning
  - Docker container OOM priority system stability best practices
summary: "Prevent OOM killer crashes on your Docker homelab host. Configure systemd OOMD, set proper oom_score_adj values, enable earlyoom, and apply cgroups v2 memory limits for reliable container operation."
canonical: "https://blog.gntech.me/posts/linux-oom-management-docker-homelab/"
---

## The OOM Problem on Docker Homelab Hosts

Your homelab host runs Docker containers. Maybe a dozen. Maybe thirty. Postgres for Immich, Redis for Valkey cache, Prometheus hammering metrics every 15 seconds, Ollama loading a 7B model into RAM. The host has 16 GB total. Maybe 8 GB if you're running on a repurposed thin client. And you've just rebuilt your media library — now Immich is transcoding, Postgres is indexing, and Prometheus is scraping.

Then everything freezes. SSH stops responding. The web UI disappears. Thirty seconds later, things come back — but Postgres is gone. Or worse, Prometheus, and now you lost metrics. The kernel's OOM killer picked a victim. It almost never picks the right one.

The Linux Out-Of-Memory (OOM) killer doesn't understand Docker container boundaries or service priority. It sees memory pressure, calculates an oom_score for every process, and kills the highest scorer. A 1 GiB Postgres container that's been running for months has a higher badness score than a memory-leaking sidecar that started five minutes ago. The kernel doesn't know which container is critical to your homelab — it just sees big processes using memory.

This guide covers every layer of OOM defense for a Docker homelab host, from Docker Compose resource limits through kernel sysctl tuning. Apply all five layers and your critical services stay up under memory pressure.

## Docker Compose Resource Limits Are Your First Line of Defense

The single most important thing you can do for Docker host stability is set resource limits on every container. Without limits, a single container can consume all host memory and force the kernel to make kill decisions.

Docker Compose v3 supports deploy-level resource constraints:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
        reservations:
          memory: 256M

  prometheus:
    image: prom/prometheus
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.5"

  ollama:
    image: ollama/ollama
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "2.0"
```

With `docker compose up` (not swarm), these limits are applied directly via cgroups v2. When a container reaches its memory limit, Docker's internal OOM kills the container itself — contained, predictable, and logged. Without limits, the kernel kills host-wide.

For `docker run`, the equivalent flags are:

```bash
docker run -d \
  --name postgres \
  --memory="512m" \
  --cpus="1.0" \
  --memory-reservation="256m" \
  postgres:16-alpine
```

**Key detail:** By default Docker sets `--memory-swap` to twice `--memory`, giving each container swap access equal to its RAM limit. To disable swap per-container, set `--memory-swap` equal to `--memory`:

```bash
docker run --memory="512m" --memory-swap="512m" postgres:16-alpine
```

Every container in your homelab should have at least a memory limit. No exceptions. Even monitoring tools need limits — a Prometheus tsdb compaction spike can eat 2 GB before you notice.

## systemd-oomd — Userspace OOM Prevention at the Cgroup Level

Systemd v250+ ships `systemd-oomd`, a userspace OOM manager that monitors memory pressure at the cgroup level and kills offending cgroups before the kernel panic-kills random processes. It's the cleanest approach for Docker hosts because Docker containers already live under systemd cgroup hierarchies.

Enable it on Ubuntu 22.04+ and Debian Bookworm+:

```bash
systemctl enable --now systemd-oomd
systemctl status systemd-oomd
```

Configure thresholds in `/etc/systemd/oomd.conf`:

```ini
[OOM]
DefaultMemoryPressureDurationSec=30
DefaultMemoryPressureLimit=60%
SwapUsedLimitPercent=90%
```

This tells oomd to kill the cgroup with the highest memory pressure when:
- 60%+ memory pressure sustained for 30 seconds, or
- 90%+ swap is used

To make Docker's cgroup eligible for systemd-oomd management, add `ManagedOOM=kill` to the Docker daemon's service override:

```bash
systemctl edit docker
```

Add:

```ini
[Service]
ManagedOOM=kill
```

Then reload:

```bash
systemctl daemon-reload
systemctl restart docker
```

Check oomd activity:

```bash
journalctl -u systemd-oomd --since "1 hour ago"
```

You should see entries like:

```
systemd-oomd[XXX]: Performing kill action for cgroup /system.slice/docker-<id>.scope (memory pressure critical)
```

The key advantage over the kernel OOM killer: systemd-oomd kills the **entire cgroup** (all processes in the Docker container) rather than picking one process and leaving orphaned children. For Docker hosts, this is exactly what you want.

## Earlyoom — Simple OOM Prevention Daemon

Earlyoom is a lightweight userspace OOM killer that monitors available memory and swap, and preemptively kills the process with the largest `rss` allocation before the kernel OOM killer activates. It's simpler than systemd-oomd and works on any systemd-capable distribution.

Installation:

```bash
apt install earlyoom
```

Earlyoom's default configuration is conservative: it acts when free memory drops below 10% **and** swap is below 10%. The recommended config for Docker hosts is more aggressive:

Edit `/etc/default/earlyoom`:

```
EARLYOOM_ARGS="-m 5,10 -s 10,5 -r 3600 --prefer '(!postgres|!redis|!prometheus|!nginx)' --avoid '(!systemd|!sshd)'"
```

Breaking this down:
- `-m 5,10` — kill when available memory drops below 5%, report to syslog at 10%
- `-s 10,5` — kill when available swap drops below 10%, report at 5%
- `-r 3600` — report memory stats to syslog every hour
- `--prefer` — regex for processes to prefer **not** killing (inverted syntax: kill processes that don't match these first)
- `--avoid` — processes to never kill (systemd, sshd — the things you need to recover)

Enable the daemon:

```bash
systemctl enable --now earlyoom
```

Test it with a memory stress:

```bash
apt install stress-ng
stress-ng --vm 2 --vm-bytes 80% -t 30
```

Watch earlyoom in action:

```bash
journalctl -u earlyoom -f
```

Expected output:

```
earlyoom[XXX]: mem avail:  387 of  7855 MiB ( 4.93%), swap free:  456 of  2048 MiB (22.27%)
earlyoom[XXX]: sending SIGTERM to process 12345 (stress-ng-vm):
```

Earlyoom sends SIGTERM first (graceful shutdown), waits 10 seconds, then SIGKILL if the process is still alive. This is far more civilized than the kernel OOM killer's instant SIGKILL.

## Setting oom_score_adj for Critical Services

The kernel calculates an `oom_score` for every process based on `rss size + (total_vm / 2) × (cpu_time / total_cpu_time)`. You can adjust this with `oom_score_adj`:

| Value | Effect |
|-------|--------|
| -1000 | OOM_DISABLE — process is invisible to OOM killer |
| -500 | Very unlikely to be killed |
| -200 | Less likely |
| 0 | Default |
| +500 | More likely |
| +1000 | Highest priority target |

Docker passes `oom-score-adj` per container:

```bash
docker run -d \
  --name postgres \
  --memory="512m" \
  --oom-score-adj=-800 \
  postgres:16-alpine
```

Docker Compose doesn't have native `oom_score_adj` support in v3, but you can work around it with wrapper scripts or by using `docker run` directly for critical services. Alternatively, set it post-start with a systemd timer:

```bash
#!/bin/bash
# /usr/local/bin/set-oom-scores.sh
for name in postgres redis prometheus nginx; do
  pid=$(docker inspect -f '{{.State.Pid}}' "$name" 2>/dev/null)
  [ -n "$pid" ] && echo -500 > /proc/$pid/oom_score_adj
done
```

Make it executable and run on boot via systemd or cron:

```bash
chmod +x /usr/local/bin/set-oom-scores.sh
(crontab -l 2>/dev/null; echo "@reboot /usr/local/bin/set-oom-scores.sh") | crontab -
```

Recommended oom_score_adj values for a typical homelab:

- **Databases** (Postgres, MariaDB, Redis): **-500 to -800**
- **Web/Reverse proxies** (Nginx, Traefik, Caddy): **-200 to -400**
- **Monitoring** (Prometheus, Grafana, Loki): **0 (neutral)**
- **Batch/Transient** (build jobs, backup scripts): **+250 to +500**
- **System critical** (sshd, systemd-journald, Docker daemon): **Already protected by systemd service configuration**

## Swap Configuration: To Have or Not to Have

The Docker documentation recommends disabling swap entirely for production Docker hosts. The reasoning: when a host swaps, performance tanks for all containers, and the OOM killer may trigger too late to be useful.

For homelab hosts, a middle ground works better:

**1. Low swappiness** — Set swappiness to 1 or 10 so swap is used only as emergency buffer:

```bash
sysctl vm.swappiness=10
echo "vm.swappiness=10" > /etc/sysctl.d/99-swap.conf
```

**2. Disable swap per-container** — Prevent individual containers from swapping by setting `--memory-swap` equal to `--memory` as shown earlier. This keeps the host-level swap available for non-container processes.

**3. ZRAM as compressed swap** — For hosts with limited RAM (8-16 GB), compressed swap in RAM is a net win:

```bash
modprobe zram
echo lz4 > /sys/block/zram0/comp_algorithm
echo 2G > /sys/block/zram0/disksize
mkswap /dev/zram0
swapon /dev/zram0
```

Persist via `/etc/systemd/zram-generator.conf`:

```ini
[zram0]
zram-size = ram / 4
compression-algorithm = lz4
```

Install `systemd-zram-generator` on Ubuntu 24.04+:

```bash
apt install systemd-zram-generator
systemctl enable --now systemd-zram-generator
```

ZRAM compresses idle process memory pages, effectively doubling usable memory for burst workloads without the latency penalty of disk-backed swap.

## Kernel and Sysctl Memory Hardening

The kernel's virtual memory subsystem has several knobs that affect OOM behavior. These settings harden the host against runaway memory consumption:

```bash
cat > /etc/sysctl.d/99-docker-memory.conf << 'EOF'
# Disable memory overcommit — reject allocations that would exceed RAM + swap
vm.overcommit_memory = 2
vm.overcommit_ratio = 90

# Low swappiness — prefer page cache reclaim over swap
vm.swappiness = 10

# Reserve 64 MB for critical kernel allocations
vm.min_free_kbytes = 65536

# Reduce dentry/inode cache pressure — keep cached filesystem metadata
vm.vfs_cache_pressure = 50

# Allow enough PIDs for dozens of containers
kernel.pid_max = 4194304
EOF

sysctl -p /etc/sysctl.d/99-docker-memory.conf
```

**vm.overcommit_memory=2** is the most impactful. When set to 2 (strict overcommit), the kernel refuses memory allocations that would exceed `RAM × overcommit_ratio + swap`. Applications that try to malloc more than available memory get a clean `ENOMEM` error instead of crashing into swap death and eventual OOM. Databases handle ENOMEM gracefully; random OOM kills do not.

## Verification — Confirm All Protections Are Active

After applying everything, verify your setup:

```bash
# Check oomd status
systemctl is-active systemd-oomd && echo "OOMD active"

# Check earlyoom status
systemctl is-active earlyoom && echo "Earlyoom active"

# Check oom_score_adj on critical containers
for c in postgres redis prometheus nginx; do
  pid=$(docker inspect -f '{{.State.Pid}}' "$c" 2>/dev/null)
  [ -n "$pid" ] && echo "$c: $(cat /proc/$pid/oom_score_adj)"
done

# Check memory limits on running containers
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}"

# Check kernel parameters
sysctl vm.overcommit_memory vm.swappiness vm.min_free_kbytes

# Monitor OOM killer activity
dmesg | grep -i "oom-killer" | tail -5

# Check cgroup v2 memory limits
cat /sys/fs/cgroup/system.slice/docker-*.scope/memory.max 2>/dev/null | head -5

# Check memory pressure
cat /proc/pressure/memory
```

For Prometheus monitoring, add the `node_memory_oom_kills_total` metric to your Grafana dashboard. Any value above zero means you need to tighten limits or add RAM.

## Summary — Five Layers of OOM Defense

| Layer | Tool | What It Does |
|-------|------|-------------|
| 1 | Docker `deploy.resources.limits.memory` | Caps per-container memory, triggers in-Docker OOM |
| 2 | systemd-oomd | Kills entire cgroups at 60%+ memory pressure |
| 3 | earlyoom | SIGTERM-first preemptive kill below 5% free memory |
| 4 | oom_score_adj | Biases kernel choices toward non-critical containers |
| 5 | Kernel sysctls | Prevents overcommit, reserves memory, limits swap eagerness |

A Docker homelab host without memory limits is one `stress-ng` away from an unrecoverable freeze. Apply these configurations once, and your Postgres databases, Prometheus instances, and reverse proxies stay running even when a container goes rogue.

The kernel OOM killer is a last resort, not a memory management strategy.
