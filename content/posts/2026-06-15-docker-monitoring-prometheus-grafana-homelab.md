---
title: "Docker Monitoring with Prometheus and Grafana in Homelab"
description: "Deploy a full Docker monitoring stack with Prometheus, Grafana, cAdvisor, and node_exporter in your homelab. Real docker-compose configs, dashboards, and alerting."
date: 2026-06-15T14:00:00-04:00
tags:
  - docker
  - monitoring
  - prometheus
  - grafana
  - homelab
keywords:
  - Docker container monitoring Prometheus Grafana homelab setup guide
  - cAdvisor Docker container metrics Prometheus scraping homelab
  - Prometheus node_exporter Docker host metrics configuration
  - Grafana Docker monitoring dashboard Prometheus datasource
  - Docker Compose Prometheus stack cAdvisor node_exporter deployment
  - Prometheus Alertmanager Docker container alert configuration
  - Self-hosted infrastructure monitoring Docker Compose homelab
summary: "Deploy Prometheus, Grafana, cAdvisor, and node_exporter via Docker Compose for full homelab monitoring. Real configs for metrics collection, dashboards, and alerting."
canonical: "https://blog.gntech.me/posts/docker-monitoring-prometheus-grafana-homelab/"
---

When your homelab has a dozen containers across multiple Compose stacks, `docker stats` stops cutting it. You need persistent metrics, historical data, and visual dashboards to understand what your containers are actually doing.

This guide deploys a complete monitoring stack using Docker Compose:

- **Prometheus** — scrapes and stores time-series metrics
- **cAdvisor** — exports per-container CPU, memory, network, and disk metrics
- **node_exporter** — exports host-level metrics (CPU, memory, disk, load, network)
- **Grafana** — dashboards and alerting with Prometheus as the data source
- **Alertmanager** — deduplicates and routes alerts to email, Telegram, or Slack

Everything runs as Docker containers on a single host. No agent installation on the host beyond a single bind mount. All config files are included. Deploy in under 30 minutes.

## Why Monitor Docker Containers in Your Homelab?

Running `docker stats` gives you a live snapshot of CPU and memory per container. That's useful for debugging right now, but it doesn't help with:

- **Trend analysis**: was that memory spike yesterday a one-off or a leak?
- **Resource planning**: which container is eating 80% of your disk I/O?
- **Anomaly detection**: did a container restart while you were sleeping?
- **Historical comparison**: how did the last deployment affect performance?

A Prometheus-based stack solves all of these. Prometheus scrapes metrics every 15 seconds by default, stores them with configurable retention, and exposes everything via PromQL for querying and alerting.

## Architecture Overview — Prometheus Stack Components

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│              │     │              │     │              │
│   cAdvisor   │────▶│  Prometheus  │◀────│ Node Exporter│
│  (container  │     │  (metrics    │     │   (host      │
│   metrics)   │     │   storage)   │     │   metrics)   │
│              │     │              │     │              │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐     ┌──────────────┐
                     │              │     │              │
                     │   Grafana    │────▶│ Alertmanager │
                     │ (dashboards) │     │ (alert       │
                     │              │     │  routing)    │
                     └──────────────┘     └──────────────┘
```

Prometheus is the central time-series database. It scrapes HTTP endpoints that expose metrics in Prometheus format:

- **cAdvisor** (`:8080/metrics`) — per-container CPU, memory, network RX/TX, filesystem, and task stats
- **node_exporter** (`:9100/metrics`) — host CPU, memory, disk space, disk I/O, network, load average, and more
- **Prometheus itself** (`:9090/metrics`) — internal metrics about the scrape targets and storage

Grafana connects to Prometheus as a data source and provides dashboards. Alertmanager handles alert deduplication, grouping, and notification routing.

## Deploying the Monitoring Stack with Docker Compose

Create a project directory and a `.env` file:

```bash
mkdir -p ~/docker/monitoring && cd ~/docker/monitoring
```

`.env` contents:

```env
# Grafana
GF_ADMIN_PASSWORD=changeme_secure_password

# Prometheus data retention
PROMETHEUS_RETENTION_TIME=30d
PROMETHEUS_RETENTION_SIZE=10GB

# Alertmanager email (optional)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASS=your_smtp_password
ALERT_EMAIL=you@example.com
```

### docker-compose.yml

```yaml
x-restart: &restart
  restart: unless-stopped

