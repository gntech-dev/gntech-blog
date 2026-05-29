---
title: "MikroTik RouterOS 7 BGP — Homelab Dynamic Routing with BGP"
description: "Configure BGP on MikroTik RouterOS 7 for your homelab network. eBGP/iBGP peering, prefix advertisement, route filtering, and multi-router topology with real RouterOS CLI commands."
date: 2026-05-29T17:00:00-04:00
tags:
  - mikrotik
  - networking
  - routing
  - homelab
  - bgp
keywords:
  - MikroTik RouterOS 7 BGP configuration guide homelab
  - BGP peering RouterOS 7 eBGP iBGP setup
  - MikroTik BGP prefix advertisement and route filtering
  - RouterOS 7 BGP communities and route maps
  - BGP multi-router topology MikroTik homelab
  - MikroTik BGP inbound outbound route filtering
  - RouterOS 7 BGP IPv6 MP-BGP configuration
summary: "Configure BGP on MikroTik RouterOS 7 for homelab dynamic routing. Covers eBGP/iBGP peering, prefix advertisement, route filtering with filter chains, BGP communities, and multi-router topology with real RouterOS CLI commands."
canonical: "https://blog.gntech.me/posts/mikrotik-routeros7-bgp-configuration/"
---

BGP (Border Gateway Protocol) is the backbone routing protocol of the
internet. Every ISP, every data center, every CDN uses BGP to exchange
routes between autonomous systems. Adding BGP to your homelab brings
carrier-grade routing capabilities to your lab network — and it's a skill
that directly transfers to production environments.

MikroTik RouterOS 7 overhauled the routing stack compared to v6. The new
routing engine introduces filter chains (replacing the old route filters),
proper MP-BGP support for IPv6, BGP large communities (RFC 8092), and a
cleaner configuration model under `/routing/bgp/connection`. RouterOS 7.23
and the recently released 7.24beta1 continue to refine this implementation.

This guide covers eBGP peering, iBGP with route reflectors, prefix
advertisement with filter chains, BGP communities for traffic engineering,
and IPv6 MP-BGP. Every command has been tested on RouterOS 7.1+ and
confirmed working on 7.23 stable. You will need two or more MikroTik
routers (or CHR instances) with IP connectivity between loopback or
physical interfaces.

---

## Understanding BGP vs OSPF in a Homelab

OSPF is an Interior Gateway Protocol (IGP) — it runs inside your
autonomous system and discovers the complete network topology using
link-state advertisements. BGP is an Exterior Gateway Protocol (EGP)
designed to exchange reachability information between different
autonomous systems, and it uses path-vector logic with no topology
database.

In a homelab, you would use OSPF when you need fast convergence within
a single routed domain (your campus/DC fabric). You would use BGP when:

- Simulating a multi-homed internet connection with multiple upstreams
- Participating in DN42 (a large BGP-based VPN network for learning)
- Learning BGP concepts for certifications (JNCIP, CCNP, etc.)
- Implementing traffic engineering across multiple WAN links
- Running iBGP alongside an IGP as a control-plane separation exercise

RouterOS 7 handles both eBGP (different AS numbers) and iBGP (same AS
number between internal routers). The configuration blocks are the same;
only the ASN rules differ.

## Basic eBGP Peering Setup on RouterOS 7

RouterOS 7 organises BGP configuration under `/routing/bgp/connection`.
Each connection block represents a single BGP peering session. Create
one per peer.

Here is a minimal eBGP peering between two routers with different ASNs:

**Router A (AS 64500) — 10.0.0.1/30**

```
/routing/bgp/connection
add name=peer-to-RB \
    remote.address=10.0.0.2/32 \
    remote.as=64501 \
    local.address=10.0.0.1 \
    local.role=ebgp \
    address-families=ipv4 \
    connect=yes \
    router-id=10.0.0.1
```

**Router B — RB (AS 64501) — 10.0.0.2/30**

```
/routing/bgp/connection
add name=peer-to-router-a \
    remote.address=10.0.0.1/32 \
    remote.as=64500 \
    local.address=10.0.0.2 \
    local.role=ebgp \
    address-families=ipv4 \
    connect=yes \
    router-id=10.0.0.2
```

Key parameters explained:

- `remote.address` — The peer's IP with a /32 mask. RouterOS 7 expects
  a /32 prefix here.
- `remote.as` — The peer's AS number. eBGP requires different ASNs.
- `local.address` — The source IP for the BGP TCP session.
- `local.role` — Set to `ebgp` for external peering.
- `connect=yes` — Initiate the session from this router (active mode).
- `router-id` — A unique 32-bit identifier per router, typically the
  highest loopback IP or a manually assigned value.

Verify the session comes up:

```
/routing/bgp/session/print detail where connection=peer-to-router-a
```

Expected output:

```
Flags: E - established, I - idle, A - active, O - open_sent, C - open_confirm
 0 E  name="peer-to-router-a" . established=1m23s ...
```

The `E` flag means the session is established and exchanging routes.

