---
title: "Docker IPv6 Networking — Enable Dual-Stack in Your Homelab"
description: "Configure Docker with full IPv6 support in your homelab — enable dual-stack networking, configure compose networks, assign Global Unicast or ULA, and run Traefik with IPv6 entry points."
date: 2026-05-21T07:00:00-04:00
tags:
  - docker
  - networking
  - homelab
  - linux
  - containers
keywords:
  - Docker IPv6 networking configuration homelab
  - enable IPv6 Docker daemon dual-stack
  - Docker Compose IPv6 network subnet ULA
  - Docker default-address-pools IPv6 automatic allocation
  - Traefik IPv6 reverse proxy Docker
  - Docker container IPv6 NDP proxy macvlan
  - IPv6 Docker firewall ip6tables configuration
summary: "Complete guide to enabling IPv6 in Docker — from daemon configuration and address pools to Compose networks, Traefik reverse proxy, and IPv6 firewall rules for your homelab."
canonical: "https://blog.gntech.me/posts/2026-05-21-docker-ipv6-networking-guide/"
---

IPv4 exhaustion is not theoretical. RIPE NCC, APNIC, and LACNIC
have all run out of /8 blocks. ISPs in Latin America, Europe, and
Asia are deploying IPv6 natively, and if your homelab runs behind
a GPON or FTTH connection, you likely already have a /56 or /64
from your ISP.

Yet Docker defaults to IPv4-only. Every `docker network create`,
every Compose file, every container — pure IPv4 with NAT. Running
dual-stack in 2026 is not a nice-to-have; it is a prerequisite
for services that need to be reachable over IPv6 directly, for
containers that need to bypass carrier-grade NAT, and for staying
compatible with a rapidly v6-ing internet.

This guide covers everything: enabling IPv6 in the Docker daemon,
configuring address pools for automatic allocation, building
IPv6-ready Compose stacks, running Traefik with IPv6 entry points,
and securing it all with `ip6tables`.

---

## Step 1 — Enable IPv6 in the Docker Daemon

The first step is telling the Docker daemon to allocate IPv6
addresses on the default bridge network. Edit or create
`/etc/docker/daemon.json`:

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00:dead:beef:1::/64",
  "ip6tables": true
}
```

- **`ipv6: true`** — Enables IPv6 on the default bridge.
- **`fixed-cidr-v6`** — The ULA (Unique Local Address) subnet for
  the default bridge. Use a ULA from `fd00::/8` rather than
  guessing at GUA prefixes you do not own.
- **`ip6tables: true`** — Automatically manages IPv6 firewall
  rules for port publishing and network isolation. Enabled by
  default, but worth making explicit.

Restart the daemon:

```bash
sudo systemctl restart docker
```

Verify the default bridge now has an IPv6 address:

```bash
ip -6 addr show docker0
# 6: docker0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
#    inet6 fd00:dead:beef:1::1/64 scope global
#    inet6 fe80::42:acff:fe12:2/64 scope link
```

Run a quick test:

```bash
docker run --rm -p 80:80 traefik/whoami
curl -6 http://[::1]:80
# Hostname: ...
# IP: ::1
# IP: 2001:db8:1::242:ac12:2
# RemoteAddr: [fd00:dead:beef:1::1]:57342
```

If you see IPv6 addresses in the output, the daemon is working.

---

## Step 1b — Default Address Pools for Dynamic IPv6

Without explicit configuration, user-defined networks with
`enable_ipv6: true` fall back to Docker's default address pools,
which include **no IPv6 pools**. This means every Compose stack
that needs IPv6 must specify an explicit `subnet` under `ipam`.

To make Docker auto-allocate IPv6 subnets just like it does for
IPv4, add pools to `daemon.json`:

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00:dead:beef:1::/64",
  "ip6tables": true,
  "default-address-pools": [
    { "base": "172.17.0.0/16", "size": 24 },
    { "base": "172.18.0.0/16", "size": 24 },
    { "base": "172.19.0.0/16", "size": 24 },
    { "base": "172.20.0.0/14", "size": 24 },
    { "base": "fd00:dead:beef::/48", "size": 64 }
  ]
}
```

