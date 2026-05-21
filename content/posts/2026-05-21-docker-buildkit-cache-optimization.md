---
title: "Docker BuildKit Cache Optimization — Speed Up Container Builds"
description: "Speed up Docker builds with BuildKit cache mounts, inline and registry cache export, and practical Dockerfile patterns for homelab CI/CD that cut build times by 80%."
date: 2026-05-21T09:30:00-04:00
tags:
  - docker
  - homelab
  - linux
  - performance
  - devops
keywords:
  - Docker BuildKit cache optimization homelab
  - cache mount type docker build speed
  - Docker inline cache registry export
  - BuildKit buildx cache-from cache-to
  - Dockerfile package cache mount apt pip npm
  - multi-stage build cache optimization
  - Docker compose build cache shared
summary: "Cut Docker build times by 80% using BuildKit cache mounts, inline/registry cache export, and optimized Dockerfile patterns — with real homelab examples for apt, pip, npm, and Go builds."
canonical: "https://blog.gntech.me/posts/2026-05-21-docker-buildkit-cache-optimization/"
---

If you build Docker images in your homelab — for self-hosted
applications, CI/CD pipelines, or custom toolchains — you have
felt the pain of waiting minutes for `apt-get install` or
`pip install` to re-run on every build. Docker's layer cache
helps when only the Dockerfile changes, but the moment your
source code changes or a `COPY` busts an earlier layer, every
downstream `RUN` command rebuilds from scratch.

BuildKit, the default build backend since Docker Engine 23.0,
ships three powerful cache features that most homelab setups
never configure:

1. **Cache mounts** (`--mount=type=cache`) — persist package
   downloads across builds without bloating the image.
2. **Inline cache** — embed build cache metadata into the image
   itself so that future pulls can reuse layers.
3. **Registry cache** (`--cache-to` / `--cache-from`) — push
   and pull cache blobs to a container registry independently
   of the image.

This guide covers all three with real Dockerfiles and
Compose configurations you can apply immediately.

---

## Why Default Docker Builds Are Slow

Every `RUN` instruction in a Dockerfile produces a layer. Docker
caches each layer keyed on the preceding command text and its
input files. If a `COPY` changes the `requirements.txt`, the
`RUN pip install -r requirements.txt` layer cache is invalidated,
and pip downloads and compiles everything from scratch.

With cache mounts, that `pip install` can reuse a persistent
download cache on the host, skipping network fetches even when
the layer rebuilds. The difference is dramatic:

| Scenario | Without cache mount | With cache mount |
|----------|--------------------|-----------------|
| `apt-get install` (20 packages) | 45 s | 4 s |
| `pip install` (large requirements.txt) | 120 s | 15-20 s |
| Go module download | 60 s | 2-3 s |
| npm ci | 40 s | 8 s |

---

## Enabling BuildKit

BuildKit is the default in Docker Engine 23.0+, but verify it is
active:

```bash
docker info | grep BuildKit
# Output: BuildKit: true
```

If you see `false`, set the environment variable:

```bash
export DOCKER_BUILDKIT=1
```

For `docker compose build`, BuildKit is used automatically in
modern Compose v2. You can also force it per build:

```bash
DOCKER_BUILDKIT=1 docker build .
```

---

## Cache Mounts — The Biggest Win

A cache mount binds a persistent directory on the host into the
build container. The cache survives image rebuilds and is shared
across concurrent builds. Critically, it is **not** part of the
final image — the layer stays clean.

### apt Cache Mount

Replace a plain `RUN apt-get install` with a cache mount for
`/var/cache/apt` and `/var/lib/apt/lists`:

```dockerfile
# Dockerfile
FROM ubuntu:24.04 AS base

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        nginx \
        postgresql-client && \
    rm -rf /var/lib/apt/lists/*
```

The `sharing=locked` flag ensures that concurrent builds do not
corrupt the apt cache. The `--no-install-recommends` flag keeps
image size lean.

### pip Cache Mount

Python projects suffer heavily from pip re-downloading wheels.
Add a cache mount for the pip cache directory:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY . .
```

Even when `requirements.txt` changes and the layer rebuilds,
already-downloaded wheels in `/root/.cache/pip` are reused. The
`--no-cache-dir` flag here controls pip's runtime cache (inside
the image), not the BuildKit cache mount.

### npm / Yarn Cache Mount

```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY package*.json .

RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline

COPY . .
```

For Yarn:

```dockerfile
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn \
    yarn install --frozen-lockfile
```

### Go Module Cache Mount

```dockerfile
FROM golang:1.24-alpine AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 go build -o /app .
```

The `go mod download` layer uses the cache mount for module
binaries. Even if `go.mod` changes, previously downloaded
modules are reused.

---

## Combining Cache Mounts with Multi-Stage Builds

Multi-stage builds already keep your final image small. Add
cache mounts on every stage that downloads packages:

```dockerfile
# ---- Build stage ----
FROM golang:1.24-alpine AS builder

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache git ca-certificates

WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 go build -ldflags="-s -w" -o /app .

# ---- Runtime stage ----
FROM alpine:3.20
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache ca-certificates tzdata