x-logging: &logging
  logging:
    driver: "local"
    options:
      max-size: "10m"
      max-file: "3"

services:
  prometheus:
    <<: *restart
    <<: *logging
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=${PROMETHEUS_RETENTION_TIME}"
      - "--storage.tsdb.retention.size=${PROMETHEUS_RETENTION_SIZE}"
      - "--web.console.libraries=/etc/prometheus/console_libraries"
      - "--web.console.templates=/etc/prometheus/consoles"
      - "--web.enable-lifecycle"
    networks:
      - monitoring

  cadvisor:
    <<: *restart
    <<: *logging
    image: gcr.io/cadvisor/cadvisor:latest
    container_name: cadvisor
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk:/dev/disk:ro
    privileged: false
    devices:
      - /dev/kmsg
    networks:
      - monitoring

  node-exporter:
    <<: *restart
    <<: *logging
    image: prom/node-exporter:latest
    container_name: node-exporter
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/host/root:ro
    command:
      - "--path.procfs=/host/proc"
      - "--path.sysfs=/host/sys"
      - "--path.rootfs=/host/root"
      - "--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)"
    networks:
      - monitoring

  grafana:
    <<: *restart
    <<: *logging
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GF_ADMIN_PASSWORD}"
      GF_INSTALL_PLUGINS: "grafana-piechart-panel"
    networks:
      - monitoring

  alertmanager:
    <<: *restart
    <<: *logging
    image: prom/alertmanager:latest
    container_name: alertmanager
    ports:
      - "9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager-data:/alertmanager
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
      - "--config.expand-env=true"
      - "--storage.path=/alertmanager"
    networks:
      - monitoring

volumes:
  prometheus-data:
  grafana-data:
  alertmanager-data:

networks:
  monitoring:
    driver: bridge
```

Key points about this Compose file:

- **cAdvisor** mounts the host filesystem in several locations to read container and cgroup metrics. The `/dev/kmsg` device is needed for kernel log access on newer kernels.
- **node_exporter** uses `--path.procfs`, `--path.sysfs`, and `--path.rootfs` to read host metrics from bind-mounted host paths, avoiding running as host-networked.
- **Grafana** auto-provisions data sources and dashboards via the `provisioning` directory.
- **Alertmanager** persists silences and notification state to a Docker volume.

## Setting Up Prometheus Configuration

Create `prometheus.yml` in the project directory:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    host: "srv1"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

rule_files:
  - "alerts.yml"

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "cadvisor"
    scrape_interval: 30s
    static_configs:
      - targets: ["cadvisor:8080"]
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        target_label: container
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: compose_service

  - job_name: "node"
    scrape_interval: 30s
    static_configs:
      - targets: ["node-exporter:9100"]

  # Add host-specific jobs here
  # - job_name: "mikrotik"
  #   scrape_interval: 60s
  #   static_configs:
  #     - targets: ["10.0.20.1:9116"]
```

The `scrape_interval` of 15 seconds is fine for a homelab. If you're running on constrained hardware, bump it to 30s for cAdvisor and node_exporter jobs — the data resolution loss is negligible for trend analysis.

### Prometheus Alert Rules

Create `alerts.yml`:

```yaml
groups:
  - name: homelab
    rules:
      - alert: ContainerDown
        expr: time() - container_last_seen{container!=""} > 60
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.name }} is down"
          description: "Container {{ $labels.name }} has not been seen for over 1 minute."

      - alert: HighContainerCPU
        expr: sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (name) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.name }} high CPU"
          description: "Container {{ $labels.name }} CPU usage above 80% for 5 minutes."

      - alert: HighContainerMemory
        expr: container_memory_usage_bytes{container!=""} / container_spec_memory_limit_bytes{container!=""} > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.name }} memory high"
          description: "Container {{ $labels.name }} memory usage at {{ $value | humanizePercentage }}"

      - alert: HostDiskFull
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Host disk almost full"
          description: "Root filesystem has less than 10% free space."

      - alert: HostMemoryLow
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Host memory critically low"
          description: "Available memory is below 10% of total."
```

## Grafana Data Source and Dashboard Provisioning

Grafana provisioning allows you to pre-configure data sources and dashboards from YAML files — no manual clicking after deployment.

Create the provisioning directory structure:

```bash
mkdir -p grafana/provisioning/datasources
mkdir -p grafana/provisioning/dashboards
mkdir -p grafana/dashboards
```

