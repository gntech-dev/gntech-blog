---
title: "Building R1 — A MikroTik Router for VLAN-Segmented Homelab"
description: "Step-by-step guide to configuring a MikroTik E62iUGS-2axD5axT as an edge router with VLAN segmentation, strict firewall, WireGuard VPN, containerized Cloudflare Tunnel, and WiFi."
date: 2026-05-07
tags:
  - mikrotik
  - routeros
  - vlan
  - networking
  - firewall
categories:
  - homelab
  - networking
---

Every homelab needs a solid network foundation. This guide walks through the full configuration of R1 — a MikroTik edge router with segmented VLANs, inter-VLAN firewalling, WireGuard VPN, and a Cloudflare Tunnel running directly on the router.

The config below is based on RouterOS 7.22.1. Commands are split by section so you can follow along step-by-step. Replace anything in `<>` with your own values.

---

## Hardware

```
Model:  MikroTik E62iUGS-2axD5axT
OS:     RouterOS 7.22.1
WAN:    GPON FTTH (PPPoE on VLAN 100)
```

### Port Layout

| Port | Role | Access VLAN | Notes |
|------|------|-------------|-------|
| SFP1 | WAN | — | GPON ONT, native vlan 1 for ONT access |
| Ether1 | CCTV | 50 | Untagged, camera network |
| Ether2 | MGMT | 99 | Untagged, management |
| Ether3 | MGMT | 99 | Untagged, secondary management |
| Ether4 | HOME | 10 | Untagged, main home LAN |
| Ether5 | Trunk | Tagged | Inter-switch link carrying all VLANs |

---

## Step 1 — Bridge Setup

Create the main bridge with VLAN filtering enabled, and a separate bridge for container veth interfaces:

```
/interface bridge add name=bridge-trunk vlan-filtering=yes
/interface bridge add name=containers
```

## Step 2 — VLAN Interfaces

Create a VLAN interface on the bridge for each segment:

```
/interface vlan add interface=bridge-trunk name=vlan-home  vlan-id=10
/interface vlan add interface=bridge-trunk name=vlan-lab   vlan-id=20
/interface vlan add interface=bridge-trunk name=vlan-iot   vlan-id=40
/interface vlan add interface=bridge-trunk name=vlan-cctv  vlan-id=50
/interface vlan add interface=bridge-trunk name=vlan-mgmt  vlan-id=99
```

The WAN VLAN uses the SFP1 interface directly, not the bridge:

```
/interface vlan add interface=sfp1 name=vlan100-wan vlan-id=100
```

## Step 3 — Bridge Port Assignment

Configure each physical port's PVID (untagged VLAN) and tagging mode:

```
/interface bridge port add bridge=bridge-trunk interface=ether2 pvid=99 \
    frame-types=admit-only-untagged-and-priority-tagged
/interface bridge port add bridge=bridge-trunk interface=ether3 pvid=99 \
    frame-types=admit-only-untagged-and-priority-tagged
/interface bridge port add bridge=bridge-trunk interface=ether4 pvid=10 \
    frame-types=admit-only-untagged-and-priority-tagged
/interface bridge port add bridge=bridge-trunk interface=ether1 pvid=50 \
    frame-types=admit-only-untagged-and-priority-tagged
/interface bridge port add bridge=bridge-trunk interface=ether5 \
    frame-types=admit-only-vlan-tagged
/interface bridge port add bridge=bridge-trunk interface=sfp1
```

`ether5` is the trunk port — it only accepts tagged frames. Everything else accepts untagged (their PVID VLAN) and tagged.

## Step 4 — Bridge VLAN Table

Tell the bridge which VLANs are allowed on which ports, and whether they're tagged or untagged:

```
/interface bridge vlan add bridge=bridge-trunk vlan-ids=10  tagged=bridge-trunk,ether5 untagged=ether4
/interface bridge vlan add bridge=bridge-trunk vlan-ids=20  tagged=bridge-trunk,ether5,ether3
/interface bridge vlan add bridge=bridge-trunk vlan-ids=40  tagged=bridge-trunk,ether5
/interface bridge vlan add bridge=bridge-trunk vlan-ids=50  tagged=bridge-trunk,ether5
/interface bridge vlan add bridge=bridge-trunk vlan-ids=99  tagged=bridge-trunk,ether5 untagged=ether2
/interface bridge vlan add bridge=bridge-trunk vlan-ids=300 tagged=bridge-trunk,sfp1,ether5
/interface bridge vlan add bridge=bridge-trunk vlan-ids=1   untagged=sfp1,bridge-trunk
```

