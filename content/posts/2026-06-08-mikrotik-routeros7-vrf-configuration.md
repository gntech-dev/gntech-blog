---
title: "MikroTik RouterOS 7 VRF Configuration — Multi-Tenant Network Segmentation"
description: "Configure VRFs on MikroTik RouterOS 7 for multi-tenant network segmentation. Static routes, BGP VRF, route leaking, and firewall integration for homelab routing."
date: 2026-06-08T07:00:00-04:00
tags:
  - mikrotik
  - networking
  - routing
  - homelab
keywords:
  - MikroTik RouterOS 7 VRF configuration guide homelab
  - VRF network segmentation MikroTik multi-tenant routing
  - MikroTik VRF BGP route leaking RouterOS 7
  - RouterOS 7 VRF static routes route tables networking
  - MikroTik VRF firewall rules interface assignment homelab
  - MikroTik CRS3xx VRF L3 routing hardware offload
  - RouterOS 7 multi-tenancy VRF route separation ISP WAN
summary: "Configure VRFs on MikroTik RouterOS 7 for multi-tenant network segmentation. Step-by-step guide covering VRF creation, static routes, BGP VRF, route leaking between VRFs, firewall integration, and practical homelab topology examples."
canonical: "https://blog.gntech.me/posts/mikrotik-routeros7-vrf-configuration/"
---

## What Is VRF and Why Use It in Your Homelab

VRF (Virtual Routing and Forwarding) is a technology that allows a single router to maintain multiple independent routing tables. Each VRF has its own forwarding table, its own set of interfaces, and its own routing protocol instances. This means IP addresses can overlap across VRFs without conflict, and traffic in one VRF never leaks into another by default.

In a homelab context, VRFs solve a problem that VLANs alone cannot. VLANs separate traffic at Layer 2, but once traffic reaches the router's Layer 3 interface, everything converges into a single routing table. VRFs extend separation to Layer 3 — each VRF gets its own routing table, its own default gateway, and its own routing protocol sessions.

Common homelab use cases for VRFs include:

- **Multi-WAN separation** — each WAN uplink in its own VRF with independent routing policies
- **IoT isolation** — IoT devices use a separate routing domain with controlled internet access and no LAN reachability
- **Guest networks** — guests get a VRF with internet-only access, no inter-VRF transit
- **Lab environments** — overlapping IP ranges for testing without conflicts with production
- **Tenant isolation** — separate routing domains for different users or services on shared infrastructure

MikroTik RouterOS 7 introduced robust VRF support that has matured significantly through versions 7.14 through 7.23. With the recent RouterOS 7.24beta1 release, VRF integration continues to improve. RouterOS 7 uses a routing-table-based VRF model where each VRF maps to a routing table, separate from the main table.

## Prerequisites and Topology Overview

Before configuring VRFs, ensure you are running **RouterOS 7.x** — VRF support is not available in RouterOS 6. Any RouterOS 7 device works: CHR, RB5009, RB4011, CCR series, or x86 installations. CRS3xx switches running RouterOS in L3 mode also support VRF.

This guide uses a three-VRF topology for a typical homelab:

| VRF Name     | Purpose     | Subnet            | Uplink     | Table ID |
|--------------|-------------|-------------------|------------|----------|
| (main)       | WAN / mgmt  | DHCP from ISP     | ether1     | main     |
| VRF-RED      | Trusted LAN | 192.168.10.0/24   | bridge-red | 100      |
| VRF-BLUE     | IoT network | 10.0.100.0/24     | bridge-iot | 200      |
| VRF-GREEN    | Guest       | 172.16.0.0/24     | bridge-gst | 300      |

The bridge interfaces (`bridge-red`, `bridge-iot`, `bridge-gst`) are each part of a separate VLAN-aware bridge on different physical switch ports. This combines VLAN L2 separation with VRF L3 routing.

## Creating VRFs and Assigning Interfaces

Creating a VRF in RouterOS 7 is straightforward — add a VRF entry that maps to a routing table, then assign interfaces.

```bash
# Create routing tables for each VRF
/routing table add name=vrf-red fib=100
/routing table add name=vrf-blue fib=200
/routing table add name=vrf-green fib=300

# Create VRF entries linking interfaces to tables
/routing vrf add interface=bridge-red routing-mark=vrf-red
/routing vrf add interface=bridge-iot routing-mark=vrf-blue
/routing vrf add interface=bridge-gst routing-mark=vrf-green
```

