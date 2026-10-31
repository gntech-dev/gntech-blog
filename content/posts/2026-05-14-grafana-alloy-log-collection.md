---
title: "Grafana Alloy Log Collection — Docker Logs with Loki in 2026"
description: "Send an opt-in Docker test stream through Alloy to an existing Loki instance, then verify it in Grafana Explore before migrating collectors."
date: 2026-05-14T18:30:00-04:00
lastmod: 2026-10-31
draft: false
tags: [monitoring, docker, containers, linux, devops]
keywords: [Grafana Alloy Docker logs, Loki log collection, Alloy validate, Promtail migration]
summary: "Verify one Docker log stream end to end before expanding collection or replacing Promtail."
---

Promtail reached end of life on March 2, 2026. Grafana directs users toward Alloy or another supported client. See the [Promtail notice](https://grafana.com/docs/loki/latest/send-data/promtail/).

Start a migration with a controlled test stream. A running collector does not prove that Loki accepted its entries or that Grafana can query them.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official Grafana references below reviewed on October 31, 2026. |
| Static checks | Bash syntax, embedded Compose YAML, and pipeline references checked. |
| Runtime | Docker and Alloy are unavailable in the review environment. No image pull, Alloy validation, ingestion, or Grafana query executed. |
| Scope | Linux Docker Engine with an existing trusted, single-tenant Loki test endpoint. Host files and production authentication are outside this example. |

## 1. Check the prerequisites

You need a working Loki instance, Grafana with access to it, and a Docker network shared with Loki. This article does not install or reconfigure Loki. The [monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) cover metrics, not a preinstalled Loki service.

For this test, Loki must be reachable as `http://loki:3100` from the selected Docker network. Confirm its service name or network alias. If yours differs, change the URL in the Alloy file below. Container localhost refers to that container, not the host or another service.

Choose a supported Alloy image tag or digest and review its matching documentation. The commands ask for that image and the actual existing network name rather than silently selecting an unreviewed version.

Alloy needs Docker API access. A read-only socket bind mount does **not** make Docker API operations read-only; treat socket access as privileged host access. Run this lab only on a trusted Docker host. The label filter limits collection, not API privileges.

## 2. Create a separate test project

Run in Bash:

```bash
alloy_lab_dir=$(mktemp -d -t alloy-logs-lab.XXXXXX)
cd "$alloy_lab_dir" || exit 1
read -r -p 'Reviewed Alloy image tag or digest: ' ALLOY_IMAGE
read -r -p 'Existing Docker network shared with Loki: ' LOKI_NETWORK
export ALLOY_IMAGE LOKI_NETWORK
docker network inspect "$LOKI_NETWORK"

cat > compose.yaml <<'EOF'
services:
  alloy:
    image: ${ALLOY_IMAGE:?Set a reviewed Alloy image tag or digest}
    user: "0:0"
    command:
      - run
      - /etc/alloy/config.alloy
      - --storage.path=/var/lib/alloy/data
      - --server.http.listen-addr=0.0.0.0:12345
    volumes:
      - ./config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - alloy_state:/var/lib/alloy/data
    ports:
      - "127.0.0.1:12346:12345"
    networks:
      - logging

  log_demo:
    image: busybox:1.37
    command: ["sh", "-c", "while true; do echo alloy-demo-check; sleep 5; done"]
    labels:
      com.gntech.alloy-demo: "true"
    logging:
      driver: json-file
      options:
        max-size: "1m"
        max-file: "2"
    networks:
      - logging

volumes:
  alloy_state:

networks:
  logging:
    external: true
    name: ${LOKI_NETWORK:?Set the existing Loki network name}
EOF
```

Only Alloy's UI is published, bound to loopback on port 12346. Keep that interface private. This example runs Alloy as root for socket access; choose a reviewed permission model before production deployment.

The named state volume retains collector state across container recreation. That does not guarantee exactly-once delivery. Record image digests and tool versions for reproducibility.

## 3. Define one connected pipeline

```bash
cat > config.alloy <<'EOF'
discovery.docker "demo" {
  host = "unix:///var/run/docker.sock"

  filter {
    name   = "label"
    values = ["com.gntech.alloy-demo=true"]
  }
}

loki.source.docker "demo" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.docker.demo.targets
  labels     = { job = "alloy_demo" }
  forward_to = [loki.write.destination.receiver]
}

loki.write "destination" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
EOF
```

Discovery selects only the labelled test container. The source reads its Docker logs and forwards them to the Loki writer. No host log files or collector self-logs are included.

Review [Docker discovery](https://grafana.com/docs/alloy/latest/reference/components/discovery/discovery.docker/), [Docker log collection](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/), and [Loki writing](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/) for supported arguments.

These are generally available components. They do not need an experimental stability setting. The old claim that omitting such a flag silently skips them was incorrect.

## 4. Validate before starting

Continue in the same shell and project directory:

```bash
docker compose config --quiet
docker compose run --rm --no-deps alloy validate /etc/alloy/config.alloy
```

The supported command is [alloy validate](https://grafana.com/docs/alloy/latest/reference/cli/validate/), not `alloy tools CONFIG`. A zero validation exit code establishes configuration validity; it does not prove permissions, network access, or delivery.

If either check fails, resolve its diagnostics before starting. For authenticated or multi-tenant Loki, configure the required authentication, TLS, and tenant settings using the writer documentation. Do not disable TLS verification to hide a certificate problem.

## 5. Verify the marker end to end

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=30 log_demo
docker compose logs --tail=80 alloy
```

Confirm the demo emits `alloy-demo-check`. Open Alloy's UI at `http://127.0.0.1:12346` on the Docker host and inspect the discovery, source, and writer components. An overall health response alone is insufficient evidence.

In Grafana, configure a **Loki** data source pointing to Loki's base URL reachable from the Grafana server. Alloy is the collector, not the Loki query data source. If Grafana shares this network, that base URL may be `http://loki:3100`.

Open Explore, select the Loki data source, choose a recent time range, and run:

```logql
{job="alloy_demo"} |= "alloy-demo-check"
```

Record a returned entry and its timestamp as the delivery check. If no result appears, work backwards: Grafana data-source URL and tenant, Loki acceptance errors, writer connection, discovery target, Docker logging availability, and source output. Allow time for discovery and batching; do not use configuration reload as a substitute for diagnosing target discovery.

Use the [Loki data-source documentation](https://grafana.com/docs/grafana/latest/datasources/loki/) when configuring Grafana.

## 6. Migrate deliberately

Test a small production subset with separate labels or a separate destination before switching collectors. Running two collectors against identical sources can duplicate ingestion. Compare actual source coverage, labels, timestamps, query results, and error behavior.

Keep a rollback configuration and preserve collector state. Retire the old collector only after the replacement is verified. Avoid a broad remove-orphans command that may remove unrelated services.

Loki retention is separate from ingestion-age validation. Rejecting samples older than 168 hours does not delete stored logs after seven days. Configure and verify retention against the installed Loki version using the [retention guide](https://grafana.com/docs/loki/latest/operations/storage/retention/).

A plain S3 endpoint is not a Loki push API. Archive configuration belongs to the appropriate storage system; do not send loki.write requests to an arbitrary bucket URL.

## 7. Stop the test without deleting state

From this lab directory:

```bash
docker compose down
```

This stops the demo and Alloy while preserving the named volume and external Loki network. It does not remove entries already ingested into Loki.

Before expanding to host logs, review file permissions and the source type. A read-only mount does not grant file-read permission, and some hosts use only journald. Do not make authentication logs world-readable as a troubleshooting shortcut.

## Continue reading

- [Compose health checks](/posts/2026-05-14-docker-compose-healthchecks/) — Distinguish startup, readiness, and recovery.
- [Monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) — Keep the metrics and log paths clear.
