---
title: "MikroTik CAPsMAN VLAN — Multi-SSID Configuration Guide"
description: "Configure MikroTik CAPsMAN with VLANs for multiple SSIDs — local forwarding mode, bridge VLAN filtering, provisioning rules, and real RouterOS 7 commands for a working multi-VLAN WiFi setup."
date: 2026-05-15T15:00:00-04:00
tags:
  - mikrotik
  - networking
  - vlan
  - homelab
  - wireless
keywords:
  - MikroTik CAPsMAN VLAN configuration
  - CAPsMAN multi SSID VLAN RouterOS 7
  - MikroTik local forwarding mode VLAN
  - CAPsMAN bridge VLAN filtering setup
  - MikroTik provisioning rules multiple SSIDs
  - RouterOS 7 CAPsMAN VLAN troubleshooting
  - MikroTik VLAN trunk WiFi access points
summary: "A complete guide to configuring MikroTik CAPsMAN with VLANs in RouterOS 7 — local forwarding mode, bridge VLAN filtering, provisioning rules for multiple SSIDs, DHCP per VLAN, and real troubleshooting for the common mistakes that break CAPsMAN VLAN setups."
canonical: "https://gntech.dev/posts/mikrotik-capsman-vlan-configuration/"
---

CAPsMAN is MikroTik's centralized wireless management — one router
configures and controls every access point on your network. Add VLANs
and you get per-SSID network isolation: a work WiFi that lives on
VLAN 10, a guest network on VLAN 20, and an IoT SSID on VLAN 30 — all
from a single radio on each AP.

The problem is that MikroTik's documentation for CAPsMAN with VLANs in
RouterOS 7 is fragmented. The official wiki covers examples but misses
the edge cases that break deployments: bridge VLAN filtering gotchas,
datapath mode differences, and provisioning rules that don't trigger.

This guide covers a complete multi-SSID CAPsMAN VLAN setup in RouterOS
7.16+, using local forwarding mode, bridge VLAN filtering, and
provisioning rules that actually work.

---

## Topology and Design Decisions

Before writing any config, understand the three forwarding modes:

| Mode | Traffic Flow | VLAN Tagging Location | Best For |
|------|-------------|----------------------|----------|
| Local Forwarding | CAP → Switch → Router directly | On the CAP | Most homelabs — minimal overhead |
| CAPsMAN Forwarding | CAP → CAPsMAN → Router | On the CAPsMAN router | Centralized filtering, IDS/IPS |
| 802.11v BSS Transition | Client steers between APs | Per-AP | Mesh, high-density deployments |

**Use local forwarding.** It's simpler and faster. Traffic from each
SSID is VLAN-tagged at the access point and switched directly toward
the router — the CAPsMAN controller only manages config, it never
touches data traffic.

For this guide, the setup is:

```
Internet — [MikroTik Router (RB5009)] — trunk port — [Switch] — trunk ports — [cAP ax / hAP ac²]

VLAN Layout:
  VLAN 1   — Management (native/untagged) — 192.168.88.0/24
  VLAN 10  — Staff WiFi (SSID: Office)    — 192.168.10.0/24
  VLAN 20  — Guest WiFi (SSID: Guest)     — 192.168.20.0/24
  VLAN 30  — IoT WiFi (SSID: IoT)         — 192.168.30.0/24
```

---

## Step 1: CAPsMAN Router — Bridge and VLAN Interfaces

The CAPsMAN controller runs on the main router. Start by creating the
VLAN interfaces and enabling the CAPsMAN service.

```bash
# Create VLAN interfaces on the bridge that connects to the switch
/interface vlan
add interface=bridge name=VLAN10 vlan-id=10
add interface=bridge name=VLAN20 vlan-id=20
add interface=bridge name=VLAN30 vlan-id=30

# Assign IPs to each VLAN
/ip address
add address=192.168.10.1/24 interface=VLAN10
add address=192.168.20.1/24 interface=VLAN20
add address=192.168.30.1/24 interface=VLAN30

# DHCP pools
/ip pool
add name=dhcp-vlan10 ranges=192.168.10.10-192.168.10.254
add name=dhcp-vlan20 ranges=192.168.20.10-192.168.20.254
add name=dhcp-vlan30 ranges=192.168.30.10-192.168.30.254

# DHCP servers
/ip dhcp-server
add address-pool=dhcp-vlan10 disabled=no interface=VLAN10 name=dhcp-vlan10
add address-pool=dhcp-vlan20 disabled=no interface=VLAN20 name=dhcp-vlan20
add address-pool=dhcp-vlan30 disabled=no interface=VLAN30 name=dhcp-vlan30

# DHCP server networks (dns + gateway for each)
/ip dhcp-server network
add address=192.168.10.0/24 dns-server=192.168.88.1,1.1.1.1 gateway=192.168.10.1
add address=192.168.20.0/24 dns-server=1.1.1.1,8.8.8.8 gateway=192.168.20.1
add address=192.168.30.0/24 dns-server=192.168.88.1,1.1.1.1 gateway=192.168.30.1
```

