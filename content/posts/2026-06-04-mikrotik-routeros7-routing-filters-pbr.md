---
title: "MikroTik RouterOS 7 Routing Filters — Policy-Based Routing and Route Selection"
description: "Master MikroTik RouterOS 7 routing filters and policy-based routing. Configure route maps, BGP filters, mangle rules, and routing marks for traffic steering in your network lab."
date: 2026-06-04T16:00:00-04:00
tags:
  - mikrotik
  - routeros
  - networking
  - routing
keywords:
  - MikroTik RouterOS 7 routing filter configuration guide
  - Policy-based routing MikroTik routing marks mangle setup
  - MikroTik BGP route filtering as-path prefix-list
  - RouterOS 7 routing filter chain match action example
  - MikroTik dual WAN policy-based routing failover
  - RouterOS 7 route selection routing-mark mangle tos
  - MikroTik network traffic steering policy routing CLI
summary: "Configure MikroTik RouterOS 7 routing filters for BGP, OSPF, and policy-based routing. Real CLI examples for route maps, mangle rules, routing marks, and traffic steering."
canonical: "https://blog.gntech.me/posts/mikrotik-routeros7-routing-filters-pbr/"
---

## Introduction to MikroTik RouterOS 7 Routing Filters

If you moved from RouterOS 6 to RouterOS 7, the first thing you noticed about routing is that everything changed. The old firewall-style routing filter rules are gone. In their place is a **declarative filter chain** — a script-like language that operates on route attributes rather than firewall chains. This change affects BGP, OSPF, RIP, and even your static route selection.

Policy-based routing (PBR) is separate but complementary. Where routing filters control *which routes exist* in the routing table, PBR controls *which routing table traffic uses*. Combined, they give you complete traffic engineering in your MikroTik network.

This guide covers:
- RouterOS 7 routing filter architecture and syntax
- BGP route filtering with AS path, prefix, and community filters
- Policy-based routing with mangle rules and routing marks
- Dual WAN traffic steering and failover
- Troubleshooting common filter and PBR issues

## Understanding RouterOS 7 Routing Filter Architecture

RouterOS 7 introduces a **unified routing filter engine** used by all routing protocols. Filters are defined as independent chain rules and then attached to a protocol or VRF.

### Filter Chains

Each routing protocol has up to four filter chains:

| Chain | Direction | Purpose |
|-------|-----------|---------|
| `in` | Inbound | Filter routes before they enter the routing table |
| `out` | Outbound | Filter routes before advertising to peers |
| `default-in` | Inbound | Applied when no `in` chain exists |
| `default-out` | Outbound | Applied when no `out` chain exists |

Filters are configured under `/routing filter rule` and referenced by name in the protocol configuration.

### Route Attributes Available in Filters

RouterOS 7 routing filters operate on per-route attributes. The most commonly used ones:

- `dst-address` — destination prefix
- `gateway` — next-hop address
- `distance` — administrative distance
- `routing-mark` — associated routing table
- `bgp-as-path` — BGP AS_PATH attribute
- `bgp-communities` — BGP community list
- `bgp-local-pref` — BGP local preference
- `pref-src` — preferred source address
- `scope` — route scope for next-hop resolution

### Filter Flow — Match and Action

Every filter rule has a condition (match) and an action. Rules are evaluated in order. The first matching rule with a terminal action (accept/reject) terminates the chain.

```mikrotik
/routing filter rule
add chain=bgp-in \
    if-dst-length=32 \
    action=reject

add chain=bgp-in \
    if-gateway="10.0.0.1" \
    action=accept
```

If no rule matches, the implicit reject applies — the route is denied.

## Basic Routing Filter Syntax

Filter rules use a consistent syntax. Here are the core building blocks:

### Matching on Prefix

```mikrotik
/routing filter rule
add chain=bgp-in if-dst-address="10.0.0.0/8" action=accept

# Reject /32 routes (host routes from BGP)
add chain=bgp-in if-dst-length=32 action=reject

# Accept only prefixes /24 or smaller
add chain=bgp-in if-dst-length=24-32 action=accept
```

