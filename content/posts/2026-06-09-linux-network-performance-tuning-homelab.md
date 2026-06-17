---
title: "Linux Network Performance Tuning — ethtool, irqbalance, and tc for Homelab"
description: "Optimize Linux network performance on Proxmox and Docker hosts with ethtool ring buffer tuning, irqbalance configuration, multiqueue RSS/RPS, and tc traffic shaping — with benchmarks and systemd persistence."
date: 2026-06-09T17:00:00-04:00
tags:
  - linux
  - networking
  - performance
  - homelab
  - docker
keywords:
  - Linux network performance tuning ethtool irqbalance homelab
  - ethtool ring buffer optimization Linux server network queue
  - irqbalance CPU affinity network interrupt configuration
  - tc traffic shaping Docker host bandwidth management
  - Linux network adapter tuning multiqueue RSS RPS
  - Proxmox host network performance optimization
  - network performance benchmarking iperf3 ethtool stats
summary: "Optimize Linux network performance on Proxmox and Docker hosts with ethtool ring buffer tuning, irqbalance configuration, multiqueue RSS/RPS, and tc traffic shaping — with real benchmarks and systemd persistence."
canonical: "https://blog.gntech.me/posts/linux-network-performance-tuning-homelab/"
---

## Why Stock Linux Network Settings Leave Performance on the Table

Out of the box, Ubuntu Server and Debian configure network interfaces conservatively. Ring buffers default to 256 descriptors, IRQ handlers land on whatever CPU core boots first, and interrupt coalescing favors compatibility over throughput. On a Proxmox host running 20 VMs, a Docker host serving NFS shares, or a media server streaming 4K transcodes, these defaults become measurable bottlenecks.

The three most common symptoms of untuned networking:

- **rx_missed_errors** or **rx_dropped** climbing in `ethtool -S` counters while under load
- **SoftIRQ** pegging a single CPU core to 100% while other cores sit idle
- **Inconsistent throughput** during iperf3 tests or NFS transfers

This guide walks through diagnosing each issue, applying the fix, and making changes persistent across reboots. Every command here works on Debian 12/13, Ubuntu 22.04/24.04, and Proxmox VE 8/9 hosts.

## Diagnosing Network Bottlenecks with ethtool

Before tuning anything, capture a baseline. Start with driver-level counters — these tell you exactly what the NIC hardware sees.

```bash
# Check for dropped or missed packets
ethtool -S eth0 | grep -E 'drop|miss|error|fail'
```

Look for counters rising during load. `rx_missed_errors` indicates the hardware ring buffer overflowed — the card had packets to deliver but no room in the ring. `rx_dropped` means the kernel dropped packets after the ring accepted them, usually due to socket buffer pressure.

Inspect current ring buffer sizes:

```bash
ethtool -g eth0
```

Output:

```
Ring parameters for eth0:
Pre-set maximums:
RX:             4096
RX Mini:        0
RX Jumbo:       0
TX:             4096
Current hardware settings:
RX:             256
TX:             256
```

The NIC supports 4096, but the kernel set 256. Your first tuning opportunity.

Check available queue counts and current configuration:

```bash
ethtool -l eth0
```

Output:

```
Channel parameters for eth0:
Pre-set maximums:
RX:             0
TX:             0
Other:          1
Combined:       4
Current hardware settings:
RX:             0
TX:             0
Other:          1
Combined:       1
```

The NIC supports 4 combined queues but only 1 is active. Each queue gets its own IRQ vector, so running 1 queue means one CPU core handles all RX and TX interrupts.

Check offload features:

```bash
ethtool -k eth0 | grep -E 'tcp|udp|generic|large|scatter|tx-checksum'
```

And run a simple baseline benchmark:

```bash
# Server side
iperf3 -s

# Client side
iperf3 -c 10.0.20.30 -t 30 -P 4
```

Record the results. After tuning, you will run the same test and compare.

## Ring Buffer Tuning for High Throughput

