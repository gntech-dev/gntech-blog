---
title: "MikroTik WireGuard — Site-to-Site and Road Warrior VPN Setup"
description: "Configure WireGuard on MikroTik RouterOS for both road warrior (remote client) and site-to-site VPN, with firewall rules, split tunneling, and performance tuning for a VLAN-segmented homelab."
date: 2026-05-08T00:27:22-04:00
tags:
  - mikrotik
  - wireguard
  - vpn
  - routeros
  - networking
  - homelab
categories:
  - homelab
  - networking
---

WireGuard on MikroTik RouterOS is production-ready as of RouterOS 7.x, and it's dramatically simpler than IPsec or OpenVPN for homelab use. No certificate authorities, no confusing phase 1/phase 2 settings, no userspace daemon eating CPU — just a kernel module, a private key, and a peer config.

This post covers two WireGuard topologies running on the same MikroTik router (R1 from the [previous deployment post](/posts/r1-router-deployment/)):

1. **Road Warrior** — remote devices (phone, laptop) connect to the homelab
2. **Site-to-Site** — two MikroTik routers connected across the internet

Both share the same base config and coexist on the same router.

---

## WireGuard on RouterOS 7 — What Changed

RouterOS 6 had WireGuard as a beta package. RouterOS 7 ships it baked in:

```
/system package print where name~wireguard
```

If you don't see it, update RouterOS — it's included in all 7.x builds.

Compared to older VPN options:

| Feature | WireGuard | IPsec/IKEv2 | OpenVPN |
|---------|-----------|-------------|---------|
| Lines of config | ~5 | ~30+ | ~40+ |
| Kernel module | Yes | Yes | Userspace (slow) |
| Roaming | Built-in | Requires config | Requires config |
| Noise protocol | Yes | IKE overhead | TLS handshake |
| MTU handling | Needs tuning | Auto | Tends to work |
| CPU on MikroTik | Very low | Moderate | High |

For a homelab, WireGuard is the right default. IPsec only wins if you need legacy device compatibility or built-in OS clients that don't support WireGuard natively.

---

## Base Setup — Keys and Interface

### Generate Keys

WireGuard uses Curve25519 key pairs. Generate them on the router:

```
/tool wg-genkey
```

This outputs a private key. Derive the public key:

```
/tool wg-genkey
:set privKey [get]
:set pubKey [/tool wg-genkey public-key from-key $privKey]
:put $pubKey
```

Or generate both in one command on a Linux machine:

```bash
wg genkey | tee private.key | wg pubkey > public.key
```

Save both keys. You'll need the public key for remote peers, and the private key stays in the router config.

### WireGuard Interface

```
/interface wireguard add name=wg-home listen-port=51820 private-key="<private-key>"
```

No IP assigned to the WireGuard interface just yet — IP assignment is per-peer or you can assign it from a pool.

---

## Scenario 1 — Road Warrior (Remote Client)

The canonical use case: you're on your laptop at a coffee shop and need to reach a service running in VLAN 20 (LAB) or VLAN 10 (HOME) without exposing those services to the public internet.

### Router Config (Server Side)

```routeros
# WireGuard interface
/interface wireguard add name=wg-remote listen-port=51820 private-key="<server-private-key>"

# IP on WG interface — this will be the gateway for remote peers
/ip address add address=10.200.200.1/24 interface=wg-remote comment="WG remote pool gateway"

# Peer definition: your phone/laptop
/interface wireguard peers add \
    interface=wg-remote \
    public-key="<client-public-key>" \
    allowed-address=10.200.200.2/32 \
    comment="Phone - Pixel 9"
```

**`allowed-address`** is critical. On the **server side**, it tells WireGuard which IPs this peer is allowed to use. You assign each remote device a unique `/32` address from the pool.

### Firewall — Allow WireGuard on WAN

```routeros
/ip firewall filter add \
    chain=input \
    protocol=udp \
    dst-port=51820 \
    in-interface-list=WAN \
    action=accept \
    comment="Allow WireGuard UDP"
```