**What's happening here:**
- `bridge-trunk` is listed as tagged on all VLANs — this gives the bridge itself (and its VLAN interfaces) access to those VLANs
- `ether4` gets VLAN 10 untagged — devices plugged into that port are on HOME
- `ether2` gets VLAN 99 untagged — plugged into that port → MGMT
- `ether3` gets VLAN 20 tagged in addition to its PVID — it's a trunk-like MGMT port that also carries LAB
- `ether5` gets everything tagged — trunk to downstream switch
- VLAN 300 is ISP VoIP, passed transparently to Proxmox via the trunk
- VLAN 1 is the native/untagged VLAN on SFP1 — ONT access

## Step 5 — WAN (PPPoE)

PPPoE on the WAN VLAN interface. Replace `<username>` with your ISP credentials:

```
/interface pppoe-client add name=pppoe-out1 interface=vlan100-wan \
    user=<pppoe-username> password=<pppoe-password> add-default-route=yes disabled=no
```

## Step 6 — IP Addresses

Assign gateway addresses to each VLAN interface:

```
/ip address add address=10.0.99.1/24  interface=vlan-mgmt  comment="MGMT gateway"
/ip address add address=10.0.10.1/24  interface=vlan-home  comment="HOME gateway"
/ip address add address=10.0.20.1/24  interface=vlan-lab   comment="LAB gateway"
/ip address add address=10.0.40.1/24  interface=vlan-iot   comment="IoT gateway"
/ip address add address=10.0.50.1/24  interface=vlan-cctv  comment="CCTV gateway"
/ip address add address=172.31.255.1/24 interface=containers
/ip address add address=192.168.1.2/24 interface=sfp1       comment="ONT access"
```

## Step 7 — Interface Lists

Interface lists simplify firewall rules. Group VLANs and WAN:

```
/interface list add name=WAN
/interface list add name=LAN

/interface list member add interface=vlan-home  list=LAN
/interface list member add interface=vlan-lab   list=LAN
/interface list member add interface=vlan-iot   list=LAN
/interface list member add interface=vlan-cctv  list=LAN
/interface list member add interface=vlan-mgmt  list=LAN
/interface list member add interface=pppoe-out1 list=WAN
```

Now firewall rules can target `in-interface-list=LAN` or `out-interface-list=WAN` instead of listing individual interfaces.

## Step 8 — DHCP

### Pools

```
/ip pool add name=pool-home ranges=10.0.10.100-10.0.10.250
/ip pool add name=pool-iot  ranges=10.0.40.100-10.0.40.250
/ip pool add name=pool-cctv ranges=10.0.50.100-10.0.50.250
/ip pool add name=pool-mgmt ranges=10.0.99.100-10.0.99.250
/ip pool add name=pool-lab  ranges=10.0.20.100-10.0.20.250
```

### Networks

```
/ip dhcp-server network add address=10.0.10.0/24 gateway=10.0.10.1 dns-server=10.0.10.1
/ip dhcp-server network add address=10.0.20.0/24 gateway=10.0.20.1 dns-server=10.0.20.1
/ip dhcp-server network add address=10.0.40.0/24 gateway=10.0.40.1 dns-server=10.0.40.1
/ip dhcp-server network add address=10.0.50.0/24 gateway=10.0.50.1 dns-server=10.0.50.1
/ip dhcp-server network add address=10.0.99.0/24 gateway=10.0.99.1 dns-server=10.0.99.1
```

### Servers

```
/ip dhcp-server add name=dhcp-home interface=vlan-home address-pool=pool-home
/ip dhcp-server add name=dhcp-iot  interface=vlan-iot  address-pool=pool-iot
/ip dhcp-server add name=dhcp-cctv interface=vlan-cctv address-pool=pool-cctv
/ip dhcp-server add name=dhcp-mgmt interface=vlan-mgmt address-pool=pool-mgmt
/ip dhcp-server add name=dhcp-lab  interface=vlan-lab  address-pool=pool-lab disabled=yes
```

LAB DHCP is disabled because servers use static IPs.

## Step 9 — DNS

```
/ip dns set allow-remote-requests=yes servers=1.1.1.1,8.8.8.8 \
    cache-size=8192KiB max-udp-packet-size=1232
```

## Step 10 — Firewall

### Address List

Define hosts that router containers are allowed to reach on the MGMT VLAN:

```
/ip firewall address-list add list=cloudflared-mgmt-allowed \
    address=10.0.99.2-10.0.99.10
```

### Input Chain (traffic to the router itself)

```
# Allow established/related
/ip firewall filter add chain=input connection-state=established,related action=accept

# Drop invalid
/ip firewall filter add chain=input connection-state=invalid action=drop

# ICMP
/ip firewall filter add chain=input protocol=icmp action=accept

# DHCP
/ip firewall filter add chain=input protocol=udp dst-port=67 in-interface-list=LAN action=accept

# DNS
/ip firewall filter add chain=input protocol=udp dst-port=53 in-interface-list=LAN action=accept
/ip firewall filter add chain=input protocol=tcp dst-port=53 in-interface-list=LAN action=accept

# MGMT access to router
/ip firewall filter add chain=input in-interface=vlan-mgmt action=accept

# Drop from WAN
/ip firewall filter add chain=input in-interface-list=WAN action=drop

# Block IoT → router
/ip firewall filter add chain=input in-interface=vlan-iot action=drop

# Default drop
/ip firewall filter add chain=input action=drop
```

IoT cannot reach the router at all. MGMT is the only VLAN that can manage it.

### Forward Chain (traffic between VLANs)

```
# Established/related
/ip firewall filter add chain=forward connection-state=established,related action=accept

# Drop invalid
/ip firewall filter add chain=forward connection-state=invalid action=drop

# Per-VLAN Internet access
/ip firewall filter add chain=forward in-interface=vlan-home out-interface-list=WAN action=accept
/ip firewall filter add chain=forward in-interface=vlan-lab  out-interface-list=WAN action=accept
/ip firewall filter add chain=forward in-interface=vlan-iot  out-interface-list=WAN action=accept
/ip firewall filter add chain=forward in-interface=vlan-cctv out-interface-list=WAN action=accept
/ip firewall filter add chain=forward in-interface=vlan-mgmt out-interface-list=WAN action=accept

# MGMT → all VLANs
/ip firewall filter add chain=forward in-interface=vlan-mgmt out-interface-list=LAN action=accept

# All VLANs → servers (10.0.20.10 = SRV2, 10.0.20.30 = SRV1)
/ip firewall filter add chain=forward dst-address=10.0.20.10 action=accept
/ip firewall filter add chain=forward dst-address=10.0.20.30 action=accept

# Frigate hosts → CCTV VLAN (camera access)
/ip firewall filter add chain=forward dst-address=10.0.50.0/24 src-address=10.0.20.15 action=accept
/ip firewall filter add chain=forward dst-address=10.0.50.0/24 src-address=10.0.20.30 action=accept

# VPN → Internet + LAN
/ip firewall filter add chain=forward in-interface=back-to-home-vpn out-interface-list=WAN action=accept
/ip firewall filter add chain=forward in-interface=back-to-home-vpn out-interface-list=LAN action=accept

# DNS outbound
/ip firewall filter add chain=forward protocol=udp dst-port=53 out-interface-list=WAN action=accept
/ip firewall filter add chain=forward protocol=tcp dst-port=53 out-interface-list=WAN action=accept

# LAN → router containers
/ip firewall filter add chain=forward in-interface-list=LAN dst-address=172.31.255.0/24 action=accept

# Container → LAB
/ip firewall filter add chain=forward in-interface=containers out-interface=vlan-lab action=accept

# Container → selected MGMT hosts (Cloudflare Tunnel proxying web UIs)
/ip firewall filter add chain=forward src-address=172.31.255.0/24 \
    dst-address-list=cloudflared-mgmt-allowed action=accept

# Asterisk VoIP flows
/ip firewall filter add chain=forward protocol=udp dst-address=10.0.20.25 dst-port=5160 in-interface=vlan-mgmt action=accept
/ip firewall filter add chain=forward protocol=udp dst-address=10.0.20.25 dst-port=10000-20000 in-interface=vlan-mgmt action=accept
/ip firewall filter add chain=forward protocol=udp dst-address=10.0.20.25 dst-port=5160 in-interface=vlan-home action=accept
/ip firewall filter add chain=forward protocol=udp dst-address=10.0.20.25 dst-port=10000-20000 in-interface=vlan-home action=accept
# Return traffic
/ip firewall filter add chain=forward protocol=udp src-address=10.0.20.25 src-port=5160 out-interface=vlan-mgmt action=accept
/ip firewall filter add chain=forward protocol=udp src-address=10.0.20.25 src-port=10000-20000 out-interface=vlan-mgmt action=accept
/ip firewall filter add chain=forward protocol=udp src-address=10.0.20.25 src-port=5160 out-interface=vlan-home action=accept
/ip firewall filter add chain=forward protocol=udp src-address=10.0.20.25 src-port=10000-20000 out-interface=vlan-home action=accept

# ONT access from MGMT
/ip firewall filter add chain=forward src-address=10.0.99.0/24 dst-address=192.168.1.0/24 action=accept

# Block DNS-over-TLS from LAN
/ip firewall filter add chain=forward protocol=tcp dst-port=853 in-interface-list=LAN action=reject

# Default drop inter-VLAN
/ip firewall filter add chain=forward action=drop
```

