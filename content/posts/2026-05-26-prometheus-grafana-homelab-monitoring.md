---
title: "Prometheus and Grafana — Homelab Monitoring Stack with Docker Compose"
description: "Deploy a complete Prometheus and Grafana monitoring stack for your homelab with Docker Compose — metrics from every host and container with Node Exporter, cAdvisor, Alertmanager, and production-ready dashboards."
date: 2026-05-26T22:00:00Z
tags:
  - monitoring
  - prometheus
  - grafana
  - docker
  - docker-compose
  - linux
  - homelab
  - observability
keywords:
  - Prometheus Grafana monitoring stack Docker Compose homelab
  - Node Exporter host metrics CPU memory disk
  - cAdvisor Docker container metrics monitoring
  - Prometheus Alertmanager notification configuration
  - Grafana dashboard import Node Exporter cAdvisor
  - Alertmanager email Slack webhook homelab alerts
  - Prometheus data retention and storage configuration
summary: "A practical guide to deploying a full Prometheus and Grafana monitoring stack in your homelab with Docker Compose — collect CPU, RAM, disk, network, and Docker container metrics from every host, visualize with pre-built dashboards, and get alerts when things go wrong."
canonical: "https://gntech.dev/posts/prometheus-grafana-homelab-monitoring/"
---

You have five services running in Docker. Some are critical —
your DNS resolver, your reverse proxy, your database. If one of
them crashes or a disk fills up, how do you know?

SSHing into every host and running `htop` does not scale past one
machine. You need a monitoring stack that collects metrics from
every host and service, visualizes them in dashboards, and alerts
you when something needs attention.

Prometheus scrapes metrics on a schedule. Grafana turns those
metrics into dashboards. Node Exporter exposes Linux kernel and
hardware counters. cAdvisor exposes Docker container resource
usage. Alertmanager routes notifications to email, Slack, or
Telegram. Together they form the standard observability stack for
Linux infrastructure.

This guide deploys the entire stack with a single Docker Compose
file, configures it for a multi-host homelab, and walks through
the first dashboards and alerts.

---

## Architecture Overview

The stack has four components, all deployed via Docker Compose on
one "monitoring" host:

```
┌─────────────────────────────────────┐
│           Docker Network            │
│            monitoring-net           │
│                                     │
│  ┌──────────┐  ┌───────────┐       │
│  │ Grafana  │──│ Prometheus │       │
│  │ :3000    │  │ :9090     │       │
│  └────┬─────┘  └─────┬─────┘       │
│       │              │             │
│       │   ┌──────────┴──────────┐  │
│       └───┤ Alertmanager :9093 │  │
│           └──────────┬──────────┘  │
│                      │             │
│           ┌──────────┴──────────┐  │
│           │  Notification       │  │
│           │  (Email/Slack/TG)   │  │
│           └─────────────────────┘  │
└─────────────────────────────────────┘
        ▲                     ▲
        │ scrape              │ scrape
        │ :9100               │ :8080
   ┌────┴─────┐          ┌────┴─────┐
   │Node      │          │ cAdvisor │
   │Exporter  │          │ :8080    │
   │(each host)│          │(per host)│
   └──────────┘          └──────────┘
```

Prometheus is the central collector. It pulls metrics from each
Node Exporter and cAdvisor instance on a configurable interval
(default 15 seconds). Grafana queries Prometheus to render
dashboards. Alertmanager evaluates alert rules and fires
notifications.

---

## Step 1 — Create the Directory Structure

```bash
mkdir -p /opt/monitoring/{prometheus,alertmanager,grafana}
mkdir -p /opt/monitoring/prometheus/data
mkdir -p /opt/monitoring/grafana/data
```

Set ownership so Grafana and Prometheus can write their data:

```bash
chown 472:472 /opt/monitoring/grafana/data
chown 65534:65534 /opt/monitoring/prometheus/data
```

The UIDs are the default user inside each container (grafana=472,
prometheus=nobody=65534). Mismatch these and the containers will
crash on startup with permission errors.

---

## Step 2 — Prometheus Configuration