The WAN interface list is set up in the R1 deployment — it includes `pppoe-out1`. If you have multiple WAN interfaces (failover), add them all.

### NAT for Remote Clients

Remote peers connect to the tunnel IP (10.200.200.1), but they need to reach the actual LAN subnets. Add a source NAT rule on the WireGuard interface:

```routeros
/ip firewall nat add \
    chain=srcnat \
    src-address=10.200.200.0/24 \
    dst-address=10.0.0.0/16 \
    action=srcnat \
    comment="NAT remote WG clients to LAN"
```

This translates the remote peer's WG IP (10.200.200.x) to the router's LAN IP when they talk to local subnets. Without this, return traffic wouldn't know how to route back.

### Allowing Access to Target Subnets

By default, the firewall drops inter-VLAN traffic (from the R1 config). Add an allow rule for the WireGuard pool to reach specific VLANs:

```routeros
/ip firewall filter add \
    chain=forward \
    src-address=10.200.200.0/24 \
    dst-address=10.0.10.0/24 \
    action=accept \
    comment="Allow WG clients → HOME (10)"

/ip firewall filter add \
    chain=forward \
    src-address=10.200.200.0/24 \
    dst-address=10.0.20.0/24 \
    action=accept \
    comment="Allow WG clients → LAB (20)"
```

For full LAN access (less secure, more convenient):

```routeros
/ip firewall filter add \
    chain=forward \
    src-address=10.200.200.0/24 \
    dst-address=10.0.0.0/16 \
    action=accept \
    comment="Allow WG clients → all VLANs"
```

### Client Config (Phone / Laptop)

On the client device (WireGuard app on iOS/Android, or `wg-quick` on Linux), create a peer config:

```ini
[Interface]
PrivateKey = <client-private-key>
Address = 10.200.200.2/32
DNS = 10.0.20.1

[Peer]
PublicKey = <server-public-key>
Endpoint = <public-ip>:51820
AllowedIPs = 10.0.0.0/16, 10.200.200.0/24
PersistentKeepalive = 25
```

**`AllowedIPs`** on the client tells the OS which destinations should be routed through the tunnel. Setting it to `10.0.0.0/16` routes all homelab traffic through WireGuard while internet traffic goes direct (split tunnel).

If you want all traffic through the VPN (full tunnel, everything goes through your home connection):

```ini
AllowedIPs = 0.0.0.0/0, ::/0
```

**`PersistentKeepalive = 25`** keeps the NAT binding alive on cellular networks. Without it, the router won't be able to initiate connections back to the client (the endpoint is behind CGNAT or carrier-grade NAT).

---

## Scenario 2 — Site-to-Site (Two MikroTiks)

This connects two MikroTik routers across different physical locations — say a primary and a secondary site, each with their own subnets.

### Topology

```
Site A (Primary)                 Site B (Secondary)
┌──────────────┐                ┌──────────────┐
│  MikroTik A  │    VPN Tunnel  │  MikroTik B  │
│  10.0.0.0/16 │ ◄───────────► │  172.16.0.0/24│
│  WAN: <IP-A> │  10.200.201.0 │  WAN: <IP-B>  │
└──────────────┘                └──────────────┘
```

### Site A Config (Primary)

```routeros
# WireGuard interface
/interface wireguard add name=wg-site listen-port=51821 private-key="<site-a-private>"

# Tunnel IP
/ip address add address=10.200.201.1/30 interface=wg-site

# Peer — Site B
/interface wireguard peers add \
    interface=wg-site \
    public-key="<site-b-public>" \
    allowed-address=10.200.201.2/32,172.16.0.0/24 \
    endpoint-address=<site-b-public-ip> \
    endpoint-port=51821 \
    persistent-keepalive=25s \
    comment="Site B (Secondary)"
```

The key difference from road warrior: **`allowed-address`** on the server side includes the remote site's LAN subnet (`172.16.0.0/24`). This tells WireGuard to route traffic destined for that subnet through this peer.

