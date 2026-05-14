---
title: "Grafana Alloy Log Collection — Docker Logs with Loki in 2026"
description: "Replace Promtail with Grafana Alloy for Docker log collection in your homelab. Complete migration guide with docker-compose, Alloy config, and real Loki pipeline configs."
date: 2026-05-14T18:30:00-04:00
tags:
  - monitoring
  - docker
  - containers
  - linux
  - devops
keywords:
  - Grafana Alloy Docker setup
  - Grafana Alloy Promtail replacement
  - Docker logs Loki 2026
  - Grafana Alloy Docker compose
  - Loki Docker logging stack
  - Grafana Alloy log collection
  - Alloy config docker discovery
summary: "Grafana Alloy is the official Promtail replacement with EOL in March 2026. This guide covers a complete Docker logging stack with Alloy, Loki, and Grafana — including Alloy config syntax, Docker auto-discovery, host log collection, and the migration path from Promtail."
canonical: "https://gntech.dev/posts/grafana-alloy-log-collection/"
---

Grafana deprecated Promtail as of March 2, 2026. If you're still
running it in your homelab monitoring stack, your log pipeline still
works today but receives no new features or security patches. The
official replacement is Grafana Alloy — a unified telemetry collector
that handles logs, metrics, and traces in a single binary with a
component-based pipeline architecture.

The older monitoring setup on this blog from May 9 ([Homelab Monitoring
Stack](/posts/homelab-monitoring-stack/)) used Promtail for log shipping.
This post updates that stack with Alloy, including a complete
docker-compose deployment, Alloy's River config syntax, Docker container
auto-discovery, and host log tailing — all feeding into the same Loki
instance you probably already have.

---

## Why Grafana Alloy Replaced Promtail

Promtail was purpose-built for one thing: scraping log files and pushing
them to Loki. It did that well, but Grafana's direction is consolidation.
Alloy replaces three separate agents:

| Capability | Promtail | Grafana Agent (Static) | Grafana Agent (Flow) | Alloy |
|-----------|----------|----------------------|---------------------|-------|
| Log collection | ✅ | ❌ | ✅ | ✅ |
| Metrics collection | ❌ | ✅ | ✅ | ✅ |
| Traces collection | ❌ | ✅ | ✅ | ✅ |
| Component pipeline | ❌ | ❌ | ✅ | ✅ |
| Active development | ❌ EOL | ❌ EOL | ❌ EOL | ✅ |

If you're running a monitoring stack with Prometheus for metrics and
Loki for logs, you currently need two agents (Promtail + node_exporter
or Grafana Agent). With Alloy, one container handles everything.

The config syntax changed too. Promtail used YAML. Alloy uses River —
a declarative language similar to HCL but purpose-built for telemetry
pipelines. It's more verbose upfront but dramatically more flexible
when you need to filter, relabel, or route logs.

---

## Step 1: Project Structure

Create the directory layout:

```bash
mkdir -p /opt/alloy/{alloy,loki,grafana-data,loki-data}
cd /opt/alloy
```

Set correct ownership for Loki and Grafana data directories — these
run as non-root UIDs inside their containers:

```bash
sudo chown 10001:10001 loki-data/
sudo chown 472:472 grafana-data/
```

---

## Step 2: Docker Compose with Alloy

```yaml
# docker-compose.yml
services:
  loki:
    image: grafana/loki:3.4
    container_name: loki
    command: -config.file=/etc/loki/config.yml
    volumes:
      - ./loki/config.yml:/etc/loki/config.yml:ro
      - ./loki-data:/loki
    ports:
      - "3100:3100"
    restart: unless-stopped
    networks:
      - observability

  alloy:
    image: grafana/alloy:v1.7
    container_name: alloy
    command:
      - run
      - /etc/alloy/config.alloy
      - --server.http.listen-addr=0.0.0.0:12345
      - --stability.level=generally-available
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
    ports:
      - "12345:12345"
    restart: unless-stopped
    depends_on:
      - loki
    networks:
      - observability

  grafana:
    image: grafana/grafana:11.5
    container_name: grafana
    volumes:
      - ./grafana-data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped
    environment:
      - GF_INSTALL_PLUGINS=grafana-lokiexplore-app
    depends_on:
      - loki
    networks:
      - observability

networks:
  observability:
    driver: bridge
```

