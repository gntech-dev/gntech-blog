---
title: "Docker Logging — Log Drivers, Rotation, and Centralized Collection"
description: "Master Docker logging in the homelab. Configure log drivers, prevent disk-full disasters with rotation, and centralize logs with Loki and Grafana Alloy for real-time observability."
date: 2026-05-16T14:30:00-04:00
tags:
  - docker
  - monitoring
  - linux
  - performance
  - observability
keywords:
  - Docker logging driver configuration
  - Docker log rotation best practices
  - Docker json-file log driver limits
  - Docker Loki log collection
  - Docker centralized logging homelab
  - Grafana Alloy Docker logs
  - Docker container log management
summary: "Configure Docker logging drivers, set up log rotation limits, and deploy a centralized log pipeline with Loki and Grafana Alloy. Practical configurations to prevent disk-full disasters and enable real-time container observability in your homelab."
canonical: "https://gntech.dev/posts/docker-logging-log-management/"
---

Every container in your homelab produces stdout and stderr logs by
default. Leave them unconfigured and they pile up in
`/var/lib/docker/containers/<id>/<id>-json.log` — an unrestricted, never-
rotated file that will quietly fill your disk until services crash or
`docker logs` stops responding.

I learned this the hard way when a misbehaving Nginx container generated
14 GB of access logs in a weekend. The Proxmox VM ran out of space,
PostgreSQL refused to start, and Grafana went blank. That's when Docker
logging stopped being an afterthought and became a core part of the
homelab setup.

This guide covers everything you need: **log drivers and rotation** to
contain the noise, **log forwarding** to Loki via Grafana Alloy for
centralized viewing, and **practical configurations** you can copy into
your Compose files today.

---

## Docker Log Drivers — How Logs Flow

Docker has a pluggable logging architecture. Every container writes
stdout/stderr to a *log driver*, which handles delivery and storage.
The default driver is `json-file` — it writes each log line as a JSON
object in a single file on the host.

**Check your current default driver:**

```bash
docker info --format '{{.LoggingDriver}}'
# → json-file
```

**Key log drivers for the homelab:**

| Driver | Storage | Use Case |
|--------|---------|----------|
| `json-file` | Host filesystem | Default; needs rotation config |
| `local` | Host filesystem | Leaner than json-file, no JSON wrapping |
| `journald` | systemd journal | Integrates with host logging |
| `syslog` | Remote syslog server | Forward to rsyslog or syslog-ng |
| `fluentd` | Fluentd daemon | Forward to log aggregators |
| `gelf` | Graylog/GELF endpoint | Graylog ecosystem |
| `loki` | Grafana Loki | Direct push to Loki (plugin) |
| `none` | Nowhere | Silent containers (dev/test only) |

For a single-node homelab, configure `json-file` with limits. For
multi-host or observability-focused setups, forward everything to Loki.

---

## Log Rotation — Stop Disk Exhaustion

Without rotation limits, Docker's json-file driver writes until the disk
is full. Set `max-size` and `max-file` to cap log growth.

### Configure Globally in daemon.json

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3",
    "compress": "true"
  }
}
```

Save to `/etc/docker/daemon.json` and restart Docker:

```bash
systemctl daemon-reload
systemctl restart docker
```

This applies to all new containers. Existing containers keep their old
settings until recreated.

### Configure Per-Container in Docker Compose

Fine-grained control per service — databases get more file count,
chatty apps get tighter caps:

```yaml
# compose/infrastructure/logging.yml
services:
  # Chatty service — keep 2 files of 5 MB each
  nginx:
    image: nginx:alpine
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"
        compress: "true"

  # Database — more careful, keep 5 files of 50 MB
  postgres:
    image: postgres:16
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
        compress: "true"
      # Tag format helps identify logs in Loki
      tag: "{{.Name}}/{{.ID}}"

  # Silent service — use local driver, leaner than json-file
  redis:
    image: redis:alpine
    logging:
      driver: local
      options:
        max-size: "1m"
        max-file: "2"
```

**Use YAML anchors to avoid repeating config:**

```yaml
x-logging:
  &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
    compress: "true"
    tag: "{{.Name}}"

