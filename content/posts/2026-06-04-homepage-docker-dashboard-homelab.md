---
title: "Homepage Docker Deployment — Self-Hosted Dashboard for Homelab Services"
description: "Deploy Homepage — a modern self-hosted dashboard with Docker Compose. Monitor system stats, track container health, and organize homelab services with API widgets and customizable YAML config."
date: 2026-06-04T07:00:00-04:00
tags:
  - selfhosting
  - docker
  - homelab
  - monitoring
  - docker-compose
keywords:
  - Homepage Docker homelab deployment configuration
  - Self-hosted dashboard Docker Compose setup
  - Homepage gethomepage service integration widgets
  - Homelab dashboard system monitoring CPU RAM Docker stats
  - Homepage YAML configuration bookmarks services
  - Docker container health status dashboard
  - Homepage API widgets homelab integration
summary: "Deploy Homepage, the lightweight homelab dashboard, with Docker Compose. Configure service widgets, system monitors, Docker stats, and API integrations in a single YAML-driven interface."
canonical: "https://blog.gntech.me/posts/homepage-docker-dashboard-homelab/"
---

## Why a Self-Hosted Dashboard Belongs in Every Homelab

As your homelab grows, so does the list of services you manage. Traefik routes traffic, Portainer manages containers, Grafana visualizes metrics, Pi-hole filters DNS — each with its own URL, port, and login page. A self-hosted dashboard gives you a single entry point to launch any service, see which containers are healthy, and monitor system resources at a glance.

