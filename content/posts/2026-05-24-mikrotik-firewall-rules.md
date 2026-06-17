---
title: "MikroTik RouterOS 7 Firewall — Rules, FastTrack, and Connection Tracking"
description: "Complete guide to MikroTik RouterOS 7 firewall — filter rules, FastTrack performance tuning, connection tracking states, address lists, and brute force protection for homelab routers."
date: 2026-05-24T12:00:00-04:00
tags:
  - mikrotik
  - routeros
  - networking
  - firewall
  - security
  - homelab
keywords:
  - MikroTik RouterOS 7 firewall filter rules and chains
  - MikroTik FastTrack connection performance tuning
  - MikroTik connection tracking states established related
  - MikroTik address list brute force protection SSH
  - MikroTik raw table connection untracked bypass
  - MikroTik firewall NAT masquerade rule configuration
  - MikroTik RouterOS 7 firewall rule ordering best practices
summary: "Configure a production-ready MikroTik RouterOS 7 firewall — understand filter, NAT, mangle, and raw tables, enable FastTrack for wire-speed forwarding, implement connection tracking state rules, and build brute force protection with dynamic address lists."
canonical: "https://gntech.dev/posts/mikrotik-firewall-rules/"
---

The MikroTik firewall is one of the most flexible packet filtering engines available at any price point. Built on top of Linux Netfilter, RouterOS gives you four independent firewall tables (filter, NAT, mangle, raw) with connection tracking, stateful inspection, Layer 7 matching, and FastTrack hardware-accelerated forwarding. It's also where most homelab configurations have subtle gaps that leave the router vulnerable.

This guide covers every aspect of the MikroTik firewall as it exists in RouterOS 7.x: how packets move through each table and chain, how connection tracking assigns states, when to use FastTrack and when to avoid it, how to build effective address lists for brute force protection, and a complete, practical firewall ruleset you can apply to any RouterOS device.

Every command shown here works in RouterOS 7.16+. All examples use the CLI (terminal), but the same rules can be configured through Winbox or WebFig.

---

## Firewall Tables and Packet Flow

RouterOS has four firewall tables, processed in a strict order:

1. **Raw** — Pre-connection tracking filtering. Use this to bypass connection tracking for traffic you don't need to track (bulk transfers, trusted LAN-to-LAN flows).
2. **Mangle** — Packet marking for routing policy, QoS, and routing table selection. Runs after connection tracking.
3. **Filter** — Accept or drop packets. The main security rules live here.
4. **NAT** — Source (srcnat) and destination (dstnat) address translation. Evaluated after filter rules.

Each table has up to three built-in chains:

- **Input** — Packets destined for the router itself (SSH, Winbox, API)
- **Forward** — Packets passing through the router between interfaces (LAN → WAN, VLAN → VLAN)
- **Output** — Packets originating from the router (DNS queries, NTP syncs)

The order matters. Raw processes first, then mangle, then filter, then NAT. A packet dropped in the filter chain never reaches NAT — which is why you place security rules in filter and don't duplicate them in NAT.

```text
Packet arrives
   ↓
Raw (pre-connection tracking)
   ↓
Connection tracking (assigns state)
   ↓
Mangle (mark routing, QoS)
   ↓
Filter (accept or drop)
   ↓
NAT (srcnat/dstnat)
   ↓
Route decision
```

---

## Connection Tracking and Packet States

Connection tracking is what makes RouterOS a stateful firewall. Every packet is classified into one of five states:

| State | Meaning |
|-------|---------|
| **new** | First packet of a connection (TCP SYN, or first UDP packet) |
| **established** | Part of an existing, tracked connection |
| **related** | Belongs to a related connection (FTP data, ICMP errors) |
| **invalid** | Not part of any tracked connection — usually malformed or spoofed |
| **untracked** | Explicitly excluded from connection tracking via raw table |

The standard stateful rule pattern places accept rules for established/related/untracked and a drop rule for invalid at the top of each chain, so only new packets need full rule evaluation:

```
/ip firewall filter
add chain=input connection-state=invalid action=drop comment="Drop Invalid Input"
add chain=input connection-state=established,related,untracked action=accept comment="Allow Established/Related/Untracked Input"
add chain=forward connection-state=invalid action=drop comment="Drop Invalid Forward"
add chain=forward connection-state=established,related,untracked action=accept comment="Allow Established/Related/Untracked Forward"
```

This pattern drastically reduces CPU load. Established connections match at rule 1 and skip the remaining rules.

### Connection Tracking Table

You can inspect active connections with:

```
/ip firewall connection print count-only
/ip firewall connection print where protocol=tcp
/ip firewall connection print where dst-port=443
```

If your tracking table grows large (50k+ entries), tune the timeouts:

```
/ip firewall connection tracking set tcp-established-timeout=1d
/ip firewall connection tracking set udp-timeout=30s
/ip firewall connection tracking set generic-timeout=5m
```

For routers with limited RAM, reduce `max-connections`:

```
/ip firewall connection tracking set max-connections=32768
```

---

## FastTrack — Wire-Speed Forwarding