Write `/opt/monitoring/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

rule_files:
  - "alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

scrape_configs:
  # Prometheus self-metrics
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]

  # Node Exporter — one target per host
  - job_name: node
    static_configs:
      - targets:
        - "10.0.20.30:9100"   # SRV1 — Proxmox host
        - "10.0.20.31:9100"   # SRV2 — backup node
        - "10.0.20.10:9100"   # GATEWAY — OpenClaw gateway
      relabel_configs:
        - source_labels: ["__address__"]
          regex: "([^:]+):.+"
          target_label: "instance"

  # cAdvisor — one target per host
  - job_name: cadvisor
    static_configs:
      - targets:
        - "10.0.20.30:8080"   # SRV1
        - "10.0.20.31:8080"   # SRV2
      relabel_configs:
        - source_labels: ["__address__"]
          regex: "([^:]+):.+"
          target_label: "instance"
```

### Alert Rules

Write `/opt/monitoring/prometheus/alerts.yml`:

```yaml
groups:
  - name: homelab-alerts
    rules:
      - alert: NodeDown
        expr: up{job="node"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Node {{ $labels.instance }} is down"
          description: "{{ $labels.instance }} has been unreachable for more than 2 minutes."

      - alert: DiskSpaceCritical
        expr: (1 - (node_filesystem_free_bytes{fstype!="tmpfs",mountpoint!="/boot"} /
              node_filesystem_size_bytes{fstype!="tmpfs",mountpoint!="/boot"})) * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk space >90% on {{ $labels.instance }} - {{ $labels.mountpoint }}"
          description: "Disk at {{ $labels.mountpoint }} on {{ $labels.instance }} is {{ $value | humanizePercentage }} full."

      - alert: DiskSpaceWarning
        expr: (1 - (node_filesystem_free_bytes{fstype!="tmpfs",mountpoint!="/boot"} /
              node_filesystem_size_bytes{fstype!="tmpfs",mountpoint!="/boot"})) * 100 > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Disk space >80% on {{ $labels.instance }} - {{ $labels.mountpoint }}"

      - alert: HighCpuLoad
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100) > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "CPU >85% on {{ $labels.instance }}"
          description: "CPU usage on {{ $labels.instance }} is at {{ $value | humanizePercentage }}."

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory >90% on {{ $labels.instance }}"
          description: "Memory usage on {{ $labels.instance }} is at {{ $value | humanizePercentage }}."

      - alert: DockerContainerDown
        expr: time() - container_last_seen > 60
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.name }} is down"
          description: "Container {{ $labels.name }} has not reported metrics for over 60 seconds."
```

---

## Step 3 — Alertmanager Configuration

Write `/opt/monitoring/alertmanager/alertmanager.yml`:

```yaml
route:
  group_by: ["alertname", "instance"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: "default"

receivers:
  - name: "default"
    email_configs:
      - to: "admin@gntech.dev"
        from: "alerts@gntech.dev"
        smarthost: "smtp.gmail.com:587"
        auth_username: "alerts@gntech.dev"
        auth_password: $SMTP_PASSWORD
        require_tls: true
    webhook_configs:
      - url: "https://hooks.slack.com/services/T00/B00/xxxxxxxxx"
        send_resolved: true
```

For Telegram notifications, add a webhook receiver:

```yaml
    webhook_configs:
      - url: "http://telegram-webhook:8080/alert"
        send_resolved: true
```

Use environment variables for secrets. The Compose file passes
`$SMTP_PASSWORD` into Alertmanager. Never hardcode tokens in
config files committed to git.

---

## Step 4 — Docker Compose Configuration

Write `/opt/monitoring/docker-compose.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    hostname: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro
      - ./prometheus/data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"
      - "--web.console.libraries=/usr/share/prometheus/console_libraries"
      - "--web.console.templates=/usr/share/prometheus/consoles"
      - "--web.enable-lifecycle"
    ports:
      - "9090:9090"
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:latest
    container_name: alertmanager
    hostname: alertmanager
    restart: unless-stopped
    volumes:
      - ./alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
      - "--storage.path=/alertmanager"
      - "--web.listen-address=:9093"
    ports:
      - "9093:9093"
    environment:
      - SMTP_PASSWORD=${SMTP_PASSWORD}
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    hostname: grafana
    restart: unless-stopped
    volumes:
      - ./grafana/data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    environment:
      - GF_SECURITY_ADMIN_USER=${GRAFANA_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
      - GF_SERVER_ROOT_URL=https://grafana.gntech.dev
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
    networks:
      - monitoring-net

networks:
  monitoring-net:
    name: monitoring-net
    driver: bridge
```