[Homepage](https://gethomepage.dev/) is the most polished option in this space. It is a lightweight, YAML-driven dashboard that integrates directly with Docker containers, exposes real-time system stats, and provides API widgets for services like Traefik, Pi-hole, Prometheus, Proxmox, and Uptime Kuma. Unlike heavier solutions like Homer or Heimdall, Homepage requires no database and no complex backend — just a Docker container and a few YAML files.

**What you will end up with:**
- A single dashboard at `http://homelab:3000` or via your reverse proxy
- Auto-discovered Docker containers with live status, CPU, and memory
- System resource widgets (CPU, memory, disk, uptime)
- Service-specific API widgets for Traefik, Pi-hole, Uptime Kuma, and Proxmox
- A clean, customizable interface with bookmarks and search

## Prerequisites

- Docker and Docker Compose v2 installed on any Linux host
- A working reverse proxy (Traefik or Nginx) if you want TLS and a clean domain
- Port 3000 available on the host (or change it in compose)
- Docker socket access for container discovery

## Deploying Homepage with Docker Compose

Homepage runs as a single container with no external dependencies. The Docker Compose deployment is straightforward:

```yaml
services:
  homepage:
    image: ghcr.io/gethomepage/homepage:latest
    container_name: homepage
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - ./config:/app/config
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

Create the project directory and start the container:

```bash
mkdir -p ~/docker/homepage/config
cd ~/docker/homepage
docker compose up -d
```

Open `http://your-host:3000`. You will see a blank page — Homepage ships with no configuration by default. The config directory is empty until you populate it.

### Adding a Traefik Reverse Proxy

If you run Traefik, add labels for automatic TLS and routing:

```yaml
services:
  homepage:
    image: ghcr.io/gethomepage/homepage:latest
    container_name: homepage
    restart: unless-stopped
    expose:
      - "3000"
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - ./config:/app/config
      - /var/run/docker.sock:/var/run/docker.sock:ro
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.homepage.rule=Host(`homepage.lab.example.com`)"
      - "traefik.http.services.homepage.loadbalancer.server.port=3000"
      - "traefik.http.routers.homepage.entrypoints=websecure"
      - "traefik.http.routers.homepage.tls.certresolver=letsencrypt"
```

> **Security note:** Mounting the Docker socket (`/var/run/docker.sock`) gives Homepage access to control Docker. This is required for automatic container discovery. If you prefer to avoid the socket mount, you can manually define services in `services.yaml` without Docker stats.

## Configuration Structure

Homepage reads its configuration from three YAML files in the config directory. You can start with just `services.yaml` and `bookmarks.yaml` and add more as needed:

```
~/docker/homepage/config/
├── services.yaml       # Service groups and links
├── bookmarks.yaml      # Quick-access bookmarks
├── widgets.yaml        # Widget configuration for API integrations
├── docker.yaml         # Docker container overrides
├── settings.yaml       # Layout, theme, and general settings
└── custom.css          # Theme overrides
```

After adding or modifying any config file, restart the container:

```bash
cd ~/docker/homepage && docker compose restart
```

Homepage reloads configuration on restart only — there is no hot-reload.

## Services Configuration with Docker Integration

The `services.yaml` file defines how services are grouped and displayed. Combined with the Docker socket mount, Homepage automatically shows the health status and resource usage of each container.

### Manual Service Groups

Create `config/services.yaml`:

```yaml
---
- Infrastructure:
    - Traefik:
        href: https://traefik.lab.example.com
        description: Reverse Proxy Dashboard
        icon: traefik
        ping: https://traefik.lab.example.com
        container: traefik

    - Portainer:
        href: https://portainer.lab.example.com
        description: Container Management
        icon: portainer
        container: portainer

    - Proxmox:
        href: https://proxmox.lab.example.com:8006
        description: Virtualization Platform
        icon: proxmox

- Monitoring:
    - Grafana:
        href: https://grafana.lab.example.com
        description: Metrics Dashboard
        icon: grafana
        container: grafana

    - Uptime Kuma:
        href: https://uptime.lab.example.com
        description: Status Monitoring
        icon: uptime-kuma
        container: uptime-kuma

    - Netdata:
        href: https://netdata.lab.example.com
        description: System Monitoring
        icon: netdata
        container: netdata

- Media:
    - Jellyfin:
        href: https://media.lab.example.com
        description: Media Server
        icon: jellyfin
        container: jellyfin
```

Key fields:
- **icon**: Homepage ships with [200+ built-in icons](https://gethomepage.dev/configs/services/#icons) — just use the service name
- **container**: Links the service to a Docker container name; Homepage uses the socket to show status, CPU, and memory
- **ping**: Homepage periodically checks the URL and shows a green/red dot status indicator
- **description**: Shown beneath the service name

### Docker Auto-Discovery with docker.yaml

Without any configuration, Homepage can auto-discover all running containers if the Docker socket is mounted. By default, it creates a group called "Docker" with every container listed. To control what appears and in which group, create `config/docker.yaml`:

```yaml
---
my-docker-host:
  host: 127.0.0.1
  docker: host
  monitors:
    - traefik
    - portainer
    - grafana
    - uptime-kuma
    - jellyfin
```

This creates a server group named "my-docker-host" with only the listed containers. Each container shows its status, CPU usage, and memory consumption pulled from the Docker API.

### Docker Labels for Customization

You can override Homepage display settings by adding labels to your Docker compose files:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin
    labels:
      - "homepage.group=Media"
      - "homepage.name=Jellyfin"
      - "homepage.icon=jellyfin"
      - "homepage.href=https://media.lab.example.com"
      - "homepage.description=Movies, TV, Music"
      - "homepage.ping=https://media.lab.example.com"
      - "homepage.weight=1"
```

This approach keeps everything in the container's own configuration — Homepage picks it up from Docker labels automatically.

## System Monitoring Widgets

The `widgets.yaml` file adds panels to the top of the dashboard showing real-time system information. Homepage supports several built-in widgets:

### Resources Widget

```yaml
---
- resources:
    label: SRV1
    cpu: true
    memory: true
    disk: /
    uptime: true
```

This widget displays CPU usage, memory usage, root disk usage, and system uptime for the host running Homepage.

### Docker Engine Widget

```yaml
- docker:
    label: Docker Engine
    host: /var/run/docker.sock
```

Shows total container count, running count, and a quick health summary.

### Search Widget

```yaml
- search:
    provider: google
    target: _blank
```

For a privacy-respecting homelab, point it at your own SearXNG instance:

```yaml
- search:
    provider: custom
    url: https://search.lab.example.com/search?q={query}
    target: _blank
```

### Clock and Greeting

```yaml
- datetime:
    text_format: HH:mm
    locale: en-US
```

Or with the date:

```yaml
- datetime:
    text_format: EEEE, MMMM do yyyy '|' HH:mm
    locale: en-US
```

All widgets in one `widgets.yaml`:

```yaml
---
- resources:
    label: SRV1
    cpu: true
    memory: true
    disk: /
    uptime: true

- search:
    provider: custom
    url: https://search.lab.example.com/search?q={query}
    target: _blank

- datetime:
    text_format: EEEE, MMMM do yyyy '|' HH:mm
    locale: en-US
```

## Service-Specific API Widgets

Homepage's real power is in API widgets — live data pulled directly from your services' APIs and rendered as panel cards.

### Traefik Widget

Enable the Traefik API endpoint first:

```yaml
services:
  traefik:
    image: traefik:v3.3
    command:
      - "--api.insecure=false"
      - "--api.dashboard=true"
    # ... other config
```

Then in `widgets.yaml`:

```yaml
- traefik:
    label: Traefik
    url: https://traefik.lab.example.com
    key: your-api-key-or-basic-auth
```

If Traefik is behind authentication, you can pass the credentials as the key. Check the [Traefik widget docs](https://gethomepage.dev/widgets/services/traefik/) for exact authentication methods.

### Pi-hole Widget

Requires the Pi-hole API token. Find it in Pi-hole's Settings → API/Web Interface → "Show API Token".

```yaml
- pihole:
    label: Pi-hole
    url: http://pihole.lab.local
    key: your-api-token-here
```

Shows total queries blocked today, percentage blocked, and query count.

### Uptime Kuma Widget

Uptime Kuma exposes a status page API by default. Enable the status page in Uptime Kuma settings, then:

```yaml
- uptimekuma:
    label: Uptime Kuma
    url: https://uptime.lab.example.com
    slug: your-status-page-slug
```

The widget shows a green/red indicator for each monitored endpoint.

### Proxmox Widget

Requires an API token with read permissions. Create one in Proxmox at Datacenter → Permissions → API Tokens:

```yaml
- proxmox:
    label: Proxmox VE
    host: 10.0.20.30
    username: your-token-id
    password: your-secret
```

Shows node status, memory usage, CPU load, and running VM/LXC counts.

## Bookmark Organization

Bookmarks are grouped links for quick access. Create `config/bookmarks.yaml`:

```yaml
---
- Tools:
    - GitHub:
        - icon: github
          href: https://github.com
    - Cloudflare:
        - icon: cloudflare
          href: https://dash.cloudflare.com
    - Docker Hub:
        - icon: docker
          href: https://hub.docker.com

- Internal:
    - Router:
        - icon: mikrotik
          href: https://10.0.20.1
    - Proxmox Host:
        - icon: proxmox
          href: https://10.0.20.30:8006
    - NAS:
        - icon: nas
          href: https://nas.lab.local
```

Bookmarks appear in a collapsible sidebar on the dashboard.

## Theming and Customization

Homepage supports full visual customization through `settings.yaml` and `custom.css`.

### Layout and Layout Settings

Create `config/settings.yaml`:

```yaml
---
title: Homelab
theme: dark
background:
  image: https://images.unsplash.com/photo-1519681393784-d120267933ba
  blur: xs
  saturate: 50
layout:
  Media:
    style: row
    columns: 4
  Monitoring:
    style: column
    columns: 3
```

### Custom CSS

Add `config/custom.css` with your own style overrides:

```css
body {
  --color-primary: #7c3aed;
  --color-primary-light: #a78bfa;
}
```

Common customizations include accent colors, card border radius, and header opacity. See the [Homepage theming guide](https://gethomepage.dev/configs/settings/#custom-css) for the full variable list.

## Advanced: Custom API Widgets

If a service isn't in Homepage's built-in widget list, you can build a custom widget that fetches from any JSON API.

```yaml
- customapi:
    label: Custom Endpoint
    url: https://your-service/api/status
    headers:
      Authorization: Bearer your-token
    jsonpath: ".status"
    refreshInterval: 30000
```

Use `jsonpath` to extract a specific field from the JSON response. This works with any HTTP endpoint that returns JSON — NUT UPS status, TrueNAS API, or a custom script.

## Troubleshooting Common Issues

### Empty Dashboard After Deployment

Homepage starts with a blank page until you create config files. Create at least `services.yaml` with a service group and restart the container.

### Docker Socket Permission Denied

```
Permission denied on /var/run/docker.sock
```

The PUID/PGID in the container must match a user that belongs to the `docker` group on the host. Verify:

```bash
ls -l /var/run/docker.sock
# Output: srw-rw---- 1 root docker 0 ...
getent group docker
# Output: docker:x:999:youruser
usermod -aG docker youruser  # if needed
```

Then set `PUID=$(id -u youruser)` and `PGID=$(getent group docker | cut -d: -f3)`.

### Containers Not Appearing

If Docker auto-discovery isn't showing containers:
- Verify the socket is mounted correctly: `docker exec homepage ls -l /var/run/docker.sock` should show the socket
- Check `docker.yaml` is loading the correct host (defaults to `127.0.0.1`)
- Ensure containers are running: `docker ps --all`

### Widget Not Showing Data

API widgets fail silently if the endpoint is unreachable or authentication is wrong. Check the Homepage container logs:

```bash
docker logs homepage | grep -i widget
```

Common causes:
- Wrong URL or port (containers behind a Docker network need the internal URL, not the public one)
- Missing or expired API token
- Self-signed TLS certificate causing connection errors

## Putting It All Together

A self-hosted dashboard transforms a scattered collection of services into a unified homelab experience. Homepage delivers this with minimal overhead — a single container, three YAML files, and optional API integrations give you a polished, responsive interface that works on desktop and mobile.

**Key takeaways:**
- Start with the basic compose file and add service groups one at a time
- Mount the Docker socket for automatic container health, CPU, and memory display
- Add API widgets for Traefik, Pi-hole, and Uptime Kuma as high-value integrations
- Use `docker.yaml` to filter which containers appear instead of showing everything
- Customize the theme through `settings.yaml` and optional `custom.css`
- Test changes with `docker compose restart` — no database or rebuild needed

Your dashboard will become the first page you open every time you check on the homelab. Start with the basics, then layer on widgets and integrations as your infrastructure grows.
