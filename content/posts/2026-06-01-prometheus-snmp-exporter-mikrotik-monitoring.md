---
title: "Prometheus SNMP Exporter — Monitoring MikroTik and Network Devices"
description: "Deploy Prometheus SNMP Exporter with Docker to monitor MikroTik routers, switches, and UPS units. Real SNMP metrics, v2c/v3 config, and Grafana dashboards for homelab observability."
date: 2026-06-01T17:00:00-04:00
tags:
  - prometheus
  - mikrotik
  - monitoring
  - networking
  - docker
keywords:
  - Prometheus SNMP Exporter Docker Compose deployment homelab
  - MikroTik SNMP monitoring Prometheus Grafana dashboard
  - SNMP v2c v3 configuration network device monitoring
  - Prometheus SNMP exporter generator config.yml MikroTik
  - Homelab network observability Prometheus SNMP metrics
  - Grafana SNMP dashboard MikroTik router switch monitoring
  - Docker Compose snmp-exporter Prometheus monitoring stack
summary: "Deploy Prometheus SNMP Exporter with Docker Compose to collect bandwidth, CPU, memory, and interface metrics from MikroTik routers and network devices. Configure SNMP v2c/v3, generate the exporter config, and visualize everything in Grafana."
canonical: "https://blog.gntech.me/posts/prometheus-snmp-exporter-mikrotik-monitoring/"
---

## Why SNMP Monitoring Matters for Homelab Networking

You already monitor your Docker hosts and Proxmox server with Prometheus and Grafana. But what about the network devices that make it all work — the MikroTik router, the managed switch, the access points, the UPS? When a switch port starts dropping packets or the router CPU hits 100% under load, you need to know before users notice.

**SNMP (Simple Network Management Protocol)** is the universal language network hardware speaks. Every managed switch, router, access point, and UPS exposes metrics via SNMP — interface traffic counters, CPU load, memory usage, temperature sensors, and more.

The **Prometheus SNMP Exporter** translates those SNMP OID walks into Prometheus metrics, which means you can add your entire network to your existing Grafana dashboards without running a separate monitoring stack. A single Docker Compose service bridges the gap between your network hardware and Prometheus.

What you can monitor with this stack:

- Interface bandwidth in/out (bps) and packet rates per port
- Interface errors, discards, and CRC failures
- CPU utilization and load averages on routers and switches
- Memory usage (total, used, free)
- System uptime and reachability
- UPS battery charge, runtime, and load percentage
- Sensor temperature readings

## Prerequisites

Before deploying, make sure you have:

- **Docker and Docker Compose** on a host in your homelab (Proxmox LXC or dedicated host)
- **A running Prometheus + Grafana stack** — either the full Prometheus + Grafana + Loki stack from [the monitoring guide](https://blog.gntech.me/posts/2026-05-21-prometheus-grafana-monitoring-stack/) or a minimal setup
- **One or more SNMP-enabled devices** — MikroTik RouterOS router, managed switch, or any device exposing SNMP
- **SNMP credentials** — a community string (v2c) or username/auth phrase (v3)

## Enabling SNMP on MikroTik RouterOS

MikroTik RouterOS supports SNMP v1, v2c, and v3 out of the box. For a homelab on a trusted network, v2c with a non-default community string is acceptable. For production or any device exposed to untrusted networks, use v3 with authentication and encryption.

### SNMP v2c Configuration

Connect via SSH or Winbox and run these commands:

```
/ip service set snmp disabled=no
/snmp community set [find] name=monitoring address=10.0.0.0/24
/snmp set enabled=yes contact="admin@gntech.me" location="SRV1 Rack"
```

This does three things:
- Enables the SNMP IP service on the router
- Creates (or updates) a community string `monitoring` restricted to your management subnet `10.0.0.0/24`
- Enables the SNMP agent with contact and location metadata

If this is a fresh RouterOS installation and no community exists yet, create one explicitly:

```
/snmp community add name=monitoring address=10.0.0.0/24
/snmp set enabled=yes
```

### SNMP v3 Configuration (Recommended for Production)

SNMP v3 provides authentication (SHA) and encryption (AES). RouterOS supports it natively:

```
/snmp set enabled=yes
/snmp community set [find] name=monitoring
/user add name=snmp-monitor group=read password="your-secure-password"
/snmp security add user=snmp-monitor group=read authentication=sha1 encryption=aes verify=yes
```

The security entry ties the local user `snmp-monitor` to authentication and encryption methods. Prometheus SNMP Exporter needs matching v3 parameters in its config.

### Verify SNMP Reachability

From your Docker host or any Linux machine on the management network, test with `snmpwalk`:

```bash
# Install snmp tools if needed
sudo apt install snmp -y

# Test SNMP v2c — should return system information
snmpwalk -v 2c -c monitoring 10.0.20.1 .1.3.6.1.2.1.1

# Test interface counters specifically
snmpwalk -v 2c -c monitoring 10.0.20.1 .1.3.6.1.2.1.2.2
```

A successful walk returns OID trees with values. If it hangs or returns no data, check:
- The firewall on the MikroTik — UDP port 161 must be reachable from your monitoring host
- The community string and subnet restriction
- That SNMP is enabled (`/snmp print`)

## Docker Compose Deployment

The Prometheus SNMP Exporter runs as a single Docker container. Create a project directory and add this configuration:

```yaml
# docker-compose.yml
services:
  snmp-exporter:
    image: prom/snmp-exporter:v0.27.0
    container_name: snmp-exporter
    restart: unless-stopped
    ports:
      - "9116:9116"
    volumes:
      - ./snmp.yml:/etc/snmp_exporter/snmp.yml:ro
    command:
      - "--config.file=/etc/snmp_exporter/snmp.yml"
```

Deploy with:

```bash
docker compose up -d
```

The exporter exposes metrics on port 9116. Verify it is running by hitting the web endpoint:

```bash
curl http://localhost:9116/metrics
```

You should see internal Prometheus process metrics — this confirms the exporter is healthy but has no device targets yet. Targets are specified as query parameters in Prometheus scrape configs, not in the exporter itself.

## Generating the SNMP Exporter Configuration

The SNMP Exporter uses a YAML configuration file (`snmp.yml`) that maps OID trees to Prometheus metric names and labels. Writing this by hand is tedious and error-prone, so the upstream project provides a **generator** that compiles a human-readable `generator.yml` into the optimized `snmp.yml`.

### Pull and Run the Generator

Use Docker to run the generator against the same image version:

```bash
# Create a generator configuration file
cat > generator.yml << 'EOF'
modules:
  if_mib:
    walk:
      - 1.3.6.1.2.1.2          # interfaces
      - 1.3.6.1.2.1.31.1.1     # ifXTable (high capacity counters)
      - 1.3.6.1.2.1.10         # transmission
    version: 2
    auth:
      community: monitoring
    lookups:
      - source_indexes: [ifIndex]
        lookup: 1.3.6.1.2.1.2.2.1.2    # ifDescr
      - source_indexes: [ifIndex]
        lookup: 1.3.6.1.2.1.31.1.1.1.1 # ifName
    overrides:
      ifType:
        type: EnumAsInfo
      ifAdminStatus:
        type: EnumAsInfo
      ifOperStatus:
        type: EnumAsInfo

  mikrotik:
    walk:
      - 1.3.6.1.4.1.14988.1    # MikroTik MIB (CPU, memory, uptime)
      - 1.3.6.1.4.1.14988.2    # MikroTik interfaces
      - 1.3.6.1.2.1.25         # host resources (storage)
    version: 2
    auth:
      community: monitoring
EOF
```

Now generate `snmp.yml`:

```bash
docker run --rm \
  -v "${PWD}:/opt" \
  prom/snmp-generator:v0.27.0 \
  generate -m /opt/generator.yml -o /opt/snmp.yml
```

This produces `snmp.yml` in the current directory — an optimized metric mapping file ready to mount into the exporter.

### Understanding the Modules

The `generator.yml` defines two modules:

- **`if_mib`** — The standard interfaces MIB (RFC 1213 / RFC 2863). Walks interface counters, descriptions, and operational status. Works on any SNMP-capable device — switches, routers, APs, NAS devices. The `lookups` section ensures Prometheus labels like `ifDescr` and `ifName` are resolved from index numbers into human-readable interface names.

- **`mikrotik`** — The MikroTik private MIB (`1.3.6.1.4.1.14988`). Provides RouterOS-specific metrics: CPU load, total memory and used memory, storage usage, uptime, and BIOS-level hardware info. This module only works on RouterOS devices.

## Prometheus Scrape Configuration

Add the SNMP targets to your `prometheus.yml` scrape configuration:

```yaml
scrape_configs:
  - job_name: snmp
    scrape_interval: 60s
    scrape_timeout: 30s
    static_configs:
      - targets:
        - 10.0.20.1       # MikroTik CCR or hAP router
        - 10.0.20.2       # MikroTik CRS switch
        - 10.0.20.5       # APC UPS
    metrics_path: /snmp
    params:
      module: [if_mib]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: snmp-exporter:9116   # Docker Compose service name

  - job_name: mikrotik_system
    scrape_interval: 120s
    scrape_timeout: 30s
    static_configs:
      - targets:
        - 10.0.20.1
    metrics_path: /snmp
    params:
      module: [mikrotik]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: snmp-exporter:9116
```

This configuration separates interface metrics (every 60 seconds) from RouterOS-specific metrics (every 120 seconds) into two jobs. Each job:
1. Sets the target IP via `__param_target` (the device to query)
2. Labels the metric with the target IP for identification
3. Redirects the scrape to the SNMP Exporter container on port 9116

If your SNMP Exporter runs on a different host, replace `snmp-exporter:9116` with `<host-ip>:9116`.

Reload Prometheus after updating the config:

```bash
curl -X POST http://localhost:9090/-/reload
```

Or restart the Prometheus container if HTTP reload is not configured. Check the Prometheus targets page (`http://prometheus:9090/targets`) to confirm both jobs show `UP`.

## Grafana Dashboard — Visualizing SNMP Metrics

With metrics flowing into Prometheus, build Grafana panels to visualize your network.

### Import a Pre-Built Dashboard

Go to **Dashboards → New → Import** in Grafana. The most popular SNMP dashboard for Prometheus is **SNMP Interface Detail** (ID: 12492). Paste the ID and select your Prometheus data source.

This dashboard provides:
- Interface traffic line charts (bits in/out per second)
- Packet rate panels per interface
- Error and discard counters
- Interface status table (up/down/admin)

### Creating a MikroTik System Panel

For RouterOS-specific metrics, create a custom panel:

1. Click **Dashboards → New Dashboard → Add Visualization**
2. Select **Prometheus** as the data source
3. Use the Prometheus **Explore** tab (`http://prometheus:9090/explore`) to discover the exact metric names from the generated `snmp.yml`. Query with label matchers to find MikroTik-specific metrics:

```promql
{__name__=~".*cpu.*",instance="10.0.20.1"}
```

Common RouterOS metrics exposed by the MikroTik module include:

- `snmp_mikrotik_cpuLoad` — CPU utilization percentage
- `snmp_mikrotik_totalMemory` and `snmp_mikrotik_usedMemory` — memory in bytes
- `snmp_mikrotik_totalHddSpace` and `snmp_mikrotik_usedHddSpace` — storage usage

For interface traffic, use the `if_mib` module metrics:

```promql
# Interface bits in per second (per interface)
rate(snmp_ifHCInOctets{ifDescr=~"ether1|sfp-plus1|bridge"}[5m]) * 8

# Interface bits out per second
rate(snmp_ifHCOutOctets{ifDescr=~"ether1|sfp-plus1|bridge"}[5m]) * 8
```

Add units → **bps (bits/sec)** in the panel configuration for human-readable axis labels.

## Advanced Configuration

### SNMP v3 for Encrypted Monitoring

For environments where network traffic traverses untrusted segments, use SNMP v3. Update the `generator.yml`:

```yaml
modules:
  if_mib_v3:
    walk:
      - 1.3.6.1.2.1.2
      - 1.3.6.1.2.1.31.1.1
    version: 3
    auth:
      username: snmp-monitor
      security_level: authPriv
      password: "your-auth-password"
      auth_protocol: SHA
      priv_protocol: AES
      priv_password: "your-priv-password"
```

Regenerate `snmp.yml` with the generator and redeploy the exporter.

### Monitoring Multiple Device Types

You can scrape multiple device types with different modules from the same exporter. Add more entries to `static_configs` in Prometheus:

```yaml
static_configs:
  - targets:
    - 10.0.20.1       # MikroTik router
    - 10.0.20.2       # MikroTik switch
    - 10.0.20.5       # APC UPS
    - 10.0.20.10      # UniFi AP
```

For UPS units, you may need additional modules like `apcups` or `ups-mib`. Add them to `generator.yml` and regenerate.

### Securing the Exporter with Traefik

If you expose the exporter endpoint externally, run it behind Traefik with authentication middleware:

```yaml
services:
  snmp-exporter:
    image: prom/snmp-exporter:v0.27.0
    container_name: snmp-exporter
    restart: unless-stopped
    expose:
      - "9116"
    volumes:
      - ./snmp.yml:/etc/snmp_exporter/snmp.yml:ro
    networks:
      - traefik-public
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.snmp.rule=Host(`snmp.gntech.me`)"
      - "traefik.http.routers.snmp.entrypoints=websecure"
      - "traefik.http.routers.snmp.tls.certresolver=letsencrypt"
      - "traefik.http.services.snmp.loadbalancer.server.port=9116"
      - "traefik.http.routers.snmp.middlewares=secHeaders@file,basicAuth@file"

networks:
  traefik-public:
    external: true
```

Remove the `ports` mapping — the exporter only needs to be reachable via the internal Docker network and Traefik.

## Verification and Troubleshooting

### Test the Exporter Endpoint

Hit the exporter's metrics endpoint with a target parameter to confirm SNMP communication:

```bash
curl 'http://localhost:9116/snmp?target=10.0.20.1&module=if_mib'
```

If successful, this returns SNMP metrics from the router wrapped in Prometheus exposition format. If it returns an empty response or errors, the issue is between the exporter and the device.

### Common Issues and Fixes

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| `Error scraping target: context deadline exceeded` | SNMP request timed out — firewall blocking UDP 161 | Check `ip firewall filter` on MikroTik, allow UDP 161 from monitoring host |
| Empty metric output | OID tree has no data — wrong module or community | Run `snmpwalk -v 2c -c monitoring 10.0.20.1` manually |
| `Unknown module` error | Module name mismatch in Prometheus config | Verify module name in `snmp.yml` matches `params.module` |
| `snmp: authentication failure` | Wrong community string or v3 credentials | Double-check community string case and subnet restriction |
| Exporter not returning MikroTik specific metrics | `mikrotik` module not in `snmp.yml` | Re-run generator with `mikrotik` module in `generator.yml` |
| Prometheus target shows DOWN | Exporter unreachable or scrape timeout | Check exporter container is running: `docker ps \| grep snmp` |

### Using snmpwalk for Diagnostics

Always verify device-side SNMP before debugging Prometheus:

```bash
# General system info
snmpwalk -v 2c -c monitoring 10.0.20.1 system

# Interface table
snmpwalk -v 2c -c monitoring 10.0.20.1 ifTable

# MikroTik private MIB
snmpwalk -v 2c -c monitoring 10.0.20.1 .1.3.6.1.4.1.14988.1
```

If `snmpwalk` works from your host but the exporter gets empty results, the issue is likely in the `snmp.yml` module definition.

## Summary

You now have a complete SNMP monitoring pipeline for your homelab network devices:

1. **SNMP enabled** on MikroTik RouterOS with v2c (or v3 for production)
2. **Prometheus SNMP Exporter** deployed as a single Docker Compose service
3. **Generated `snmp.yml`** mapping standard IF-MIB and MikroTik-specific MIBs
4. **Prometheus scrape config** targeting each network device
5. **Grafana dashboards** visualizing interface traffic, CPU, and memory

The best part: this integrates directly into your existing Prometheus and Grafana stack — no separate monitoring platform, no additional databases. Network device metrics coexist alongside container, host, and application metrics in the same dashboards and alerting rules.

Next steps to expand this stack:

- Add alerting rules in Prometheus for interface down detection and high CPU
- Import the UPS MIB module to monitor battery health and runtime
- Add SNMP monitoring to managed switches, access points, and NAS devices
- Set up a Grafana alert contact point for Telegram or email notifications on interface failures
