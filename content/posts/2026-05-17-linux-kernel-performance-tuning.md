---
title: "Linux Kernel Performance Tuning — sysctl Optimizations for Homelab Servers"
description: "Practical Linux kernel performance tuning for homelab servers — TCP BBR, sysctl network optimizations, I/O schedulers, memory management, and CPU governor tuning with real benchmarks and configuration files."
date: 2026-05-17T17:00:00-04:00
tags:
  - linux
  - performance
  - networking
  - systemd
keywords:
  - Linux kernel performance tuning homelab
  - TCP BBR congestion control sysctl
  - Linux server network stack optimization
  - sysctl performance tuning parameters
  - Linux I/O scheduler NVMe SSD optimization
  - CPU frequency scaling governor performance
  - Linux memory management vm swappiness tuning
summary: "Tune your Linux server kernel for maximum throughput and low latency. Covers TCP BBR, network buffer tuning, I/O schedulers, memory management, and CPU governor configuration with real config files and benchmarks."
canonical: "https://gntech.dev/posts/linux-kernel-performance-tuning/"
---

The Linux kernel ships with conservative defaults designed to work
reliably on a Raspberry Pi and a 128-core server alike. Those defaults
leave significant performance on the table — especially for homelab
servers running Docker, Proxmox, or network-heavy workloads.

This guide covers the kernel parameters that make the biggest
difference for homelab workloads, with production-grade configuration
files you can drop in and deploy immediately.

---

## Before You Tune: Establish a Baseline

You cannot improve what you do not measure. Capture your current state
before making any changes:

```bash
# Current sysctl values (all network-related)
sysctl -a | grep -E 'net\.(core|ipv4|ipv6)' | sort > baseline-net.txt

# TCP connection statistics
ss -s > baseline-ss.txt

# Network interface counters
ip -s link show eth0 > baseline-eth0.txt

# Current TCP congestion control
sysctl net.ipv4.tcp_congestion_control

# Simple throughput test (run on two machines)
# Receiver:
iperf3 -s
# Sender:
iperf3 -c <RECEIVER_IP> -t 30 -P 4
```

Save these outputs somewhere you can reference later. "Feels faster"
is not a performance improvement — hard numbers are.

---

## Network Stack Tuning: The Biggest Wins

The network stack is where kernel tuning has the most dramatic impact
for most homelab servers. These changes affect everything from Docker
container networking to NFS transfers and reverse proxy throughput.

### TCP Buffer Sizes

TCP socket buffers are the single most impactful setting for
high-throughput workloads. The default maximum is often 4 MB — far too
small for modern gigabit links with real-world latency.

Create `/etc/sysctl.d/90-network-performance.conf`:

```ini
# Maximum socket receive/send buffer size
# 128 MB for 10 Gbps links, 64 MB for 1 Gbps
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864

# TCP receive buffer: min, default, max (bytes)
net.ipv4.tcp_rmem = 4096 131072 67108864

# TCP send buffer: min, default, max (bytes)
net.ipv4.tcp_wmem = 4096 65536 67108864

# Allow auto-tuning of receive buffers
net.ipv4.tcp_moderate_rcvbuf = 1
```

On a 1 Gbps link with 10 ms RTT, the bandwidth-delay product is
about 1.25 MB. With 64 MB max buffers, you have headroom for burst
traffic and concurrent connections without bottlenecking.

### TCP BBR Congestion Control

BBR (Bottleneck Bandwidth and Round-trip propagation time) is
Google's model-based congestion control algorithm. It significantly
outperforms CUBIC on links with packet loss — which describes most
real-world internet connections.

```ini
# Switch to BBR congestion control
net.ipv4.tcp_congestion_control = bbr

# BBR requires fair queueing for pacing
net.core.default_qdisc = fq

# Disable slow start after idle (keep pipe full)
net.ipv4.tcp_slow_start_after_idle = 0
```

Verify it is active:

```bash
sysctl net.ipv4.tcp_congestion_control
# Output: net.ipv4.tcp_congestion_control = bbr

# Check which connections use BBR
ss -ti | head -20
```

On a 1 Gbps link with 1% packet loss, BBR delivers roughly 890 Mbps
versus ~520 Mbps for CUBIC. For homelab servers with Docker registries,
media streaming, or remote backups, this is a free throughput upgrade.

### Connection Handling for High-Concurrency Workloads

If you run a reverse proxy (Traefik, Nginx), database server, or any
service handling many concurrent connections, the default backlog and
TIME_WAIT settings will drop connections before you saturate the CPU.

```ini
# Increase the accept queue length
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Increase the device input packet backlog
net.core.netdev_max_backlog = 250000

# Reuse TIME_WAIT sockets for new connections (essential for proxies)
net.ipv4.tcp_tw_reuse = 1

# Reduce TIME_WAIT duration (default: 60 seconds)
net.ipv4.tcp_fin_timeout = 15

# Raise the TIME_WAIT bucket limit
net.ipv4.tcp_max_tw_buckets = 2000000
```