Ring buffers sit between the NIC hardware and the kernel networking stack. When a packet arrives, the NIC DMA-writes it into the ring, and the kernel reads from the ring. If the kernel falls behind — say, because storage IO is busy or another CPU is handling interrupts — the ring fills up and packets get dropped.

Modern 1GbE and 10GbE NICs support rings of 4096 or more descriptors. Doubling the default 256 to 4096 gives the kernel more headroom during bursts.

```bash
# Increase ring buffer sizes
ethtool -G eth0 rx 4096 tx 4096
```

Verify the change:

```bash
ethtool -g eth0
```

The tradeoff: larger rings improve throughput under load by reducing drops, but they increase per-packet latency because the kernel spends more time draining the ring. For homelab workloads (file serving, media streaming, backups), throughput matters more than microseconds of latency. For real-time applications like VoIP or gaming servers, keep rings at 1024 or lower.

To find your sweet spot, run iperf3 with the counter watch:

```bash
# Watch drops while running a test
watch -n 1 'ethtool -S eth0 | grep -E "miss|drop"'
```

If drops appear at 256 but disappear at 4096, you found the optimal setting.

### Making Ring Buffer Settings Persistent

ethtool changes do not survive a reboot. The standard approach is a systemd oneshot service:

```bash
cat <<'EOF' | sudo tee /etc/systemd/system/ethtool-tune.service
[Unit]
Description=Apply ethtool network tuning
After=network.target
Before=network-online.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -G eth0 rx 4096 tx 4096
ExecStart=/usr/sbin/ethtool -K eth0 gro on gso on tso on
ExecStart=/usr/sbin/ethtool -C eth0 rx-usecs 4 tx-usecs 4
RemainAfterExit=true
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ethtool-tune.service
```

For hosts with multiple interfaces, repeat the ExecStart lines for each, or use a script that iterates over `ip link show | grep -v lo | awk -F: '/^[0-9]/{print $2}'`.

## Multiqueue, RSS, RPS, and XPS Configuration

Network queue configuration is the most impactful single tuning you can do. A single queue means a single IRQ, which means one CPU core. On modern multi-core hosts, spreading RX and TX work across all cores dramatically improves throughput and reduces tail latency.

### RSS — Receive Side Scaling

RSS is hardware-level load balancing. The NIC distributes incoming packets across multiple RX queues using a hash of the IP header (or TCP 5-tuple). Each queue has its own IRQ vector.

Enable all available queues:

```bash
# Set combined queues to the maximum supported
ethtool -L eth0 combined 4
```

Verify:

```bash
ethtool -l eth0
```
```
Current hardware settings:
RX:             0
TX:             0
Other:          1
Combined:       4
```

Check IRQ distribution:

```bash
grep eth0 /proc/interrupts | sort -k1 -n
```

You should see one interrupt line per queue, each landing on a different CPU core. If they all land on the same core, irqbalance reassigns them automatically after a few seconds, or you can set affinity manually.

### RPS — Receive Packet Steering (Software RSS)

Not all NICs support multiple queues. VirtIO paravirtualized NICs in Proxmox VMs, older Realtek chips, and USB Ethernet adapters expose only one combined queue. RPS distributes packet processing across CPUs in software, after the single hardware queue delivers the packet.

Enable RPS on each RX queue by writing a CPU bitmask to `rps_cpus`. On a 4-core system (cores 0-3), the bitmask for all cores is `f`:

```bash
echo f | sudo tee /sys/class/net/eth0/queues/rx-0/rps_cpus
```

For each additional RX queue (if available):

```bash
for q in /sys/class/net/eth0/queues/rx-*; do
  echo f | sudo tee "$q"/rps_cpus
done
```

On a 8-core system with cores 2-7 isolated for networking, the bitmask is `fc`. Calculate bitmasks quickly:

```bash
# Bitmask for CPU 2,3,4,5,6,7
python3 -c "print(hex(int('11111100', 2)))"  # 0xfc
```

### XPS — Transmit Packet Steering

XPS is the TX-side analog of RPS. It binds TX queues to CPU cores so that transmit completions and subsequent TX processing happen on the same core:

```bash
for q in /sys/class/net/eth0/queues/tx-*; do
  echo f | sudo tee "$q"/xps_cpus
done
```

### RFS — Receive Flow Steering

RFS extends RPS by steering packets to the CPU where the application processing them is running. This improves cache locality. Enable it with:

```bash
# Increase flow table size
sudo sysctl -w net.core.rps_sock_flow_entries=32768

# Set flow count for each RX queue (1-2x rps_sock_flow_entries / queue count)
for q in /sys/class/net/eth0/queues/rx-*; do
  echo 8192 | sudo tee "$q"/rps_flow_cnt
done
```

### When Each Technique Applies

| Hardware | Recommended Approach |
|----------|---------------------|
| Intel i350/X710, Mellanox ConnectX, Broadcom NetXtreme | RSS (hardware) — set combined queues to max, verify IRQ spread |
| VirtIO (Proxmox VM), vmxnet3 (VMware) | RSS + RPS — enable virtio multiqueue driver in VM config |
| Realtek, USB Ethernet, single-queue NICs | RPS + XPS + RFS — software distribution only |

For Proxmox VMs, enable virtio multiqueue in the VM configuration:

```bash
# Per-vCPU queue pairs: set to match vCPU count
qm set <VMID> --args "-device virtio-net-pci,netdev=net0,mq=on,vectors=8"
```

Or for new VMs, include `multifunction=on`:

```bash
qm set <VMID> --numa 0 --args "-device virtio-net-pci,netdev=hostnet0,mq=on,vectors=12"
```

Now match the queue count inside the VM:

```bash
ethtool -L ens18 combined "$(nproc)"
```

## IRQ Balancing and CPU Pinning

`irqbalance` runs by default on Ubuntu Server and Debian and does a reasonable job of spreading IRQs across CPUs. But it rebalances periodically, which can cause jitter. For consistent performance, pin critical IRQs manually.

First, identify the IRQ numbers for your NIC:

```bash
grep eth0 /proc/interrupts
```

Output:

```
 28:        123   IO-APIC   28-fasteoi   eth0-0
 29:         45   IO-APIC   29-fasteoi   eth0-1
 30:         67   IO-APIC   30-fasteoi   eth0-2
 31:         89   IO-APIC   31-fasteoi   eth0-3
```

Pin each IRQ to a specific CPU core by writing the CPU bitmask:

```bash
# Core 0 for eth0-0, Core 1 for eth0-1, etc.
echo 1 > /proc/irq/28/smp_affinity
echo 2 > /proc/irq/29/smp_affinity
echo 4 > /proc/irq/30/smp_affinity
echo 8 > /proc/irq/31/smp_affinity
```

For dual-socket NUMA systems, pin to cores on the same NUMA node as the NIC's PCI slot:

```bash
# Find NUMA node of the NIC
cat /sys/class/net/eth0/device/numa_node

# Bitmask for all cores on node 0 (e.g., cores 0-7)
echo ff | tee /proc/irq/28/smp_affinity
```

If you keep irqbalance, ban critical IRQs from being rebalanced:

```bash
# Ban IRQs 28-31 from irqbalance
echo 28-31 > /proc/irq/28/irqbalance_ban
# Repeat for each banned IRQ or use --banirq
```

For more advanced setups, run irqbalance in oneshot mode — it configures affinity once on boot and exits:

```bash
# In /etc/default/irqbalance
IRQBALANCE_ONESHOT=yes
```

Or disable irqbalance entirely and manage affinities via a systemd service:

```bash
sudo systemctl disable --now irqbalance
```

Then add `echo` commands for each IRQ to the same `ethtool-tune.service` from the ring buffer section.

## Traffic Control for Docker Host Bandwidth Management

On a shared Docker host, one container running a backup or large download can saturate the uplink, starving other containers. Traffic control (tc) with HTB qdisc provides per-interface bandwidth limits.

Limit outbound traffic on `eth0` to 800 Mbps (80% of a 1 Gbps link, leaving overhead headroom):