### NAT (Masquerade)

```
# WAN masquerade
/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade

# ONT access masquerade (MGMT → ONT private subnet)
/ip firewall nat add chain=srcnat src-address=10.0.99.0/24 dst-address=192.168.1.0/24 action=masquerade
```

## Step 11 — WireGuard VPN

```
/interface wireguard add name=back-to-home-vpn mtu=1420 listen-port=46209

/interface wireguard peers add interface=back-to-home-vpn \
    public-key="<peer-public-key>" allowed-address=0.0.0.0/0
```

Enable MikroTik Cloud DDNS so the router is reachable remotely:

```
/ip cloud set ddns-enabled=yes ddns-update-interval=10m back-to-home-vpn=enabled
```

## Step 12 — WiFi

### 2.4 GHz Radio (wifi1)

```
/interface wifi set [find default-name=wifi1] \
    channel.frequency=2412 .width=20mhz \
    configuration.country="United States" .mode=ap .tx-power=17 disabled=no
```

### 5 GHz Radio (wifi2)

```
/interface wifi set [find default-name=wifi2] \
    channel.frequency=5180 .skip-dfs-channels=all .width=20/40mhz \
    configuration.country="United States" .mode=ap .ssid=R1-MASTER-5G .tx-power=18 disabled=no
```

### Datapaths (VLAN binding per SSID)

```
/interface wifi datapath add bridge=bridge-trunk name=dp-home vlan-id=10
/interface wifi datapath add bridge=bridge-trunk name=dp-iot  vlan-id=40
/interface wifi datapath add bridge=bridge-trunk name=dp-cctv vlan-id=50
/interface wifi datapath add bridge=bridge-trunk name=dp-mgmt vlan-id=99
```

### Security Profiles

```
/interface wifi security add authentication-types=wpa2-psk name=sec-home
/interface wifi security add authentication-types=wpa2-psk name=sec-iot
/interface wifi security add authentication-types=wpa2-psk name=sec-cctv
/interface wifi security add authentication-types=wpa2-psk name=sec-mgmt
```

### SSID Configurations

```
/interface wifi configuration add datapath=dp-home security=sec-home ssid="<home-ssid>" name=cfg-home
/interface wifi configuration add datapath=dp-iot  security=sec-iot  ssid=IoT name=cfg-iot
/interface wifi configuration add datapath=dp-cctv security=sec-cctv ssid=GS name=cfg-cctv hide-ssid=yes
/interface wifi configuration add datapath=dp-mgmt security=sec-mgmt ssid="<mgmt-ssid>" name=cfg-mgmt hide-ssid=yes
```

### Virtual APs (2.4 GHz)

```
/interface wifi add master-interface=wifi1 configuration=cfg-home name=wifi1-home
/interface wifi add master-interface=wifi1 configuration=cfg-iot  name=wifi1-iot
/interface wifi add master-interface=wifi1 configuration=cfg-cctv name=wifi1-cctv
/interface wifi add master-interface=wifi1 configuration=cfg-mgmt name=wifi1-mgmt
```

### Virtual APs (5 GHz)

```
/interface wifi add master-interface=wifi2 configuration=cfg-home-5g name=wifi2-home
/interface wifi add master-interface=wifi2 configuration=cfg-mgmt    name=wifi2-mgmt
```

## Step 13 — Container (Cloudflare Tunnel)

Create veth interfaces for the container:

```
/interface veth add name=veth1 address=172.31.255.2/24 gateway=172.31.255.1
/interface veth add name=veth2 address=172.31.255.3/24 gateway=172.31.255.1

/interface bridge port add bridge=containers interface=veth1
/interface bridge port add bridge=containers interface=veth2
```

