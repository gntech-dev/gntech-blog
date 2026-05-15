---
title: "Docker Compose Networking — Multi-Stack Bridge, DNS, and Cross-Story Communication"
description: "Master Docker Compose networking patterns for multi-stack homelabs — bridge networks, DNS resolution, external network sharing, and container-to-container communication with real Compose examples."
date: 2026-05-15T11:00:00-04:00
tags:
  - docker
  - networking
  - docker-compose
  - homelab
  - linux
keywords:
  - Docker Compose networking patterns
  - multi-stack Docker communication
  - Docker bridge network DNS resolution
  - external network Docker Compose
  - container service discovery Docker
  - Docker network isolation
  - cross-compose container communication
summary: "Learn how Docker Compose networking really works — bridge networks, DNS-based service discovery, cross-stack communication, and real-world network isolation patterns for homelab deployments."
canonical: "https://gntech.dev/posts/docker-compose-networking-patterns/"
---

Every homelab running Docker Compose eventually runs into the same
problem: you have one `docker-compose.yml` for your media stack, another
for your monitoring stack, and a third for your reverse proxy. They all
need to talk to each other, but Compose creates separate networks by
default.

This post covers the networking patterns you need to make multiple
Docker Compose stacks communicate reliably — bridge networks, DNS-based
service discovery, external network sharing, and multi-network
containers — with real configurations you can drop into your homelab
today.

---

## How Compose Networking Works (Default Behavior)

When you run `docker compose up`, Compose automatically creates a
default bridge network named `<project>_default`. Every service in that
Compose file joins this network. Services can reach each other by their
service name, which Compose resolves via embedded DNS.

```yaml
# docker-compose.yml
services:
  web:
    image: nginx
    # Reachable by other services as "web"
  db:
    image: postgres:16
    # Reachable by other services as "db"
```

App connects to `db:5432` — no IPs needed. This is the default bridge
network, and it Just Works for a single Compose file.

The problem starts when you have two Compose stacks:

```yaml
# stack-a/docker-compose.yml
services:
  app:
    image: my-app

# stack-b/docker-compose.yml
services:
  app:
    image: my-other-app
```

These two `app` services are on completely separate networks. `stack-a`
cannot resolve `app` from `stack-b`, and `stack-b` cannot resolve `app`
from `stack-a`. No DNS, no connectivity, nothing.

---

## Pattern 1: External Networks for Cross-Stack Communication

The cleanest way to connect multiple Compose stacks is to define a
shared external network that every stack joins. This is the pattern
used by every homelab reverse proxy setup.

First, create the shared network:

```bash
docker network create shared-net
```

Then each Compose file joins it:

```yaml
# traefik/docker-compose.yml
networks:
  proxy-net:
    name: proxy-net
    external: true    # Don't create it — use the existing one

services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    networks:
      - proxy-net
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command:
      - "--providers.docker=true"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
```

```yaml
# nextcloud/docker-compose.yml
networks:
  proxy-net:
    name: proxy-net
    external: true

services:
  nextcloud:
    image: nextcloud:stable
    container_name: nextcloud
    networks:
      - proxy-net
    # Traefik can reach this as "nextcloud:80"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.nextcloud.rule=Host(`cloud.example.com`)"
      - "traefik.http.services.nextcloud.loadbalancer.server.port=80"
```

```yaml
# immich/docker-compose.yml
networks:
  proxy-net:
    name: proxy-net
    external: true

services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:release
    container_name: immich
    networks:
      - proxy-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.immich.rule=Host(`photos.example.com`)"
```

DNS resolves container names — Traefik discovers `nextcloud:80` and
`immich:2283` through the shared `proxy-net`. No manual IPs. No
Compose-level dependencies across stacks.

---

## Pattern 2: Multi-Network Containers (The Traefik Sandwich)

A more advanced pattern: a single container belongs to multiple networks
simultaneously. Traefik is the classic example — it needs to be on both
the public network (to accept inbound traffic) and on every internal
network (to reach backend services).

```yaml
# traefik/docker-compose.yml
networks:
  public-net:
    name: public-net
    external: true
  internal-apps-net:
    name: internal-apps-net
    external: true
  monitoring-net:
    name: monitoring-net
    external: true

services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    networks:
      - public-net
      - internal-apps-net
      - monitoring-net
    ports:
      - target: 443
        published: 443
        protocol: tcp
```

Traefik sees every service on all three networks. Backend services only
need to be on their respective network — they never expose ports to the
host. This is defense-in-depth: even if a service in `internal-apps-net`
is compromised, it cannot reach services on `monitoring-net`.

```yaml
# monitoring/docker-compose.yml
networks:
  monitoring-net:
    name: monitoring-net
    external: true

services:
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    networks:
      - monitoring-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`monitor.example.com`)"
```

No port mapping on Grafana — it's only reachable through Traefik on the
shared `monitoring-net`. A container in `internal-apps-net` cannot touch
it.

---

## Pattern 3: Internal Networks for Database Isolation

Databases should never be exposed to external networks — not even to
the shared proxy network. The pattern: create a separate internal
network, put only the database and its consumer on it.

