---
title: "MikroTik RouterOS 7 OSPF — Dynamic Routing for Your Homelab"
description: "Configure MikroTik RouterOS 7 OSPF for dynamic routing in your homelab. CLI commands, area design, redistribution, authentication, and multi-router topology examples."
date: 2026-05-28T07:00:00-04:00
tags:
  - mikrotik
  - networking
  - routing
  - homelab
  - linux
keywords:
  - MikroTik RouterOS 7 OSPF configuration guide homelab
  - OSPF dynamic routing MikroTik multi-router setup
  - RouterOS 7 OSPF area design and redistribution
  - MikroTik OSPF authentication and passive interfaces
  - OSPF between MikroTik and Linux FRR Quagga
  - RouterOS 7 routing filter redistribution configuration
  - OSPF stub area NSSA MikroTik homelab deployment
summary: "Configure OSPF dynamic routing on MikroTik RouterOS 7 for your homelab. Step-by-step guide with real RouterOS CLI commands, area design patterns, route redistribution, and multi-router topology examples."
canonical: "https://gntech.dev/posts/mikrotik-routeros7-ospf-dynamic-routing/"
---

When your homelab grows past a single router and a handful of VLANs, static routes become a maintenance burden. Every new subnet, every link change, every failover scenario requires manual updates across every router. OSPF (Open Shortest Path First) solves this by dynamically discovering the network topology and converging on the best paths automatically.

MikroTik RouterOS 7 ships a mature OSPF implementation that supports both OSPFv2 (IPv4) and OSPFv3 (IPv6), routing filter chains for redistribution policy, and full support for stub, NSSA, and area authentication. RouterOS 7.23 and the recent 7.24beta1 continue to refine the routing stack, making this an excellent time to add dynamic routing to your lab.

This guide covers everything from a basic two-router setup to multi-area designs, authentication, and cross-platform interop with Linux FRR. All commands target RouterOS 7.1+.

---

## 1. OSPF Concepts for the Homelab

OSPF is a link-state IGP (Interior Gateway Protocol). Every router builds a complete map of the network (the LSDB), then runs the SPF (Shortest Path First) algorithm independently. This gives you:

- **Loop-free routing** by construction
- **Fast convergence** when links change
- **Load balancing** across equal-cost paths (ECMP)
- **Hierarchical design** through areas

Key concepts to understand before the CLI:

| Concept | Purpose |
|---------|---------|
| Router ID | 32-bit identifier, usually the loopback or highest IP |
| Area | Logical grouping of routers — area 0 is the backbone |
| Neighbor | Adjacent router exchanging link-state updates |
| DR/BDR | Designated Router on broadcast segments (not needed on P2P) |
| Cost | Metric based on interface bandwidth (cost = reference / bandwidth) |
| LSA | Link-State Advertisement — carries routing information |

Route types you'll see in the routing table: **O** (intra-area), **O IA** (inter-area), **O E1/E2** (external, via redistribution).

If your homelab has three or more routers, or you run separate VLANs behind different routers, OSPF will save you real time. If you only have one router, static routes are fine — skip ahead or bookmark this for later.

---

## 2. Basic OSPF Configuration — Two-Router Setup

Start with the simplest topology: two routers connected by a /30 transit link, each with a LAN subnet behind it.

**Topology:**

- RouterA: LAN 10.0.10.0/24, transit .1/30 on ether1
- RouterB: LAN 10.0.20.0/24, transit .2/30 on ether1
- Transit: 10.99.99.0/30

### RouterA Configuration

```routeros
/routing ospf instance
set [ find ] name=default-vrf-instance router-id=10.0.10.1

/routing ospf area
add name=backbone area-id=0.0.0.0 instance=default-vrf-instance

/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone
add networks=10.0.10.0/24 area=backbone passive=yes
```

### RouterB Configuration

```routeros
/routing ospf instance
set [ find ] name=default-vrf-instance router-id=10.0.20.1

/routing ospf area
add name=backbone area-id=0.0.0.0 instance=default-vrf-instance

/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone
add networks=10.0.20.0/24 area=backbone passive=yes
```

