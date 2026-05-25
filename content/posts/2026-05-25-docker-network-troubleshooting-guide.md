---
title: "Docker Network Troubleshooting — Diagnostics and Fixes for Container Connectivity"
description: "Diagnose and fix Docker container networking issues — DNS resolution failures, port binding errors, cross-host connectivity, bridge network debugging, and netshoot diagnostics for homelab deployments."
date: 2026-05-25T17:00:00-04:00
tags:
  - docker
  - networking
  - linux
  - troubleshooting
  - homelab
keywords:
  - Docker container networking troubleshooting
  - Docker DNS resolution failure fix
  - Docker bridge network debugging guide
  - netshoot container network diagnostics
  - Docker port binding errors resolve
  - container cross-host connectivity docker
  - docker-compose network connectivity issues
summary: "A practical guide to diagnosing and fixing Docker container networking problems — DNS timeouts, port conflicts, bridge network isolation, cross-host communication, and the netshoot toolkit for homelab deployments."
canonical: "https://gntech.dev/posts/docker-network-troubleshooting-guide/"
---

Docker networking is the number one source of "it works on my machine"
failures in homelabs. A container can't reach the database. DNS resolves
on the host but not inside the container. Port 8080 is already in use.
The error messages are cryptic, and `docker inspect` spews JSON that's
hard to parse under pressure.

This guide covers the five most common Docker networking failure modes,
how to diagnose each one with concrete commands, and the permanent fix.
You'll learn to use `netshoot` like a network engineer, decode Docker's
internal DNS resolution, debug bridge and macvlan interfaces, and build
robust multi-service compose files that survive host reboots and IP
reassignments.

---

## The Diagnostic Toolkit — netshoot

