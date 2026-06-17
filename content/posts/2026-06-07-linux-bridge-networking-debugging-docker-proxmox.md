---
title: "Linux Bridge Network Debugging — Docker and Proxmox Homelab Guide"
description: "Debug Docker and Proxmox bridge networks with tcpdump, brctl, and bridge fdb. Fix container connectivity, VLAN tagging, and MAC learning issues in your homelab."
date: 2026-06-07T17:00:00-04:00
tags:
  - docker
  - networking
  - linux
  - proxmox
keywords:
  - Linux bridge networking debugging Docker Proxmox homelab troubleshooting guide
  - Docker bridge network connectivity container debugging tcpdump
  - Proxmox Linux bridge VLAN configuration troubleshooting
  - brctl bridge fdb MAC learning debugging container networks
  - Docker network namespace inspection bridge forwarding table
  - Linux bridge STP configuration container networking issues
  - Homelab bridge network packet capture traffic analysis tcpdump
summary: "A practical guide to debugging Linux bridge networks used by Docker and Proxmox. Covers tcpdump packet captures, brctl and bridge fdb inspection, VLAN troubleshooting, Docker network namespace traversal, and fixes for common connectivity problems."
canonical: "https://blog.gntech.me/posts/linux-bridge-networking-debugging-docker-proxmox/"
---

## Why Linux Bridges Deserve Your Debugging Attention

Every time a Docker container talks to another container, or a Proxmox VM sends a packet to the gateway, that traffic flows through a Linux bridge. Docker's default `bridge` network uses `docker0`. Every user-defined Docker bridge is a Linux bridge. Every Proxmox virtual bridge — `vmbr0`, `vmbr1`, etc. — is the same kernel primitive under the hood.

When something breaks — container can't reach the internet, VM on a VLAN can't ping its gateway, or traffic simply vanishes between two bridged interfaces — the problem is almost always in the bridge forwarding table, a missing VLAN tag, or iptables interference.

This guide covers the exact commands and techniques to find and fix those problems. You'll use `brctl`, `bridge` (the modern iproute2 tool), `tcpdump`, and Docker namespace inspection to trace traffic from container to wire.

## Inspecting Linux Bridges with brctl and bridge

Start with the big picture. The `bridge-utils` package (`brctl`) is still widely available, but the iproute2 `bridge` tool is the modern replacement and should be your default.

### List All Bridges

```bash
# Old-school
brctl show

# Modern equivalent
bridge link show
```

`brctl show` prints bridge name, bridge ID, STP status, and interfaces. The `bridge` command with no arguments shows all bridge ports with their state and flags.

### Inspect the MAC Forwarding Table

The forwarding database (FDB) is where bridges learn which MAC addresses are on which port. A stale or missing entry is the most common cause of mysterious packet loss.

```bash
# Show MAC table for a specific bridge
brctl showmacs br0

# Modern: show FDB with port details
bridge fdb show br br0
```

Look for entries where ` ageing timer` keeps resetting — that indicates MAC flapping (the same MAC appearing on different ports), usually caused by a network loop or misconfigured bonding.

### Check VLAN Membership

If you use VLAN filtering on your bridges (common on Proxmox in VLAN-aware mode), verify which VLANs are allowed on each port:

```bash
bridge vlan show
bridge vlan show dev veth1234
```

A missing VLAN on the port means traffic tagged with that VLAN gets dropped silently — one of the hardest issues to diagnose without this command.

### Disable STP on Docker Bridge Networks

Docker user-defined bridges have STP enabled by default on some distributions. This can block ports for 15–30 seconds during container restarts, causing connection timeouts:

```bash
# Check STP status
brctl stp docker0
brctl showstp docker0

# Disable STP (Docker bridge only — leave it on for physical networks)
brctl stp docker0 off
```

## Packet Capture on Bridge Interfaces with tcpdump

Capturing on the bridge interface itself shows all traffic flowing through it, including inter-container traffic that never touches a physical NIC.

### Basic Capture on the Bridge

```bash
# See everything on the bridge with MAC addresses
tcpdump -i br0 -e -n

# Filter to ARP only (debugging neighbor discovery)
tcpdump -i br0 -e -n arp

# See VLAN tags
tcpdump -i br0 -e -n vlan
```

