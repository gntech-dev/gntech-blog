---
title: "Docker Container Security — Non-Root Users, Capabilities, and Runtime Hardening"
description: "Hardening Docker containers for homelab deployments: non-root users, capability drops, read-only root filesystems, seccomp profiles, resource limits, and security-opt flags with real Compose configurations."
date: 2026-05-15T09:30:00-04:00
tags:
  - docker
  - security
  - linux
  - homelab
  - containers
keywords:
  - Docker container security hardening
  - Docker non-root user configuration
  - Docker capability drop security
  - Docker read-only root filesystem
  - Docker seccomp AppArmor profiles
  - Docker compose security context
  - container runtime security homelab
summary: "Hardening Docker containers in your homelab isn't optional — it's how you prevent container escapes and privilege escalation. This guide covers non-root users, capability drops, read-only filesystems, and seccomp profiles with real Compose configs."
canonical: "https://gntech.dev/posts/docker-container-security-hardening/"
---

Most homelabs run Docker containers as root by default. The Dockerfile
says `FROM nginx:latest` and nginx runs as root inside the container. A
container escape, a vulnerable web app, or a malicious image — and an
attacker has root on your Docker host.

This isn't theoretical. CVEs targeting container escape vectors
(CVE-2024-21626 for runc, CVE-2026-42945 for Nginx) are published
regularly. The fix is straightforward: stop running containers as root,
drop unnecessary capabilities, lock down the filesystem, and apply
runtime security profiles.

This guide covers the exact configurations you need for a hardened
Docker setup in a homelab — with real `docker-compose.yml` examples you
can apply today.

---

## Why Default Docker Permissions Are Dangerous

Docker containers share the host kernel. When a process runs as root
(UID 0) inside a container, it has the same UID 0 outside the
container. The only thing separating it from the host is the Linux
kernel's namespace isolation and cgroups.

Check what user your containers are running as:

```bash
docker exec my-container whoami
# root ← this is a problem

docker exec my-container id
# uid=0(root) gid=0(root) groups=0(root)
```

If an attacker exploits a kernel vulnerability from inside that
container, they get root on your Proxmox host. The `runc` escape CVE
(CVE-2019-5736, CVE-2024-21626) proves this isn't theoretical — it's
been exploited in the wild against CI pipelines and cloud deployments.

**The fix:** every container should run as a non-root user with the
minimum Linux capabilities it actually needs.

---

## Hardening Layer 1: Non-Root Users in Dockerfiles

The first and most important layer: define a non-root user in your
Dockerfile and switch to it with the `USER` directive.

**Bad Dockerfile:**

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["node", "server.js"]
# Runs as root — one exploit = full host compromise
```

**Good Dockerfile:**

```dockerfile
FROM node:20-alpine

# Create a non-root user with known UID/GID
RUN addgroup -S appgroup && \
    adduser -S appuser -G appgroup -u 1001

WORKDIR /app
COPY package*.json ./
RUN npm install && \
    chown -R appuser:appgroup /app
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

CMD ["node", "server.js"]
```

The `chown` is critical — if the app writes files (logs, uploads,
caches), the non-root user must own them or the container crashes with
"Permission denied."

**For Docker Compose, you can also enforce the user without modifying
the image:**

```yaml
services:
  app:
    image: some-image-that-runs-as-root
    user: "1001:1001"    # Force container to run as UID 1001