Key details in this compose file:

- **Alloy runs with `--stability.level=generally-available`** to
  enable the stable component set. Without this, some components like
  `loki.source.docker` may not be available.
- **Alloy gets access to `/var/log`** for host log tailing and
  **`/var/run/docker.sock`** for Docker container auto-discovery.
- **Grafana 11.5** includes native Loki Explore support without extra
  plugin configuration.

---

## Step 3: Loki Configuration

Standard Loki config with filesystem storage — sufficient for a
homelab that doesn't need S3 or GCS:

```yaml
# loki/config.yml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

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
  # Allow ingestion of up to 10 MB/s per source
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20

compactor:
  working_directory: /loki/compactor
  retention_enabled: true

retention:
  delete_worker_count: 10
```

The `reject_old_samples_max_age: 168h` prevents accidental bulk
uploads of old logs. For a homelab, 7-day retention is usually
sufficient. Adjust via retention policies in Loki if you need longer.

---

## Step 4: Alloy Configuration (River Syntax)

This is the core of the setup. Alloy uses River — not YAML. The config
defines a pipeline with stages that flow data from sources through
processors to the Loki write endpoint.

```river
// alloy/config.alloy — Grafana Alloy log pipeline

// 1. Send Alloy's own logs to Loki for debugging
logging {
  level = "info"
  format = "logfmt"
  write_to = [loki.relabel.alloy_logs.receiver]
}

// 2. Discover running Docker containers
discovery.docker "local_docker" {
  host = "unix:///var/run/docker.sock"
}

// 3. Match host log files
local.file_match "host_logs" {
  path_targets = [
    {__path__ = "/var/log/syslog"},
    {__path__ = "/var/log/auth.log"},
    {__path__ = "/var/log/kern.log"},
  ]
}

// 4. Tail matched host log files
loki.source.file "host_tail" {
  targets    = local.file_match.host_logs.targets
  forward_to = [loki.process.host_pipeline.receiver]
}

// 5. Process host logs — add static labels
loki.process "host_pipeline" {
  forward_to = [loki.write.local.receiver]

  stage.static_labels {
    values = {
      job      = "varlogs",
      source   = "host",
      env      = "homelab",
    }
  }
}

// 6. Collect Docker container stdout/stderr
loki.source.docker "docker_engine" {
  host   = "unix:///var/run/docker.sock"
  targets = discovery.docker.local_docker.targets
  labels = {
    job       = "docker_logs",
    env       = "homelab",
    collector = "alloy",
  }
  forward_to = [loki.process.docker_pipeline.receiver]
}

// 7. Process Docker logs — extract container metadata
loki.process "docker_pipeline" {
  forward_to = [loki.write.local.receiver]

  // Extract container name from Docker metadata labels
  stage.static_labels {
    values = {
      job  = "docker_logs",
      type = "container",
    }
  }
}

// 8. Relabel Alloy's own logs with a service label
loki.relabel "alloy_logs" {
  forward_to = [loki.write.local.receiver]

  rule {
    target_label = "service"
    replacement  = "alloy"
  }

  rule {
    target_label = "job"
    replacement  = "alloy_internal"
  }
}

// 9. Push everything to Loki
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### What each block does:

- **`discovery.docker`** — queries the Docker socket for running
  containers and exposes their metadata (name, image, labels) as
  targets for log collection.
- **`loki.source.docker`** — reads stdout/stderr from each discovered
  container using Docker's log API. No file scraping, no log rotation
  issues — Docker handles the I/O.
- **`local.file_match`** — finds host log files matching path globs.
  Unlike Promtail, Alloy uses a separate discovery + scraping model
  for files.
- **`loki.source.file`** — tails the matched log files and forwards
  lines through the pipeline.
- **`loki.process`** — applies processing stages (static labels,
  regex, relabeling, etc.) before sending to Loki.
- **`loki.write`** — the final destination. This is your Loki endpoint.

### Testing the config syntax

Before starting the stack, validate the Alloy config:

```bash
docker run --rm -v ./alloy/config.alloy:/config.alloy:ro \
  grafana/alloy:v1.7 \
  tools /config.alloy