The `passive=yes` on the LAN-facing network tells OSPF to advertise that subnet but never form a neighbor on it — exactly what you want for a network segment with no other routers.

### Verify OSPF Neighbors

```routeros
/routing ospf neighbor print detail
```

Expected output:

```
 0  instance=default-vrf-instance router-id=10.0.20.1
    address=10.99.99.2 interface=ether1 state=Full
    priority=1 dead-time=36s
```

State **Full** means the adjacency is established and databases are synchronized.

### Verify OSPF Routes

```routeros
/routing route print where protocol=ospf
```

You should see:

```
 0  DAc  protocol=ospf dst-address=10.0.20.0/24
         gateway=10.99.99.2 distance=110
```

RouterA now knows about 10.0.20.0/24 via OSPF — no static route needed.

---

## 3. OSPF Network Types and Interface Tuning

The default OSPF network type on Ethernet is **broadcast**, which elects a Designated Router (DR) and Backup DR. On point-to-point links like the transit segment above, this adds unnecessary overhead and delays convergence.

Switch the transit network type to **ptp** (point-to-point):

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
```

Benefits of P2P on transit links:

- No DR/BDR election (faster convergence)
- Simpler LSAs (Type 1 only, no Type 2)
- Smaller OSPF database
- No multicast timer sensitivity

### OSPF Interface Costs

By default, RouterOS calculates cost as `100 Gbps / interface-speed`. For a 1 Gbps link, the cost is 100. For 10 Gbps, cost is 10.

Override the cost explicitly if your links have asymmetric speeds:

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp cost=50
```

Lower cost = more preferred path.

### Hello/Dead Interval Tuning

The default hello interval is 10s with a 40s dead interval. For faster convergence on homelab links:

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone hello-interval=3s dead-interval=12s
```

Both routers must match hello and dead intervals, or they will reject the adjacency.

---

## 4. Multi-Area OSPF — Three-Router Topology

Once you add a third router, multi-area design becomes practical. The backbone area (0.0.0.0) must be contiguous. All other areas connect to it.

**Topology:**

- RouterA (10.0.10.1, area 0) — backbone + LAN
- RouterB (10.0.20.1, area 1) — transit to backbone + LAN
- RouterC (10.0.30.1, area 2) — transit to backbone + LAN
- Transit links: 10.99.99.0/30 (A-B), 10.99.99.4/30 (A-C)

### RouterA (Backbone, Area 0)

```routeros
/routing ospf instance
set [ find ] name=default-vrf-instance router-id=10.0.10.1

/routing ospf area
add name=backbone area-id=0.0.0.0 instance=default-vrf-instance

/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
add networks=10.99.99.4/30 area=backbone network-type=ptp
add networks=10.0.10.0/24 area=backbone passive=yes
```

### RouterB (Area 1)

```routeros
/routing ospf instance
set [ find ] name=default-vrf-instance router-id=10.0.20.1

/routing ospf area
add name=area1 area-id=0.0.0.1 instance=default-vrf-instance

/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
add networks=10.0.20.0/24 area=area1 passive=yes
```

### RouterC (Area 2)

```routeros
/routing ospf instance
set [ find ] name=default-vrf-instance router-id=10.0.30.1

/routing ospf area
add name=area2 area-id=0.0.0.2 instance=default-vrf-instance