### Site B Config (Secondary)

```routeros
# WireGuard interface
/interface wireguard add name=wg-site listen-port=51821 private-key="<site-b-private>"

# Tunnel IP
/ip address add address=10.200.201.2/30 interface=wg-site

# Peer — Site A
/interface wireguard peers add \
    interface=wg-site \
    public-key="<site-a-public>" \
    allowed-address=10.200.201.1/32,10.0.0.0/16 \
    endpoint-address=<site-a-public-ip> \
    endpoint-port=51821 \
    persistent-keepalive=25s \
    comment="Site A (Primary)"
```

Notice the symmetry: Site A allows `172.16.0.0/24`, Site B allows `10.0.0.0/16`. Each side advertises its own LAN subnets in `allowed-address` on the opposite peer.

### Firewall — Site-to-Site

Add WAN allow rules for the site-to-site port (51821):

```routeros
/ip firewall filter add \
    chain=input \
    protocol=udp \
    dst-port=51821 \
    in-interface-list=WAN \
    action=accept \
    comment="Allow WG site-to-site"
```

And forward rules between the tunnel and the LAN subnets:

```routeros
# Site A: allow site B subnets into Site A LAN
/ip firewall filter add \
    chain=forward \
    src-address=172.16.0.0/24 \
    dst-address=10.0.0.0/16 \
    in-interface=wg-site \
    out-interface=bridge-trunk \
    action=accept \
    comment="Allow Site B → Site A LAN"

# Site A: allow responses back
/ip firewall filter add \
    chain=forward \
    src-address=10.0.0.0/16 \
    dst-address=172.16.0.0/24 \
    in-interface=bridge-trunk \
    out-interface=wg-site \
    action=accept \
    comment="Allow Site A LAN → Site B"
```

### Route Table

WireGuard handles routing internally via the peer's `allowed-address` — you don't need static routes for the tunnel itself. But verify the routing table:

```
/ip route print where dst-address~"172.16"
```

The route should show `gateway=wg-site` with no explicit next-hop IP. WireGuard resolves it from the peer config.

---

## Firewall Best Practices

### Default Drop Ingress

Never skip the default drop rules on the forward chain. WireGuard connections spawn new forward sessions that the firewall must evaluate:

```routeros
/ip firewall filter add chain=forward action=drop comment="Default drop forward"
```

Place it at the bottom of the forward chain. WireGuard accept rules go above it.

### FastTrack and WireGuard

FastTrack (connection tracking bypass) doesn't work on WireGuard interfaces — WireGuard encrypts every packet, so there's nothing to fast-track. Don't worry about this; WireGuard's kernel module is fast enough that FastTrack would save negligible CPU anyway on a homelab router.

If you have FastTrack rules, make sure they don't accidentally match WireGuard traffic:

```routeros
/ip firewall filter add chain=forward action=fasttrack-connection \
    connection-state=established,related \
    in-interface-list=LAN \
    out-interface-list=LAN
```

WireGuard traffic goes over WAN — it won't match this rule.

---

## Performance Tuning

### MTU

WireGuard's default MTU is 1420 (standard 1500 minus 60 bytes WG overhead, minus 20 IP header). If your ISP uses PPPoE (another 8 bytes overhead), the MTU needs to be lower:

```routeros
/interface wireguard set wg-remote mtu=1412
/interface wireguard set wg-site mtu=1412
```

1412 = 1500 - 60 (WG) - 20 (IP) - 8 (PPPoE). If you're behind CGNAT or use IPIP tunneling, go lower.

### Test MTU from the Router

```routeros
/ping 10.0.10.1 do-not-fragment do-not-fragment size=1400
```

Increase the size until it fails. The maximum successful size + 28 (IP+ICMP headers) is your path MTU. Set the WireGuard interface MTU to that value minus 80 (60 bytes WG + 20 bytes outer IP).

### Keepalive Timing

- **Road warrior (mobile clients):** 25 seconds — cellular NAT timeouts are often 30-60 seconds
- **Site-to-site (fixed endpoints):** 10-15 seconds — more aggressive to detect link flips faster, or disable keepalive if both endpoints have stable public IPs

