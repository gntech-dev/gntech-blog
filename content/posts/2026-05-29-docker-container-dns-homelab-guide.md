---
title: "Docker Container DNS Guide — Custom DNS and Service Discovery for Homelab"
description: "Configure Docker container DNS resolution for homelab — custom DNS servers like Pi-hole, service discovery with Compose, DNS aliases, daemon.json settings, and troubleshooting container DNS failures."
date: 2026-05-29T18:30:00Z
tags:
  - docker
  - networking
  - homelab
  - linux
keywords:
  - Docker container DNS resolution homelab guide
  - Docker custom DNS server configuration Pi-hole
  - Docker Compose DNS service discovery network aliases
  - Docker internal DNS resolution container-to-container
  - Docker DNS troubleshooting container network issues
  - Docker daemon.json global DNS configuration
  - Docker embedded DNS resolver 127.0.0.11 setup
summary: "Master Docker container DNS for your homelab — configure custom resolvers like Pi-hole, enable internal service discovery with Docker Compose network aliases, set global DNS via daemon.json, and troubleshoot container DNS failures step by step."
canonical: "https://blog.gntech.me/posts/docker-container-dns-homelab-guide/"
---

You set up Pi-hole on your homelab network. Ad blocking works on every
device — phones, laptops, even the IoT lightbulbs. But your Docker
containers? They're hitting Google's 8.8.8.8 directly, bypassing all
your carefully configured blocklists and internal hostnames.

This is the default Docker DNS behavior, and it breaks two things:
external ad-blocking and internal service discovery. Containers can't
resolve `pihole.internal` or `router.homelab` because they're not
talking to your DNS infrastructure. This guide covers every level of
Docker DNS configuration — from a quick `--dns` flag to global
`daemon.json` settings, Compose service discovery, and troubleshooting
when things go wrong.

## Understanding Docker DNS Resolution Inside Containers

Every Docker container gets a `/etc/resolv.conf` file. By default,
Docker copies the host's DNS configuration. If your Proxmox LXC or VM
uses 8.8.8.8 via systemd-resolved, that's what your containers use.

When you connect a container to a user-defined bridge network (the
kind you create with `docker network create` or define in Compose),
Docker injects its own embedded DNS resolver at `127.0.0.11`. This
resolver handles **container-to-container name resolution** — service
names in Compose, container names, and network aliases. It does
**not** handle external domain resolution. External queries still go
to whatever DNS servers are configured in the container's
`/etc/resolv.conf`.

```
Container /etc/resolv.conf
  ├── 127.0.0.11 → Docker embedded resolver
  │   └── Resolves: service-name, container-name, network-alias
  └── 10.0.20.5  → Custom DNS (Pi-hole)
      └── Resolves: google.com, pihole.internal, *.homelab
```

The embedded resolver listens on 127.0.0.11 inside every container on a
user-defined network. For external queries, it acts as a forwarder to
whatever upstream DNS servers are configured.

## Configuring DNS Per Container and Per Service

The simplest approach is setting DNS per container. This works for
individual services or testing.

### Docker CLI

```bash
docker run --dns 10.0.20.5 --dns 10.0.20.6 nginx
```

### Docker Compose

```yaml
services:
  web-app:
    image: nginx
    dns:
      - 10.0.20.5
      - 10.0.20.6
    dns_search: homelab.internal
```

The `dns_search` directive adds a search domain. When you ping
`router`, Docker appends `.homelab.internal` and tries
`router.homelab.internal` automatically.

## Setting Global DNS via daemon.json

Per-container DNS is tedious when you have twenty services. Set the
global default for all containers by editing
`/etc/docker/daemon.json`:

```json
{
  "dns": ["10.0.20.5", "10.0.20.6"],
  "dns-opts": ["timeout:2", "attempts:3"],
  "dns-search": ["homelab.internal"]
}
```

Apply the change:

```bash
sudo systemctl restart docker
```

Every new container now uses your homelab DNS servers by default. The
`dns-opts` settings control query timeout (2 seconds) and retries
(3 attempts) before falling back — critical when a DNS server is
temporarily down.

**Important:** `daemon.json` DNS settings apply only to containers
that don't specify their own `dns:` in Compose or `--dns` on the
command line. Per-container overrides always win.

### Checking the Current daemon.json

```bash
cat /etc/docker/daemon.json
# Check if DNS is set:
docker info | grep -i dns
```

If `daemon.json` doesn't exist, create it. Docker reads this file on
startup.

## Docker Compose Service Discovery with Network Aliases

When containers need to talk to each other by name inside a Compose
stack, the embedded DNS resolver at 127.0.0.11 handles it
automatically — as long as all services share the same network.

```yaml
services:
  db:
    image: postgres:16-alpine
    networks:
      - backend
    volumes:
      - pgdata:/var/lib/postgresql/data

  app:
    image: my-app:latest
    networks:
      - backend
    depends_on:
      - db
    dns:
      - 10.0.20.5

networks:
  backend:
    driver: bridge
```

In this example, the `app` container resolves `db` to the PostgreSQL
container's IP on the `backend` network. External lookups (like
`api.example.com`) go through 10.0.20.5 (your Pi-hole).

### Network Aliases

Need to resolve a service by multiple names? Use aliases:

```yaml
services:
  redis:
    image: redis:7-alpine
    networks:
      backend:
        aliases:
          - cache
          - session-store
          - redis
```

Now any container on the `backend` network can resolve `cache`,
`session-store`, or `redis` — all pointing to the same Redis instance.

### The Legacy Links Approach

Docker links (`links:`) also provide name resolution but are
deprecated. User-defined bridge networks with aliases are the
modern replacement:

```yaml
# Legacy — avoid
services:
  app:
    links:
      - db:database

# Modern
services:
  app:
    networks:
      - backend
```