### Data Retention

The `--storage.tsdb.retention.time=30d` flag keeps 30 days of
metrics. For a homelab collecting ~1000 series per host, this
uses roughly 500 MB–1 GB of disk per month. Adjust to `7d` or
`90d` based on your storage budget.

---

## Step 5 — Deploy Node Exporter and cAdvisor on Each Host

You need Node Exporter and cAdvisor running on every machine you
want to monitor. Node Exporter provides host-level metrics (CPU,
RAM, disk, network). cAdvisor provides per-container resource
usage.

### Node Exporter (systemd service)

Create `/etc/systemd/system/node-exporter.service`:

```ini
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
ExecStart=/usr/local/bin/node_exporter \
  --web.listen-address=:9100 \
  --path.procfs=/proc \
  --path.sysfs=/sys \
  --collector.filesystem.mount-points-exclude="^/(sys|proc|dev|host|etc)($|/)"
Restart=always

[Install]
WantedBy=multi-user.target
```

Install the binary:

```bash
wget -O /tmp/node_exporter.tar.gz \
  https://github.com/prometheus/node_exporter/releases/download/v1.10.0/node_exporter-1.10.0.linux-amd64.tar.gz
tar xzf /tmp/node_exporter.tar.gz -C /tmp/
sudo mv /tmp/node_exporter-1.10.0.linux-amd64/node_exporter /usr/local/bin/
rm -rf /tmp/node_exporter*
sudo systemctl daemon-reload
sudo systemctl enable --now node-exporter
```

Verify it is collecting metrics:

```bash
curl -s http://localhost:9100/metrics | head -10
```

### cAdvisor (Docker container)

```bash
docker run -d --name=cadvisor --restart unless-stopped \
  --privileged \
  --device=/dev/kmsg \
  -p 8080:8080 \
  -v /:/rootfs:ro \
  -v /var/run:/var/run:ro \
  -v /sys:/sys:ro \
  -v /var/lib/docker/:/var/lib/docker:ro \
  gcr.io/cadvisor/cadvisor:latest
```

cAdvisor requires `--privileged` to access kernel cgroup metrics.
On Proxmox LXC containers, you may need `lxc.cgroup2: ""` in the
container config for cAdvisor to work properly.

### Firewall Rules

If you use UFW or nftables, open ports 9100 and 8080 to your
monitoring host only:

```bash
# UFW — allow from monitoring host only
ufw allow from 10.0.20.10 to any port 9100 proto tcp
ufw allow from 10.0.20.10 to any port 8080 proto tcp
```

Never expose Node Exporter or cAdvisor ports to the internet.
They serve unauthenticated metrics endpoints that leak system
information.

---

## Step 6 — Start the Stack

```bash
cd /opt/monitoring
docker compose up -d
```

Check that everything is running:

```bash
docker compose ps
# NAME                IMAGE                     STATUS
# alertmanager        prom/alertmanager:latest  Up 2 minutes
# grafana             grafana/grafana:latest     Up 2 minutes
# prometheus          prom/prometheus:latest     Up 2 minutes
```

Check Prometheus targets:

```bash
# List all configured scrape targets
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health}'
```

All targets should show `"health": "up"`. If any show `"down"`,
check firewall rules and verify that Node Exporter / cAdvisor are
running on the target host.

---

## Step 7 — Import Grafana Dashboards

Log into Grafana at `http://your-host:3000` (default credentials:
admin / admin — change immediately on first login).

### Add Prometheus as a Data Source

1. **Configuration → Data Sources → Add data source**
2. Select **Prometheus**
3. Set **URL** to `http://prometheus:9090` (Docker internal DNS)
4. Click **Save & Test**