```bash
# Remove existing qdisc
tc qdisc del dev eth0 root 2>/dev/null

# Add HTB root with default class
tc qdisc add dev eth0 root handle 1: htb default 10

# Root class — total bandwidth
tc class add dev eth0 parent 1: classid 1:1 htb rate 1000mbit

# Limit class — actual cap
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 800mbit ceil 800mbit
```

Inbound traffic is harder to shape because you cannot control what the upstream sends. A simple approach uses the ifb (Intermediate Functional Block) pseudo-device:

```bash
# Load ifb module
modprobe ifb
ip link set ifb0 up

# Redirect ingress to ifb0
tc qdisc add dev eth0 ingress
tc filter add dev eth0 parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev ifb0

# Apply shaping on ifb0
tc qdisc add dev ifb0 root handle 1: htb default 10
tc class add dev ifb0 parent 1: classid 1:1 htb rate 1000mbit
tc class add dev ifb0 parent 1:1 classid 1:10 htb rate 800mbit ceil 800mbit
```

For Docker-specific bandwidth control, bind tc to the container's veth interface instead of the host's physical interface. Or use a cleaner approach with cgroup-based traffic classification:

```bash
# Create cgroup filters for specific containers
tc filter add dev eth0 parent 1: protocol all prio 1 cgroup
```

Then assign the container pid to a cgroup with specific `net_cls.classid`, and the tc filter applies the corresponding rate.

For most homelabs, shaping the host's physical interface and setting per-container `--cpus` and `--memory` limits is sufficient. Add tc to your ethtool systemd service for persistence:

```ini
ExecStart=/sbin/tc qdisc add dev eth0 root handle 1: htb default 10
ExecStart=/sbin/tc class add dev eth0 parent 1: classid 1:1 htb rate 1000mbit
ExecStart=/sbin/tc class add dev eth0 parent 1:1 classid 1:10 htb rate 800mbit ceil 800mbit
```

## Offload Feature Tuning

ethtool offload flags control whether packet segmentation, checksumming, and coalescing happen in hardware or software. The defaults (all on) are usually correct for bare-metal servers, but virtualization and container networking create edge cases.

### Checksum Offload

Some NICs generate incorrect checksums with certain drivers under load. The symptom: tcpdump shows good packets, but the application sees TCP checksum failures. Test by temporarily disabling:

```bash
ethtool -K eth0 tx-checksum-ip-generic off
```

If the problem persists, the NIC driver is fine. Re-enable:

```bash
ethtool -K eth0 tx-checksum-ip-generic on
```

### TSO, GSO, GRO

TSO (TCP Segmentation Offload) and GSO (Generic Segmentation Offload) let the NIC split large TCP segments into MTU-sized packets in hardware. GRO (Generic Receive Offload) merges incoming packets into larger chunks before the kernel processes them.

Keep them on for throughput-sensitive workloads. Disable only if:

- The NIC/driver has bugs with large offloads (check dmesg for errors)
- You are running packet inspection (Snort, Suricata) — they need unsegmented packets
- You need per-packet latency under 100µs

```bash
# Disable (most aggressive tuning for latency)
ethtool -K eth0 gro off gso off tso off
```

### Vendor-Specific Tuning

Intel and Broadcom NICs expose additional tuning through private flags:

```bash
ethtool --show-priv-flags eth0
```

On Intel ixgbe/ice drivers, the `adaptive-rx` and `adaptive-tx` flags control dynamic interrupt coalescing. Disable for consistent latency, keep enabled for mixed workloads:

```bash
ethtool --set-priv-flags eth0 adaptive-rx off adaptive-tx off
```

## Proxmox and Docker Host-Specific Tuning

### sysctl Network Stack Tuning

These sysctl settings complement hardware-level tuning:

