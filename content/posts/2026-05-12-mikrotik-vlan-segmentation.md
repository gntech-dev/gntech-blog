---
title: "MikroTik VLAN Segmentation — Inter-VLAN Routing, DHCP, and Firewall Rules"
description: "Practical MikroTik VLAN setup for a segmented homelab — bridge VLAN filtering, per-VLAN DHCP servers, firewall rules for inter-VLAN routing, and optional CAPsMAN WiFi. All CLI commands, no Winbox clicking."
date: 2026-05-12T11:00:00-04:00
tags:
  - mikrotik
  - networking
  - vlan
  - routeros
  - homelab
categories:
  - homelab
  - networking
---

Consumer routers give you one flat LAN. Everything talks to everything.
That's fine for five devices. Not fine for a homelab with IoT toasters,
security cameras, a NAS with your whole life on it, and a gaming PC that
absolutely does not need to see the Frigate NVR's admin interface.

MikroTik's RouterOS handles VLANs natively — bridge VLAN filtering,
inter-VLAN routing, per-VLAN DHCP, and firewall rules to control traffic
between segments. All from the CLI. No third-party tools, no extra
switches, no license fees.

This post walks through a real segmented network on a MikroTik RB5009:
management, servers, IoT, guest, and home VLANs with full firewall
isolation between them.

---

## Architecture

```
                         ┌──────────────────┐
                         │     Internet      │
                         └────────┬─────────┘
                                  │ PPPoE / DHCP
                         ┌────────▼─────────┐
                         │   MikroTik Router │
                         │ (RB5009 / RB4011) │
                         └──┬───┬───┬───┬───┘
                            │   │   │   │
        VLAN10 Mgmt ────────┤   │   │   │
        VLAN20 Servers ─────┘   │   │   │
        VLAN30 IoT ─────────────┘   │   │
        VLAN40 Guest ───────────────┘   │
        VLAN50 Home ────────────────────┘
```

### VLAN Plan

| VLAN | Name | Subnet | Purpose |
|------|------|--------|---------|
| 1 | Native (untagged) | 10.0.10.0/24 | Management (router, switches, APs) |
| 10 | mgmt | 10.0.10.0/24 | Host management, Proxmox, iDRAC, IPMI |
| 20 | servers | 10.0.20.0/24 | Docker hosts, NAS, VMs |
| 30 | iot | 10.0.30.0/24 | Cameras, smart plugs, sensors |
| 40 | guest | 10.0.40.0/24 | Guest WiFi — internet only |
| 50 | home | 10.0.50.0/24 | Personal devices, laptops, phones |

### Firewall Rules (Intended Behavior)

| Source | Destination | Action | Reason |
|--------|-------------|--------|--------|
| mgmt (10) | any | allow | Admins manage everything |
| servers (20) | iot, home | allow | NAS accessible, services reachable |
| iot (30) | any | drop | Cameras don't phone home unchecked |
| guest (40) | internet only | drop | Guest WiFi is isolated |
| home (50) | servers, internet | allow | Normal user access |

---

## 1. Configure the Bridge with VLAN Filtering

The modern way to do VLANs on RouterOS 7 is **bridge VLAN filtering**.
You create one bridge, add all ports, and tag/untag VLANs at the bridge
level. The switch chip handles forwarding at wire speed instead of
routing through the CPU.

```bash
# Create the bridge with VLAN filtering enabled
/interface bridge add name=bridge1 fast-forward=yes
/interface bridge set bridge1 vlan-filtering=yes

# Add physical ports to the bridge
/interface bridge port add bridge=bridge1 interface=ether1       # WAN - not bridged
/interface bridge port add bridge=bridge1 interface=ether2       # LAN ports
/interface bridge port add bridge=bridge1 interface=ether3
/interface bridge port add bridge=bridge1 interface=ether4
/interface bridge port add bridge=bridge1 interface=ether5
/interface bridge port add bridge=bridge1 interface=sfp1

# Tag bridge ports as trunk (ports that carry multiple VLANs)
/interface bridge port set [find interface=ether2] tag=yes
/interface bridge port set [find interface=ether3] tag=yes
/interface bridge port set [find interface=ether4] tag=yes
/interface bridge port set [find interface=ether5] tag=yes
/interface bridge port set [find interface=sfp1] tag=yes
```