```

But this breaks if the image writes to files owned by root. Fixing it
at the image level with a proper Dockerfile is the correct approach.

---

## Hardening Layer 2: Dropping Linux Capabilities

Linux capabilities break the root user's blanket privileges into
discrete units: `CAP_NET_BIND_SERVICE` (bind to ports <1024),
`CAP_SYS_ADMIN` (mount filesystems, access kernel features), and many
more.

Docker gives containers a default set of capabilities. Most are
unnecessary for a standard web app.

**Check what capabilities your container has:**

```bash
docker run --rm ubuntu:22.04 capsh --print
docker exec my-container capsh --print | grep -o '=[^=]*cap_[^+]*'
```

**Drop all capabilities, then add back only what's needed:**

```yaml
services:
  nginx:
    image: nginx:alpine
    container_name: web
    cap_drop:
      - ALL                         # Remove every capability
    cap_add:
      - NET_BIND_SERVICE            # Only allow binding to port 80/443
      - CHOWN                       # Allow changing file ownership
      - SETGID                      # Allow setting group ID
      - SETUID                      # Allow setting user ID
```

For a typical web app (Node.js, Python, Go), you usually only need:

```yaml
services:
  webapp:
    image: my-web-app
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE   # Optional — only if binding to ports <1024
```

If your app binds to port 8080 (not 80), you don't even need
`NET_BIND_SERVICE`. Drop everything:

```yaml
services:
  webapp:
    image: my-web-app
    cap_drop:
      - ALL
    cap_add: []    # No capabilities at all — cleanest config
```

**What about databases?**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE     # Needed for file permission operations
      - SETUID
      - SETGID
      - NET_BIND_SERVICE # Postgres binds to port 5432
```

**Signs a capability is missing:**

```
nginx: [emerg] socket() failed: (13: Permission denied)
→ Add NET_BIND_SERVICE

change_attributes: Operation not permitted
→ Add CHOWN or DAC_OVERRIDE

fork failed: Resource temporarily unavailable
→ Check pids_limit, not a capability issue
```

---

## Hardening Layer 3: Read-Only Root Filesystem

Most containers only need to write to specific directories (uploads,
caches, databases). Everything else should be read-only. This prevents
attackers from modifying binaries or writing malicious files.

```yaml
services:
  my-app:
    image: my-web-app
    cap_drop:
      - ALL
    read_only: true
    tmpfs:                          # Writable temp directories in RAM
      - /tmp:noexec,nosuid,size=64M
      - /var/run:noexec,nosuid,size=32M
    volumes:
      - app_data:/app/data          # Persistent writable directory
```

The `read_only: true` flag makes the entire container filesystem
read-only. The `tmpfs` mounts provide small RAM-backed writable
directories for runtime data (pids, sockets, temp files). The named
volume provides a persistent writable directory for application data.

**For PostgreSQL:**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - SETUID
      - SETGID
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=64M
    volumes:
      - pg_data:/var/lib/postgresql/data  # Data dir must be writable
    environment:
      POSTGRES_INITDB_ARGS: "--data-checksums"
```

PostgreSQL writes to `/var/lib/postgresql/data` — that volume gives it
write access. Everything else (binaries, libraries) stays read-only.

**For Nginx with read-only root:**

```yaml
services:
  nginx:
    image: nginx:alpine
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - CHOWN
    read_only: true
    tmpfs:
      - /var/cache/nginx:noexec,nosuid,size=128M
      - /var/run:noexec,nosuid,size=64M
      - /tmp:noexec,nosuid,size=64M
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./html:/usr/share/nginx/html:ro
    ports:
      - "80:80"
      - "443:443"
```

Nginx needs writable `/var/cache/nginx` for its cache and `/var/run`
for the PID file. Everything else is read-only — including the config
and static files mounted with `:ro`.

---

## Hardening Layer 4: Security Options (seccomp, AppArmor, no-new-privileges)

Docker applies a default seccomp profile that blocks ~44 of ~300 Linux
syscalls. You can tighten it further, or apply a custom profile.

**Start with these security options for every container:**

```yaml
services:
  my-app:
    image: my-web-app
    security_opt:
      - no-new-privileges:true      # Prevent privilege escalation via suid binaries
      - seccomp=unconfined          # ⚠️ Only for debugging — don't use in production
    # Do this instead for production:
    # seccomp: profiles/default.json  # Docker's default is usually fine
