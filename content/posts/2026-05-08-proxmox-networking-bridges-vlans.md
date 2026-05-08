---
title: "Proxmox Networking — Bridges, VLANs, and a Clean Host Topology"
description: "Practical Proxmox VE networking configuration — bridge layout, VLAN-aware bridges, Linux and OVS bridges, trunk ports to tagged LXC/VM, and tying it back to an external VLAN-segmented router."
date: 2026-05-08T00:00:00-04:00
tags:
  - proxmox
  - networking
  - vlan
  - bridges
  - homelab
categories:
  - homelab
  - networking
---

Proxmox VE's networking layer is simple on the surface — bridges, bonds,
VLANs — but there's a gap between "it works" and "it's maintainable."
A poorly planned bridge topology leads to broadcast storms, accidental
cross-VLAN routing, or containers that can't reach the internet because
the bridge isn't connected to anything.

This post breaks down the networking setup on my Proxmox host (SRV1),
which connects to a MikroTik router (R1) with VLAN filtering and a
trunk port. By the end, you'll know exactly how bridges map to the
physical wire, how VLAN-aware bridges differ from the old approach, and
how to assign VLANs to both VMs and LXC containers cleanly.

---

## Architecture Overview

The host has a single physical NIC (or bond) connected to a MikroTik
trunk port carrying multiple VLANs. All bridge traffic goes through
this trunk. There is no separate management NIC — management rides
VLAN 99.

```
┌─────────────────────────────────────────────────────┐
│                  Proxmox Host (SRV1)                 │
│                                                      │
│  ┌─────── vmbr0 (VLAN-aware) ─────────────────────┐ │
│  │  enp3s0 ──── trunk to R1 (tagged VLANs 1-99)   │ │
│  │                                                 │ │
│  │  vmbr0.10  ── Home LAN   (tagged)              │ │
│  │  vmbr0.50  ── CCTV       (tagged)              │ │
│  │  vmbr0.99  ── Management (tagged)              │ │
│  │                                                 │ │
│  │  ┌────────┐  ┌────────┐  ┌──────────────────┐  │ │
│  │  │ LXC A  │  │ LXC B  │  │  VM (Docker)     │  │ │
│  │  │ vlan:10│  │ vlan:50│  │  virtio, vlan:10 │  │ │
│  │  └────────┘  └────────┘  └──────────────────┘  │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────── vmbr1 (host-routed) ────────────────────┐ │
│  │  no physical port — host-only services go here │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

Proxmox can use either **VLAN-aware bridges** (Linux bridge with
`vlan-aware=yes`) or **manual bridge VLAN interfaces** (vmbr0.10,
vmbr0.50, etc.). I use VLAN-aware bridges — they reduce interface
clutter and let you assign VLANs per VM/LXC at the virtual NIC level.

---

## Step 1 — /etc/network/interfaces

This is the single source of truth for Proxmox networking. The file
lives on the Proxmox host at `/etc/network/interfaces`.

```ini
# Management interface — no IP here, bridge handles everything
auto enp3s0
iface enp3s0 inet manual

# Main trunk bridge — VLAN-aware
auto vmbr0
iface vmbr0 inet manual
    bridge-ports enp3s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094
    # No IP on the bridge itself — management is on vmbr0.99

# Management VLAN — gateway to the router's mgmt subnet
auto vmbr0.99
iface vmbr0.99 inet static
    address 10.0.20.30/24
    gateway 10.0.20.1
    # dns-nameservers are set in /etc/resolv.conf or via stub resolver