Wait — `tag=yes` on bridge ports configures the port as an **access port**
in the default VLAN (usually VLAN 1), not a trunk. In RouterOS 7, the
correct approach is different. Let me clarify:

### Bridge Port Modes

| Mode | Setting | Behavior |
|------|---------|----------|
| **Access** | `pvid=<vlan>` + no VLAN tag in bridge VLAN table for this port | Port accepts untagged traffic on PVID VLAN |
| **Trunk** | `tag=yes` + VLAN entries with `tagged=<port>` | Port carries multiple tagged VLANs |

For our setup:
- `ether2` → trunk to the managed switch
- `ether3-ether5` → access ports (untagged) for direct devices
- `sfp1` → trunk to another switch or AP

```bash
# Trunk port — carries all VLANs tagged
/interface bridge port add bridge=bridge1 interface=ether2 tag=yes

# Access ports — assign a VLAN per port
/interface bridge port add bridge=bridge1 interface=ether3 pvid=10   # mgmt
/interface bridge port add bridge=bridge1 interface=ether4 pvid=30   # IoT
/interface bridge port add bridge=bridge1 interface=ether5 pvid=50   # Home

# SFP trunk
/interface bridge port add bridge=bridge1 interface=sfp1 tag=yes

# Create bridge VLAN entries
/interface bridge vlan add bridge=bridge1 vlan-ids=10 tagged=bridge1,ether2,sfp1 untagged=ether3
/interface bridge vlan add bridge=bridge1 vlan-ids=20 tagged=bridge1,ether2,sfp1
/interface bridge vlan add bridge=bridge1 vlan-ids=30 tagged=bridge1,ether2,sfp1 untagged=ether4
/interface bridge vlan add bridge=bridge1 vlan-ids=40 tagged=bridge1,ether2,sfp1
/interface bridge vlan add bridge=bridge1 vlan-ids=50 tagged=bridge1,ether2,sfp1 untagged=ether5
```

**Key detail:** The bridge itself must be in the `tagged` list for every
VLAN. That's how the CPU (and thus RouterOS routing) can reach those
VLANs.

---

## 2. VLAN Interfaces on the Bridge

Each VLAN needs a routed interface on the bridge so the router can
assign IP addresses, serve DHCP, and apply firewall rules.

```bash
/interface vlan add name=vlan10-mgmt   vlan-id=10 interface=bridge1
/interface vlan add name=vlan20-servers vlan-id=20 interface=bridge1
/interface vlan add name=vlan30-iot     vlan-id=30 interface=bridge1
/interface vlan add name=vlan40-guest   vlan-id=40 interface=bridge1
/interface vlan add name=vlan50-home    vlan-id=50 interface=bridge1
```

---

## 3. IP Addresses and DHCP

```bash
# Assign gateway IPs
/ip address add address=10.0.10.1/24  interface=vlan10-mgmt
/ip address add address=10.0.20.1/24  interface=vlan20-servers
/ip address add address=10.0.30.1/24  interface=vlan30-iot
/ip address add address=10.0.40.1/24  interface=vlan40-guest
/ip address add address=10.0.50.1/24  interface=vlan50-home

# DHCP server on each VLAN
/ip pool add name=pool-mgmt   ranges=10.0.10.100-10.0.10.200
/ip pool add name=pool-server ranges=10.0.20.100-10.0.20.200
/ip pool add name=pool-iot    ranges=10.0.30.10-10.0.30.50
/ip pool add name=pool-guest  ranges=10.0.40.100-10.0.40.150
/ip pool add name=pool-home   ranges=10.0.50.50-10.0.50.200

/ip dhcp-server add name=dhcp-mgmt   interface=vlan10-mgmt   address-pool=pool-mgmt   lease-time=1d
/ip dhcp-server add name=dhcp-server interface=vlan20-servers address-pool=pool-server lease-time=7d
/ip dhcp-server add name=dhcp-iot    interface=vlan30-iot     address-pool=pool-iot    lease-time=1d
/ip dhcp-server add name=dhcp-guest  interface=vlan40-guest   address-pool=pool-guest  lease-time=2h
/ip dhcp-server add name=dhcp-home   interface=vlan50-home    address-pool=pool-home   lease-time=1d

# DHCP networks (tell clients the gateway + DNS)
/ip dhcp-server network add address=10.0.10.0/24  gateway=10.0.10.1  dns-server=10.0.20.5,1.1.1.1
/ip dhcp-server network add address=10.0.20.0/24  gateway=10.0.20.1  dns-server=10.0.20.5,1.1.1.1
/ip dhcp-server network add address=10.0.30.0/24  gateway=10.0.30.1  dns-server=1.1.1.1
/ip dhcp-server network add address=10.0.40.0/24  gateway=10.0.40.1  dns-server=1.1.1.1
/ip dhcp-server network add address=10.0.50.0/24  gateway=10.0.50.1  dns-server=10.0.20.5,1.1.1.1
```