> **Warning:** Do not set `tcp_fin_timeout` below 15. On lossy networks,
> values under 15 can cause data corruption. Also, `tcp_tw_recycle` was
> removed in Linux 4.12 — it never worked safely behind NAT.

### Expand the Ephemeral Port Range

Every outbound TCP connection from your server uses a local ephemeral
port. The default range of 32768–60999 gives you about 28,000 ports.
For a Docker host running 50 containers with outbound connections, or
a reverse proxy making many upstream requests, this exhausts quickly.

```ini
# Maximize the ephemeral port range
net.ipv4.ip_local_port_range = 1024 65535
```

Monitor exhaustion:

```bash
# Check TIME-WAIT counts every few minutes
watch -n 30 'ss -s | grep -i timewait'

# If TIME-WAIT consistently exceeds 30,000, you are close to exhaustion
```

### TCP Keepalive for Persistent Connections

Databases, WebSockets, and long-lived TCP connections need keepalive
to detect dead peers. The default takes over two hours to time out a
dead connection.

```ini
# Start keepalive after 60 seconds of idle (default: 7200)
net.ipv4.tcp_keepalive_time = 60

# Probe interval: 10 seconds
net.ipv4.tcp_keepalive_intvl = 10

# Dead connection after 6 failed probes
net.ipv4.tcp_keepalive_probes = 6
```

Dead connection detection drops from 2 hours to 2 minutes. This is
especially important with Docker overlay networks and VPN tunnels.

### Complete Network Configuration File

Save all of the above as `/etc/sysctl.d/90-network-performance.conf`:

```ini
# /etc/sysctl.d/90-network-performance.conf
# Apply: sudo sysctl -p /etc/sysctl.d/90-network-performance.conf

# TCP buffers
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 131072 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.ipv4.tcp_moderate_rcvbuf = 1

# BBR congestion control
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
net.ipv4.tcp_slow_start_after_idle = 0

# Connection handling
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 250000
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_max_tw_buckets = 2000000

# Ephemeral ports
net.ipv4.ip_local_port_range = 1024 65535

# Keepalive
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# Network memory
net.ipv4.tcp_mem = 786432 1048576 16777216
net.ipv4.tcp_fastopen = 3
```

Apply it:

```bash
sudo sysctl -p /etc/sysctl.d/90-network-performance.conf
```

---

## NIC Hardware Tuning

Software tuning helps, but the NIC itself has tuning knobs too.

### Ring Buffer Sizes

NIC ring buffers are hardware queues between the network and kernel.
If the ring fills up, packets get dropped.

```bash
# Check current ring buffer sizes
ethtool -g eth0

# Increase for better burst handling
sudo ethtool -G eth0 rx 4096 tx 4096

# Monitor drops
ethtool -S eth0 | grep -E '(drop|error|miss)' | grep -v ': 0'
```

Make the change permanent by adding it to a systemd oneshot unit or
`/etc/rc.local`.

### Receive Packet Steering (RPS)

RPS distributes packet processing across CPU cores. Without it, a
single interrupt line can pin one core at 100% while others sit idle.

```bash
# For a 4-core system, enable RPS on all RX queues
for i in /sys/class/net/eth0/queues/rx-*/rps_cpus; do
  echo "f" | sudo tee "$i"
done

# Value is a CPU bitmask in hex:
# f = CPUs 0-3, ff = CPUs 0-7, ffff = CPUs 0-15
```

### Verify irqbalance

```bash
# irqbalance should distribute NIC interrupts across CPUs
sudo systemctl status irqbalance

# Check interrupt distribution
cat /proc/interrupts | grep eth0
```

---

## Memory Management Tuning

### vm.swappiness

Controls how aggressively the kernel swaps application memory versus
filesystem cache. The default of 60 means the kernel starts swapping
well before it needs to. For homelab servers with sufficient RAM,
lower this to reduce swap pressure on Docker containers and VMs.

```bash
# Create /etc/sysctl.d/90-memory-performance.conf
echo "vm.swappiness = 10" | sudo tee /etc/sysctl.d/90-memory-performance.conf
echo "vm.vfs_cache_pressure = 50" | sudo tee -a /etc/sysctl.d/90-memory-performance.conf
sudo sysctl -p /etc/sysctl.d/90-memory-performance.conf
```

- **vm.swappiness = 10** — Only swap under extreme memory pressure
- **vm.vfs_cache_pressure = 50** — Retain dentry/inode caches longer
  (good for file servers and Docker image layers)

### Dirty Page Writeback

Controls how long the kernel delays writing dirty pages to disk.
Tune these if you experience I/O stalls during large writes.

```ini
# /etc/sysctl.d/90-memory-performance.conf (add these)

# Start background writeback at 20% dirty pages (default: 10%)
vm.dirty_background_ratio = 20

# Block foreground writes at 50% dirty pages (default: 30%)
vm.dirty_ratio = 50

# Old data must flush every 30 seconds (default: 30, fine for HDD)
vm.dirty_expire_centisecs = 3000

# Background flusher wakes every 5 seconds (default: 5)
vm.dirty_writeback_centisecs = 500
```

For servers with SSDs or NVMe drives, consider more aggressive
settings since write latency is low:

