---
title: "Grafana Loki — Centralized Docker Logging for Your Homelab"
description: "Set up Grafana Loki with Docker Compose for centralized container log collection, analysis, and alerting using Grafana Alloy — a complete homelab observability stack."
date: 2026-05-27T21:00:00Z
tags:
  - docker
  - monitoring
  - grafana
  - loki
  - observability
keywords:
  - Grafana Loki Docker logging homelab
  - centralized Docker log management Grafana
  - Grafana Alloy log collection Docker Compose
  - Docker log aggregation Loki Promtail alternative
  - Loki Prometheus monitoring stack homelab
  - Grafana Loki Docker log analysis alerting
  - Docker container log visualization dashboard
summary: "Collect, analyze, and alert on Docker container logs with Grafana Loki and Grafana Alloy. A complete centralized logging stack for your homelab with real Compose configs and dashboards."
canonical: "https://gntech.dev/posts/grafana-loki-centralized-docker-logging/"
---

If you manage more than a handful of Docker containers, you already know the pain. SSH into a node, scroll through `docker logs -f`, grep for error strings, repeat. No central search. No retention policy. No correlation with metrics.

Grafana Loki solves this. It is a log aggregation system designed around the same philosophy as Prometheus — cheap, scalable, and tightly integrated with Grafana. Unlike Elasticsearch, Loki indexes only metadata labels and compresses the log content itself, so it runs comfortably on a homelab server with 2 GB of RAM.

This post walks through a complete Loki stack deployment with Grafana Alloy (the modern replacement for Promtail) as the log collector, all in Docker Compose.

---

## Architecture: How the Stack Fits Together

The stack has three components:

- **Grafana Alloy** — watches Docker containers, scrapes stdout/stderr, attaches metadata labels, ships logs to Loki
- **Loki** — stores and indexes log streams, exposes LogQL query API on port 3100
- **Grafana** — queries Loki, builds dashboards, fires alerts

Alloy replaces Promtail. It supports the same pipelines but adds native OpenTelemetry, Prometheus scraping, and a more flexible configuration language.

---

## Deploying Loki with Docker Compose

Create a project directory:

```bash
mkdir -p /opt/loki-stack && cd /opt/loki-stack
```

Start with `docker-compose.yml`. Loki runs as a single binary and in single-process mode for homelab use — no microservices needed:

```yaml
services:
  loki:
    image: grafana/loki:3.4
    container_name: loki
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yml:/etc/loki/config.yml:ro
      - ./loki-data:/loki
    command: -config.file=/etc/loki/config.yml
    restart: unless-stopped
    networks:
      - loki-net

networks:
  loki-net:
    driver: bridge
```

The config file `loki-config.yml`:

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9095

common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  max_query_series: 500
  ingestion_rate_mb: 10
  per_stream_rate_limit: 5MB

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
```

Key settings:

- `schema: v13` with `store: tsdb` is the current recommended schema — fast queries, low memory
- `reject_old_samples_max_age: 168h` discards logs older than 7 days at ingestion
- `ingestion_rate_mb: 10` is fine for homelab; bump to 50 if you run 50+ containers

---

## Deploying Grafana Alloy for Log Collection

Grafana Alloy watches the Docker socket and streams container logs to Loki. Add it to `docker-compose.yml`:

```yaml
  alloy:
    image: grafana/alloy:v1.8
    container_name: alloy
    ports:
      - "12345:12345"
    volumes:
      - ./alloy-config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: run --server.http.listen-addr=0.0.0.0:12345 /etc/alloy/config.alloy
    restart: unless-stopped
    networks:
      - loki-net
```

The Alloy config file `alloy-config.alloy` uses the River configuration language:

```river
// Discover all running Docker containers
discovery.docker "all_containers" {
  host = "unix:///var/run/docker.sock"
}

// Scrape logs from discovered containers
loki.source.docker "container_logs" {
  host    = "unix:///var/run/docker.sock"
  targets = discovery.docker.all_containers.targets
  forward_to = [loki.process.add_compose_label]
}

// Add useful labels from Docker metadata
loki.process "add_compose_label" {
  forward_to = [loki.write.loki_endpoint]

  stage.static_labels {
    values = {
      source = "docker",
    }
  }

  stage.labels {
    values = {
      container_name  = "",
      compose_project = "",
      container_image = "",
    }
  }
}

// Ship to Loki
loki.write "loki_endpoint" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

What this does:

1. `discovery.docker` discovers running containers via the Docker socket
2. `loki.source.docker` tails stdout/stderr from each container
3. `loki.process` attaches labels — container_name, compose_project, container_image
4. `loki.write` pushes everything to Loki

No sidecar containers, no logging driver changes in other Compose stacks. Alloy handles it transparently.

---

## Deploying Grafana with Loki Datasource

