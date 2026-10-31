---
title: "Docker Compose Health Checks — Reliable Service Startup Orchestration"
description: "Use health-based startup dependencies, inspect probe results, and test an unhealthy running container in a disposable Compose lab."
date: 2026-05-14T13:30:00-04:00
lastmod: 2026-10-31
draft: false
tags: [docker, docker-compose, devops, homelab, linux]
keywords: [Docker Compose healthcheck, service_healthy, container readiness]
summary: "A small Redis lab explains startup gating, health transitions, and the limits of automatic recovery."
---

A running container can still be unable to serve requests. A health check runs a probe inside the container; Compose can wait for a passing probe before starting a dependent service.

That startup gate does not replace application retry logic or ongoing monitoring. Choose a probe that measures the capability the consumer actually needs.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official references below reviewed on October 31, 2026. |
| Static checks | Bash syntax, YAML parsing, and example structure checked. |
| Runtime | Docker is unavailable in the review environment; no image pull, Compose validation, or container execution performed. |
| Example scope | Disposable Redis lab, not an authenticated or persistent production deployment. |

## 1. Separate health, startup, and restarts

| Mechanism | What it does |
|---|---|
| Health check | Reports starting, healthy, or unhealthy from probe results. |
| depends_on with service_healthy | Gates a dependent service's startup on the dependency's health. |
| Container restart policy | Handles process exits; unhealthy status alone is not an exit. |

Compose does not automatically stop or restart existing consumers whenever a dependency later becomes unhealthy. Applications still need to recover from lost connections. Dependency-level `restart: true` concerns explicit Compose operations and differs from the service's process restart policy.

See [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/).

## 2. Create a disposable lab

Use a supported Docker Engine and the `docker compose` plugin. This demo publishes no host ports and contains no production data or credentials. The Redis Alpine image provides its client and the shell tools used here.

Run in Bash. A new temporary directory separates the example from existing projects:

```bash
health_lab_dir=$(mktemp -d -t compose-health-lab.XXXXXX)
cd "$health_lab_dir" || exit 1
docker version
docker compose version

cat > compose.yaml <<'EOF'
services:
  redis:
    image: redis:7.4-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    healthcheck:
      test:
        - CMD-SHELL
        - "test ! -f /tmp/force-unhealthy && redis-cli ping | grep -qx PONG"
      interval: 5s
      timeout: 3s
      retries: 3
      start_period: 10s

  client:
    image: redis:7.4-alpine
    depends_on:
      redis:
        condition: service_healthy
    command: ["sh", "-c", "redis-cli -h redis ping | grep -x PONG"]
    restart: "no"
EOF

docker compose config --quiet
```

Record image digests and tool versions when you run the exercise; version-series tags can change.

The file test is a **lab-only failure switch**. The Redis portion expects [PING](https://redis.io/docs/latest/commands/ping/) to return PONG. It does not test credentials, application data, persistence, or remote connectivity.

## 3. Start and inspect

Continue in the same lab directory:

```bash
docker compose up -d
docker compose ps -a
docker compose logs client

redis_id=$(docker compose ps -q redis)
test -n "$redis_id" &&
  docker inspect --format '{{json .State.Health}}' "$redis_id"
```

Expected behavior to verify: Redis becomes healthy, then Compose starts the client. The client prints PONG and exits successfully because it is a one-shot check. Confirm its exit code in `docker compose ps -a`.

The local probe and the client request exercise different paths. Neither proves a complete application works.

## 4. Test unhealthy status without stopping the process

Use this only in the disposable project:

```bash
docker compose exec redis touch /tmp/force-unhealthy
docker compose ps -a
```

Wait for consecutive probe failures and repeat the inspection commands. Expected result: Redis remains running while its health becomes unhealthy. The completed client does not rerun automatically.

Restore the probe without restarting Redis:

```bash
docker compose exec redis rm /tmp/force-unhealthy
docker compose ps -a
```

After a passing probe, health should return to healthy. Inspect stored probe output rather than assuming a fixed delay. This simulates probe failure, not a real Redis outage.

When finished, remove only this disposable project's containers, network, and anonymous volumes:

```bash
docker compose down --volumes
```

Run cleanup from the lab directory. Do not copy the volume-removal option into a production cleanup routine.

## 5. Tune timing and command execution

`interval` controls regular checks, `timeout` limits each probe, and `retries` counts consecutive failures. During `start_period`, early failures are initially ignored; checks still run. A success during that period ends the initial failure exemption.

Optional `start_interval` requires Compose 2.20.2 or later and Engine 25.0 or later. A top-level file version does not enable it. The old claim that service_healthy itself requires Compose 2.20 was incorrect.

Use `CMD` for a direct executable invocation. Use `CMD-SHELL` for shell operators or container-side variable expansion. The required shell and executable must exist in the actual image.

See the [Compose healthcheck reference](https://docs.docker.com/reference/compose-file/services/#healthcheck) and [Docker HEALTHCHECK behavior](https://docs.docker.com/reference/dockerfile/#healthcheck).

Read probe output and service logs before increasing grace periods. Missing tools, authentication failures, and incorrect URLs need correction, not longer delays.

## 6. Choose database probes with precise limits

These are fragments for existing services, not additional runnable stacks.

For PostgreSQL configured with user and database named myapp:

```yaml
healthcheck:
  test: ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "myapp", "-d", "myapp"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

[pg_isready](https://www.postgresql.org/docs/current/app-pg-isready.html) reports whether the server accepts connections. It does not prove credentials authenticate or migrations finished. Add an application-specific query or readiness endpoint when needed.

For a compatible official MariaDB image:

```yaml
healthcheck:
  test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 40s
```

Check [MariaDB healthcheck.sh](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/using-healthcheck-sh) against the image version and initialized volume. Older volumes may need setup for the helper's health-check account. Prefer its supported helper over passing a root password to a ping command.

For variable-based probes, remember that Compose normally interpolates dollar expressions before creation. Use `$$` to preserve a literal dollar sign for later container-shell expansion. Exec-form CMD does not itself expand shell variables. See [Compose interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## 7. Extend only after the baseline works

Replace the one-shot client with a real application image or complete build context. Define a readiness endpoint that fails until required initialization completes, and ensure the probe tool exists.

Keep reconnect logic even with startup gating. Avoid circular dependencies and unnecessary gates that delay monitoring or log collection. Test initial startup and a later dependency outage in isolation.

Record tool versions, image digests, configuration validation, probe logs, consumer results, and recovery behavior. YAML parsing alone cannot validate image contents or service readiness.

## Continue reading

- [Monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) — Add external visibility beyond a local probe.
- [Ansible homelab automation](/posts/2026-05-27-ansible-homelab-automation/) — Manage configuration after verifying behavior.