/routing ospf interface-template
add networks=10.99.99.4/30 area=backbone network-type=ptp
add networks=10.0.30.0/24 area=area2 passive=yes
```

Verify inter-area routes on RouterB:

```routeros
/routing route print where protocol=ospf
```

You'll see both `O` (intra-area) and `O IA` (inter-area) routes. The router learns about 10.0.30.0/24 as an inter-area route via RouterA.

### Stub Areas

An **area** can be configured as stub if it has only one ABR (Area Border Router) — a very common homelab pattern. Stub areas block Type 5 LSAs (external routes) and replace them with a default route:

```routeros
/routing ospf area
add name=stub-area area-id=0.0.0.3 instance=default-vrf-instance type=stub
```

Stub areas reduce the LSDB size and memory usage on lower-end hardware like an RB750Gr3 or hAP ac².

---

## 5. Route Redistribution

Redistribution injects routes from other sources (connected, static, BGP) into OSPF.

### Redistribute Connected Routes

Advertise all directly connected networks, including management IPs and loopbacks:

```routeros
/routing ospf instance
set [ find ] redistribute=connected
```

### Redistribute Default Route

In many homelabs, one router has the default gateway to the ISP. Advertise it into OSPF so all routers know where to send internet-bound traffic:

```routeros
/routing ospf instance
set [ find ] redistribute=default
```

This injects `0.0.0.0/0` as an O E2 route (external type 2, default metric stays unchanged across the OSPF domain).

### Redistribution with Routing Filters (RouterOS 7)

RouterOS 7's routing filter chain gives you fine-grained control over what gets redistributed:

```routeros
/routing filter rule
add chain=ospf-out rule="if (dst == 10.0.0.0/8) { accept }"
add chain=ospf-out rule="reject"

/routing ospf instance
set [ find ] out-filter=ospf-out redistribute=connected
```

This only redistributes connected networks in the 10.0.0.0/8 range, rejecting anything else.

### Route Tagging for Redistribution Policy

Tag redistributed routes so you can match them in filters on other routers:

```routeros
/routing filter rule
add chain=ospf-out rule="set tag 100; accept"

/routing ospf instance
set [ find ] out-filter=ospf-out redistribute=connected
```

Then on another router, use the tag to influence route selection:

```routeros
/routing filter rule
add chain=ospf-in rule="if (tag == 100) { set distance 150; accept }"
add chain=ospf-in rule="accept"

/routing ospf instance
set [ find ] in-filter=ospf-in
```

---

## 6. OSPF Authentication

OSPF authentication prevents rogue routers from injecting false routes. RouterOS supports both simple password and MD5 cryptographic authentication.

### Simple Password Authentication

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
   authentication=simple auth-key="homelab-secret"
```

Simple passwords are sent in cleartext — fine for isolated lab networks but not production.

### MD5 Cryptographic Authentication

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
   authentication=md5 auth-key-id=1 auth-key="LabRoute#2026!"
```

Both routers must have matching `auth-key-id` and `auth-key`. The key ID rotates keys without breaking the adjacency.

### Area-Level Authentication

Apply authentication to all interfaces in an area at once:

```routeros
/routing ospf area
add name=backbone area-id=0.0.0.0 instance=default-vrf-instance
   authentication=md5 auth-key-id=1 auth-key="LabRoute#2026!"
```

Area-level authentication avoids configuring every interface template individually.

---

## 7. OSPF Passive Interfaces

Passive interfaces advertise the subnet but never send or process OSPF hellos. Every LAN-facing interface should be passive to prevent OSPF from forming adjacencies on client-facing segments and to reduce OSPF traffic.

In the interface-template, you already saw the pattern:

```routeros
/routing ospf interface-template
add networks=10.0.10.0/24 area=backbone passive=yes
```

Verify that no neighbors exist on the passive subnet:

```routeros
/routing ospf neighbor print where interface=bridge_lan
```

An empty output confirms the interface is properly passive.

---

## 8. OSPFv3 (IPv6) Configuration

RouterOS 7 supports OSPFv3 for IPv6 routing alongside OSPFv2 for IPv4. They operate independently under the same OSPF instance.

Configure OSPFv3 on the same routers:

```routeros
/routing ospf instance
set [ find ] version=v3 router-id=10.0.10.1

/routing ospf area
add name=backbone-v3 area-id=0.0.0.0 instance=default-vrf-instance