```yaml
# nextcloud/docker-compose.yml
networks:
  proxy-net:
    name: proxy-net
    external: true
  db-net:
    name: nextcloud-db-net
    internal: true    # No external connectivity — containers can't reach outside

services:
  nextcloud:
    image: nextcloud:stable
    container_name: nextcloud
    networks:
      - proxy-net
      - db-net

  postgres:
    image: postgres:16-alpine
    container_name: nextcloud-db
    networks:
      - db-net    # Only on the internal network
    environment:
      POSTGRES_DB: nextcloud
      POSTGRES_USER: nextcloud
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U nextcloud"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

The database is unreachable from Traefik, unreachable from the internet,
unreachable from any other Compose stack. Only `nextcloud` can talk to
it. The `internal: true` flag on the network means the database cannot
even initiate outbound connections.

For PostgreSQL and MySQL, add `--network=nextcloud-db-net` to your
backup container:

```yaml
  pg-backup:
    image: prodrigestivill/postgres-backup-local:16-alpine
    container_name: nextcloud-db-backup
    networks:
      - db-net
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_DB: nextcloud
      POSTGRES_USER: nextcloud
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      SCHEDULE: "@daily"
    volumes:
      - ./backups:/backups
```

Only the database, the app, and the backup container exist on this
network. Nothing else.

---

## Pattern 4: Default Networks with Custom Names and Subnets

Sometimes you want more control than Compose's auto-generated
`<project>_default`. Define the default network explicitly:

```yaml
# docker-compose.yml
networks:
  default:
    name: media-stack
    driver: bridge
    ipam:
      config:
        - subnet: "10.30.0.0/24"
          gateway: "10.30.0.1"

services:
  plex:
    image: plexinc/pms-docker
    container_name: plex
    networks:
      - default
  sabnzbd:
    image: lscr.io/linuxserver/sabnzbd:latest
    container_name: sabnzbd
    networks:
      - default
```

Benefits:
- Predictable subnet — useful if your firewall rules reference Docker IPs
- Named network — easier to reference as `external: true` from other stacks
- No collision with other Compose defaults (all named `media-stack` instead
  of `project_a_default` vs `project_b_default`)

Check what IP a container got:

```bash
docker inspect plex -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
# 10.30.0.2
```

---

## Pattern 5: Aliases and Container Names for Stable DNS

Compose services get DNS entries by their service name. But if you need
a service to respond on multiple DNS names, use `aliases`:

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: app-database
    networks:
      db-net:
        aliases:
          - postgres
          - database
          - primary-db
```

Services on `db-net` can reach this container as `postgres`, `database`,
`primary-db`, or `app-database` (the container name). This is useful
when migrating — you can run both old and new databases temporarily
with the same DNS aliases.

Container names also work as DNS entries within the same network:

```yaml
services:
  app:
    image: my-app
    container_name: my-app-v2
    # Reachable as "my-app-v2" on all networks it joins
```

---

## Pattern 6: The Database URI with Docker DNS

When configuring apps to connect to databases, use the service name as
the hostname:

```yaml
services:
  app:
    image: my-app
    environment:
      DATABASE_URL: "postgres://user:password@postgres:5432/appdb"
      REDIS_URL: "redis://redis:6379"
      RABBITMQ_URL: "amqp://rabbitmq:5672"
```

Docker DNS resolves `postgres`, `redis`, and `rabbitmq` to the correct
container IPs on the shared network. No config files, no IP hardcoding,
no round-robin confusion.

If the database fails and restarts, Docker re-issues the same DNS name
with the new IP. Apps reconnect automatically as long as they have
connection retry logic.

---

## Pattern 7: Depends On for Network Startup Ordering

Services on the same network still need startup ordering. Use
`depends_on` with health checks for production services:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser"]
      interval: 5s
      timeout: 3s
      retries: 10

  app:
    image: my-app
    depends_on:
      postgres:
        condition: service_healthy
    # DNS will resolve postgres once it's healthy
```

Without `condition: service_healthy`, `depends_on` only waits for the
container to start, not for the database to accept connections. The
app starts, connects to `postgres:5432`, Docker DNS resolves it, but
PostgreSQL isn't ready yet — connection refused.

With health checks + `condition: service_healthy`, Compose waits for
`pg_isready` to succeed before starting the app. The network is
available, DNS resolves, and the database is listening.

---

## Pattern 8: Connect Running Containers to Networks

Sometimes you need to connect an already-running container to a network
without restarting it. Useful for debugging or temporary access:

```bash
# Connect a container to a network
docker network connect shared-net my-container

# Disconnect from a network
docker network disconnect shared-net my-container

# Inspect all networks a container is on
docker inspect my-container -f \
  '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

This is a runtime operation — the container keeps running. Use it when
you need to temporarily add a debugging container to a network:

```bash
# Spin up a diagnostic container on a running stack's network
docker run -it --rm --network media-stack nicolaka/netshoot \
  sh -c "nslookup plex && curl -s plex:32400/web/index.html | head -5"
```

