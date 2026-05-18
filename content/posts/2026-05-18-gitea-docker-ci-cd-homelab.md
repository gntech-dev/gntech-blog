---
title: "Gitea Docker Deployment — Self-Hosted Git and CI/CD for Homelab"
description: "Deploy Gitea with Docker Compose, PostgreSQL, and SSH in your homelab. Set up Gitea Actions for CI/CD, automate Docker builds, and back up your repositories."
date: 2026-05-18T17:00:00-04:00
tags:
  - docker
  - docker-compose
  - devops
  - homelab
  - security
keywords:
  - Gitea Docker deployment homelab
  - self-hosted Git server Docker compose
  - Gitea Actions CI/CD setup
  - Gitea PostgreSQL Docker deployment
  - Gitea Docker backup strategy
  - Gitea Actions runner Docker
  - self-hosted Git CI CD pipeline
summary: "Complete guide to deploying Gitea with Docker Compose in your homelab — PostgreSQL backend, SSH passthrough, daily backups, and Gitea Actions CI/CD for automated Docker builds and deployments."
canonical: "https://blog.gntech.me/posts/gitea-docker-ci-cd-homelab/"
---

Relying on GitHub, GitLab, or Bitbucket for every project puts your
infrastructure code, Docker Compose files, and Ansible playbooks on
someone else's servers. For a homelab where you control every packet,
your source code should live in your own VLAN.

**Gitea** is a self-hosted Git server written in Go. The binary is
~100 MB with zero dependencies, and the Docker image with PostgreSQL
runs comfortably on a 1 GB RAM LXC container. It supports SSH and
HTTP(S) access, pull requests, issue tracking, a built-in registry,
and — most importantly for this guide — **Gitea Actions**, a
GitHub-Actions-compatible CI/CD system that runs on your own
hardware.

This guide covers the full stack: Docker Compose deployment with
PostgreSQL, SSH configuration for git operations, Traefik reverse
proxy integration, backup automation, and a working CI/CD pipeline
that builds and deploys Docker images inside your homelab.

---

## Gitea Docker Compose Deployment

The standard Gitea deployment uses two containers: Gitea itself and a
PostgreSQL database. A third service for Redis is optional — Gitea
can use file-based sessions for small deployments.

### Complete Docker Compose Configuration

```yaml
# /opt/gitea/docker-compose.yml
services:
  server:
    image: gitea/gitea:1.23
    container_name: gitea
    environment:
      - USER_UID=1000
      - USER_GID=1000
      - GITEA__database__DB_TYPE=postgres
      - GITEA__database__HOST=db:5432
      - GITEA__database__NAME=gitea
      - GITEA__database__USER=gitea
      - GITEA__database__PASSWD=${DB_PASSWORD}
      - GITEA__server__DOMAIN=git.gntech.dev
      - GITEA__server__HTTP_PORT=3000
      - GITEA__server__ROOT_URL=https://git.gntech.dev
      - GITEA__server__SSH_DOMAIN=git.gntech.dev
      - GITEA__server__SSH_PORT=2222
      - GITEA__server__SSH_LISTEN_PORT=22
      - GITEA__server__DISABLE_SSH=false
      - GITEA__server__START_SSH_SERVER=true
      - GITEA__metrics__ENABLED=true
    volumes:
      - ./data:/data
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    ports:
      - "2222:22"
    networks:
      - proxy
      - internal
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.gitea.rule=Host(`git.gntech.dev`)"
      - "traefik.http.routers.gitea.entrypoints=websecure"
      - "traefik.http.services.gitea.loadbalancer.server.port=3000"

  db:
    image: postgres:16-alpine
    container_name: gitea-db
    environment:
      - POSTGRES_USER=gitea
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=gitea
    volumes:
      - ./postgres:/var/lib/postgresql/data
    networks:
      - internal
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gitea"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  proxy:
    external: true
  internal:
    internal: true
```

### Environment File

Create `.env` alongside the Compose file:

```bash
# /opt/gitea/.env
DB_PASSWORD=$(openssl rand -base64 32)
```

Generate it once and keep it in the `.env` file. Never commit this to
version control — yes, the irony of keeping a Git password outside
Git is intentional.

### First Run

```bash
mkdir -p /opt/gitea/{data,postgres}
cd /opt/gitea
echo 'DB_PASSWORD=your-secure-password-here' > .env
docker compose up -d
```

On first start, Gitea runs the installer at
`https://git.gntech.dev/install`. Pre-fill the database settings from
the environment variables above. Set the **Server Domain** and **Gitea
Base URL** to your domain. SSH port should match the mapped port
(2222 in this setup).

After installation, Gitea auto-configures itself from the database
settings and the admin account you create during setup.

