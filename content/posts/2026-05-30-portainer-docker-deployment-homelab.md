---
title: "Portainer Docker Deployment — Homelab Container Management Guide"
description: "Deploy Portainer with Docker Compose for visual container management across your homelab. Multi-host agent setup, stack deployment, security hardening, and backup strategies."
date: 2026-05-30T17:00:00-04:00
tags:
  - docker
  - containers
  - management
  - devops
  - homelab
keywords:
  - Portainer Docker Compose deployment homelab guide
  - Portainer agent multi-host Docker management
  - Portainer stack deployment container orchestration
  - Portainer security hardening Docker socket proxy
  - Portainer backup restore homelab containers
  - Portainer Business Edition community edition comparison
  - Portainer container management UI tutorial
summary: "Deploy Portainer with Docker Compose for visual container management across your homelab. Covers CE vs Business Edition, multi-host agent setup, stack deployment, security hardening, and backup strategies."
canonical: "https://blog.gntech.me/posts/portainer-docker-deployment-homelab/"
---

Portainer is the most widely deployed container management UI in the
self-hosted world, and for good reason. It gives you a clean web interface
for everything you normally type into a terminal — starting and stopping
containers, inspecting logs, pulling images, managing volumes and networks,
and deploying full Docker Compose stacks.

When your homelab runs five containers, `docker ps` and a handful of
aliases are fine. When it runs thirty containers across three Docker hosts
plus a handful of Proxmox LXCs, the CLI overhead adds up fast. Portainer
absorbs that overhead without requiring you to abandon the terminal
entirely — it complements the CLI rather than replacing it.

This guide covers deploying Portainer Community Edition with Docker
Compose, setting up agents for multi-host management, deploying stacks
through the UI, hardening the deployment with a socket proxy, and
backing up your Portainer database so you never lose your configuration.

## Portainer CE vs Business Edition — Which One for Your Homelab

Portainer comes in two editions:

**Community Edition (CE)** — Free, open source, and fully capable for
single-user homelab environments. CE gives you the full dashboard,
container management, image management, volumes, networks, stacks,
and basic access controls.

**Business Edition (BE)** — Adds RBAC with teams, registry management,
Kubernetes support, and audit logging. These features matter in corporate
environments with multiple teams sharing infrastructure, but are overkill
for the typical homelab. BE requires a paid license after the free trial.

For this guide we deploy Portainer CE. If you need multi-user RBAC or
Kubernetes later, migrating to BE is straightforward — the data directory
is compatible between editions.

## Deploying Portainer CE with Docker Compose

Portainer ships as a single container that mounts the Docker socket to
manage the local host. The deployment is lightweight — Portainer itself
consumes about 100 MB of RAM and near-zero CPU at idle.

Create a directory for Portainer and a `docker-compose.yml`:

```yaml
services:
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - portainer_data:/data
    environment:
      - TZ=America/Santo_Domingo
    networks:
      - proxy

networks:
  proxy:
    external: true

volumes:
  portainer_data:
```

The socket mount (`:ro` for read-only) gives Portainer the API access it
needs. The data volume stores the internal SQLite database, TLS
certificates, user settings, and stack definitions. The proxy network
assumes you already run Traefik or another reverse proxy — if you do not,
remove the network section and access Portainer directly on port 9000.

Bring it up:

```bash
docker compose up -d
```

Access `http://<host-ip>:9000` and create the admin user on first launch.
Set a strong password — Portainer uses bcrypt hashing, and this account
controls every Docker host you attach.

### Traefik Reverse Proxy Configuration

If you already run Traefik, front Portainer with a proper domain and
automatic TLS. Add Traefik labels to the compose file:

```yaml
services:
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - portainer_data:/data
    environment:
      - TZ=America/Santo_Domingo
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.portainer.rule=Host(`portainer.lab.example.com`)"
      - "traefik.http.routers.portainer.entrypoints=https"
      - "traefik.http.routers.portainer.tls=true"
      - "traefik.http.routers.portainer.tls.certresolver=letsencrypt"
      - "traefik.http.services.portainer.loadbalancer.server.port=9000"

networks:
  proxy:
    external: true

volumes:
  portainer_data:
```

Replace `portainer.lab.example.com` with your actual domain. The
entrypoint and cert resolver names must match your Traefik configuration.

## Multi-Host Management with Portainer Agents

Portainer's real value in a multi-host homelab is the agent architecture.
An agent container runs on each additional Docker host and communicates
back to the Portainer server over an encrypted tunnel on port 9001.

### Agent Deployment

On each secondary Docker host, create a `docker-compose.yml`:

```yaml
services:
  portainer_agent:
    image: portainer/agent:latest
    container_name: portainer_agent
    restart: unless-stopped
    ports:
      - "9001:9001"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/lib/docker/volumes:/var/lib/docker/volumes:ro
    environment:
      - AGENT_CLUSTER_ADDR=tasks.portainer_agent
    networks:
      - agent_net

networks:
  agent_net:
    name: portainer_agent
```

The `AGENT_CLUSTER_ADDR` variable is required for Docker Swarm mode;
for standalone hosts it is ignored but does no harm.

### Connecting an Agent to the Portainer Server

1. Log into the Portainer UI at `https://portainer.lab.example.com`
2. Go to **Home** → **Add Endpoint**
3. Select **Docker** as the environment type
4. Choose **Agent** as the method
5. Enter the agent URL: `http://<agent-host-ip>:9001`
6. Click **Connect**

The agent host immediately appears in the Portainer dashboard alongside
your local endpoint. You can now manage containers, images, volumes, and
networks on that host as if it were local to the server.

### Firewall Rules

On Proxmox hosts or physical servers, restrict agent access to the
Portainer server IP only:

```bash
iptables -A INPUT -p tcp --dport 9001 -s 10.0.20.30 -j ACCEPT
iptables -A INPUT -p tcp --dport 9001 -j DROP
```

Replace `10.0.20.30` with your Portainer server IP. On MikroTik
routers, create a corresponding firewall filter rule:

```
/ip firewall filter add chain=input protocol=tcp dst-port=9001 \
  src-address=10.0.20.30 action=accept
/ip firewall filter add chain=input protocol=tcp dst-port=9001 \
  action=drop
```

## Managing Containers Through the Portainer UI

The Portainer dashboard presents a real-time overview of your
environment. From the left sidebar you access every management function:

**Containers** — Start, stop, restart, pause, kill, or remove containers.
Click any container to view live logs, inspect configuration, exec into
a shell, see resource usage charts (CPU, memory, network I/O), and
attach or detach networks without typing a single docker command.

**Images** — Pull images from Docker Hub or your private registry, tag
them, push to registries, build from a Dockerfile (uploaded or pasted),
and prune unused images.

**Volumes** — Create, inspect, and remove volumes. The volume browser
shows mounted containers, mount points, and size — useful for
identifying orphaned volumes after stack removal.

**Networks** — Create custom bridge, macvlan, or ipvlan networks. Portainer
shows which containers are attached to each network with their assigned
IPs, which is invaluable when debugging connectivity between services.

## Stack Deployment — Visual Docker Compose

Portainer Stacks implement Docker Compose through the browser. This is
the feature that makes Portainer indispensable in a multi-service
homelab: you can version and deploy entire application stacks through a
UI with git-backed sources.

### Creating a Stack from YAML

1. Go to **Stacks** → **Add Stack**
2. **Name** the stack (e.g., `monitoring-stack`)
3. Choose **Web editor** and paste your compose file, or select
   **Repository** and provide a git URL and branch
4. Optionally upload an `.env` file for environment variables
5. Click **Deploy the stack**

Portainer parses the compose file, creates the networks and volumes,
pulls images if missing, and starts all services. The stack appears as
a single deployable unit — redeploy to update, or remove the stack to
tear down every associated resource.

### Git-Backed Stacks

The repository option is the preferred workflow for production homelabs.
Point Portainer at a GitHub, Gitea, or Forgejo repository containing
your compose files. Portainer clones the repo, deploys the stack, and
provides a **Pull and redeploy** button to apply updates:

```
Repository URL:  https://git.gntech.dev/infra/docker-compose.git
Repository ref:  refs/heads/main
Compose path:    monitoring/prometheus-grafana/docker-compose.yml
```

This git-backed pattern means your infrastructure-as-code lives in a
git repository, visible to team members, CI pipelines, and disaster
recovery procedures, while Portainer handles the deployment mechanics.

## Security Hardening with Docker Socket Proxy

The single biggest security concern with Portainer — or any tool that
mounts the Docker socket — is that a compromise of the web UI gives an
attacker root on the host. The Docker socket is root-equivalent.

