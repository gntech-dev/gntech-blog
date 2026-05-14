---
title: "Homelab Monitoring — Prometheus, Grafana, Loki, and Exporters on Docker"
description: "Full observability stack for a Proxmox homelab — Prometheus for metrics, Loki for logs, Grafana for dashboards, with node and Docker exporters. All configs, no theory."
date: 2026-05-09T00:00:00-04:00
tags:
  - monitoring
  - prometheus
  - grafana
  - docker
  - homelab
categories:
  - homelab
  - monitoring
---

Every homelab needs observability. Not because you're running a production
SLA — because you can't fix what you can't see. Running out of disk on the
ZFS pool at 3 AM, a Docker container silently OOM-killed, or the Frigate
NVR eating 100% CPU for hours — these are the things you catch with a
monitoring stack, not by noticing the UI feels sluggish.

This post covers a full Prometheus + Grafana + Loki stack deployed on
Docker in a Proxmox LXC, with metrics from the host, Docker containers,
and system logs collected into one dashboard.

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Host (LXC/VM)                    │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │Prometheus │  │  Loki     │  │  Grafana │               │
│  │ :9090     │  │ :3100     │  │ :3000     │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       │              │              │                      │
│  ┌────▼─────┐  ┌────▼─────┐       │                      │
│  │node_exp  │  │docker_exp│       │                      │
│  │ (host)   │  │ (docker) │       │                      │
│  └──────────┘  └──────────┘       │                      │
│                                   │                      │
│  ┌────────────────────────────────▼────────┐             │
│  │          promtail (log collector)       │             │
│  │  /var/log/*.log → Loki                  │             │
│  └─────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────┘
```

---

## Stack Overview

| Component | Role | Port |
|-----------|------|------|
| **Prometheus** | Time-series metrics database and alert evaluator | 9090 |
| **Grafana** | Visualization, dashboards, alerting UI | 3000 |
| **Loki** | Log aggregation (Prometheus-like, but for logs) | 3100 |
| **promtail** | Log collector, ships container and system logs to Loki | — |
| **node_exporter** | Host metrics (CPU, RAM, disk, network, ZFS) | 9100 |
| **cadvisor** (optional) | Container-level resource metrics | 8080 |

All run as Docker containers via a single Compose file. The only
exception is `node_exporter`, which runs directly on the Proxmox host
(or in a privileged LXC — I'll cover both).

---

## Directory Layout

```
/opt/docker/monitoring/
├── compose.yml
├── .env
├── prometheus/
│   ├── prometheus.yml
│   └── rules/
│       └── alerts.yml
├── grafana/
│   ├── grafana.ini
│   ├── dashboards/      (provisioned JSON)
│   └── datasources/     (provisioned YAML)
├── loki/
│   └── loki-config.yml
└── promtail/
    └── promtail-config.yml
```

---

## 1. Compose File

```yaml
# /opt/docker/monitoring/compose.yml
services:
  prometheus:
    image: prom/prometheus:v2.54.1
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=${PROM_RETENTION:-30d}'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    networks:
      - monitoring

  loki:
    image: grafana/loki:3.0.0
    container_name: loki
    restart: unless-stopped
    volumes:
      - ./loki:/etc/loki
      - loki_data:/loki
    command:
      - '-config.file=/etc/loki/loki-config.yml'
    ports:
      - "3100:3100"
    networks:
      - monitoring

  promtail:
    image: grafana/promtail:3.0.0
    container_name: promtail
    restart: unless-stopped
    volumes:
      - ./promtail:/etc/promtail
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    command:
      - '-config.file=/etc/promtail/promtail-config.yml'
    networks:
      - monitoring
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:11.3.0
    container_name: grafana
    restart: unless-stopped
    volumes:
      - ./grafana/datasources:/etc/grafana/provisioning/datasources
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=${GF_ADMIN_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASSWORD:-admin}
      - GF_INSTALL_PLUGINS=${GF_PLUGINS:-}
      - GF_SERVER_HTTP_PORT=3000
    ports:
      - "3000:3000"
    networks:
      - monitoring
    depends_on:
      - prometheus

  docker_exporter:
    image: prometheuscommunity/docker-exporter:latest
    container_name: docker_exporter
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "9101:9101"
    networks:
      - monitoring

volumes:
  prometheus_data:
  loki_data:
  grafana_data:

networks:
  monitoring:
    name: monitoring
    external: false
```

**Notes:**
- Retention defaults to 30 days — tune `PROM_RETENTION` in `.env`.
- Promtail needs access to `/var/lib/docker/containers` to scrape Docker
  container logs. On hosts with SELinux or AppArmor, you may need
  additional rules.
- The `docker_exporter` exposes container CPU/mem/network stats at
  port 9101.

```bash
# /opt/docker/monitoring/.env
PROM_RETENTION=30d
GF_ADMIN_USER=admin
GF_ADMIN_PASSWORD=changeme!
GF_PLUGINS=grafana-piechart-panel
```

---

## 2. Prometheus Configuration

```yaml
# /opt/docker/monitoring/prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

rule_files:
  - "rules/alerts.yml"

scrape_configs:
  # Local node_exporter (on the Proxmox host)
  - job_name: 'node'
    static_configs:
      - targets: ['10.0.20.30:9100']
        labels:
          host: srv1

  # Docker exporter (running in compose)
  - job_name: 'docker'
    static_configs:
      - targets: ['docker_exporter:9101']
        labels:
          host: srv1

  # Prometheus itself
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Why node_exporter runs outside Docker:** Docker networking adds a NAT
layer that makes host-level metrics inaccurate. Running `node_exporter`
directly on the Proxmox host (or inside a privileged LXC with host
network) gives you real CPU, disk, and network numbers.

### Installing node_exporter on Proxmox (or LXC)

```bash
# Download and install (replace version as needed)
NODE_EXPORTER_VER=1.8.2
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VER}/node_exporter-${NODE_EXPORTER_VER}.linux-amd64.tar.gz
tar xzf node_exporter-${NODE_EXPORTER_VER}.linux-amd64.tar.gz
sudo cp node_exporter-${NODE_EXPORTER_VER}.linux-amd64/node_exporter /usr/local/bin/
rm -rf node_exporter-${NODE_EXPORTER_VER}.linux-amd64*

# Create systemd service
sudo tee /etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/local/bin/node_exporter \
  --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/) \
  --collector.textfile.directory=/var/lib/node_exporter/textfile
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter

# Verify
curl http://localhost:9100/metrics | head -5
```

If you run this inside an unprivileged LXC, you'll hit issues with
ZFS and disk metrics. For full host metrics, deploy node_exporter on
the Proxmox host itself — it's lightweight (~30 MB RAM, negligible CPU).

---

## 3. Loki Configuration

```yaml
# /opt/docker/monitoring/loki/loki-config.yml
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
  ingestion_rate_mb: 4
  ingestion_burst_size_mb: 8

table_manager:
  retention_deletes_enabled: true
  retention_period: 720h  # 30 days
```

This is a single-binary, single-instance Loki config — fine for a
homelab. If you want to scale later, Loki supports S3/GCS backends
and horizontal sharding.

---

## 4. Promtail Configuration

Promtail runs as a Docker container but needs access to Docker's log
files to extract container names and labels.

```yaml
# /opt/docker/monitoring/promtail/promtail-config.yml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: system
    static_configs:
      - targets:
          - localhost
        labels:
          job: varlogs
          __path__: /var/log/*.log

  - job_name: docker
    pipeline_stages:
      - docker: {}
    static_configs:
      - targets:
          - localhost
        labels:
          job: docker
          __path__: /var/lib/docker/containers/*/*-log.json
