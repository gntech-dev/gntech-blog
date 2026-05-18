---
title: "Docker Multi-Stage Builds — Practical Guide for Homelab"
description: "Reduce Docker images from 1.2GB to under 50MB with multi-stage builds. Real Dockerfile examples for Go, Python, Node.js, and homelab-optimized production images."
date: 2026-05-18T07:00:00-04:00
tags:
  - docker
  - docker-compose
  - containers
  - homelab
  - security
keywords:
  - Docker multi-stage builds guide
  - reduce Docker image size
  - Dockerfile optimization homelab
  - distroless base images Docker
  - Go Docker scratch image build
  - Python slim Docker image production
  - Docker build cache optimization
summary: "Master Docker multi-stage builds to shrink production images from 1.2GB to under 50MB. Covers Go, Python, and Node.js patterns with real Dockerfiles and build cache strategies."
canonical: "https://blog.gntech.me/posts/docker-multistage-builds/"
---

Docker images in the wild easily balloon past 1 GB. A `python:3.12`
base with your app and a few pip packages weighs over a gigabyte. The
same Go binary compiled from scratch fits in 6 MB. The difference is
not the code — it is everything the compiler left behind.

Multi-stage builds let you use a full build environment with compilers,
dev headers, and debug tools in one stage, then copy only the compiled
artifact to a minimal runtime stage. The build tools vanish from the
final image. Your homelab disk, registry storage, and deployment
bandwidth all benefit from the size reduction.

This guide covers multi-stage build patterns for the three languages
you are most likely to use in homelab automation — Go, Python, and
Node.js — with real Dockerfiles, cache strategies, and security
hardening you can apply today.

---

## Why Multi-Stage Builds Matter in a Homelab

A single fat image might not seem like a problem when you have a
terabyte of storage. But consider the compounding effect:

- **Registry storage**: Five services, each rebuilt weekly with a 1 GB
  image means 5 GB of layers retained per version
- **Backup bandwidth**: Offsite backups of Docker volumes include the
  image cache unless you exclude `/var/lib/docker`
- **Pull time**: A 50 MB image pulls in under 2 seconds on a gigabit
  link versus 30+ seconds for a 1 GB image
- **Attack surface**: Every package in the base image is a potential
  CVE. Distroless or scratch images have near-zero CVEs

The pattern is always the same — build in one stage, copy artifacts to
another:

```dockerfile
# Stage 1: Build
FROM golang:1.23 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/my-service ./cmd

# Stage 2: Run
FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /app/my-service /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/my-service"]
```

The final image is `golang:1.23` (800 MB) replaced by `alpine:3.21`
(7 MB) with just the binary. That is the core idea. The rest is
optimization and language-specific nuance.

---

## Go: From Scratch for the Smallest Images

Go is the ideal candidate for multi-stage builds because it compiles
to a statically-linked binary with zero runtime dependencies. You can
use the ultimate minimal base — `FROM scratch` — which is an empty
filesystem.

### Minimal Go Dockerfile

```dockerfile
# Build stage
FROM golang:1.23-alpine AS builder
RUN apk add --no-cache git ca-certificates
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# Build with full static linking
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /app/server ./cmd/server

# Runtime stage — literally nothing but the binary
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

The `-ldflags="-s -w"` strips debug symbols and DWARF tables, shaving
another 30-40% off the binary size. Combined with `FROM scratch`, your
final image is the binary plus CA certs — typically 6-15 MB.

### Health Check and Config Files

If your Go service needs configuration files, copy them explicitly:

```dockerfile
FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /app/server /server
COPY config.yaml /etc/server/config.yaml
COPY static/ /static/
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
    CMD ["/server", "health"]
ENTRYPOINT ["/server"]
```

### Build and Verify

```bash
# Build the image
docker build -t my-go-service:latest .

# Check final size
docker images my-go-service:latest
# REPOSITORY       TAG       IMAGE ID       CREATED          SIZE
# my-go-service    latest    abc123def456   10 seconds ago   14.2 MB

# Compare with a single-stage build
docker build -t my-go-service:fat -f Dockerfile.single-stage .
# 14.2 MB vs ~950 MB
```

### Go Build Cache Optimization

Docker build cache is per-layer. Reordering your Dockerfile to cache
dependency downloads saves minutes per rebuild:

```dockerfile
FROM golang:1.23-alpine AS builder
WORKDIR /build

# Cache layer 1: download dependencies (only changes when go.mod changes)
COPY go.mod go.sum ./
RUN go mod download

