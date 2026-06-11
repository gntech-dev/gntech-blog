---
title: "Docker Proxy Configuration Guide — HTTP/HTTPS Proxy for Containers"
description: "Configure HTTP/HTTPS proxy for Docker daemon, CLI, and individual containers in your homelab. Covers daemon.json, systemd override, Compose env vars, and NO_PROXY best practices."
date: 2026-06-11T11:00:00-04:00
tags:
  - docker
  - homelab
  - containers
  - networking
  - proxy
keywords:
  - Docker daemon proxy configuration HTTP_PROXY HTTPS_PROXY systemd
  - Docker per-container proxy environment variables homelab setup
  - Docker compose proxy settings service-level http_proxy configuration
  - Docker NO_PROXY internal network proxy bypass best practices
  - Docker pull-through proxy behind VPN gateway configuration
  - Docker CLI proxy environment variables build-time configuration
  - Docker proxy vs Gluetun VPN gateway container networking
summary: "Configure HTTP/HTTPS proxy for Docker daemon, CLI, and individual containers in your homelab. Covers systemd drop-in overrides, daemon.json settings, Docker Compose proxy variables, and the critical NO_PROXY configuration to avoid breaking internal container communication."
canonical: "https://blog.gntech.me/posts/docker-proxy-configuration-homelab/"
---

Your Proxmox host runs Docker behind a Gluetun WireGuard gateway. Containers start, DNS works, but `docker pull` hangs. `docker build` times out fetching packages. Your app container tries to reach an external API through `localhost:3128` — but nothing is listening there.

This is the Docker proxy configuration problem, and it hits every homelab that routes traffic through a VPN gateway or forward proxy. The good news: Docker supports proxy configuration at three cleanly separated levels — daemon, CLI, and container — and once you understand how each one works, the fix is straightforward.

This guide covers all three layers with real configs you can copy into your homelab today.

## Docker Daemon Proxy Configuration for Image Pulls

The Docker daemon needs proxy settings when it pulls images from registries. Without them, `docker pull` fails silently when the host has no direct internet route.

There are two ways to set daemon-level proxy: systemd drop-in files (recommended for systemd-managed Docker) and `daemon.json` (for dockerd config-based setups).

### Systemd Drop-In Approach

Create a drop-in file under the Docker systemd service directory:

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
```

Then create `/etc/systemd/system/docker.service.d/proxy.conf`:

```ini
[Service]
Environment="HTTP_PROXY=http://192.168.1.100:3128"
Environment="HTTPS_PROXY=http://192.168.1.100:3128"
Environment="NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal"
```

Docker accepts both uppercase and lowercase variants (`HTTP_PROXY` and `http_proxy`). Set both for maximum application compatibility.

Apply the change and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
systemctl show --property=Environment docker
```

You should see your proxy variables in the output. You can also verify with:

```bash
docker info | grep -i proxy
```

Expected output:

```
 HTTP Proxy: http://192.168.1.100:3128
 HTTPS Proxy: http://192.168.1.100:3128
 No Proxy: localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal
```

### daemon.json Approach

If you manage Docker through its JSON config file (`/etc/docker/daemon.json`), add a `proxies` block:

```json
{
  "proxies": {
    "http-proxy": "http://192.168.1.100:3128",
    "https-proxy": "http://192.168.1.100:3128",
    "no-proxy": "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal"
  }
}
```

This approach is cleaner if you already maintain `daemon.json` for other settings like storage driver, log driver, or cgroup configuration. The systemd drop-in method takes precedence if both are set.

After editing, restart Docker:

```bash
sudo systemctl restart docker
```

### Which One to Choose

Use the systemd drop-in if:
- You already configure Docker via systemd
- You want separation between service-level and config-level settings
- You use a distribution where Docker is installed via the official repo (Debian, Ubuntu, Fedora)

Use `daemon.json` if:
- You manage Docker config through Ansible or a configuration management tool
- You already have a `daemon.json` with other settings
- You run Docker in rootless mode

## Docker CLI Proxy Configuration for Builds

When you build images locally with `docker build` or `docker buildx`, the build process needs proxy access to download packages. There are two parts to this: getting the proxy into the build context, and consuming it inside the Dockerfile.