Alternatively, you can assign interfaces and set routing marks through the IP settings:

```bash
/ip vrf add interface=bridge-red routing-mark=vrf-red
/ip vrf add interface=bridge-iot routing-mark=vrf-blue
/ip vrf add interface=bridge-gst routing-mark=vrf-green
```

Verify the configuration:

```bash
/routing table print
/routing vrf print
```

Example output:

```text
Columns: NAME, INTERFACES
# NAME       INTERFACES
0 vrf-red    bridge-red
1 vrf-blue   bridge-iot
2 vrf-green  bridge-gst
```

## Configuring IP Addresses on VRF Interfaces

Each VRF interface needs an IP address. Because the interface is assigned to a VRF, the address belongs to that VRF's routing table only.

```bash
# Trusted LAN (VRF-RED)
/ip address add address=192.168.10.1/24 interface=bridge-red network=192.168.10.0

# IoT network (VRF-BLUE)
/ip address add address=10.0.100.1/24 interface=bridge-iot network=10.0.100.0

# Guest network (VRF-GREEN)
/ip address add address=172.16.0.1/24 interface=bridge-gst network=172.16.0.0
```

The key behavior here: these addresses only appear in their respective VRF routing tables. A ping to 192.168.10.1 from the guest network (VRF-GREEN) will not reach it unless routes between VRFs exist.

## Static Routes with VRF Routing Tables

Each VRF needs its own default route. Set the routing mark to match the VRF:

```bash
# Default route in VRF-RED via ISP gateway
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 routing-table=vrf-red distance=1

# Default route in VRF-BLUE via ISP gateway
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 routing-table=vrf-blue distance=1

# Default route in VRF-GREEN via ISP gateway
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 routing-table=vrf-green distance=1
```

For connected subnets within the homelab, add static routes so each VRF knows how to reach its local networks:

```bash
/ip route add dst-address=192.168.10.0/24 gateway=192.168.10.1 routing-table=vrf-red
/ip route add dst-address=10.0.100.0/24 gateway=10.0.100.1 routing-table=vrf-blue
/ip route add dst-address=172.16.0.0/24 gateway=172.16.0.1 routing-table=vrf-green
```

Verify routes per VRF:

```bash
/ip route print where table=vrf-red
/ip route print where table=vrf-blue
/ip route print where table=vrf-green
```

## BGP VRF Configuration

For larger homelabs with dynamic routing, RouterOS 7 supports BGP within VRFs. Each VRF gets its own BGP instance and peering.

```bash
# Create a BGP instance bound to VRF-RED
/routing bgp instance set default vrf=vrf-red

# Or add a separate instance for a specific VRF
/routing bgp instance add name=bgp-vrf-red vrf=vrf-red as=64501
/routing bgp instance add name=bgp-vrf-blue vrf=vrf-blue as=64502
```

Add BGP peers within each VRF:

```bash
# Peer with upstream router in VRF-RED
/routing bgp peer add name=peer-red instance=bgp-vrf-red remote-address=10.0.0.2 remote-as=64500

# Peer with upstream in VRF-BLUE
/routing bgp peer add name=peer-blue instance=bgp-vrf-blue remote-address=10.0.1.2 remote-as=64500
```

Redistribute connected routes into BGP per VRF:

```bash
/routing bgp network add network=192.168.10.0/24 synchronize=yes
/routing bgp network add network=10.0.100.0/24 synchronize=yes
```

The BGP process inside each VRF only sees routes from its own routing table. A BGP update received via VRF-RED goes into the vrf-red table only.

## Route Leaking Between VRFs

By default, VRFs are completely isolated — no traffic passes between them. When you need selective inter-VRF communication (e.g., IoT devices reaching a DNS server on the trusted LAN), you configure route leaking.

### Route Leaking with Routing Filters

RouterOS 7 uses routing filter rules to import or export routes between tables. The pattern creates a filter chain attached to the destination table:

```bash
# Create a filter chain that leaks specific routes into VRF-RED
/routing filter rule add chain=leak-to-vrf-red \
    src-address=192.168.10.0/24 action=accept
/routing filter rule add chain=leak-to-vrf-red \
    dst-address=10.0.100.0/24 action=accept
/routing filter rule add chain=leak-to-vrf-red action=discard

# Apply filter to the destination table (VRF-RED imports these routes)
/routing table set vrf-red filter-chain=leak-to-vrf-red
```

