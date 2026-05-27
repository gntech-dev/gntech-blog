---
title: "Docker Swarm Homelab — Single-Node Orchestration with Compose to Swarm"
description: "Deploy Docker Swarm in single-node mode for your homelab — initialize the cluster, deploy stacks from Compose files, add Portainer for management, and handle persistent storage via NFS."
date: 2026-05-27T14:30:00Z
tags:
  - docker
  - swarm
  - orchestration
  - homelab
  - devops
keywords:
  - Docker Swarm single-node homelab deployment
  - Docker Compose to Swarm stack migration guide
  - Docker Swarm portainer management interface
  - Docker Swarm persistent storage NFS homelab
  - Docker Swarm Traefik reverse proxy labels
  - Docker Swarm vs Docker Compose homelab orchestration
  - Docker Swarm Prometheus monitoring Docker metrics
summary: "Deploy Docker Swarm in single-node mode for orchestration in your homelab — initialize the cluster, convert Compose files to stacks, deploy Portainer and Traefik, and manage persistent storage with NFS."
canonical: "https://gntech.dev/posts/docker-swarm-homelab-single-node-orchestration/"
---

If you already run Docker Compose on a single Proxmox LXC or
bare-metal Linux host, you have a solid container setup. But Compose
leaves gaps: containers run until they crash, there is no built-in
health-based reconciliation, and rolling out a new version means
manual `docker compose up -d` with a brief window of downtime.

Docker Swarm fills those gaps with zero additional dependencies.
It is built into Docker Engine and turns your single host into a
one-node cluster with declarative reconciliation, rolling updates,
automatic restart on failure, and built-in service discovery. Best
of all, you keep the same compose file format — just add a deploy
section and run `docker stack deploy` instead of `docker compose up`.

This guide walks through initialising a single-node Swarm, converting
Compose files to stacks, deploying Traefik and Portainer as Swarm
services, managing persistent storage, and the day 2 operations you
need for a production homelab.

---

## Why Docker Swarm for a Single-Node Homelab

The common objection: "Swarm is for multi-node clusters. I have one
machine." The answer: Swarm's orchestration engine gives you
infrastructure-level reliability on that one machine that Compose
simply does not provide.

| Capability | Docker Compose | Docker Swarm |
|---|---|---|
| Desired-state reconciliation | Manual up/restart | Automatic |
| Failure recovery | Stays stopped | Restarts with backoff |
| Rolling updates | Manual | Declarative, configurable |
| Rollback on failure | Manual | Automatic on failure detection |
| Service scaling | Scale with up | `deploy.replicas` |
| Built-in DNS/service discovery | No | Per-service A records |

For a homelab running critical services — DNS, reverse proxy, Git
server, monitoring — Swarm's automatic reconciliation is the
difference between "woke up and found Immich was down since 3 AM"
and waking up to a notification that the service restarted and is
healthy again.

## Prerequisites for Docker Swarm

- **Docker Engine 24+** — Swarm mode is shipped with the engine, no extra package
- **Docker Compose v2** (optional, for local testing before deploying as stack)
- **NFS server** or adequate local disk for persistent volumes
- **Port 2377/tcp** open (Swarm manager communication) — only needed if you ever add nodes
- **Ports 7946/tcp+udp** and **4789/udp** for overlay networking (safe to leave closed on single-node, but opened for future nodes)

Verify your Docker Engine supports swarm mode:

```bash
docker info | grep -i swarm
```

Output on a Swarm-enabled host (even if not in Swarm mode):

```
Swarm: inactive
```

## Initialise the Swarm on Your Homelab Host

Pull the trigger:

```bash
docker swarm init --advertise-addr 10.0.20.30
```

Replace `10.0.20.30` with your homelab server's LAN IP. On a
single-node setup, this IP only matters for the manager election —
no other nodes need to reach it unless you expand later.

Output:

```
Swarm initialized: current node (abc123def456) is now a manager.

To add a worker to this swarm, run the following command:

    docker swarm join --token SWMTKN-1-xxxxx 10.0.20.30:2377

To add a manager, run 'docker swarm join-token manager' and follow the instructions.
```

Verify the cluster state:

```bash
docker node ls
```

