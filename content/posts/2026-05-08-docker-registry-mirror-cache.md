---
title: "Local Docker Registry Mirror — Cache Images and Speed Up Your Lab"
description: "Deploy a Docker registry mirror as a pull-through cache to save bandwidth, speed up deployments, and reduce Docker Hub rate limits in your homelab."
date: 2026-05-08T07:00:00-04:00
tags:
  - docker
  - registry
  - cache
  - containers
  - performance
categories:
  - homelab
  - docker
---

Docker Hub rate-limits anonymous pulls to 100 per 6 hours (200 for authenticated users). In a homelab with frequent rebuilds, multiple hosts, or CI-style workflows, you'll hit that limit fast. Even if you don't, pulling the same `nginx:alpine` image ten times across ten containers wastes bandwidth and time.

A local Docker registry mirror fixes both: it acts as a pull-through cache. First pull is from Docker Hub (or any upstream). Every subsequent pull from any host in your lab hits the local cache instead.

---

## Architecture

```
                    ┌──────────────────┐
                    │    Docker Hub    │
                    │  registry-1.dkr  │
                    └────────┬─────────┘
                             │ upstream
                             │ (WAN)
                    ┌────────▼─────────┐
                    │  Registry Mirror │
                    │  10.0.20.30:5000 │
                    │  /var/lib/reg/   │
                    └────────┬─────────┘
                             │ local cache
                             │ (LAN, low latency)
        ┌────────────┐  ┌────▼────┐  ┌────────────┐
        │  SRV1      │  │  SRV2   │  │  LXC/VM    │
        │ (Proxmox)  │  │ (node)  │  │ (any host) │
        └────────────┘  └─────────┘  └────────────┘
```

One registry instance on your homelab network. Every Docker daemon is configured to use it as a mirror. Images are stored on a local disk or ZFS dataset.

---

## Deploy the Registry Mirror

### Docker Compose

```yaml
version: "3.9"

services:
  registry:
    image: registry:2
    container_name: registry-mirror
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      REGISTRY_PROXY_REMOTEURL: https://registry-1.docker.io
      REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY: /var/lib/registry
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
      REGISTRY_PROXY_USERNAME: ""
      REGISTRY_PROXY_PASSWORD: ""
    volumes:
      - ./data:/var/lib/registry
```

If you have a Docker Hub authenticated account (recommended for the 200-pull limit), set `REGISTRY_PROXY_USERNAME` and `REGISTRY_PROXY_PASSWORD`. Leave them blank for anonymous (100-pull limit).

### Health Check

Add a health check to catch issues early:

```yaml
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:5000/v2/"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 20s
```

---

## Launch and Verify

```bash
docker compose up -d
```

Check it's serving:

```bash
curl -s http://10.0.20.30:5000/v2/_catalog
# → {"repositories":[]}
```

Empty catalog is normal — nothing cached yet. Pull something through the mirror:

```bash
docker pull localhost:5000/library/alpine:latest
# → Pulling from library/alpine
# → Digest: sha256:...
```

The registry creates the proxy cache on first pull. `library/` prefix is the Docker Hub namespace for official images.

Check what's cached:

```bash
curl -s http://10.0.20.30:5000/v2/_catalog
# → {"repositories":["library/alpine"]}
```

---

## Configure Docker Daemon Clients

Every host that should use the mirror needs its Docker daemon configured. Edit `/etc/docker/daemon.json`:

```json
{
  "registry-mirrors": ["http://10.0.20.30:5000"],
  "insecure-registries": ["10.0.20.30:5000"]
}
```

The `insecure-registries` entry is required because the mirror runs on HTTP (no TLS). If you add TLS later, remove it.

Restart Docker:

```bash
systemctl restart docker
```

Verify the mirror is in use:

```bash
docker info | grep -A 1 Mirrors
# → Registry Mirrors:
# →   http://10.0.20.30:5000/
```

### Test the Mirror

```bash
# Clear local cache first
docker system prune -a

# Pull an image — first pull hits Docker Hub (slower)
time docker pull nginx:alpine

# Remove it and pull again — second pull hits local mirror (fast)
docker rmi nginx:alpine
time docker pull nginx:alpine
```

The second pull should be significantly faster — local network latency vs WAN.

---

## Storage Tuning

### ZFS Dataset

If your host uses ZFS, put the registry data on a dedicated dataset with compression:

```bash
zfs create -o compression=zstd-3 rpool/registry
```

Update the compose mount to `/var/lib/registry:/var/lib/registry` or point to the dataset's mount point.

### Disk Space

A typical homelab sees:
- 10-30 GB after a few weeks of use
- ~50-80 GB for a year of active development with multiple hosts
- More if you pull multi-platform images (arm64 + amd64)