A simpler and more common pattern for static leaking uses static routes with appropriate scope and target-scope:

```bash
# On the main table, add route through VRF-RED gateway
/ip route add dst-address=10.0.100.0/24 gateway=10.0.100.1 routing-table=main

# On VRF-RED, add route to main table networks
/ip route add dst-address=10.0.20.0/24 gateway=192.168.10.100 routing-table=vrf-red
```

The key consideration: you need a routing path between the VRFs. If the router has an interface in both VRFs (or a shared management network), you can leak specific routes.

For more controlled leaking in RouterOS 7, use the routing rule feature:

```bash
# Add a routing rule to redirect specific traffic
/routing rule add src-address=172.16.0.0/24 dst-address=192.168.10.53/32 \
    action=lookup table=vrf-red
/routing rule add src-address=10.0.100.0/24 dst-address=192.168.10.53/32 \
    action=lookup table=vrf-red
```

This pattern redirects traffic from VRF-GREEN and VRF-BLUE to the DNS server at 192.168.10.53 into the VRF-RED table, enabling DNS resolution without full inter-VRF routing.

## Firewall Rules per VRF

Firewall in a VRF environment requires careful attention. The RouterOS firewall processes packets against the routing table the packet arrived on, not the VRF name. This means your rules should match on inbound interfaces.

### Default-Deny Inter-VRF Policy

```bash
# Drop inter-VRF traffic by default (forward chain)
/ip firewall filter add chain=forward src-address-list=!trusted_subnets \
    action=drop comment="Default deny inter-VRF"

# Or match specific interface combinations
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red action=drop \
    comment="Block IoT to trusted LAN"
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=bridge-red action=drop \
    comment="Block guest to trusted LAN"
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=bridge-iot action=drop \
    comment="Block guest to IoT"
```

### Selective Allow Rules

Allow specific services between VRFs:

```bash
# Allow IoT to reach DNS (192.168.10.53) on trusted LAN
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red dst-address=192.168.10.53/32 \
    protocol=udp dst-port=53 action=accept \
    comment="Allow IoT DNS to trusted DNS"

# Allow IoT to reach NTP on trusted LAN
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red dst-address=192.168.10.53/32 \
    protocol=udp dst-port=123 action=accept \
    comment="Allow IoT NTP to trusted NTP"

# Allow guest internet (WAN access) - strict
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=ether1 action=accept \
    comment="Allow guest to WAN"

# Drop guest to internal networks
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=!ether1 action=drop \
    comment="Block guest to internal"
```

### NAT Per VRF

NAT rules must also account for VRFs. Configure masquerade for each VRF's outbound traffic:

```bash
# NAT for VRF-RED
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-red action=masquerade \
    comment="NAT VRF-RED to WAN"

# NAT for VRF-BLUE
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-blue action=masquerade \
    comment="NAT VRF-BLUE to WAN"

# NAT for VRF-GREEN
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-green action=masquerade \
    comment="NAT VRF-GREEN to WAN"
```

The `routing-mark` match ensures that only traffic belonging to the specific VRF gets NAT'd.

## Complete Homelab Topology Example

Here is a consolidated example combining all the concepts. This assumes a MikroTik RB5009 with ether1 as WAN, ether2-ether5 for trusted LAN, ether6-ether7 for IoT, and ether8 as guest access point uplink.

