---
title: "WireGuard Performance Tuning — Kernel sysctl and MTU Optimization"
description: "Maximize WireGuard VPN throughput on Linux with kernel sysctl tuning, BBR congestion control, UDP buffer optimization, MTU/MSS clamping, and iperf3 benchmarking — practical configurations for homelab and production."
date: 2026-05-20T14:30:00-04:00
tags:
  - wireguard
  - vpn
  - linux
  - performance
  - networking
keywords:
  - WireGuard performance tuning Linux kernel sysctl
  - WireGuard UDP buffer size optimization
  - BBR congestion control WireGuard VPN throughput
  - WireGuard MTU MSS clamping configuration
  - WireGuard NAPI polling budget tuning
  - iperf3 WireGuard benchmarking methodology
  - Linux kernel network stack optimization VPN
summary: "A practical guide to maximizing WireGuard throughput on Linux — covering kernel sysctl tuning, BBR congestion control, UDP buffer sizes, MTU/MSS clamping, NAPI polling optimization, and proper benchmarking with iperf3."
canonical: "https://blog.gntech.me/posts/wireguard-kernel-performance-tuning/"
---

WireGuard is already the fastest general-purpose VPN protocol available,
but default Linux kernel settings are tuned for desktop workloads, not
high-throughput encrypted UDP forwarding. If you're routing 1 Gbps+
through a WireGuard tunnel and seeing CPU spikes, packet drops, or
asymmetric performance, the bottleneck is almost never WireGuard itself
— it's the kernel's conservative defaults for UDP buffering, congestion
control, and interrupt handling.

This guide walks through every high-impact tuning parameter, provides
copy-paste configurations for homelab and production scales, and shows
you how to benchmark properly so you can measure your gains.

## Why Default Linux Settings Limit WireGuard Throughput

WireGuard runs in kernel space (since Linux 5.6) as a virtual network
interface. Traffic enters the interface, gets encrypted with
ChaCha20-Poly1305, and exits as UDP packets on the real NIC. The kernel
path is:

```
Application → wg0 (encrypt) → eth0 (UDP out) → Network
```

Three things can go wrong with stock settings:

1. **UDP receive buffers too small** — the kernel drops packets before
   WireGuard can decrypt them under high throughput
2. **CUBIC congestion control** — designed for long-fat TCP networks,
   not UDP tunnels carrying TCP-over-TCP traffic
3. **NAPI polling budget too low** — the kernel yields the CPU before
   draining the NIC ring buffer, causing drops during bursts

Each of these has a direct sysctl fix.

## Step 1 — Benchmark Your Baseline (Before Touching Anything)

Never tune blind. Establish a baseline so you can compare before/after.

Install iperf3 on both ends:

```bash
sudo apt install iperf3   # Debian/Ubuntu
sudo dnf install iperf3   # Fedora/RHEL
```

Start the server on the remote endpoint:

```bash
iperf3 -s -B 10.0.0.1   # bind to WireGuard tunnel IP
```

Run a single-stream test from the client:

```bash
iperf3 -c 10.0.0.1
```

Then a parallel-stream test to assess multi-core scaling:

```bash
iperf3 -c 10.0.0.1 -P 4
```

Test the reverse direction (often asymmetric with default settings):

```bash
iperf3 -c 10.0.0.1 -R
```

Record the single-stream, parallel, and reverse results. If your
parallel test is significantly faster than single-stream, you have
headroom to gain by tuning. If they're identical, you're hitting a
per-flow bottleneck — likely MTU fragmentation or UDP buffer drops.

Also check for retransmits and packet drops during the test:

```bash
ip -s link show wg0
ip -s link show eth0
```

High `RX errors` or `dropped` on the real NIC under WireGuard load is
your first red flag.

## Step 2 — sysctl Configuration for WireGuard Performance

Create `/etc/sysctl.d/99-wireguard.conf` with the following
optimizations. Apply with `sysctl --system` after editing.

### UDP Buffer Sizes — The Single Biggest Win