### Matching on BGP AS Path

```mikrotik
# Accept only routes with origin AS 65001
add chain=bgp-in if-bgp-as-path="^65001$" action=accept

# Reject routes from AS 65099 (transit ISP)
add chain=bgp-in if-bgp-as-path=".*65099.*" action=reject

# Accept routes with exactly 2 AS hops
add chain=bgp-in if-bgp-as-path-length=2 action=accept
```

## BGP Route Filtering with Routing Filters

Let's put together a complete BGP filter setup. This example assumes a BGP session with an upstream ISP (AS 64500) and an internal peer (AS 65001).

### Inbound Filter — Control What Enters Your Table

```mikrotik
/routing filter rule
# Chain: bgp-in — applied to inbound BGP updates

# 1. Reject default route from internal peer
add chain=bgp-in \
    if-dst-address="0.0.0.0/0" \
    if-bgp-as-path="^65001$" \
    action=reject

# 2. Accept specific prefixes from upstream (AS 64500)
add chain=bgp-in \
    if-bgp-as-path="^64500$" \
    if-dst-address="203.0.113.0/24" \
    action=accept

# 3. Accept default route only from upstream
add chain=bgp-in \
    if-dst-address="0.0.0.0/0" \
    if-bgp-as-path="^64500$" \
    action=accept

# 4. Accept internal routes from AS 65001
add chain=bgp-in \
    if-bgp-as-path="^65001$" \
    action=accept

# 5. Reject everything else (security)
add chain=bgp-in \
    action=reject
```

### Outbound Filter — Control What You Advertise

```mikrotik
/routing filter rule
# Chain: bgp-out — applied to outbound BGP updates

# 1. Only advertise your own prefixes
add chain=bgp-out \
    if-dst-address="198.51.100.0/24" \
    action=accept

# 2. Don't advertise private ranges
add chain=bgp-out \
    if-dst-address="10.0.0.0/8" \
    action=reject

add chain=bgp-out \
    if-dst-address="192.168.0.0/16" \
    action=reject

# 3. Reject everything else
add chain=bgp-out \
    action=reject
```

### Attaching Filters to a BGP Connection

```mikrotik
/routing bgp connection
add name=isp-upstream \
    remote.address=203.0.113.1 \
    remote.as=64500 \
    local.role=ebgp \
    routing-table=main \
    .in.filter=bgp-in \
    .out.filter=bgp-out
```

> Note the syntax: `.in.filter` and `.out.filter` reference the filter chain names you created.

## Policy-Based Routing with Routing Marks and Mangle

Policy-based routing (PBR) lets you route traffic based on source address, protocol, port, packet size, or any combination — rather than just the destination.

### Architecture

The PBR pipeline in RouterOS 7 is:

1. **Firewall mangle** marks packets or connections
2. **Routing marks** identify the routing table to use
3. **Separate routing tables** contain the custom routes
4. **Routing rules** direct marked traffic to the correct table

### Step 1 — Mark Traffic with Mangle

```mikrotik
/ip firewall mangle
# Mark all traffic from VLAN 10 (office) to use the office routing table
add chain=prerouting \
    src-address=10.0.10.0/24 \
    action=mark-routing \
    new-routing-mark=office \
    passthrough=yes

# Mark all HTTP/HTTPS traffic from VLAN 20 (guest) to use a filtered WAN
add chain=prerouting \
    src-address=10.0.20.0/24 \
    protocol=tcp \
    dst-port=80,443 \
    action=mark-routing \
    new-routing-mark=guest-web \
    passthrough=yes

# Mark all traffic to specific destination (VPN subnet) via dedicated table
add chain=prerouting \
    dst-address=10.200.0.0/16 \
    action=mark-routing \
    new-routing-mark=vpn \
    passthrough=yes
```