The `-e` flag is critical — it prints MAC source and destination addresses so you can verify the bridge is forwarding to the correct port.

### Debug: Container Can't Reach the Internet

A container that can ping its gateway's IP but not the internet usually points to NAT or routing — but let's verify at layer 2 first:

```bash
# From the host, capture on docker0
tcpdump -i docker0 -e -n icmp and host 8.8.8.8

# In another terminal, ping from inside the container
docker exec mycontainer ping -c 3 8.8.8.8
```

If you see the ICMP request on `docker0` but no reply, the bridge is forwarding correctly — the issue is upstream (NAT iptables rule, routing table, or ISP). If you see nothing, the packet isn't reaching the bridge — check container routes and default gateway.

## Docker Network Namespace Inspection

Every Docker container lives in its own network namespace. To bridge traffic, Docker creates a veth pair — one end inside the container's namespace, the other plugged into the bridge.

### Find a Container's Network Namespace

```bash
# Get the container PID
PID=$(docker inspect -f '{{.State.Pid}}' mycontainer)

# Enter its network namespace to inspect interfaces
nsenter -t $PID -n -- ip addr
nsenter -t $PID -n -- ip route
nsenter -t $PID -n -- ip neigh
nsenter -t $PID -n -- iptables -L -n -v
```

This is far more revealing than `docker exec`. You see exactly what the container sees: its ARP cache, its routing table, its firewall rules.

### Debug: Container Resolves DNS But Cannot Connect

This classic symptom — `ping google.com` resolves but connection fails — is almost never a bridge problem, but here's how to confirm:

```bash
# Check routes from inside the container
nsenter -t $PID -n -- ip route

# Check default gateway
nsenter -t $PID -n -- ip route show default

# Check that the container's veth is the default route via the bridge IP
```

If the default route points to the bridge IP correctly, the issue is upstream (NAT/firewall). If there's no default route, restart the container or attach it to the correct network.

### Map Container veth to Bridge Port

Each container gets a veth interface in the host namespace. Find which one belongs to your container:

```bash
# Container side shows the veth peer index
ETH_INDEX=$(docker exec mycontainer cat /sys/class/net/eth0/iflink)
echo "Container's host veth index: $ETH_INDEX"

# Find the veth name from the index
ip link | grep "^${ETH_INDEX}:"
```

Then inspect that specific veth on the bridge:

```bash
bridge fdb show br br0 | grep $(ip -o link show | grep "^${ETH_INDEX}:" | awk '{print $2}' | tr -d ':')
```

## Proxmox Bridge and VLAN Troubleshooting

Proxmox bridges follow the same Linux bridge rules, but with configuration in `/etc/network/interfaces` and a VLAN-aware mode that adds another layer.

### Check Current Bridge Configuration

```bash
cat /etc/network/interfaces
```

A typical Proxmox bridge with VLAN-aware mode:

```
auto vmbr0
iface vmbr0 inet static
    address 10.0.20.30/24
    gateway 10.0.20.1
    bridge-ports enp3s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094
```

### Verify VLAN Interfaces Are Working

```bash
# List all VLAN devices
ip link show type vlan

# Check a specific VLAN interface
cat /proc/net/vlan/vlan20
```

### Debug: VM on Tagged VLAN Cannot Reach Gateway

When a Proxmox VM is configured with VLAN tag 20 but can't reach its gateway on VLAN 20:

```bash
# 1. Check the bridge sees the VLAN
bridge vlan show dev vmbr0

# 2. Verify the VM's tap interface has the right VLAN tag
bridge vlan show dev tap100i0

# 3. Capture on the bridge filtered to VLAN 20
tcpdump -i vmbr0 -e -n vlan 20

# 4. Check from the host that the VLAN interface exists
ip addr show vmbr0.20

# 5. Verify the VLAN interface is up
ip link set vmbr0.20 up
```

Missing `bridge-vlan-aware yes` in the Proxmox config is the most common root cause. Without it, tagged traffic passes through untagged and the VM never sees its VLAN ID.

## Common Issues and Fixes

### iptables Interfering with Bridge Traffic

The `bridge-nf-call` sysctls cause iptables rules to apply to bridged traffic. This can break container-to-container communication if your FORWARD chain has restrictive policies:

```bash
# Check current state
sysctl net.bridge.bridge-nf-call-iptables
sysctl net.bridge.bridge-nf-call-ip6tables

# Disable for Docker bridge traffic (set to 0)
echo 0 | sudo tee /proc/sys/net/bridge/bridge-nf-call-iptables
echo 0 | sudo tee /proc/sys/net/bridge/bridge-nf-call-ip6tables

# Make permanent
cat > /etc/sysctl.d/99-bridge-nf-call.conf << 'EOF'
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
EOF
sysctl -p /etc/sysctl.d/99-bridge-nf-call.conf
```

### MAC Address Port Security

Some managed switches learn MAC addresses on specific ports. When a container restarts and gets a new MAC, or you migrate a VM, the switch still forwards traffic for the old MAC to the wrong port. Clear the switch's MAC table or set the VM/container to use a static MAC:

```yaml
# In Docker Compose — assign a static MAC
services:
  myapp:
    mac_address: "02:42:ac:1a:00:01"
```

On Proxmox, set `hwaddr` in the VM config under Hardware → Network Device.

### MTU Mismatches

If your physical interface uses jumbo frames (MTU 9000) but Docker containers get MTU 1500, packets may get silently fragmented or dropped:

```bash
# Check MTU across the path
ip link show docker0
ip link show br0
ip link show enp3s0

# Set Docker daemon MTU
# Add to /etc/docker/daemon.json:
# { "mtu": 9000 }
```

For Proxmox bridges, set the MTU on the bridge interface itself:

```bash
ip link set vmbr0 mtu 9000
```

### STP Blocking Docker Bridge Ports

STP on Docker bridges causes a 15–30 second delay every time a container starts or restarts. If you're running containers that need fast failover or rapid restarts (like HA proxies or load balancers), disable STP on Docker-created bridges:

```bash
for br in $(brctl show | grep -E '^br-[0-9a-f]+' | awk '{print $1}'); do
    brctl stp $br off
done
```

## Automation: Bridge Health Check Script

Save this as `/usr/local/bin/bridge-health.sh` and run it periodically with a systemd timer:

```bash
#!/bin/bash
# Bridge health check — log MAC table and flag suspicious entries

BRIDGES=$(brctl show | grep -v "bridge name" | awk '{print $1}')

for br in $BRIDGES; do
    echo "=== $br MAC Table $(date) ==="
    bridge fdb show br "$br" | while read -r line; do
        mac=$(echo "$line" | awk '{print $1}')
        port=$(echo "$line" | awk '{print $3}')
        ageing=$(echo "$line" | awk '{print $5}')
        # Flag MACs with ageing timer below 5 seconds (potential flapping)
        if [ -n "$ageing" ] && [ "$ageing" -lt 5 ] 2>/dev/null; then
            echo "WARNING: $mac on $port has ageing timer $ageing — potential flapping"
        fi
    done
done
```

Make it executable and set a systemd timer for every 10 minutes:

```bash
chmod +x /usr/local/bin/bridge-health.sh

# systemd service
cat > /etc/systemd/system/bridge-health.service << 'EOF'
[Unit]
Description=Bridge health check
[Service]
Type=oneshot
ExecStart=/usr/local/bin/bridge-health.sh
EOF

# systemd timer
cat > /etc/systemd/system/bridge-health.timer << 'EOF'
[Unit]
Description=Run bridge health check every 10 minutes
[Timer]
OnCalendar=*:0/10
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now bridge-health.timer
```

## Building Your Bridge Debugging Mental Model

Linux bridges are simple devices: they learn MAC-to-port mappings, forward frames based on destination MAC, and optionally filter by VLAN. When something breaks, start at the bridge and work outward:

1. **Is the bridge up?** — `ip link show $BRIDGE`
2. **Is the container's veth connected?** — `bridge link show` / `brctl show`
3. **Does the bridge have the container's MAC?** — `bridge fdb show br $BRIDGE`
4. **Can you see packets on the bridge?** — `tcpdump -i $BRIDGE -e -n`
5. **Is iptables interfering?** — Check `bridge-nf-call-iptables`
6. **Is STP blocking?** — `brctl showstp $BRIDGE`

Work this chain from bottom to top, and you'll isolate the fault in minutes instead of hours. The tools are already on your system — learn to use them, and networking problems become much less mysterious.