### datasources/prometheus.yml

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

### dashboards/dashboard-provider.yml

```yaml
apiVersion: 1

providers:
  - name: "Homelab Dashboards"
    orgId: 1
    folder: "Homelab"
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

### Import Community Dashboards

Grafana community dashboards provide immediate visibility without building from scratch. Download them and place them in `grafana/dashboards/`:

```bash
# Node Exporter Full (ID 1860)
curl -sL "https://grafana.com/api/dashboards/1860/revisions/37/download" \
  -o grafana/dashboards/node_exporter_full.json

# Docker Monitoring (ID 179)
curl -sL "https://grafana.com/api/dashboards/179/revisions/24/download" \
  -o grafana/dashboards/docker_monitoring.json

# Prometheus 2.0 Overview (ID 3662)
curl -sL "https://grafana.com/api/dashboards/3662/revisions/7/download" \
  -o grafana/dashboards/prometheus_overview.json
```

These JSON files are the complete dashboard definitions. Grafana will import them automatically on startup and keep them in sync via the provisioning provider.

## Configuring Alertmanager for Email and Telegram

Create `alertmanager.yml`:

```yaml
global:
  smtp_smarthost: "${SMTP_HOST}:${SMTP_PORT}"
  smtp_from: "Alertmanager <${SMTP_USER}>"
  smtp_auth_username: "${SMTP_USER}"
  smtp_auth_password: "${SMTP_PASS}"
  smtp_require_tls: true
  resolve_timeout: 5m

