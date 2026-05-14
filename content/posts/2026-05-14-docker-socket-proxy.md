---
title: "Docker Socket Proxy — Secure API Access Without Giving Away Root"
description: "Learn how to secure Docker socket access with Tecnativa's socket proxy — granular API permissions for Portainer, Watchtower, Traefik, and Dozzle without exposing root access to your Docker host."
date: 2026-05-14T11:00:00-04:00
tags:
  - docker
  - security
  - homelab
  - containers
  - devops
keywords:
  - docker socket proxy security
  - Tecnativa docker-socket-proxy
  - secure Docker API access
  - Portainer socket proxy
  - Watchtower socket proxy
  - protect Docker socket
  - container API permissions
summary: "Secure your Docker socket with a proxy that grants granular API permissions to Portainer, Watchtower, Traefik, and Dozzle — without exposing root-level access."
canonical: "https://gntech.dev/posts/docker-socket-proxy/"
---

Every homelab runs containers that need Docker API access. Portainer needs
it to manage containers. Watchtower needs it to restart updated images.
Traefik needs it for automatic service discovery. Dozzle needs it for
live logs.

The standard approach? Mount `/var/run/docker.sock` into each container.
That's the equivalent of giving every one of those containers `sudo root`
on your host. A compromised Portainer container doesn't just mean a broken
dashboard — it means full host compromise.

