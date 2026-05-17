---
title: "Homelab Monitoring Stack — Prometheus, Grafana, Loki with Docker Compose"
description: "Deploy a complete monitoring stack with Prometheus, Grafana, Loki, and Grafana Alloy using Docker Compose. Covers metrics collection, log aggregation, alerting, and dashboard provisioning for your homelab."
date: 2026-05-17T14:30:00-04:00
tags:
  - docker
  - docker-compose
  - monitoring
  - homelab
  - linux
  - grafana
keywords:
  - Prometheus Grafana Docker Compose monitoring stack
  - Loki log aggregation Docker homelab setup
  - Grafana Alloy Docker log collection configuration
  - Prometheus Node Exporter cAdvisor container metrics
  - Docker monitoring stack alerting Alertmanager
  - homelab observability stack 2026
  - Prometheus alert rules homelab configuration
summary: "Deploy a complete homelab observability stack with Prometheus, Grafana, Loki, Grafana Alloy, and Alertmanager using Docker Compose. Includes pre-configured dashboards, alert rules, and log aggregation for Docker hosts."
canonical: "https://gntech.dev/posts/homelab-monitoring-stack/"
---

You have a dozen containers running on your Proxmox host, a MikroTik
router handling your VLANs, and maybe a NAS storing your backups. When
something breaks — a container OOMs, disk fills up, or a service stops
responding — finding the root cause means SSHing into machines and
grepping log files.

A monitoring stack changes that. Prometheus collects metrics, Loki
aggregates logs, and Grafana puts everything on dashboards. When things
go wrong, Alertmanager tells you before your users do.

This guide covers a full homelab monitoring deployment with Docker
Compose. It includes:

- **Prometheus** for time-series metrics
- **Grafana** for dashboards and visualization
- **Loki** for centralized log aggregation
- **Grafana Alloy** as the log collector (the modern Promtail replacement)
- **Node Exporter** for host-level system metrics
- **cAdvisor** for container-level metrics
- **Alertmanager** for alert routing and notifications
- **Pre-configured dashboards and alert rules** that work out of the box

---

## Architecture Overview

The stack has four layers:

1. **Data sources** — Node Exporter and cAdvisor expose metrics over
   HTTP. Alloy watches Docker container logs.
2. **Storage** — Prometheus scrapes metrics every 15s and stores them
   locally. Loki stores indexed logs.
3. **Visualization** — Grafana queries both Prometheus and Loki,
   displaying metrics and logs on the same dashboards.
4. **Alerting** — Prometheus evaluates alert rules. When triggered,
   Alertmanager sends notifications to Telegram, email, or webhooks.

All components run as Docker containers on a single host. The
configuration files are mounted as bind mounts so you can edit them
without rebuilding.

---

## Step 1: Directory Structure and Docker Compose

Create the project directory:

```bash
mkdir -p /opt/monitoring/{prometheus,grafana,loki,alloy,alertmanager}
cd /opt/monitoring
```

**`/opt/monitoring/docker-compose.yml`:**