This gives Docker 256 /64 IPv6 subnets to hand out dynamically
from the `fd00:dead:beef::/48` ULA range. Each Compose stack
that sets `enable_ipv6: true` without an explicit `subnet` gets
its own /64 automatically.

Restart Docker again after editing:

```bash
sudo systemctl restart docker
```

Test it with a quick network create:

```bash
docker network create --ipv6 test-ipv6-auto
docker network inspect test-ipv6-auto --format '{{.IPAM.Config}}'
# [{172.18.0.0/24  fd00:dead:beef:2::/64 }]
```

You should see a /64 ULA subnet allocated automatically.

---

## Step 2 — Docker Compose with Explicit IPv6 Networks

For production stacks where you want predictable addressing,
define the IPv6 subnet explicitly. Here is a complete Compose
file for a web app with a PostgreSQL backend:

```yaml
# docker-compose.yml — Dual-stack web app
services:
  app:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    networks:
      frontend:
        ipv4_address: 172.21.0.10
        ipv6_address: fd00:dead:beef:10::10
      backend:
        ipv4_address: 172.21.1.10
        ipv6_address: fd00:dead:beef:11::10

  db:
    image: postgres:16-alpine
    networks:
      backend:
        ipv4_address: 172.21.1.20
        ipv6_address: fd00:dead:beef:11::20
    environment:
      POSTGRES_PASSWORD: changeme

networks:
  frontend:
    driver: bridge
    enable_ipv6: true
    ipam:
      config:
        - subnet: 172.21.0.0/24
          gateway: 172.21.0.1
        - subnet: fd00:dead:beef:10::/64
          gateway: fd00:dead:beef:10::1

  backend:
    driver: bridge
    enable_ipv6: true
    internal: true
    ipam:
      config:
        - subnet: 172.21.1.0/24
          gateway: 172.21.1.1
        - subnet: fd00:dead:beef:11::/64
          gateway: fd00:dead:beef:11::1
```

Key points:

- **Static IPv6 addresses** let you write firewall rules against
  known addresses and keep DNS records stable.
- **The backend network is `internal: true`** — no external access,
  no default route. Only the app container can reach the database.
  This works identically for IPv6 traffic.
- **Each network gets its own /64.** Docker bridges support
  multiple IPAM config blocks; the IPv4 and IPv6 entries are
  completely independent.

If your host has a public /64 from your ISP, you can skip ULA and
use GUA (Global Unicast Addresses) directly. Replace the subnet
with your delegated prefix:

```yaml
networks:
  frontend:
    enable_ipv6: true
    ipam:
      config:
        - subnet: 2001:db8:1234:ab::/64
          gateway: 2001:db8:1234:ab::1
```

---

## Step 3 — Exposing Containers to the LAN over IPv6

The Docker bridge with port publishing (`-p` or `ports:` in
Compose) works for both IPv4 and IPv6. Publishing port 443
binds to `[::]:443` on the host by default:

```bash
docker run -d -p 443:443 --network ipv6-net myapp
```

Internally, Docker creates `ip6tables` DNAT rules just like it
creates `iptables` rules for IPv4. Check them:

```bash
sudo ip6tables -t nat -L DOCKER -n
# Chain DOCKER (2 references)
# DNAT  tcp  [::]:443 -> fd00:dead:beef:10::10:443
```

### MACVLAN for Direct LAN Addressing

If you want containers to appear as first-class citizens on your
LAN with their own IPv6 address (no host NAT), use a **macvlan**
network. This is especially useful for services that need direct
inbound connections — game servers, SIP phones, P2P nodes.

```bash
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  --subnet=2001:db8:1234:ab::/64 \
  --gateway=2001:db8:1234:ab::1 \
  -o parent=eth0 \
  macvlan-lan
```