/routing ospf interface-template
add networks=2001:db8:99::/64 area=backbone-v3 network-type=ptp
add networks=2001:db8:10::/64 area=backbone-v3 passive=yes
```

Key differences from OSPFv2:

- Router ID remains an IPv4 address, even when routing only IPv6
- Interfaces are identified by link-local IPv6 addresses in neighbor output
- LSAs carry IPv6 prefixes and next-hops instead of IPv4 ones
- Authentication uses IPsec AH/ESP instead of built-in MD5

Verify OSPFv3 neighbors:

```routeros
/routing ospf neighbor print where version=v3
```

---

## 9. OSPF with Linux FRR (Optional Interop)

You can peer a MikroTik router with a Linux host running FRR (Free Range Routing) — useful for testing, education, or routing to a Docker host. This is covered in the [Docker networking patterns guide](https://gntech.dev/posts/docker-compose-networking-patterns/).

### Install FRR on Debian/Ubuntu

```bash
apt update && apt install -y frr frr-pythontools
```

### Enable OSPFd

```bash
sed -i 's/ospfd=no/ospfd=yes/' /etc/frr/daemons
systemctl restart frr
```

### Configure FRR

```bash
vtysh <<'EOF'
configure terminal
router ospf
 router-id 10.0.99.1
 network 10.99.99.0/30 area 0.0.0.0
 network 10.0.100.0/24 area 0.0.0.0
 passive-interface eth1
end
write
EOF
```

### Verify Adjacency with MikroTik

On FRR:

```bash
vtysh -c "show ip ospf neighbor"
```

On the MikroTik side, the peer appears if both sides agree on the network type, area, and authentication. Start with P2P network type on both ends for the simplest interop:

```routeros
/routing ospf interface-template
add networks=10.99.99.0/30 area=backbone network-type=ptp
```

---

## 10. Monitoring and Troubleshooting

These commands will become your daily drivers once OSPF is running:

```routeros
# Show all OSPF neighbors and their state
/routing ospf neighbor print detail

# Dump the OSPF link-state database
/routing ospf lsa print

# Show OSPF-learned routes in the routing table
/routing route print where protocol=ospf

# Real-time OSPF logs
/log print where topics~"ospf"

# Show OSPF instance summary
/routing ospf instance print detail
```

### Common Issues and Fixes

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Neighbor stuck in **ExStart/Exchange** | MTU mismatch | Set `mtu=1500` on both transit interfaces |
| Neighbor stuck in **Init** | Network type mismatch | Set both sides to broadcast or ptp |
| No routes received | Area mismatch | Verify both sides use the same area ID |
| Authentication fails | Mismatched key or key-id | Double-check `auth-key` and `auth-key-id` |
| Routes flapping | Cost oscillation | Set explicit `cost=` on interface templates |

**MTU tip:** RouterOS defaults to 1500 on Ethernet. If you use VLAN tagging or bridge VXLAN (common with [Proxmox SDN](https://gntech.dev/posts/proxmox-sdn-software-defined-networking/)), the effective MTU drops. Check with:

```routeros
/interface ethernet print mtu
/interface vlan print mtu
```

If the transit MTU is lower than 1500, lower it on the OSPF interface template too, or MTU mismatch will block the adjacency.

---

## Summary

OSPF on MikroTik RouterOS 7 is production-class dynamic routing accessible to any homelab owner with more than one router. Start with a two-router single-area setup, verify the neighbor states, and expand from there.

The RouterOS 7 interface-template approach makes configuration clean — no more per-interface OSPF setup like RouterOS 6 required. With routing filters, stub areas, and authentication, you have everything needed for a robust dynamic routing environment.

**Next steps:** Once you're comfortable with OSPF, explore BGP for WAN-facing routing, VRF for multi-tenant network segmentation, or pair OSPF with the [MikroTik firewall rules for inter-VLAN filtering](https://gntech.dev/posts/mikrotik-firewall-rules/). For a broader look at the RouterOS 7 routing stack, check the [RouterOS 7 best practices guide](https://gntech.dev/posts/mikrotik-routeros7-best-practices/).