Note the different lease times: servers get 7 days (stable IPs), guests
get 2 hours (transient), IoT gets 1 day (cameras don't move).

---

## 4. Firewall Rules — Controlling Inter-VLAN Traffic

This is where the real work happens. RouterOS processes firewall rules
top-down, first match wins. The default action for forward chain is
`accept`, so we need explicit drop rules before traffic flows.

### Base Setup (NAT for internet access)

First, ensure internet works. This is standard MASQUERADE on the WAN:

```bash
/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade
```

### Inter-VLAN Rules

The strategy: allow only what's needed, drop everything else.

```bash
# Allow established/related connections (essential for return traffic)
/ip firewall filter add chain=forward connection-state=established,related action=accept

# Allow ICMP (ping) from management to all VLANs for troubleshooting
/ip firewall filter add chain=forward src-address=10.0.10.0/24 protocol=icmp action=accept

# VLAN 10 (mgmt) → any: full access
/ip firewall filter add chain=forward src-address=10.0.10.0/24 dst-address=10.0.0.0/8 action=accept

# VLAN 20 (servers) → VLAN 50 (home): allow specific ports (SMB, Plex, etc.)
/ip firewall filter add chain=forward src-address=10.0.20.0/24 dst-address=10.0.50.0/24 \
  protocol=tcp dst-port=139,445,2049,32400 action=accept
/ip firewall filter add chain=forward src-address=10.0.20.0/24 dst-address=10.0.50.0/24 \
  protocol=udp dst-port=137,138,53,1900,5353 action=accept

# VLAN 20 (servers) → VLAN 30 (IoT): allow (NAS stores camera footage, Frigate queries cameras)
/ip firewall filter add chain=forward src-address=10.0.20.0/24 dst-address=10.0.30.0/24 action=accept

# VLAN 50 (home) → VLAN 20 (servers): allow (users access services)
/ip firewall filter add chain=forward src-address=10.0.50.0/24 dst-address=10.0.20.0/24 action=accept

# VLAN 50 (home) → VLAN 10 (mgmt): allow (IT folks can manage)
/ip firewall filter add chain=forward src-address=10.0.50.0/24 dst-address=10.0.10.0/24 action=accept

# Drop IoT → anything (IoT devices are untrusted)
/ip firewall filter add chain=forward src-address=10.0.30.0/24 action=drop

# Drop guest → anything (internet only, allowed by NAT rule above)
/ip firewall filter add chain=forward src-address=10.0.40.0/24 dst-address=!0.0.0.0/0 action=drop

# Drop everything else between VLANs (catch-all)
/ip firewall filter add chain=forward src-address=10.0.0.0/8 dst-address=10.0.0.0/8 action=drop
```

**Important:** The NAT MASQUERADE rule runs in the `nat` table, not the
`filter` table. Traffic from guest VLAN to the internet goes: FORWARD
chain (filter) → allowed by default → hits NAT MASQUERADE → WAN. The
drop rule for guest only matches when destination is *not* internet
(`dst-address=!0.0.0.0/0` — effectively private ranges and local).

### Understanding Rule Order

The established/related rule must be first. Without it, return traffic
from a server response to a home client gets dropped by the catch-all.
Everything after it is for *new* connections only.

```
Rule 1: established,related → accept           (return traffic for all)
Rule 2: mgmt → any → accept                    (admins go everywhere)
Rule 3-6: specific allow rules                  (targeted access)
Rule 7: IoT → any → drop                        (isolate IoT)
Rule 8: guest → !internet → drop               (guest isolation)
Rule 9: inter-VLAN catch-all → drop            (default deny)
```

---

## 5. VLANs with WiFi (CAPsMAN)

If you have MikroTik wireless APs (hAP ax², cAP ax, etc.), CAPsMAN
manages them centrally. Each SSID is mapped to a VLAN.

```bash
# Create CAPsMAN configuration
/caps-man configuration add name=cfg-mgmt   ssid="Home-Mgmt"   security.authentication-types=wpa2-psk, wpa3-psk security.passphrase="changeme"
/caps-man configuration add name=cfg-home   ssid="Home"        security.authentication-types=wpa2-psk, wpa3-psk security.passphrase="changeme"
/caps-man configuration add name=cfg-iot    ssid="Home-IoT"    security.authentication-types=wpa2-psk security.passphrase="changeme"
/caps-man configuration add name=cfg-guest  ssid="Guest"       security.authentication-types=wpa2-psk security.passphrase="changeme"

# Assign VLANs per SSID
/caps-man configuration set cfg-mgmt   vlan.mode=use-tag vlan.vlan-id=10
/caps-man configuration set cfg-home   vlan.mode=use-tag vlan.vlan-id=50
/caps-man configuration set cfg-iot    vlan.mode=use-tag vlan.vlan-id=30
/caps-man configuration set cfg-guest  vlan.mode=use-tag vlan.vlan-id=40

# Enable CAPsMAN and provision APs
/caps-man manager set enabled=yes
/caps-man manager interface set [find] disabled=no

# Provision CAP (auto-discovery)
/caps-man provisioning add action=create-dynamic-enabled master-configuration=cfg-home
```

**AP side (one-time):** Set each AP to CAP mode and point it at the
router:

```bash
/interface wireless cap set discovery-interfaces=bridge1 enabled=yes
```

The AP tags traffic with the correct VLAN ID. The router's bridge VLAN
table handles the rest — traffic tagged VLAN 30 goes to the IoT subnet
and hits the IoT firewall rules automatically.

---

## 6. Verifying It Works

```bash
# Check bridge VLAN table
/interface bridge vlan print

# Show which VLANs each port carries
/interface bridge port print detail

# Check active DHCP leases
/ip dhcp-server lease print

# Show all VLAN interfaces and their IPs
/ip address print where interface~"vlan"

# Monitor firewall hits
/ip firewall filter print stats

# Trace a packet from IoT to server (test)
/tool traceroute 10.0.20.5 src-address=10.0.30.10
```

A quick end-to-end test: connect a laptop to `ether4` (IoT access port),
set a static IP in 10.0.30.0/24, and try:

```bash
# Should work (internet access)
ping 1.1.1.1

# Should fail (isolated from home VLAN)
ping 10.0.50.10

# Should work if you have NAS/DNS in servers
ping 10.0.20.5
```

---

## 7. Performance Notes

**Bridge VLAN filtering uses the switch chip** (on RB5009, CRS3xx
series). Traffic between ports in the same VLAN is hardware-offloaded at
wire speed. Traffic *between* VLANs hits the CPU for routing — that's
expected and fine on an RB5009 (up to ~5 Gbps inter-VLAN routing).

Check hardware offloading:

```bash
/interface bridge port print detail where hardware-offload=yes
```

If a port shows `hardware-offload=no`, something is preventing it
(Common causes: datapath ACLs, untagged VLAN on a port with `tag=yes`,
or a port with `pvid` set to 0).

**For maximum throughput:** Keep VLAN 1 (native/untagged) off the
management interface and assign explicit PVIDs. RouterOS 7 handles
untagged VLANs more cleanly when every port has an explicit PVID.

---

## Summary

```bash
# Quick checklist after setup
# 1. Bridge VLAN filtering enabled?
/interface bridge print detail where name=bridge1
# → vlan-filtering should show "yes"

# 2. All VLANs reachable via the bridge?
/interface bridge vlan print
# → bridge1 tagged in every VLAN

# 3. DHCP running on each VLAN?
/ip dhcp-server print

# 4. Firewall rules applied in correct order?
/ip firewall filter print

# 5. Internet works from guest VLAN?
# Connect to Guest WiFi, browse a site
```

VLAN segmentation is one of those things you set up once and never think
about again — until a cheap IoT camera tries to reach some random
Chinese server on port 443 and the firewall silently drops it. That's
the moment it pays off.

The same patterns work across all RouterOS devices — RB5009, RB4011,
hAP ax², CRS3xx switches. Bridge VLAN filtering is the standard now.
Skip the old `vlan` interface on physical ports approach; the bridge
method is faster, cleaner, and the only path to hardware offloading.