```

The `no-new-privileges:true` flag is the single most impactful security
option. It prevents processes inside the container from gaining
additional privileges through suid binaries or `capset` syscalls.

**For a full security-optimized stack:**

```yaml
services:
  app:
    image: my-app
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=64M
    security_opt:
      - no-new-privileges:true
    # Use default seccomp profile (Docker applies it automatically)
```

---

## Hardening Layer 5: Resource Limits (prevent DoS)

A single compromised container shouldn't be able to exhaust host
resources. Set explicit limits:

```yaml
services:
  my-app:
    image: my-web-app
    deploy:
      resources:
        limits:
          cpus: "1.0"              # Max 1 CPU core
          memory: 512M             # Max 512MB RAM
        reservations:
          cpus: "0.25"            # Reserve 0.25 CPU
          memory: 256M            # Reserve 256MB RAM

    # Legacy compose syntax (v2):
    # mem_limit: 512m
    # cpus: "1.0"

    # PID limit — prevent fork bombs inside the container
    pids_limit: 200
```

The `pids_limit: 200` is often overlooked. A process that fork()s in
an infinite loop can exhaust the host PID table. Limiting to 200 PIDs
prevents this while being more than enough for most applications.

Restart policies with limits:

```yaml
    restart: unless-stopped
    stop_grace_period: 30s       # Give the app time to shut down cleanly
    oom_kill_disable: false      # Allow OOM killer — true can hide memory leaks
```

---

## Hardening Layer 6: Volume Mount Safety

Bind mounts are inherently risky. If you mount `/:/host` (don't do
this), the container can modify anything. Safer patterns:

```yaml
services:
  my-app:
    volumes:
      # Read-only bind mounts — the container cannot modify them
      - ./config:/app/config:ro

      # Named volumes — safer than bind mounts, managed by Docker
      - app_data:/app/data

      # Never mount the Docker socket unless you absolutely need it
      # - /var/run/docker.sock:/var/run/docker.sock:ro  # ⚠️ Container escape risk
```

**If you must mount the Docker socket (Portainer, Traefik, Watchtower),
read-only is safer but not safe — socket access is effectively root:**

```yaml
services:
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Minimal exposure

  # Better alternative: use a Docker socket proxy
  docker-proxy:
    image: tecnativa/docker-socket-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      CONTAINERS: 1     # Only allow container operations
      NETWORKS: 0       # Block network operations
      IMAGES: 1         # Allow image operations
      SERVICES: 0       # Block service operations
      TASKS: 0          # Block task operations
      POST: 1           # Allow POST requests
```

The docker-socket-proxy pattern (covered in depth in the Docker Socket
Proxy post) lets you whitelist specific API endpoints instead of giving
full socket access. For security-minded homelabs, this is the correct
approach.

---

## Hardening Layer 7: Image Hygiene

Your container is only as secure as the base image you build from.

```bash
# Scan for vulnerabilities
docker scout quickstart
docker scout cves nginx:alpine    # Check base image for known CVEs

# Use Trivy for offline scanning
docker pull aquasec/trivy:latest
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image my-app

# Use specific tags, not "latest"
FROM node:20-alpine        # Specific major version — good
FROM node:alpine           # No version — bad, "latest" changes
FROM node:20.14.0-alpine   # Pinned to patch — best for production

# Distroless images have no shell, no package manager, no utilities
FROM gcr.io/distroless/nodejs20-debian12:latest
# If an attacker gets code execution, there's no bash, no curl, no wget
```

For a homelab, distroless images are overkill for most services. But
pinning versions and scanning for known CVEs is table stakes.

**Dockerfile security checklist:**

```dockerfile
FROM node:20-alpine AS build
# Build stage — has all the build tools

FROM node:20-alpine AS production
# Runtime stage — minimal dependencies
RUN addgroup -S appgroup && adduser -S appuser -G appgroup -u 1001

COPY --from=build --chown=appuser:appgroup /app /app
USER appuser