### Import the Node Exporter Full Dashboard

The best dashboard for host metrics is
[Node Exporter Full](https://grafana.com/grafana/dashboards/1860)
(dashboard ID: 1860):

1. **Dashboards → Import**
2. Enter dashboard ID `1860`
3. Select the Prometheus data source
4. Click **Import**

### Import the Docker Monitoring Dashboard

For container metrics, use the
[Docker Monitoring](https://grafana.com/grafana/dashboards/193/)
dashboard (ID: 193):

1. **Dashboards → Import**
2. Enter dashboard ID `193`
3. Select the Prometheus data source
4. Click **Import**

### Create a Simple CPU Dashboard (Manual)

If you prefer a minimal dashboard over importing large ones:

1. **Dashboards → New Dashboard → Add visualization**
2. Select **Prometheus** as data source
3. Enter this PromQL query for CPU:

```promql
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

4. Set title to "CPU Usage by Host"
5. Add another panel with this memory query:

```promql
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

6. Add a disk panel:

```promql
(1 - (node_filesystem_free_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100
```

7. Save the dashboard

### Key PromQL Queries for Homelab Monitoring

| What to measure | PromQL query |
|---|---|
| CPU per host (%) | `100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)` |
| Memory used (%) | `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100` |
| Disk used per mount (%) | `(1 - (node_filesystem_free_bytes / node_filesystem_size_bytes)) * 100` |
| Disk IOPS (reads) | `rate(node_disk_reads_completed_total[5m])` |
| Disk IOPS (writes) | `rate(node_disk_writes_completed_total[5m])` |
| Network throughput (rx) | `rate(node_network_receive_bytes_total{device!="lo"}[5m])` |
| Network throughput (tx) | `rate(node_network_transmit_bytes_total{device!="lo"}[5m])` |
| Container CPU per name | `sum by(name) (rate(container_cpu_usage_seconds_total{name!=""}[5m]))` |
| Container memory per name | `container_memory_usage_bytes{name!=""}` |
| Uptime (days) | `(time() - node_boot_time_seconds) / 86400` |
| Load average (1m) | `node_load1` |

---

## Step 8 — Test an Alert

Trigger a test alert to verify Alertmanager is working:

```bash
# Send a test message to Alertmanager
curl -X POST -H "Content-Type: application/json" \
  -d '{
    "labels": {"alertname": "TestAlert", "severity": "critical", "instance": "test-host"},
    "annotations": {"summary": "This is a test alert", "description": "Homelab monitoring stack is configured correctly."}
  }' \
  http://localhost:9093/api/v1/alerts
```

Check Alertmanager status:

```bash
curl -s http://localhost:9093/api/v2/alerts | jq '.[].labels'
```

If email or Slack webhook is configured, you should receive the
test notification within a few seconds.

---

## Step 9 — Long-Term Data and Backup

Prometheus stores metrics as TSDB blocks on disk. After 30 days
(default from this guide), old blocks are deleted. If you want
longer retention, either increase the retention period or add
remote write to VictoriaMetrics or Thanos.

### Back up Grafana

Grafana dashboards and data sources live in the SQLite database
at `/opt/monitoring/grafana/data/grafana.db`. Back it up daily:

```bash
# Simple backup script
cp /opt/monitoring/grafana/data/grafana.db \
  /opt/monitoring/grafana/data/grafana.db.$(date +%Y%m%d)
```

Better approach: use Grafana's
[Provisioning API](https://grafana.com/docs/grafana/latest/administration/provisioning/)
to define dashboards as YAML files in `./grafana/provisioning/dashboards/`.
This way, dashboards are version-controlled and survive container
recreations.

### Grafana Provisioning Example

Create `/opt/monitoring/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
```

Create `/opt/monitoring/grafana/provisioning/dashboards/dashboard.yml`:

```yaml
apiVersion: 1

providers:
  - name: "default"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
```

Drop exported JSON dashboard files into `./grafana/dashboards/`
and they will load automatically on container restart.

---

## Step 10 — Adding More Hosts

Adding a new host to the monitoring stack takes two minutes:

```bash
# On the new host:
# 1. Install and start Node Exporter
sudo systemctl enable --now node-exporter

# 2. Start cAdvisor (run as docker container)
docker run -d --name=cadvisor --restart unless-stopped \
  --privileged -p 8080:8080 \
  -v /:/rootfs:ro -v /var/run:/var/run:ro \
  -v /sys:/sys:ro -v /var/lib/docker/:/var/lib/docker:ro \
  gcr.io/cadvisor/cadvisor:latest

# 3. On the monitoring host, add to prometheus.yml
#    under node job and cadvisor job targets:
#    - "10.0.20.50:9100"
#    - "10.0.20.50:8080"

# 4. Reload Prometheus without restart
curl -X POST http://localhost:9090/-/reload
```

The `--web.enable-lifecycle` flag on Prometheus enables the
`/-/reload` endpoint without a full restart. Use it whenever you
add or remove scrape targets.

---

## Security Considerations

- **Never expose ports 9090 (Prometheus), 9093 (Alertmanager),
  or 3000 (Grafana) to the internet.** These are management
  interfaces. Route Grafana through your reverse proxy with HTTPS
  and authentication.
- **Node Exporter and cAdvisor serve unauthenticated metrics.**
  Firewall them to your monitoring subnet only. A reverse proxy is
  not enough — these should not be accessible from outside your
  LAN at all.
- **Change Grafana admin password** on first login. In the Compose
  file, use `$GRAFANA_PASSWORD` from an `.env` file instead of the
  default.
- **Alertmanager SMTP password** should be in an `.env` file, not
  committed to git.

Create `/opt/monitoring/.env`:

```bash
GRAFANA_USER=admin
GRAFANA_PASSWORD=your-strong-password-here
SMTP_PASSWORD=your-gmail-app-password
```

Add `.env` to `.gitignore` if you version-control this directory.

---

## Troubleshooting

### Prometheus targets show "down"

```bash
# Check if Node Exporter is listening
nc -zv 10.0.20.30 9100

# Check if cAdvisor responds
curl -s http://10.0.20.30:8080/metrics | head

# Check Prometheus logs
docker logs prometheus --tail 50
```

### Grafana says "No data"

```bash
# Verify Prometheus has metrics for the time range
curl -s 'http://localhost:9090/api/v1/query?query=up'

# Check Grafana data source is pointing to http://prometheus:9090
# (Docker internal DNS, not localhost)
```

### Container metrics missing in cAdvisor

On Proxmox LXC containers, cAdvisor needs cgroup v2 access:

```bash
# In LXC config (/etc/pve/lxc/<CT_ID>.conf), add:
lxc.cgroup2: ""
```

Then restart the container.

### Prometheus storage growing too fast

Reduce retention or limit scraped metrics:

```bash
# In prometheus.yml, add metric_relabel_configs to drop
# high-cardinality labels you don't need:

scrape_configs:
  - job_name: node
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: "(node_cpu_.*|node_memory_.*|node_filesystem_.*)"
        action: keep
```

This keeps only CPU, memory, and filesystem metrics from Node
Exporter, dropping disk scheduler stats, network hardware info,
and other rarely-used metrics.

---

## Summary

The Prometheus + Grafana stack gives you full observability into
every host and container in your homelab. With today's setup you
get:

- **Host metrics** — CPU, RAM, disk, network, and load from every
  machine via Node Exporter
- **Container metrics** — per-container CPU, memory, network, and
  filesystem via cAdvisor
- **Dashboards** — pre-built Node Exporter and Docker monitoring
  dashboards in Grafana
- **Alerts** — disk space, CPU, memory, and container-down alerts
  routed to email or Slack via Alertmanager
- **Easy expansion** — add hosts by deploying Node Exporter +
  cAdvisor and adding one line to prometheus.yml

Start with the single-host Compose stack, add Node Exporters to
your other machines one at a time, and within an afternoon you
will have full visibility into your entire lab. When a disk fills
up at 3 AM, your phone will buzz instead of a service crashing
silently.