```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-netoptim.conf
# Increase network buffer sizes
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144

# TCP buffer auto-tuning (min, default, max)
net.ipv4.tcp_rmem = 4096 131072 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# TCP congestion control — BBR for throughput
net.ipv4.tcp_congestion_control = bbr

# Enable TCP window scaling
net.ipv4.tcp_window_scaling = 1

# Increase the maximum backlog
net.core.netdev_max_backlog = 5000
net.core.netdev_budget = 600
net.core.netdev_budget_usecs = 8000

# Increase TCP max syn backlog
net.ipv4.tcp_max_syn_backlog = 8192

# Enable fast socket open (TFO)
net.ipv4.tcp_fastopen = 3

# Increase epoll limits
net.core.optmem_max = 65536

# RFS flow table
net.core.rps_sock_flow_entries = 32768
EOF

sudo sysctl -p /etc/sysctl.d/99-netoptim.conf
```

### Proxmox Bridge Tuning

Proxmox uses Linux bridges for VM connectivity. Default bridge settings prioritize simplicity over throughput. Tune the bridge forwarding database:

```bash
# Increase bridge aging time (default 300s)
echo 600 > /sys/class/net/vmbr0/bridge/ageing_time

# Disable bridge hash elasticity (reduce CPU overhead with many MACs)
echo 0 > /sys/class/net/vmbr0/bridge/hash_elasticity

# Increase hash max size
echo 4096 > /sys/class/net/vmbr0/bridge/hash_max
```

### Docker Overlay2 and nftables Overhead

Docker's overlay2 storage driver and nftables forwarding rules add kernel overhead. The nftables flowtable accelerates forwarding by bypassing the kernel stack for established connections:

```bash
nft add table inet homelab
nft add flowtable inet homelab netfwd { hook ingress priority 0\; devices = { eth0, docker0 } \; }
nft add rule inet homelab forward ip protocol tcp flow add @netfwd
```

## Benchmarking and Validation

After applying all tuning, run the same iperf3 test from the baseline:

```bash
# Client to server, 4 parallel streams, 30 seconds
iperf3 -c 10.0.20.30 -t 30 -P 4
```

Compare against your earlier baseline. A properly tuned host should show 15-40% higher throughput and no dropped packets.

Check IRQ distribution during the test:

```bash
watch -n 2 'grep eth0 /proc/interrupts'
```

Each queue IRQ should increment roughly evenly across the cores.

Check driver counters under load:

```bash
watch -n 1 'ethtool -S eth0 | grep -E "miss|drop"'
```

Both counters should remain at zero or near-zero during sustained throughput.

Monitor CPU utilization during the test:

```bash
mpstat -P ALL 2
```

SoftIRQ (`%soft`) should spread across multiple cores, not peg a single one.

## Quick Checklist — 5 Things to Check on Any Homelab Linux Host

If you only have five minutes, run through these in order:

1. `ethtool -g eth0` — are ring buffers at maximum?
2. `ethtool -l eth0` — are all combined queues active?
3. `grep eth0 /proc/interrupts` — are IRQs spread across CPU cores?
4. `sysctl net.ipv4.tcp_congestion_control` — is BBR enabled?
5. `ethtool -S eth0 | grep -E 'miss|drop'` — are there any packet drops?

Each item addresses one of the three bottlenecks from the introduction: ring overflows, single-CPU IRQ saturation, and buffer pressure. Fixing these five things covers 90% of network performance issues in a homelab environment.

## Summary

Linux network performance tuning for homelab servers breaks down into four layers: hardware ring buffers, receive/transmit queue distribution via RSS/RPS/XPS, IRQ affinity with irqbalance, and traffic shaping with tc. Each layer has a straightforward diagnostic tool (ethtool) and a permanent persistence method (systemd).

Start with `ethtool -S` to identify drops, then work through the checklist. On a Proxmox host serving 10-30 containers, ring buffer tuning alone can eliminate dropped packets under burst loads. Adding RSS or RPS distribution spreads the interrupt load across all CPU cores, which directly translates to higher consistent throughput.

The configurations in this guide are safe to apply to any Debian-based homelab host. Test each change with iperf3 before and after, make them persistent with the included systemd service and sysctl drop-in, and monitor `/proc/interrupts` to verify IRQ distribution.
