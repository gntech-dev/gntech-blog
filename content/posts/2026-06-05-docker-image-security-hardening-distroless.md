---
title: "Docker Image Security Hardening — Multi-Stage Builds and Distroless"
description: "Harden your Docker images with multi-stage builds, distroless base images, Trivy vulnerability scanning, and runtime security options. A practical homelab guide to reducing CVEs and attack surface."
date: 2026-06-05T13:30:00-04:00
tags:
  - docker
  - security
  - linux
  - homelab
  - devops
keywords:
  - Docker image security hardening homelab guide
  - Multi-stage Docker builds optimization techniques
  - Distroless base images Docker container security
  - Docker vulnerability scanning Trivy Docker Scout
  - Docker runtime security no-new-privileges read-only rootfs
  - Docker container non-root user best practices
  - Dockerfile optimization for small secure images
summary: "Harden your Docker images with multi-stage builds, distroless base images, and runtime security options. A practical guide to reducing image size and CVEs in your homelab."
canonical: "https://blog.gntech.me/posts/docker-image-security-hardening-distroless/"
---

## Why Docker Image Security Matters in Your Homelab

Your homelab runs Docker containers — maybe a lot of them. MiniO, Grafana, Nginx, PostgreSQL, Gitea, Uptime Kuma. Most of these come from public images on Docker Hub. And most of them ship with build artifacts, unused libraries, package manager caches, and shells you never need at runtime.

The security problem is straightforward: every unnecessary package and binary in your container image is an attack surface. When `FROM ubuntu:22.04` pulls a 77 MB base image and your Dockerfile adds build dependencies that inflate it past 1 GB, you're not just wasting disk — you're shipping every CVE in every one of those packages to your homelab.

Docker's April 2026 Hardened Images update reported that hardened images have roughly 90–95% fewer CVEs than their standard counterparts, with some images running at near-zero known vulnerabilities. Google's distroless project has shown similar results for years.

This guide covers three layers of Docker image security you can apply in your homelab right now:

1. **Build-time hardening** — multi-stage Dockerfiles that separate build and runtime
2. **Image choice** — distroless, slim, and hardened base images with minimal attack surface
3. **Runtime security** — drop capabilities, enforce read-only filesystems, run as non-root

You don't need to rebuild every image. Runtime hardening alone reduces risk on existing containers significantly.

## Multi-Stage Builds for Smaller, Cleaner Images

Multi-stage builds let you use one Dockerfile with multiple `FROM` statements. Build tools and dependencies live in an early stage, while the final runtime image copies only what's needed.

### Go Application Example

```dockerfile
# Stage 1: build
FROM golang:1.23-alpine AS builder
RUN apk add --no-cache ca-certificates git
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/my-service .

# Stage 2: runtime
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/my-service /app/my-service
USER 1001:1001
ENTRYPOINT ["/app/my-service"]
```

The `scratch` base is completely empty — no shell, no package manager, no utilities. The final image is exactly one binary plus CA certificates, typically 10–20 MB instead of 500 MB+.

### Python Application Example

Python is trickier because you need a Python interpreter at runtime. The multi-stage approach still cuts the image drastically:

```dockerfile
# Stage 1: install dependencies
FROM python:3.12-alpine AS builder
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --user gunicorn fastapi uvicorn[standard]

# Stage 2: runtime
FROM python:3.12-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY --from=builder /root/.local /root/.local
WORKDIR /app
COPY app.py .
ENV PATH=/root/.local/bin:$PATH
USER appuser
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
```

Key improvements over a single-stage Dockerfile:
- Package archives in `/root/.cache/pip` don't persist into the final image because the `RUN --mount=type=cache` mount disappears after that layer
- The final image is based on `-alpine` (only ~50 MB) instead of `python:3.12` full (~335 MB)
- The non-root user is created explicitly in the `RUN` layer

### Cache Mounts for Faster Builds

When developing custom homelab Dockerfiles (custom Nginx with modules, home automation Python scripts, data processing pipelines), use cache mounts to avoid re-downloading packages:

```dockerfile
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    libnginx-mod-http-brotli \
    nginx-extras
```

## Choosing Secure Base Images — Distroless and Slim Variants

Not every image you consume is one you build. For off-the-shelf containers, your security stance is determined by the upstream maintainer's base image choice. Here's how the options compare:

| Aspect | Full Distro | Slim | Distroless | Docker Hardened |
|--------|------------|------|------------|-----------------|
| Size | 150–800 MB | 30–80 MB | 5–50 MB | Variable |
| Shell | Yes | Yes | No | Varies |
| Package manager | Yes | Limited | No | No |
| `apt` upgrade | Manual | Manual | Not needed | Auto-patched |
| CVEs | High | Medium | Low | Near-zero |
| Debugging | Easy | Moderate | Hard (no shell) | Moderate |

Google's **distroless** images (`gcr.io/distroless/base`, `gcr.io/distroless/python3-debian12`, `gcr.io/distroless/java17-debian12`) contain only your application and its runtime dependencies. There is no shell, no `apt`, no `curl`, no `ls` — which means no way to exploit those tools even if an attacker gets code execution.

Switch to distroless images where possible in your Docker Compose files:

```yaml
services:
  # Instead of:
  # image: python:3.12-slim
  # Use:
  image: gcr.io/distroless/python3-debian12:latest
```

Docker's **Hardened Images** (`docker.io/library/nginx:hardened`, `docker.io/library/python:hardened`) are a newer option. As of April 2026, they see over 500,000 daily pulls and are continuously rebuilt from source as CVEs are patched. They integrate with Docker Scout for attestation and SBOM generation.