route:
  group_by: ["alertname", "severity"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: "default"
  routes:
    - match:
        severity: critical
      receiver: "critical"
      repeat_interval: 1h

receivers:
  - name: "default"
    email_configs:
      - to: "${ALERT_EMAIL}"
        send_resolved: true

  - name: "critical"
    email_configs:
      - to: "${ALERT_EMAIL}"
        send_resolved: true
    webhook_configs:
      - url: "http://your-telegram-bot:8080/alert"
        send_resolved: true
```

For Telegram notifications, deploy a simple webhook bridge container:

```yaml
services:
  alertmanager-bridge:
    image: webhippie/alertmanager-bot:latest
    container_name: alertmanager-bot
    environment:
      ALERTMANAGER_URL: "http://alertmanager:9093"
      BOT_TOKEN: "${TELEGRAM_BOT_TOKEN}"
      BOT_WEBHOOK_URL: "https://your-domain.com/alertmanager-bot"
      BOT_STORE: "/data/bot"
    volumes:
      - bot-data:/data/bot
    networks:
      - monitoring
```

## Verify the Stack — Testing End to End

Deploy everything:

```bash
cd ~/docker/monitoring
docker compose up -d
```

Wait 30 seconds for first scrape cycle, then check each component:

### Prometheus Targets

```bash
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool
```

Or open `http://your-host:9090/targets` in a browser. All three targets (`prometheus`, `cadvisor`, `node`) should show state `UP`.

### Query PromQL

```bash
# Container CPU usage (total across all cores, last 5m)
curl -s 'http://localhost:9090/api/v1/query?query=rate(container_cpu_usage_seconds_total[5m])' | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data['data']['result']:
    name = r['metric'].get('name', 'unknown')
    val = float(r['value'][1])
    print(f'{name}: {val:.3f} cores')
"
```

### Host memory

```bash
curl -s 'http://localhost:9090/api/v1/query?query=node_memory_MemAvailable_bytes' | python3 -c "
import sys, json
data = json.load(sys.stdin)
avail = int(data['data']['result'][0]['value'][1])
print(f'Available memory: {avail / 1024**3:.1f} GB')
"
```

### Grafana

Open `http://your-host:3000` and log in with admin / `${GF_ADMIN_PASSWORD}`. The Home dashboard should show provisioned dashboards under the "Homelab" folder.

### Test Alerts

Stop a container to trigger an alert:

```bash
docker stop cadvisor
```

Alertmanager should fire the `ContainerDown` alert within ~2 minutes (60s of not seeing the container + 1m `for` duration). Check `http://your-host:9093/#/alerts`.

Restart cAdvisor when done:

```bash
docker start cadvisor
```

The alert should auto-resolve within 5 minutes (the `resolve_timeout` in alertmanager.yml).

## Maintenance and Best Practices

### Prometheus Storage Management

Prometheus stores all data in its TSDB. With the config above, data is retained for 30 days or until the volume reaches 10 GB, whichever comes first. Adjust for your hardware:

```yaml
# In docker-compose.yml command section:
--storage.tsdb.retention.time=60d
--storage.tsdb.retention.size=50GB
```

Monitor the TSDB size with a PromQL query in Grafana:

```
prometheus_tsdb_storage_blocks_bytes
```

### Resource Usage of the Monitoring Stack

The stack itself is lightweight:

| Service       | Memory | CPU (idle) |
|---------------|--------|------------|
| Prometheus    | 150-300 MB | ~0.01 core |
| cAdvisor      | 50-80 MB   | ~0.02 core |
| node_exporter | 15-25 MB   | <0.01 core |
| Grafana       | 80-150 MB  | ~0.01 core |
| Alertmanager  | 10-20 MB   | <0.01 core |

Total: ~350-600 MB RAM and negligible CPU at idle. Spikes only during query execution or dashboard loading.

### Securing Grafana Behind Traefik

If you already run Traefik in your homelab, add Traefik labels to the Grafana service:

```yaml
services:
  grafana:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.entrypoints=websecure"
      - "traefik.http.routers.grafana.rule=Host(`grafana.yourlab.com`)"
      - "traefik.http.routers.grafana.tls.certresolver=letsencrypt"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"
    networks:
      - monitoring
      - traefik-public
```

Combine with Authelia for SSO authentication. Remove the published `3000:3000` port when behind Traefik.

### Dashboard Backup

Export Grafana dashboards periodically:

```bash
docker exec grafana grafana-cli admin export-dashboards /tmp/backup
docker cp grafana:/tmp/backup ./dashboards-export-$(date +%Y%m%d).zip
```

For automated backups, schedule a cron job or add a `backup` service to the compose stack that runs `curl` against the Grafana API.

## Extending the Stack — Custom Exporters

Once the base stack is running, adding new data sources is straightforward:

**MikroTik metrics**: Deploy the Prometheus SNMP Exporter with a MikroTik MIB config:
```bash
docker run -d --name snmp-exporter \
  -v $(pwd)/snmp.yml:/etc/snmp_exporter/snmp.yml:ro \
  -p 9116:9116 \
  prom/snmp-exporter:latest
```

Add to `prometheus.yml`:
```yaml
  - job_name: "mikrotik"
    scrape_interval: 60s
    static_configs:
      - targets: ["10.0.20.1:9116"]
```

**Proxmox host metrics**: Enable the Proxmox VE metrics exporter and add to Prometheus scrape config.

**Docker daemon metrics**: Enable Docker's built-in Prometheus endpoint by adding to `/etc/docker/daemon.json` on the host:
```json
{
  "metrics-addr": "0.0.0.0:9323",
  "experimental": true
}
```

Then add a scrape job for `host:9323`.

## Summary: Full Homelab Observability in Under 30 Minutes

This stack gives you persistent metrics, visual dashboards, and alerting for your entire Docker homelab — all self-hosted, all running as containers, all configured declaratively.

Startup sequence:

```bash
mkdir -p ~/docker/monitoring && cd ~/docker/monitoring

# Create all config files (prometheus.yml, alerts.yml, alertmanager.yml, grafana provisioning)
# Then:
docker compose up -d

# Verify
curl -s http://localhost:9090/targets | grep -c '"health":"up"'
# Should output: 3

open http://localhost:3000  # Grafana
```

What you get for the ~600 MB RAM investment:

- Per-container CPU, memory, network, and disk metrics (from cAdvisor)
- Host CPU, memory, disk space, and load metrics (from node_exporter)
- Historical queries via PromQL with configurable retention
- Alerting for container crashes, resource exhaustion, and disk space
- Extensible: add custom exporters for MikroTik, Proxmox, UPS, or any Prometheus-compatible endpoint
- All configuration in one directory, backed up with the rest of your Docker project files

The monitoring stack itself needs monitoring. Add a Uptime Kuma probe for each service endpoint, or configure Prometheus to scrape itself and alert on any target going down. In a homelab, the most important alert is "Prometheus stopped scraping" — because without it, you're flying blind.

```bash
# Quick health check for the whole stack
for svc in prometheus cadvisor node-exporter grafana alertmanager; do
  status=$(docker inspect --format='{{.State.Status}}' $svc 2>/dev/null || echo "missing")
  echo "$svc: $status"
done
```
