---
title: "Docker MACVLAN Homelab Networking — Assign Direct VLAN IPs"
description: "Give Docker containers direct IPs on any VLAN using MACVLAN and IPVLAN. A practical homelab guide with real Compose configs, routing, and use cases."
date: 2026-06-09T16:00:00-04:00
tags:
  - docker
  - networking
  - homelab
  - vlan
  - linux
keywords:
  - Docker MACVLAN driver homelab networking guide
  - assign static IP Docker container VLAN interface
  - Docker IPVLAN L2 L3 mode difference comparison
  - Docker compose macvlan network configuration
  - direct container IP on physical network without port mapping
  - Docker VLAN segmentation homelab security
  - Docker macvlan vs bridge networking performance
summary: "Give your containers their own IPs on any VLAN with Docker MACVLAN and IPVLAN. A practical guide with docker-compose configs, routing tweaks, and real-world homelab use cases."
canonical: "https://blog.gntech.me/posts/docker-macvlan-homelab-networking/"
---

If you run Docker in your homelab, your containers probably sit behind the default `bridge` network, hidden behind a NAT on `172.17.0.0/16`. That works fine for casual setups, but the moment you need VLAN segmentation — keeping your IoT containers on VLAN 30, your reverse proxy on VLAN 10, and your databases isolated on VLAN 40 — the bridge driver becomes a bottleneck.

You end up stacking port mappings, guessing which containers talk to which, and losing the IP-level visibility that makes VLANs useful in the first place.

**Docker MACVLAN and IPVLAN drivers solve this.** They let you attach containers directly to your physical network with their own IP addresses on whichever VLAN you choose. No port forwarding. No NAT. Just containers behaving like full-fledged network members on the right segment.

## MACVLAN vs IPVLAN — Choosing the Right Driver

Before reaching for `docker network create`, understand which driver fits your environment.

### MACVLAN

The MACVLAN driver assigns a **unique MAC address** to each container on the same parent interface. From the network's perspective, each container looks like a separate physical device.

```
Container A (00:0c:29:aa:01) ─┐
Container B (00:0c:29:bb:02) ─┤── eth0.20 (host) ── VLAN 20
Container C (00:0c:29:cc:03) ─┘
```

**Pros:**
- Works with most switches and routers out of the box
- Containers appear as independent hosts (DHCP, ARP, mDNS all work)
- Near line-rate performance — no extra kernel routing

**Cons:**
- Some managed switches restrict the number of MAC addresses per switchport
- Requires the parent interface to be in promiscuous mode
- **The host cannot reach containers on a MACVLAN network** without additional setup
- Does not work over wireless interfaces

### IPVLAN

The IPVLAN driver assigns **one shared MAC** to all containers on the parent interface, differentiated only by IP address.

**IPVLAN L2 mode** — containers live on the same L2 broadcast domain as the parent:
- Switch-friendly: only one MAC per port regardless of container count
- Same performance profile as MACVLAN
- Host *can* reach containers (major advantage)

**IPVLAN L3 mode** — containers communicate via L3 routing only:
- No ARP, no MAC learning
- Routes must be configured on upstream routers
- Higher CPU overhead for software routing

### Decision Guide

| Need | Driver |
|------|--------|
| Simple direct IPs, no switch limits | MACVLAN |
| Many containers, switch port MAC limits | IPVLAN L2 |
| Host needs to reach containers directly | IPVLAN L2 |
| Strict L3 isolation from broadcast domain | IPVLAN L3 |
| WiFi parent interface | Neither (use bridge + port mapping) |

For most homelabs, **MACVLAN is the right starting point**. Switch over to IPVLAN only if you hit MAC limits or need host-to-container connectivity without extra bridge work.

## Setting Up Docker MACVLAN

### Prerequisites