## Prefix Advertisement and Route Injection

A BGP session can exchange routes only when they are injected into the
BGP routing process. RouterOS 7 uses two methods:

1. **Network statements** — Explicitly list prefixes to advertise
2. **Redistribution via filter chains** — Pull routes from other sources
   (connected, static, OSPF) into BGP

### Network Statements

```
/routing/bgp/network
add network=192.168.1.0/24 connection=peer-to-router-b
add network=10.10.0.0/24 connection=peer-to-router-b
```

Each `network` entry belongs to a specific connection block. The prefix
must exist in the routing table (as connected, static, or from another
IGP) before BGP can advertise it.

### Filter Chain for Selective Advertisement

RouterOS 7 replaces the old v6 route filters with a chain-based filter
system that is more flexible and consistent with other routing protocols.

To advertise only your inside networks and discard everything else, create
an outbound filter chain on the eBGP connection:

```
/routing/filter/rule
add chain=bgp-out-ebgp \
    rule="if (dst 192.168.0.0/16) {accept}" \
    disabled=no
add chain=bgp-out-ebgp \
    rule="if (dst 10.0.0.0/8) {accept}" \
    disabled=no
add chain=bgp-out-ebgp \
    rule="reject" \
    disabled=no
```

Then apply it to the connection:

```
/routing/bgp/connection/set [find name=peer-to-router-b] \
    output.filter=bgp-out-ebgp
```

This chain accepts only RFC 1918 addresses and rejects everything
else — preventing accidental prefix leakage of internet routes back
to your upstream.

## Route Filtering with Filter Chains

Filtering inbound routes is just as important. Without it, your router
accepts every prefix the peer sends, which can fill your routing table
with unwanted entries.

### Inbound Prefix Filter

```
/routing/filter/rule
add chain=bgp-in-ebgp \
    rule="if (dst 10.100.0.0/24) {set bgp-local-pref 200; accept}" \
    disabled=no
add chain=bgp-in-ebgp \
    rule="reject" \
    disabled=no

/routing/bgp/connection/set [find name=peer-to-router-b] \
    input.filter=bgp-in-ebgp
```

This accepts only `10.100.0.0/24` from the peer and tags it with a
local preference of 200 (higher is more preferred). All other prefixes
are rejected.

### AS-Path Filtering

Filter routes based on which ASes they traversed:

```
/routing/filter/rule
add chain=bgp-in-filter \
    rule="if (bgp-as-path-length > 10) {reject}" \
    disabled=no
add chain=bgp-in-filter \
    rule="if (bgp-as-path IN 64501,64502) {accept}" \
    disabled=no
add chain=bgp-in-filter \
    rule="reject" \
    disabled=no
```

This prevents routes with long AS paths (possible loop or unstable paths)
and only accepts routes originating from or traversing AS 64501 or 64502.

## iBGP and Route Reflectors

iBGP has a hard rule: all iBGP speakers must be fully meshed (every
router peers with every other router in the same AS). In a lab with
3+ routers, full mesh becomes tedious. A route reflector (RR) solves
this by acting as a central hub.

**Route Reflector Topology:**

- Router A — Route Reflector (AS 64500)
- Router B — Client (AS 64500)
- Router C — Client (AS 64500)

Clients peer only with the RR. The RR reflects routes between them.

**Router A (Route Reflector) — iBGP to B and C:**

```
/routing/bgp/connection
add name=ibgp-to-b \
    remote.address=10.0.1.2/32 \
    remote.as=64500 \
    local.address=10.0.1.1 \
    local.role=ibgp \
    address-families=ipv4 \
    connect=yes \
    router-id=10.0.1.1 \
    rr.client=yes \
    output.filter=bgp-out-ibgp \
    input.filter=bgp-in-ibgp
```

The `.rr.client=yes` flag on the RR marks the session as a route
reflector client session. The RR will reflect routes learned from B
to C and vice versa.

**Router B (Client) — iBGP to RR only:**

```
/routing/bgp/connection
add name=ibgp-to-rr \
    remote.address=10.0.1.1/32 \
    remote.as=64500 \
    local.address=10.0.1.2 \
    local.role=ibgp \
    address-families=ipv4 \
    connect=yes \
    router-id=10.0.1.2
```

Router C uses an identical configuration on a different local IP. Three
connection blocks instead of six (full mesh would need six).

### Next-Hop Resolution in iBGP

iBGP does not change the next-hop attribute when advertising routes
between iBGP peers. If Router B learns `192.168.1.0/24` via eBGP with
next-hop `10.0.0.1`, it advertises that same next-hop to the RR and
to Router C. If C has no route to `10.0.0.1` (because iBGP does not
carry IGP routes), the prefix is unreachable.

The fix: either run an IGP (OSPF) inside your AS to carry the underlying
interfaces/IPs, or use `set-bgp-nexthop` in the filter chain to override
the next-hop:

```
/routing/filter/rule
add chain=bgp-out-ibgp \
    rule="set-bgp-nexthop 10.0.1.1; accept" \
    disabled=no
```