# Cache layer 2: copy and build source (rebuilds on every code change)
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/server .
```

This separation means adding a line of code does NOT re-download all
modules. The `go mod download` layer is cached and reused.

---

## Python: Slimming the 1.2 GB Behemoth

Python does not compile to a standalone binary. Your application
requires the Python interpreter plus all pip dependencies at runtime.
But multi-stage builds still help dramatically by separating the build
dependencies — compilers, dev headers, build tools — from the runtime.

### Naive Single-Stage (What Not To Do)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

This works but includes pip, setuptools, wheel, and whatever packages
your requirements pulled in. Size: ~350-500 MB for a small app.

### Multi-Stage Python with Virtual Environment

```dockerfile
# Build stage — install dependencies
FROM python:3.12-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Runtime stage — clean base + copied venv
FROM python:3.12-slim
WORKDIR /app

# Copy installed user packages from builder
COPY --from=builder /root/.local /root/.local
COPY . .

# Ensure local bin is in PATH
ENV PATH=/root/.local/bin:$PATH

CMD ["python", "app.py"]
```

The build tools (gcc, python3-dev) are only in the builder stage.
The runtime stage keeps only the slim Python image plus the
pre-installed packages. For a typical Flask or FastAPI app, this drops
size from ~500 MB to ~180 MB.

### Python with Compiled Extensions

Packages like `numpy`, `pandas`, `cryptography`, or `psycopg2` compile
C extensions during installation. Without build tools in the builder
stage, they fail.

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# --no-build-isolation avoids pip pulling extra compilers
RUN pip install --user --no-cache-dir --no-build-isolation -r requirements.txt

# Runtime
FROM python:3.12-slim
WORKDIR /app

# Runtime libraries only — no compilers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH
CMD ["python", "app.py"]
```

The runtime stage only has shared libraries (`libpq5`, `libffi8`),
not the dev headers. The compilers and build tools are confined to the
builder stage and never reach the final image.

### Alpine vs Slim Base for Python

```dockerfile
# Compare these two runtime stages:

# Option A: python:3.12-slim (Debian-based, ~120 MB base)
FROM python:3.12-slim

# Option B: python:3.12-alpine (~50 MB base)
FROM python:3.12-alpine
RUN apk add --no-cache libpq
```

Alpine images are smaller but use musl instead of glibc. If your C
extensions are compiled against glibc (most are), Alpine will either
fail to import them or produce subtle runtime bugs. For pure Python
packages without C extensions, Alpine is fine. For anything with
native code, stick with `slim`.

---

## Node.js: Size from a Different Angle

Node.js images follow a similar pattern but have a gotcha: `node_modules`
is the bulk of the image, and npm/yarn install is the slowest build
step.

### Multi-Stage Node.js Dockerfile

```dockerfile
# Build stage
FROM node:22-alpine AS builder
WORKDIR /build

# Cache npm dependencies
COPY package.json package-lock.json ./
RUN npm ci --only=production

# Install dev dependencies for build step
RUN npm ci

# Build application (TypeScript, React, etc.)
COPY tsconfig.json ./
COPY src/ src/
RUN npm run build

# Prune dev dependencies from node_modules
RUN npm prune --production && \
    rm -rf src/ tsconfig.json

# Runtime stage
FROM node:22-alpine
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy only what is needed at runtime
COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/dist ./dist
COPY package.json ./

USER appuser
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

Key optimizations:

- **`npm ci` instead of `npm install`** — Faster, deterministic,
  respects lockfile exactly, and fails if `package-lock.json` is out
  of sync with `package.json`
- **`npm prune --production`** — Removes devDependencies after build
- **Separate `package.json` copy** — Dependencies layer is cached
  until `package.json` or `package-lock.json` changes

### Comparison

| Technique | Image Size | Notes |
|-----------|-----------|-------|
| Single-stage `node:22` | ~1.2 GB | Full image with dev deps |
| Single-stage `node:22-alpine` | ~350 MB | Smaller but still has dev deps |
| Multi-stage (above) | ~150-200 MB | Production deps only |
| Distroless Node.js | ~120-150 MB | Google distroless base |

---

## Distroless Base Images

Google's [distroless](https://github.com/GoogleContainerTools/distroless)
images are another runtime option. They contain only the language
runtime and its shared libraries — no shell, no package manager, no
utilities.

```dockerfile
# Go on distroless
FROM golang:1.23-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

```dockerfile
# Python on distroless
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM gcr.io/distroless/python3-debian12
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app /app
WORKDIR /app
ENV PATH=/root/.local/bin:$PATH
CMD ["app.py"]
```

**When to use distroless:**
- You need the smallest possible attack surface
- Your container is scanned by security tooling (Trivy, Grype)
- You do not need shell access to running containers

**When to avoid distroless:**
- You need to `docker exec` into the container and debug with shell
  tools (no `sh`, `curl`, `ping` available)
- Your application relies on OS utilities that are not in the image
- You run health checks that depend on shell commands

For homelab use, Alpine or slim bases strike a better balance. They
are small enough yet retain basic debugging tools. Swap to distroless
only when you are comfortable debugging blind.

---

## General Multi-Stage Optimization Strategies

### Layer Ordering for Cache Hits

Docker builds each layer sequentially and caches results. To maximize
cache reuse, order your Dockerfile from least-changing to most-changing:

```dockerfile
# 1. OS packages (changes rarely)
FROM alpine:3.21 AS base
RUN apk add --no-cache ca-certificates tzdata

# 2. Dependency manifests (changes when you add/remove packages)
COPY go.mod go.sum ./
RUN go mod download

# 3. Source code (changes on every edit)
COPY . .
RUN go build -o /app/server .
```

This ordering means a single-line code change does NOT invalidate the
OS package layer or the dependency download layer. Builds that would
take 3 minutes recompile in 20 seconds.

### Using Build Arguments

Build args let you parameterize the Dockerfile without hardcoding:

```dockerfile
ARG GO_VERSION=1.23
FROM golang:${GO_VERSION}-alpine AS builder

ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} \
    go build -ldflags="-s -w" -o /app/server .
```

Build with platform-specific images:

```bash
# Build for multiple architectures
docker buildx build \
  --build-arg GO_VERSION=1.23 \
  --platform linux/amd64,linux/arm64 \
  -t my-service:latest \
  --push .
```

### Multi-Stage for Monorepos

If your homelab runs multiple Go services in one repository, use a
single Dockerfile with argument-based stage selection:

```dockerfile
ARG SERVICE=api

FROM golang:1.23-alpine AS base
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .

FROM base AS service-api
RUN go build -o /app/service ./cmd/api

FROM base AS service-worker
RUN go build -o /app/service ./cmd/worker

FROM base AS service-webhook
RUN go build -o /app/service ./cmd/webhook

FROM service-${SERVICE} AS final
FROM alpine:3.21
COPY --from=final /app/service /usr/local/bin/service
ENTRYPOINT ["/usr/local/bin/service"]
```

Build specific services:

```bash
docker build --build-arg SERVICE=api -t my-api:latest .
docker build --build-arg SERVICE=worker -t my-worker:latest .
```

The `go mod download` layer is shared across all services, and each
build only runs one compile step.

---

## Security Hardening Through Multi-Stage

Beyond size reduction, multi-stage builds improve security in three
ways:

### 1. No Build Tools in Production

Compilers, headers, and package managers are the biggest source of
CVEs in container images. By confining them to the builder stage, the
runtime image has less software to patch.

```bash
# Scan a fat image vs a multi-stage image
docker scout quickview my-app:fat
# 25 vulnerabilities (3 critical, 8 high)

docker scout quickview my-app:multi-stage
# 2 vulnerabilities (0 critical, 0 high)
```

### 2. Non-Root User by Default

Build the non-root user into the runtime stage:

```dockerfile
FROM alpine:3.21
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY --from=builder /app/server /server
USER appuser
ENTRYPOINT ["/server"]
```

### 3. Read-Only Root Filesystem

Combine with Docker's `--read-only` flag:

```bash
docker run --read-only --tmpfs /tmp my-app:latest
```

The binary needs nowhere to write in the root filesystem. If an
attacker compromises the process, they cannot drop files on the
filesystem.

---

## Database Sidecar Pattern with Alpine

Multi-stage is not just for application images. Database initializers,
migration runners, and cron containers benefit too:

```dockerfile
# PostgreSQL migration runner
FROM golang:1.23-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app/migrate ./cmd/migrate

FROM alpine:3.21
RUN apk add --no-cache postgresql-client
COPY --from=builder /app/migrate /usr/local/bin/migrate
COPY migrations/ /migrations/
ENTRYPOINT ["/usr/local/bin/migrate"]
```

This runs as a docker-compose `depends_on` init container that applies
database migrations, then exits. The image stays under 20 MB.

---

## Measuring Your Results

Before-and-after metrics keep you honest:

```bash
# After building your optimized image
docker images my-app:optimized

# Show image layers and their sizes
docker history my-app:optimized

# Scan for CVEs
docker scout quickview my-app:optimized

# Compare against single-stage
echo "Size reduction:"
echo "Before: $(docker images my-app:fat --format '{{.Size}}')"
echo "After:  $(docker images my-app:optimized --format '{{.Size}}')"
```

Run Trivy for a deeper audit:

```bash
trivy image my-app:optimized
```

A well-optimized homelab Docker image should:
- Be 80-95% smaller than its single-stage equivalent
- Have zero critical CVEs (achievable with scratch/distroless)
- Build in under 30 seconds from cache on a code change

---

## Summary

Multi-stage builds are the single most impactful Dockerfile optimization
you can make. The pattern is language-agnostic:

1. **Build stage** — Full toolchain, compile or install everything
2. **Runtime stage** — Minimal base, copy only the artifacts

For Go services, `FROM scratch` with static binaries produces images
under 15 MB. For Python and Node.js, separating build dependencies
from runtime reduces size by 60-80% while also reducing the CVE count.

Combine multi-stage with proper cache layering (dependencies before
source), non-root users, and read-only filesystems for containers that
are small, fast to deploy, and hardened against exploitation.
