---
title: "Prometheus Grafana Monitoring Stack — Docker Compose Setup"
description: "Deploy a complete homelab monitoring stack with Prometheus, Grafana, Node Exporter, and cAdvisor using Docker Compose — with preconfigured dashboards and Alertmanager integration."
date: 2026-05-21T14:30:00-04:00
tags:
  - monitoring
  - prometheus
  - grafana
  - docker
  - homelab
  - containers
keywords:
  - Prometheus Grafana Docker Compose homelab setup
  - homelab monitoring stack installation
  - Node Exporter cAdvisor container monitoring
  - Prometheus alertmanager configuration rules
  - Grafana preconfigured dashboard homelab
  - Docker service monitoring alerts notification
  - homelab observability Prometheus Grafana
summary: "Deploy a production-grade Prometheus Grafana monitoring stack with Docker Compose — including Node Exporter, cAdvisor, and Alertmanager for complete homelab observability."
canonical: "https://blog.gntech.me/posts/2026-05-21-prometheus-grafana-monitoring-stack/"
---

If you run a homelab with multiple Docker services, VMs, and
physical hosts, you have no real visibility into what is
happening. A container goes OOM, a disk fills up, or a service
stops responding — and you only discover it when something
breaks.

A Prometheus Grafana monitoring stack built on Docker Compose
gives you metric collection, alerting, and visualization for
your entire infrastructure. This guide walks through deploying
Prometheus for time-series storage, Grafana for dashboards,
Node Exporter for host metrics, cAdvisor for container metrics,
and Alertmanager for push notifications — all behind a single
Traefik reverse proxy.

---

## Architecture Overview

The stack consists of five components:

| Component | Role | Exposes |
|-----------|------|---------|
| **Prometheus** | Time-series database and metric scraper | Port 9090 |
| **Grafana** | Dashboard and visualization layer | Port 3000 |
| **Node Exporter** | Host-level metrics (CPU, RAM, disk, network) | Port 9100 |
| **cAdvisor** | Container-level metrics (per-container resource usage) | Port 8080 |
| **Alertmanager** | Handles and routes alerts from Prometheus | Port 9093 |

Prometheus scrapes Node Exporter and cAdvisor at configurable
intervals. Grafana queries Prometheus as a data source.
Alertmanager receives firing alerts and sends notifications via
email, Telegram, or webhook.

---

## Docker Compose Configuration

Create a project directory and `compose.yaml`:

```yaml
# /opt/monitoring/compose.yaml
services:
  prometheus:
    image: prom/prometheus:v2.55.1
    container_name: prometheus
    hostname: prometheus
    restart: unless-stopped
    command:
      - '--config.file=/etc/prometheus/prometheus.yaml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
    volumes:
      - ./prometheus.yaml:/etc/prometheus/prometheus.yaml:ro
      - ./alert-rules.yaml:/etc/prometheus/alert-rules.yaml:ro
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:11.4.0
    container_name: grafana
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
      - GF_SERVER_ROOT_URL=https://grafana.gntech.home
      - GF_AUTH_ANONYMOUS_ENABLED=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/datasources:/etc/grafana/provisioning/datasources:ro
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./grafana/dashboards-json:/var/lib/grafana/dashboards:ro
    ports:
      - "127.0.0.1:3000:3000"
    networks:
      - monitoring
    depends_on:
      - prometheus

  node_exporter:
    image: prom/node-exporter:v1.8.2
    container_name: node_exporter
    restart: unless-stopped
    command:
      - '--path.rootfs=/host'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    pid: host
    volumes:
      - /:/host:ro,rslave
    ports:
      - "127.0.0.1:9100:9100"
    networks:
      - monitoring

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.1
    container_name: cadvisor
    restart: unless-stopped
    privileged: true
    devices:
      - /dev/kmsg:/dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "127.0.0.1:8080:8080"
    networks:
      - monitoring

  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    restart: unless-stopped
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yaml'
      - '--storage.path=/alertmanager'
    volumes:
      - ./alertmanager.yaml:/etc/alertmanager/alertmanager.yaml:ro
      - alertmanager_data:/alertmanager
    ports:
      - "127.0.0.1:9093:9093"
    networks:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:
  alertmanager_data:

networks:
  monitoring:
    name: monitoring
    external: false
```

> **Note:** All ports are bound to `127.0.0.1` so they are not
> directly exposed. Access goes through a reverse proxy (Traefik
> or Nginx) with authentication. For a single-host setup, you
> can omit the `ports` sections and use the internal Docker
> network exclusively.

---

## Prometheus Configuration

Create `prometheus.yaml` with scrape targets and alerting rules:

```yaml
# /opt/monitoring/prometheus.yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: 'homelab'

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

rule_files:
  - 'alert-rules.yaml'

scrape_configs:
  # Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Node Exporter on this host
  - job_name: 'node'
    static_configs:
      - targets: ['node_exporter:9100']

  # cAdvisor for container metrics
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']

  # Additional Node Exporters on other hosts
  # - job_name: 'node-proxmox'
  #   static_configs:
  #     - targets:
  #       - '10.0.20.30:9100'   # SRV1
  #       - '10.0.20.31:9100'   # SRV2
```