---

## SSH Configuration for Git Operations

Gitea runs its own SSH server inside the container on port 22. The
Compose file maps host port 2222 to container port 22. Users configure
their local Git client to use this port:

```bash
# On your workstation or management machine
git clone ssh://git@git.gntech.dev:2222/username/repo.git
```

For SSH key authentication, add your public key in Gitea's web UI
under **Settings → SSH/GPG Keys**.

### Alternative: Host SSH Passthrough

If you already run an SSH server on the Docker host and prefer not
to expose another port, use SSH port forwarding instead. Add this to
your `~/.ssh/config`:

```
Host git.gntech.dev
  HostName git.gntech.dev
  Port 2222
  User git
  IdentityFile ~/.ssh/id_ed25519
```

Then clone normally:

```bash
git clone git@git.gntech.dev:username/repo.git
# Port 2222 is used automatically from ~/.ssh/config
```

---

## Traefik Reverse Proxy Integration

The Docker labels on the Gitea service register it with Traefik
automatically. Add the `proxy` network and the `websecure` entrypoint
to your Traefik configuration:

```yaml
# traefik.yml — dynamic config or labels
labels:
  - "traefik.http.routers.gitea.rule=Host(`git.gntech.dev`)"
  - "traefik.http.routers.gitea.entrypoints=websecure"
  - "traefik.http.routers.gitea.tls.certresolver=letsencrypt"
  - "traefik.http.services.gitea.loadbalancer.server.port=3000"
```

Traefik terminates TLS, passes plain HTTP/1.1 to the Gitea container
on port 3000, and Gitea does not need to know about certificates at
all. This is the cleanest setup — Gitea's built-in HTTPS is disabled
because Traefik handles it upstream.

---

## Backup Strategy

Your Git repositories are Gitea's most valuable asset. Back them up
daily with a script that runs inside the container:

```bash
#!/bin/bash
# /opt/gitea/backup.sh — run via cron

BACKUP_DIR="/opt/gitea/backups"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"

# Run Gitea's built-in dump command
docker exec gitea bash -c "
  /usr/local/bin/gitea dump \
    -c /data/gitea/conf/app.ini \
    -f /tmp/gitea-dump.zip \
    --skip-repository-archive \
    --skip-log \
    --skip-custom-dir
"

# Copy dump and database
docker cp gitea:/tmp/gitea-dump.zip "$BACKUP_DIR/gitea-dump-$TIMESTAMP.zip"
docker exec gitea rm /tmp/gitea-dump.zip

# Rotate old backups
find "$BACKUP_DIR" -name "gitea-dump-*.zip" -mtime +$RETENTION_DAYS -delete

echo "Backup complete: gitea-dump-$TIMESTAMP.zip"
```

Add it to the host's cron:

```bash
# /etc/cron.d/gitea-backup
0 3 * * * root /opt/gitea/backup.sh
```

This produces a complete dump including repositories, database, and
configuration — everything needed to restore Gitea on a fresh install.

---

## Gitea Actions — Self-Hosted CI/CD

Gitea Actions is the killer feature. It is compatible with GitHub
Actions syntax, which means existing workflows from GitHub projects
port over with minimal changes. Runners execute jobs on your
infrastructure, not on a cloud provider's bill.

### Enabling Actions

In the Gitea web UI, go to **Site Administration → Actions** and
ensure **Enable Actions** is checked. Then deploy a runner:

### Deploy a Docker-Based Runner

```yaml
# /opt/gitea-runner/docker-compose.yml
services:
  runner:
    image: gitea/act_runner:latest
    container_name: gitea-runner
    environment:
      - CONFIG_FILE=/config.yaml
      - GITEA_INSTANCE_URL=https://git.gntech.dev
      - GITEA_RUNNER_REGISTRATION_TOKEN=${RUNNER_TOKEN}
      - GITEA_RUNNER_NAME=homelab-runner
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
    volumes:
      - ./data:/data
      - ./config.yaml:/config.yaml:ro
    networks:
      - proxy
    restart: unless-stopped
    depends_on:
      - docker-socket-proxy

  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy
    container_name: docker-socket-proxy
    environment:
      - CONTAINERS=1
      - POST=1
      - BUILD=1
      - IMAGES=1
      - INFO=1
      - AUTH=1
      - EXEC=1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - proxy
    restart: unless-stopped

networks:
  proxy:
    external: true
```

The `docker-socket-proxy` sidecar provides the runner with Docker
access without exposing the socket directly. The runner builds images,
runs containers, and executes commands — all through a restricted API
proxy.

### Registering the Runner

```bash
# Get the registration token from Gitea Admin → Actions → Create Runner
# Then:
cd /opt/gitea-runner
echo 'RUNNER_TOKEN=your-token-here' > .env
docker compose up -d
```

