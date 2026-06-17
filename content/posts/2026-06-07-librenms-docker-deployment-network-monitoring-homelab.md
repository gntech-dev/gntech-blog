---
title: "LibreNMS Docker Deployment — Complete Homelab Network Monitoring Guide"
description: "Deploy LibreNMS in Docker for comprehensive homelab network monitoring. SNMP autodiscovery, alerting, and graphing for MikroTik, Proxmox, Linux hosts, and switches."
date: 2026-06-07T18:30:00-04:00
tags:
  - docker
  - monitoring
  - networking
  - mikrotik
  - linux
keywords:
  - LibreNMS Docker deployment homelab SNMP monitoring guide
  - LibreNMS Docker Compose configuration network monitoring 2026
  - SNMPv3 MikroTik monitoring LibreNMS homelab network devices
  - LibreNMS alert rules email Telegram notification setup
  - Proxmox host SNMP monitoring LibreNMS hypervisor metrics
  - LibreNMS autodiscovery CIDR subnet configuration homelab
  - LibreNMS Oxidized config backup integration network device backups
summary: "Deploy LibreNMS in Docker for complete homelab network monitoring. SNMP autodiscovery, alert rules, and dashboard setup for MikroTik routers, Proxmox hosts, and Linux servers."
canonical: "https://blog.gntech.me/posts/librenms-docker-deployment-network-monitoring-homelab/"
---

## What LibreNMS Monitors and Why It Belongs in Your Homelab

LibreNMS is a fully-featured, auto-discovering network monitoring system. Think of it as PRTG or SolarWinds for the self-hosted world — except it's open source, has no device limits, and runs happily in Docker.

If your homelab has more than a handful of network devices — MikroTik routers, managed switches, Proxmox hosts, Linux servers — you've probably run into the pain of manually checking each one when something breaks. LibreNMS solves this by polling every device at configurable intervals, graphing interface utilization, CPU, memory, storage, and temperature sensors, and alerting you when thresholds cross.

Unlike Prometheus + Grafana, which requires a separate exporter per metric type, LibreNMS speaks SNMP natively. Enable SNMP on a device, add it to LibreNMS, and it automatically discovers every interface, disk, process, and sensor the device exposes.

In this guide you'll deploy the full LibreNMS Docker Compose stack, configure SNMP on MikroTik RouterOS and Linux hosts, set up autodiscovery, create alert rules, and optionally integrate Oxidized for automated config backups.

## Docker Compose Stack for LibreNMS

The official LibreNMS Docker image uses MariaDB for storage and Redis for queue and cache. Create a directory and the compose file:

```bash
mkdir -p /opt/librenms
cd /opt/librenms
nano docker-compose.yml
```

Here is the complete compose file:

```yaml
version: '3.8'

services:
  db:
    image: mariadb:10.11
    container_name: librenms-db
    restart: unless-stopped
    volumes:
      - ./data/mysql:/var/lib/mysql
    environment:
      - MYSQL_ROOT_PASSWORD=changeme_root_pass
      - MYSQL_DATABASE=librenms
      - MYSQL_USER=librenms
      - MYSQL_PASSWORD=changeme_librenms_pass
      - TZ=America/Santo_Domingo
    command:
      - "mysqld"
      - "--innodb-file-per-table=1"
      - "--innodb-buffer-pool-size=512M"
      - "--character-set-server=utf8mb4"
      - "--collation-server=utf8mb4_unicode_ci"

  redis:
    image: redis:7-alpine
    container_name: librenms-redis
    restart: unless-stopped
    volumes:
      - ./data/redis:/data

  librenms:
    image: librenms/librenms:latest
    container_name: librenms
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data/librenms:/data
    environment:
      - DB_HOST=db
      - DB_NAME=librenms
      - DB_USER=librenms
      - DB_PASSWORD=changeme_librenms_pass
      - REDIS_HOST=redis
      - TZ=America/Santo_Domingo
    depends_on:
      - db
      - redis
```

Pull and start the stack:

```bash
docker compose up -d
```

The first startup initializes the database. Check the logs until the web UI is ready:

```bash
docker compose logs -f librenms
```

## Initial Setup via Web Installer

Point your browser to `http://your-docker-host:8000/install`. The installer will guide you through:

1. Checking prerequisites (all should pass in the Docker image)
2. Database credentials — leave as defaults since they match the compose environment
3. Creating the admin user — username, password, email
4. Generating the `config.php` — the Docker image handles this through environment variables

After the installer completes, log in and go to **Settings → Global Settings → Poller Settings** to adjust the polling interval (default 5 minutes) and enable distributed polling if you run multiple pollers.

