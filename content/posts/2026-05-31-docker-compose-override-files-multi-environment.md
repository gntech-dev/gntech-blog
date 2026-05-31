---
title: "Docker Compose Override Files — Multi-Environment Homelab Deployments"
description: "Master Docker Compose override files for dev, staging, and production deployments in your homelab. Covers docker-compose.override.yml, named overrides, port volume and resource overrides with real configs."
date: 2026-05-31T07:00:00-04:00
tags:
  - docker
  - docker-compose
  - devops
  - homelab
  - linux
keywords:
  - Docker Compose override files multi-environment deployment
  - docker-compose.override.yml dev production override examples
  - Docker Compose port mapping override volumes resource limits
  - Docker Compose -f flag multiple compose files merge order
  - Docker Compose extension fields DRY configuration patterns
  - Docker Compose staging production homelab docker-compose.yml
  - Docker Compose override file security production hardening
summary: "Learn how Docker Compose override files let you manage dev, staging, and production deployments from a single base docker-compose.yml — with port mapping overrides, resource limits, volume mounts, and security hardening for your homelab."
canonical: "https://blog.gntech.me/posts/docker-compose-override-files-multi-environment/"
---

## Why Docker Compose Override Files Matter in a Homelab

You have a Docker Compose stack that works great in development — bind volumes for live code reload, relaxed resource limits, ports exposed for debugging. Then you want to run the same stack in "production" behind Traefik, with resource constraints, restart policies, and read-only filesystems. Do you maintain two separate `docker-compose.yml` files? Branch the repo? Use profiles?

None of those scale well. Override files are the clean solution Docker Compose provides for exactly this scenario.

Docker Compose lets you merge multiple compose files together. A base file defines the shared structure — services, networks, volumes. Override files layer on environment-specific changes: different port mappings, volumes, resource limits, and security settings. The same config drives dev, staging, and prod without duplication.

In my homelab, I run a web application stack across three environments: an LXC container for development on my Proxmox host, a staging VM for integration testing, and a production VM behind Traefik. Override files keep all three in one directory.

## How Docker Compose File Merging Works

Docker Compose merges multiple YAML files into a single configuration before applying it. The merge follows these rules:

- **Maps (dictionaries)** are merged recursively — if the base file defines `environment` keys and the override defines `environment` keys, both sets are combined.
- **Arrays (sequences)** are fully replaced — if the base file has a `ports` array and the override has a `ports` array, the override wins entirely.
- **Scalar values** from the override replace the base.

This behaviour matters. A common mistake is putting override ports alongside base ports and wondering why both appear.

### Default Override File

When you run `docker compose up -d` without the `-f` flag, Docker Compose automatically loads `docker-compose.override.yml` if it exists alongside `docker-compose.yml`. This makes `docker-compose.override.yml` ideal for local development overrides — checked-into-git structures, secrets in `.env`.

### Explicit Named Override Files

For staging, production, or other environments, use the `-f` flag to specify exactly which files to merge:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

The later file wins in conflicts. The project name defaults to the directory name. Override it with `-p`:

```bash
docker compose -p myapp -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Base Configuration — Shared docker-compose.yml

Start with a base file that defines the common structure for all environments. Use YAML extension fields (`x-` prefixed keys) to keep it DRY:

```yaml
x-app-defaults: &app-defaults
  restart: unless-stopped
  networks:
    - backend
  environment:
    - TZ=America/Santo_Domingo
    - APP_ENV=${APP_ENV:-development}

x-healthcheck: &healthcheck
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:80/health"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 15s

services:
  app:
    image: myapp:latest
    container_name: myapp
    <<: [*app-defaults, *healthcheck]
    expose:
      - "9000"

  db:
    image: mariadb:11
    container_name: myapp-db
    <<: *app-defaults
    volumes:
      - db-data:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MYSQL_DATABASE: ${DB_NAME:-myapp}
    expose:
      - "3306"

  web:
    image: nginx:alpine
    container_name: myapp-web
    <<: *app-defaults
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - app
    expose:
      - "80"

volumes:
  db-data:

networks:
  backend:
    driver: bridge
```

Key points: services use `expose` (internal only, no host ports), extension fields keep configs consistent, and `APP_ENV` defaults to `development`.

## Development Override — docker-compose.override.yml

This file loads automatically when you run `docker compose up -d` in the project directory:

```yaml
services:
  app:
    ports:
      - "127.0.0.1:9000:9000"
    volumes:
      - ./src:/var/www/html:cached
    environment:
      APP_DEBUG: "1"
      XDEBUG_MODE: debug

  db:
    ports:
      - "127.0.0.1:3306:3306"
    volumes:
      - db-data-dev:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: devpassword
      MYSQL_DATABASE: ${DB_NAME:-myapp}

  web:
    ports:
      - "127.0.0.1:8080:80"
    volumes:
      - ./src:/var/www/html:cached
      - ./nginx.dev.conf:/etc/nginx/conf.d/default.conf:ro

volumes:
  db-data-dev:
```

What the dev override does:

- Binds service ports to `127.0.0.1` only — accessible from the Docker host but not the network.
- Bind-mounts source code into `app` and `web` for live reload.
- Enables debug mode and Xdebug for the PHP/Node.js app service.
- Sets a simple dev password in the environment (never in the base file).
- Uses a separate named volume for dev database data so it doesn't pollute production volumes.

## Production Override — docker-compose.prod.yml

For production, add resource limits, healthchecks, read-only filesystems, and reverse proxy integration:

```yaml
services:
  app:
    ports: []
    restart: always
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "512M"
        reservations:
          cpus: "0.5"
          memory: "256M"
    logging:
      driver: journald
      options:
        tag: myapp
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp.rule=Host(`app.yourdomain.com`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.services.myapp.loadbalancer.server.port=80"

  db:
    restart: always
    deploy:
      resources:
        limits:
          memory: "1G"
        reservations:
          memory: "512M"
    volumes:
      - db-data-prod:/var/lib/mysql
    logging:
      driver: journald
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s

  web:
    restart: always
    read_only: true
    deploy:
      resources:
        limits:
          memory: "128M"
    logging:
      driver: journald

volumes:
  db-data-prod:
```

Key production hardening:

- `read_only: true` prevents any container filesystem writes.
- `security_opt: no-new-privileges:true` prevents privilege escalation inside the container.
- `cap_drop: ALL` followed by minimal `cap_add` implements least-privilege.
- `deploy.resources.limits` caps CPU and memory — essential on a shared homelab host.
- `deploy.resources.reservations` guarantees minimum resources.
- `logging.driver: journald` sends logs to the host's systemd journal, centralised with Loki or your log aggregator.
- Traefik labels route traffic to the web service. The `ports: []` in the app service ensures no direct host port exposure.
- Separate named volumes for production data prevent accidental data overwrite.

## Staging Override — docker-compose.staging.yml

Staging sits between dev and prod — similar structure to prod but relaxed limits and a different DNS name:

```yaml
services:
  app:
    ports:
      - "127.0.0.1:9001:9000"
    restart: always
    deploy:
      resources:
        limits:
          cpus: "1"
          memory: "256M"
    environment:
      APP_DEBUG: "1"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp-staging.rule=Host(`staging.yourdomain.com`)"
      - "traefik.http.routers.myapp-staging.entrypoints=websecure"

  db:
    restart: always
    deploy:
      resources:
        limits:
          memory: "512M"
    volumes:
      - db-data-staging:/var/lib/mysql

  web:
    restart: always
    deploy:
      resources:
        limits:
          memory: "96M"

volumes:
  db-data-staging:
```

## Running Each Environment

With all files in place, the workflow is clean:

```bash
# Development — auto-loads docker-compose.override.yml
cd /opt/myapp
docker compose up -d

# Staging — explicit merge with staging override
docker compose -f docker-compose.yml -f docker-compose.staging.yml -p myapp-staging up -d

# Production — explicit merge with prod override
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p myapp-prod up -d

# Check what's running
docker compose -p myapp-staging ps
docker compose -p myapp-prod ps
```

### Shell Aliases for Convenience

Add these to your `.bashrc` or `.zshrc`:

```bash
alias dc='docker compose'
alias dcdev='docker compose up -d'
alias dcstag='docker compose -f docker-compose.yml -f docker-compose.staging.yml -p myapp-staging up -d'
alias dcprod='docker compose -f docker-compose.yml -f docker-compose.prod.yml -p myapp-prod up -d'
alias dcstag-down='docker compose -p myapp-staging down'
alias dcprod-down='docker compose -p myapp-prod down'
```

### Gitignore Strategy

Keep the override structure clean in version control:

```gitignore
# .gitignore
.env

# Ignore the auto-loaded dev override — it's personal
docker-compose.override.yml

# Track named overrides — they define environment configs
# docker-compose.prod.yml
# docker-compose.staging.yml
```

The auto-loaded `docker-compose.override.yml` is ignored because it contains personal dev preferences and possibly secrets. Named overrides (`prod.yml`, `staging.yml`) are tracked in git — they are infrastructure definitions, not secrets.

## Advanced Patterns: Extension Fields with YAML Anchors

Extension fields (`x-*`) let you reuse YAML blocks across services and override files:

```yaml
# docker-compose.yml
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

x-healthcheck-web: &healthcheck-web
  test: ["CMD", "wget", "-qO-", "http://localhost:80/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s

services:
  app:
    image: myapp:latest
    logging: *default-logging

  web:
    image: nginx:alpine
    logging: *default-logging
    healthcheck: *healthcheck-web
```

In production override, swap the logging driver:

```yaml
# docker-compose.prod.yml
x-logging: &default-logging
  driver: journald

services:
  app:
    logging: *default-logging
  web:
    logging: *default-logging
```

Override files merge YAML anchors just like any other map key.

## Security Considerations for Override Deployments

1. **Never put secrets in override files tracked in git.** Use `.env` files with `.gitignore` for passwords, API keys, and tokens. Override files are for structure and config — not secrets.

2. **Dev overrides should bind to 127.0.0.1**, not 0.0.0.0, to prevent accidental network exposure on your homelab.

3. **Production overrides should strip all dev ports.** Use `ports: []` or `expose` only. If you need host access, route through your reverse proxy exclusively.

4. **Resource limits prevent noisy-neighbour problems.** Without `deploy.resources.limits`, one container can starve others on the same Docker host.

5. **Read-only root filesystem + no-new-privileges** should be default for production containers. Override files make this easy — define it once in the override, not in every base service.

## Conclusion

Docker Compose override files solve the multi-environment problem without branching, template engines, or duplicate compose files. A single `docker-compose.yml` holds the shared structure. `docker-compose.override.yml` provides dev defaults automatically. Named override files (`docker-compose.prod.yml`, `docker-compose.staging.yml`) layer on environment-specific hardening, resources, and network config.

In my homelab, this pattern eliminated config drift between environments. Port mapping, volume mounts, resource limits, and security settings each live in the right layer. Using extension fields and YAML anchors keeps everything DRY. One directory, three environments, zero duplication.

### See Also

- [Docker Compose Profiles — Selective Service Management for Homelab](/posts/docker-compose-profiles-homelab/)
- [Docker Compose Environment Variables — .env, Substitution, and Secrets](/posts/docker-compose-env-variables/)
- [Docker Compose Production Patterns](/posts/docker-compose-production-patterns/)