The bridge itself becomes a VLAN trunk. Enable VLAN filtering on it so
only tagged VLANs pass through:

```bash
/interface bridge vlan
add bridge=bridge tagged=bridge,ether1,ether2 vlan-ids=10,20,30

/interface bridge port
set [find interface=ether1] frame-types=admit-only-vlan-tagged
set [find interface=ether2] frame-types=admit-only-vlan-tagged
```

Adjust the port names to match your router's physical layout. The key
is that ports connected to the switch (or directly to APs) only accept
tagged frames. Untagged frames (VLAN 1 management) should still work
on the native bridge.

---

## Step 2: CAPsMAN Configuration — SSIDs and Security

Create a CAPsMAN configuration for each SSID. This defines the SSID
name, security, and — critically — the VLAN and forwarding mode.

```bash
# Staff SSID on VLAN 10
/caps-man configuration
add name=cfg-office comment="Office WiFi - VLAN 10" \
    ssid=Office \
    country="united states" \
    security.authentication-types=wpa2-psk,wpa3-psk \
    security.passphrase="office-secure-pass-2026" \
    datapath.local-forwarding=yes \
    datapath.vlan-id=10 \
    datapath.vlan-mode=use-tag \
    datapath.client-isolation=no

# Guest SSID on VLAN 20
add name=cfg-guest comment="Guest WiFi - VLAN 20" \
    ssid=Guest \
    country="united states" \
    security.authentication-types=wpa2-psk \
    security.passphrase="guest-welcome-2026" \
    datapath.local-forwarding=yes \
    datapath.vlan-id=20 \
    datapath.vlan-mode=use-tag \
    datapath.client-isolation=yes

# IoT SSID on VLAN 30
add name=cfg-iot comment="IoT Devices - VLAN 30" \
    ssid=IoT \
    country="united states" \
    security.authentication-types=wpa2-psk \
    security.passphrase="iot-devices-2026" \
    datapath.local-forwarding=yes \
    datapath.vlan-id=30 \
    datapath.vlan-mode=use-tag \
    datapath.client-isolation=yes
```

Key parameters explained:

- **`local-forwarding=yes`** — Traffic stays local to the AP, not
  tunneled back to CAPsMAN. Required for the switch to handle VLANs.
- **`vlan-mode=use-tag`** — AP tags every client's traffic with the
  specified VLAN ID before sending it out the Ethernet port.
- **`vlan-id=10/20/30`** — The 802.1Q VLAN tag applied to client
  traffic for that SSID.
- **`client-isolation`** — Prevents wireless clients on the same SSID
  from talking to each other. Enable for guest networks, disable for
  office/staff networks that need local discovery (printers, etc.).

---

## Step 3: CAPsMAN Interface Binding

Restrict the CAPsMAN service to a specific interface — don't leave it
listening on all interfaces:

```bash
# Disable the default "all interfaces" binding
/caps-man manager interface
set [find] forbid=yes

# Add only the bridge (or management VLAN interface)
add interface=bridge disabled=no

# Enable CAPsMAN
/caps-man manager set enabled=yes
```

If you have a dedicated management VLAN, use that interface instead:

```bash
add interface=VLAN1 disabled=no
```

This prevents CAPsMAN discovery traffic from leaking onto client VLANs
and keeps the control plane clean.

---

## Step 4: Provisioning Rules — Attach SSIDs to APs

Provisioning rules tell CAPsMAN which configuration to push to which
CAP. You can match by MAC address, radio MAC, or use a catch-all.

**Catch-all rule — same SSIDs on every AP:**

```bash
/caps-man provisioning
add action=create-dynamic-enabled \
    master-configuration=cfg-office \
    slave-configurations=cfg-guest,cfg-iot
```

This creates three VAPs (Virtual Access Points) on every CAP that
connects: the master `cfg-office` (VLAN 10) and two slaves `cfg-guest`
(VLAN 20) and `cfg-iot` (VLAN 30).

**Per-AP rules — different SSIDs per access point:**

```bash
# Only push Office + IoT to AP in the main building
add action=create-dynamic-enabled \
    master-configuration=cfg-office \
    slave-configurations=cfg-iot \
    comment="Building A - no guest" \
    identity-regex="ap-building-a"

# Guest SSID only on the outdoor AP
add action=create-dynamic-enabled \
    master-configuration=cfg-guest \
    comment="Outdoor AP - guest only" \
    identity-regex="ap-outdoor"
```