```yaml
services:
  # Metrics storage
  prometheus:
    image: prom/prometheus:v2.55.0
    container_name: prometheus
    restart: unless-stopped
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"
      - "--web.console.libraries=/etc/prometheus/console_libraries"
      - "--web.console.templates=/etc/prometheus/consoles"
      - "--web.enable-lifecycle"
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus_data:/prometheus
    networks:
      - monitoring

  # Log storage
  loki:
    image: grafana/loki:3.2.0
    container_name: loki
    restart: unless-stopped
    command:
      - "-config.file=/etc/loki/loki-config.yml"
    volumes:
      - ./loki:/etc/loki:ro
      - loki_data:/loki
    networks:
      - monitoring

  # Log collector
  alloy:
    image: grafana/alloy:v1.6.0
    container_name: alloy
    restart: unless-stopped
    command:
      - "run"
      - "/etc/alloy/config.alloy"
      - "--server.http.listen-addr=0.0.0.0:12345"
      - "--stability.level=generally-available"
    volumes:
      - ./alloy:/etc/alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log:/var/log:ro
    depends_on:
      loki:
        condition: service_started
    networks:
      - monitoring

  # Host metrics exporter
  node-exporter:
    image: prom/node-exporter:v1.8.2
    container_name: node-exporter
    restart: unless-stopped
    command:
      - "--path.procfs=/host/proc"
      - "--path.sysfs=/host/sys"
      - "--path.rootfs=/host/root"
      - "--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/host/root:ro
    networks:
      - monitoring

  # Container metrics exporter
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.51.0
    container_name: cadvisor
    restart: unless-stopped
    privileged: true
    devices:
      - /dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    networks:
      - monitoring

  # Dashboard visualization
  grafana:
    image: grafana/grafana:11.3.0
    container_name: grafana
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
      - GF_SERVER_ROOT_URL=https://monitor.gntech.dev
      - GF_AUTH_ANONYMOUS_ENABLED=false
    volumes:
      - ./grafana/datasources:/etc/grafana/provisioning/datasources:ro
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - grafana_data:/var/lib/grafana
    depends_on:
      prometheus:
        condition: service_started
      loki:
        condition: service_started
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`monitor.gntech.dev`)"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"
    networks:
      - monitoring

  # Alerting
  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    restart: unless-stopped
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
      - "--storage.path=/alertmanager"
    volumes:
      - ./alertmanager:/etc/alertmanager:ro
      - alertmanager_data:/alertmanager
    networks:
      - monitoring

volumes:
  prometheus_data:
  loki_data:
  grafana_data:
  alertmanager_data:

networks:
  monitoring:
    name: monitoring
    external: false
```

Create a `.env` file for the Grafana admin password:

```bash
echo 'GRAFANA_PASSWORD=changeme-strong-password' > /opt/monitoring/.env
```

---

## Step 2: Prometheus Configuration

**`/opt/monitoring/prometheus/prometheus.yml`:**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    host: srv1

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node"
    static_configs:
      - targets: ["node-exporter:9100"]

  - job_name: "cadvisor"
    static_configs:
      - targets: ["cadvisor:8080"]

  - job_name: "alloy"
    static_configs:
      - targets: ["alloy:12345"]

rule_files:
  - "rules/*.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

**Alert rules — `/opt/monitoring/prometheus/rules/alerts.yml`:**

```yaml
groups:
  - name: homelab
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        annotations:
          summary: "CPU usage above 80% for 5 minutes"
          description: "Instance {{ $labels.instance }} — {{ $value | humanizePercentage }}"

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 85
        for: 5m
        annotations:
          summary: "Memory usage above 85%"
          description: "Instance {{ $labels.instance }} — {{ $value | humanizePercentage }}"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100 < 10
        for: 2m
        annotations:
          summary: "Disk space below 10%"
          description: "Instance {{ $labels.instance }} mount {{ $labels.mountpoint }} — {{ $value | humanizePercentage }} available"

      - alert: ContainerDown
        expr: time() - container_last_seen{name!=""} > 60
        for: 1m
        annotations:
          summary: "Container {{ $labels.name }} unreachable"
          description: "Container {{ $labels.name }} last seen {{ $value | humanizeDuration }} ago"

      - alert: HighDiskIO
        expr: rate(node_disk_io_time_seconds_total[5m]) * 100 > 70
        for: 5m
        annotations:
          summary: "Disk I/O above 70%"
          description: "Device {{ $labels.device }} on {{ $labels.instance }}"
```

Create the rules directory:

```bash
mkdir -p /opt/monitoring/prometheus/rules
```

---

## Step 3: Loki Configuration

**`/opt/monitoring/loki/loki-config.yml`:**

```yaml
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
      replication_factor: 1
  chunk_idle_period: 15m
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
  filesystem:
    directory: /loki/chunks

compactor:
  working_directory: /loki/compactor

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h

ruler:
  alertmanager_url: http://alertmanager:9093

table_manager:
  retention_deletes_enabled: true
  retention_period: 30d
```

For a homelab with a single host, this minimal config is enough. Loki
stores chunks on the filesystem and retains 30 days of logs. If you
scale up, switch to object storage (MinIO or S3).

---

## Step 4: Grafana Alloy Configuration

Alloy replaces Promtail as Grafana's log collector. It uses a
River-based configuration file to discover Docker containers and
forward their logs to Loki.

**`/opt/monitoring/alloy/config.alloy`:**