```

If the config is valid, it prints "valid" and exits 0. If there are
syntax errors, it prints the line and column of each problem.

---

## Step 5: Start the Stack

```bash
docker compose up -d
docker compose logs -f alloy
```

Check that Alloy is running and connected to Loki:

```bash
# Alloy's HTTP health endpoint
curl -s http://localhost:12345/-/healthy

# Alloy's component status
curl -s http://localhost:12345/-/components | jq .
```

You should see components like `loki.write.local` with `ok` status
and `loki.source.docker.local_docker` scraping containers.

Verify logs are reaching Loki:

```bash
# Simple label query
curl -s "http://localhost:3100/loki/api/v1/labels" | jq .

# Query recent log entries for a Docker container
curl -s -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job="docker_logs"}' \
  --data-urlencode 'limit=10' \
  --data-urlencode 'start='$(date -d '1 hour ago' +%s)'000000000' \
  --data-urlencode 'end='$(date +%s)'000000000' \
  | jq '.data.result[].values[] | .[1]'
```

---

## Step 6: Add Alloy as a Grafana Data Source

In Grafana, go to **Connections → Add new connection** and search for
"Grafana Alloy". The Alloy HTTP endpoint exposes metrics at
`http://alloy:12345/metrics` — you can scrape those with Prometheus for
Alloy's own performance telemetry:

```yaml
# In your Prometheus scrape config
scrape_configs:
  - job_name: 'alloy'
    static_configs:
      - targets: ['alloy:12345']
```

This gives you dashboards for Alloy's log ingestion rate, component
health, and pipeline latency.

---

## Step 7: Migrating from Promtail

If you're replacing an existing Promtail setup, here's the migration
path:

### 1. Keep Promtail running alongside Alloy initially

```bash
# Leave Promtail running, start Alloy
docker compose up -d alloy
```

Let both run for an hour to verify Alloy is shipping logs correctly.
Compare entries in Loki for the same time window — you should see the
same log lines with potentially different labels.

### 2. Update Grafana dashboards

Promtail adds a `job` label of `varlogs` and a `container_name` label
on Docker logs. Alloy's config above sets `job="varlogs"` for host
logs and `job="docker_logs"` for container logs. Adjust dashboard
queries accordingly:

**Promtail query:**
```
{job="varlogs"} |= "error"
```

**Alloy query (same result):**
```
{job="varlogs", source="host"} |= "error"
```

### 3. Remove Promtail

```yaml
# Remove from docker-compose.yml
# services:
#   promtail:
#     image: grafana/promtail:3.0
#     ...
```

Then:

```bash
docker compose up -d --remove-orphans
```

---

## Step 8: Advanced Alloy Patterns

### Container Label-Based Filtering

Filter logs based on Docker labels — useful for excluding noisy
containers like healthcheck probes:

```river
// Only collect logs from containers with monitoring=true label
discovery.docker "filtered_docker" {
  host = "unix:///var/run/docker.sock"
  // Use Docker label com.example.monitoring.enabled=true
  filter {
    name   = "label"
    values = ["com.example.monitoring.enabled=true"]
  }
}

loki.source.docker "filtered_engine" {
  host   = "unix:///var/run/docker.sock"
  targets = discovery.docker.filtered_docker.targets
  labels = { job = "monitored_containers" }
  forward_to = [loki.write.local.receiver]
}
```

Add `com.example.monitoring.enabled=true` as a Docker label on your
compose services:

```yaml
services:
  nginx:
    image: nginx:alpine
    labels:
      com.example.monitoring.enabled: "true"
```