- Docker Engine 24+ (20.10 works too, but 24+ has better networking)
- A wired Ethernet interface (MACVLAN/IPVLAN don't work on WiFi)
- VLAN-aware parent interface (a physical NIC or a VLAN sub-interface)

### Creating the MACVLAN Network

Assume your host connects via `eth0`, and you want containers on VLAN 20 (`10.0.20.0/24` with gateway `10.0.20.1`):

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  --opt parent=eth0 \
  vlan20
```

If your VLAN is tagged on the switch but the host interface is untagged, create a Linux VLAN sub-interface first:

```bash
ip link add link eth0 name eth0.20 type vlan id 20
ip link set eth0.20 up
```

Then create the MACVLAN network using `eth0.20` as the parent:

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  --opt parent=eth0.20 \
  vlan20
```

> **Important:** Make sure the host itself has an IP on VLAN 20 through some other path (a bridge or a separate interface) if you need the host to reach containers on this network. The MACVLAN driver isolates the parent interface from container IPs.

## Docker Compose Configuration

Here is how you wire a container to a MACVLAN network using Docker Compose. This example puts Nginx on VLAN 20 with a static IP:

```yaml
networks:
  vlan20:
    external: true
    name: vlan20

services:
  nginx:
    image: nginx:1.27-alpine
    container_name: web-vlan20
    hostname: web-vlan20
    networks:
      vlan20:
        ipv4_address: 10.0.20.100
    restart: unless-stopped
```

Start it:

```bash
docker compose up -d
```

Verify the container picked up the right IP:

```bash
docker inspect web-vlan20 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
# Output: 10.0.20.100
```

Now ping `10.0.20.100` from any device on VLAN 20. The container responds directly — no port mapping needed.

### Multiple Containers on Different VLANs

Run services across multiple VLANs in one Compose file:

```yaml
networks:
  vlan10:
    external: true
    name: vlan10
  vlan30:
    external: true
    name: vlan30

services:
  traefik:
    image: traefik:v3.2
    container_name: traefik
    networks:
      vlan10:
        ipv4_address: 10.0.10.50
    ports: []

  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mqtt
    networks:
      vlan30:
        ipv4_address: 10.0.30.50
    volumes:
      - ./mosquitto/config:/mosquitto/config
```

Create the two networks first:

```bash
docker network create --driver macvlan --subnet=10.0.10.0/24 --gateway=10.0.10.1 --opt parent=eth0.10 vlan10
docker network create --driver macvlan --subnet=10.0.30.0/24 --gateway=10.0.30.1 --opt parent=eth0.30 vlan30
```

Traefik now lives on your DMZ VLAN with a public IP (assuming VLAN 10 routes to the internet), and MQTT lives on your IoT VLAN 30 — and they can still reach each other if the upstream router routes between those VLANs.

## VLAN-Aware Routing and Connectivity

### The MACVLAN Host-Connectivity Problem

The biggest gotcha with MACVLAN: **the host cannot reach containers at the L3 level** without workarounds. If you SSH into your Proxmox host and try to ping `10.0.20.100`, it fails — because the MACVLAN driver creates a dedicated bridge that is not connected to the host's own networking stack.

### Solution — MACVLAN Bridge (Host Mode)

Create the MACVLAN network in bridge mode:

```bash
# Create a shared macvlan bridge
docker network create \
  --driver macvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  --opt parent=eth0 \
  --ipam-driver default \
  --aux-address="host=10.0.20.250" \
  vlan20

# Create a macvlan interface on the host in bridge mode
ip link add macvlan20 link eth0 type macvlan mode bridge
ip addr add 10.0.20.250/24 dev macvlan20
ip link set macvlan20 up

# Add a route so the host uses the macvlan interface for container traffic
ip route add 10.0.20.0/24 dev macvlan20 metric 1000
```

Now the host can ping `10.0.20.100` (your nginx container) and services running there.

To make this persistent on Debian/Ubuntu with `systemd-networkd`, create `/etc/systemd/network/10-macvlan20.netdev`:

```ini
[NetDev]
Name=macvlan20
Kind=macvlan

[MACVLAN]
Mode=bridge
```

And `/etc/systemd/network/10-macvlan20.network`:

```ini
[Match]
Name=macvlan20

[Network]
Address=10.0.20.250/24

[Route]
Destination=10.0.20.0/24
Metric=1000
```

Then reload:

```bash
systemctl restart systemd-networkd
```

### When to Prefer IPVLAN Instead

If the MACVLAN bridge dance feels too hacky, switch to IPVLAN L2. The host can reach containers natively.

```bash
docker network create \
  --driver ipvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  --opt parent=eth0.20 \
  --ipvlan l2 \
  iot_net
```

```yaml
services:
  example:
    image: nginx:alpine
    networks:
      iot_net:
        ipv4_address: 10.0.20.200
```

No extra routing. The host sees the container IP on the same subnet and can communicate directly.

## Real-World Homelab Use Cases

### DMZ Reverse Proxy (VLAN 10)

Your Traefik or Nginx Proxy Manager needs ports 80/443 exposed to the internet. Put it on a dedicated DMZ VLAN with a static IP and firewall rules limiting inbound to ports 80/443 only.

```yaml
services:
  traefik:
    image: traefik:v3.2
    container_name: traefik
    networks:
      dmz:
        ipv4_address: 10.0.10.2
    command:
      - "--providers.docker.endpoint=unix:///var/run/docker.sock"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.address=:80"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
```

### Isolated IoT Network (VLAN 30)

MQTT, Zigbee2MQTT, ESPHome containers should not have direct internet access. Put them on VLAN 30 with an upstream ACL blocking outbound WAN:

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.30.0/24 \
  --gateway=10.0.30.1 \
  --opt parent=eth0.30 \
  iot_net
```

### Media Servers on Guest/Smart TV VLAN (VLAN 40)

Jellyfin or Plex containers streaming to smart TVs should live on the same VLAN as your TVs. Direct IP access means DLNA, Chromecast, and mDNS discovery work natively:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    networks:
      media_vlan:
        ipv4_address: 10.0.40.50
    volumes:
      - /opt/media:/media
      - ./jellyfin/config:/config
    devices:
      - /dev/dri:/dev/dri
```

## Troubleshooting Common Issues

### Container Can't Reach Internet

Check the gateway on the VLAN:

```bash
docker exec container-name ip route show default
```

The gateway must be reachable from the VLAN's broadcast domain. If your upstream router uses a different IP as gateway, set `--gateway` to that IP when creating the network.

### Host Can't Reach Container (MACVLAN only)

This is expected behavior. Use one of:
- IPVLAN L2 instead
- The MACVLAN bridge host interface described above
- Create a second network (bridge) on the host just for management traffic

### Ping Works, DNS Doesn't

Docker does not automatically inject DNS settings for MACVLAN/IPVLAN networks. The container inherits the host's `/etc/resolv.conf`, which may not be routed on the VLAN. Set explicit DNS:

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  --ip-range=10.0.20.128/25 \
  --opt parent=eth0.20 \
  vlan20
```

Or set DNS explicitly in the Compose service:

```yaml
services:
  web-vlan20:
    image: nginx:1.27-alpine
    networks:
      vlan20:
        ipv4_address: 10.0.20.100
    dns:
      - 10.0.0.1
      - 1.1.1.1
```

### Switch Drops Traffic (Too Many MACs)

Some managed switches limit per-port MAC addresses (especially on edge ports). If you run 10+ containers on one parent interface, switch to IPVLAN L2 — it uses a single MAC for all containers.

### Parent Interface Goes Down

MACVLAN networks die if the parent interface goes down. There is no built-in failover or redundancy. If uptime matters, consider placing the parent interface on a LAG or bonding interface first.

## Performance Considerations

MACVLAN performs at near line rate because the kernel handles packet switching in hardware through the NIC's macvlan offload. In benchmarks, MACVLAN adds roughly **1-3% overhead** compared to bare-metal — far better than bridge NAT, which can add 15-25% overhead for high-throughput workloads.

IPVLAN L2 is essentially identical to MACVLAN in performance. IPVLAN L3 adds more kernel routing cycles, making it 5-10% slower for bulk transfers.

| Driver | CPU Overhead | Throughput | Use When |
|--------|-------------|-----------|----------|
| Default bridge (NAT) | Moderate-High (15-25%) | Good | Simple single-host stacks |
| MACVLAN | Low (1-3%) | Near line-rate | VLAN separation, direct IP access |
| IPVLAN L2 | Low (1-3%) | Near line-rate | Many containers, host reachability |
| IPVLAN L3 | Moderate (5-10%) | Good | L3 isolated networks |

For a media server streaming 4K at 100+ Mbps, the difference between MACVLAN and bridge NAT is negligible. For a file-transfer or backup container saturating 10 GbE, MACVLAN matters.

## Conclusion

Docker MACVLAN and IPVLAN drivers turn containers into first-class citizens on your network. Instead of wrangling port mappings and bridge NAT, you assign each container a real IP on the right VLAN and let your existing firewall rules and routing handle the rest.

Here is the cheat sheet:

- **MACVLAN** for most cases — simple, fast, one container = one MAC
- **IPVLAN L2** when switch MAC limits bite you or the host needs to talk to containers
- **IPVLAN L3** when you need true L3 isolation

Start with one service on a dedicated VLAN and expand from there. Your network will thank you — and so will your future self when the "what IP does this container have?" question has a straightforward answer.

*Related: [Linux Bridge Networking Debugging for Docker and Proxmox](/posts/linux-bridge-networking-debugging-docker-proxmox/), [systemd-networkd for Homelab Networking](/posts/systemd-networkd-homelab-networking-bridges-vlans-bonds/)*