# Health check prevents the orchestrator from routing traffic to dead containers
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1

# Explicit EXPOSE documents the port
EXPOSE 3000

ENTRYPOINT ["node", "server.js"]
```

---

## The Complete Hardened Compose Template

Combining all layers into a single production-ready template:

```yaml
version: "3.9"

services:
  web:
    image: my-web-app:1.0.0           # Pinned version, not "latest"
    container_name: my-web-app
    restart: unless-stopped
    stop_grace_period: 30s

    # === User ===
    user: "1001:1001"                  # Non-root user

    # === Capabilities ===
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE               # Bind to port 80/443

    # === Filesystem ===
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=64M
    volumes:
      - app_data:/app/data             # Persistent data
      - ./config/app.conf:/etc/app.conf:ro  # Read-only config

    # === Security Options ===
    security_opt:
      - no-new-privileges:true

    # === Resource Limits ===
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          cpus: "0.25"
          memory: 256M
    pids_limit: 200

    # === Networking ===
    networks:
      - internal-net
    ports:
      - "127.0.0.1:8080:3000"          # Bind to localhost only — reverse proxy handles external

    # === Health Check ===
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

    # === Logging ===
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  internal-net:
    internal: true                      # No external connectivity — locked down

volumes:
  app_data:
```

---

## Verifying Your Hardening

After applying these changes, verify each layer is active:

```bash
# Check user inside container
docker exec my-web-app whoami
# Should output: appuser (not root)

# Check capabilities
docker exec my-web-app capsh --print
# Current: = cap_net_bind_service+ep
# (No SYS_ADMIN, no NET_ADMIN, no DAC_OVERRIDE)

# Check read-only filesystem
docker exec my-web-app touch /test
# touch: /test: Read-only file system ✓

# Check writable paths
docker exec my-web-app touch /app/data/test
# Should succeed ✓

# Check security options
docker inspect my-web-app --format '{{.HostConfig.SecurityOpt}}'
# [no-new-privileges:true]

# Check resource limits
docker stats my-web-app --no-stream
# CPU %    MEM USAGE / LIMIT
# 0.05%    128MiB / 512MiB
```

---

## Common Pitfalls When Hardening Containers

**"Permission denied" on startup:** You set `read_only: true` but the
app needs to write to a directory you didn't map. Fix: add a `tmpfs` or
volume for the required path.

**"Operation not permitted" for database:** Databases need `CHOWN`,
`SETUID`, `SETGID` to manage file permissions. Drop them and the
container crashes on `initdb`.

**App runs but can't serve traffic:** Port 80 requires
`NET_BIND_SERVICE`. Switch to port 8080 or add the capability.

**"Bad system call" with seccomp:** Some apps use syscalls blocked by
the default seccomp profile (rare, but happens with Chrome/Puppeteer).
Generate a custom profile instead of going `unconfined`:

```bash
# Generate a seccomp profile from a running container
docker run --rm it --security-opt seccomp=unconfined my-app
# Capture strace output, generate profile from filtered syscalls
# or use: dockersec generate my-app > custom-profile.json
```

---

## Summary: The Minimal Hardening Checklist

These five changes cover 95% of the security improvement with minimal
breakage:

1. **Define a non-root `USER`** in every Dockerfile or use `user:` in
   Compose — prevents container escape from yielding root on the host
2. **Drop ALL capabilities** and add back only what the app needs —
   eliminates privilege escalation vectors
3. **Set `read_only: true`** with `tmpfs` for runtime dirs — prevents
   attackers from modifying binaries or writing malware
4. **Enable `no-new-privileges:true`** — blocks suid-based privilege
   escalation entirely
5. **Set `pids_limit` and memory limits** — prevents a compromised
   container from DoS-ing the host

Apply these to every new container you deploy. Retrofit them onto
existing containers one at a time, testing each change. The first time
you catch a container escape exploit failing because of these settings,
you'll wonder why you ever ran containers as root.
