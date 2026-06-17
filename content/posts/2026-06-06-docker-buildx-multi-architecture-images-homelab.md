---
title: "Multi-Arch Docker Images with Buildx for Homelab"
description: "Build and serve multi-architecture Docker images with Docker Buildx in your homelab. Step-by-step guide for amd64 and arm64 cross-platform builds on a single Linux host."
date: 2026-06-06T16:00:00-04:00
tags:
  - docker
  - devops
  - containers
  - linux
  - selfhosting
keywords:
  - Docker Buildx multi-architecture images homelab setup guide
  - Build and push multi-arch Docker images amd64 arm64 single host
  - Docker Buildx cross-platform emulation QEMU binfmt
  - Multi-stage Docker build multi-architecture ARM64 x86_64 CI/CD
  - Self-hosted Docker registry multi-platform manifest list
  - Docker BuildKit multi-arch container images homelab
  - Docker desktop buildx alternative CLI only buildx
summary: "Run Docker Buildx on a single Linux host to produce amd64 plus arm64 images. Configure QEMU binfmt emulation, build with buildx bake, and push multi-manifest images to any registry."
canonical: "https://blog.gntech.me/posts/docker-buildx-multi-architecture-images-homelab/"
---

## Why Multi-Architecture Docker Images Matter in Your Homelab

Most homelabs start as a single x86_64 server. A Dell PowerEdge, a custom Ryzen build, a repurposed office PC. Then the Raspberry Pi shows up. Then an Orange Pi for a low-power always-on service. Then a Mac Mini M-series running containers. Suddenly you have a mixed-architecture environment and every second `docker pull` downloads the wrong CPU instruction set.

When you pull `nginx:alpine` on an arm64 machine without a manifest-aware process, Docker either:

1. Pulls the correct arm64 variant automatically (if the image has a manifest list), or
2. Pulls amd64 and runs it through QEMU user-mode emulation — silently, and 3–5x slower.

The fix is to stop relying on upstream manifests and build your own multi-architecture images. Docker Buildx wraps BuildKit with multi-platform support, letting you produce a single tagged image that contains native layers for every architecture you target.

## How Docker Multi-Architecture Images Work

Under the hood, a multi-arch image is an **OCI image index** (formerly called a manifest list). It contains references to the actual manifest for each platform:

```json
{
  "schemaVersion": 2,
  "manifests": [
    {
      "platform": { "os": "linux", "architecture": "amd64" },
      "digest": "sha256:abc123..."
    },
    {
      "platform": { "os": "linux", "architecture": "arm64", "variant": "v8" },
      "digest": "sha256:def456..."
    }
  ]
}
```

When a Docker client pulls the image, it reads the index, matches its own architecture, and downloads only the relevant manifest and layers. No emulation overhead, no wasted bandwidth.

## Prerequisites

- Docker Engine 24.0 or later (BuildKit is built in)
- A registry to push to (Docker Hub, GitHub Container Registry, or a [self-hosted registry with MinIO](/posts/minio-docker-object-storage/))
- Linux kernel with `binfmt_misc` support (all modern kernels)

## Step 1 — Enable Cross-Platform Emulation with QEMU

Docker Buildx uses QEMU user-mode emulation to build arm64 binaries on an amd64 host and vice versa. First, register the binfmt handlers:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

This installs QEMU static binaries and registers them with the kernel's binfmt_misc subsystem. Verify the builders are registered:

```bash
ls -1 /proc/sys/fs/binfmt_misc/ | grep qemu
```

You should see entries like `qemu-aarch64`, `qemu-x86_64`, and others.

## Step 2 — Create a Multi-Architecture Docker Builder

Buildx ships with a default `docker` driver that uses the local Docker Engine — but it does not support multi-platform builds. You need the `docker-container` driver, which runs BuildKit in its own container:

```bash
docker buildx create \
  --name multiarch \
  --driver docker-container \
  --bootstrap
```

Verify the builder supports your target platforms:

```bash
docker buildx ls
```

The output should list `linux/amd64` and `linux/arm64` under the `multiarch` builder. If arm64 is missing, re-run the binfmt step and restart the builder:

```bash
docker buildx rm multiarch
# repeat create step above
```

Set this builder as the default for your shell:

```bash
docker buildx use multiarch
```

## Step 3 — Write a Cross-Platform Dockerfile

The key to multi-arch Dockerfiles is the built-in `BUILDPLATFORM` and `TARGETPLATFORM` build arguments. BuildKit sets these automatically based on the target architecture:

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY . .
RUN GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app .