For Node Exporter on remote hosts (Proxmox nodes, other VMs),
install the agent:

```bash
# On each remote host
wget https://github.com/prometheus/node_exporter/releases/download/v1.8.2/node_exporter-1.8.2.linux-amd64.tar.gz
tar xzf node_exporter-1.8.2.linux-amd64.tar.gz
sudo install node_exporter-1.8.2.linux-amd64/node_exporter /usr/local/bin/

# Create systemd service
sudo tee /etc/systemd/system/node_exporter.service << 'SVC'
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/local/bin/node_exporter \
  --path.rootfs=/host \
  --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)
Restart=always

[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

Uncomment the remote targets in `prometheus.yaml` after
installing Node Exporter on each remote host.

---

## Alerting Rules

Create `alert-rules.yaml` with practical homelab alerts:

```yaml
# /opt/monitoring/alert-rules.yaml
groups:
  - name: homelab_node
    interval: 30s
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is {{ $value }}% for 5 minutes."

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is {{ $value }}%."

      - alert: DiskSpaceRunningOut
        expr: (node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100 < 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Disk space low on {{ $labels.instance }}"
          description: "Only {{ $value }}% available on {{ $labels.mountpoint }}."

      - alert: DiskSpaceWarning
        expr: (node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) * 100 < 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk space warning on {{ $labels.instance }}"
          description: "Only {{ $value }}% available on {{ $labels.mountpoint }}."

      - alert: NodeDown
        expr: up{job="node"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Node {{ $labels.instance }} is down"
          description: "Node {{ $labels.instance }} has been unreachable for 1 minute."

  - name: homelab_container
    interval: 30s
    rules:
      - alert: ContainerHighCPU
        expr: rate(container_cpu_usage_seconds_total{name!=""}[2m]) * 100 > 200
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High CPU in container {{ $labels.name }}"
          description: "Container {{ $labels.name }} is using {{ $value }}% CPU."

      - alert: ContainerHighMemory
        expr: container_memory_usage_bytes{name!=""} / container_spec_memory_limit_bytes{name!=""} * 100 > 90
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High memory in container {{ $labels.name }}"
          description: "Container {{ $labels.name }} at {{ $value }}% of memory limit."

      - alert: ContainerRestarting
        expr: changes(container_last_seen{name!=""}[15m]) > 3
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.name }} restarting"
          description: "Container {{ $labels.name }} restarted {{ $value }} times in 15 minutes."

      - alert: ContainerOOMKilled
        expr: container_oom_events_total{name!=""} > 0
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.name }} OOM killed"
          description: "Container {{ $labels.name }} was killed by OOM."
```

These rules cover the most common homelab failure scenarios: a
node going offline, disk filling up, a container in a restart
loop, or a process hitting its memory limit.

---

## Alertmanager Notification Configuration

Create `alertmanager.yaml` to route alerts to Telegram:

```yaml
# /opt/monitoring/alertmanager.yaml
route:
  receiver: 'telegram'
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'telegram'
      repeat_interval: 1h

receivers:
  - name: 'telegram'
    telegram_configs:
      - bot_token: ${TELEGRAM_BOT_TOKEN}
        chat_id: ${TELEGRAM_CHAT_ID}
        message: |-
          {{ range .Alerts }}
          🔴 *{{ .Labels.alertname }}*
          *Instance:* {{ .Labels.instance }}
          *Severity:* {{ .Labels.severity }}
          *Summary:* {{ .Annotations.summary }}
          *Description:* {{ .Annotations.description }}
          {{ end }}
        parse_mode: 'MarkdownV2'
        send_resolved: true
```

Set the environment variables in a `.env` file:

```bash
# /opt/monitoring/.env
GRAFANA_PASSWORD=your-strong-password
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
```

For email alerts, switch to:

```yaml
  - name: 'email'
    email_configs:
      - to: 'admin@gntech.dev'
        from: 'alertmanager@gntech.dev'
        smarthost: 'mail.gntech.dev:587'
        auth_username: 'alertmanager@gntech.dev'
        auth_password: ${SMTP_PASSWORD}
```

---

## Grafana Provisioning — Automatic Dashboards

Avoid clicking around in the Grafana UI. Use provisioning files
so the dashboards survive container recreations.

### Datasource Provisioning

```yaml
# /opt/monitoring/grafana/datasources/datasources.yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

### Dashboard Provisioning

```yaml
# /opt/monitoring/grafana/dashboards/dashboards.yaml
apiVersion: 1

providers:
  - name: 'Homelab'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: true
    editable: false
    options:
      path: /var/lib/grafana/dashboards
```

### Import Community Dashboards

Download the most popular dashboards for Node Exporter and
cAdvisor:

```bash
# /opt/monitoring/grafana/dashboards-json/
# Node Exporter Full (ID 1860)
curl -sL https://grafana.com/api/dashboards/1860/revisions/latest/download \
  -o grafana/dashboards-json/node-exporter-full.json

# Docker Monitoring (ID 17906)
curl -sL https://grafana.com/api/dashboards/17906/revisions/latest/download \
  -o grafana/dashboards-json/docker-monitoring.json
```

Grafana loads these on startup. No manual importing needed.

---

## Reverse Proxy with Traefik

If you use Traefik (covered in earlier posts), add labels to
expose Grafana and Prometheus securely:

```yaml
  grafana:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`monitor.gntech.home`)"
      - "traefik.http.routers.grafana.entrypoints=https"
      - "traefik.http.routers.grafana.tls=true"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"

  prometheus:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.prometheus.rule=Host(`prometheus.gntech.home`)"
      - "traefik.http.routers.prometheus.entrypoints=https"
      - "traefik.http.routers.prometheus.tls=true"
      - "traefik.http.services.prometheus.loadbalancer.server.port=9090"
      - "traefik.http.routers.prometheus.middlewares=auth@file"
```

> **Security:** Always put Prometheus behind authentication. The
> Prometheus UI has no auth by default. Use Traefik forward auth
> (Authentik or basic auth middleware) or add Prometheus's
> `--web.auth.file` flag with a bcrypt-hashed password file.

---

## Deployment

Start the stack:

```bash
cd /opt/monitoring
docker compose up -d
```

Verify all services are running:

```bash
docker compose ps

# Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].labels.job'

# Query a metric
curl -s 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result[] | {job: .metric.job, instance: .metric.instance, up: .value[1]}'

# Test an alert rule
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | {name: .name, state: .state}'
```

Access Grafana at `http://localhost:3000` (or your Traefik URL).
Login with `admin` and your configured `GRAFANA_PASSWORD`. The
Prometheus datasource and dashboards are preconfigured.

---

## Adding Monitoring to a Multi-Node Homelab

For a Proxmox cluster with multiple hosts, install Node Exporter
on every node and point Prometheus at each:

```yaml
scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets:
        - 'node_exporter:9100'        # Docker host
        - '10.0.20.30:9100'           # SRV1
        - '10.0.20.31:9100'           # SRV2
        - '10.0.20.32:9100'           # SRV3 (backup node)
```

For Proxmox-specific metrics (which Node Exporter does not
cover), install the **Proxmox VE Exporter**:

```bash
docker run -d \
  --name=pve-exporter \
  --restart=unless-stopped \
  -e PVE_USER=monitoring@pve \
  -e PVE_PASSWORD=secret \
  -e PVE_HOST=10.0.20.30 \
  -p 127.0.0.1:9221:9221 \
  prompve/prometheus-pve-exporter:latest
```

Add it as a scrape target in `prometheus.yaml`:

```yaml
  - job_name: 'proxmox'
    static_configs:
      - targets: ['pve-exporter:9221']
```

---

## Disk Usage Considerations

Prometheus can consume significant disk depending on retention
and scrape volume. Estimate:

- **15s scrape interval** × ~500 time series = ~2 GB/month
- **15s scrape interval** × ~2000 time series (multi-node) = ~8 GB/month
- **30d retention** with multi-node = ~8-10 GB total

Allocate a dedicated Docker volume on fast storage. For ZFS
users, set the mountpoint on a dataset with `recordsize=16K`
(optimized for Prometheus write patterns):

```bash
zfs create -o recordsize=16K -o compression=lz4 tank/monitoring
```

Then mount it via volume bind:

```yaml
volumes:
  - /tank/monitoring/prometheus:/prometheus
```

---

## Maintenance and Updates

### Backing Up Grafana

Grafana stores dashboards, datasources, and users in SQLite.
Back up the database and provisioning files:

```bash
docker exec grafana sqlite3 /var/lib/grafana/grafana.db ".backup /tmp/grafana-backup.db"
docker cp grafana:/tmp/grafana-backup.db ./backups/
```

Or use provisioning (recommended) — export dashboards as JSON
and store them in your git repo.

### Updating Images

```bash
docker compose pull
docker compose up -d
docker image prune -f
```

### Adding a New Host

1. Install Node Exporter on the host (systemd service above).
2. Open port 9100 in the host firewall.
3. Add the IP to `prometheus.yaml` `scrape_configs`.
4. Reload Prometheus: `curl -X POST http://localhost:9090/-/reload`.

---

## Summary

This Prometheus Grafana monitoring stack gives you complete
observability into your homelab with minimal overhead. Five
Docker containers provide:

- **Host metrics** — CPU, RAM, disk, network from every node
- **Container metrics** — per-container resource usage and
  health from cAdvisor
- **Alerting** — Telegram notifications when things go wrong
- **Preconfigured dashboards** — visual monitoring on day one
- **Multi-node support** — scrape any host running Node Exporter

The stack runs on any Docker host, uses minimal resources
(~500 MB RAM total for the full stack), and alerts you before
problems become outages. Deploy it today and you will catch
your next disk-full or container-OOM before it takes down your
services.