## Using Extra Hosts for Static DNS Entries

For hostnames that don't change, `extra_hosts` adds static entries to
the container's `/etc/hosts`:

```yaml
services:
  app:
    extra_hosts:
      - "pihole.internal:10.0.20.5"
      - "router.homelab:10.0.20.1"
      - "proxmox.srv1:10.0.20.30"
```

This is equivalent to `--add-host` on `docker run` and is useful for:
- Hostnames not served by your DNS server
- Overriding DNS for testing
- Referencing hosts on different subnets

Use `extra_hosts` when you need static resolution and custom DNS via
`dns:` when you want dynamic DNS resolution through your infrastructure.

## Troubleshooting Container DNS Issues

DNS problems in Docker are frustrating because the failure looks like
a network issue. Here's a systematic approach.

### Step 1: Check Resolv Conf

```bash
docker exec -it container-name cat /etc/resolv.conf
```

Expected output shows 127.0.0.11 (embedded resolver) and your custom
DNS servers. If you see only 8.8.8.8, your daemon.json or per-service
DNS setting isn't applied.

### Step 2: Test Resolution

```bash
docker exec -it container-name nslookup google.com
docker exec -it container-name dig +short service-name
```

If `nslookup google.com` fails but `ping 8.8.8.8` works, it's a DNS
issue, not a network issue.

### Step 3: Check Embedded Resolver

```bash
docker exec -it container-name nslookup db 127.0.0.11
```

If service names via the embedded resolver (127.0.0.11) fail but
external resolution works, check that all services are on the same
user-defined network. The default bridge network (`docker0`) does not
support DNS-based service discovery.

### Common Issues and Fixes

**systemd-resolved interference**
On Ubuntu/Debian hosts, systemd-resolved creates a resolv.conf
symlink. Docker may follow the symlink instead of the actual
DNS configuration:

```bash
ls -la /etc/resolv.conf
# If symlinked to /run/systemd/resolve/stub-resolv.conf:
# Point Docker daemon to the resolved configuration directly:
echo "{\"dns\":[\"10.0.20.5\"]}" | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

**DNS breaks after network change**
When you disconnect and reconnect a network, the embedded resolver's
entry in resolv.conf can disappear:

```bash
docker network disconnect backend container-name
docker network connect backend container-name
# Container may lose 127.0.0.11 entry
```

Fix: restart the container or use `docker compose down && docker compose up`.

**Container can't reach Pi-hole**
Verify network connectivity between the container and your DNS server:

```bash
docker exec -it container-name ping 10.0.20.5
```

If ping fails, the container is on an isolated network and can't reach
your homelab DNS server. Ensure the container's network has a route to
the DNS server, or use the host's Docker bridge.

### Debugging with Tcpdump

```bash
# On the Docker host:
sudo tcpdump -i docker0 port 53
# On the Proxmox host:
sudo tcpdump -i vmbr0 port 53 and host 10.0.20.5
```

Watch for DNS queries leaving the Docker bridge toward your Pi-hole.
If queries hit the host but not Pi-hole, a firewall rule may be
blocking UDP 53 between Docker networks.

## Full Working Example: Web Stack with Homelab DNS

Here's a complete docker-compose.yml that ties everything together:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal
    environment:
      POSTGRES_DB: appdb
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      internal:
        aliases:
          - cache
          - session-store

  app:
    image: nginx:alpine
    restart: unless-stopped
    networks:
      - internal
      - proxy
    depends_on:
      - postgres
      - redis
    dns:
      - 10.0.20.5
    dns_search: homelab.internal
    extra_hosts:
      - "pihole.internal:10.0.20.5"
      - "api.example.com:203.0.113.50"

  traefik:
    image: traefik:v3.3
    restart: unless-stopped
    networks:
      - proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro

networks:
  internal:
    driver: bridge
    internal: true
  proxy:
    driver: bridge

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

Key points:
- `postgres` and `redis` are on the `internal` network — no external
  DNS needed, the embedded resolver handles service discovery.
- `redis` has aliases (`cache`, `session-store`) for flexible references.
- `app` uses 10.0.20.5 (Pi-hole) for external DNS, plus `extra_hosts`
  for static entries that bypass DNS entirely.
- `traefik` is on the `proxy` network only — no custom DNS needed,
  default daemon.json settings apply.
- Setting `internal: true` on the `internal` network isolates it from
  external access but still supports embedded DNS resolution between
  containers.

## Best Practices Summary

1. **Set global DNS in daemon.json** — point all containers to your
   Pi-hole or Unbound resolver by default. Override per-service when
   specific containers need different DNS.

2. **Use user-defined networks for service discovery** — the default
   bridge (`docker0`) does not support DNS-based name resolution.
   Always define named networks in Compose.

3. **Docker embedded resolver for service names, custom DNS for
   external domains** — the 127.0.0.11 resolver handles
   container-to-container discovery. Configure upstream DNS for
   everything else.

4. **Use network aliases instead of links** — aliases are more
   flexible and support multiple names per service without deprecated
   syntax.

5. **Add extra_hosts for critical infrastructure** — hostnames like
   your Pi-hole, router, or Proxmox host benefit from static entries
   that work even if DNS is temporarily down.

6. **Test DNS isolation** — when debugging, always check whether
   failure is in the embedded resolver (internal) or the upstream
   resolver (external). Use `nslookup` with explicit server IPs to
   narrow it down.

Docker DNS configuration is one of those things you set once and
forget about — until a container silently bypasses your ad-blocking
DNS server. Start with a sensible `daemon.json` default, use
user-defined networks with aliases for service discovery, and keep
`extra_hosts` in your back pocket for static entries that must
survive any DNS outage.
