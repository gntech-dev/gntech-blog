---
title: "Building R1 — A MikroTik Router for VLAN-Segmented Homelab"
description: "Designing and deploying a MikroTik E62iUGS-2axD5axT as the edge router for a segmented home network with VLANs, WireGuard VPN, Cloudflare Tunnel, and strict firewall."
date: 2026-05-06
tags:
  - mikrotik
  - networking
  - vlan
  - routeros
  - firewall
categories:
  - homelab
  - networking
---

Every homelab needs a solid network foundation. This is the story of R1 — my MikroTik-based edge router that segments the entire home network into clean VLANs with strict inter-VLAN firewalling, WireGuard VPN, and a Cloudflare Tunnel running directly on the router.

---

## Hardware

```
Model:  MikroTik E62iUGS-2axD5axT
OS:     RouterOS 7.22.1
WAN:    Claro GPON FTTH (PPPoE on VLAN 100)
Location: Santo Domingo, DR
```

The E62iUGS is an interesting beast — it combines a CCR2004-class CPU with built-in WiFi (2.4/5 GHz) and an SFP+ cage. It sits at the edge of the network handling routing, firewalling, DHCP, DNS, containers, and wireless all in one box.

### Port Layout

| Port | Role | VLAN | Notes |
|------|------|------|-------|
| SFP1 | WAN | 100 (PPPoE) | GPON ONT, native vlan 1 for ONT access |
| Ether1 | CCTV | 50 (untagged) | Camera network |
| Ether2 | MGMT | 99 (untagged) | Management |
| Ether3 | MGMT | 99 (untagged) | Secondary MGMT |
| Ether4 | HOME | 10 (untagged) | Main home LAN |
| Ether5 | Trunk | Tagged (10,20,40,50,99,300) | Inter-switch |

---

## VLAN Design

```
┌─────────────────────────────────────────────────────────────┐
│                        R1 MikroTik                          │
│                                                             │
│  WAN (VLAN 100) ──┐                                         │
│   PPPoE: Claro    │                                         │
├───────────────────┼─────────────────────────────────────────┤
│  HOME (10)        │  10.0.10.0/24     Wi-Fi + wired         │
│  LAB (20)         │  10.0.20.0/24     Servers, homelab      │
│  IoT (40)         │  10.0.40.0/24     Rate-limited 1Mbps    │
│  CCTV (50)        │  10.0.50.0/24     Cameras               │
│  MGMT (99)        │  10.0.99.0/24     Router, switch, APs   │
│  VoIP (300)       │  Trunked → Proxmox                      │
└───────────────────┴─────────────────────────────────────────┘
```

The design philosophy: **each VLAN is isolated by default**, exceptions are explicit.

| VLAN | Subnet | DHCP | Notes |
|------|--------|------|-------|
| 10 HOME | 10.0.10.0/24 | Router (.100-.250) | Family devices, WiFi |
| 20 LAB | 10.0.20.0/24 | External (disabled) | Servers, containers |
| 40 IoT | 10.0.40.0/24 | Router (.100-.250) | Smart plugs, sensors, rate-limited 1Mbps |
| 50 CCTV | 10.0.50.0/24 | Router (.100-.250) | Cameras only |
| 99 MGMT | 10.0.99.0/24 | Router (.100-.250) | Router SSH/WinBox, management |
| 300 VoIP | — | Passed via trunk | Claro IMS phone |

---

## Firewall Policy

The forwarding rules tell the full story. From R1's `/ip firewall filter`:

```
 1  accept  established/related         # Return traffic
 2  drop    invalid                     # No invalid packets
 3  accept  in=LAN out=WAN             # Internet access (per-VLAN)
 4  accept  in=MGMT out=any            # MGMT → everything
 5  accept  dst=10.0.20.30             # All → LAB servers
 6  accept  src=10.0.20.15/30 dst=50   # Frigate → CCTV
 7  accept  in=back-to-home-vpn        # VPN → all
 8  accept  dport=53 out=WAN           # DNS outgoing
 9  accept  src=LAN dst=172.31.255.0/24# LAN → router containers
10  accept  MGMT→Asterisk SIP/RTP      # VoIP flows
11  reject  dport=853 from LAN         # Block DNS-over-TLS
12  drop    *                           # Default drop
```

Key behaviors:
- **Inter-VLAN is dropped by default** — devices on HOME cannot talk to LAB, IoT, or CCTV
- **MGMT can reach everything** — management LAN has full access for maintenance
- **Servers are reachable from anywhere** — 10.0.20.30 (SRV1) is accessible from all VLANs so services like Frigate, Plex, etc. work
- **CCTV is locked down** — only Frigate hosts (10.0.20.15/30) can initiate connections to cameras
- **DNS-over-TLS is blocked** — prevents devices from bypassing the router's DNS filtering

---

## IPv6

DHCPv6-PD runs on the PPPoE interface, requesting a prefix from Claro:

```
/ipv6 dhcp-client add interface=pppoe-out1 pool-name=ipv6-pd
/ipv6 address add from-pool=ipv6-pd interface=vlan10-home
ipv6 address add from-pool=ipv6-pd interface=vlan20-lab
...
```