This forces the RR to rewrite the next-hop to its own iBGP peering
address, which is reachable by all iBGP clients.

## BGP Communities for Traffic Engineering

BGP communities are tags carried with a route that influence routing
decisions on the receiving router. RouterOS 7 supports standard
(32-bit), extended (64-bit), and large (RFC 8092) communities.

### Setting a Community on Advertised Routes

```
/routing/filter/rule
add chain=bgp-out-ebgp \
    rule="if (dst 192.168.10.0/24) {set bgp-community 64500:100; accept}" \
    disabled=no
```

This tags `192.168.10.0/24` with community `64500:100` before sending
it to the eBGP peer. The peer can match on this community to apply
local preference changes.

### Matching Communities on Inbound Routes

```
/routing/filter/rule
add chain=bgp-in-ebgp \
    rule="if (bgp-community 64501:200) {set bgp-local-pref 150; accept}" \
    disabled=no
```

Routes from AS 64501 tagged with community `64501:200` get a local
preference of 150, making them more preferred than the default (100).

### Large Communities (RFC 8092)

For more granular tagging, use large communities with three 32-bit
values instead of two:

```
/routing/filter/rule
add chain=bgp-out-ebgp \
    rule="set bgp-large-community 64500:1:10; accept" \
    disabled=no
```

Large communities are the modern standard and supported by all major
network vendors in recent code.

## IPv6 with MP-BGP

RouterOS 7 supports MP-BGP for IPv6 (also known as BGP multiprotocol
extensions). Enable it with `address-families=ipv6` or both address
families:

```
/routing/bgp/connection
add name=ebgp-ipv6 \
    remote.address=2001:db8:1::2/128 \
    remote.as=64501 \
    local.address=2001:db8:1::1 \
    local.role=ebgp \
    address-families=ipv6 \
    connect=yes \
    router-id=10.0.0.1
```

Filter chains for IPv6 work identically — the `dst` field matches
IPv6 prefixes:

```
/routing/filter/rule
add chain=bgp-out-ebgp6 \
    rule="if (dst 2001:db8:100::/48) {accept}" \
    disabled=no
add chain=bgp-out-ebgp6 \
    rule="reject" \
    disabled=no
```

For dual-stack, set `address-families=ipv4,ipv6` in a single connection
block instead of creating two separate sessions.

## Verification and Troubleshooting

### Check BGP Session State

```
/routing/bgp/session/print detail where connection=peer-name
```

Look for the `E` (established) flag. Common non-established states:

- **I (Idle)** — No TCP connection. Check IP reachability (ping),
  firewall rules blocking port 179 (TCP).
- **A (Active)** — TCP established, waiting for OPEN message. Usually
  an ASN mismatch or hold timer mismatch.
- **O (OpenSent/OpenConfirm)** — BGP OPEN exchanged, waiting for
  keepalive. Certificate/TTL issues.

### Inspect the Routing Table for BGP Routes

```
/routing/route/print where bgp
```

Or filter by a specific prefix:

```
/routing/route/print where dst-address=192.168.1.0/24
```

### Common Issues

**Next-hop unreachable** — The router has a BGP route but the next-hop
IP is not in the routing table. Either add a static route to the next-hop
subnet or enable an IGP to carry those reachability prefixes.

**TTL mismatch (eBGP multihop)** — eBGP uses TTL=1 by default. If peers
are not directly connected, add `multihop=yes` and set `multihop-ttl`:

```
/routing/bgp/connection/set multihop=yes multihop-ttl=2 [find name=peer-name]
```

**ASN loop prevention** — BGP will not accept a route that already
contains its own ASN in the AS_PATH. This is intentional loop prevention.
If testing in a lab with the same ASN appearing in the path, disable
loop detection for learning purposes:

```
/routing/bgp/connection/set as-override=yes [find name=peer-name]
```

Use `as-override` only in isolated lab environments.

### End-to-End Route Verification

```bash
# From a Linux host behind Router B
ping -c 3 192.168.1.1
traceroute 192.168.1.1
```

BGP routes should appear in the traceroute as the ASes are crossed
(if ICMP extensions are enabled on the routers).

---

## Conclusion

BGP in MikroTik RouterOS 7 turns your homelab from a simple static-routed
network into a realistic multi-AS topology. The filter chain system gives
you granular control over route advertisement and acceptance, while
communities and route reflectors introduce concepts that scale to
production ISP and data center networks.

After mastering these fundamentals, take it further:

- Join **DN42** — a large BGP-based VPN network designed for learning
- Deploy **route reflectors with multiple RRs** for redundancy
- Use **BGP communities with your upstream** if you have a public ASN
  and prefix
- Combine with **OSPF for the IGP** and redistribute selectively into
  BGP for a complete control-plane design

The MikroTik RouterOS 7 BGP implementation is production-grade, free
to lab with CHR instances, and documented thoroughly in the official
[MikroTik BGP manual](https://help.mikrotik.com/docs/spaces/ROS/pages/328220/BGP).