## SNMP Configuration on Target Devices

### MikroTik RouterOS

LibreNMS reads the standard SNMP MIBs that RouterOS exposes. Start with SNMPv2c for simplicity, then move to SNMPv3 for security.

**SNMPv2c (quick setup):**

```bash
# SSH into your MikroTik
/system identity set name=router-core
/snmp community set public addresses=10.0.20.0/24
/snmp set enabled=yes contact="admin@example.com" location="Rack1"
```

**SNMPv3 (recommended for production):**

```bash
/snmp set enabled=yes
/snmp community remove public
/snmp community remove private
/snmp v3 add name=librenms auth-protocol=sha auth-password=Str0ngAuthPass \
    privacy-protocol=aes privacy-password=Str0ngPrivPass group=full-access
```

### Linux and Proxmox Hosts

Install and configure `snmpd` on each host to expose system metrics:

```bash
apt update && apt install -y snmpd
```

Edit `/etc/snmp/snmpd.conf`:

```text
agentAddress udp:161

view systemonly included .1.3.6.1.2.1.1
view systemonly included .1.3.6.1.2.1.25.1

rocommunity public 10.0.20.0/24

sysLocation    "Rack1"
sysContact     admin@example.com

# Disk monitoring
disk /
disk /var/lib/vz
disk /var/log

# Interface monitoring
includeAllDisks 10%
```

Restart snmpd:

```bash
systemctl restart snmpd
systemctl enable snmpd
```

Verify connectivity from your Docker host:

```bash
docker exec librenms snmpwalk -v2c -c public 10.0.20.30 1.3.6.1.2.1.1
```

### Managed Switches (MikroTik CRS3xx)

Add SNMP on MikroTik switches the same way:

```bash
/snmp set enabled=yes
/snmp community set public addresses=10.0.20.0/24
/snmp set contact="rack@home" location="Switch-Room"
```

## Adding Devices and Autodiscovery

LibreNMS can discover devices automatically by scanning subnets. Enable it in **Settings → Global Settings → Autodiscovery**:

- Set `Autodiscovery` to **Enabled**
- Set `Autodiscovery Networks` to your homelab CIDR blocks, e.g. `10.0.20.0/24,10.0.30.0/24`

Then run discovery manually from inside the container:

```bash
docker exec librenms lnms device:discover --snmp-community=public --ping-fallback
```

This scans the configured subnets, tests SNMP reachability, and adds any device that responds.

To manually add a single device via the command line:

```bash
docker exec librenms lnms device:add --community=public --version=v2c 10.0.20.1
```

You can also use the **Devices → Add Device** form in the web UI.

### Device Groups

Organize devices by type. Go to **Devices → Device Groups** and create groups:

- **MikroTik** — match by sysDescr regex `/MikroTik|RouterOS/`
- **Linux Servers** — match by sysDescr regex `/Linux/`
- **Proxmox** — match by sysLocation or manual assignment

Groups make it easier to set per-group alert rules and build focused dashboards.

## Alerting and Notifications

LibreNMS ships with sensible default alert rules. You can also create custom ones.

### Default Alert Rules

Go to **Alerts → Alert Rules**. Pre-configured rules include:

- Device Down — ICMP unreachable or SNMP timeout
- Port Down — administrative + operational status changes
- High CPU — threshold per device type
- High Storage — disk usage above 90%

### Telegram Notifications

Create a transport in **Alerts → Alert Transports → Create Transport**:

- **Transport Type**: Telegram
- **API Key**: your bot token from BotFather
- **Chat ID**: your Telegram chat ID
- **Format**: Markdown or HTML

Then map transport to alert rules via **Alert Rules → edit → Transport → Telegram**.

### Custom Alert Rule Example

Create a rule that fires when a MikroTik CPU exceeds 80% for two polling cycles:

1. Go to **Alerts → Alert Rules → Create Alert Rule**
2. Rule name: `MikroTik High CPU`
3. Builder mode: Advanced
4. Query: `%macros.device` AND `%macros.sensor_cpu`
5. Condition: `sensor_current >= 80`
6. Interval: check every `600s` (two standard polling intervals)
7. Max alerts per day: `3`
8. Transport: select your Telegram transport

You can also use the rule builder without writing SQL:

```sql
-- Check for all devices where CPU load average exceeds 4.0
SELECT * FROM devices
LEFT JOIN device_perf ON device_perf.device_id = devices.device_id
WHERE devices.status = 1
AND device_perf.x15m > 4.0
```

