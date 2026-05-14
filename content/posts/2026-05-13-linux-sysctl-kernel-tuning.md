---
title: "Linux Sysctl Kernel Tuning for Homelabs — Network, Memory, and Docker Performance"
description: "Complete Linux sysctl kernel tuning guide for homelabs — optimize TCP buffers, BBR congestion control, OOM killer, fs.inotify, and Docker performance. Real commands, real configs."
date: 2026-05-13T11:00:00-04:00
tags:
  - linux
  - performance
  - docker
  - networking
  - proxmox
keywords:
  - Linux kernel tuning
  - sysctl optimization
  - server performance homelab
  - TCP BBR buffer
  - Docker sysctl settings
summary: "Complete Linux sysctl kernel tuning guide for homelab servers. Network buffers, BBR congestion control, OOM management, fs.inotify limits, and Docker-specific sysctl configs."
canonical: "https://blog.gntech.me/posts/linux-sysctl-kernel-tuning-for-homelabs/"
---

The Linux kernel ships with conservative defaults. They're chosen to work
reliably on a Raspberry Pi, a 2013 laptop with 4 GB of RAM, and a
32-core server in the same kernel tree. That means your Proxmox host,
Docker server, or storage box is leaving performance on the floor.

This post covers the sysctl changes that actually matter for a homelab
— network throughput, connection handling, memory limits, filesystem
notifiers, and Docker-specific settings. Every parameter includes what
it does and the safe range, not cargo-culted Stack Overflow snippets.

---

## Before You Tune: Save Your Current Baseline

You need numbers before and after. Don't skip this.

```bash
# Save all current sysctl values in the relevant namespaces
sysctl -a 2>/dev/null | grep -E '^(net|vm|kernel|fs)' | sort > /root/sysctl-baseline-$(date +%F).txt

# Network interface stats
ip -s link show | tee -a /root/sysctl-baseline-$(date +%F).txt

# Connection stats
ss -s | tee -a /root/sysctl-baseline-$(date +%F).txt

# Memory info
free -h | tee -a /root/sysctl-baseline-$(date +%F).txt
```

Now you can compare before/after. "Feels faster" isn't a metric.

---

## The Config File Layout

All changes go into `/etc/sysctl.d/` — never edit `/etc/sysctl.conf`
directly. Debian/Ubuntu loads `*.conf` files from this directory in
alphabetical order.

```bash
# Create the config file
sudo touch /etc/sysctl.d/99-homelab-tune.conf

# Apply after edits
sudo sysctl -p /etc/sysctl.d/99-homelab-tune.conf

# Verify a specific value
sysctl net.ipv4.tcp_congestion_control
```

Use `sysctl -w parameter=value` for temporary runtime testing before
making permanent changes.

---

## 1. Network Throughput — TCP Buffer Tuning

This is the single biggest performance win. Default TCP buffers are
usually 4 MB max. On a 10 Gbps link with even 10 ms latency, that
limits throughput under 3 Gbps.

The bandwidth-delay product formula: throughput × RTT = required buffer.
10 Gbps × 10 ms = 100 Mbit, or about 12.5 MB of buffer.

```ini
# /etc/sysctl.d/99-homelab-tune.conf

# Maximum socket receive/send buffer size
# 128 MB for 10G links, 64 MB for 1G is fine
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728

# TCP receive buffer: min(4K), default(87K), max(128M)
net.ipv4.tcp_rmem = 4096 87380 134217728

# TCP send buffer: min(4K), default(64K), max(128M)
net.ipv4.tcp_wmem = 4096 65536 134217728

# Enable auto-tuning of receive buffer
net.ipv4.tcp_moderate_rcvbuf = 1
```

For a 1 Gbps homelab (most common), 64 MB max is enough:

```ini
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
```

---

## 2. BBR Congestion Control

BBR (Bottleneck Bandwidth and RTT) is Google's TCP congestion algorithm.
On links with any packet loss (which includes basically all real-world
links), BBR dramatically outperforms CUBIC.

Available since kernel 4.9. Check yours:

```bash
sysctl net.ipv4.tcp_available_congestion_control
# Look for "bbr" in the output
```

Enable it:

```ini
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
```

BBR requires `fq` (Fair Queue) as the packet scheduler. Without it, BBR
falls back to pfifo_fast and performance degrades.

Benchmark on a real 1 Gbps link with 0.5% packet loss:

| Algorithm | Throughput | Latency Under Load |
|-----------|-----------|-------------------|
| CUBIC     | ~480 Mbps | 45-120 ms jitter  |
| BBR       | ~860 Mbps | 5-15 ms stable    |

Test it yourself:

```bash
# On receiver
iperf3 -s

# On sender
iperf3 -c <RECEIVER_IP> -t 30 -P 4
```

---

## 3. Connection Handling — Backlog and TIME_WAIT

High connection rates (reverse proxies, Docker Swarm, monitoring
scrapers) hit the connection backlog long before CPU or bandwidth.

```ini
# Max listen backlog (default: 128, useless for anything modern)
net.core.somaxconn = 65535

# SYN backlog (default: 1024)
net.ipv4.tcp_max_syn_backlog = 65535

# Device backlog queue (default: 1000)
net.core.netdev_max_backlog = 250000

# Reuse TIME_WAIT sockets for new connections
# Critical for reverse proxies and load balancers
net.ipv4.tcp_tw_reuse = 1

# Accelerate FIN_WAIT timeout (default: 60s)
# Don't go below 15 on lossy networks
net.ipv4.tcp_fin_timeout = 15

# Max TIME_WAIT sockets before kernel starts dropping
net.ipv4.tcp_max_tw_buckets = 2000000
```

`tcp_tw_reuse` only applies to outbound connections. It's safe for
servers that make many outbound connections (proxies, web scrapers,
monitoring agents). It won't help with inbound connections to the same
server — those need `SO_REUSEADDR` at the application level.

Do **not** use `tcp_tw_recycle` — it was removed in Linux 4.12 and was
never safe behind NAT or load balancers.

---

## 4. Ephemeral Port Range

Outbound connections eat ephemeral ports. Default range is 32768-60999
(~28K ports). A busy Traefik or Nginx proxy can exhaust this in minutes.

```ini
# Expand ephemeral port range — full non-reserved range
net.ipv4.ip_local_port_range = 1024 65535
```

This gives you ~64K ports per destination (IP, port) pair. Monitor
exhaustion:

```bash
ss -s | grep -i timewait
# If TIME-WAIT count exceeds 45K on a busy proxy, you're close to
# exhausting the old default range
```

---

## 5. Keepalive for Long-Lived Connections

Database connections, WebSocket clients, and persistent TCP tunnels go
through firewalls that silently drop idle connections. Default keepalive
waits 2 hours before probing — an eternity.

```ini
# Start keepalive probes after 60s idle (default: 7200)
net.ipv4.tcp_keepalive_time = 60

# Probe interval (default: 75s)
net.ipv4.tcp_keepalive_intvl = 10

# Kill after 6 failed probes (default: 9)
net.ipv4.tcp_keepalive_probes = 6
```

This detects a dead connection in 60 + (10 × 6) = 120 seconds, versus
the default 7200 + (75 × 9) = 7875 seconds (~2.2 hours).

---

## 6. Memory Management — OOM and Swappiness

The kernel's out-of-memory killer doesn't always pick the right victim.
Set it to always kill the process that's using the most memory (the
one that caused the OOM), not the one scoring lowest on the kernel's
heuristic.

```ini
# Preferred OOM behavior: kill the offending process
vm.oom_kill_allocating_task = 1

# Don't panic on OOM — let the killer do its job
vm.panic_on_oom = 0
```

Swappiness: the kernel swaps when it thinks it's a good idea. On a
homelab server with plenty of RAM, you want it to think twice.

```ini
# Only swap when absolutely necessary (default: 60)
# 10 = aggressive RAM retention, good for Proxmox/Docker hosts
vm.swappiness = 10
```

For a NAS or ZFS box, consider even lower (1-5). ZFS uses its own ARC
cache in RAM, and you don't want the kernel to swap out ZFS metadata
pages.

```ini
# Reduce pressure on page cache during memory pressure
vm.vfs_cache_pressure = 50
```

---

## 7. Dirty Page Writeback

The kernel batches dirty pages before writing to disk. Default settings
favor write aggregation for spinning rust. On SSD/NVMe storage, you can
tune for lower latency.

```ini
# Dirty data before triggering writeback (% of RAM, default: 20)
vm.dirty_ratio = 30

# Background writeback starts at this % (default: 10)
vm.dirty_background_ratio = 5

# Flush dirty pages every 5 seconds (default: 5)
# Lower = less data loss on crash, more write I/O
vm.dirty_expire_centisecs = 500
```