```river
// Log collection from Docker containers
local.file_match "docker_containers" {
  path_targets = [{"__path__" = "/var/lib/docker/containers/*/*-json.log"}]
}

loki.source.file "docker" {
  targets    = local.file_match.docker_containers.targets
  forward_to = [loki.process.filter_logs.receiver]
  tail_from_end = false
}

// Parse and enrich log lines
loki.process "filter_logs" {
  forward_to = [loki.write.loki.receiver]

  stage.json {
    expressions = {
      log = "",
      stream = "stream",
      time = "time",
      attrs = "",
    }
  }

  stage.labels {
    values = {
      stream = "",
    }
  }

  // Add container_name label from the log file path
  stage.static_labels {
    values = {
      job = "docker",
    }
  }

  // Drop health check noise
  stage.drop {
    source = "log"
    value  = ".*GET /healthz.*"
  }

  stage.drop {
    source = "log"
    value  = ".*GET /readyz.*"
  }
}

// System logs
loki.source.file "system" {
  targets = [
    {__path__ = "/var/log/syslog"},
    {__path__ = "/var/log/auth.log"},
    {__path__ = "/var/log/kern.log"},
  ]
  forward_to = [loki.write.loki.receiver]
  tail_from_end = false
}

// Forward all logs to Loki
loki.write "loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}

// Alloy self-metrics
prometheus.scrape "alloy_self" {
  http_client {
    follow_redirects = false
  }
  forward_to = [prometheus.remote_write.alloy.receiver]
  job_name   = "alloy"
  targets    = [{"__address__" = "127.0.0.1:12345"}]
}

prometheus.remote_write "alloy" {
  endpoint {
    url = "http://prometheus:9090/api/v1/write"
  }
}
```

This config discovers all running Docker containers by tailing their
JSON log files from `/var/lib/docker/containers/`. It also captures
system logs and drops health check noise so your dashboards stay clean.

---

## Step 5: Grafana — Provisioned Datasources and Dashboards

Provisioning means Grafana starts with datasources and dashboards
already configured. No clicking through the UI.

**`/opt/monitoring/grafana/datasources/datasources.yml`:**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false

  - name: Alloy
    type: prometheus
    access: proxy
    url: http://alloy:12345
    editable: false
```

**`/opt/monitoring/grafana/dashboards/dashboards.yml`:**

```yaml
apiVersion: 1

providers:
  - name: "default"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: true
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

Grafana ships with built-in dashboards for Prometheus data. The Node
Exporter Full dashboard (ID 1860) and Docker Monitoring (ID 193) are
popular community dashboards to import after first login.

---

## Step 6: Alertmanager with Telegram Notifications

**`/opt/monitoring/alertmanager/alertmanager.yml`:**

```yaml
route:
  receiver: "telegram"
  repeat_interval: 4h
  group_by: ["alertname", "instance"]
  group_wait: 30s
  group_interval: 5m

receivers:
  - name: "telegram"
    telegram_configs:
      - bot_token: "${TELEGRAM_BOT_TOKEN}"
        chat_id: ${TELEGRAM_CHAT_ID}
        parse_mode: "HTML"
        message: |
          <b>{{ .GroupLabels.alertname }}</b>
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          Instance: {{ .Labels.instance }}
          Value: {{ .Annotations.description }}
          Severity: {{ .Labels.severity }}
          {{ end }}

  - name: "null"
    # Used to silence specific alerts by routing them here

inhibit_rules:
  - source_matchers:
      - severity = "critical"
    target_matchers:
      - severity = "warning"
    equal: ["alertname", "instance"]
```

For Telegram notifications, you need a bot token and chat ID:

```bash
# Create the bot with @BotFather on Telegram, then:
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# Alertmanager reads environment variables when you use ${VAR} syntax
# Add them to your .env or docker-compose environment
```

Add the environment variables to the Alertmanager service in
`docker-compose.yml`:

```yaml
services:
  alertmanager:
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
```

---

## Step 7: Deploy the Stack