### Log Rate Limiting

Prevent a noisy container from overwhelming your Loki instance:

```river
loki.process "rate_limit" {
  forward_to = [loki.write.local.receiver]

  // Drop 90% of debug-level logs
  stage.drop {
    source = "level"
    value  = "debug"
    rate   = 0.9
  }

  // Hard rate limit: max 100 lines per second per container
  stage.rate_limit {
    rate = 100
    burst = 200
  }
}
```

### Multi-Destination Routing

Ship logs to two destinations — local Loki for hot queries and an
S3-compatible archive for compliance:

```river
// Local Loki
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}

// S3 archive (any S3-compatible service)
loki.write "archive" {
  endpoint {
    url = "https://s3.archive.internal.example.com/loki/api/v1/push"
    basic_auth {
      username = "access_key"
      password = "secret_key"
    }
  }
}

// Split pipeline — send all matched logs to both
loki.process "splitter" {
  forward_to = [
    loki.write.local.receiver,
    loki.write.archive.receiver,
  ]
}
```

---

## Step 9: Monitoring Alloy Itself

Alloy exposes its own metrics on the debug port. Add this to your
Prometheus config to monitor your monitor:

```yaml
scrape_configs:
  - job_name: 'alloy_self'
    scrape_interval: 15s
    static_configs:
      - targets: ['alloy:12345']
    metrics_path: '/metrics'
```

Key metrics to watch:

| Metric | What It Tells You |
|--------|-------------------|
| `loki_source_docker_entries_total` | Total log lines scraped from Docker |
| `loki_source_file_read_bytes_total` | Bytes read from host log files |
| `loki_write_encoded_bytes_total` | Bytes sent to Loki |
| `loki_write_request_duration_seconds` | Latency of Loki push requests |
| `alloy_component_health` | Per-component health (1=healthy, 0=unhealthy) |

Grafana has a community dashboard for Alloy — import ID `21571` to
get a pre-built view of these metrics.

---

## Troubleshooting

### No logs appearing in Loki

Check Alloy's own logs:

```bash
docker compose logs alloy | tail -20
```

If you see connection refused to Loki, check that Loki started before
Alloy and is listening on port 3100:

```bash
docker compose logs loki | tail -5
```

### Docker log scraping skipping containers

Alloy can miss containers that start after it. This is normal — the
discovery component polls every 30 seconds by default. Force a
rescan:

```bash
curl -X POST http://localhost:12345/-/reload
```

Or reduce the poll interval:

```river
discovery.docker "local_docker" {
  host         = "unix:///var/run/docker.sock"
  refresh_interval = "5s"
}
```

### Permission denied on /var/log

Alloy needs read access to host log files. If running in Docker,
the `:ro` mount on `/var/log` should be sufficient. If Alloy still
can't read specific files, check they're world-readable on the host:

```bash
sudo chmod 644 /var/log/auth.log
```

### Config validation fails

The `--stability.level=generally-available` flag is required for
`loki.source.docker` and `loki.source.file`. Without it, Alloy
starts but silently skips these components. Verify:

```bash
docker compose exec alloy alloy --version
# Should show v1.7+ with "stability level: generally-available"
```

---

## Summary

Grafana Alloy replaces Promtail cleanly for Docker log collection
and adds metrics and traces collection in the same container. The
migration is straightforward:

1. Deploy Alloy alongside your existing Loki + Grafana stack
2. Replace Promtail's YAML config with Alloy's River syntax
3. Validate logs flow to Loki before removing Promtail
4. Optionally add Prometheus scraping of Alloy's own metrics

The River config syntax takes a few minutes to learn if you're used
to YAML, but the component model makes complex pipelines — rate
limiting, multi-destination routing, label-based filtering —
significantly easier than Promtail's static config approach.

For a homelab running the monitoring stack from the earlier guide,
migrating to Alloy means one fewer container and confidence that
your log pipeline is on a supported path through 2026 and beyond.