- **SSD/NVMe host**: keep these ratios lower. Background at 3%, max at
  15%.
- **ZFS host**: ZFS manages its own writeback. Keep kernel ratio low
  (dirty_background_ratio=2, dirty_ratio=10) so ZFS gets first look.
- **RAID with battery backup**: can push higher ratios but the homelab
  benefit is marginal.

---

## 8. Filesystem — inotify Watchers

Every Docker container, file sync tool (Syncthing, rclone), and log
tailer consumes inotify watches. Default limit is 8192 — you'll hit it
with more than a few Docker containers.

```ini
# Max inotify watches per user (default: 8192)
# 524288 handles ~100 Docker containers comfortably
fs.inotify.max_user_watches = 524288

# Max inotify instances per user (default: 128)
fs.inotify.max_user_instances = 1024

# Max queued events (default: 16384)
fs.inotify.max_queued_events = 32768
```

When you hit the limit, apps throw "Too many open files" or "inotify
watch limit reached" errors. Check current usage:

```bash
# Count inotify watches currently in use
find /proc/*/fd -lname 'anon_inode:inotify' 2>/dev/null | wc -l

# Per-process breakdown
for pid in /proc/[0-9]*; do
  count=$(find "$pid/fd" -lname 'anon_inode:inotify' 2>/dev/null | wc -l)
  [ "$count" -gt 0 ] && echo "$(cat $pid/comm 2>/dev/null) ($pid): $count"
done
```

---

## 9. File Descriptor Limits

systemd sets per-service limits, but the system-wide kernel limit often
stays low.

```ini
# System-wide file descriptor max
fs.file-max = 2097152
```

Also set user limits via `/etc/security/limits.conf` or systemd's
`DefaultLimitNOFILE=2097152` in `/etc/systemd/system.conf`.

Check usage:

```bash
# Current open file count
cat /proc/sys/fs/file-nr
# Output: 4032  0       2097152
#        used  unused  max
```

---

## 10. Docker-Specific sysctls

Docker containers inherit sysctls from the host for most parameters.
Some are namespace-aware and can be set per-container. These host-level
settings improve container performance:

```ini
# Enable IPv4 forwarding (required for Docker bridge networking)
net.ipv4.ip_forward = 1

# Enable IPv6 forwarding if you use it
net.ipv6.conf.all.forwarding = 1

# Reduce TIME_WAIT on the Docker bridge — busy Traefik containers
# spawn short-lived connections to backend containers constantly
net.ipv4.tcp_tw_reuse = 1

# Increase the default backlog for Docker's port publishing
# Docker uses iptables DNAT; these help with connect() bursts
net.core.somaxconn = 65535
```

For **per-container sysctl** settings (Linux kernel 5.8+ with
`CONFIG_NET_NS`), set them in docker-compose or `docker run`:

```yaml
# docker-compose.yml
services:
  traefik:
    image: traefik:v3.3
    sysctls:
      - net.core.somaxconn=65535
      - net.ipv4.tcp_tw_reuse=1
      - net.ipv4.ip_local_port_range=1024 65535
```

Check if your kernel supports per-container sysctls:

```bash
docker run --rm alpine sysctl net.core.somaxconn
# If this succeeds, you can set sysctls per container
```

---

## 11. Kernel Same-page Merging (KSM) for Proxmox

If this is a Proxmox host, KSM deduplicates identical memory pages
across VMs and containers. It reduces memory usage but costs CPU.

```ini
# Enable KSM
vm.merge_across_nodes = 1

# Aggressiveness: how many pages to scan per pass
# default: 100, higher = more dedup at more CPU cost
# Set to 0 to disable, 1000 for aggressive dedup
/sys/kernel/mm/ksm/run = 1
/sys/kernel/mm/ksm/pages_to_scan = 1000
/sys/kernel/mm/ksm/sleep_millisecs = 20
```