The `passthrough=yes` parameter makes the packet continue to subsequent mangle rules. Use `passthrough=no` if you want to stop processing after the match.

### Connection Marking for Stateful Routing

For stateful PBR (recommended), mark connections instead of individual packets:

```mikrotik
# Mark connections from the office VLAN
add chain=prerouting \
    src-address=10.0.10.0/24 \
    action=mark-connection \
    new-connection-mark=office-conn \
    passthrough=yes

# Route all packets in those connections
add chain=prerouting \
    connection-mark=office-conn \
    action=mark-routing \
    new-routing-mark=office \
    passthrough=no
```

Connection marking ensures that return traffic follows the same path.

### Step 2 — Create Routing Tables

```mikrotik
/routing table
add name=office fib
add name=guest-web fib
add name=vpn fib

# The 'fib' flag means the table participates in FIB resolution
# — required for the routes to be usable
```

### Step 3 — Add Routes to Each Table

```mikrotik
/ip route
# Office traffic goes via ISP1
add dst-address=0.0.0.0/0 \
    gateway=172.16.1.1 \
    routing-mark=office \
    distance=1

# Guest web traffic goes via ISP2
add dst-address=0.0.0.0/0 \
    gateway=172.16.2.1 \
    routing-mark=guest-web \
    distance=1

# VPN traffic via Wireguard interface
add dst-address=0.0.0.0/0 \
    gateway=wg0 \
    routing-mark=vpn \
    distance=1
```

### Step 4 — Routing Rules (Optional)

Routing rules direct traffic *before* the main routing table lookup. They are evaluated before standard destination-based routing:

```mikrotik
/routing rule
# Send traffic from specific source to custom table
add src-address=10.0.10.0/24 table=office

# Send traffic to specific destination via VPN table
add dst-address=10.200.0.0/16 table=vpn

# Everything else uses the main table
add table=main
```

Use routing rules as an alternative to mangle-based marking when you only need source or destination-based PBR.

## Dual WAN with Policy-Based Routing

A common homelab scenario: two ISPs where one handles general traffic and the other handles specific services (or backup).

### Basic Dual WAN Setup

Assume WAN1 on ether1 (gateway 172.16.1.1) and WAN2 on ether2 (gateway 172.16.2.1).

```mikrotik
# Default route via WAN1 (lower distance = preferred)
/ip route
add dst-address=0.0.0.0/0 \
    gateway=172.16.1.1 \
    distance=1

# Backup route via WAN2
add dst-address=0.0.0.0/0 \
    gateway=172.16.2.1 \
    distance=2
```

### PBR for Specific Traffic via WAN2

Force certain traffic to use WAN2 even when WAN1 is up:

```mikrotik
/ip firewall mangle
# Mark DNS and NTP traffic to use WAN2
add chain=prerouting \
    protocol=udp \
    dst-port=53,123 \
    action=mark-routing \
    new-routing-mark=wan2 \
    passthrough=no

# Mark torrent traffic to use WAN2
add chain=prerouting \
    protocol=tcp \
    dst-port=6881-6999 \
    action=mark-routing \
    new-routing-mark=wan2 \
    passthrough=no

/routing table
add name=wan2 fib

/ip route
add dst-address=0.0.0.0/0 \
    gateway=172.16.2.1 \
    routing-mark=wan2 \
    distance=1
```

### Failover with Route Checks

For production failover, add recursive next-hop checks:

```mikrotik
/ip route
# WAN1 with recursive check
add dst-address=0.0.0.0/0 \
    gateway=172.16.1.1 \
    distance=1 \
    check-gateway=ping

# WAN2 with recursive check
add dst-address=0.0.0.0/0 \
    gateway=172.16.2.1 \
    distance=2 \
    check-gateway=ping
```

When `check-gateway=ping` is set, RouterOS periodically pings the gateway. If the ping fails, the route is disabled and traffic falls back to the next available route.

## Advanced Filtering — BGP Communities and Local Preference

