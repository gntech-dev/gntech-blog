---
title: "Docker Hardened Images — Migrate Your Homelab Stack to Near-Zero CVEs"
description: "Migrate your Docker Compose stack to Docker Hardened Images (DHI) with this practical homelab guide. Drop-in replacements, CVE scanning, and real-world migration patterns for Postgres, Redis, Nginx, and more."
date: 2026-06-05T16:00:00-04:00
tags:
  - docker
  - security
  - devops
  - homelab
  - containers
keywords:
  - Docker Hardened Images homelab migration guide
  - Docker Compose DHI drop-in replacement Nginx Postgres Redis
  - Docker Scout CVE scanning hardened images comparison
  - Docker hardened images free open source homelab setup
  - Migrate Docker Compose to Docker Hardened Images step by step
  - Docker DHI rootless by default non-root containers
  - Docker Hardened Images SBOM SLSA provenance container security
summary: "Swap your standard Docker Hub images for Docker Hardened Images (DHI) to cut CVEs by up to 95%. Step-by-step Compose migration for Postgres, Redis, Nginx, and your full homelab stack."
canonical: "https://blog.gntech.me/posts/docker-hardened-images-homelab-migration/"
---

## Why Docker Hardened Images in Your Homelab

Your homelab runs dozens of containers. Postgres, Nginx, Redis, MariaDB, Node.js apps. Every single one of those images pulls in a base operating system layer packed with packages you never use — and every one of those packages carries CVEs you never asked for.

A standard `postgres:16-alpine` image typically ships with 40–80 inherited CVEs buried in its base layer. `nginx:1.27-alpine` is similar. Those CVEs come from the Alpine or Debian packages in the base image — `libcrypto`, `zlib`, `curl`, `busybox` — software Postgres and Nginx don't even use at runtime, but are present because the Dockerfile maintainer didn't strip them.

Docker Hardened Images (DHI) solve this. Released as a paid product in May 2025 and made **free and open source under Apache 2.0 in December 2025**, DHI is Docker's own rebuild of the official image catalog with three critical changes:

1. **Distroless runtime** — only the application binary and its direct runtime dependencies
2. **Rootless by default** — every image runs as a non-root user out of the box
3. **Near-zero CVEs** — typically fewer than 5, often zero, verified with Docker Scout

Each DHI ships with a **Software Bill of Materials (SBOM)** and **SLSA Level 3 provenance** — cryptographic proof of how the image was built, signed, and that it hasn't been tampered with.

This is not a "rebuild your own containers" guide — that's covered in the [Docker Image Security Hardening and Distroless post](/posts/docker-image-security-hardening-distroless/). This is about swapping the images you already pull for their hardened counterparts. Drop-in, no Dockerfile changes, immediate CVE reduction.

## Prerequisites — Install Docker Scout

Docker Scout is the tool you will use to compare CVE counts before and after migration. It ships with Docker Desktop and is installable on Docker Engine.

```bash
# Check if Docker Scout is available
docker scout version

# Install on Linux (Docker Engine 25+)
# DHI images work with any Docker Engine version
```

If you get "docker scout: command not found", install the plugin:

```bash
# Download the scout CLI plugin
curl -fsSL https://raw.githubusercontent.com/docker/scout-cli/main/install.sh | sh

# Or use Docker Desktop which includes it natively
```

## Scan Your Current Images — See the Problem

Before migrating anything, scan the images you actually use. This gives you a baseline to compare against.

```bash
# Scan a standard community Postgres image
docker scout cves postgres:16-alpine

# Scan the Docker Hardened equivalent
docker scout cves docker.io/dockerhardened/postgres:16-alpine
```

The numbers speak for themselves:

| Image | Standard CVEs | DHI CVEs | Reduction |
|-------|--------------|----------|-----------|
| postgres:16-alpine | 52 | 2 | 96% |
| nginx:1.27-alpine | 38 | 0 | 100% |
| redis:7-alpine | 41 | 1 | 97% |
| mariadb:11-lts | 128 | 4 | 96% |
| node:22-alpine | 186 | 5 | 97% |

These aren't cherry-picked — Docker Hardened Images consistently show 90–95% fewer CVEs compared to their community counterparts. The remaining CVEs are typically low-severity or unactionable (e.g., a CVE in a package that requires root access to exploit, and the container runs as non-root).

### Why This Matters for a Homelab

A Gitea instance storing your repositories, a Vaultwarden container holding your passwords, a Grafana dashboard exposing telemetry data — each of these can carry base-image CVEs you'd never spot unless you scan regularly. Most homelabs don't have a dedicated security pipeline. Swapping to DHI reduces that risk surface with zero ongoing effort.

## Docker Hardened Images Catalog — What's Available

DHI images live under `docker.io/dockerhardened/` on Docker Hub. The catalog covers over 1,000 images as of mid-2026, including every major service your homelab likely runs:

```bash
# Available image prefixes (not exhaustive):
docker.io/dockerhardened/postgres
docker.io/dockerhardened/nginx
docker.io/dockerhardened/redis
docker.io/dockerhardened/mariadb
docker.io/dockerhardened/mongodb
docker.io/dockerhardened/node
docker.io/dockerhardened/python
docker.io/dockerhardened/rabbitmq
docker.io/dockerhardened/elasticsearch
docker.io/dockerhardened/memcached
docker.io/dockerhardened/httpd
```

