---
title: "Proxmox SDN — Centralized Virtual Networking for Homelab Clusters"
description: "Deploy Proxmox SDN with VXLAN zones, VNets, subnets, and DHCP integration across multi-node clusters. Replace manual bridge management with centralized software-defined networking."
date: 2026-05-19T17:00:00-04:00
tags:
  - proxmox
  - networking
  - homelab
  - virtualization
  - linux
keywords:
  - Proxmox SDN setup guide homelab
  - Proxmox VXLAN zone configuration cluster
  - Proxmox VNet subnet DHCP dnsmasq
  - Proxmox software defined networking multi-node
  - Proxmox SDN Simple zone vs VLAN zone vs VXLAN
  - Proxmox virtual network isolation containers
  - Proxmox centralized bridge management
summary: "Complete guide to Proxmox SDN — configure centralized virtual networks with VXLAN overlays, VNets, subnets, and integrated DHCP across your multi-node cluster."
canonical: "https://gntech.dev/posts/proxmox-sdn-software-defined-networking/"
---

If you manage a Proxmox cluster with multiple nodes, you have
probably written manual bridge configs on every host. Need to
add a new isolated network? SSH into node1, edit
`/etc/network/interfaces`, apply it. Node2? Same. Node3? Same.
Now keep them in sync when you add a fourth host. That is brittle,
error-prone, and doesn't scale.

Proxmox SDN (Software-Defined Networking) solves this. Introduced
as a core feature in Proxmox VE 8.1, SDN lets you define virtual
networks — zones, VNets, subnets — once at the datacenter level.
The configuration is replicated across your cluster automatically
and applied on every node. Need a new isolated network for your
IoT containers? Create a VNet in the web UI, apply, and bridge it
to any VM or CT on any node. No SSH required.

This guide covers deploying Proxmox SDN in a homelab cluster,
choosing the right zone type, creating VNets with subnets and DHCP,
and assigning them to virtual guests.

---

## Why Bother with SDN in a Homelab?

The traditional approach — Linux bridges with VLAN tagging — works
fine for a single node. With a three-node cluster, it is annoying
but manageable. At five nodes and a dozen networks, the overhead
becomes real.

SDN replaces per-node manual configuration with a single source of
truth in the Proxmox cluster filesystem. The benefits:

- **Single point of management** — create/edit/delete networks from
  the web UI, no CLI required on individual nodes
- **Automatic distribution** — config syncs via `pmxcfs` (the
  Proxmox cluster file system) and is applied with one click
- **Self-service isolation** — spin up a new VNet for a project or
  tenant without touching physical switch VLANs
- **DHCP integration** — built-in dnsmasq gives VMs IPs in their
  VNet subnet automatically
- **Consistency** — no drift between nodes, no forgotten bridges

If you run even two Proxmox nodes with more than one isolated
network, SDN saves you time. With three or more, it is a
game-changer.

---

## Prerequisites

- **Proxmox VE 8.1+** — SDN is installed by default on fresh
  installs. On upgrades from 7.x, you need the package:

```bash
apt update && apt install libpve-network-perl
```

- **Cluster** — SDN works at the datacenter level across nodes.
  A single-node cluster works fine too; you still get centralized
  management.

- **`ifupdown2`** — Required by SDN. Included by default since
  Proxmox 7. Check with:

```bash
dpkg -l | grep ifupdown2
```

If absent, install it before proceeding:

```bash
apt install ifupdown2
```

- **Verify the include line** — Ensure `/etc/network/interfaces`
  ends with:

```bash
source /etc/network/interfaces.d/*
```

This line tells `ifupdown2` to load SDN-generated configs. Add it
if missing. Do this on **every node**.

---

## Zone Types — Picking the Right One

Proxmox SDN offers four zone types. Each uses a different
transport technology:

| Zone Type | Transport | Best For |
|-----------|-----------|----------|
| **Simple** | Local bridge (no overlay) | Single node, test/development |
| **VLAN** | 802.1Q tagged | Existing physical VLAN infrastructure |
| **VXLAN** | UDP overlay (port 4789) | Multi-node clusters, no switch VLAN config |
| **EVPN** | VXLAN + BGP routing | Multi-site, inter-VNet routing |

**For most homelabs with 2-4 nodes**, VXLAN is the sweet spot.
It creates overlay networks over your existing management or
storage network — no physical switch VLAN provisioning needed.
Each VNet gets its own VXLAN Network Identifier (VNI), giving you
up to 16 million isolated networks.

Stick with Simple if you only have one Proxmox node. Use VLAN if
your physical switch already handles VLANs and you want SDN to
manage the bridge side. Use VXLAN for everything else.

---

## Step 1 — Creating a VXLAN Zone

Navigate to **Datacenter > SDN > Zones** and click **Create**.