```

Key points:

- **`bridge-vlan-aware yes`** enables 802.1Q filtering inside the bridge.
  The bridge decides which VLANs are allowed on each port based on
  `bridge-vids` and per-port PVID settings.
- **`bridge-vids 2-4094`** allows all standard VLANs on the bridge. The
  upstream switch/router handles filtering — Proxmox just passes frames.
- **No IP on vmbr0 itself.** The bridge is purely a switching fabric. An
  IP address on a VLAN-aware bridge is valid but confusing — better to
  put it on the VLAN interface where intent is clear.
- **Management VM**.99**.** `vmbr0.99` is a regular VLAN interface on top
  of vmbr0. Proxmox uses this for its own IP, DNS, web GUI, and SSH.

### Adding Other VLANs

For VLANs that need host-level access (like a subnet for host-originated
backups or NFS mounts):

```ini
# CCTV VLAN — for Frigate API calls from the host
auto vmbr0.50
iface vmbr0.50 inet static
    address 10.0.50.30/24
```

Don't create vmbr0.<VLAN> interfaces unless the host itself needs an IP
on that VLAN. VMs and LXCs get their VLAN assignment through their
virtual NIC config — they don't need host-side interfaces.

---

## Step 2 — Assigning VLANs to VMs and LXCs

### VMs (virtio NICs)

In the VM config file (`/etc/pve/qemu-server/<VMID>.conf`) or via the
web GUI:

```
# VM 101 — Home LAN service VM
net0: virtio=XX:XX:XX:XX:XX:XX,bridge=vmbr0,tag=10
```

The `tag=10` tells Proxmox to tag all traffic from that NIC with VLAN
10. Since vmbr0 is VLAN-aware, it handles the 802.1Q tagging at the
bridge level — the VM sees an untagged frame, but it leaves the host
tagged.

Multiple NICs, multiple VLANs:

```
# VM 200 — Dual-homed jump box
net0: virtio=XX:XX:XX:XX:XX:XX,bridge=vmbr0,tag=99
net1: virtio=YY:YY:YY:YY:YY:YY,bridge=vmbr0,tag=10
```

### LXC Containers

LXCs are more flexible. In the container config
(`/etc/pve/lxc/<CTID>.conf`):

```
# Trunk-style: container sees tagged traffic
net0: name=eth0,bridge=vmbr0,tag=10,type=veth

# VLAN tagging on the LXC bridge port — no guest config needed
```

If the LXC itself needs to handle VLANs (e.g., a containerized router or
a management LXC that needs to reach multiple subnets), omit the tag and
add the LXC as a trunk member by configuring VLAN interfaces inside the
container. For most services, the simple `tag=<ID>` approach is
cleaner.

---

## Step 3 — The Old Way: Non-VLAN-Aware Bridges

Before Proxmox added VLAN-aware bridge support, you'd create one bridge
per VLAN:

```ini
# Old approach — one bridge per VLAN
auto vmbr0
iface vmbr0 inet manual
    bridge-ports enp3s0.10
    bridge-stp off
    bridge-fd 0

auto vmbr1
iface vmbr1 inet manual
    bridge-ports enp3s0.50
    bridge-stp off
    bridge-fd 0
```

This still works, but it's noisy — every VLAN gets its own bridge, its
own vlan interface in `/etc/network/interfaces`, and the web GUI shows a
long list of bridges. The VLAN-aware approach in Step 1 replaces all of
that with one bridge and per-VM/LXC tag assignments.

I switched to VLAN-aware bridging after having 6 bridges and realizing
only the trunk port mattered. Don't do it the old way unless you need
a specific bridge configuration that VLAN-aware bridges don't support
(e.g., different STP settings per VLAN).

### When the Old Way Still Makes Sense

- **Open vSwitch (OVS).** OVS bridges in Proxmox don't support the
  `vlan-aware` property. If you need OVS for advanced features (OpenFlow,
  QoS, bonding with LACP), you create one bridge per VLAN.
- **Bridged firewall rules on the host.** If your host firewall needs
  to filter traffic differently per VLAN at the bridge level, a
  per-VLAN bridge gives you a named interface to write rules against.

---

## Step 4 — Bonding for Redundancy

If your host has multiple NICs and your switch supports LACP:

```ini
# Bond interface
auto bond0
iface bond0 inet manual
    bond-slaves enp3s0 enp4s0
    bond-mode 802.3ad
    bond-miimon 100
    bond-lacp-rate fast
    bond-xmit-hash-policy layer2+3

