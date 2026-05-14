---
title: "Docker MACVLAN and IPVLAN — Giving Containers Real LAN IPs in Your Homelab"
description: "Docker MACVLAN and IPVLAN networking guide — give containers real LAN IPs for Pi-hole, Home Assistant, and Scrypted. Includes Proxmox setup, host communication fix, and Compose examples."
date: 2026-05-13T15:30:00-04:00
tags:
  - docker
  - networking
  - homelab
  - containers
  - linux
keywords:
  - Docker MACVLAN setup
  - Docker IPVLAN L2 L3
  - containers LAN IP
  - Docker multi-network compose
  - Proxmox MAC spoofing Docker
summary: "Step-by-step Docker MACVLAN and IPVLAN guide — give containers real LAN IPs for Pi-hole, Home Assistant, Scrypted. Host communication fix, Proxmox gotcha, multi-network Compose examples."
canonical: "https://gntech.dev/posts/docker-macvlan-ipvlan-networking/"
---

By default, Docker containers sit on an isolated bridge network
(172.17.x.x). You reach them through port mappings like
`-p 8080:80`. This works for web dashboards, but it breaks for
anything that needs to be a first-class network citizen.

**Services that need their own LAN IP:**

- **Pi-hole** — network-wide DNS. Your router needs to reach it on
  port 53, and you can't map port 53 through Docker without breaking
  the host's own DNS resolution.
- **Home Assistant / ESPHome** — mDNS discovery for IoT devices.
  Broadcasts don't cross Docker bridges.
- **Plex / Jellyfin DLNA** — UPnP discovery requires being on the
  same broadcast domain.
- **Print servers, AirPlay receivers, SNMP collectors** — any
  service that relies on broadcast/multicast.

MACVLAN and IPVLAN are Docker network drivers that solve this by
giving containers their own presence on your physical LAN — their
own IP, their own MAC (or shared MAC with IPVLAN), directly
addressable from any device on your network.

This post covers how to set up both, when to use each, the crucial
pitfalls to avoid, and real Compose examples for common services.

---

## MACVLAN — The Default Choice

MACVLAN assigns each container a unique virtual NIC with its own
MAC address. Your router sees the container as a separate physical
device. DHCP assigns it an IP, or you set one statically.

### How It Works

The Docker host's physical interface (e.g., `eth0`) acts as a trunk.
The kernel creates virtual child interfaces, one per container, each
with its own MAC. The switch sees multiple MACs on one port — which
is perfectly normal for any switch made in the last 20 years.

### Creating a MACVLAN Network

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.0.0/24 \
  --gateway=10.0.0.1 \
  --ip-range=10.0.0.240/28 \
  -o parent=eth0 \
  macvlan-home
```

Breakdown of the flags:

- **`--subnet`** — Your LAN subnet. Must match your physical network.
- **`--gateway`** — Your router's IP.
- **`--ip-range`** — A subset Docker can assign from. Use a range
  *outside* your DHCP pool to avoid conflicts. If your router hands
  out 10.0.0.100–10.0.0.239, use 10.0.0.240/28 (240–254).
- **`-o parent`** — The host's physical interface. Run `ip link` to
  find yours (`eth0`, `enp3s0`, `ens18`, etc.).

### Running a Container on MACVLAN

```bash
docker run -d \
  --name pihole \
  --network macvlan-home \
  --ip 10.0.0.53 \
  pihole/pihole:latest
```

With Docker Compose:

```yaml
# docker-compose.yml
services:
  pihole:
    image: pihole/pihole:latest
    container_name: pihole
    hostname: pihole
    environment:
      TZ: America/Santo_Domingo
      WEBPASSWORD: "${PIHOLE_PASSWORD}"
    volumes:
      - pihole-etc:/etc/pihole
      - pihole-dnsmasq:/etc/dnsmasq.d
    restart: unless-stopped
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.53

networks:
  macvlan-home:
    external: true        # Created with docker network create

volumes:
  pihole-etc:
  pihole-dnsmasq:
```

That's it. Your Pi-hole is now at `10.0.0.53`, directly accessible
from any device on your LAN. Set your router's DNS to that IP.

### Multiple Containers on the Same MACVLAN

You can attach many containers to the same MACVLAN network, each
with a different IP:

```yaml
services:
  pihole:
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.53

  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: homeassistant
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.100

  scrypted:
    image: koush/scrypted:latest
    container_name: scrypted
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.50

networks:
  macvlan-home:
    external: true
```

---

## The Host-to-Container Problem (Important!)

MACVLAN has a fundamental limitation: **the Docker host cannot
communicate with its own MACVLAN containers**. Your host at
`10.0.0.10` cannot reach `10.0.0.53` — they're on the same physical
interface, but MACVLAN's internal routing prevents it.

This means:

- `docker exec` and health checks still work (they use the internal
  container namespace), but `curl http://10.0.0.53` from the host
  fails.