The runner registers itself with Gitea on startup. Check the runner
status in **Site Administration → Actions → Runners**.

### Example Workflow — Build and Deploy a Docker Image

Place this `.gitea/workflows/build.yml` in your repository:

```yaml
# .gitea/workflows/build.yml
name: Build and Deploy
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Gitea Container Registry
        uses: docker/login-action@v3
        with:
          registry: git.gntech.dev
          username: ${{ secrets.GITEA_USER }}
          password: ${{ secrets.GITEA_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: git.gntech.dev/${{ github.repository }}:${{ github.sha }}

      - name: Deploy to homelab
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_KEY }}
          script: |
            cd /opt/apps/myapp
            docker compose pull
            docker compose up -d --force-recreate
```

### Secrets Configuration

Add secrets in the Gitea repository at **Settings → Actions → Secrets**:

- `GITEA_USER` — your Gitea username
- `GITEA_TOKEN` — a personal access token from **Settings → Applications**
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY` — SSH credentials for
  the target Docker host

### Runner Labels

Gitea Actions runners use labels instead of GitHub's
`runs-on: ubuntu-latest`. The default runner image ships with labels
like `ubuntu-latest:docker://node:20-bullseye`. If your workflow
uses `runs-on: ubuntu-latest` and the runner has that label, it
matches automatically.

You can define custom labels in the runner's `config.yaml`:

```yaml
# /opt/gitea-runner/config.yaml
runner:
  labels:
    - "ubuntu-latest:docker://node:20-bullseye"
    - "docker-builder:docker://docker:27-cli"
```

---

## Performance Tuning for Low-Spec Hosts

Gitea is lightweight by design, but a few optimizations help it run
on constrained hardware:

```bash
# Limit Gitea container to 512 MB RAM
# Add to the Compose file under gitea service:
deploy:
  resources:
    limits:
      memory: 512M
```

```ini
# Gitea config (/data/gitea/conf/app.ini) — disable unused features
[repository]
DISABLE_STARS = true
DISABLE_WATCHERS = true
DEFAULT_BRANCH = main

[other]
SHOW_FOOTER_VERSION = false
SHOW_FOOTER_TEMPLATE_LOAD_TIME = false
```

```bash
# Postgres: limit shared buffers (add to db service)
deploy:
  resources:
    limits:
      memory: 256M
```

With these limits, Gitea + Postgres stay under 700 MB RAM total,
leaving headroom for the runner.

---

## Security Considerations

Running a Git server on your homelab exposes an attack surface beyond
the usual web services:

**SSH hardening.** Gitea's built-in SSH server uses its own
implementation. Keep it behind a non-standard port (2222) or disable
it entirely and use HTTP(S) cloning only. If you need SSH, restrict
it with `AllowUsers git` in the Docker host's SSH config.

**Rate limiting.** Traefik middleware protects the HTTP endpoint:

```yaml
labels:
  - "traefik.http.middlewares.gitea-ratelimit.ratelimit.average=30"
  - "traefik.http.middlewares.gitea-ratelimit.ratelimit.burst=60"
  - "traefik.http.routers.gitea.middlewares=gitea-ratelimit"
```

**Container registry authentication.** Gitea's built-in container
registry uses JWT tokens. Generate scoped tokens in
**Settings → Applications** for CI/CD use. Never use your admin
password in workflow files.

**Database isolation.** The PostgreSQL service uses an internal Docker
network (`internal: true`). No other container on the Docker host can
reach it unless explicitly connected to the `internal` network.

---

## Restoring from Backup

If your Gitea instance dies, recovery is a two-step process:

```bash
# 1. Start fresh Gitea + Postgres with the same docker-compose.yml
cd /opt/gitea && docker compose up -d

# 2. Copy the latest backup into the container
docker cp backups/gitea-dump-20260518-030000.zip gitea:/tmp/

# 3. Run restore inside the container
docker exec -it gitea bash -c "
  unzip /tmp/gitea-dump-20260518-030000.zip -d /tmp/restore
  /usr/local/bin/gitea restore \
    -c /data/gitea/conf/app.ini \
    -f /tmp/gitea-dump-20260518-030000.zip
"
```

After restore, restart the container and verify your repositories are
back. The dump includes all repos, issues, pull requests, and user
accounts.

---

Gitea replaces GitHub's proprietary offering with a fully self-hosted
Git stack that runs on the same hardware you already manage. Your
repositories stay inside your network, CI/CD pipelines run on your
CPU cycles, and the container registry stores images without egress
charges. It is one of the highest-impact services you can add to a
homelab — a single LXC container replaces three external
dependencies.