```

What this does:
- **system**: Scrapes all `.log` files in `/var/log/` — syslog, auth,
  kern, daemon, etc.
- **docker**: Reads JSON log files from Docker containers, extracts
  container labels, and adds them as Loki labels.

---

## 5. Grafana Provisioning

Provision datasources automatically so Grafana is ready on first boot.

```yaml
# /opt/docker/monitoring/grafana/datasources/prometheus.yml
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
```

For dashboards, drop JSON exports from Grafana.com into:
```
/opt/docker/monitoring/grafana/dashboards/
```

The two I use daily:
- **Node Exporter Full** (ID 1860) — Host metrics (CPU, RAM, disk, network, temp)
- **Docker Monitoring** (ID 12220) — Container resource usage

To provision them automatically:

```bash
# Download dashboard JSONs at deploy time
mkdir -p /opt/docker/monitoring/grafana/dashboards
curl -s -o /opt/docker/monitoring/grafana/dashboards/node_exporter.json \
  "https://grafana.com/api/dashboards/1860/revisions/38/download"
curl -s -o /opt/docker/monitoring/grafana/dashboards/docker_monitoring.json \
  "https://grafana.com/api/dashboards/12220/revisions/5/download"
```

Then add a dashboard provider:

```yaml
# /opt/docker/monitoring/grafana/dashboards/dashboard.yml
apiVersion: 1

providers:
  - name: 'default'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: true
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

---

## 6. Alerts — Catching Problems Before You Wake Up