- If Pi-hole is your DNS server, the host itself can't use it.
- Services running on the host can't reach MACVLAN containers by
  their LAN IP.

### The Fix: A Host-Side MACVLAN Bridge

Create a secondary MACVLAN interface on the host that bridges the
gap:

```bash
# Create a host-side macvlan interface (same parent, bridge mode)
ip link add macvlan-bridge link eth0 type macvlan mode bridge

# Assign an unused IP from your ip-range
ip addr add 10.0.0.239/32 dev macvlan-bridge

# Bring it up
ip link set macvlan-bridge up

# Add a route for the container range through the bridge
ip route add 10.0.0.240/28 dev macvlan-bridge
```

Now `10.0.0.239` is the host's MACVLAN IP, and it can reach all
containers in the `10.0.0.240/28` range. Traffic routes through
`macvlan-bridge` directly — it never leaves the host.

### Persisting the Bridge (systemd)

Create a systemd unit so this survives reboots:

```ini
# /etc/systemd/system/macvlan-bridge.service
[Unit]
Description=MACVLAN bridge for Docker host-container communication
After=network.target docker.service
Requires=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c ' \
  ip link add macvlan-bridge link eth0 type macvlan mode bridge && \
  ip addr add 10.0.0.239/32 dev macvlan-bridge && \
  ip link set macvlan-bridge up && \
  ip route add 10.0.0.240/28 dev macvlan-bridge'
ExecStop=/bin/bash -c 'ip link delete macvlan-bridge'

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now macvlan-bridge
```

---

## IPVLAN — When MACVLAN Won't Work

IPVLAN is similar to MACVLAN but shares the host's MAC address
across all containers. The router sees one MAC with multiple IPs.

### IPVLAN L2 Mode

Functionally similar to MACVLAN — containers get LAN IPs, traffic
bridges at layer 2. The key difference is the shared MAC, which
matters when:

- Your hosting provider or network restricts multiple MACs per port
  (common on VPS/VDS).
- You have many containers and want to avoid MAC table exhaustion
  on your switch (rare, but possible with hundreds of containers).
- Your Proxmox bridge drops MACVLAN traffic (see below).

Creation:

```bash
docker network create \
  --driver ipvlan \
  --subnet=10.0.0.0/24 \
  --gateway=10.0.0.1 \
  --ip-range=10.0.0.240/28 \
  -o parent=eth0 \
  -o ipvlan_mode=l2 \
  ipvlan-home
```

In Compose:

```yaml
services:
  pihole:
    image: pihole/pihole:latest
    networks:
      ipvlan-home:
        ipv4_address: 10.0.0.53

networks:
  ipvlan-home:
    external: true
```

The host-to-container problem exists here too. The fix is the same
approach — an IPVLAN host interface — but IPVLAN only supports L2
mode for host-side interfaces:

```bash
ip link add ipvlan-bridge link eth0 type ipvlan mode l2
ip addr add 10.0.0.238/32 dev ipvlan-bridge
ip link set ipvlan-bridge up
```

### IPVLAN L3 Mode — Routed Networking

L3 mode puts containers in a completely separate subnet. The host
routes between the container subnet and your LAN.

```bash
docker network create \
  --driver ipvlan \
  --subnet=10.10.0.0/24 \
  --gateway=10.10.0.1 \
  -o parent=eth0 \
  -o ipvlan_mode=l3 \
  ipvlan-l3
```

The gateway `10.10.0.1` is actually the host itself. You need to:

1. Set up routing on the host (NAT or routing rules) so containers
   can reach the LAN.
2. Add a static route on your LAN router pointing to the Docker host
   for the `10.10.0.0/24` subnet.

L3 mode eliminates broadcast noise entirely — no ARP, no DHCP
broadcasts from containers. This is useful in security-segmented
networks or when you want to isolate container traffic at layer 3.
For most homelabs, stick with L2.

---

## Proxmox Gotcha: Enable MAC Spoofing

If Docker is running inside a Proxmox VM, the Proxmox bridge
(`vmbr0`) drops traffic from unknown MAC addresses by default.

**Fix:** Enable MAC spoofing on the VM's virtual NIC.

```bash
# On the Proxmox host
qm set <VMID> --net0 virtio,bridge=vmbr0,macspoof=1
```

Alternatively, in the Proxmox UI: select the VM → Hardware → Network
Device → Edit → check **MAC spoofing**.

Without this, MACVLAN traffic is silently dropped — containers get
IPs but can't communicate. IPVLAN avoids this issue because it
shares the VM's assigned MAC address.

---

## MACVLAN + Regular Bridge Together

Many services benefit from having *both* a MACVLAN interface (for
LAN access) and the default Docker bridge (for container-to-container
communication):

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: homeassistant
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.100
      docker-bridge:
        aliases:
          - homeassistant

networks:
  macvlan-home:
    external: true
  docker-bridge:
    driver: bridge
