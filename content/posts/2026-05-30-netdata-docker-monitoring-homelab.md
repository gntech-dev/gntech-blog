---
title: "Netdata Docker Monitoring — Real-Time Container Monitoring Guide"
description: "Deploy Netdata with Docker Compose for real-time container monitoring. Per-second metrics, health alarms, auto-detection, and parent-child streaming for multi-host homelab observability."
date: 2026-05-30T07:00:00-04:00
tags:
  - monitoring
  - docker
  - linux
  - homelab
  - performance
keywords:
  - Netdata Docker monitoring homelab deployment
  - real-time container infrastructure monitoring
  - Netdata Docker Compose configuration
  - Netdata health alarms notifications setup
  - Netdata parent-child streaming multiple hosts
  - Netdata per-second metrics auto-detection
  - Netdata Prometheus Grafana integration
summary: "Complete guide to deploying Netdata with Docker Compose for real-time container and infrastructure monitoring in your homelab. Covers auto-detection, health alarms, notifications, parent-child streaming, and Prometheus integration."
canonical: "https://blog.gntech.me/posts/netdata-docker-monitoring-homelab/"
---

If your homelab has five containers running on a single host, you can
get away with occasional glances at `docker stats`. But when you're
running twenty-plus services across multiple hosts — databases, reverse
proxies, media servers, automation pipelines — you need observability
that keeps up.

You probably already have Prometheus scraping metrics every 15 seconds
and Grafana dashboards for historical analysis. That covers the *what
happened* question. But it misses the *what is happening right now*
question — the spikes, the blips, the containers that briefly peg the
CPU and settle down before Prometheus comes back for its next scrape.

That's where Netdata comes in.

Netdata is a real-time monitoring agent that collects thousands of
metrics per-second with zero configuration. Spin it up in a container,
point your browser at port 19999, and you get per-second dashboards for
CPU, memory, disk, network, processes, and every running container. No
setup, no queries to write, no dashboard building.

This guide covers deploying Netdata with Docker Compose, understanding
the dashboard, configuring health alarms and notifications, setting up
parent-child streaming for multi-host environments, and integrating with
Prometheus and Grafana for a complete observability stack.

## Deploying Netdata with Docker Compose

Netdata needs access to host-level system files to collect metrics.
The cleanest way to provide this in Docker is to bind-mount `/proc`,
`/sys`, and `/var/run/docker.sock` into the container and use host
networking mode.

### Basic Docker Compose Configuration

Create a `docker-compose.yml` for Netdata:

```yaml
services:
  netdata:
    image: netdata/netdata:latest
    container_name: netdata
    hostname: srv1
    network_mode: host
    pid: host
    cap_add:
      - SYS_PTRACE
      - SYS_ADMIN
    security_opt:
      - apparmor:unconfined
    environment:
      - NETDATA_CLAIM_TOKEN=
      - NETDATA_CLAIM_URL=
      - NETDATA_CLAIM_ROOMS=
    volumes:
      - /etc/passwd:/host/etc/passwd:ro
      - /etc/group:/host/etc/group:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - netdata_config:/etc/netdata
      - netdata_lib:/var/lib/netdata
      - netdata_cache:/var/cache/netdata
    restart: unless-stopped

volumes:
  netdata_config:
  netdata_lib:
  netdata_cache:
```

Key points about this configuration:

- **`network_mode: host`** — Gives Netdata direct access to host network interfaces so it can report per-interface bandwidth and per-connection details. Without it, Netdata only sees the container's virtual interface.
- **`pid: host`** — Allows Netdata to see all host processes, including container processes running outside its PID namespace.
- **`cap_add: SYS_PTRACE`** — Required for process-level monitoring. Without it, Netdata cannot inspect the cgroups of other containers.
- **Volume mounts** — The `/host/*` bind mounts let Netdata read system files through a consistent path. The Docker socket gives it container-level metrics via cgroups.

### Quick Start with Docker Run

If you want to test Netdata before committing to compose:

```bash
docker run -d --name=netdata \
  --pid=host \
  --network=host \
  -v /etc/passwd:/host/etc/passwd:ro \
  -v /etc/group:/host/etc/group:ro \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --cap-add SYS_PTRACE \
  --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  netdata/netdata
```

Access the dashboard at `http://YOUR_HOST_IP:19999`.

## Understanding the Netdata Dashboard

Open the dashboard and you'll see a scrollable page of charts grouped
by subsystem. The layout is intentionally flat — no drill-downs, no
navigation tree. Every chart is visible on one page.

### Sections You Get Automatically

- **System Overview** — CPU usage (per-core), load average, uptime, context switches, interrupts, softirqs
- **CPU** — Per-core frequency, temperature, c-states, throttling
- **Memory** — RAM usage, swap, page faults, memory available, committed memory
- **Disk** — Per-disk and per-partition I/O (read/write ops, bandwidth, latency, backlog, utilization)
- **Network** — Per-interface bandwidth, packets, errors, drops, retransmits, TCP states
- **Processes** — Running, blocked, zombie, forks, threads
- **Containers** — Per-container CPU, memory, disk I/O, network traffic (auto-detected from cgroups)