If both sites have static public IPs, you can drop `persistent-keepalive` entirely for the site-to-site link. WireGuard will still reconnect when traffic flows.

### Multiple Streams

WireGuard is single-threaded on the router's CPU. RouterOS 7 uses a single worker for the WireGuard crypto. On an ARM64 MikroTik like the E62iUGS, this isn't a bottleneck for 100-200 Mbps. For gigabit WireGuard, you'd need a faster CPU (CCR series or x86 RouterOS).

Check CPU usage:

```
/system resource cpu print
```

If WireGuard pushes CPU past 70-80%, consider:
- IPsec with AES-NI hardware offload (if your router supports it)
- A dedicated WireGuard endpoint (e.g., a small LXC running `wg-quick`)
- Lowering the MTU (less overhead per packet, more packets per byte → more CPU per byte)

Real-world throughput on the E62iUGS with WireGuard is roughly 250-350 Mbps — adequate for remote access to a homelab, but not for site-to-site bulk transfer at line rate.

---

## DNS for Remote Clients

Distribute a meaningful DNS server to remote peers. In the road warrior client config:

```ini
DNS = 10.0.20.1
```

If your router runs the DNS server (or forwards to AdGuard/Pi-hole), remote clients get ad-blocking and local hostname resolution through the tunnel. Inside the homelab, `nas.lab` resolves to a local IP. Outside, it resolves through the tunnel.

For the site-to-site setup, configure DNS forwarding on each router:

```routeros
/ip dns set servers=1.1.1.1,8.8.8.8 allow-remote-requests=no
```

Local DNS on each site resolves its own subnets. Cross-site DNS uses static entries or a shared DNS server reachable through the tunnel.

---

## Split Tunnel vs Full Tunnel

### Split Tunnel (Recommended for Road Warrior)

Only homelab traffic goes through the VPN. Internet traffic goes direct:

```
AllowedIPs = 10.0.0.0/16, 10.200.200.0/24
```

**Pros:**
- No bandwidth bottleneck at home
- Streaming services work from the client's real IP
- Lower latency for internet browsing

**Cons:**
- Traffic to the internet doesn't benefit from the homelab's ad-blocking DNS
- The client's public IP is exposed to websites (privacy tradeoff)

### Full Tunnel

All traffic routes through the home connection:

```
AllowedIPs = 0.0.0.0/0, ::/0
```

**Pros:**
- Ad-blocking and DNS filtering applies to all traffic
- Client's public IP is the home's IP (useful for geo-unblocking)
- Network monitoring sees all traffic

**Cons:**
- Throughput is limited to the home upload speed (often 10-50 Mbps)
- Latency adds a round trip to the home link
- Home internet outage means no internet at all for the client

I run split tunnel for phones (low bandwidth, cellular NAT is unpredictable) and full tunnel for laptops when connected to untrusted WiFi (hotels, airports).

---

## Monitoring and Debugging

### Peer Status

Check if a peer is connected:

```
/interface wireguard peers print detail where interface=wg-remote
```

Look for `current-endpoint-address:` — if it's populated, the peer is connected. If not, check firewall rules and NAT.

### Connection Tracking

See active WireGuard sessions:

```
/ip firewall connection print where protocol=udp and dst-port=51820
```

A single `established,related` connection is expected per peer.

### Logging

Log WireGuard handshake failures:

```
/system logging add topics=wireguard,info action=memory
/log print where topics~"wireguard"
```

Common errors:

| Log Message | Likely Cause |
|-------------|-------------|
| `handshake failed` | Wrong public key on either side |
| `noise_connection_reset` | Endpoint IP/port changed (roaming) |
| `packet too big` | MTU mismatch — lower MTU on the interface |
| `allowed-address mismatch` | Peer sent from an IP not in its `allowed-address` list |

### Speed Test Through Tunnel