Add Grafana to `docker-compose.yml`:

```yaml
  grafana:
    image: grafana/grafana:11.5
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - ./grafana-data:/var/lib/grafana
      - ./grafana-provisioning:/etc/grafana/provisioning:ro
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_INSTALL_PLUGINS=
    restart: unless-stopped
    networks:
      - loki-net
```

Provision the Loki datasource automatically so you don't need to click through the UI each time:

Create `grafana-provisioning/datasources/loki.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: false
    editable: true
    jsonData:
      maxLines: 1000
      derivedFields:
        - datasourceUid: prometheus
          matcherRegex: "trace_id=(\\w+)"
          name: TraceID
          url: "$${__value.raw}"
```

---

## Visualizing Logs with LogQL

LogQL is Loki's query language — similar to PromQL but for log streams. Basic patterns:

**See all logs from a specific container:**

```logql
{container_name="traefik"}
```

**Find errors across all containers:**

```logql
{container_name=~".+"} |= "error"
```

**Filter by compose project:**

```logql
{compose_project="monitoring"} |= "timeout" | json
```

**Count errors per container over 5-minute windows:**

```logql
sum by (container_name) (count_over_time({container_name=~".+"} |= "error" [5m]))
```

**Parse JSON logs from Traefik and extract status codes:**

```logql
{container_name="traefik"} | json | status_code >= 500 | line_format "{{.container_name}}: {{.status_code}} {{.request_uri}}"
```

To build a dashboard in Grafana:

1. Add a new dashboard → "Logs" panel
2. Query: `{container_name=~".+"} |= "error" | json`
3. Set visualization to "Logs" (built-in log viewer with highlighting)
4. Add a "Time series" panel with `rate({container_name=~".+"}[5m])` for log volume per container

---

## Log Retention and S3 Storage

For a homelab with 10-20 containers, filesystem storage works fine for about 7-14 days. Beyond that, configure Loki to use MinIO for scalable S3-compatible storage:

Add MinIO to the stack:

```yaml
  minio:
    image: minio/minio:latest
    container_name: minio
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ./minio-data:/data
    environment:
      MINIO_ROOT_USER: loki
      MINIO_ROOT_PASSWORD: changeme123
    restart: unless-stopped
    networks:
      - loki-net
```

Update `loki-config.yml` storage block:

```yaml
  storage:
    s3:
      endpoint: minio:9000
      access_key_id: loki
      secret_access_key: changeme123
      insecure: true
      bucketnames: loki-logs
      s3forcepathstyle: true
```

Retention configuration (28-day retention for chunks, 7-day for index):

```yaml
table_manager:
  retention_deletes_enabled: true
  retention_period: 672h
```

---

## Alerting on Log Patterns

Grafana can alert on log patterns using Loki as a data source.

**Alert: Error rate exceeds threshold**

1. Create a Grafana alert rule with the query:

```logql
sum(rate({container_name=~".+"} |= "error" [5m])) by (container_name) > 0.1
```

2. Set condition: `WHEN last() OF query (A, 5m, now) IS ABOVE 0.1`
3. Add notification channel (email, Telegram, Slack)

**Alert: Container crash loop detected**

```logql
count_over_time({container_name=~".+"} != "alive" != "ready" [2m]) > 10
```

---

## Troubleshooting

**Check Alloy logs:**

```bash
docker compose logs alloy
```

**Verify Loki is running:**

```bash
curl http://localhost:3100/ready
```

**List available labels in Loki:**

```bash
curl -s http://localhost:3100/loki/api/v1/label | jq .
```

**Test log push from curl:**

```bash
curl -s -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"test":"log"},"values":[["'$(date +%s%N)'","this is a test log line"]]}]}'
```

**Common issues**

- **No logs appearing in Grafana** — Alloy needs access to the Docker socket (`/var/run/docker.sock`). Check the volume mount.
- **Labels missing** — The `loki.source.docker` block in Alloy must have labels forwarded. Ensure the pipeline chain is complete.
- **High memory usage** — Reduce `max_query_series` in `limits_config` and lower `ingestion_rate_mb`.
- **Loki refuses old logs** — Check `reject_old_samples_max_age` in the config. Default is 168h (7 days).

---

## Next Steps

This Loki stack gives you centralized log search, retention policies, and alerting across all Docker containers in your homelab. From here you can:

- Add Prometheus to the same stack and correlate logs with metrics (CPU, memory, disk) in Grafana
- Set up Grafana OnCall for incident management
- Deploy a second Alloy instance on another Docker host and ship to the same Loki
- Replace the filesystem backend with S3 for production-grade retention

The full Compose file and configs are on [GitHub](https://github.com/gntech/homelab). Start with the patterns above and adapt them to your scale — whether that's 5 containers or 50.