Before fixing anything, you need a containerized network toolkit that
runs in the same network namespace as the broken service. The
[nicolaka/netshoot](https://github.com/nicolaka/netshoot) image bundles
everything: `tcpdump`, `dig`, `nslookup`, `curl`, `ping`, `mtr`,
`iftop`, `iperf3`, `nmap` and more — zero installation on the host.

### Run netshoot in a Container's Network Namespace

```bash
# Launch netshoot sharing the target container's network stack
docker run -it --rm --net container:<container-name> nicolaka/netshoot
```

Once inside, every tool sees the same network interfaces, routing
table, and DNS configuration as the container you're debugging.

```bash
# Inside netshoot — check interfaces
ip addr show

# Check routing
ip route

# Check DNS config
cat /etc/resolv.conf

# Check DNS resolution
dig +short service-name.local
nslookup db-service

# Hit the target port
curl -v http://other-service:8080/metrics

# Trace the path
mtr -r database-host
```

### Common CLI Installation Alternatives

If you can't pull netshoot (air-gapped or constrained homelab), drop
these into any container:

```bash
# On Debian/Ubuntu-based containers
apt update && apt install -y dnsutils iproute2 curl netcat-openbsd mtr-tiny

# On Alpine-based containers
apk add bind-tools iproute2 curl netcat-openbsd mtr
```

---

## 1. DNS Resolution Failures Inside Containers

**Symptom:** `curl http://service-name` works on the host but fails
inside a container with `Name or service not known`. Pinging by IP
works fine.

**Root cause:** Docker's embedded DNS resolver (127.0.0.11) isn't
reaching the configured upstream DNS servers, or the container isn't
on a user-defined bridge network.

### Diagnosis

```bash
# Check which DNS servers the container sees
docker run --rm alpine cat /etc/resolv.conf
# Expected: "nameserver 127.0.0.11" (Docker's internal resolver)

# Check if the container is on a user-defined network
docker inspect <container> --format '{{json .NetworkSettings.Networks}}'
# If only "bridge" appears, you're on the default bridge — no DNS.
```

### The Problem with the Default Bridge

Containers attached to Docker's `bridge` network (the default) use the
host's `/etc/resolv.conf` directly through the host's loopback,
inheriting whatever DNS servers the host uses. User-defined bridge
networks, on the other hand, get Docker's embedded DNS resolver at
127.0.0.11, which enables container-name resolution.

**Fix — always use a user-defined network:**

```yaml
# docker-compose.yml
services:
  app:
    image: my-app:latest
    networks:
      - app-net

  db:
    image: postgres:16-alpine
    networks:
      - app-net

networks:
  app-net:
    driver: bridge
```

If you're using `docker run` instead:

```bash
docker network create app-net
docker run -d --name db --network app-net postgres:16-alpine
docker run -it --rm --network app-net alpine ping db  # Works!
```

### DNS Timeout on User-Defined Networks

If DNS still fails on user-defined networks:

```bash
# Check Docker daemon DNS settings
docker info | grep -i dns

# Override DNS per-container
docker run -d --dns 10.0.20.1 --dns 1.1.1.1 --network app-net my-app

# Or per-compose-service
services:
  app:
    dns:
      - 10.0.20.1    # Your homelab DNS
      - 1.1.1.1      # Cloudflare fallback
```

**System-wide fix** — configure Docker daemon DNS:

```json
{
  "dns": ["10.0.20.1", "1.1.1.1"]
}
```

Save this to `/etc/docker/daemon.json` and restart:

```bash
systemctl restart docker
```

---

## 2. Port Already in Use

**Symptom:** `docker: Error response from daemon: driver failed
programming external connectivity on endpoint <name>: Bind for
0.0.0.0:8080 failed: port is already allocated.`

### Diagnosis

```bash
# Find what's using the port
ss -tlnp | grep 8080
# or
lsof -i :8080

# Check if another Docker container has the port
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep 8080

# Check if a systemd service is listening
systemctl list-sockets | grep 8080
```

### Common Causes in Homelabs

1. **Another container on the same host claims the port.** Two services
   can't both bind to host port 8080. Move one to a different port:

```yaml
services:
  app1:
    ports:
      - "8081:8080"  # Map host 8081 to container 8080
  app2:
    ports:
      - "8080:8080"  # Keep this one
```

2. **A previous container didn't release the port.** Docker does
   release ports on container stop, but a stopped container still
   reserves its IP. Restart or remove it:

```bash
docker rm -f <old-container>  # Force remove
```

3. **Traefik/NGINX reverse proxy is listening there.** Your reverse
   proxy binds to 80/443/8080 on the host. Your service shouldn't
   also expose those ports — expose an unprivileged port and let
   the proxy route traffic:

```yaml
services:
  my-service:
    expose:
      - "3000"            # Internal only — no host port binding
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.my-service.rule=Host(`app.gntech.dev`)"
```

4. **systemd-resolved or dnsmasq on port 53.** Docker maps container
   DNS to 127.0.0.11, but if you're running a local DNS service on
   the host (Pi-hole, AdGuard Home, dnsmasq), they compete for port 53:

```bash
# Check what's on port 53
ss -tulpn | grep ':53'

# Solutions:
# - Move Pi-hole/AdGuard to another port (e.g., 5353)
# - Run DNS services in Docker with network_mode: host
# - Disable systemd-resolved on the host
systemctl stop systemd-resolved
systemctl disable systemd-resolved
```

---

## 3. Cross-Container and Cross-Host Connectivity

**Symptom:** Containers on the same Docker network can't communicate,
or containers on different hosts can't reach each other.

### Same Host, Same User-Defined Network

Containers on the same user-defined bridge can reach each other by
container name, but not by `localhost`. The container's idea of
`localhost` is its own network namespace — not the host's.

```bash
# This works (same network, by name):
docker exec app curl http://db:5432

# This does NOT work from inside a container:
docker exec app curl http://localhost:5432
```

**Fix — use service names, not localhost:**

```yaml
# Wrong: container tries to reach another service via localhost
# Wrong: container tries to reach host services via 127.0.0.1

# Right: use the service name (Docker DNS resolves it)
# Right: use host.docker.internal for host services
```

To reach services *on the host* from inside a container:

```yaml
services:
  my-app:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

This adds a `/etc/hosts` entry that resolves to the Docker gateway
IP (172.x.x.1), which routes to the host's network stack. Then
inside the container:

```bash
curl http://host.docker.internal:9090/api  # Hits host's port 9090
```

### Cross-Host Networking (Multi-Node Docker)

Docker's default bridge network does not span hosts. Containers on
different machines cannot reach each other by container name. Three
solutions:

**Option A — Expose ports and use host IPs:**

```yaml
services:
  my-app:
    ports:
      - "3000:3000"  # Expose on the host's IP
```

Then from another host: `curl http://10.0.20.30:3000`.

**Option B — Docker Swarm overlay network:**

```bash
# Initialize swarm on first node
docker swarm init --advertise-addr 10.0.20.30

# On other nodes
docker swarm join --token <token> 10.0.20.30:2377

# Create overlay network that spans all nodes
docker network create --driver overlay --attachable homelab-overlay
```

Then any container attached to `homelab-overlay` can reach any other
container on that network across hosts — by container name.

**Option C — Tailscale or WireGuard mesh:**

For a homelab without Docker Swarm, route over Tailscale/WireGuard:

```yaml
services:
  app:
    networks:
      app-net:
        ipv4_address: "100.100.1.10"  # Tailscale IP
```

This requires configuring Tailscale on each Docker host and attaching
containers to the Tailscale interface.

---

## 4. Bridge and Macvlan Networking Issues

### Bridge Network — Container Cannot Reach External Network

**Symptom:** Containers can talk to each other but cannot reach the
internet. `ping 1.1.1.1` hangs.

**Diagnosis:**

```bash
# From inside the container (via netshoot)
ip route show default
# Expected: default via 172.x.x.1 dev eth0
# If missing, the container has no default gateway

# Check iptables NAT rules on the host
iptables -t nat -L -n | grep MASQUERADE
# Docker should have a MASQUERADE rule for the bridge subnet
```

**Fix — enable IP forwarding and check iptables:**

```bash
# On the Docker host
sysctl net.ipv4.ip_forward=1
# Make permanent
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

# Verify Docker's iptables rules exist
docker network inspect bridge --format '{{json .IPAM.Config}}'
# Ensure iptables is not fully blocking Docker bridge traffic
iptables -I DOCKER-USER -i br-<id> -j ACCEPT
```

If you use UFW, it overrides Docker's iptables rules. See the
[Docker UFW fix](https://gntech.dev/posts/docker-ufw-firewall-fix/)
for the permanent solution:

```bash
# /etc/ufw/after.rules — add before the final COMMIT
*filter
:DOCKER-USER - [0:0]
-A DOCKER-USER -j RETURN -s 10.0.0.0/8
-A DOCKER-USER -j RETURN -s 172.16.0.0/12
-A DOCKER-USER -j DROP -p tcp --dport 2375:2376
-A DOCKER-USER -j DROP -p tcp --dport 3375
COMMIT
```

### Macvlan — Container Receives DHCP but Can't Reach Host

**Symptom:** Macvlan containers get IPs from your DHCP server and can
reach external hosts, but cannot reach services running on the Docker
host itself.

**Root cause:** Macvlan bypasses the host's network stack. The host
cannot communicate with macvlan containers unless you create a
subinterface.

**Diagnosis:**

```bash
# From the container
ip addr show
# Should show the macvlan (not bridge) interface

# From the host — try reaching the container's IP
ping 10.0.20.50  # The macvlan container's IP
```

**Fixes:**

Option 1 — Use IPvlan L2 instead (lighter, no MAC address per
container):

```bash
docker network create -d ipvlan \
  --subnet=10.0.20.0/24 \
  --gateway=10.0.20.1 \
  -o parent=eth0 \
  -o ipvlan_mode=l2 \
  ipvlan-net
```

Option 2 — Add a macvlan subinterface on the host so it can
communicate with macvlan containers:

```bash
# On the Docker host
ip link add macvlan-host link eth0 type macvlan mode bridge
ip addr add 10.0.20.49/32 dev macvlan-host
ip link set macvlan-host up
ip route add 10.0.20.50/32 dev macvlan-host
```

Option 3 — Route through an external gateway (MikroTik/OPNsense)
if you need macvlan isolation:

```
# On the MikroTik router, add a static route
# /ip route add dst-address=10.0.20.50/32 gateway=10.0.20.1
```

---

## 5. Docker Compose — Networking Configuration Gotchas

### Containers Created Before the Network Exists

**Symptom:** `docker compose up` fails with `network not found`.

**Fix — Docker Compose v2 creates networks automatically.** If you're
manually pre-creating networks, stop:

```bash
# Don't do this — Compose manages it
docker network create app-net
docker compose up  # Conflicts

# Do this instead — just define it in compose
docker compose down -v
docker compose up  # Creates network from definition
```

If you must share a network across multiple compose files, create it
once with `external: true`:

```yaml
# compose-file-a.yml
networks:
  shared-net:
    external: true

# compose-file-b.yml
networks:
  shared-net:
    external: true
```

Then create it once:

```bash
docker network create shared-net
```

### Dependency Start Order — Not Network, But Timing

**Symptom:** Service A (database) takes 30 seconds to initialize.
Service B starts immediately and fails because the database isn't
ready — even though the network works.

**Fix — add healthchecks and `depends_on` with condition:**

```yaml
services:
  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - app-net

  app:
    image: my-app:latest
    depends_on:
      db:
        condition: service_healthy
    networks:
      - app-net
```

Docker Compose v2.20+ waits for the `depends_on` condition before
starting dependent services. This is a timing problem, not a
networking problem — but the error looks exactly like one.

### Depends_on Without Condition Is Not Enough

```yaml
# This is NOT sufficient — app starts before db is ready
depends_on:
  - db

# This is correct — app waits for db healthcheck
depends_on:
  db:
    condition: service_healthy
```

---

## 6. Diagnostic Reference — Quick Command Reference

```bash
# ----- Container-Level Diagnostics -----

# Check all network interfaces inside a container
docker exec <container> ip addr show

# Check routing table
docker exec <container> ip route

# Check DNS resolution
docker exec <container> nslookup google.com

# Check firewall rules inside container (if any)
docker exec <container> iptables -L -n 2>/dev/null || echo "No iptables inside"

# Check open ports inside container
docker exec <container> ss -tlnp

# ----- Docker-Level Diagnostics -----

# List all Docker networks
docker network ls

# Inspect a network in detail
docker network inspect app-net

# Show containers attached to a network (with IPs)
docker network inspect app-net --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'

# Check container's network settings
docker inspect <container> --format '{{json .NetworkSettings.Networks}}' | jq

# Test DNS from Docker's perspective
docker run --rm --network app-net alpine nslookup db

# ----- Host-Level Diagnostics -----

# Check IP forwarding
sysctl net.ipv4.ip_forward

# Check iptables NAT rules for Docker
iptables -t nat -L -n | grep -E "DOCKER|MASQUERADE"

# Check port usage
ss -tlnp

# Trace traffic to a container
tcpdump -i docker0 -n port 8080

# ----- Full Network Audit for a Down Container -----

# Step 1: Is the container running?
docker ps -a --filter name=<name>

# Step 2: What network is it on?
docker inspect <name> --format '{{range $k,$v := .NetworkSettings.Networks}}{{printf "%s: %s\n" $k $v.IPAddress}}{{end}}'

# Step 3: Can it reach the gateway?
docker exec <name> ping -c 2 $(docker inspect <name> --format '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')

# Step 4: Can it resolve DNS?
docker exec <name> nslookup google.com

# Step 5: Can it reach the specific target?
docker exec <name> nc -zv target-service 5432

# Step 6: Restart DNS resolver inside container (without restarting it)
docker exec <name> sh -c 'echo "nameserver 1.1.1.1" > /etc/resolv.conf'
```

---

## Troubleshooting Flowchart

```
┌──────────────────────────┐
│ Container can't connect  │
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐
│ Is the container running?│
└──────────┬───────────────┘
    ├── No → docker start <name> or docker logs <name>
    │
    ▼ Yes
┌──────────────────────────┐
│ Can it reach the gateway?│
└──────────┬───────────────┘
    ├── No → Check iptables, IP forwarding, bridge interface
    │        └─ sysctl net.ipv4.ip_forward
    │        └─ iptables -t nat -L | grep MASQUERADE
    │
    ▼ Yes
┌──────────────────────────┐
│ Can it resolve DNS?      │
└──────────┬───────────────┘
    ├── No → Is it on a user-defined network?
    │        ├── No → Create one, move container
    │        └── Yes → Check Docker DNS (127.0.0.11)
    │                   └── Override with --dns
    │
    ▼ Yes
┌──────────────────────────┐
│ Can it reach the target  │
│ service by IP?           │
└──────────┬───────────────┘
    ├── No → Firewall between containers?
    │        └── Check docker-proxy, iptables DOCKER-USER
    │        └── Check container's exposed ports
    │
    ▼ Yes
┌──────────────────────────┐
│ Can it reach by name?    │
└──────────┬───────────────┘
    ├── No → Same user-defined network?
    │        ├── No → Attach to same network
    │        └── Yes → Check docker DNS resolution
    │                   └── docker compose restart
    │
    ▼ Yes
 The network works. Check the application logs.
```

---

## Summary

Docker networking failures are frustrating but follow predictable
patterns. When a container can't connect:

1. **Run netshoot** in the same namespace — `docker run -it --rm
   --net container:<name> nicolaka/netshoot`
2. **Check the network type** — user-defined bridge or default?
   Use `docker inspect <name>` to confirm.
3. **Verify DNS resolution** — `nslookup` inside the container.
   127.0.0.11 means Docker's resolver is active. Anything else
   means it inherited the host's network.
4. **Check port conflicts** — `ss -tlnp | grep <port>` on the
   host. One port, one process.
5. **Test by IP first** — if IP works but name doesn't, it's DNS.
   If neither works, it's routing, firewalls, or the network driver.
6. **Use user-defined networks** for all compose files — default
   bridge lacks DNS-based service discovery.
7. **Add healthchecks with depends_on conditions** — many
   "networking" errors are actually race conditions at startup.
8. **Separate reverse proxy ports** — let Traefik/NGINX bind to
   80/443. Your services expose unprivileged ports internally.

The diagnostic skill that separates experienced homelab operators
from beginners isn't knowing all the answers — it's knowing the
right three commands to run next.