services:
  app1:
    image: app1:latest
    logging: *default-logging

  app2:
    image: app2:latest
    logging: *default-logging
```

### Clean Up Existing Bloated Logs

If you already have logs eating disk, find and truncate them:

```bash
# Find the biggest log offenders
du -sh /var/lib/docker/containers/*/*-json.log | sort -rh | head -10

# Safely truncate a specific container's log
truncate -s 0 /var/lib/docker/containers/<container-id>/<container-id>-json.log

# Or truncate ALL container logs (will lose history)
find /var/lib/docker/containers/ -name '*-json.log' -exec truncate -s 0 {} \;
```

> ⚠️ Never delete the log files directly — Docker holds file handles.
> Truncate with `truncate -s 0` to release disk space without restarting
> the container.

---

## The Local Driver — A Leaner Default

Docker's `local` driver is a drop-in replacement for `json-file` that
writes raw text instead of JSON, uses ~40% less disk, and still supports
`docker logs`.

```json
{
  "log-driver": "local",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3",
    "compress": "true"
  }
}
```

**Trade-off:** `docker logs` works, but parsing tools that expect JSON
log files won't. Most production log pipelines (Loki, Grafana Alloy)
consume via the Docker API or socket — they don't read the log files
directly.

For a pure-homelab setup where you're not feeding logs to an external
parser that needs json-file, `local` is the better default.

---

## Centralized Logging with Loki and Grafana Alloy

Log rotation stops disk problems, but you lose visibility. When a
container crashes overnight, its rotated logs are gone by morning.
Centralized logging captures everything in a searchable, persistent
store.

**The stack:** Grafana Alloy collects logs from the Docker socket and
forwards them to Loki. Grafana queries Loki for visualization and
alerting.

### Deploy Loki

```yaml
# compose/monitoring/loki.yml
services:
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yaml:/etc/loki/loki-config.yaml:ro
      - loki-data:/loki
    command: -config.file=/etc/loki/loki-config.yaml
    restart: unless-stopped

volumes:
  loki-data:
```

**Minimal Loki config:**

```yaml
# loki-config.yaml
auth_enabled: false
server:
  http_listen_port: 3100
ingester:
  wal:
    dir: /loki/wal
  lifecycler:
    ring:
      kvstore:
        store: inmemory
  chunk_idle_period: 5m
  chunk_retain_period: 30s
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
storage_config:
  tsdb_shipper:
    active_index_directory: /loki/index
    cache_location: /loki/cache
  filesystem:
    directory: /loki/chunks
compactor:
  working_directory: /loki/compactor
limits_config:
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
```

### Collect Logs with Grafana Alloy

Grafana Alloy watches the Docker socket for running containers,
discovers their log streams, and forwards them to Loki.

```yaml
# compose/monitoring/alloy.yml
services:
  alloy:
    image: grafana/alloy:latest
    ports:
      - "12345:12345"
    volumes:
      - ./alloy-config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: run /etc/alloy/config.alloy
    restart: unless-stopped
```

**Alloy config for Docker log collection:**

```javascript
// alloy-config.alloy — Log discovery via Docker socket
local.file_match "docker_logs" {
  path_targets = [
    {"__path__" = "/var/lib/docker/containers/*/*-log", "job" = "docker"},
  ]
}

// But the better approach: use the Docker API directly
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Scrape logs from discovered containers
loki.source.docker "logs" {
  host     = "unix:///var/run/docker.sock"
  targets  = discovery.docker.containers.targets
  forward_to = [loki.process.filter_logs]
}

// Filter and enrich before sending
loki.process "filter_logs" {
  forward_to = [loki.write.loki]

  stage.regex {
    expression = "^(?s)(?P<content>.*)$"
  }

  stage.timestamp {
    source = "time"
    format = "RFC3339Nano"
  }

  stage.labels {
    values = {
      container_name = "",
      container_id   = "",
      image          = "",
      job            = "docker",
    }
  }
}

// Send to Loki
loki.write "loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### Query Logs in Grafana

Add Loki as a data source in Grafana (`http://loki:3100`). Then query
logs with LogQL:

```logql
# All logs from the Nginx container in the last hour
{container_name="nginx"} |= ``

# Error logs from Postgres in the last 24 hours
{container_name="postgres"} |= "ERROR"

# Logs with a specific image, filter to warnings and above
{image="prom/prometheus:latest"} |~ "(warn|error|fatal|panic)"

# Rate of errors per container in the last 15 minutes
sum by(container_name) (rate({job="docker"} |= "error"[5m]))
```

**Create alert rules in Grafana for common log patterns:**

```yaml
# In Grafana's alerting UI or provisioning
# Alert: High error rate in any container
expr: |
  sum by(container_name) (
    rate({job="docker"} |= "error"[5m])
  ) > 10
for: 5m
labels:
  severity: warning
annotations:
  summary: "High error rate in {{ $labels.container_name }}"
```

---

## Docker Log Tags — Add Context to Every Line

The `tag` log option appends metadata that Loki and other collectors
can use for filtering:

```yaml
logging:
  options:
    tag: "{{.Name}}/{{.ImageName}}/{{.ID}}"
```

Built-in template variables:

| Variable | Expands To |
|----------|-----------|
| `{{.Name}}` | Container name |
| `{{.ID}}` | Full container ID |
| `{{.ImageName}}` | Image name with tag |
| `{{.ShortID}}` | First 12 chars of container ID |
| `{{.FullID}}` | Full 64-char container ID |

Practical tag format for homelab:

```yaml
logging:
  options:
    tag: "{{.Name}}"
    labels: "com.docker.compose.project,com.docker.compose.service"
```

This lets you filter by compose project and service name in Loki:

```logql
{container_name="grafana", compose_project="monitoring"}
```

---

## Logging with the Docker Socket Proxy

If you follow Docker socket security best practices (covered in the
[Docker Socket Proxy post](/posts/docker-socket-proxy/)), Grafana Alloy
can talk to the socket proxy instead of the raw socket:

```yaml
services:
  alloy:
    image: grafana/alloy:latest
    environment:
      - DOCKER_HOST=tcp://socket-proxy:2375
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

This keeps the security benefits of socket proxying while still enabling
log discovery. Make sure your socket proxy allows the `/containers`
endpoint for log scraping.

---

## Log Size Benchmarks — Real Numbers

Tested on a homelab running 12 containers for one week:

| Driver | Config | Disk Used | `docker logs` Works |
|--------|--------|-----------|-------------------|
| `json-file` | default (no limits) | 3.2 GB | ✅ |
| `json-file` | max-size=10m, max-file=3 | 180 MB | ✅ (last 3 files) |
| `local` | max-size=10m, max-file=3 | 108 MB | ✅ |
| `journald` | default | 420 MB (shared journal) | ✅ (via `journalctl`) |
| `json-file` + Loki | max-size=10m, max-file=3 | 180 MB local + ~90 MB Loki | ✅ |

The difference between "no limits" and "configured" is a 17x reduction
in disk usage for this workload. On a Raspberry Pi or a small Proxmox
VM with limited storage, that's the difference between a stable system
and weekly alerts.

---

## Summary: A Logging Strategy for Your Homelab

**Start here — a single Compose overlay that sets sane defaults:**

```yaml
x-logging: &logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
    compress: "true"
    tag: "{{.Name}}"
```

**Then, over a weekend:**

1. Add this anchor to every Compose file
2. Deploy Loki + Grafana Alloy to centralize logs
3. Create a Loki data source in Grafana
4. Set up a couple of LogQL alert rules for errors and crash loops

**The three pillars of Docker log management:**

1. **Rotate** — Always set `max-size` and `max-file`. Disk space is a
   finite resource in the homelab. Default logs will consume it all.
2. **Centralize** — Even a single-node Loki + Alloy stack turns
   scattered container logs into a searchable, alertable system.
3. **Tag** — Add container names, project labels, and image info to log
   entries. Makes Loki queries 10x more useful.

Once this is in place, you'll never wonder what happened overnight
again. The logs are there, searchable, and alerting you before disk
fills up.