```yaml
# docker-compose.yml — MACVLAN with IPv6
services:
  direct-app:
    image: nginx:alpine
    networks:
      lan:
        ipv4_address: 192.168.1.100
        ipv6_address: 2001:db8:1234:ab::100

networks:
  lan:
    driver: macvlan
    driver_opts:
      parent: eth0
    enable_ipv6: true
    ipam:
      config:
        - subnet: 192.168.1.0/24
          gateway: 192.168.1.1
        - subnet: 2001:db8:1234:ab::/64
          gateway: 2001:db8:1234:ab::1
```

**Caveat:** MACVLAN bridges do not allow communication between
the host and its own containers without a separate macvlan
interface on the host. For most homelab setups, bridge + port
publishing is simpler and sufficient.

---

## Step 4 — Traefik with IPv6 Entry Points

If you run Traefik as your reverse proxy, configuring IPv6 entry
points is straightforward. The key is binding `[::]:port` instead
of `0.0.0.0:port`.

Static configuration (`traefik.yml`):

```yaml
entryPoints:
  web:
    address: "[::]:80"
  websecure:
    address: "[::]:443"
    forwardedHeaders:
      trustedIPs:
        - "10.0.0.0/8"
        - "fd00::/8"
        - "172.16.0.0/12"

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web
```

Or via CLI arguments in a Compose stack:

```yaml
services:
  traefik:
    image: traefik:v3.3
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=[::]:80
      - --entrypoints.websecure.address=[::]:443
      - --certificatesresolvers.letsencrypt.acme.email=admin@example.com
      - --certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web
    ports:
      - "80:80"
      - "443:443"
    networks:
      - proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    cap_drop:
      - ALL

  app:
    image: myapp:latest
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.example.com`)"
      - "traefik.http.routers.app.entrypoints=websecure"
      - "traefik.http.routers.app.tls.certresolver=letsencrypt"

networks:
  proxy:
    driver: bridge
    enable_ipv6: true
    ipam:
      config:
        - subnet: fd00:dead:beef:ff::/64
```

Because the entry points bind to `[::]:port` and the host kernel
has `net.ipv6.bindv6only=0` (default on most distros), IPv4
traffic also reaches these sockets via IPv4-mapped IPv6
addresses. You do not need separate IPv4 and IPv6 entry points.

### Verifying Traefik IPv6

If you have the Traefik API enabled:

```bash
curl -6 http://[::1]:8080/api/entrypoints | jq .
# {
#   "web": { "address": "[::]:80" },
#   "websecure": { "address": "[::]:443" }
# }
```

Test an actual request through Traefik over IPv6:

```bash
curl -6 -v https://app.example.com/
# * IPv6: 2001:db8:1234::1
# ...
# < HTTP/2 200
```

Check Traefik logs for the client IP source — it should show your
real IPv6 address, not the Docker gateway:

```bash
docker compose logs traefik | grep -E "[0-9a-fA-F:]{3,39}"
# 2026-05-21T10:30:00Z app.example.com "GET /" - [2001:db8:5678::1]:44312
```

---

## Step 5 — IPv6 Firewall Rules with ip6tables

Docker's `ip6tables: true` manages port publishing rules
automatically, but it does not restrict outbound or forwarded
traffic. For a homelab running public-facing services, add a
minimal ip6tables ruleset.

Create `/etc/iptables/rules.v6` (on Debian/Ubuntu with
iptables-persistent):

```bash
sudo apt install iptables-persistent
```

Example ruleset:

```
# /etc/iptables/rules.v6
*filter
:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]
:DOCKER - [0:0]

# Allow established connections
-A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow loopback
-A INPUT -i lo -j ACCEPT

# Allow ICMPv6 (Neighbor Discovery, MLD, etc.)
-A INPUT -p ipv6-icmp -j ACCEPT

# Allow SSH and Docker-published ports
-A INPUT -p tcp --dport 22 -j ACCEPT
-A INPUT -p tcp --dport 80 -j ACCEPT
-A INPUT -p tcp --dport 443 -j ACCEPT