The `netshoot` image is purpose-built for Docker network debugging —
it includes `dig`, `nslookup`, `curl`, `tcpdump`, `ping`, `mtr`, and
`netstat`.

---

## Pattern 9: Network Troubleshooting Toolkit

When containers can't reach each other, here's the diagnostic sequence:

**Step 1 — Verify network exists:**
```bash
docker network ls
docker network inspect proxy-net
```

**Step 2 — Check which containers are on each network:**
```bash
docker network inspect proxy-net -f '{{range .Containers}}{{.Name}} {{end}}'
```

**Step 3 — Test DNS resolution from inside a container:**
```bash
docker run --rm --network proxy-net nicolaka/netshoot \
  dig +short nextcloud
# Should return the container IP
```

**Step 4 — Test TCP connectivity:**
```bash
docker run --rm --network proxy-net nicolaka/netshoot \
  sh -c "nc -zv nextcloud 80"
# Should return: nc: nextcloud (10.20.0.3:80) open
```

**Step 5 — Check container-level network config:**
```bash
docker inspect nextcloud -f '{{json .NetworkSettings.Networks}}' | jq .
```

**Common failures:**

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| DNS resolution fails | Container not on the same network | Add network to `networks:` in Compose |
| Connection refused | Service not listening on that interface | Check `bind 0.0.0.0` in app config |
| Connection timeout | Firewall blocking the port | Check `iptables -L DOCKER` on host |
| Can't reach by hostname | Missing `container_name` in Compose | Use service name instead |
| Works on host but not in container | Port exposed on `127.0.0.1` | Expose on `0.0.0.0` in the app |

---

## Real-World Homelab Network Topology

Here's how these patterns compose into a full homelab:

```
                                     Internet
                                        │
                                    ┌───┴───┐
                                    │  WAN  │
                                    └───┬───┘
                                        │
                                    ┌───┴───┐      public-net
                                    │Traefik│◄──── (443/80)
                                    └───┬───┘
                                        │
              ┌─────────────────────────┼─────────────────────┐
              │                         │                      │
        ┌─────┴─────┐           ┌──────┴──────┐       ┌──────┴──────┐
        │ nextcloud │           │  immich     │       │   grafana   │
        │  :80      │           │  :2283      │       │   :3000     │
        └─────┬─────┘           └──────┬──────┘       └──────┬──────┘
              │                        │                     │
        ┌─────┴─────┐           ┌──────┴──────┐       ┌──────┴──────┐
        │ postgres  │           │  postgres   │       │  prometheus │
        │ (internal)│           │ (internal)  │       │ (monitoring)│
        └───────────┘           └─────────────┘       └─────────────┘
```

**Networks:**

| Network | Type | Contains | External Reach |
|---------|------|----------|----------------|
| `public-net` | bridge | Traefik | Internet (80, 443) |
| `media-net` | bridge | Sonarr, Radarr, Plex | LAN only |
| `monitoring-net` | bridge | Grafana, Prometheus | Traefik only |
| `nextcloud-db-net` | internal | Nextcloud + Postgres | None |
| `immich-db-net` | internal | Immich + Postgres | None |

**Compose file structure:**

```text
~/docker/
├── traefik/
│   └── docker-compose.yml       # public-net + monitoring-net + media-net
├── nextcloud/
│   └── docker-compose.yml       # public-net + nextcloud-db-net
├── immich/
│   └── docker-compose.yml       # public-net + immich-db-net
├── monitoring/
│   └── docker-compose.yml       # monitoring-net only
└── media/
    └── docker-compose.yml       # media-net only
```

Every stack is its own Compose file. No single `docker-compose.yml`
with 30 services. Each stack can be updated, restarted, or torn down
independently.

---

## The One-Liner: Creating All Networks

Bootstrap all the shared networks before deploying:

```bash
for net in public-net monitoring-net media-net nextcloud-db-net immich-db-net; do
  docker network create "$net" 2>/dev/null || echo "Network $net already exists"
done
```

Then deploy each stack independently:

```bash
cd ~/docker/traefik && docker compose up -d
cd ~/docker/nextcloud && docker compose up -d
cd ~/docker/immich && docker compose up -d
cd ~/docker/monitoring && docker compose up -d
cd ~/docker/media && docker compose up -d
```

Want to rebuild monitoring without touching the media stack?

```bash
cd ~/docker/monitoring && docker compose down -v && docker compose up -d
```

Everything else keeps running. That's the point of multi-stack
networking.

---

## Summary

Docker Compose networking is deceptively simple until you cross stack
boundaries. The core patterns are straightforward:

1. **External networks** — create once, reference from every Compose file
2. **Multi-network containers** — put Traefik on every network that needs it
3. **Internal networks** — lock databases behind `internal: true`
4. **Service name DNS** — use container names, not IPs, everywhere
5. **Health checks** — wait for `service_healthy` before connecting

These five patterns cover 90% of homelab networking needs. No service
mesh, no Kubernetes, no overlay networks. Just well-planned bridge
networks with clean boundaries.