```routeros
/tool bandwidth-test \
    address=10.0.10.100 \
    user=admin \
    password=<pass> \
    direction=both \
    protocol=udp \
    duration=10s \
    local-address=10.200.200.1
```

Run this from a client on the WG subnet to a server inside the LAN. Compare to a direct (non-WG) speed test to measure overhead. Expect ~3-5% throughput loss from WireGuard encryption.

---

## Multiple Peers on One Interface

You can stack peers on the same WireGuard interface. Each road warrior device gets its own `/32`:

```routeros
/interface wireguard peers add interface=wg-remote public-key="<pub1>" \
    allowed-address=10.200.200.2/32 comment="Phone - Pixel 9"

/interface wireguard peers add interface=wg-remote public-key="<pub2>" \
    allowed-address=10.200.200.3/32 comment="Laptop - ThinkPad"

/interface wireguard peers add interface=wg-remote public-key="<pub3>" \
    allowed-address=10.200.200.4/32 comment="Tablet - iPad"
```

They all share the same listening port (51820) and tunnel interface. WireGuard demultiplexes by public key.

The site-to-site peer uses a separate interface (`wg-site` on port 51821) for clarity, but it could share `wg-remote` with different `allowed-address` ranges. Separate interfaces keep the config readable and let you set different MTUs or firewall rules per context.

---

## Security Notes

### Key Management

- **Keys are everything in WireGuard.** Lose the private key, you lose the connection. Keep a backup in a password manager or encrypted file.
- **Rotate keys periodically.** Add a new peer with the new key, remove the old one, update clients. No service interruption.

### Exposure

- Don't expose WireGuard on a non-standard port thinking it's security through obscurity — standard port (51820) is fine. The protocol is authenticated and encrypted.
- Set `listen-port` to a high port (51820-51900) if you want to avoid noisy scanning, but don't rely on it for security.

### Rate Limiting

RouterOS doesn't have native rate limiting on WireGuard handshakes. If you see repeated handshake failures from unknown peers (scanning), block them with a firewall filter:

```routeros
/ip firewall filter add \
    chain=input \
    protocol=udp \
    dst-port=51820 \
    src-address-list=wg-scanners \
    action=drop \
    comment="Drop known WG scanners"

/ip firewall filter add \
    chain=input \
    protocol=udp \
    dst-port=51820 \
    action=add-src-to-list \
    connection-state=new \
    src-address-list-timeout=1h \
    src-address-list=wg-scanners \
    comment="Rate limit WG handshakes (adjust as needed)"
```

In practice, this is overkill for a homelab. I've never seen a WireGuard handshake flood on residential connections.

---

## Full Config Summary

### Road Warrior (Server Side — R1)

```routeros
# Interface
/interface wireguard add name=wg-remote listen-port=51820 private-key="<priv>"

# IP pool gateway
/ip address add address=10.200.200.1/24 interface=wg-remote

# Peers (one per device)
/interface wireguard peers add interface=wg-remote public-key="<pub>" \
    allowed-address=10.200.200.2/32 comment="Phone"

# Firewall — WAN input
/ip firewall filter add chain=input protocol=udp dst-port=51820 \
    in-interface-list=WAN action=accept comment="Allow WG WAN"

# NAT for LAN access
/ip firewall nat add chain=srcnat src-address=10.200.200.0/24 \
    dst-address=10.0.0.0/16 action=srcnat

# Forward rules
/ip firewall filter add chain=forward src-address=10.200.200.0/24 \
    dst-address=10.0.10.0/24 action=accept comment="WG → HOME"
/ip firewall filter add chain=forward src-address=10.200.200.0/24 \
    dst-address=10.0.20.0/24 action=accept comment="WG → LAB"
/ip firewall filter add chain=forward src-address=10.200.200.0/24 \
    dst-address=10.0.50.0/24 action=accept comment="WG → CCTV"
```

### Site-to-Site (Both Sides — Partial)

**Site A:**