Add the container (replace `<token>` with your Cloudflare Tunnel token):

```
/container add name=docker-cloudflared interface=veth1 \
    remote-image=ghcr.io/shmick/docker-cloudflared \
    cmd="tunnel --no-autoupdate run --token <cloudflare-tunnel-token>" \
    dns=1.1.1.1,1.0.0.1 hostname=CF \
    root-dir=/usb1/container/cloudflared start-on-boot=yes

/container config set registry-url=https://registry-1.docker.io tmpdir=/usb1/tmp
```

## Step 14 — Rate Limiting (IoT)

IoT devices get capped at 1 Mbps to prevent a compromised device from consuming bandwidth:

```
/queue simple add name=limit-iot-1m target=10.0.40.0/24 max-limit=1M/1M
```

## Step 15 — Services Security

Lock down management services to MGMT VLAN only:

```
/ip service set ftp      disabled=yes
/ip service set telnet   disabled=yes
/ip service set api      disabled=yes
/ip service set api-ssl  disabled=yes
/ip service set ssh      address=10.0.99.0/24
/ip service set winbox   address=10.0.99.0/24
/ip service set www      address=10.0.99.0/24,172.31.255.2/32 port=8080
/ip service set www-ssl  address=10.0.99.0/24,172.31.255.2/32 disabled=no
```

WebFig on port 8080 (non-SSL) and HTTPS are also accessible from the Cloudflare Tunnel container IP, so proxied services work through Cloudflare Access.

## Step 16 — LEDs Off

All LEDs disabled for silent/dark operation:

```
/system leds set 0 disabled=yes
/system leds set 1 disabled=yes
/system leds settings set all-leds-off=immediate
```

## Step 17 — IPv6

```
/ipv6 dhcp-client add interface=pppoe-out1 pool-name=ipv6-pd request=prefix add-default-route=yes

/ipv6 address add from-pool=ipv6-pd interface=vlan-home
/ipv6 address add from-pool=ipv6-pd interface=vlan-lab
/ipv6 address add from-pool=ipv6-pd interface=vlan-iot
/ipv6 address add from-pool=ipv6-pd interface=vlan-cctv
/ipv6 address add from-pool=ipv6-pd interface=vlan-mgmt

/ipv6 nd add interface=vlan-home
/ipv6 nd add interface=vlan-lab
/ipv6 nd add interface=vlan-iot
/ipv6 nd add interface=vlan-cctv
/ipv6 nd add interface=vlan-mgmt
```

IPv6 firewall mirrors the IPv4 logic (established/related → accept, per-VLAN out → accept, others → drop).

---

## Deployment Lessons

**What worked:**
- Single box doing routing, WiFi, firewall, VPN, and containers keeps the stack simple
- Bridge VLAN filtering with `vlan-filtering=yes` is clean once you understand it — the bridge VLAN table is the key
- Interface lists make firewall rules readable and maintainable
- Simple queues for rate-limiting IoT is zero-maintenance

**What to watch for:**
- 2 GB RAM on the router is tight with containers running — 4 GB is more comfortable
- The built-in WiFi is adequate but a dedicated AP (Unifi/Omada) would perform better at range
- Container storage on USB works but isn't ideal for persistent logs

**Key firewall design:**
- Inter-VLAN is **dropped by default**
- MGMT can reach everything (management convenience)
- Servers are reachable from all VLANs (services need to work across segments)
- CCTV is locked down — only specific Frigate hosts can initiate connections to cameras
- DNS-over-TLS is blocked to prevent devices from bypassing the router's DNS

---

## Full Export

Below is the complete sanitized RouterOS export (2026-05-07). This is the reference config — everything above is the broken-down version.