For a practical homelab strategy: use `-slim` variants for general services (Grafana, Prometheus) and distroless or hardened images for security-critical services (reverse proxies, authentication gateways, public-facing APIs).

## Vulnerability Scanning — Trivy in Your Docker Pipeline

You can't fix what you don't measure. Scan your images regularly for CVEs. **Trivy** from Aqua Security is the go-to open-source scanner for homelabs.

### Basic Scan

```bash
# Scan a local image
trivy image myapp:latest

# Scan with severity filter and ignore unfixed packages
trivy image --severity CRITICAL,HIGH --ignore-unfixed nginx:latest

# Scan a Docker Hub image directly
trivy image docker.io/library/nginx:1.27-alpine
```

### Scanning in a CI Pipeline

If you use Gitea Actions with your self-hosted runner, add a scan step to catch issues before deployment:

```yaml
- name: Scan image for vulnerabilities
  run: |
    trivy image \
      --severity CRITICAL,HIGH \
      --ignore-unfixed \
      --exit-code 1 \
      myapp:${GITEA_COMMIT_SHA}
```

`--exit-code 1` makes the pipeline fail if critical or high CVEs are found. In a homelab context, you may want `--exit-code 0` with a human review instead — few homelabs have dedicated security teams.

### Docker Scout Alternative

If you prefer Docker's native tooling:

```bash
docker scout cves myapp:latest
docker scout recommendations myapp:latest
docker scout quickview myapp:latest
```

Docker Scout connects with Docker Hub's vulnerability database and can suggest base image upgrades automatically. It's included with Docker Desktop and Docker Engine 24+.

### Interpreting Results

A typical scan of a full `ubuntu:22.04`-based image returns 50–200 CVEs (depending on the packages). A slim variant of the same image drops to 20–80. A distroless or hardened image often returns 0–5, and those are typically in glibc or OpenSSL — infrastructure you genuinely need.

For each finding:
- **Fixed version available** → rebuild with the patched base image
- **Not fixed yet** → monitor the CVE, consider temporarily switching to a different base
- **False positive** → suppress with `.trivyignore`:

```
# .trivyignore
CVE-2024-XXXXX  # Not exploitable in our configuration
```

## Runtime Security Hardening for Docker Containers

Image hardening reduces risk at build time. Runtime security controls reduce risk when the container is running. These apply to **any** container, including ones you pull off-the-shelf without modifications.

### Run as Non-Root

Most official images now run as non-root by default, but check. In your own Dockerfiles:

```dockerfile
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
USER appuser:appgroup
```

### Drop Capabilities

Linux capabilities control what a process can do — even as root inside the container. Drop everything, then add back only what's needed:

```bash
docker run --cap-drop ALL --cap-add NET_BIND_SERVICE nginx:alpine
```

Nginx needs `NET_BIND_SERVICE` to bind to port 80. A database container doesn't need any extra capabilities at all.

### Read-Only Root Filesystem

Prevent the container from writing to its own filesystem:

```bash
docker run --read-only --tmpfs /run:noexec,nosuid,size=64M \
    --tmpfs /tmp:noexec,nosuid,size=32M nginx:alpine
```

Write-capable directories are mounted explicitly as tmpfs volumes. Any exploit that tries to write a file to `/usr`, `/etc`, or `/var` will fail because those paths are read-only.

### Full Docker Compose Runtime Example

Here's how all three options look in a `docker-compose.yml`:

```yaml
version: "3.8"

services:
  web:
    image: nginx:1.27-alpine
    ports:
      - "127.0.0.1:8080:80"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - NET_RAW
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=32M
      - /var/cache/nginx:noexec,nosuid,size=128M
      - /run:noexec,nosuid,size=64M
    user: "101:101"  # nginx user within the container
    restart: unless-stopped
```

This configuration:
- Prevents privilege escalation (`no-new-privileges`)
- Strips all capabilities, then adds only `NET_BIND_SERVICE` (bind port 80) and `NET_RAW` (health check pings)
- Makes the entire root filesystem read-only
- Mounts tmpfs volumes for Nginx's cache, PID file, and temp directories
- Runs as the nginx user (UID 101)

## Putting It All Together — A Hardened Docker Compose Stack

The following stack applies both image-level and runtime security to a static site served by Nginx:

```yaml
version: "3.8"

services:
  static-site:
    # Use a slim, hardened base image
    image: nginx:1.27-alpine
    ports:
      - "127.0.0.1:8080:80"
    volumes:
      - ./html:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=16M
      - /var/cache/nginx:noexec,nosuid,size=64M
      - /var/run:noexec,nosuid,size=16M
    user: "101:101"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped
```

All volumes are mounted `:ro` to prevent writes to config and content directories. Logging is capped at 30 MB total. The container runs with no extra capabilities beyond binding its network port.

Apply the same pattern to PostgreSQL, Redis, MinIO, and any other stateful service by adding `:ro` bind mounts for config files, tmpfs for writable runtime directories, and capability drops for everything except what the process genuinely needs.

## Conclusion

Docker image security in your homelab doesn't require an enterprise security team. Three practical steps make a measurable difference:

1. **Build-time** — use multi-stage Dockerfiles to exclude build artifacts and unnecessary packages from your final images
2. **Image choice** — prefer `-slim`, distroless, or Docker Hardened Images. Each shaves hundreds of packages and their associated CVEs
3. **Runtime** — apply `no-new-privileges`, drop all capabilities, and set `read_only: true` on every compose service

Start with layer 3 (runtime hardening) — it requires zero build changes and works on any existing Docker Compose stack. Then move up to layer 2 (slimmer base images) and layer 1 (custom multi-stage Dockerfiles) as you maintain and rebuild your own images.

Run `trivy image nginx:latest` on your homelab right now. The results will tell you exactly where to start.