```
Zone ID:    lab-zone
Type:       VXLAN
Peers:      10.0.20.30, 10.0.20.31, 10.0.20.32
MTU:        1450
Nodes:      all
```

The **Peers** field lists the IP addresses of every cluster node
on your underlay network. These are the VTEP (VXLAN Tunnel
Endpoint) addresses — the IPs the nodes use to reach each other
for overlay traffic. Typically your management network IPs.

**MTU 1450** is critical. VXLAN overhead is 50 bytes per packet
(outer IP + UDP + VXLAN header). With a physical MTU of 1500,
payload MTU drops to 1450. If your switch supports jumbo frames
(MTU 9000), set Peers MTU to 8950.

Click **OK** to create the zone.

---

## Step 2 — Creating VNets and Subnets

Now create isolated virtual networks inside the zone. Navigate to
**Datacenter > SDN > VNets** and click **Create**.

### VNet for Production Containers

```
VNet ID:    vnet-prod
Zone:       lab-zone
Tag:        100
```

The **Tag** is the VXLAN VNI — a unique identifier for this
overlay network. Each VNet in a VXLAN zone needs its own tag.

After creating the VNet, click on it and add a subnet:

```
Subnet:     10.100.1.0/24
Gateway:    10.100.1.1
SNAT:       Enabled
DHCP Range: 10.100.1.100 - 10.100.1.200
DNS Server: 10.0.20.1
```

**SNAT** enables masquerading traffic from this VNet to external
networks (like the internet). Without it, guests can talk to each
other across VXLAN but cannot reach the outside world.

### VNet for Development

```
VNet ID:    vnet-dev
Zone:       lab-zone
Tag:        200
Subnet:     10.100.2.0/24
Gateway:    10.100.2.1
SNAT:       Enabled
DHCP Range: 10.100.2.100 - 10.100.2.200
```

### VNet for IoT

```
VNet ID:    vnet-iot
Zone:       lab-zone
Tag:        300
Subnet:     10.100.3.0/24
Gateway:    10.100.3.1
SNAT:       Disabled
```

IoT networks are intentionally left without SNAT and without DHCP
— guests get static IPs and have no internet access. If you need
selective internet access, enable SNAT and apply firewall rules
instead.

---

## Step 3 — Applying the Configuration

In **Datacenter > SDN**, you will see a banner saying **"Pending
changes"**. Click the **Apply** button.

SDN applies changes atomically. It reads the config from
`/etc/pve/sdn/`, generates ifupdown2 config snippets, and pushes
them to all nodes. On each node, it creates bridges:

- `vnets-bridge-vnet-prod` on all nodes
- `vnets-bridge-vnet-dev` on all nodes  
- `vnets-bridge-vnet-iot` on all nodes

Verify the bridges are up:

```bash
# On any node
bridge link show | grep vnet
```

If you see the bridges and their VXLAN tunnel interfaces, SDN is
active. You can also check:

```bash
ip -d link show vnet-prod
```

---

## Step 4 — Assigning VNets to VMs and Containers

VNets appear as regular bridges in the network device dropdown.
A VM gets a virtual NIC plugged into the bridge, just like any
Linux bridge network.

### Via Web UI

For a VM: go to **Hardware > Add > Network Device**, select
`vnet-prod` as the bridge, VirtIO model.

For an LXC container: go to **Network > Add**, select `vnet-prod`,
set IPv4 to DHCP.

### Via CLI

```bash
# Attach VM 100 to vnet-prod
qm set 100 -net0 virtio,bridge=vnet-prod

# Attach CT 200 to vnet-dev with DHCP
pct set 200 -net0 name=eth0,bridge=vnet-dev,ip=dhcp
```

When the guest boots, it receives an IP from the dnsmasq DHCP
server running for that subnet. Containers on different VNets
cannot communicate with each other — they are fully isolated at
layer 2.

---

## Step 5 — DHCP Integration with dnsmasq

For DHCP to work, you need `dnsmasq` installed on **every node**
that hosts guests on a VNet with DHCP enabled:

```bash
apt install dnsmasq
systemctl disable --now dnsmasq
```

Proxmox SDN manages its own dnsmasq instances per subnet. The
system-level dnsmasq must be disabled to avoid port conflicts.

The DHCP server automatically:

- Assigns IPs from the configured range
- Sets the gateway and DNS server you specified
- Registers hostnames (guest hostname → IP) for DNS resolution
  within the VNet

You can check active leases:

```bash
ls /var/lib/dnsmasq/dnsmasq-*.leases
cat /var/lib/dnsmasq/dnsmasq-vnet-prod.leases
```

---

## Step 6 — Firewalling VNet Traffic

SDN VNets are isolated by default — layer 2 traffic does not
cross VNet boundaries. However, layer 3 traffic (routed through
SNAT or through a router VM) can mix. Add Proxmox firewall rules
at the datacenter or node level to control inter-VNet access.