Match rules are evaluated top-to-bottom. The first matching rule wins.
Use `identity-regex` to match based on the CAP's identity (set in the
CAP's `/system identity`).

---

## Step 5: CAP Configuration — Enabling the Access Points

On each MikroTik AP, enable CAP mode:

```bash
# On the AP — run this via SSH or MAC-telnet
/interface wireless cap
set enabled=yes \
    bridge=bridge \
    discovery-interfaces=bridge \
    interfaces=wlan1,wlan2
```

For **wifiwave2** package devices (cAP ax, hAP ax³, etc.):

```bash
# RouterOS 7 wifiwave2 CAP mode
/interface/wifiwave2/cap
set enabled=yes \
    slave-configurations=cfg-guest,cfg-iot \
    discovery-interfaces=bridge
```

The `bridge=bridge` setting is critical — it tells the CAP to add its
wireless interfaces to the local bridge so bridged VLAN traffic flows
correctly.

After the CAP connects, verify it in CAPsMAN:

```bash
# On the CAPsMAN router
/caps-man remote-cap print
# Columns: FLAGS, ADDRESS, IDENTITY, VERSION, RADIOS, STATE
# Look for state=running

/caps-man registration-table print
# Shows connected wireless clients and their VLAN assignment
```

---

## Step 6: Switch Configuration — Bridge VLAN Filtering

The switch between the CAPsMAN router and APs needs bridge VLAN
filtering to pass tagged traffic.

On a MikroTik switch (CRS or CSS series):

```bash
# Create the bridge with VLAN filtering
/interface bridge
add name=bridge1 vlan-filtering=yes

# Ports to CAPsMAN router and APs — trunk ports
/interface bridge port
add bridge=bridge1 interface=ether1 comment="uplink to CAPsMAN"
add bridge=bridge1 interface=ether2 comment="to AP - living room"
add bridge=bridge1 interface=ether3 comment="to AP - office"
add bridge=bridge1 interface=ether4 comment="to AP - outdoor"
add bridge=bridge1 interface=ether5 pvid=1 comment="management port"

# Define VLANs on the bridge
/interface bridge vlan
add bridge=bridge1 tagged=ether1,ether2,ether3,ether4 vlan-ids=10,20,30
add bridge=bridge1 tagged=ether1,ether2,ether3,ether4 untagged=ether5 vlan-ids=1
```

The trunk ports (ether1-4) carry tagged VLANs 10, 20, and 30.
Management traffic (VLAN 1) stays untagged on port ether5 so you can
plug a laptop directly into the switch for management access.

**For non-MikroTik switches**, create an equivalent VLAN setup:
- Port to CAPsMAN router → trunk with tagged VLANs 10, 20, 30
- Ports to APs → trunk with tagged VLANs 10, 20, 30 (PVID 1)
- Management port → access port on VLAN 1

---

## Common CAPsMAN VLAN Problems and Fixes

### Problem 1: CAP connects but SSIDs don't appear

```bash
# Check remote CAP status
/caps-man remote-cap print detail
```

If the CAP shows `state=running` but no dynamic interfaces appear,
check the provisioning rule:

```bash
# Verify the provisioning matches
/caps-man provisioning print
```

Most common cause: the provisioning rule's `identity-regex` doesn't
match the CAP's system identity. Use a catch-all rule first to confirm
the config works, then narrow it down.

### Problem 2: Clients connect but get no IP address

The DHCP server isn't reachable through the VLAN. Check:

```bash
# On the CAPsMAN router, verify DHCP is running
/ip dhcp-server print
/ip dhcp-server lease print

# Test VLAN reachability from the bridge
/ping 192.168.10.1 interface=VLAN10 count=5
```

If DHCP discovery packets never reach the router, the switch isn't
forwarding the VLAN. Double-check bridge VLAN filtering:

```bash
# On the switch, verify VLAN membership
/interface bridge vlan print
/interface bridge port print
```

Every trunk port must appear in the `tagged=` list for each VLAN.

### Problem 3: "CAPsMAN disconnects after a minute"

UDP ports 5246 and 5247 must be open between CAP and CAPsMAN router:

```bash
# Check firewall on CAPsMAN router
/ip firewall filter print

# Allow CAPsMAN control and data
/ip firewall filter
add chain=input protocol=udp dst-port=5246-5247 action=accept \
    comment="allow CAPsMAN"
```

### Problem 4: Guest network can reach staff network

Firewall rules must block inter-VLAN routing. On the CAPsMAN router:

```bash
# Block Guest VLAN 20 from reaching Staff VLAN 10 and IoT VLAN 30
/ip firewall filter
add chain=forward src-address=192.168.20.0/24 dst-address=192.168.10.0/24 action=drop \
    comment="block Guest -> Staff"
add chain=forward src-address=192.168.20.0/24 dst-address=192.168.30.0/24 action=drop \
    comment="block Guest -> IoT"

# Allow IoT to reach internet but not Staff
add chain=forward src-address=192.168.30.0/24 dst-address=192.168.10.0/24 action=drop \
    comment="block IoT -> Staff"

# Allow Staff to reach everything (for management, printers, etc.)
# No drop rule needed — default forward policy allows it

# Allow established/related traffic back
add chain=forward connection-state=established,related action=accept
```

Guest network should typically only have internet access. Block it from
all private subnets:

```bash
add chain=forward src-address=192.168.20.0/24 dst-address=192.168.0.0/16 action=drop \
    comment="block Guest -> entire LAN"
```

### Problem 5: VLAN tags stripped by switch

If your AP is connected to a dumb switch or an unmanaged switch between
the trunk and the AP, VLAN tags get stripped. CAPsMAN VLAN setups
require **managed switches** with VLAN trunk ports between the router
and every AP.

If you must use an unmanaged switch, the AP must do VLAN tagging on its
egress port. This works in local forwarding mode only if the AP's
Ethernet port connects directly to a router interface that understands
the VLANs.

---

## Verifying the Full Setup

After everything is configured, run through this checklist:

```bash
# 1. Check CAPsMAN sees all APs
/caps-man remote-cap print
# Expected: one entry per AP, state=running

# 2. Check dynamic interfaces on a CAP
# (run on the AP itself)
/interface wireless print
# Expected: wlan1 (Office), wlan2 (Guest), wlan3 (IoT)

# 3. Check VLAN assignment on the CAP
/interface bridge port print
# Expected: dynamic ports with PVID matching VLAN config
# wlan1 (PVID 10), wlan2 (PVID 20), wlan3 (PVID 30)

# 4. Check connected clients
/caps-man registration-table print
# Expected: clients with correct VLAN ID per SSID

# 5. Check DHCP leases from client perspective
/ip dhcp-server lease print where server=vlan10
# Expected: client got an IP on 192.168.10.0/24

# 6. Verify traffic isolation
# From a Guest client, try pinging a Staff client:
# Should time out (firewall drops it)
```

---

## Maintenance and Updates

**Adding a new SSID:** Create a new CAPsMAN configuration with the new
VLAN ID, add it to the provisioning rule's `slave-configurations`, then
ensure the VLAN interface, DHCP pool, and firewall rules exist on the
router.

**Adding a new AP:** Connect it to a trunk port on the switch, enable
CAP mode, and CAPsMAN auto-provisions it. No per-AP configuration
needed if using catch-all provisioning.

**Updating RouterOS on APs:** Use CAPsMAN's built-in upgrade:

```bash
# On CAPsMAN router — push firmware to all CAPs
/caps-man manager upgrade set channel=upgrade package-url="" \
    action=upgrade
```

This works best if you've already uploaded the `.npk` to the CAPsMAN
router's `files` directory:

```bash
# Upload RouterOS .npk file via web interface or SCP
# Then trigger upgrade on a specific CAP group
/caps-man manager upgrade
set channel=upgrade \
    package-url="https://upgrade.mikrotik.com/routeros/7.16.2/" \
    action=upgrade
```

For production APs, stage the upgrade: upgrade one AP, verify clients
reconnect, then upgrade the rest.

---

## Summary

MikroTik CAPsMAN with VLANs gives you proper WiFi network segmentation
without per-AP management overhead. The critical rules:

1. **Use local forwarding** — simpler, faster, and compatible with
   managed switches that do VLAN filtering
2. **Match forwarding mode everywhere** — `local-forwarding=yes` on
   every CAPsMAN configuration and `vlan-mode=use-tag` for tagged
   egress
3. **Bridge VLAN filtering is mandatory** on the switch between
   CAPsMAN router and APs — trunk ports must pass the VLANs you use
4. **Provisioning rules can be catch-all** or per-AP via
   `identity-regex` — test with a catch-all first, then narrow
5. **Firewall between VLANs** — CAPsMAN tags traffic, but isolating
   VLANs is the router's firewall job

The most common failure point is bridge VLAN filtering: a port that
isn't listed as `tagged` for a VLAN silently drops that traffic. Always
verify with `/interface bridge vlan print` on every switch and on the
CAPsMAN router's bridge.

Once it clicks, CAPsMAN VLANs are the cleanest way to run multi-SSID
WiFi in a homelab. Add an AP: plug in, enable CAP mode, done. No SSH,
no config, no per-AP tweaks. The controller handles everything.