FROM --platform=$TARGETPLATFORM alpine:3.20
COPY --from=builder /app /app
ENTRYPOINT ["/app"]
```

For interpreted languages like Python or Node.js, the same image works on both architectures — you only need to ensure the base image is multi-arch aware:

```dockerfile
FROM --platform=$TARGETPLATFORM node:22-alpine
WORKDIR /app
COPY package*.json .
RUN npm ci --omit=dev
COPY . .
CMD ["node", "server.js"]
```

Most official Docker images (alpine, node, python, nginx, postgres) are already multi-arch. The `--platform=$TARGETPLATFORM` ensures BuildKit resolves the correct variant during the build.

## Step 4 — Build and Push Multi-Arch Images

The simplest approach is a single `docker buildx build` command:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/yourname/myapp:latest \
  --push \
  .
```

**Important**: `--push` is required when building for multiple platforms. The `--load` flag only supports a single architecture — loading a multi-platform result into the local Docker image store is not supported.

For projects with multiple images, use a **bake file** (`docker-bake.hcl`):

```hcl
group "default" {
  targets = ["app", "web"]
}

target "app" {
  dockerfile = "app/Dockerfile"
  context   = "app"
  tags      = ["ghcr.io/yourname/app:latest"]
  platforms = ["linux/amd64", "linux/arm64"]
}

target "web" {
  dockerfile = "web/Dockerfile"
  context   = "web"
  tags      = ["ghcr.io/yourname/web:latest"]
  platforms = ["linux/amd64", "linux/arm64"]
}
```

Build and push everything in one command:

```bash
docker buildx bake --push
```

## Step 5 — Verify the Multi-Arch Manifest

After pushing, inspect the image manifest to confirm both architectures are present:

```bash
docker buildx imagetools inspect ghcr.io/yourname/myapp:latest
```

You should see output listing both platforms:

```
Name:      ghcr.io/yourname/myapp:latest
MediaType: application/vnd.oci.image.index.v1+json
Manifests:
  linux/amd64 @ sha256:abc...
  linux/arm64 @ sha256:def...
```

Test the arm64 pull on a Raspberry Pi or any ARM machine:

```bash
docker pull ghcr.io/yourname/myapp:latest
docker inspect --format '{{.Architecture}}' ghcr.io/yourname/myapp:latest
# Output: arm64
```

## Integrating Multi-Arch Builds with Homelab CI/CD

If you run [Gitea with Actions](/posts/gitea-docker-ci-cd-homelab/), add a workflow that builds and pushes multi-arch images on every tag:

```yaml
# .gitea/workflows/build.yaml
name: Build and Push
on:
  push:
    tags: ['v*']
jobs:
  multiarch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up QEMU
        run: docker run --privileged --rm tonistiigi/binfmt --install all
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Login to registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ secrets.REGISTRY_USER }}
          password: ${{ secrets.REGISTRY_TOKEN }}
      - name: Build and push
        uses: docker/bake-action@v5
        with:
          push: true
          files: docker-bake.hcl
```

The same workflow works for GitHub Actions, Woodpecker, or any Drone-compatible runner.

## Common Pitfalls

**QEMU crashes on certain Go crypto instructions.** Some Go packages (especially `golang.org/x/crypto` with assembly optimizations) use CPU-specific instructions that QEMU user-mode cannot emulate. Workaround: build with `CGO_ENABLED=0` or use the `-tags=noasm` build tag.

**BuildKit cache mounts break across architectures.** Cache mounts (`--mount=type=cache`) are not shared between different platform builds. Each architecture gets its own separate cache directory.

**`--load` only stores one platform.** If you run `docker buildx build --platform linux/amd64,linux/arm64 --load`, BuildKit silently builds only the native platform (your host architecture). Always use `--push` for multi-platform builds.

**Emulated builds are slow.** Building arm64 on amd64 via QEMU is 3–5x slower than a native arm64 build. For production workloads, use native ARM runners or cross-compilation instead of emulation.

## Summary

Docker Buildx turns your single-architecture homelab server into a multi-architecture build station. With one QEMU container, one builder, and one Dockerfile, you can produce images that run natively on everything from an x86_64 Proxmox host to an ARM-based Raspberry Pi cluster.

The workflow is consistent whether you push to Docker Hub, GitHub Container Registry, or your own [self-hosted MinIO-backed registry](/posts/minio-docker-object-storage/). Combined with a Gitea Actions workflow, every tagged commit produces verified multi-arch images with zero manual effort.