This post covers how to use [Tecnativa's docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)
to grant containers only the Docker API permissions they actually need,
with real Compose configurations for the most common homelab services.

---

## The Problem: The Docker Socket Is Root-Equivalent

The Docker socket `/var/run/docker.sock` is a Unix socket that exposes
the full Docker API without authentication. Any process that can read
and write to this socket can:

```bash
# Start a privileged container with host filesystem access
docker run -v /:/host --privileged alpine sh -c "cat /host/etc/shadow"

# Remove any container, image, volume, or network
docker system prune --all --force --volumes

# Access host processes and namespaces
docker run --pid=host alpine sh -c "ps aux"

# Pivot to host filesystem and install a backdoor
docker run -v /:/mnt --privileged alpine sh -c \
  "chroot /mnt /bin/bash -c 'useradd -G sudo attacker'"
```

A single container with socket access equals unrestricted root on the
Docker host. Most homelabs mount the socket into 3-5 containers. That's
3-5 attack surfaces, any one of which gives an attacker full control.

The standard counter-argument is "my homelab isn't exposed to the
internet." But even in a LAN-only setup, a compromised web app running
on your network can pivot to the Docker host. A malicious npm package,
a vulnerable PHP app, a Wordpress plugin — any of these can reach the
socket if the container has it mounted.

---

## The Solution: Docker Socket Proxy

The socket proxy is a lightweight HAProxy container that sits between
your services and the Docker socket. Instead of mounting the socket
directly, you mount it only into the proxy. Your services connect to
the proxy via a Docker network, and the proxy enforces which API
endpoints each service can access.

The proxy is controlled through environment variables:

```yaml
# Enable specific API access
- ALLOW_START=true       # Allow container start/stop
- ALLOW_STOP=true
- ALLOW_RESTARTS=true    # Allow container restart
- ALLOW_CREATE=true      # Allow container creation
- ALLOW_DELETE=true      # Allow container removal
- ALLOW_IMAGES=true      # Allow image management
- ALLOW_INFO=true        # Allow system info queries
- ALLOW_EVENTS=true      # Allow event streaming
- ALLOW_LOGS=true        # Allow log access
- ALLOW_EXEC=true        # Allow exec into containers
```

Each API call is checked against the enabled permissions. If a service
tries to delete containers but `ALLOW_DELETE` isn't set, the proxy
returns a 403 Forbidden.

---

## Complete Setup: Socket Proxy with Common Services

Here's a full `docker-compose.yml` that sets up the socket proxy
alongside Portainer, Watchtower, Traefik, and Dozzle — each with only
the permissions it needs.

```yaml
version: "3.8"

networks:
  proxy-net:
    name: proxy-net
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24

services:
  # --- Socket Proxy ---
  socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: socket-proxy
    restart: unless-stopped
    networks:
      - proxy-net
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      # Containers — Portainer needs these
      ALLOW_CONTAINERS: "true"     # List/inspect containers
      ALLOW_START: "true"          # Start containers
      ALLOW_STOP: "true"           # Stop containers
      ALLOW_RESTARTS: "true"       # Restart containers
      ALLOW_CREATE: "true"         # Portainer creates containers
      ALLOW_DELETE: "true"         # Remove containers
      # Images — Portainer + Watchtower need these
      ALLOW_IMAGES: "true"         # List/pull/remove images
      # System info — most services need this
      ALLOW_INFO: "true"           # Docker system info
      # Events — Watchtower needs this for live monitoring
      ALLOW_EVENTS: "true"         # Event stream
      # Logs — Dozzle needs this
      ALLOW_LOGS: "true"           # Container logs
      # Networking — Traefik needs this
      ALLOW_NETWORKS: "true"       # List networks
      # Volumes — Portainer needs this
      ALLOW_VOLUMES: "true"        # List volumes
      # Tasks / Services / Swarm — not needed in single-host setups
      ALLOW_TASKS: "false"
      ALLOW_SERVICES: "false"
      ALLOW_NODES: "false"
      ALLOW_SECRETS: "false"
      ALLOW_CONFIGS: "false"
      ALLOW_SESSION: "false"
      # Don't allow exec into running containers
      ALLOW_EXEC: "false"
      # No file system access through the proxy
      ALLOW_ATTACH: "false"

  # --- Portainer ---
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    networks:
      - proxy-net
    ports:
      - "9000:9000"
    volumes:
      - portainer_data:/data
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
    depends_on:
      - socket-proxy

  # --- Watchtower ---
  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    networks:
      - proxy-net
    environment:
      - WATCHTOWER_CLEANUP=true
      - WATCHTOWER_POLL_INTERVAL=86400
      - DOCKER_HOST=tcp://socket-proxy:2375
      - WATCHTOWER_INCLUDE_STOPPED=true
      - WATCHTOWER_REVIVE_STOPPED=false
      - WATCHTOWER_NOTIFICATIONS=shoutrrr
      - WATCHTOWER_NOTIFICATION_URL=${WATCHTOWER_NOTIFICATION_URL:-}
    volumes:
      - /etc/localtime:/etc/localtime:ro
    depends_on:
      - socket-proxy

  # --- Traefik ---
  traefik:
    image: traefik:v3.1
    container_name: traefik
    restart: unless-stopped
    networks:
      - proxy-net
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - traefik_config:/etc/traefik
      - traefik_certs:/letsencrypt
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
    command:
      # Provider: Docker via socket proxy
      - "--providers.docker=true"
      - "--providers.docker.endpoint=tcp://socket-proxy:2375"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.defaultrule=Host(`{{.Name}}.{{env \"DOMAIN\"}}`)"
      # Entrypoints
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Let's Encrypt
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=${ACME_EMAIL}"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
      # Dashboard
      - "--api.dashboard=true"
      - "--api.debug=false"
    depends_on:
      - socket-proxy

  # --- Dozzle ---
  dozzle:
    image: amir20/dozzle:latest
    container_name: dozzle
    restart: unless-stopped
    networks:
      - proxy-net
    ports:
      - "8080:8080"
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
    depends_on:
      - socket-proxy

volumes:
  portainer_data:
  traefik_config:
  traefik_certs:
```

This configuration gives each service exactly what it needs:

- **Portainer** can create, start, stop, restart, and delete containers,
  manage images, volumes, and networks — full management capability.
- **Watchtower** can list containers, pull images, and restart containers.
  It cannot delete, exec, or access volumes.
- **Traefik** can only list containers and networks — it needs to discover
  new containers and their labels. It cannot create, modify, or delete
  anything.
- **Dozzle** can only read container logs. No CRUD operations at all.

---

## Granular Permissions: What Each Service Actually Needs

Not every service needs the same level of access. Here's a per-service
permission table for the most common socket-using containers:

| Service        | Required Permissions                       | Rationale                                |
|----------------|--------------------------------------------|------------------------------------------|
| Portainer      | containers, images, networks, volumes,     | Full container lifecycle management      |
|                | info, events, start, stop, restarts,       |                                          |
|                | create, delete                             |                                          |
| Watchtower     | containers, images, info, events,          | List containers, pull new images,        |
|                | start, stop, restarts                      | restart updated containers               |
| Traefik/Caddy  | containers, networks, info                 | Service discovery via container labels   |
| Dozzle         | containers, logs, info                     | Read container logs                      |
| Homer/Homepage | containers, info                           | Service status display only              |
| Glances        | containers, info, networks, images         | System monitoring — may need more        |
| Grafana Docker | containers, info                           | Docker dashboard datasource              |

The principle: start with the minimum permissions, see what breaks, and
add one permission at a time. Most services fail loudly when they miss
an API endpoint — Watchtower will log endpoint errors, Portainer will
show empty pages.

---

## Testing Your Proxy Setup

After deploying, verify the proxy is working correctly:

```bash
# Direct connection to proxy (should work)
docker run --rm --network=proxy-net \
  alpine:latest sh -c \
  "apk add --no-cache curl && curl -s http://socket-proxy:2375/version"

# Try accessing a blocked endpoint
docker run --rm --network=proxy-net \
  alpine:latest sh -c \
  "apk add --no-cache curl && \
   curl -s -o /dev/null -w '%{http_code}' \
   http://socket-proxy:2375/containers/json?all=true"

# This should return 403 if ALLOW_ATTACH is false
docker run --rm --network=proxy-net \
  alpine:latest sh -c \
  "apk add --no-cache curl && \
   curl -s -o /dev/null -w '%{http_code}' \
   -X POST http://socket-proxy:2375/containers/test/attach"
```

Check the proxy logs for blocked requests:

```bash
docker logs socket-proxy
# Look for lines like: "Forbidden: /containers/test/attach"
```

---

## Hardening the Proxy Further

### 1. Read-Only Socket Mount

Mount the socket as read-only in the proxy container. The proxy only
reads from it anyway:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

Already included in our Compose file above. If you're running with
`docker run`, add `:ro`:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock:ro ...
```

### 2. Restrict Proxy to Specific Subnet

Bind the proxy to the internal network only. Don't expose port 2375
to the host or external interfaces:

```yaml
services:
  socket-proxy:
    networks:
      proxy-net:
        ipv4_address: 172.20.0.2
    # No ports section — the proxy is only reachable via the Docker network
```

No `ports:` mapping means the proxy's TCP port 2375 is only accessible
from containers on the `proxy-net` network. Not from the host. Not from
your LAN.

### 3. Use Separate Proxy Instances for Different Trust Levels

If you have services that need broad permissions and services that need
only minimal ones, run two proxy instances:

```yaml
services:
  # Full-access proxy for management tools
  socket-proxy-admin:
    image: tecnativa/docker-socket-proxy:latest
    container_name: socket-proxy-admin
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      ALLOW_CONTAINERS: "true"
      ALLOW_START: "true"
      ALLOW_STOP: "true"
      ALLOW_RESTARTS: "true"
      ALLOW_CREATE: "true"
      ALLOW_DELETE: "true"
      ALLOW_IMAGES: "true"
      ALLOW_INFO: "true"
      ALLOW_EVENTS: "true"
      ALLOW_LOGS: "true"
      ALLOW_NETWORKS: "true"
      ALLOW_VOLUMES: "true"
      ALLOW_EXEC: "true"
    networks:
      - admin-net

  # Read-only proxy for monitoring and display
  socket-proxy-readonly:
    image: tecnativa/docker-socket-proxy:latest
    container_name: socket-proxy-readonly
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      ALLOW_CONTAINERS: "true"
      ALLOW_INFO: "true"
      ALLOW_LOGS: "true"
    networks:
      - monitor-net
```

Connect Portainer to `admin-net`. Connect Dozzle and Homer to
`monitor-net`. A compromise in the dashboard won't affect the manager.

---

## What If a Container Doesn't Support a Remote Docker Host?

Some containers hardcode the socket path and don't respect the
`DOCKER_HOST` environment variable. For those, you have two options:

### Option A: Third-Party Socket Forwarder

Use a tool like `socat` to forward the local socket to the proxy:

```yaml
services:
  # Workaround for containers that hardcode /var/run/docker.sock
  socket-forwarder:
    image: alpine/socat:latest
    container_name: socket-forwarder
    restart: unless-stopped
    networks:
      - proxy-net
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock
    command: "socat UNIX-LISTEN:/tmp/forwarded.sock,fork,reuseaddr,mode=777 TCP:172.20.0.2:2375"
    depends_on:
      - socket-proxy
```

### Option B: Use a Symlink

If the container respects Unix sockets:

```bash
# Stop the container, create a socket forwarder that connects to the proxy
# This is rarely the right solution — prefer Option A or use a compatible image
```

In practice, almost every modern Docker tool supports `DOCKER_HOST` or
has an environment variable to configure the endpoint. Check the
container's documentation before resorting to workarounds.

---

## Migrating from Direct Socket Mounts

Moving existing containers from direct socket mounts to the proxy is
straightforward:

1. **Remove the volume mount** — delete `- /var/run/docker.sock:/var/run/docker.sock`
   from the container's volumes section.

2. **Add the environment variable** — set `DOCKER_HOST=tcp://socket-proxy:2375`
   in the container's environment.

3. **Connect to the proxy network** — add the proxy network to the
   container's networks section.

4. **Add depends_on** — add `depends_on: - socket-proxy` for proper
   startup ordering.

5. **Recreate the container** — `docker compose up -d`

Example migration for a single container:

```bash
# Before
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower

# After
docker run -d \
  --name watchtower \
  --network proxy-net \
  -e DOCKER_HOST=tcp://socket-proxy:2375 \
  containrrr/watchtower
```

The container won't restart, logs won't show, and Portainer won't list
containers on the first run if you missed permissions. Check the proxy
logs — every denied access is logged with the exact endpoint that was
blocked.

---

## When the Proxy Makes Sense and When It Doesn't

The socket proxy is a good fit for:
- Homelabs running 3+ socket-consuming containers
- Any setup where untrusted containers need Docker API access
- Multi-tenant Docker hosts (shared with friends or family)
- Learning Docker security before scaling to production

Skip the proxy when:
- You run exactly one container that needs the socket (just ask if you
  really need that container)
- You need Docker in Docker (DinD) for CI/CD pipelines — different
  pattern entirely
- You're on a single-board computer with tight memory (the proxy adds
  ~15 MB overhead)
- Your containers already run with `--privileged` (fix that first)

---

## Summary

The Docker socket proxy is one of the highest-impact security
improvements you can make in a homelab. It replaces a binary "mount
the socket or don't" decision with granular, per-endpoint control.

The setup takes five minutes: deploy the proxy, change `DOCKER_HOST`,
remove the socket mount. Fifteen megabytes of RAM buys you defense in
depth for every container that needs Docker API access.

Remember: if the attacker gets your Portainer, they should not also get
your host. The socket proxy is the firewall between them.