# Allow Docker bridge traffic
-A INPUT -i docker0 -j ACCEPT

# Log and drop everything else
-A INPUT -j LOG --log-prefix "IPv6-DROP: "
-A INPUT -j DROP

# Forward rules to accept Docker NAT traffic
-A FORWARD -i docker0 -j ACCEPT
-A FORWARD -o docker0 -m state --state ESTABLISHED,RELATED -j ACCEPT
COMMIT
```

Apply:

```bash
sudo ip6tables-restore < /etc/iptables/rules.v6
```

**Important:** Docker inserts its own rules on restart. If you
use a custom ruleset, ensure Docker's `ip6tables` rules chain
properly. The safest approach is to set your default policies
and let Docker manage its own chains — do not flush the DOCKER
chain.

---

## Step 6 — DNS and Reverse DNS for Container IPv6

Containers on a user-defined bridge get DNS via Docker's embedded
DNS resolver (127.0.0.11), which handles both A and AAAA records
seamlessly. But external DNS is your responsibility.

For public-facing containers, add AAAA records alongside your
existing A records:

```
app.example.com.  IN A     192.168.1.100
app.example.com.  IN AAAA  2001:db8:1234:ab::100
```

If your ISP delegates a reverse zone (ip6.arpa delegation), set
up PTR records too. Most homelab ISPs do not provide this, but
you can run your own authoritative DNS internally with
PowerDNS or Bind9 and delegate within your network.

For internal service discovery with Traefik, Docker's DNS
resolver handles AAAA queries natively. Containers on the same
network can reach each other by service name over IPv6 or IPv4
— whichever the client requests.

---

## Troubleshooting Common IPv6 Docker Issues

### Container cannot reach the internet over IPv6

Check that the host has a working IPv6 default route:

```bash
ip -6 route show default
# default via fe80::1 dev eth0 proto ra metric 1024
```

If missing, enable SLAAC or DHCPv6 on the host. Docker bridges
do not run their own router advertisements — containers rely on
the host's global connectivity.

### Port publishing binds IPv4 only

Ensure `daemon.json` has `"ipv6": true` and Docker was restarted.
Without it, `-p 80:80` only creates an IPv4 iptables rule.

Check:

```bash
sudo ip6tables -t nat -L DOCKER -n
```

If empty, IPv6 port publishing is not working.

### Containers cannot ping each other's IPv6 addresses

User-defined bridge networks forward traffic by default, but the
container must have an IPv6 default route. On bridge networks,
Docker adds a default route via the gateway address. Verify:

```bash
docker exec myapp ip -6 route
# default via fd00:dead:beef:10::1 dev eth0
# fd00:dead:beef:10::/64 dev eth0 proto kernel metric 256
```

### "IPv6 is not supported by the kernel" on older kernels

Docker IPv6 requires the `ip6_tables` kernel module. Load it:

```bash
sudo modprobe ip6_tables
echo "ip6_tables" | sudo tee /etc/modules-load.d/ip6_tables.conf
```

This is rare on modern kernels but can surface in minimal Docker
images running Docker-in-Docker.

---

## Summary

Enabling IPv6 in your Docker homelab is a few lines of JSON and
one daemon restart. The payoff is significant: containers get
globally routable addresses, services bypass carrier-grade NAT,
and your infrastructure is ready for an IPv6-dominant internet.

The complete setup checklist:

1. Add `ipv6: true` and a `fixed-cidr-v6` ULA to `daemon.json`
2. Optionally add IPv6 `default-address-pools` for auto-allocation
3. Configure Compose networks with `enable_ipv6: true` and
   explicit subnets
4. Set Traefik entry points to `[::]:80` and `[::]:443`
5. Lock down with `ip6tables` — default DROP on INPUT
6. Add AAAA DNS records for public services

IPv4 is not going away tomorrow, but dual-stack is the standard
today. Your homelab should speak both.