## Dashboard and Graphing

LibreNMS automatically generates per-device graphs. Navigate to a device in the web UI to see:

- **Overview** — summary with health, uptime, and sysinfo
- **Ports** — traffic graphs for every interface
- **Health** — CPU, memory, storage, temperature
- **Apps** — application-level monitoring (nginx, MySQL, Docker, etc.)

To add application monitoring for Docker on a Linux host:

```bash
# On the monitored host
docker exec librenms lnms config:set apps.netsnmp-docker.enabled true
cp /opt/librenms/config/apps/docker/docker.yaml /etc/snmp/
systemctl restart snmpd
```

### Custom Dashboard

Create a custom dashboard: **Overview → Dashboards → Create Dashboard**.

Use the "Worldmap" widget to pin device locations for WAN link visibility. Use "Device Summary" widgets per group for at-a-glance health.

- Widget 1: Device Summary — all MikroTik devices
- Widget 2: Alerts — outstanding alerts
- Widget 3: Traffic Graphs — top 5 ports by utilization

## Oxidized Config Backup Integration (Optional)

Oxidized automatically backs up RouterOS and switch configurations whenever they change, and stores the history in a Git repository.

Deploy Oxidized in Docker alongside LibreNMS:

```yaml
services:
  oxidized:
    image: oxidized/oxidized:latest
    container_name: oxidized
    restart: unless-stopped
    ports:
      - "8888:8888"
    volumes:
      - ./data/oxidized:/root/.config/oxidized
    environment:
      - CONFIG_RELOAD_INTERVAL=600
      - TZ=America/Santo_Domingo
```

Add it to the same LibreNMS compose file and configure LibreNMS integration: **Settings → Global Settings → Oxidized Integration** → enable, set the Oxidized URL to `http://oxidized:8888`.

Oxidized needs a RouterOS-specific model. Create the config file `data/oxidized/config`:

```yaml
---
source:
  default: csv
  csv:
    file: /root/.config/oxidized/router.db
    delimiter: !ruby/regexp /:/
    map:
      name: 0
      model: 1
      username: 2
      password: 3
      group: 4
    gpg: false
model_map:
  routeros: mikrotik
output:
  default: git
  git:
    user: Oxidized
    email: oxidized@homelab
    repo: /root/.config/oxidized/oxidized-backups.git
```

And `data/oxidized/router.db`:

```text
router-core:mikrotik:admin:admin_pass:Routers
crs326-switch:mikrotik:admin:admin_pass:Switches
```

After setup, RouterOS config changes are automatically committed. View history in LibreNMS under **Device → Config → History**.

## Traefik Reverse Proxy Integration

Expose LibreNMS behind Traefik for HTTPS access via a subdomain like `librenms.homelab.example.com`. Add Traefik labels to the compose file:

```yaml
services:
  librenms:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.librenms.rule=Host(`librenms.homelab.example.com`)"
      - "traefik.http.routers.librenms.entrypoints=https"
      - "traefik.http.routers.librenms.tls=true"
      - "traefik.http.routers.librenms.tls.certresolver=letsencrypt"
      - "traefik.http.services.librenms.loadbalancer.server.port=8000"
      - "traefik.http.routers.librenms.middlewares=authelia@docker"
    networks:
      - traefik-net
```

Add `traefik-net` to the services and remove the ports section for LibreNMS to avoid direct HTTP exposure.

## Performance Tuning for Larger Networks

If your homelab grows beyond 50 devices, optimize the poller:

```bash
# Increase poller threads in config.php
docker exec librenms lnms config:set poller_threads 16

# Enable RRD caching through Redis
docker exec librenms lnms config:set rrdcached true
docker exec librenms lnms config:set rrdcached_server unix:/var/run/rrdcached.sock

# Disable unused discovery modules per device
docker exec librenms lnms config:set discovery_modules.os false
docker exec librenms lnms config:set discovery_modules.stp false
```

For distributed polling, run additional poller containers that connect to the same database — LibreNMS handles multi-poller natively.

## Summary

LibreNMS fills a specific gap in the homelab monitoring landscape: automatic SNMP-based discovery with zero per-metric config. Deploy it alongside your existing Prometheus + Grafana stack for network-focused observability, or use it standalone for a quick overview of every device on your network.

Start by enabling SNMP on your MikroTik RouterOS devices — the standard MIBs cover interfaces, CPU, memory, and temperature. Then expand to Linux hosts, switches, and Proxmox nodes. Once autodiscovery is running, LibreNMS finds new devices automatically, so your monitoring coverage grows with your lab.
