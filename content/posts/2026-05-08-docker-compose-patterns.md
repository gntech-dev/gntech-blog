---
title: "Docker Compose Patterns for Homelab Stacks"
description: "Build a small Compose stack, then choose environment handling, networks, secrets, storage, logging, and recovery patterns deliberately."
date: 2026-05-08T12:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [docker, docker-compose, containers, homelab, devops]
categories: [homelab, containers]
---

Use a small, complete stack to learn the deployment workflow. Then add only the networking, storage, and secret-handling features the application needs.

Group services by ownership and lifecycle. A Compose project can contain several services, and you can operate on one service without restarting the whole project. Fixed container names are optional and can cause collisions or prevent scaling; service names are usually sufficient.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official Docker documentation reviewed on October 31, 2026. |
| Static checks | Bash syntax and embedded Compose YAML checked. |
| Runtime | Docker unavailable in this review environment; no Compose CLI validation, image pull, HTTP request, or resource test executed. |
| Example scope | Disposable static HTTP lab on Linux, not a captured production stack. |

## 1. Start with one complete project

This demo uses BusyBox's HTTP server and wget probe, a read-only content mount, loopback publishing, log rotation, and explicit resource limits. Use Bash and have curl installed on the host.

```bash
compose_lab_dir=$(mktemp -d -t compose-patterns-lab.XXXXXX)
cd "$compose_lab_dir" || exit 1
mkdir www
printf 'gntech-compose-check\n' > www/index.html
chmod 755 www
chmod 644 www/index.html

cat > compose.yaml <<'EOF'
services:
  web:
    image: busybox:1.37
    user: "65534:65534"
    command: ["httpd", "-f", "-p", "8080", "-h", "/www"]
    ports:
      - "127.0.0.1:18080:8080"
    volumes:
      - ./www:/www:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"
    mem_limit: 64m
    cpus: 0.5
EOF

docker compose config --quiet
docker compose up -d
docker compose ps
curl --fail --silent --show-error http://127.0.0.1:18080/
```

Expected response to verify: gntech-compose-check. Wait for the health probe and inspect logs if it does not become healthy. The content permissions allow the selected non-root user to read this public test file.

This demo does not need persistence or a restart policy. For a long-running deployment, choose restart behavior to match its lifecycle. An unhealthy container is not automatically restarted merely because a restart policy exists.

## 2. Separate interpolation from container environment

| Mechanism | Purpose |
|---|---|
| Shell variables, .env, or CLI --env-file | Supply values for Compose interpolation. |
| Service environment | Explicitly sets container environment variables. |
| Service env_file | Loads environment variables into that service's container. |

A service env_file does not supply values for interpolating the rest of compose.yaml. Use explicit CLI --env-file choices when you need shared interpolation inputs, and check the resolved configuration.

Do not assume every value in .env becomes a container environment variable. Shell values and file precedence also matter. See [Compose interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

Keep secret values out of Git, including application configuration files that may embed credentials. Review staged changes; a private repository is not a substitute for secret management. Treat resolved configuration output as sensitive when it contains secrets.

PUID and PGID are image-specific conventions, not universal Docker controls. Use the image's documented permissions model or a supported user setting.

## 3. Choose network access explicitly

| Choice | Meaning and limit |
|---|---|
| Default project bridge | Service-name discovery within the project; outbound connectivity normally available. |
| Published port | Makes a container port reachable through a host binding; select the bind address intentionally. |
| External network | Network lifecycle is managed outside this project; it does not inherently mean internet access. |
| Internal network | Externally isolated network; not a blanket guarantee that the host cannot access containers. |
| Host network mode | Shares the host network namespace; no normal port mapping or project service-name discovery. |

Use [Compose networking](https://docs.docker.com/compose/how-tos/networking/) to select the actual connectivity model. Shared networks let services in different projects communicate; attach only the necessary services and avoid ambiguous aliases.

Neither internal networking nor loopback publishing substitutes for a complete host and application access policy. Services attached to multiple networks need their combined access reviewed.

Macvlan is a separate design for direct layer-2 attachment. It requires planned addressing, VLAN/switch support, and a host-communication strategy. It is not necessary merely to reach routed camera subnets. Do not treat switching to ipvlan as an automatic fix for host isolation. See [Docker macvlan](https://docs.docker.com/engine/network/drivers/macvlan/).

## 4. Use file secrets where the application supports them

Compose supports file-backed secrets without Swarm. This is a **partial example** for an existing compatible PostgreSQL service:

```yaml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

secrets:
  db_password:
    file: ./secrets/db_password
```

Supply the actual service image, storage, and other required settings separately. The application must support the file-reading convention; a generic DB_PASSWORD_FILE name does not make every application read it.

Compose mounts a local secret file into the authorized container. This is not an encrypted secret store and does not prevent a privileged host administrator or authorized container process from reading it. Protect source files, backups, and access permissions. See [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

## 5. Treat storage and consistency separately

| Storage | Useful property | Recovery requirement |
|---|---|---|
| Bind mount | Explicit host path, convenient configuration management | Back up selected contents with correct consistency and permissions. |
| Named volume | Docker-managed lifecycle and location | Preserve application data and document volume mapping and restore. |

Named volumes do not automatically solve UID/GID mismatches. Bind mounts are resolved on the Docker daemon host, and relative paths depend on the Compose project/file context. A read-only mount limits writes through that mount; it does not freeze other writers. See [bind mounts](https://docs.docker.com/engine/storage/bind-mounts/).

A raw rsync of a changing database directory is not an application-consistent backup. Use the [PostgreSQL dump and isolated restore guide](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/) and [Restic workflow](/posts/2026-05-19-restic-docker-backup-strategy/) for data preparation and recovery.

## 6. Keep operations verifiable

Log rotation settings apply per container, not as a total stack-disk guarantee. Review the active logging driver and volume growth. The [JSON logging reference](https://docs.docker.com/engine/logging/drivers/json-file/) explains the options.

Select supported image releases and record deployed digests. A major/minor tag is still mutable; a digest identifies exact image content. Updates need deliberate review, recovery preparation, and verification.

Memory and CPU limits constrain resources; they are not a promise of latency or application readiness. Reservations are not dedicated capacity on a standalone host. Inspect effective runtime settings and test representative workloads before depending on them.

Use the [health-check guide](/posts/2026-05-14-docker-compose-healthchecks/) for startup dependencies and recovery behavior. For metrics and logs, use the focused [monitoring](/posts/2026-05-17-homelab-monitoring-stack/) and [Alloy](/posts/2026-05-14-grafana-alloy-log-collection/) guides instead of a second inconsistent stack here.

## 7. Review changes and stop the lab

Before a real deployment, record configuration validation, image references, required secrets, network exposure, data locations, backup evidence, and the rollback path. Test recovery instead of assuming that compose up alone reconstructs lost data.

Inspect this lab and stop it from its project directory:

```bash
docker compose logs --tail=30 web
docker compose down
```

The source directory remains available for inspection. For real projects, down --volumes can delete persistent state; make that a separate, deliberate decision.