```ini
vm.dirty_background_ratio = 5
vm.dirty_ratio = 20
vm.dirty_expire_centisecs = 500
vm.dirty_writeback_centisecs = 100
```

This flushes writes to NVMe storage quickly, reducing the risk of
data loss on crash and keeping the page cache clean.

---

## I/O Scheduler Tuning

The I/O scheduler sits between the block layer and the storage device.
The right choice depends on your hardware.

```bash
# Check current scheduler
cat /sys/block/nvme0n1/queue/scheduler
# Output example: [none] mq-deadline  kyber

# Check for NVMe
cat /sys/block/nvme0n1/queue/rotational
# 0 = SSD/NVMe, 1 = HDD
```

**Recommended scheduler by hardware type:**

| Storage | Scheduler | Rationale |
|---------|-----------|-----------|
| NVMe | none | NVMe controllers handle their own queuing (up to 64K commands). Adding the kernel scheduler overhead only slows things down. |
| SATA SSD | mq-deadline | Low overhead, good latency bounds. Avoids starvation on mixed read/write workloads. |
| HDD (spinning) | mq-deadline or bfq | Deadline prevents seek starvation. BFQ provides better fairness for shared disks. |

Set the scheduler persistently:

```bash
# For NVMe
echo 'ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"' \
  | sudo tee /etc/udev/rules.d/60-iosched.rules

# For SATA SSD
echo 'ACTION=="add|change", KERNEL=="sd*[!0-9]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"' \
  | sudo tee -a /etc/udev/rules.d/60-iosched.rules

# Reload udev
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Additional Block Layer Tuning

```bash
# Increase the max number of segments in a single I/O request
# Improves throughput for large sequential transfers (backups, media)
echo 1024 | sudo tee /sys/block/nvme0n1/queue/max_sectors_kb
echo 1024 | sudo tee /sys/block/nvme0n1/queue/read_ahead_kb
```

---

## CPU Frequency Scaling

Most Linux servers ship with the `powersave` or `ondemand` governor by
default. For homelab workloads, `performance` eliminates latency
variation from frequency transitions.

```bash
# Check current governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Set to performance (immediate)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

Make it persistent via systemd:

```bash
sudo tee /etc/systemd/system/cpu-performance.service << 'EOF'
[Unit]
Description=Set CPU governor to performance
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now cpu-performance.service
```

> The power cost of `performance` is minimal on modern servers at
> idle — the CPU still enters C-states when idle. The difference shows
> under load, where frequency transitions are eliminated.

---

## Docker-Specific Tuning

Docker containers inherit kernel parameters from the host. The
following sysctl settings benefit Docker hosts specifically:

```ini
# /etc/sysctl.d/90-docker-performance.conf
# Apply: sudo sysctl -p /etc/sysctl.d/90-docker-performance.conf

# Increase connection tracking table (Docker overlay networks)
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# User namespace limits for Docker
kernel.keys.maxkeys = 20000
kernel.keys.maxbytes = 2000000

# Max number of open files (containers each have file descriptors)
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
```

---

## Verifying Everything

After applying all configuration, validate that it stuck:

```bash
# Quick sysctl audit
echo "=== TCP BBR ==="
sysctl net.ipv4.tcp_congestion_control
echo "=== Buffer sizes ==="
sysctl net.core.rmem_max net.core.wmem_max
echo "=== Backlog ==="
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog
echo "=== Keepalive ==="
sysctl net.ipv4.tcp_keepalive_time
echo "=== VM ==="
sysctl vm.swappiness vm.vfs_cache_pressure
echo "=== I/O Scheduler ==="
cat /sys/block/nvme0n1/queue/scheduler
echo "=== CPU Governor ==="
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo "=== File max ==="
sysctl fs.file-max

# Network throughput comparison
iperf3 -c <SECOND_SERVER_IP> -t 30 -P 4
```

Compare the iperf3 results against your baseline. On a homelab server
with BBR and tuned buffers, you should see 15-40% throughput
improvement depending on link quality.

---

## Reverting Changes Safely

If a parameter causes problems, you have options:

```bash
# Remove a single config file
sudo rm /etc/sysctl.d/90-network-performance.conf
sudo sysctl --system

# Or override a single parameter temporarily
sudo sysctl -w net.core.rmem_max=212992
```

All sysctl changes are live immediately and survive reboot if saved to
`/etc/sysctl.d/*.conf`. The `--system` flag reloads all config files
in the correct precedence order.

---

## Summary

The Linux kernel's conservative defaults leave significant performance
on the table for homelab servers. The most impactful changes in order
of benefit:

1. **TCP BBR + buffer tuning** — Free throughput improvement on any link
2. **TIME_WAIT reuse + port range** — Prevents connection exhaustion
3. **I/O scheduler to none (NVMe)** — Removes unnecessary overhead
4. **CPU performance governor** — Eliminates latency variance
5. **Memory management** — Reduces swap pressure for containers

These configs have been tested on Ubuntu 24.04 / Debian 12 with kernel
6.x and work identically on Proxmox hosts (the underlying Debian
kernel) and container-optimized Linux distributions.