```
ID                            HOSTNAME   STATUS    AVAILABILITY   MANAGER STATUS   ENGINE VERSION
abc123def456 *                srv1       Ready     Active         Reachable        27.4.1
```

On a single-node homelab, the manager also runs workloads. No need
to drain the manager — you are not adding worker nodes.

## Deploy Your First Swarm Service

A quick smoke test to confirm Swarm is working:

```bash
docker service create \
  --name whoami \
  --publish 8080:80 \
  traefik/whoami
```

Then scale it to two replicas:

```bash
docker service scale whoami=2
docker service ls
docker service ps whoami
```

Access `http://10.0.20.30:8080` and refresh — each request hits a
different replica container. Swarm's internal load balancer round-robins
across them.

Clean up:

```bash
docker service rm whoami
```

## Convert a Docker Compose File to a Swarm Stack

This is the core migration: turning your existing `docker-compose.yml`
into a `docker-stack.yml` that `docker stack deploy` can consume.

### Key Differences Between Compose and Stack

**1. Version field is optional.** Modern Docker (24+) accepts stack
files without `version:`. Omit it.

**2. Use `deploy:` instead of direct resource fields.**

```yaml
services:
  app:
    image: nginx:alpine
    deploy:
      replicas: 2
      update_config:
        order: start-first
        parallelism: 1
        delay: 10s
        failure_action: rollback
      restart_policy:
        condition: any
        delay: 5s
        max_attempts: 3
      resources:
        limits:
          cpus: "0.5"
          memory: 256M
        reservations:
          cpus: "0.25"
          memory: 128M
```

**3. Networks must exist or be declared as overlay.**

```yaml
networks:
  traefik-public:
    driver: overlay
    attachable: true
```

`attachable: true` allows standalone containers (e.g., debugging tools)
to connect to the overlay network.

**4. Volumes work the same way for single-node.**

Named volumes like `postgres_data:` resolve to the local Docker
volume store. For multi-node, you would use NFS, but on a single node,
local bind mounts and named volumes are fine.

### Full Example: Static Site with Traefik

Here is a complete `docker-stack.yml` that deploys an nginx static
site behind Traefik:

```yaml
services:
  nginx:
    image: nginx:alpine
    deploy:
      replicas: 2
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.nginx.rule=Host(`static.gntech.dev`)"
        - "traefik.http.routers.nginx.entrypoints=websecure"
        - "traefik.http.services.nginx.loadbalancer.server.port=80"
    volumes:
      - ./static-site:/usr/share/nginx/html:ro
    networks:
      - traefik-public

networks:
  traefik-public:
    name: traefik-public
    driver: overlay
    attachable: true
```

Deploy with:

```bash
docker stack deploy -c docker-stack.yml static-site
```

Note the `traefik.http.services.<name>.loadbalancer.server.port` label.
In Swarm mode, Traefik needs an explicit port declaration — it cannot
inspect container ports the same way it does on Compose.

## Deploy Traefik as a Swarm Service

Traefik must run in Swarm mode to work with stack-deployed services.
Here is the Traefik stack definition:

```yaml
services:
  traefik:
    image: traefik:v3.3
    command:
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@gntech.dev"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-le:/letsencrypt
    networks:
      - traefik-public
    deploy:
      placement:
        constraints:
          - node.role == manager
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.dashboard.rule=Host(`traefik.gntech.dev`)"
        - "traefik.http.routers.dashboard.service=api@internal"
        - "traefik.http.routers.dashboard.middlewares=auth"
        - "traefik.http.middlewares.auth.basicauth.users=admin:$$apr1$$xxxxxxxxx"

volumes:
  traefik-le:

networks:
  traefik-public:
    external: true
    name: traefik-public
```

Key points:
- `mode: host` for ports 80 and 443 — bypasses Swarm's routing mesh
  for direct host-level port binding (required for Let's Encrypt
  HTTP-01 challenges).
- `node.role == manager` constraint ensures Traefik stays on the
  manager node.
- `traefik.http.services.dashboard.service=api@internal` exposes
  the Traefik dashboard at the `/api` endpoint.
- The network `traefik-public` must be `external: true` because it
  was created before the stack.

Create the network and deploy:

```bash
docker network create --driver=overlay --attachable traefik-public
docker stack deploy -c traefik-stack.yml traefik
```