```bash
# --- Routing Tables ---
/routing table add name=vrf-red fib=100
/routing table add name=vrf-blue fib=200
/routing table add name=vrf-green fib=300

# --- VRF Definitions ---
/routing vrf add interface=bridge-red routing-mark=vrf-red
/routing vrf add interface=bridge-iot routing-mark=vrf-blue
/routing vrf add interface=bridge-gst routing-mark=vrf-green

# --- IP Addresses ---
/ip address add address=192.168.10.1/24 interface=bridge-red \
    network=192.168.10.0
/ip address add address=10.0.100.1/24 interface=bridge-iot \
    network=10.0.100.0
/ip address add address=172.16.0.1/24 interface=bridge-gst \
    network=172.16.0.0

# --- Default Routes per VRF ---
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 \
    routing-table=vrf-red distance=1
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 \
    routing-table=vrf-blue distance=1
/ip route add dst-address=0.0.0.0/0 gateway=100.64.0.1 \
    routing-table=vrf-green distance=1

# --- NAT ---
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-red action=masquerade
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-blue action=masquerade
/ip firewall nat add chain=srcnat out-interface=ether1 \
    routing-mark=vrf-green action=masquerade

# --- Firewall: Inter-VRF Default-Deny ---
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red action=drop
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=bridge-red action=drop
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=bridge-iot action=drop

# --- Firewall: Selective Allows ---
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red dst-address=192.168.10.53/32 \
    protocol=udp dst-port=53 action=accept
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red dst-address=192.168.10.53/32 \
    protocol=udp dst-port=123 action=accept

# --- Firewall: Guest internet only ---
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=ether1 action=accept
/ip firewall filter add chain=forward in-interface=bridge-gst \
    out-interface=!ether1 action=drop

# --- DNS Forwarding for IoT ---
/routing rule add src-address=10.0.100.0/24 dst-address=192.168.10.53/32 \
    action=lookup table=vrf-red
```

## Verification and Troubleshooting

Test connectivity within each VRF:

```bash
# Ping from router in VRF-RED
/ping 192.168.10.100 vrf=vrf-red

# Ping internet from VRF-BLUE
/ping 8.8.8.8 vrf=vrf-blue

# Traceroute from VRF-GREEN
/tool traceroute 1.1.1.1 vrf=vrf-green
```

Verify routing tables are populated correctly:

```bash
/routing route print where table=vrf-red
/routing route print where table=vrf-blue
/routing route print where table=vrf-green
```

Common pitfalls and solutions:

| Problem | Symptom | Fix |
|---------|---------|-----|
| No internet in VRF | Ping fails to 8.8.8.8 from VRF | Check default route and routing-mark on NAT rule |
| Inter-VRF traffic blocked | Can ping but higher ports fail | Review firewall filter rules — connection tracking expected state |
| Address in wrong table | `ip route print` shows missing routes | Verify VRF interface assignment with `/routing vrf print` |
| BGP not establishing | Peer stuck in idle | BGP source address must be in the VRF interface's subnet |
| DNS not resolving | Name resolution fails from IoT | Check routing rule for DNS leaking into VRF-RED table |

For persistent connectivity issues, enable traffic logging on the firewall to see which interface pair is dropping packets:

```bash
/ip firewall filter add chain=forward in-interface=bridge-iot \
    out-interface=bridge-red action=log \
    comment="Trace IoT to trusted drops"
```

Remove the logging rule after debugging.

## When to Use VRFs vs Other Segmentation Methods

VRFs solve a different problem than VLANs. Use this decision matrix:

| Method | Separation Level | Use Case |
|--------|-----------------|----------|
| **VLAN** | Layer 2 | Broadcast domain isolation, guest WiFi SSIDs |
| **VRF** | Layer 3 | Overlapping IPs, separate routing domains, multi-ISP |
| **VLAN + VRF** | Layer 2 + 3 | Full isolation with L2 segmentation and independent routing |
| **Bridge filter** | Layer 2 only | Simple inter-VLAN blocking without L3 routing |

In practice, most homelabs benefit from VLANs for L2 separation combined with VRFs for L3 routing where traffic crosses different routing domains. If your ISP provides a /29 public block and you also have a secondary LTE uplink, VRFs keep those routing tables independent.

For simple guest WiFi isolation where guests just need internet, a VLAN with a firewall rule blocking inter-VLAN traffic is sufficient. Add VRFs when you need overlapping IP addressing or independent routing policies per tenant.

## Summary

VRFs in MikroTik RouterOS 7 provide powerful Layer 3 network segmentation that goes beyond what VLANs offer. Each VRF gets its own routing table, its own BGP instances, and its own set of firewall and NAT rules. Combined with VLANs at Layer 2, VRFs enable full multi-tenant network isolation in a homelab environment.

Start by identifying your logical segmentation needs — trusted LAN, IoT, guest, lab. Create a VRF per segment, assign interfaces, configure per-VRF routing with default routes and NAT, then add firewall rules to enforce inter-VRF policy. Route leaking and routing rules provide controlled gateways between VRFs for specific services like DNS and NTP.

RouterOS 7 has matured VRF support to a point where it is stable enough for daily-driver homelab use. Start with the topology and config in this guide, adapt the IP ranges and interface names to your setup, and test each VRF independently before enabling inter-VRF forwarding.