Each VLAN gets a `/64` delegation. ND is enabled on all VLAN interfaces.

---

## WiFi

Two radios with multiple virtual APs:

| SSID | VLAN | Security | Band | Hidden |
|------|------|----------|------|--------|
| CAROLAM.- | 10 HOME | WPA2-PSK | 2.4 + 5 GHz | No |
| IoT | 40 IoT | WPA2-PSK | 2.4 GHz | No |
| GS | 50 CCTV | WPA2-PSK | 2.4 GHz | Yes |
| GNTECH-MGMT | 99 MGMT | WPA2-PSK | 5 GHz | Yes |

The home SSID broadcasts on both bands for compatibility. IoT is 2.4 GHz only (most smart devices don't do 5 GHz). CCTV and MGMT SSIDs are hidden since they're for administration only.

---

## WireGuard VPN

```bash
/interface wireguard add name=back-to-home-vpn mtu=1420 listen-port=46209
/interface wireguard peers add interface=back-to-home-vpn \
    public-key="<remote-key>" allowed-address=0.0.0.0/0
```

The VPN uses MikroTik Cloud DDNS so the router is reachable even if Claro changes the WAN IP. Allowed address `0.0.0.0/0` means VPN clients get full LAN access — useful for remote management.

---

## Containers on Router

One of my favorite features — RouterOS containers let me run **Cloudflare Tunnel** directly on the router, no separate Raspberry Pi or VM needed:

```
docker-cloudflared: 172.31.255.2
veth bridge:         172.31.255.0/24
Image:               ghcr.io/shmick/docker-cloudflared
```

The tunnel runs on the router container bridge, with firewall rules allowing it to reach the MGMT VLAN for web interfaces and the LAB VLAN for proxied services. This means Cloudflare sits in front of:
- Frigate Web UI
- Internal dashboards
- Anything else behind Cloudflare Access

No exposed ports, no VPS, no extra hardware. Just the router.

---

## Rate Limiting

IoT devices get rate-limited because they don't need bandwidth and I don't trust them:

```
/queue simple add name=limit-iot-1m target=vlan40-iot max-limit=1M/1M
```

1 Mbps is plenty for a few smart plugs and sensors. Prevents a compromised IoT device from becoming a botnet node eating the upstream link.

---

## ONT Access

The GPON ONT lives on its own native VLAN 1 (192.168.1.0/24). From MGMT VLAN, I can reach it through SNAT:

```
/ip firewall nat add chain=srcnat src-addr=10.0.99.0/24 \
    dst-addr=192.168.1.0/24 action=masquerade
```

Useful for rebooting the ONT or checking optical levels without crawling behind the rack.

---

## Silent Operation

All LEDs are disabled:

```bash
/interface ethernet set [find] leds=off
```

The router lives in the living area. A rack of blinking indicators at 3 AM is not the vibe.

---

## Deployment Lessons

**Things that worked:**
- Single box doing routing, WiFi, firewall, VPN, and containers eliminates complexity
- Container feature on ROS 7 is genuinely useful for lightweight services
- Bridge VLAN filtering with `vlan-filtering=yes` is clean once you wrap your head around it
- Simple queues for rate-limiting IoT is zero-maintenance

**Things to improve:**
- The built-in WiFi is adequate but a dedicated AP (Unifi/Omada) would perform better, especially at range
- 2 GB RAM on the router is tight with containers — 4 GB would be more comfortable
- Container storage on a USB drive works but isn't ideal for logs
- No PoE — external switches/peripherals need injectors

---

## Full Config

The canonical RouterOS export lives in the internal docs repo. Key config blocks:

```bash
# VLAN interfaces
/interface vlan add name=vlan10-home  vlan-id=10  interface=bridge-trunk
/interface vlan add name=vlan20-lab   vlan-id=20  interface=bridge-trunk
/interface vlan add name=vlan40-iot   vlan-id=40  interface=bridge-trunk
/interface vlan add name=vlan50-cctv  vlan-id=50  interface=bridge-trunk
/interface vlan add name=vlan99-mgmt  vlan-id=99  interface=bridge-trunk

# Bridge
/interface bridge add name=bridge-trunk vlan-filtering=yes

# Bridge port VLAN assignments
/interface bridge vlan add bridge=bridge-trunk vlan-ids=10 tagged=ether5
/interface bridge vlan add bridge=bridge-trunk vlan-ids=10 untagged=ether4

# PPPoE
/interface pppoe-client add name=pppoe-out1 \
    interface=vlan100-wan user=claro@internet password=<pass> add-default-route=yes

# DHCP pools
/ip pool add name=pool-home ranges=10.0.10.100-10.0.10.250
/ip pool add name=pool-iot  ranges=10.0.40.100-10.0.40.250
/ip pool add name=pool-cctv ranges=10.0.50.100-10.0.50.250
/ip pool add name=pool-mgmt ranges=10.0.99.100-10.0.99.250
```

---

For the complete RouterOS export with all interfaces, NAT, firewall, DHCP, and container config, check the [internal docs](https://gntech-docs.pages.dev).