The mitigation is a reverse proxy that sits between Portainer and the
socket, exposing only the API endpoints Portainer actually needs. The
community-standard solution is
[Tecnativa's docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy).

Add it to your compose file:

```yaml
services:
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - CONTAINERS=1
      - IMAGES=1
      - NETWORKS=1
      - VOLUMES=1
      - TASKS=1
      - SERVICES=1
      - NODES=1
      - INFO=1
      - EVENTS=1
      - AUTH=1
      - POST=1
    networks:
      - internal

  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - portainer_data:/data
    environment:
      - TZ=America/Santo_Domingo
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
    networks:
      - proxy
      - internal
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.portainer.rule=Host(`portainer.lab.example.com`)"
      - "traefik.http.routers.portainer.entrypoints=https"
      - "traefik.http.routers.portainer.tls=true"
      - "traefik.http.routers.portainer.tls.certresolver=letsencrypt"
      - "traefik.http.services.portainer.loadbalancer.server.port=9000"

networks:
  proxy:
    external: true
  internal:
    internal: true

volumes:
  portainer_data:
```

Key points:
- The socket proxy runs with `:ro` (read-only) socket mount
- Environment flags grant only the Docker API endpoints Portainer needs
- The internal network is `internal: true` — no external connectivity
- Portainer connects to the proxy via `DOCKER_HOST=tcp://docker-socket-proxy:2375`
- Portainer no longer mounts the socket at all

This three-container pattern (proxy → portainer → UI) reduces the
blast radius of a Portainer compromise to what the proxy allows, which
is container management operations without direct host access.

## Backup and Restore Portainer

Portainer stores everything — user accounts, endpoint definitions,
stack configurations, and settings — in a SQLite database inside the
`portainer_data` volume. Backing up this data is all you need.

### Manual Backup

```bash
docker run --rm \
  --volumes-from portainer \
  -v "$(pwd):/backup" \
  alpine tar czf /backup/portainer-backup-$(date +%F).tar.gz \
    -C /data .
```

This runs a temporary Alpine container that mounts the Portainer data
volume and creates a compressed archive in the current directory.

### Automated Backup with Systemd Timer

Create a backup script at `/usr/local/bin/backup-portainer.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/portainer"
mkdir -p "$BACKUP_DIR"
docker run --rm \
  --volumes-from portainer \
  -v "$BACKUP_DIR:/backup" \
  alpine tar czf "/backup/portainer-$(date +%F).tar.gz" \
    -C /data .
find "$BACKUP_DIR" -name "portainer-*.tar.gz" -mtime +30 -delete
```

Make it executable and wire up a systemd timer:

```bash
chmod +x /usr/local/bin/backup-portainer.sh
```

```
# /etc/systemd/system/portainer-backup.service
[Unit]
Description=Portainer data backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup-portainer.sh
```

```
# /etc/systemd/system/portainer-backup.timer
[Unit]
Description=Daily Portainer backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now portainer-backup.timer
```

### Restoring from Backup

```bash
docker compose down
docker run --rm \
  -v portainer_data:/data \
  -v "$(pwd):/backup" \
  alpine tar xzf "/backup/portainer-2026-05-30.tar.gz" \
    -C /data
docker compose up -d
```

Stop Portainer, extract the backup into the data volume, then restart.

## Real-World Usage Tips

**Use container labels** to organize your endpoints. In the Portainer UI,
you can apply labels to containers, images, and volumes. Set labels like
`project=monitoring`, `project=media`, or `environment=production` and
filter the dashboard by label. This makes a cluttered dashboard
navigable.

**Webhooks for auto-deploy.** Portainer stacks with git sources support
webhook triggers. Configure your Gitea or GitHub repository to send a
POST request to Portainer's webhook URL on push, and your stack
redeploys automatically. Find the webhook URL in Stack details →
Webhooks.

**Set resource limits through the UI.** Under Container → Duplicate/Edit
→ Resource limits, set CPU and memory quotas. Portainer translates these
to `--cpus`, `--memory`, and `--memory-reservation` in the container
configuration. This prevents a runaway container from starving the rest
of your services.

**Use maintenance mode.** Under Endpoints → Maintenance, you can enable
maintenance mode which stops all containers on the endpoint while
preserving their configurations. Useful before host upgrades or Docker
engine restarts.

## Wrapping Up

Portainer solves a real problem in the growing homelab: the gap between
"a few containers you can manage from memory" and "enough containers that
you need an inventory." It does not replace `docker compose` or make you
a worse operator — it gives you a dashboard for the operations you
perform dozens of times a day and frees mental energy for the work that
actually matters.

Deploy CE on your main Docker host, add agents as you grow to multiple
hosts, and always use the socket proxy if Portainer is exposed beyond
your LAN. Your data volume is tiny — back it up daily with the systemd
timer and you will never lose your configuration.

**References:**

- [Portainer Documentation](https://docs.portainer.io/)
- [Portainer CE GitHub](https://github.com/portainer/portainer)
- [Tecnativa Docker Socket Proxy](https://github.com/Tecnativa/docker-socket-proxy)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