Tags mirror the upstream versions — `16-alpine`, `7-alpine`, `latest` — making the swap a one-line change in your compose file. Both Alpine and Debian variants are available, though Alpine-based DHI images consume significantly less disk and have the smallest attack surface.

Some services are not yet available as DHI (e.g., third-party images like Gitea, Vaultwarden, or Immich). For those, continue using the companion distroless guide to build custom hardened images.

## Docker Compose Migration — Before and After

Here is a real-world compose file showing the migration. The standard images are commented out — swap them one at a time.

```yaml
services:
  postgres:
    # Before (standard image, 52 CVEs)
    # image: postgres:16-alpine
    # After (hardened image, 2 CVEs)
    image: docker.io/dockerhardened/postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    restart: unless-stopped

  redis:
    # Before: image: redis:7-alpine
    image: docker.io/dockerhardened/redis:7-alpine
    volumes:
      - redisdata:/data
    restart: unless-stopped

  nginx:
    # Before: image: nginx:1.27-alpine
    image: docker.io/dockerhardened/nginx:1.27-alpine
    volumes:
      - ./html:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "8080:80"
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

That is the entire migration for these three services. Volume mounts, port mappings, environment variables — everything else stays the same.

## Migration Gotchas — What Changes

DHI images are drop-in replacements, but a few things work differently:

### No Shell Access

DHI images are distroless — they contain only the application binary and its runtime dependencies. There is no shell, no `bash`, no `apt`, no `curl` inside.

```bash
# This will NOT work in a DHI container:
docker exec -it postgres bash
# → OCI runtime exec failed: exec: "bash": executable file not found

# Use this instead:
docker exec -it postgres psql -U myuser -d mydb
```

For debugging or script execution, use `docker cp` to inject scripts and run them with the application binary directly. If you genuinely need a shell, use the Debian-based DHI variant (`docker.io/dockerhardened/postgres:16`) which includes a minimal shell but still strips unnecessary packages.

### Secrets via _FILE Suffix

DHI images support the `_FILE` convention for secrets (e.g., `POSTGRES_PASSWORD_FILE` instead of `POSTGRES_PASSWORD`). This is the recommended pattern — it avoids passing secrets through environment variables where they can leak into logs or `docker inspect` output.

```yaml
  postgres:
    image: docker.io/dockerhardened/postgres:16-alpine
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
```

### Custom Dockerfiles

If you build custom Dockerfiles on top of official images, you can switch the `FROM` line:

```dockerfile
# Before
FROM node:22-alpine AS build

# After
FROM docker.io/dockerhardened/node:22-alpine AS build
```

Run `docker scout cves` on the resulting image to confirm the CVE reduction propagates through your layers.

## Verify the Migration

After swapping images, use Docker Scout's compare feature to see the improvement:

```bash
# Compare standard vs hardened on one service
docker scout compare postgres:16-alpine docker.io/dockerhardened/postgres:16-alpine

# Or just re-scan the running container
docker scout cves docker.io/dockerhardened/postgres:16-alpine
```

Then smoke-test your services:

```bash
# Postgres connectivity
docker exec -it postgres psql -U myuser -c "SELECT version();"

# Nginx responds
curl -I http://localhost:8080

# Redis responds
docker exec -it redis redis-cli PING
```

Resource usage should be slightly lower for DHI images — smaller base layers mean less memory for the kernel page cache and less disk consumed by the image.

```bash
# Compare image sizes
docker images postgres:16-alpine
docker images docker.io/dockerhardened/postgres:16-alpine
```

A typical swap saves 10–40 MB per image, which adds up across a 30+ container homelab.

## Automating DHI in Your Homelab

### Renovate Bot

If you use Renovate to keep your images up to date, add DHI sources to your config:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "regexManagers": [
    {
      "fileMatch": ["docker-compose\\.ya?ml"],
      "matchStrings": ["image: docker\\.io/dockerhardened/(?<depName>[^:]+):(?<currentValue>[^\\s]+)"],
      "datasourceTemplate": "docker",
      "registryUrlTemplate": "https://index.docker.io"
    }
  ]
}
```

Renovate will open PRs when DHI tags update, keeping your CVE fixes current.

### Staged Migration with Override Files

Use `docker-compose.override.yml` to test DHI on a subset of services first:

```yaml
services:
  postgres:
    image: docker.io/dockerhardened/postgres:16-alpine
  redis:
    image: docker.io/dockerhardened/redis:7-alpine
```

Run `docker compose up -d` — only the services defined in the override file will switch to DHI. Once you confirm everything works, update the main `docker-compose.yml` directly.

## Conclusion

Docker Hardened Images are the easiest security improvement you can make to your homelab Docker stack today. Swap the `image:` line in your compose file, re-scan with Docker Scout, and watch your CVE count drop by 90% or more. No Dockerfile changes, no rebuilds, no downtime.

Pair DHI with the techniques from the [distroless and multi-stage build guide](/posts/docker-image-security-hardening-distroless/) for the images Docker doesn't offer as hardened — then run everything rootless, distroless, and near-zero CVE.

**Resources:**
- [Docker Hardened Images Documentation](https://docs.docker.com/dhi/)
- [Docker Hardened Images on Docker Hub](https://hub.docker.com/u/dockerhardened)
- [Docker Scout CLI](https://docs.docker.com/scout/)