FastTrack is a special handler that bypasses the Linux network stack entirely for established TCP and UDP connections. It enables wire-speed forwarding on capable hardware (ARM64, x86) even at 1 Gbps+ line rates.

### When to Use FastTrack

FastTrack is safe when you don't need per-connection accounting, queue trees, or IPSec on the same traffic. It's ideal for:

- Home internet routing (LAN → WAN bulk traffic)
- Media streaming traffic
- General web browsing

### When to Avoid FastTrack

FastTrack **bypasses** firewall, connection tracking, simple queues, queue tree with parent=global, IP accounting, and IPSec. Don't FastTrack traffic that needs:

- VLAN-to-VLAN firewall rules on the same router
- Bandwidth limiting with queue trees
- Traffic marked for VPN routing
- Per-connection accounting

### FastTrack Configuration

Place these two rules at the **top** of the forward filter chain:

```
/ip firewall filter
add chain=forward action=fasttrack-connection connection-state=established,related comment="FastTrack Established/Related"
add chain=forward action=accept connection-state=established,related comment="Accept Established/Related"
```

The second rule is required because not all packets in a FastTracked connection go through the fast path — some still hit the slow path and need an explicit accept.

To verify FastTrack is active:

```
/ip firewall filter print where action=fasttrack-connection
/ip firewall connection print where fasttrack=yes count-only
```

### Raw Table — Connection Tracking Bypass

For traffic that doesn't need stateful inspection at all (trusted LAN backups, rsync, NFS), bypass connection tracking entirely:

```
/ip firewall raw
add chain=forward src-address=10.0.20.0/24 dst-address=10.0.30.0/24 action=notrack comment="Bypass CT for LAN inter-vlan"
```

This saves RAM and CPU. The packets show as `connection-state=untracked` in the filter chain and must be allowed with a matching accept rule.

---

## Secure Default Filter Ruleset

The following ruleset provides a solid foundation. Adjust interface names (`ether1`, `bridge`) and trusted subnets to match your setup.

```rsc
# ===========================================
# Input Chain — Protect the Router Itself
# ===========================================

/ip firewall filter

# 1. Invalid packets → drop immediately
add chain=input connection-state=invalid action=drop comment="Drop Invalid Input"

# 2. Established/related → accept
add chain=input connection-state=established,related,untracked action=accept comment="Allow Established/Related/Untracked Input"

# 3. Allow ICMP (ping) from anywhere — but rate-limit
add chain=input protocol=icmp action=accept comment="Allow ICMP" \
    icmp-options=8:0 limit=5,5:packet

# 4. Allow management from trusted LAN only
add chain=input protocol=tcp dst-port=22,8291 src-address=10.0.0.0/16 \
    action=accept comment="Allow SSH/Winbox from LAN"

# 5. Allow API/API-SSL from trusted sources if needed
add chain=input protocol=tcp dst-port=8728,8729 src-address=10.0.0.0/16 \
    action=accept comment="Allow API from LAN"

# 6. Allow essential services (DHCP, NTP, DNS)
add chain=input protocol=udp dst-port=67,68 action=accept comment="Allow DHCP"
add chain=input protocol=udp dst-port=123 action=accept comment="Allow NTP"
add chain=input protocol=udp dst-port=53 action=accept comment="Allow DNS"

# 7. Drop everything else to the router
add chain=input action=drop comment="Drop All Other Input"

# ===========================================
# Forward Chain — Traffic Through Router
# ===========================================

# 1. FastTrack at the top
add chain=forward action=fasttrack-connection connection-state=established,related \
    comment="FastTrack Established/Related"
add chain=forward action=accept connection-state=established,related \
    comment="Accept Established/Related Forward"

# 2. Drop invalid
add chain=forward connection-state=invalid action=drop comment="Drop Invalid Forward"

# 3. Allow LAN to WAN (srcnat handles masquerade)
add chain=forward src-address=10.0.0.0/16 out-interface=ether1 action=accept \
    comment="Allow LAN to WAN"

# 4. Allow related responses back
add chain=forward dst-address=10.0.0.0/16 in-interface=ether1 connection-state=established,related \
    action=accept comment="Allow WAN Established to LAN"

# 5. Optional: block inter-VLAN by default, allow selectively
# add chain=forward src-address=10.0.10.0/24 dst-address=10.0.20.0/24 action=accept \
#     comment="Allow IoT to Services VLAN"
# add chain=forward action=drop comment="Drop Inter-VLAN by Default"

# 6. Drop everything else forward
add chain=forward action=drop comment="Drop All Other Forward"
```

### NAT — Source Masquerade

```
/ip firewall nat
add chain=srcnat out-interface=ether1 action=masquerade comment="Masquerade LAN to WAN"
```

For static IP or multiple WAN IPs, use `action=src-nat to-addresses=WAN_IP` instead of masquerade.

---

## Address Lists for Dynamic Blocking

Address lists are the RouterOS equivalent of IP set or groups — named collections of IPs you can reference in firewall rules. They can be static or populated dynamically.

### Dynamic Brute Force Protection

This is the single most impactful security rule you can add. It tracks connection attempts from each IP and blocks those exceeding a threshold:

```
/ip firewall filter

# Track new SSH connections from WAN
add chain=input protocol=tcp dst-port=22 connection-state=new \
    src-address-list=ssh_blacklist action=drop \
    comment="Drop SSH from Blacklisted IPs"

add chain=input protocol=tcp dst-port=22 connection-state=new \
    action=add-src-to-address-list address-list=ssh_blacklist \
    address-list-timeout=1h \
    comment="Add SSH Attempt to Blacklist"

# Track new Winbox connections
add chain=input protocol=tcp dst-port=8291 connection-state=new \
    src-address-list=winbox_blacklist action=drop \
    comment="Drop Winbox from Blacklisted IPs"

add chain=input protocol=tcp dst-port=8291 connection-state=new \
    action=add-src-to-address-list address-list=winbox_blacklist \
    address-list-timeout=1h \
    comment="Add Winbox Attempt to Blacklist"
```

This only works if SSH/Winbox are already allowed from LAN only — it's defense-in-depth. If you must expose management to WAN, add a connection-rate check:

```
add chain=input protocol=tcp dst-port=22 src-address-list=!allowed_admin \
    connection-state=new connection-rate=10,3 action=add-src-to-address-list \
    address-list=ssh_blacklist address-list-timeout=1h \
    comment="Rate-limit SSH, moving violators to blacklist"
```

### Static Address Lists for Whitelisting

Define trusted IP ranges or VPN peers:

```
/ip firewall address-list
add list=allowed_admin address=10.0.0.10 comment="Admin Desktop"
add list=allowed_admin address=10.0.1.0/24 comment="Management VLAN"
add list=vpn_peers address=172.16.0.0/24 comment="Wireguard Peers"
add list=known_crawlers address=1.1.1.0/24 comment="Cloudflare DNS"
```

Then reference them in rules:

```
add chain=input protocol=tcp dst-port=22 src-address-list=allowed_admin \
    action=accept comment="Allow SSH from Admin Only"
```

---

## Layer 7 Filtering

RouterOS supports basic Layer 7 (application-layer) regex matching. Use it sparingly — it consumes significant CPU and works only on the first packets.

### Blocking Streaming or P2P

```
/ip firewall layer7-protocol
add name=p2p regexp="^(torrent|.*\.torrent)"

/ip firewall filter
add chain=forward layer7-protocol=p2p action=drop \
    comment="Drop P2P traffic"
```

Layer 7 patterns are matched against the **first 2 KB** of application data. They won't match encrypted traffic (HTTPS, modern QUIC).

---

## Logging and Monitoring

Enable logging on drop rules during initial deployment to verify rules behave as expected:

```
/ip firewall filter add chain=input action=drop comment="Drop Input (Logged)" \
    log=yes log-prefix="FW_DROP_INPUT "
```

Check logs:

```
/log print where message~"FW_DROP_INPUT"
```

Inspect hit counts per rule:

```
/ip firewall filter print stats
```

The `stats` column shows packet and byte counts for every rule. Use this to identify rules that never match (dead rules) or rules matching too aggressively.

---

## Rule Ordering Checklist

Firewall rules in RouterOS are evaluated from top to bottom. First match wins. Follow these ordering rules:

1. **FastTrack** rules first (forward chain only)
2. **Connection state** accept rules (established/related/untracked)
3. **Invalid** drop rules
4. **Targeted allow** rules (specific ports, IPs, services)
5. **Address list dynamic** rules (rate limiting, blacklisting)
6. **Catch-all drop** rules

Never place blanket accept rules before specific drop rules unless the accept is for established/related traffic only.

---

## Complete Quick-Start One-Liner

If you're starting from a factory reset and want a reasonably secure baseline in one session:

```
/ip firewall filter
add chain=input connection-state=invalid action=drop
add chain=input connection-state=established,related,untracked action=accept
add chain=input protocol=icmp action=accept icmp-options=8:0 limit=5,5:packet
add chain=input protocol=tcp dst-port=22,8291 src-address=10.0.0.0/16 action=accept
add chain=input protocol=udp dst-port=67,68,123,53 action=accept
add chain=input action=drop
add chain=forward action=fasttrack-connection connection-state=established,related
add chain=forward action=accept connection-state=established,related
add chain=forward connection-state=invalid action=drop
add chain=forward src-address=10.0.0.0/16 out-interface=ether1 action=accept
add chain=forward action=drop

/ip firewall nat
add chain=srcnat out-interface=ether1 action=masquerade
```

Replace `10.0.0.0/16` with your LAN subnet and `ether1` with your WAN interface name.

---

## Summary

The MikroTik RouterOS 7 firewall is powerful but demands correct rule ordering and a firm understanding of connection tracking. Start with the stateful accept/drop pattern, add FastTrack for forwarding performance, protect management services with address-list-based dynamic blocking, and always monitor with `print stats` and logs during initial deployment. The raw table gives you fine-grained control over what gets tracked, and NAT runs after filtering so security rules aren't duplicated.

A properly configured MikroTik firewall handles 1 Gbps WAN links at under 5% CPU utilization while blocking brute force attempts autonomously — that's the sweet spot for any homelab router.