```yaml
# /opt/docker/monitoring/prometheus/rules/alerts.yml
groups:
  - name: host_alerts
    interval: 30s
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "CPU > 80% on {{ $labels.instance }} for 10m"

      - alert: HighDiskUsage
        expr: (1 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|devtmpfs"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay|devtmpfs"})) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk > 85% on {{ $labels.instance }} - {{ $labels.mountpoint }}"

      - alert: NodeDown
        expr: up{job="node"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Node {{ $labels.instance }} is unreachable"

      - alert: HighMemoryUsage
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 90
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "RAM > 90% on {{ $labels.instance }}"
```

Prometheus doesn't send notifications on its own — for that, add
**Alertmanager**:

```yaml
# Quick Alertmanager to Telegram if you already have a bot
services:
  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: alertmanager
    restart: unless-stopped
    volumes:
      - ./alertmanager:/etc/alertmanager
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
    ports:
      - "9093:9093"
    networks:
      - monitoring

networks:
  monitoring:
    external: true
    name: monitoring
```

```yaml
# /opt/docker/monitoring/alertmanager/alertmanager.yml
route:
  receiver: telegram
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: telegram
    telegram_configs:
      - bot_token: YOUR_BOT_TOKEN
        chat_id: YOUR_CHAT_ID
        parse_mode: HTML
```

---

## 7. Deploying the Stack

```bash
cd /opt/docker/monitoring

# Pull images and start
docker compose pull
docker compose up -d

# Check all running
docker compose ps

# Verify endpoints
curl -s http://localhost:9090/-/ready    # Prometheus
curl -s http://localhost:3100/ready      # Loki
curl -s http://localhost:3000/api/health # Grafana

# Prometheus targets (should show UP for node, docker, prometheus)
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].labels'
```

First-time login to Grafana at `http://<host>:3000` with
`admin` / `changeme!` (overridable in `.env`). Prometheus and Loki
datasources are pre-configured. Open the provisioned dashboards and
confirm data is flowing.

---

## 8. Adding the Proxmox Host Itself

To also scrape Proxmox VE metrics, enable the Proxmox API exporter:

```yaml
services:
  proxmox_exporter:
    image: prompve/prometheus-pve-exporter:4.1
    container_name: proxmox_exporter
    restart: unless-stopped
    volumes:
      - ./pve-exporter:/etc/pve-exporter
    ports:
      - "9221:9221"
    networks:
      - monitoring

networks:
  monitoring:
    external: true
    name: monitoring
```

```yaml
# /opt/docker/monitoring/pve-exporter/pve.yml
default:
  user: prometheus@pam
  password: your-pve-password
  # Or use: token: "USER@REALM!TOKENID=SECRET"
  verify_ssl: false
```

Add a Prometheus scrape target:
```yaml
  - job_name: 'proxmox'
    static_configs:
      - targets: ['proxmox_exporter:9221']
        labels:
          host: srv1
```

This exposes PVE-specific metrics: VM/LXC state, QEMU guest agent
status, node uptime, storage pool usage, and cluster health.

---

## Resource Usage

Grafana + Prometheus + Loki with 30-day retention consumes roughly:

| Component | RAM | Disk (30d) |
|-----------|-----|------------|
| Prometheus | ~200 MB | ~2-5 GB (depends on scrape targets) |
| Loki | ~150 MB | ~3-8 GB (depends on log volume) |
| Grafana | ~100 MB | ~100 MB (dashboards, DB) |
| promtail | ~30 MB | — |
| node_exporter | ~30 MB | — |
| **Total** | **~500 MB** | **~5-15 GB** |

Tiny footprint for what you get. SSD recommended for Loki/Prometheus
TSDB to avoid write amplification on spinning disks.

---

## What This Catches

Real problems I've caught with this stack:

- **ZFS pool at 97%** → Prometheus alerted → found a 200 GB Docker
  overlay directory from an abandoned container.
- **Docker container restart loop** → promtail showed `OOMKilled` in
  `frigate` logs → increased RAM limit in the LXC.
- **Network interface saturation** → node_exporter + Grafana graph
  showed the `enp3s0` interface hitting 950 Mbps → found a Sonarr
  import hammering NFS.
- **Proxmox storage filling** → PVE exporter alerted on `rpool` usage →
  pruned old PBS backups.

Without the stack, every single one of these would have been discovered
when something broke, not when it was trending that direction.

---

## Summary

```bash
# Fast deploy — copy, edit .env, run
git clone https://github.com/yourfork/homelab-monitoring /opt/docker/monitoring
cd /opt/docker/monitoring
# Install node_exporter on host (not in Docker)
# Edit .env with your admin password
docker compose up -d
# Browse to http://<host>:3000  (admin / your-password)
```

A monitoring stack isn't optional in a serious homelab. It's the
difference between managing by glance and managing by data. Prometheus +
Grafana + Loki run on a single Docker host with barely 500 MB of RAM and
give you full observability — metrics from the host, from Docker
containers, from Proxmox itself, and all logs searchable in one place.