### Passing Proxy via Build Arguments

```bash
docker build \
  --build-arg HTTP_PROXY=http://192.168.1.100:3128 \
  --build-arg HTTPS_PROXY=http://192.168.1.100:3128 \
  --build-arg NO_PROXY=localhost,127.0.0.1 \
  -t my-app:latest .
```

Inside the Dockerfile, declare the build args and use them in RUN commands:

```dockerfile
FROM debian:bookworm-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*
```

For Python, npm, or Go builds, the proxy variables are often picked up automatically by the package manager:

```dockerfile
RUN pip install --proxy="$HTTP_PROXY" -r requirements.txt
RUN npm config set proxy "$HTTP_PROXY"
```

### Docker CLI Client Config

You can also set proxy in `~/.docker/config.json`:

```json
{
  "proxies": {
    "default": {
      "httpProxy": "http://192.168.1.100:3128",
      "httpsProxy": "http://192.168.1.100:3128",
      "noProxy": "localhost,127.0.0.1"
    }
  }
}
```

This applies to `docker build` commands run by the current user. BuildKit (the default builder since Docker Engine 23) reads these settings natively and passes them to the build context.

## Per-Container Proxy Configuration in Docker Compose

For runtime proxy configuration — when your running containers need to reach external APIs through a proxy — set environment variables at the service level in your Compose file.

### Direct Environment Variables

```yaml
services:
  app:
    image: my-app:latest
    environment:
      - HTTP_PROXY=http://proxy:3128
      - HTTPS_PROXY=http://proxy:3128
      - NO_PROXY=localhost,127.0.0.1,.internal,.local,.cluster.local
    depends_on:
      - proxy

  proxy:
    image: ubuntu/squid:latest
    ports:
      - "3128:3128"
    volumes:
      - ./squid.conf:/etc/squid/squid.conf:ro
```

### Using an env_file

For large stacks with many services sharing the same proxy, use a shared environment file:

Create `proxy.env`:

```
HTTP_PROXY=http://proxy:3128
HTTPS_PROXY=http://proxy:3128
NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.internal,.local,.cluster.local
```

Reference it in every service that needs external access:

```yaml
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:release
    env_file: proxy.env
    # ...

  syncthing:
    image: syncthing/syncthing
    env_file: proxy.env
    # ...
```

### Variable Substitution Pattern

You can also use Compose variable substitution to make proxy settings configurable without hardcoding:

```yaml
services:
  app:
    image: my-app:latest
    environment:
      - HTTP_PROXY=${HTTP_PROXY:-}
      - HTTPS_PROXY=${HTTPS_PROXY:-}
      - NO_PROXY=${NO_PROXY:-localhost,127.0.0.1}
```

Then set the variables in a `.env` file next to your Compose file:

```env
HTTP_PROXY=http://192.168.1.100:3128
HTTPS_PROXY=http://192.168.1.100:3128
NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

### Proxy Behind a VPN Gateway

If your homelab routes external traffic through a Gluetun or WireGuard gateway container, run Squid or Tinyproxy inside the same network stack so it shares the VPN tunnel:

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun
    cap_add:
      - NET_ADMIN
    environment:
      - VPN_SERVICE_PROVIDER=mullvad
      - VPN_TYPE=wireguard
    networks:
      - vpn-net

  proxy:
    image: ubuntu/squid:latest
    network_mode: "service:gluetun"
    depends_on:
      gluetun:
        condition: service_healthy

  app:
    image: my-app:latest
    network_mode: "service:gluetun"
    environment:
      - HTTP_PROXY=http://localhost:3128
      - HTTPS_PROXY=http://localhost:3128
      - NO_PROXY=localhost,127.0.0.1
    depends_on:
      proxy:
        condition: service_started

networks:
  vpn-net:
    driver: bridge
```

This pattern gives each container full VPN routing through the proxy while keeping NO_PROXY small since localhost access stays within the same network namespace.

## NO_PROXY — The Critical Bypass List

NO_PROXY is the most common source of proxy-related failures in Docker Compose stacks. If your Postgres container is named `db` and your app tries to reach it at `db:5432` through the proxy, the connection fails because Squid doesn't speak PostgreSQL.

### What to Include

At minimum, add these to NO_PROXY:

- `localhost` and `127.0.0.1` — loopback access
- All RFC1918 subnets — `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Docker internal domain suffixes — `.local`, `.internal`, `.cluster.local`
- Specific service hostnames if your proxy ignores CIDR notation (some applications don't support CIDR in NO_PROXY)

### Full NO_PROXY Reference

```
NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal,.cluster.local,.svc.cluster.local
```

### Common NO_PROXY Mistakes

1. **Omitting RFC1918 subnets** — your Compose services communicate on Docker bridge networks (typically 172.x.x.x), which will be routed through the proxy if not excluded
2. **Using wildcards incorrectly** — NO_PROXY uses domain suffix matching (`.local` matches `anything.local`), not glob patterns
3. **Case sensitivity** — most applications respect lowercase `no_proxy` and uppercase `NO_PROXY`, but set both to be safe
4. **CIDR support varies** — some applications and libraries don't support CIDR in NO_PROXY. Go's `http.ProxyFromEnvironment` does; Python's `urllib` did not before 3.13. Use domain suffixes as a fallback

## Running a Forward Proxy Container for Your Homelab

If you do not already have a forward proxy on your network, running one in Docker is straightforward. Squid is the classic choice, but Tinyproxy is lighter for simple pass-through proxying.

### Tinyproxy — Minimal Forward Proxy

```yaml
services:
  tinyproxy:
    image: vimagick/tinyproxy:latest
    ports:
      - "127.0.0.1:8888:8888"
    environment:
      - TINYPROXY_LOGLEVEL=Warning
      - TINYPROXY_ALLOW=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

Bind to `127.0.0.1` when the proxy runs on the same host as the containers; bind to the Docker bridge IP when other hosts need it.

### Squid with Authentication

```yaml
services:
  squid:
    image: ubuntu/squid:latest
    ports:
      - "3128:3128"
    volumes:
      - ./squid.conf:/etc/squid/squid.conf:ro
      - ./passwd:/etc/squid/passwd:ro
```

With a `squid.conf` that requires authentication:

```
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic children 5
auth_param basic realm Squid Proxy
acl authenticated proxy_auth REQUIRED
http_access allow authenticated
http_access deny all
http_port 3128
```

Create the password file:

```bash
htpasswd -c ./passwd proxyuser
```

Then reference the credentials in your container proxy variables:

```
HTTP_PROXY=http://proxyuser:password@squid:3128
```

## Verification and Troubleshooting

### Test Daemon Proxy

```bash
# Check daemon proxy environment
docker info | grep -i proxy

# Test pull through proxy
docker pull alpine
```

### Test Container Proxy

```bash
# Check proxy env inside a container
docker run --rm alpine env | grep -i proxy

# Verify external access through proxy
docker run --rm alpine wget -O- https://httpbin.org/ip

# If curl is your tool
docker run --rm curlimages/curl -s https://httpbin.org/ip
```

### Troubleshooting Checklist

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `docker pull` hangs | Daemon missing proxy config | Add systemd drop-in or daemon.json proxy |
| Container can't reach external API | Missing container-level HTTP_PROXY | Set env vars per service in Compose |
| Inter-container connections fail | Missing NO_PROXY for internal subnets | Add RFC1918 ranges and `.local` to NO_PROXY |
| Build fails downloading packages | Build args not passed to Dockerfile | Add ARG and --build-arg to build command |
| Proxy refuses connection | Proxy container not running or wrong address | Check `docker ps` and verify proxy URL |

## Conclusion

Docker proxy configuration is a three-layer problem: daemon for pulls, CLI for builds, and container env vars for runtime traffic. The most common mistake in homelab setups is skipping NO_PROXY, which silently breaks inter-container communication on bridge networks.

Start with the systemd drop-in file for the daemon, add container-level proxy variables in your Compose files, and always include RFC1918 subnets plus `.local` in NO_PROXY. If you need a forward proxy, run Tinyproxy or Squid in a container and bind it to the same network stack as your VPN gateway.

For more homelab Docker patterns, check out the [Docker Compose networking patterns](/posts/docker-compose-networking-patterns/) guide and the [Gluetun VPN gateway container](/posts/gluetun-vpn-gateway-docker-wireguard/) deployment.