```routeros
/interface wireguard add name=wg-site listen-port=51821 private-key="<a-priv>"
/ip address add address=10.200.201.1/30 interface=wg-site
/interface wireguard peers add interface=wg-site public-key="<b-pub>" \
    allowed-address=10.200.201.2/32,172.16.0.0/24 \
    endpoint-address=<b-public-ip> endpoint-port=51821 persistent-keepalive=25s
```

**Site B:**

```routeros
/interface wireguard add name=wg-site listen-port=51821 private-key="<b-priv>"
/ip address add address=10.200.201.2/30 interface=wg-site
/interface wireguard peers add interface=wg-site public-key="<a-pub>" \
    allowed-address=10.200.201.1/32,10.0.0.0/16 \
    endpoint-address=<a-public-ip> endpoint-port=51821 persistent-keepalive=25s
```

---

## Why Not IPsec?

WireGuard replaces IPsec in most homelab scenarios because:

- **Configuration complexity** — IPsec on RouterOS requires multiple proposal, policy, and peer entries. WireGuard is one interface + one peer per device.
- **Handshake overhead** — IPsec IKEv2 uses multiple round trips for SA negotiation. WireGuard uses a single round trip (two messages) using the Noise protocol.
- **Roaming** — WireGuard handles IP changes seamlessly. IPsec needs MOBIKE support (not always present on RouterOS).
- **CPU usage** — WireGuard's kernel module is simpler than IPsec's stack, resulting in lower CPU on the same hardware.

IPsec still wins when:
- You need interoperability with non-WireGuard VPN gateways (AWS VPN, corporate VPNs)
- Client OS has built-in IPsec but not WireGuard (some older iOS/Android versions)
- You need NAT traversal below UDP (IPsec over TCP, not possible with WireGuard)

For homelab VPN: WireGuard. For corporate VPN requirements: IPsec. For legacy appliances: neither — use something that speaks WireGuard if possible.

---

## Recovery — When WireGuard Breaks

### "Peer disconnected" — no endpoint address shown

```routeros
/interface wireguard peers print detail
```

If `current-endpoint-address` is empty:
1. Client can't reach the router's WAN IP/port
2. Check firewall on both sides
3. Check ISP is not blocking UDP port 51820 (rare, but some mobile carriers do)
4. Try changing to port 443 or 53 (common allowed UDP ports)

### "Handshake failed" — peer keeps trying

1. Verify public keys match on both sides
2. Check that `allowed-address` on the server includes the client's tunnel IP
3. Restart the WireGuard interface: `/interface wireguard disable wg-remote; /interface wireguard enable wg-remote`
4. Check system logs: `/log print where topics~"wireguard"`

### "Can reach tunnel IP, can't reach LAN"

1. Forward firewall rules: is there a `dst-address=10.0.0.0/16` allow rule?
2. NAT: is `srcnat` active for the WG subnet?
3. Duplicate route: `/ip route print` — ensure there's no conflicting route
4. From the router: `/ping 10.0.10.1 src-address=10.200.200.1` — if this fails, it's a routing/NAT issue, not WireGuard

### MTU Issues

Symptoms: large transfers hang, small transfers work, SSH connects but scp/ping with large size times out.

Fix:
```routeros
/interface wireguard set wg-remote mtu=1350
```

Then test incrementally:
```routeros
/ping 10.0.10.1 size=1300 do-not-fragment
```

---

## Summary

| Decision | Recommendation |
|----------|---------------|
| VPN protocol | WireGuard — simpler, faster, less CPU |
| Road warrior subnet | 10.200.200.0/24 |
| Site-to-site subnet | 10.200.201.0/30 |
| Split vs full tunnel | Split for phones, full for untrusted WiFi |
| Listen port | 51820 (road warrior), 51821 (site-to-site) |
| MTU with PPPoE | 1412 (or lower if behind CGNAT) |
| Keepalive | 25s (mobile), 10-15s (site-to-site) |

WireGuard on RouterOS 7 is the fastest path to a reliable homelab VPN. The config is minimal, the security model is sound, and you can have road warrior access working in under 10 commands from a clean router.