```

Home Assistant is reachable at `10.0.0.100` from your LAN for IoT
device discovery, while other containers on `docker-bridge` can
reach it by the hostname `homeassistant`.

---

## Troubleshooting

### Container has an IP but can't reach the internet

Probable cause: the `--gateway` IP is wrong, or the parent
interface is wrong. Verify:

```bash
# Confirm the parent interface exists
ip link show eth0

# Check the network config
docker network inspect macvlan-home

# Try pinging the gateway
docker exec pihole ping -c 3 10.0.0.1
```

### Container can't reach the internet via IPv6

MACVLAN supports IPv6, but you need to specify the subnet:

```bash
docker network create \
  --driver macvlan \
  --subnet=10.0.0.0/24 \
  --gateway=10.0.0.1 \
  --ip-range=10.0.0.240/28 \
  --subnet=fd00::/64 \
  --gateway=fd00::1 \
  -o parent=eth0 \
  macvlan-home
```

Some routers (especially MikroTik with IPv6 firewall rules) may
require the container's DUID or MAC to be registered.

### "Network macvlan-home is not manually connectable" on `docker compose up`

If you used the short Compose syntax (`network:` instead of
`networks:`) or forgot `external: true`:

```yaml
networks:
  macvlan-home:
    external: true
```

Pre-create the network with `docker network create` first.

### Containers can reach LAN but not each other

MACVLAN containers *can* talk to each other directly if they're
on the same MACVLAN network. If they can't, check your switch's
port isolation or private VLAN settings.

If using different MACVLAN networks with different parents or
subnets, they need a router (your gateway) to communicate.

---

## MACVLAN vs IPVLAN — Which Should You Use?

| Factor | MACVLAN | IPVLAN L2 | IPVLAN L3 |
|--------|---------|-----------|-----------|
| MAC per container | Unique | Shared | Shared |
| Switch MAC table | 1 entry per container | 1 entry total | 1 entry total |
| Host-to-container | Broken, needs bridge | Broken, needs bridge | Works (host is router) |
| Proxmox VM | Needs MAC spoofing | Works as-is | Works as-is |
| Broadcast handling | Passes through | Passes through | Isolated |
| Performance | Slight overhead per packet | Lower overhead | Lower overhead |
| Best for | Services needing unique identity | When you can't add more MACs | Security isolation |

**My recommendation for a homelab:** Start with MACVLAN. It's the
most straightforward and works well for 1–20 containers. Switch to
IPVLAN L2 only if you hit MAC limits or Proxmox issues. Use IPVLAN
L3 when you want to completely container-isolate a subnet.

---

## Complete Example: Pi-hole + Home Assistant + Scrypted

Here's a full working setup with host bridge for DNS:

```yaml
# docker-compose.yml
services:
  pihole:
    image: pihole/pihole:latest
    container_name: pihole
    hostname: pihole
    environment:
      TZ: America/Santo_Domingo
      WEBPASSWORD: "${PIHOLE_PASSWORD}"
      PIHOLE_DNS_: "1.1.1.1;8.8.8.8"
    volumes:
      - pihole-etc:/etc/pihole
      - pihole-dnsmasq:/etc/dnsmasq.d
    restart: unless-stopped
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.53

  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: homeassistant
    environment:
      TZ: America/Santo_Domingo
    volumes:
      - ha-config:/config
    restart: unless-stopped
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.100
      internal:
        aliases:
          - homeassistant

  scrypted:
    image: koush/scrypted:latest
    container_name: scrypted
    environment:
      TZ: America/Santo_Domingo
    volumes:
      - scrypted-config:/server/volume
    restart: unless-stopped
    ports:
      - "11080:11080/tcp"
    networks:
      macvlan-home:
        ipv4_address: 10.0.0.50
      internal:
        aliases:
          - scrypted

networks:
  macvlan-home:
    external: true
  internal:
    driver: bridge

volumes:
  pihole-etc:
  pihole-dnsmasq:
  ha-config:
  scrypted-config:
```

And the host-side bridge systemd unit (from the section above) so
the Docker host itself gets DNS from Pi-hole.

---

## Summary

MACVLAN and IPVLAN turn your Docker containers from isolated bridge
guests into full LAN citizens. Setup takes five minutes:

1. Create the network with `docker network create`
2. Attach containers with static IPs
3. Add the host-side bridge so the host can reach them (for MACVLAN)
4. Enable MAC spoofing if running on Proxmox

The result is services that behave like physical devices — no port
mapping, no NAT, just clean direct addressing. Pi-hole for network
DNS, Home Assistant for mDNS device discovery, Plex for DLNA — all
with their own IP, just like a Raspberry Pi on the network.

For most homelab scenarios, MACVLAN is the right choice. Keep
IPVLAN in your back pocket for environments with MAC restrictions
or Proxmox VMs that can't enable spoofing.