## Deploy Portainer for Visual Swarm Management

Portainer gives you a web UI for managing your Swarm services without
reaching for the terminal every time. On a single-node setup, deploy
both the Portainer Agent and Server:

```yaml
services:
  agent:
    image: portainer/agent:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
    networks:
      - agent-net
    deploy:
      mode: global
      placement:
        constraints:
          - node.platform.os == linux

  portainer:
    image: portainer/portainer-ce:latest
    command: -H tcp://tasks.agent:9001 --tlsskipverify
    volumes:
      - portainer-data:/data
    networks:
      - agent-net
      - traefik-public
    deploy:
      placement:
        constraints:
          - node.role == manager
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.portainer.rule=Host(`portainer.gntech.dev`)"
        - "traefik.http.routers.portainer.entrypoints=websecure"
        - "traefik.http.services.portainer.loadbalancer.server.port=9000"

volumes:
  portainer-data:

networks:
  agent-net:
    driver: overlay
    attachable: true
  traefik-public:
    external: true
```

Deploy:

```bash
docker stack deploy -c portainer-stack.yml portainer
```

Access Portainer at `https://portainer.gntech.dev` — you can inspect
running services, view logs, scale replicas, and deploy new stacks
from the web UI.

## Persistent Storage in Single-Node Swarm

Named volumes and bind mounts work identically to Docker Compose on
a single host. If you ever plan to expand to multiple nodes, move
persistent data to an NFS share.

Create an NFS-backed volume:

```bash
docker volume create \
  --driver local \
  --opt type=nfs \
  --opt o=addr=10.0.20.50,rw,nfsvers=4 \
  --opt device=:/export/docker/postgres \
  postgres_data
```

Use it in a stack:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    deploy:
      replicas: 1

volumes:
  postgres_data:
    external: true
```

The volume is created externally (with `docker volume create`) so it
survives stack removal. The stack references it with `external: true`.

## Monitoring the Swarm

Deploy a monitoring stack to keep visibility into your Swarm services:

```yaml
services:
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    command:
      - "--docker_only=true"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    networks:
      - monitoring
    deploy:
      mode: global

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    networks:
      - monitoring
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: changeme
    volumes:
      - grafana-data:/var/lib/grafana
    networks:
      - monitoring
      - traefik-public
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.grafana.rule=Host(`grafana.gntech.dev`)"
        - "traefik.http.routers.grafana.entrypoints=websecure"
        - "traefik.http.services.grafana.loadbalancer.server.port=3000"

volumes:
  prometheus-data:
  grafana-data:

networks:
  monitoring:
    driver: overlay
    attachable: true
  traefik-public:
    external: true
```

## Day 2 Operations for Your Swarm Homelab

**Rolling update:**

```bash
docker service update --image nginx:1.27 nginx-stack_nginx
```

**Rollback if something goes wrong:**

```bash
docker service update --rollback nginx-stack_nginx
```

**View logs across all replicas:**

```bash
docker service logs --tail 50 nginx-stack_nginx
```

**Inspect service state:**

```bash
docker service ps nginx-stack_nginx
```

**Scale a service:**

```bash
docker service scale nginx-stack_nginx=3
```

**Clean up a stack entirely:**

```bash
docker stack rm static-site
```

**Drain the node for maintenance** (only relevant in multi-node,
but noted for completeness):

```bash
docker node update --availability drain srv1
```

## Why This Beats Multi-Node Overkill

A single-node Docker Swarm gives you 90% of Kubernetes-style
orchestration benefits with zero networking complexity:

- Declarative service definitions that self-heal
- Rolling updates with automatic rollback
- Built-in service discovery via DNS
- Traefik integration with zero extra service mesh
- Portainer for visual management

If you ever outgrow one host, adding a second is as simple as
running `docker swarm join` on it. Your stacks and networks
stay the same — just add more replicas.

For every Compose service you care about, try the Swarm stack
alternative. The file diff is small, the operational improvement
is immediate, and you keep the same Docker skills you already
have.

---

*Related reading: [Docker Compose patterns for homelab](/posts/docker-compose-patterns/),
[Docker Trivy vulnerability scanning](/posts/docker-trivy-vulnerability-scanning/),
[Traefik middleware security hardening](/posts/traefik-middleware-security-hardening/).*