### Datacenter Firewall Rules

Navigate to **Datacenter > Firewall > Rules** and add:

| Action | Type | Source | Dest | Comment |
|--------|------|--------|------|---------|
| ACCEPT | IP | vnet-prod | 10.100.1.0/24 | Allow prod self-traffic |
| DROP | IP | vnet-prod | 10.100.2.0/24 | Block prod→dev |
| ACCEPT | IP | vnet-dev | 10.100.2.0/24 | Allow dev self-traffic |
| DROP | IP | 10.100.3.0/24 | any | Block IoT→all |
| ACCEPT | IP | 10.100.3.0/24 | 10.100.3.0/24 | Allow IoT self-traffic |

The order matters — Proxmox firewall uses first-match semantics.
Place specific allow rules before broad drops.

### Enable Firewall on VMs

Guest-level firewall rules only apply when the firewall is
enabled on the VM or CT. Via CLI:

```bash
qm set 100 -firewall 1
pct set 200 -firewall 1
```

Then define rules in `/etc/pve/firewall/<VMID>.fw` or via the
VM's Firewall panel in the web UI.

---

## Transitioning from Manual Bridges

If you are migrating existing VMs from manually created bridges
to SDN VNets, the process is straightforward:

1. Create the VNet in SDN → Apply
2. Shut down the VM
3. Change its network device from the old bridge to the new VNet
4. Start the VM

The VM keeps its IP if you assign the same subnet. For LXC
containers using DHCP, the dnsmasq lease will assign the same IP
because dnsmasq persists leases to disk.

When all guests are migrated, delete the old manual bridge config
from `/etc/network/interfaces` on each node.

---

## Troubleshooting Common Issues

### Bridges not appearing after Apply

Check the SDN status:

```bash
cat /etc/pve/sdn/.running-config
cat /etc/pve/sdn/.version
```

If version is `-1` (not applied) or stale, re-apply from the
web UI. Also verify `ifupdown2` is installed:

```bash
ip a | grep vnet
```

If the bridge exists but has no VXLAN link, check MTU. An MTU
mismatch between nodes causes silent packet drops. Set all
physical interfaces and the VXLAN zone to the same MTU.

### Guests cannot reach the internet

Verify SNAT is enabled in the subnet configuration. Without SNAT,
VNet traffic has no route to external networks. If SNAT is on,
check the default gateway in the VNet matches what guests receive
via DHCP.

### DHCP not assigning IPs

- Ensure `dnsmasq` is installed and the systemd service is
  disabled on every node hosting guests
- Check the dnsmasq lease file for errors
- Verify the DHCP range does not overlap with the gateway IP or
  any static assignments
- Confirm the VNet is applied (check `.running-config`)

### VXLAN performance is slow

VXLAN adds 50 bytes per packet, which can cause fragmentation or
MTU issues. Set the VXLAN zone MTU to 1450 (or 8950 with jumbo
frames) and ensure guests also use the reduced MTU:

```bash
# Inside a Linux guest
ip link set eth0 mtu 1450
```

For Docker hosts on a VNet, set the MTU in `daemon.json`:

```json
{
  "mtu": 1450
}
```

---

## SDN vs Traditional Bridges — A Comparison

| Aspect | Traditional Bridges | Proxmox SDN |
|--------|-------------------|-------------|
| Config location | Every node's `/etc/network/interfaces` | Single datacenter UI |
| Applying changes | Per-node SSH, `ifreload -a` | One-click Apply |
| Adding a node | Copy all bridge configs | Add IP to Peers, re-Apply |
| DHCP | External (Pi-hole, router) | Built-in dnsmasq per subnet |
| Network isolation | Manual bridge per network | VNet per network |
| Cross-node overlay | Manual VXLAN setup | Automatic VXLAN per VNet |
| Rollback | Manual copy/backup | Re-apply previous state |

---

## When to Avoid SDN

SDN is powerful but not always the right fit:

- **Single node, one or two networks** — Simple bridges are less
  overhead and no additional service to maintain
- **Very tight memory budget** — Each dnsmasq instance uses a few
  MB. On a host with 8 GB or more, this is irrelevant
- **Complex multi-site BGP routing** — EVPN is still in tech
  preview. For multi-site routing, consider FRRouting on a VM
  alongside SDN
- **Existing heavily customized networking** — If you have complex
  OVS bridges, bonding, or policy routing, SDN may conflict.
  Test in a lab first

---

Proxmox SDN transforms network management from a per-node chore
into a cluster-wide operation. For a three-node homelab with
production, development, and IoT workloads, it eliminates the
most tedious part of Proxmox administration — keeping bridge
configs in sync. Define it once, apply it everywhere, and spend
your time on things that actually matter.