```ini
# /etc/sysctl.d/99-wireguard.conf
# Increase max UDP buffer sizes to 16 MB
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144

# UDP memory allocation — minimum, pressure, and max (bytes × pages)
net.ipv4.udp_mem = 4096 87380 16777216
```

The default `rmem_max` on most distros is 212 KB — completely
inadequate for 1 Gbps WireGuard tunnels. With a 16 MB buffer, the
kernel can queue incoming encrypted packets while WireGuard processes
them, eliminating drops during traffic bursts.

### BBR Congestion Control — Better Than CUBIC for VPN Tunnels

```ini
# Use BBR with fq (fair queue) qdisc
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

BBR (Bottleneck Bandwidth and Round-trip propagation time) is
significantly less sensitive to packet loss than CUBIC. This matters
because TCP-over-TCP inside a WireGuard tunnel amplifies loss — a
single dropped encrypted UDP packet can trigger retransmits in *both*
the inner and outer TCP stacks. BBR minimizes this by pacing based on
measured bandwidth and RTT rather than packet loss signals.

Verify BBR is active:

```bash
sysctl net.ipv4.tcp_congestion_control
# net.ipv4.tcp_congestion_control = bbr
```

### IP Forwarding and Connection Tracking

```ini
# Required for routing traffic through the tunnel
net.ipv4.ip_forward = 1

# Increase connection tracking max (tune based on concurrent users)
net.netfilter.nf_conntrack_max = 131072
```

WireGuard itself is stateless, but if you're using iptables/nftables
masquerading for egress traffic through the tunnel, conntrack tracks
every connection. At 100+ concurrent devices, the default of 65536 may
fill up, causing new connections to be dropped.

### NAPI Polling Budget — Handle Traffic Bursts

```ini
# Allow CPU to process more packets per polling cycle
net.core.netdev_budget = 600
net.core.netdev_budget_usecs = 4000

# Increase NIC input queue and listen backlog
net.core.netdev_max_backlog = 5000
net.core.somaxconn = 8192
```

`netdev_budget` defaults to 300 packets per SoftIRQ cycle. Under heavy
WireGuard load, 10 Gbps NICs can deliver thousands of packets in a
single interrupt. Increasing to 600 (and up to 1200 for 10 Gbps+)
prevents the network stack from yielding before the NIC buffer is
drained.

Apply the config:

```bash
sudo sysctl --system
```

## Step 3 — MTU and MSS Clamping

MTU mismatches are the most common cause of "slow WireGuard" that isn't
actually WireGuard's fault. WireGuard adds 60 bytes of overhead (20
IP + 8 UDP + 32 ChaCha20-Poly1305) per packet. Standard Ethernet MTU
of 1500 bytes leaves 1440 bytes for payload — but if your path has
lower MTU (PPPoE adds 8 bytes, GRE tunnels add more), packets
fragment.

### Find the Correct MTU

From the WireGuard server, ping the client with DF (Don't Fragment):

```bash
ping -M do -s 1472 -c 5 10.0.0.2
```

Start at 1472 (1500 − 28 for ICMP header) and decrease by 8 until you
get no fragmentation. Subtract 60 for the WireGuard overhead.

Common MTU values:

| Network type      | Interface MTU | WireGuard MTU |
|-------------------|---------------|---------------|
| Standard Ethernet | 1500          | 1420          |
| PPPoE             | 1492          | 1412          |
| PPPoE + VLAN      | 1488          | 1408          |
| Jumbo frames      | 9000          | 8920          |

Set it in your WireGuard interface config:

```ini
[Interface]
PrivateKey = ...
Address = 10.0.0.1/24
MTU = 1420   # <- adjust based on your path MTU
```

### MSS Clamping for TCP Traffic

If you're routing entire subnets through WireGuard (not just the tunnel
endpoints), TCP connections may not honor the tunnel MTU. Clamp MSS at
the firewall:

```bash
sudo iptables -t mangle -A FORWARD -o wg0 -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --clamp-mss-to-pmtu
```

For nftables:

```nftables
table inet mangle {
    chain forward {
        type filter hook forward priority mangle; policy accept;
        oifname "wg0" tcp flags syn tcp option maxseg size set rt mtu
    }
}
```

This forces the TCP MSS to fit inside the WireGuard tunnel MTU,
eliminating fragmentation entirely.

## Step 4 — Verify GRO/GSO Offloads Are Enabled

Generic Receive Offload (GRO) and Generic Segmentation Offload (GSO)
batch packets before handing them to WireGuard, reducing per-packet CPU
cost significantly. Verify they're enabled on the physical NIC:

```bash
ethtool -k eth0 | grep -E 'gro|gso|tso'
```

You want to see:

```
gro: on
gso: on
tso: on
```

If any are off, enable them:

```bash
sudo ethtool -K eth0 gro on gso on tso on
```

On some NICs (especially virtualized ones in Proxmox/VMware), these
offloads may be disabled or unsupported. If they can't be enabled, you
lose some batching efficiency — but the sysctl tuning above still
helps significantly.

## Step 5 — CPU Scaling Governor

WireGuard's ChaCha20-Poly1305 encryption is CPU-bound. If your CPU
frequency governor is set to `powersave` or `ondemand`, the kernel may
downclock cores under light load, causing throughput drops when a burst
arrives.

Set the governor to `performance` during benchmarking:

```bash
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