Set a soft limit with a Docker volume size constraint or monitor with `du -sh ./data`.

### GC (Garbage Collection)

Docker registry doesn't auto-clean blobs when manifests are deleted. To reclaim space:

```bash
# Delete unused manifests (e.g., old tags)
# Registry v2 has no native tag deletion via API — use Docker CLI:
docker exec registry-mirror bin/registry garbage-collect \
    /etc/docker/registry/config.yml

# For thorough cleanup, stop the container first:
docker compose stop
docker run --rm -v ./data:/var/lib/registry \
    registry:2 bin/registry garbage-collect \
    /etc/docker/registry/config.yml
docker compose start
```

Schedule this monthly via cron:

```
0 3 1 * * cd /path/to/registry && docker compose stop && \
  docker run --rm -v ./data:/var/lib/registry registry:2 \
  bin/registry garbage-collect /etc/docker/registry/config.yml && \
  docker compose start
```

---

## Multi-Registry Proxy

You're not limited to Docker Hub. Proxy any registry:

```yaml
# For Docker Hub (default)
REGISTRY_PROXY_REMOTEURL: https://registry-1.docker.io

# For quay.io
REGISTRY_PROXY_REMOTEURL: https://quay.io

# For ghcr.io (GitHub Container Registry)
REGISTRY_PROXY_REMOTEURL: https://ghcr.io
```

Run multiple instances on different ports for different upstream registries:

| Service | Port | Upstream |
|---------|------|----------|
| `registry-docker` | 5000 | Docker Hub |
| `registry-ghcr` | 5001 | ghcr.io |
| `registry-quay` | 5002 | quay.io |

---

## Nginx Reverse Proxy (Optional)

If you want a single entry point with path-based routing to multiple registry instances, put Nginx in front:

```nginx
upstream docker-hub {
    server 127.0.0.1:5000;
}

upstream ghcr {
    server 127.0.0.1:5001;
}

server {
    listen 443 ssl;
    server_name registry.lab;

    location /docker/ {
        rewrite ^/docker(/.*)$ $1 break;
        proxy_pass http://docker-hub;
    }

    location /ghcr/ {
        rewrite ^/ghcr(/.*)$ $1 break;
        proxy_pass http://ghcr;
    }
}
```

Then configure each Docker daemon with `registry-mirrors: ["https://registry.lab/docker"]`.

---

## Performance Impact

In a real homelab with 3-4 Docker hosts and nightly rebuilds:

| Metric | Without Mirror | With Mirror |
|--------|---------------|-------------|
| First pull (nginx:alpine ~24 MB) | ~8s (WAN) | ~8s (WAN, first time) |
| Second pull (same host) | ~8s again | ~1s (LAN) |
| Pull across 3 hosts | ~24s total | ~10s total (1 WAN + 2 LAN) |
| API rate limit hit | ~every 2 days with rebuilds | rarely |
| Bandwidth saved (weekly) | — | ~500 MB-2 GB |

The savings compound with every host and every rebuild. For CI runners or developers iterating on Dockerfiles, the mirror is the difference between "waiting for downloads" and "instant."

---

## Security Notes

- The mirror as described runs **HTTP only**. On a segmented homelab VLAN (non-routable, no WAN exposure), this is acceptable.
- For multi-user or internet-facing setups, add TLS. The official registry image supports `REGISTRY_HTTP_TLS_CERTIFICATE` and `REGISTRY_HTTP_TLS_KEY`.
- The proxy cache stores all pulled images. If you pull private images from a registry, the cached blobs persist until garbage-collected.

---

## Gotchas

**Registry-mirrors only catch `docker pull` from Docker Hub.** If your compose files use `image: ghcr.io/org/app:latest`, that goes directly to ghcr.io unless you configure a second mirror or use the Nginx proxy approach above.

**Digest pinning bypasses the mirror.** If a pull uses a digest (`image@sha256:...`) instead of a tag, Docker skips the mirror proxy. Use tags for cache hits.

**The registry does not sync proactively.** It only caches what you pull. To pre-warm the cache for a new host, run a batch pull script overnight.

**Bloat from multi-arch.** If your lab mixes amd64 and arm64 (e.g., Raspberry Pi + Proxmox), the registry stores both architectures. This doubles storage. Target your architecture with `--platform` pulls.

---

## Maintenance Summary

```bash
# Check disk usage
du -sh /opt/registry/data/

# List cached repos
curl -s http://10.0.20.30:5000/v2/_catalog | jq .

# Garbage collect
docker exec registry-mirror bin/registry garbage-collect \
    /etc/docker/registry/config.yml

# Verify Docker daemon uses mirror
docker info | grep -A 1 Mirrors
```

That's it. One `docker compose up -d`, one `daemon.json` edit per host, and your lab stops hammering Docker Hub.