COPY --from=builder /app /app
EXPOSE 8080
CMD ["/app"]
```

The build stage gets Go module caching; the runtime stage gets
apk caching. The final image is ~15 MB and both builds benefit
from persistent caches.

---

## Build Cache Export — Inline and Registry

Cache mounts speed up builds on a single host. If you rebuild on
a different machine — another homelab node, a CI runner, or a
friend's server — the cache starts empty. BuildKit solves this
with cache export.

### Inline Cache

Inline cache embeds cache metadata into the image manifest. Any
node that pulls the image can reuse the cached layers:

```bash
docker build \
  --cache-from app:latest \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -t app:latest .
```

Or with `docker buildx`:

```bash
docker buildx build \
  --cache-from type=registry,ref=registry.home.lab/app:cache \
  --cache-to type=inline \
  -t registry.home.lab/app:latest \
  --push .
```

**Trade-off:** Inline cache increases the image manifest size.
For multi-architecture builds, use registry cache instead.

### Registry Cache (Recommended)

Registry cache pushes cache blobs to a separate tag or cache
repo. This is the fastest option and decouples cache from images.

```bash
# Build with cache export to registry
docker buildx build \
  --cache-from type=registry,ref=registry.home.lab/app:cache \
  --cache-to type=registry,ref=registry.home.lab/app:cache,mode=max \
  -t registry.home.lab/app:latest \
  --push .
```

The `mode=max` flag stores cache for all layers, not just the
exported ones. Without it (`mode=min`), only layers in the final
image are cached.

On a subsequent build (even on a different host):

```bash
docker buildx build \
  --cache-from type=registry,ref=registry.home.lab/app:cache \
  -t registry.home.lab/app:latest \
  --push .
```

BuildKit fetches the cache manifest, compares it with the local
build context, and reuses every layer it can.

---

## Docker Compose BuildKit Integration

For homelab stacks built with Compose, add a shared build cache
by setting the `BUILDKIT_PROGRESS` and composing bake files, or
use the Compose build section:

```yaml
# compose.yaml
services:
  app:
    build:
      context: .
      cache_from:
        - type: registry
          ref: registry.home.lab/app:cache
      cache_to:
        - type: registry
          ref: registry.home.lab/app:cache
          mode: max
```

Build with the compose builder:

```bash
docker compose build --push
```

For cache mounts inside the Dockerfile, no Compose changes are
needed — they work automatically.

---

## Real-World Homelab Workflow

Here is the full workflow I use for a custom Go web service
built daily on my Proxmox CI runner:

**`Dockerfile`:**

```dockerfile
FROM golang:1.24-alpine AS builder
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache git
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 go build -o /svc .

FROM alpine:3.20
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache ca-certificates
COPY --from=builder /svc /svc
EXPOSE 8080
CMD ["/svc"]
```

**Build script (`build-push.sh`):**

```bash
#!/bin/bash
set -euo pipefail

REGISTRY="registry.home.lab"
IMAGE="${REGISTRY}/my-web-svc"
CACHE_TAG="${IMAGE}:cache"

docker buildx build \
  --cache-from type=registry,ref=${CACHE_TAG} \
  --cache-to type=registry,ref=${CACHE_TAG},mode=max \
  -t ${IMAGE}:latest \
  -t ${IMAGE}:$(git rev-parse --short HEAD) \
  --push \
  .
```

**First build:** ~90 seconds (Go module download + compilation).
**Subsequent builds (no source change):** ~3 seconds (everything
cached).
**Build with code change:** ~12 seconds (compilation only,
modules cached).

---

## Common Pitfalls

### Bind Mounts vs Cache Mounts

A bind mount (`--mount=type=bind`) gives the build container
read-only access to a host file or directory at build time. A
cache mount (`--mount=type=cache`) is a writable persistent
directory managed by BuildKit. Use bind mounts for secrets and
source; use cache mounts for package downloads.

### Clean the Cache

If a cache mount becomes stale or corrupted, purge it:

```bash
docker builder prune --all
```

Or prune only cache mounts:

```bash
docker builder prune --filter type=exec.cachemount
```

### Multi-Architecture Caches

Registry cache works across architectures if you use the same
cache ref. BuildKit stores per-architecture cache blobs and
selects the right ones at build time.

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --cache-from type=registry,ref=${CACHE_TAG} \
  --cache-to type=registry,ref=${CACHE_TAG},mode=max \
  -t ${IMAGE}:latest --push .
```

### Docker Desktop and Colima

Cache mounts work on all platforms. On macOS with Docker Desktop
or Colima, the cache lives inside the VM. It persists across
builds and survives `docker system prune` — but not VM resets.

---

## Summary

BuildKit cache mounts and registry cache export are the two
highest-leverage optimizations you can make for Docker build
performance. Cache mounts eliminate redundant network fetches on
every rebuild, while registry cache accelerates builds across
CI runners and homelab nodes.

Apply these patterns to every Dockerfile that downloads packages:

- Add `--mount=type=cache,target=/var/cache/apt` for apt-based
  images.
- Add `--mount=type=cache,target=/root/.cache/pip` for Python.
- Add `--mount=type=cache,target=/go/pkg/mod` for Go.
- Export caches to your local registry with `--cache-to
  type=registry,mode=max`.

Your CI pipeline and your Saturday-afternoon rebuilds will thank
you.