The container section is where Netdata shines for Docker users. Every
running container appears automatically with per-second CPU and memory
charts. Click any container to see its dedicated view with network and
disk metrics scoped to that container.

### Per-Second Resolution

Every chart updates every second. When Prometheus scrapes every 15
seconds, it captures 4 data points per minute. Netdata captures 60.
This granularity catches short-lived spikes — a cron job that pegs
CPU for three seconds, a database checkpoint that bursts I/O, a
container that OOM-kills and restarts between Prometheus scrape
intervals.

### Chart Interactions

- **Hover** — See the exact value at any point
- **Click and drag** — Zoom into a time range
- **Double-click** — Reset zoom
- **Pause** — Freeze the live view to inspect a specific moment
- **Volume (heatmap) mode** — Toggle charts to show distribution instead of line plots

## Configuring Health Alarms and Notifications

Netdata ships with 200+ pre-configured health alarms covering CPU,
memory, disk, network, and container metrics. They work immediately
and send alerts to the dashboard's "Alarms" tab.

### Built-In Alarm Examples

| Alarm | Warning Threshold | Critical Threshold |
|-------|-------------------|--------------------|
| CPU usage | 80% for 2 minutes | 90% for 1 minute |
| RAM usage | 85% | 95% |
| Disk space | 80% | 95% |
| Disk I/O time | 90% for 2 minutes | 95% for 1 minute |
| Network interface dropped packets | 0.1% of total | 0.5% of total |
| Outbound OOM kills | — | 1 event |

These values are defined in `/etc/netdata/health.d/` and are
customizable. To override an alarm, create a file in
`/var/lib/netdata/health.d/` (mounted as `netdata_lib`):

```bash
# Create custom directory on the host
mkdir -p /opt/netdata/health.d

# Override CPU alarm thresholds
cat << 'EOF' > /opt/netdata/health.d/cpu.conf
 alarm: cpu_user
    on: system.cpu
   lookup: average -5m of user
  units: %
  every: 10s
   warn: $this > 70
   crit: $this > 85
```

### Setting Up Notifications

Netdata supports multiple notification channels. The most practical for
homelabs are Discord, Telegram, and email.

**Telegram notifications:**

Add these environment variables to your Compose service:

```yaml
environment:
  - NETDATA_NOTIFICATION_TELEGRAM_BOT_TOKEN=your_bot_token
  - NETDATA_NOTIFICATION_TELEGRAM_CHAT_ID=your_chat_id
  - NETDATA_NOTIFICATION_TELEGRAM_SEND_BUTTON=YES
  - NETDATA_NOTIFICATION_TELEGRAM_TRIGGER_ROLE=silent
```

**Discord notifications:**

```yaml
environment:
  - NETDATA_NOTIFICATION_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook
  - NETDATA_NOTIFICATION_DISCORD_SEND_BUTTON=YES
```

The `SEND_BUTTON=YES` option adds a link back to the relevant chart in
the notification message, so you can jump directly to the metric that
triggered the alarm.

## Parent-Child Streaming for Multi-Host Monitoring

When you have multiple Proxmox hosts, LXCs, or VMs, running a separate
Netdata dashboard per host is impractical. Parent-child streaming lets
you designate one host as the "parent" that receives and displays
metrics from all "child" nodes.

### How Streaming Works

- The child node collects metrics locally and streams them to the parent
  over TCP port 19999
- The parent stores the metrics and serves a unified dashboard
- Each child's section appears grouped under its hostname
- Communication uses API key authentication

### Configure the Parent Node

Add a streaming configuration file:

```bash
mkdir -p /opt/netdata/stream
cat << 'EOF' > /opt/netdata/stream/stream.conf
[stream]
    enabled = yes
    default memory mode = dbengine
    default history = 3600

[API_KEY]
    enabled = yes
    type = api
    user = stream_user
    guid = your-random-api-key-here
    default history = 3600
    default memory mode = dbengine
    health enabled by default = auto
    allow from = *
EOF
```

Mount this into the parent's container:

```yaml
volumes:
  - /opt/netdata/stream/stream.conf:/etc/netdata/stream.conf:ro
```

### Configure a Child Node

On each child host, add these environment variables:

```yaml
environment:
  - NETDATA_STREAM_DESTINATION=PARENT_HOST_IP:19999
  - NETDATA_STREAM_API_KEY=your-random-api-key-here
  - NETDATA_STREAM_SEND_ALARMS=YES
```

Replace `PARENT_HOST_IP` with the IP of your parent Netdata instance.
All child nodes use the same API key for authentication.

## Netdata as a Prometheus Scrape Target

Netdata exposes a Prometheus-compatible metrics endpoint at
`/api/v1/allmetrics?format=prometheus`. This means you can keep your
existing Prometheus + Grafana stack and add Netdata as an additional
data source for real-time overlay.

### Add Netdata to Prometheus Scrape Config