# VLAN-aware bridge on top of the bond
auto vmbr0
iface vmbr0 inet manual
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094
```

On the MikroTik side, configure the corresponding bond/LAG:

```
/interface bonding add mode=802.3ad name=bond-trunk slaves=ether5,ether6 lacp-rate=fast
/interface bridge port add bridge=bridge-trunk interface=bond-trunk
```

Same VLAN-aware bridge logic, just on a bonded aggregate instead of a
single NIC. Everything else — VM tags, LXC VLANs, host management
interface — works the same way.

---

## Step 5 — Troubleshooting Bridge Issues

### "Guest can't reach the internet"

1. Check that the physical link is a trunk port on the upstream
   switch/router — tagged frames for the guest's VLAN must be allowed.
2. On Proxmox: `bridge vlan show dev vmbr0` to see current VLAN
   membership on the bridge ports.
3. Inside the guest: confirm the VLAN tag matches on both the Proxmox
   NIC config (`tag=X`) and the router's VLAN interface/subnet.

### "Host can't reach the internet despite vmbr0.99 having an IP"

1. The default gateway must be reachable via vmbr0.99. Run
   `ip route show default`.
2. Verify the gateway is on the same VLAN. If the router serves
   10.0.20.0/24 on VLAN 99, but you put he host IP on vmbr0.10,
   they won't see each other.
3. Check that the upstream port actually allows VLAN 99 tagged frames.
   Some switches default to blocking all VLANs except the native one.

### "I see duplicate IPs or weird ARP behavior"

- This usually means the same subnet is reachable via two different
  bridges or VLANs. Don't put the same VLAN on two ports of the same
  bridge unless you know what you're doing.
- Make sure `bridge-stp off` is intentional — with only one uplink, STP
  is unnecessary and can add 30-second delays. With multiple uplinks,
  you want STP (or a bond).

### Checking VLAN membership from Proxmox

```bash
# Shows VLAN membership on the bridge
bridge vlan show

# Show bridge ports and their PVID
bridge vlan show dev vmbr0

# Add a specific VLAN manually (rarely needed — usually done via config)
bridge vlan add vid 10 dev vmbr0 pvid untagged
```

---

## The Full Config (Single NIC, No Bond)

For reference, here's the complete `/etc/network/interfaces` for a
single-NIC host connected to a MikroTik trunk:

```ini
auto lo
iface lo inet loopback

# Physical NIC — no IP, bridge handles everything
auto enp3s0
iface enp3s0 inet manual

# Main trunk bridge — VLAN-aware
auto vmbr0
iface vmbr0 inet manual
    bridge-ports enp3s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
    bridge-vids 2-4094

# Management
auto vmbr0.99
iface vmbr0.99 inet static
    address 10.0.20.30/24
    gateway 10.0.20.1

# CCTV subnet host access (for Frigate API)
auto vmbr0.50
iface vmbr0.50 inet static
    address 10.0.50.30/24

# Home LAN host access
auto vmbr0.10
iface vmbr0.10 inet static
    address 10.0.10.30/24
```

---

## Summary

| Concept | Recommendation |
|---------|---------------|
| Bridge type | VLAN-aware (`bridge-vlan-aware yes`) |
| Physical uplink | Single trunk to upstream router/switch |
| Host management | VLAN interface (vmbr0.<VLAN>) with static IP |
| VM/LXC VLAN assignment | `tag=<VLAN>` on the virtual NIC — no host VLAN iface needed |
| Bonding | `bond-mode 802.3ad` (LACP) if multiple NICs |
| Multiple bridges | Only when needed (OVS, per-VLAN firewalling) |

The VLAN-aware bridge approach reduced my `/etc/network/interfaces`
from 40+ lines to under 20, and every VM/LXC gets its VLAN assignment
at the NIC level — clean, declarative, and easy to audit.

Your router and hypervisor are two halves of the same network: the
router defines the VLANs and firewall rules, the hypervisor connects
guests to the right VLAN. Get the bridge config right on both sides,
and you never think about it again.