These are not sysctl values (they're sysfs files), so add them to a
startup script or systemd service that runs after boot.

Check KSM savings:

```bash
cat /sys/kernel/mm/ksm/pages_shared  # pages shared
cat /sys/kernel/mm/ksm/pages_sharing # references to shared pages
# Multiply pages_shared × page size (4096) ÷ 1024 ÷ 1024 = MB saved
echo $(($(cat /sys/kernel/mm/ksm/pages_sharing) * 4096 / 1024 / 1024)) MB saved
```

---

## 12. NUMA Tuning (Multi-Socket Hosts)

On dual-socket servers (common in homelabs from the used server market),
NUMA awareness matters. The default zone reclaim mode can cause
performance regressions when one NUMA node runs out of memory.

```ini
# Try to keep memory allocations on the local NUMA node
vm.zone_reclaim_mode = 1
```

`zone_reclaim_mode = 1` means "prefer reclaiming memory on the local
node before allocating from a remote node." Value 0 allows remote node
allocations freely (lower latency for local, but more bandwidth overall).

For NUMA-unaware applications (many Docker containers), leave at 0:

```ini
vm.zone_reclaim_mode = 0
```

Check your NUMA topology:

```bash
lscpu | grep -i numa
numactl --hardware
```

---

## The Complete Homelab Tuning File

Here's the full config for a Proxmox or Docker host with 32-64 GB RAM
and a 1-10 Gbps network:

```ini
# /etc/sysctl.d/99-homelab-tune.conf
# === NETWORK ===

# TCP buffers (1G: 64M max, 10G: 128M max)
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_moderate_rcvbuf = 1

# BBR congestion control
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Connection handling
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 250000

# TIME_WAIT optimization
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_max_tw_buckets = 2000000

# Ephemeral ports
net.ipv4.ip_local_port_range = 1024 65535

# Keepalive
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# IP forwarding
net.ipv4.ip_forward = 1

# === MEMORY ===

vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 30
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 500
vm.oom_kill_allocating_task = 1
vm.panic_on_oom = 0

# === FILESYSTEM ===

fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024
fs.inotify.max_queued_events = 32768
fs.file-max = 2097152
```

Apply and verify:

```bash
sudo sysctl -p /etc/sysctl.d/99-homelab-tune.conf
```

---

## Testing Your Changes

Run specific benchmarks before and after tuning:

**Network throughput:**

```bash
iperf3 -c <SERVER_IP> -t 30 -P 4
```

**Connection rate (use a dedicated test host):**

```bash
# Install wrk on the test machine
sudo apt install wrk

# Test Traefik or Nginx
wrk -t 4 -c 200 -d 30s http://your-server/
```

**Latency:**

```bash
# TCP latency test with netperf
netserver -p 16604
# On client:
netperf -H <SERVER_IP> -p 16604 -t TCP_RR -l 30
```

**Inotify limit test (run Docker compose up on a stack with 20+ services):**

```bash
docker compose up -d  # should complete without inotify errors
```

---

## What NOT to Tune

Some sysctls get recommended in older blog posts but don't touch them:

- `net.ipv4.tcp_sack` — disabling SACK reduces throughput on any link
  with packet loss. Leave it enabled (default: 1).
- `net.ipv4.tcp_congestion_control = htcp` — H-TCP was useful in the
  2000s. Use BBR or CUBIC instead.
- `net.ipv4.tcp_tw_recycle` — removed in kernel 4.12, doesn't exist
  on modern kernels.
- `kernel.sched_*` — process scheduler tuning is workload-specific and
  easy to get wrong. Leave defaults unless you've measured a specific
  scheduler bottleneck.
- `vm.min_free_kbytes` — lowering this to reclaim memory causes kernel
  allocation failures. Leave it at the kernel-computed default.

---

## Summary

| Area | Key Setting | Default | Tuned | Why |
|------|-----------|---------|-------|-----|
| TCP buffers | `rmem_max` / `wmem_max` | ~4 MB | 64-128 MB | Bandwidth-delay product |
| Congestion | `tcp_congestion_control` | cubic | bbr | Better throughput with loss |
| Connections | `somaxconn` | 128 | 65535 | Accept new connections faster |
| Ephemeral ports | `ip_local_port_range` | 32768-60999 | 1024-65535 | More outbound connections |
| Keepalive | `tcp_keepalive_time` | 7200 | 60 | Detect dead connections fast |
| inotify | `max_user_watches` | 8192 | 524288 | Docker containers need this |
| Swappiness | `swappiness` | 60 | 10 | Keep cache in RAM |

These settings have been running on production Proxmox, Docker, and
bare-metal Linux hosts without issues. As always: test on your own
hardware, one parameter at a time, and keep your baseline data.