```
/interface bridge
add name=bridge-trunk vlan-filtering=yes
add name=containers

/interface vlan
add interface=bridge-trunk name=vlan-cctv vlan-id=50
add interface=bridge-trunk name=vlan-home vlan-id=10
add interface=bridge-trunk name=vlan-iot vlan-id=40
add interface=bridge-trunk name=vlan-lab vlan-id=20
add interface=bridge-trunk name=vlan-mgmt vlan-id=99
add interface=sfp1 name=vlan100-wan vlan-id=100

/interface pppoe-client
add name=pppoe-out1 interface=vlan100-wan user=<pppoe-user> \
    add-default-route=yes disabled=no

/interface wireguard
add name=back-to-home-vpn listen-port=46209 mtu=1420

/interface list
add name=WAN
add name=LAN

/ip pool
add name=pool-home ranges=10.0.10.100-10.0.10.250
add name=pool-lab ranges=10.0.20.100-10.0.20.250
add name=pool-iot ranges=10.0.40.100-10.0.40.250
add name=pool-cctv ranges=10.0.50.100-10.0.50.250
add name=pool-mgmt ranges=10.0.99.100-10.0.99.250

/ip dhcp-server
add address-pool=pool-home interface=vlan-home name=dhcp-home
add address-pool=pool-iot interface=vlan-iot name=dhcp-iot
add address-pool=pool-cctv interface=vlan-cctv name=dhcp-cctv
add address-pool=pool-mgmt interface=vlan-mgmt name=dhcp-mgmt
add address-pool=pool-lab interface=vlan-lab name=dhcp-lab disabled=yes

/ip address
add address=10.0.99.1/24 interface=vlan-mgmt
add address=10.0.10.1/24 interface=vlan-home
add address=10.0.20.1/24 interface=vlan-lab
add address=10.0.40.1/24 interface=vlan-iot
add address=10.0.50.1/24 interface=vlan-cctv
add address=172.31.255.1/24 interface=containers
add address=192.168.1.2/24 interface=sfp1

/ip firewall filter
add chain=input connection-state=established,related action=accept
add chain=input connection-state=invalid action=drop
add chain=input protocol=icmp action=accept
add chain=input protocol=udp dst-port=67 in-interface-list=LAN action=accept
add chain=input protocol=udp dst-port=53 in-interface-list=LAN action=accept
add chain=input protocol=tcp dst-port=53 in-interface-list=LAN action=accept
add chain=input in-interface=vlan-mgmt action=accept
add chain=input in-interface-list=WAN action=drop
add chain=input in-interface=vlan-iot action=drop
add chain=input action=drop

add chain=forward connection-state=established,related action=accept
add chain=forward connection-state=invalid action=drop
add chain=forward in-interface=vlan-home out-interface-list=WAN action=accept
add chain=forward in-interface=vlan-lab out-interface-list=WAN action=accept
add chain=forward in-interface=vlan-iot out-interface-list=WAN action=accept
add chain=forward in-interface=vlan-cctv out-interface-list=WAN action=accept
add chain=forward in-interface=vlan-mgmt out-interface-list=WAN action=accept
add chain=forward in-interface=vlan-mgmt out-interface-list=LAN action=accept
add chain=forward dst-address=10.0.20.10 action=accept
add chain=forward dst-address=10.0.20.30 action=accept
add chain=forward dst-address=10.0.50.0/24 src-address=10.0.20.15 action=accept
add chain=forward dst-address=10.0.50.0/24 src-address=10.0.20.30 action=accept
add chain=forward in-interface=back-to-home-vpn out-interface-list=WAN action=accept
add chain=forward in-interface=back-to-home-vpn out-interface-list=LAN action=accept
add chain=forward protocol=udp dst-port=53 out-interface-list=WAN action=accept
add chain=forward protocol=tcp dst-port=53 out-interface-list=WAN action=accept
add chain=forward in-interface-list=LAN dst-address=172.31.255.0/24 action=accept
add chain=forward in-interface=containers out-interface=vlan-lab action=accept
add chain=forward src-address=172.31.255.0/24 \
    dst-address-list=cloudflared-mgmt-allowed action=accept
add chain=forward src-address=10.0.99.0/24 dst-address=192.168.1.0/24 action=accept
add chain=forward protocol=tcp dst-port=853 in-interface-list=LAN action=reject
add chain=forward action=drop

/ip firewall nat
add chain=srcnat out-interface-list=WAN action=masquerade
add chain=srcnat src-address=10.0.99.0/24 dst-address=192.168.1.0/24 action=masquerade

/ip service set ssh address=10.0.99.0/24
/ip service set winbox address=10.0.99.0/24
/ip service set www address=10.0.99.0/24,172.31.255.2/32 port=8080
/ip service set www-ssl address=10.0.99.0/24,172.31.255.2/32 disabled=no
/ip service set ftp disabled=yes
/ip service set telnet disabled=yes
/ip service set api disabled=yes
/ip service set api-ssl disabled=yes

/queue simple add name=limit-iot-1m target=10.0.40.0/24 max-limit=1M/1M

/system identity set name=R1
/system clock set time-zone-name=America/Santo_Domingo
```