In your Prometheus `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'netdata'
    scrape_interval: 15s
    metrics_path: '/api/v1/allmetrics'
    params:
      format: ['prometheus']
    static_configs:
      - targets: ['10.0.20.30:19999']
        labels:
          host: srv1
```

Then import the [Netdata Grafana dashboard](https://github.com/netdata/netdata/blob/master/src/web/gui/dashboard/dashboards/grafana/netdata-grafana-dashboard.json) into Grafana for pre-built visualizations of Netdata metrics alongside your existing Prometheus data.

### Why Use Both?

| Aspect | Prometheus/Grafana | Netdata |
|--------|-------------------|---------|
| Time resolution | 15-60s scrape intervals | Per-second |
| Data retention | Weeks/months (TSDB) | Configurable (default 1h RAM) |
| Configuration | Query language, dashboard building | Zero-config, auto-detection |
| Alerting | PromQL alert rules | Pre-built health alarms |
| Best for | Historical trends, long-term analysis, custom dashboards | Real-time troubleshooting, per-second visibility, hands-off monitoring |

## Resource Usage and Performance

Netdata is designed to be lightweight. A typical homelab Netdata
instance uses:

- **Memory**: 150-250 MB RAM for hundreds of metrics with default
  retention (1 hour of per-second data in memory)
- **CPU**: 0.5-2% of a single core on modern x86 hardware
- **Disk I/O**: Near zero with `memory` or `alloc` DB mode; ~50 MB/day
  with `dbengine` mode (journaled persistent storage)

The key is the in-memory ring buffer design. Metrics cycle through RAM
and are discarded after retention expires, so disk writes are minimal
unless you enable the dbengine mode for longer persistence.

### DB Engine Modes

Set via the `NETDATA_DB_ENGINE` environment variable or
`netdata.conf`:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `ram` | All in memory. Fastest, no disk writes. | Ephemeral monitoring |
| `alloc` | Memory-mapped files. Balanced. | Default |
| `dbengine` | Journaled persistent storage. | Historical queries, streaming parent nodes |

## Production Deployment Tips

### 1. Persistent Storage

Always mount persistent volumes for config and lib data. Without them,
updating the container loses alarm customizations and the alarms log.

```yaml
volumes:
  - netdata_config:/etc/netdata
  - netdata_lib:/var/lib/netdata
  - netdata_cache:/var/cache/netdata
```

### 2. Reverse Proxy with Traefik

If you prefer bridge networking or want TLS, expose Netdata behind
your reverse proxy. With Traefik:

```yaml
services:
  netdata:
    image: netdata/netdata:latest
    container_name: netdata
    network_mode: host
    # ... rest of config

  netdata_proxy:
    image: nginx:alpine
    container_name: netdata-proxy
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.netdata.rule=Host(`netdata.yourdomain.com`)"
      - "traefik.http.services.netdata.loadbalancer.server.port=19999"

networks:
  proxy:
    external: true
```

### 3. Update with Watchtower

Netdata updates frequently with new collectors and improvements.
Pair with Watchtower for automatic updates:

```bash
docker run -d --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --cleanup --interval 86400 netdata
```

### 4. Access Control

By default, the Netdata dashboard has no authentication. For homelab
use behind a VPN or Tailscale this is fine, but if you expose it
through Cloudflare Tunnel or a public reverse proxy, add HTTP basic
auth via your reverse proxy's middleware.

## Netdata Cloud (Optional)

Netdata Cloud is a free SaaS layer that aggregates dashboards from
multiple agents without setting up parent-child streaming. Agents
connect via the `NETDATA_CLAIM_TOKEN` environment variable. It's
useful if you don't want to manage a parent node yourself, but for
a homelab the parent-child approach gives you full control and zero
data leaving your network.

## Verifying the Installation

After deploying, confirm Netdata is working:

```bash
# Check the container is running
docker ps --filter name=netdata

# Check the dashboard responds
curl -s -o /dev/null -w "%{http_code}" http://localhost:19999/api/v1/info

# View container metrics directly
curl -s http://localhost:19999/api/v1/allmetrics?format=prometheus | head -20

# Check alarms status
curl -s http://localhost:19999/api/v1/alarms | python3 -m json.tool | head -30
```

Expected output for the health check: `200`.

## Conclusion

Netdata fills a gap that every homelab operator eventually hits:
real-time, per-second observability with zero configuration. While
Prometheus and Grafana handle your long-term retention and custom
dashboards, Netdata gives you the live view — the spikes, the
blips, the containers that misbehave for five seconds and settle
down before your next Grafana refresh.

Deploying it takes five minutes. The Docker Compose above gives you
a complete monitoring agent that auto-discovers every container on
your host, ships with 200+ pre-configured alarms, and can stream to
a parent node for centralized dashboards across multiple hosts.

Pair it with Prometheus and Grafana for a comprehensive observability
stack that covers both real-time and historical perspectives. Your
future self — chasing a container that's pegging CPU at 3 AM — will
thank you.