```bash
cd /opt/monitoring

# Create directories that don't exist yet
mkdir -p prometheus/rules grafana/{datasources,dashboards} alloy loki alertmanager

# Start everything
docker compose up -d

# Check all services are running
docker compose ps

# Watch the logs
docker compose logs -f

# Verify Prometheus targets are up
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

Expected output from the target check:

```json
{"job":"prometheus","health":"up"}
{"job":"node","health":"up"}
{"job":"cadvisor","health":"up"}
{"job":"alloy","health":"up"}
```

---

## Step 8: Verify Logs Are Flowing

Query Loki directly to confirm Alloy is forwarding logs:

```bash
# Check available streams
curl -s "http://localhost:3100/loki/api/v1/labels" | jq

# Query recent logs
curl -s -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job="docker"}' \
  --data-urlencode 'limit=5' \
  --data-urlencode 'direction=backward' | jq '.data.result[].values[][1]'
```

If you see container log output, Alloy and Loki are working.

---

## Step 9: Grafana — Importing Dashboards

Open Grafana at `http://your-host:3000` (or your Traefik domain).
Log in with `admin` and the password from your `.env` file.

**Import pre-built dashboards:**

1. Click the sidebar → **Dashboards** → **New** → **Import**
2. Enter these dashboard IDs:
   - **1860** — Node Exporter Full (comprehensive host metrics)
   - **193** — Docker Monitoring (container CPU, memory, network, disk)
   - **13105** — Loki Logs (log browsing interface)
3. Select the Prometheus or Loki datasource and click Import

**Explore logs side by side with metrics:**

In any dashboard panel, click the dropdown next to a time series and
select **"View in Explore"**. Switch between Prometheus queries
(for metrics) and Loki queries (for logs), or split the view to see
both at once. When a container OOMs, you see the CPU spike in the
metrics panel and the actual OOM killer message in the logs panel in
the same view.

---

## Step 10: What to Monitor — Recommended Dashboard Setup

After the stack is running, configure your Grafana home dashboard to
answer these questions at a glance:

**Host Health (top row):**
- CPU usage gauge (target: < 70%)
- Memory usage gauge (target: < 80%)
- Disk usage per mount point (target: < 85%)
- Uptime counter
- System load 1/5/15

**Container Overview (middle row):**
- Container count (running / stopped / total)
- Top 5 containers by CPU
- Top 5 containers by memory
- Docker container state matrix (color-coded by status)

**Log Activity (bottom row):**
- Log volume per container (bar chart)
- Error log rate (count per minute)
- Recent error logs table

**Alert Status:**
- Active alert count
- Alert history timeline

---

## Maintenance

**Reload Prometheus config without restart:**

```bash
curl -X POST http://localhost:9090/-/reload
```

**Check Prometheus rule evaluation:**

```bash
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | {name: .name, state: .state}'
```

**Restart Alloy after config changes:**

```bash
docker compose restart alloy
```

**Clean old Loki data to reclaim disk space:**

```bash
# The retention period in loki-config.yml handles this automatically
# Manual cleanup if needed:
docker compose exec loki rm -rf /loki/chunks/!(index*)
docker compose restart loki
```

---

## Scaling Beyond One Host

The stack above monitors a single Docker host. To add more hosts:

1. Run Node Exporter and Alloy on each additional host
2. Add the new hosts to Prometheus's `scrape_configs` as static targets
   or use file-based service discovery
3. Point each Alloy instance to the central Loki
4. Create host-specific folders in Grafana to organize dashboards

For a homelab with 3-5 hosts, this single-instance approach works
fine. Prometheus handles millions of time series per host, and Loki
compresses log storage efficiently. When you exceed that, look at
Thanos for Prometheus horizontal scaling.

---

## Summary

This monitoring stack gives you complete observability of your homelab
in about 30 minutes. You get:

- **Metrics** from every host and container, stored and queryable in
  Prometheus
- **Logs** from every Docker container, aggregated in Loki and
  browseable from Grafana
- **Dashboards** that correlate metrics and logs so you can trace
  incidents from symptom to root cause
- **Alerts** that notify you via Telegram when CPU spikes, disk fills,
  or containers stop

The stack is entirely self-contained in a single `docker-compose.yml`.
Add it to any server that has Docker installed — your Proxmox host, a
Raspberry Pi, or a dedicated monitoring box. Having a monitoring stack
turns blind debugging into informed troubleshooting, and it catches
problems before they become outages.

The docker-compose.yml, configurations, and alert rules from this
guide are ready to deploy. `docker compose up -d` and within minutes
you'll see your homelab's metrics on a Grafana dashboard.