For permanent use, install `cpufrequtils` or configure `tlp`/`power-profiles-daemon`
to keep cores at max frequency while WireGuard is active. In a
homelab context, the power savings from downclocking are negligible
compared to the throughput cost.

## Step 6 — Re-Benchmark with Tuned Configuration

After applying all changes, run the same iperf3 tests from Step 1:

```bash
# Single stream
iperf3 -c 10.0.0.1

# Parallel streams
iperf3 -c 10.0.0.1 -P 4

# Reverse direction
iperf3 -c 10.0.0.1 -R
```

Expected improvements on a 1 Gbps link:

| Metric                       | Before (defaults) | After (tuned) |
|------------------------------|-------------------|---------------|
| Single-stream TCP upload     | 300-500 Mbps      | 700-950 Mbps  |
| Parallel-stream TCP upload   | 400-600 Mbps      | 900-940 Mbps  |
| Reverse direction (download) | 80-200 Mbps       | 700-900 Mbps  |

The reverse direction improvement is often the most dramatic — default
receive buffers starve the download path because the kernel can't queue
incoming encrypted packets fast enough.

## Common Pitfalls

**Don't tune both sides asymmetrically.** Apply the same sysctl config
on the server and all major clients for consistent behavior.

**Don't use `wg-quick` MTU unless you know your path MTU.** `wg-quick`
defaults to 1420, which works for most Ethernet paths but may need
reduction for PPPoE, cellular, or tunnel-over-tunnel paths.

**TCP-over-TCP is real.** If you're doing massive file transfers over
WireGuard, consider using UDP-based protocols (rsync over SSH with
`-e "nc -u"`, or UDP-based file transfer tools) to avoid nested
congestion control fighting itself.

**Systemd's `sysctl` persistence.** The config file in
`/etc/sysctl.d/` persists across reboots. Verify with
`sysctl --system` after boot.

## Complete Config File — Copy and Apply

```ini
# /etc/sysctl.d/99-wireguard.conf
# WireGuard kernel performance tuning — homelab scale (10-50 clients)

# UDP buffers — eliminate drops under load
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.ipv4.udp_mem = 4096 87380 16777216

# BBR congestion control
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Routing and conntrack
net.ipv4.ip_forward = 1
net.netfilter.nf_conntrack_max = 131072

# NAPI and buffer tuning
net.core.netdev_budget = 600
net.core.netdev_budget_usecs = 4000
net.core.netdev_max_backlog = 5000
net.core.somaxconn = 8192
```

Apply with `sudo sysctl --system`, set your WireGuard MTU to the
correct value after a path MTU discovery, clamp MSS on the forward
chain, and run your benchmarks. You should see 80-95% of line rate over
WireGuard on modern hardware — the same as what a direct connection
delivers.