### Setting Local Preference with Filters

Control inbound route preference before it reaches the routing table:

```mikrotik
/routing filter rule
# Set high local-pref for routes tagged with community 64512:100
add chain=bgp-in \
    if-bgp-communities="64512:100" \
    set-bgp-local-pref=200 \
    action=accept

# Set medium local-pref for routes from upstream
add chain=bgp-in \
    if-bgp-as-path="^64500$" \
    set-bgp-local-pref=150 \
    action=accept

# Default local-pref for everything else
add chain=bgp-in \
    action=accept
```

### Manipulating BGP Communities

```mikrotik
# Append a community to outbound routes
add chain=bgp-out \
    if-dst-address="198.51.100.0/24" \
    set-bgp-communities="64501:200" \
    action=accept

# Strip communities from routes before advertising to upstream
add chain=bgp-out \
    set-bgp-communities="" \
    action=accept
```

### Route Tagging with Routing Filters

Use routing filters as a route-map to tag routes for later PBR:

```mikrotik
/routing filter rule
# Tag routes from specific BGP peer with a routing mark
add chain=bgp-in \
    if-bgp-as-path="^65001$" \
    set-routing-mark=internal \
    action=accept
```

## Troubleshooting Routing Filters and PBR

### Verify Active Routes

```mikrotik
# Show all routes
/routing route print

# Show routes in a specific routing table
/routing route print where routing-mark=office

# Show BGP routes specifically
/routing route print where protocol=bgp
```

### Check What BGP Is Advertising

```mikrotik
# Show advertised routes for a BGP session
/routing bgp session advertisements print \
    session=isp-upstream

# Show received routes
/routing bgp session routes print \
    session=isp-upstream
```

### Debug PBR Traffic Flow

```mikrotik
# Check which routing table a specific packet would use
# First check mangle hits
/ip firewall mangle print stats

# Then check the routing table lookup with routing mark
/routing route print where routing-mark=guest-web

# Verify routing rules are in order
/routing rule print
```

### Common Pitfalls

**1. Filter chain ordering matters**

Rules are evaluated in the order they were created. An `accept` rule before a `reject` rule means the reject never runs. Always put specific match rules before general ones.

```mikrotik
# WRONG: This accepts everything before the reject
add chain=bgp-in action=accept
add chain=bgp-in if-dst-address="10.0.0.0/8" action=reject

# RIGHT: Specific reject first
add chain=bgp-in if-dst-address="10.0.0.0/8" action=reject
add chain=bgp-in action=accept
```

**2. Implicit reject at end of chain**

If no rule matches, the route is **rejected**. Always end your chains with an explicit `action=accept` for the traffic you want to allow, or an explicit `action=reject` to block everything else.

**3. Mangle rules need the correct chain**

- `prerouting` for traffic coming into the router (both forwarded and locally destined)
- `forward` only for forwarded traffic
- `output` for traffic generated by the router itself

For PBR, always use `chain=prerouting` so the routing mark is applied before the route lookup.

**4. Routing table missing FIB flag**

If you create a routing table without the `fib` flag, routes in that table won't be resolvable:

```mikrotik
# Check if your table has FIB enabled
/routing table print

# Enable it
/routing table set office fib=yes
```

## Putting It All Together

RouterOS 7 routing filters and policy-based routing give you complete traffic engineering control. The key differences from RouterOS 6:

- **Filters are declarative**, not firewall-style — define the match condition and action
- **PBR uses mangle + routing-mark + separate routing tables** — no more `routing-mark` in static routes
- **Routing rules** provide an alternative to mangle for simple source/destination-based PBR

Start simple: create a BGP inbound filter that blocks obvious garbage (host routes, bogons), then layer on policy routing for traffic segmentation. Always test with `print` commands before applying to production.

A well-configured routing filter chain keeps your routing table clean. Combined with PBR, you get per-client, per-protocol traffic control that rivals enterprise routers — all on MikroTik hardware.
