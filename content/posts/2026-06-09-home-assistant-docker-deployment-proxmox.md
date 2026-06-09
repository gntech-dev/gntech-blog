---
title: "Home Assistant Docker Deployment Guide — Self-Hosted Home Automation on Proxmox"
description: "Deploy Home Assistant Core with Docker Compose on Proxmox for complete local smart home automation. Covers Zigbee2MQTT, USB passthrough, Traefik reverse proxy, and backup strategy."
date: 2026-06-09T07:00:00-04:00
tags:
  - docker
  - selfhosting
  - homelab
  - iot
  - proxmox
keywords:
  - Home Assistant Docker deployment Proxmox homelab home automation
  - Home Assistant Core Docker Compose Zigbee2MQTT MQTT setup
  - Proxmox USB passthrough Zigbee coordinator Home Assistant
  - Traefik reverse proxy Home Assistant SSL configuration
  - Home Assistant Docker backup automation docker-compose
  - Zigbee2MQTT Docker Proxmox smart home automation integration
  - Home Assistant local voice pipeline AI automation homelab 2026
summary: "Deploy Home Assistant Core with Docker Compose on your Proxmox homelab. Complete guide covering Zigbee2MQTT, USB passthrough, MQTT broker, Traefik reverse proxy, and automated backups."
canonical: "https://blog.gntech.me/posts/home-assistant-docker-deployment-proxmox/"
---

## Why Self-Host Home Automation with Home Assistant on Docker

Home Assistant is the leading open-source home automation platform, integrating over 2,000 devices and services into a single privacy-focused dashboard. Running it locally means your lights, sensors, and automations keep working even when your internet goes down — no cloud dependency, no subscription fees, no data leaving your network.

### Home Assistant Installation Methods Compared

Home Assistant offers several installation paths:

| Method | Pros | Cons | Best For |
|--------|------|------|----------|
| **Home Assistant OS** | Full supervisor, add-ons, OTA updates | Heavy VM, less flexible | Plug-and-play users |
| **Home Assistant Supervised** | Add-ons on existing OS | Complex setup, fragile | Advanced OS users |
| **Home Assistant Core (Docker)** | Lightweight, full control, easy backups | Manual add-on management | Homelab operators |
| **Home Assistant Container** | Pre-packaged Docker image | Same as Core | Docker-first setups |

For a Proxmox homelab where you already run Docker, **Home Assistant Core in Docker** is the sweet spot. You get:

- Minimal resource footprint (~500 MB RAM at idle)
- Complete control over the stack (MQTT, Zigbee2MQTT, backups)
- Easy migration and version pinning via Docker tags
- Integration with your existing Traefik, monitoring, and backup infrastructure

### Architecture Overview

The stack runs in a single Docker Compose project on a Debian 12 VM or LXC container:

```
Internet → Traefik (SSL) → Home Assistant (port 8123)
                              ├── Mosquitto (MQTT broker, port 1883)
                              ├── Zigbee2MQTT (serial via USB)
                              └── Code Server (optional — config editor)
```

### Hardware Requirements

- **VM/LXC**: 2 vCPUs, 2 GB RAM, 20 GB disk (Debian 12)
- **Zigbee Coordinator**: Sonoff Zigbee 3.0 USB dongle (CC2652P) or Conbee II
- **Network**: Static IP on your management VLAN

## Proxmox VM Prerequisites for Home Assistant Docker

### Create the Debian 12 VM

On your Proxmox host, create a lightweight VM:

```bash
# Download Debian 12 cloud image
wget https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2

# Create VM with 2 vCPUs, 2 GB RAM, 20 GB disk
qm create 200 --name hass --cores 2 --memory 2048 --net0 virtio,bridge=vmbr0
qm importdisk 200 debian-12-generic-amd64.qcow2 local-lvm
qm set 200 --scsihw virtio-scsi-pci --scsi0 local-lvm:vm-200-disk-0
qm set 200 --ide2 local-lvm:cloudinit
qm set 200 --boot order=scsi0
qm set 200 --agent enabled=1
qm resize 200 scsi0 20G
qm start 200
```

Alternatively, use an LXC container for lighter overhead (no separate kernel):

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
pct create 200 /var/lib/vz/template/cache/debian-12-standard_12.7-1_amd64.tar.zst \
  --storage local-lvm --rootfs 20 --memory 2048 --cores 2 --net0 name=eth0,bridge=vmbr0,ip=dhcp
pct start 200
```

### Enable USB Passthrough for Zigbee Coordinator

If using a VM, attach the USB Zigbee dongle:

```bash
# On Proxmox host, find the USB device
lsusb
# Example output: Bus 001 Device 005: ID 1a86:55d4 QinHeng Electronics SONOFF Zigbee 3.0 USB dongle

# Attach to the VM
qm set 200 --usb0 host=1a86:55d4
```

For an LXC container, bind-mount the USB device:

```bash
# On Proxmox host, find the USB tty device
ls -l /dev/serial/by-id/
# Example: usb-ITEAD_SONOFF_Zigbee_3.0_USB_Dongle_V2_...

# Edit LXC config
echo 'lxc.cgroup2.devices.allow: c 188:* rwm' >> /etc/pve/lxc/200.conf
echo 'lxc.mount.entry: /dev/serial/by-id/usb-ITEAD_SONOFF_Zigbee_3.0_USB_Dongle_V2_... dev/ttyZigbee none bind,optional,create=file' >> /etc/pve/lxc/200.conf
```

### Install Docker on the VM/LXC

SSH into the new VM/LXC and install Docker:

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
```

## Docker Compose Configuration for Home Assistant Stack

Create the project directory and files:

```bash
mkdir -p /opt/homeassistant/{config,mqtt,zigbee2mqtt}
cd /opt/homeassistant
```

Create `docker-compose.yml`:

```yaml
services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    container_name: homeassistant
    restart: unless-stopped
    volumes:
      - ./config:/config
      - /etc/localtime:/etc/localtime:ro
      - /run/dbus:/run/dbus:ro
    ports:
      - "127.0.0.1:8123:8123"
    environment:
      - TZ=America/Santo_Domingo
    depends_on:
      mosquitto:
        condition: service_healthy
    networks:
      - hass-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.0"

  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    volumes:
      - ./mqtt/config:/mosquitto/config
      - ./mqtt/data:/mosquitto/data
      - ./mqtt/log:/mosquitto/log
    ports:
      - "127.0.0.1:1883:1883"
    healthcheck:
      test: ["CMD", "mosquitto_sub", "-t", "$$SYS/broker/version", "--retained-only", "-C", "1", "-W", "5"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - hass-net
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: "0.25"

  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    container_name: zigbee2mqtt
    restart: unless-stopped
    volumes:
      - ./zigbee2mqtt/data:/app/data
      - /run/udev:/run/udev:ro
    devices:
      - /dev/ttyZigbee:/dev/ttyZigbee
    environment:
      - TZ=America/Santo_Domingo
    depends_on:
      mosquitto:
        condition: service_healthy
    networks:
      - hass-net
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.5"

networks:
  hass-net:
    driver: bridge
```

Expose Home Assistant and Mosquitto only on localhost — Traefik handles external access. Zigbee2MQTT does not need port exposure.

## Mosquitto MQTT Broker Setup for Home Automation

Create the Mosquitto configuration:

```bash
mkdir -p /opt/homeassistant/mqtt/{config,data,log}
```

Create `/opt/homeassistant/mqtt/config/mosquitto.conf`:

```ini
listener 1883 127.0.0.1
allow_anonymous false
password_file /mosquitto/config/passwd
persistence true
persistence_location /mosquitto/data
log_dest file /mosquitto/log/mosquitto.log
log_type all
connection_messages true
log_timestamp true
```

Create MQTT users:

```bash
docker compose run --rm mosquitto mosquitto_passwd -c /mosquitto/config/passwd hass
# Enter password when prompted

docker compose run --rm mosquitto mosquitto_passwd -b /mosquitto/config/passwd zigbee2mqtt z2m_secret_pass
```

Restart Mosquitto to load the config:

```bash
docker compose up -d mosquitto
docker compose logs mosquitto
```

## Zigbee2MQTT Docker Integration with USB Passthrough

Zigbee2MQTT bridges your Zigbee coordinator to MQTT, allowing Home Assistant to control all Zigbee devices through a single integration.

Create `/opt/homeassistant/zigbee2mqtt/data/configuration.yaml`:

```yaml
homeassistant: true
permit_join: false
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto:1883
  user: zigbee2mqtt
  password: z2m_secret_pass
serial:
  port: /dev/ttyZigbee
  adapter: zstack
frontend:
  port: 8080
experimental:
  new_api: true
advanced:
  log_level: info
  network_key: GENERATE_ME
  pan_id: GENERATE_ME
  channel: 15
  transmit_power: 20
  report: true
device_options:
  legacy: false
```

Generate the network key and PAN ID:

```bash
# Generate 16-byte hex key for Zigbee network
openssl rand -hex 16
# Example output: 1a2b3c4d5e6f708192a3b4c5d6e7f809

# Generate PAN ID (2 bytes, between 0x0001 and 0xFFFE)
echo "0x$(openssl rand -hex 2)"
```

Replace `GENERATE_ME` in the configuration with your generated values. The `channel` setting should match the least congested 2.4 GHz channel in your environment. Channels 15, 20, and 25 are preferred because they avoid common Wi-Fi channels (1, 6, 11).

### Pairing Zigbee Devices

To pair a new device, temporarily enable joining:

```bash
# Via MQTT
mosquitto_pub -h 127.0.0.1 -u hass -p YOUR_PASSWORD \
  -t zigbee2mqtt/bridge/request/permit_join -m '{"value": true, "time": 120}'
```

Or set `permit_join: true` in the configuration, pair your devices, then set it back to `false`. Never leave permit_join enabled permanently — it is a security risk.

Verify devices appear via MQTT:

```bash
docker compose exec mosquitto mosquitto_sub -t zigbee2mqtt/# -v
```

## Home Assistant Core Configuration and Integrations

Home Assistant auto-generates a basic `configuration.yaml` on first launch. Start the stack to initialize it:

```bash
docker compose up -d
docker compose logs -f homeassistant
```

Wait for the log to show:

```
Home Assistant Core is running! Listening on http://0.0.0.0:8123
```

Access the VM IP on port 8123 (or via Traefik once configured). Complete the initial onboarding — create your user account, set your location, and name your home.

### Adding Integrations

From the Home Assistant web UI, navigate to **Settings → Devices & Services → Add Integration**:

1. **MQTT** — Click configure, enter `mosquitto` as broker, port `1883`, username `hass`, and the MQTT password. No SSL needed since Mosquitto binds to localhost.
2. **Zigbee2MQTT** — Search and add. It auto-discovers via MQTT topics. All paired Zigbee devices appear automatically.

### Essential configuration.yaml Additions

Over time, add these to `/opt/homeassistant/config/configuration.yaml`:

```yaml
# Home Assistant configuration.yaml — add to existing file

# Set a more specific time zone
homeassistant:
  latitude: !secret latitude
  longitude: !secret longitude
  unit_system: metric
  time_zone: America/Santo_Domingo
  name: GnTech Home

# Enable energy dashboard
energy:

# HTTP configuration (for Traefik proxying)
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16

# History and recorder
recorder:
  db_url: !secret recorder_db_url
  purge_keep_days: 30

# Logbook
logbook:

# System health
system_health:

# Update notifications
updater:

# Sun tracking for automations
sun:
```

### Using Secrets

Create `/opt/homeassistant/config/secrets.yaml` to keep sensitive values out of configuration.yaml:

```yaml
latitude: 18.4861
longitude: -69.9312
recorder_db_url: !env_var RECORDER_DB_URL
```

Home Assistant's `!env_var` directive reads environment variables from the Docker container. Set them under `environment:` in the compose file.

## Traefik Reverse Proxy Configuration for Home Assistant

Add Traefik labels to the homeassistant service in docker-compose.yml:

```yaml
services:
  homeassistant:
    # ... existing config ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.hass.rule=Host(`hass.yourlab.com`)"
      - "traefik.http.routers.hass.entrypoints=websecure"
      - "traefik.http.routers.hass.tls=true"
      - "traefik.http.routers.hass.tls.certresolver=letsencrypt"
      - "traefik.http.services.hass.loadbalancer.server.port=8123"
      - "traefik.http.middlewares.hass-headers.headers.customrequestheaders.X-Forwarded-For={{clientIp}}"
      - "traefik.http.routers.hass.middlewares=hass-headers@docker"
```

If using a Traefik dynamic config file instead:

```yaml
# /opt/traefik/config/homeassistant.yml
http:
  routers:
    hass:
      rule: "Host(`hass.yourlab.com`)"
      entryPoints: ["websecure"]
      tls:
        certResolver: letsencrypt
      service: hass
      middlewares:
        - hass-headers

  services:
    hass:
      loadBalancer:
        servers:
          - url: "http://homeassistant:8123"

  middlewares:
    hass-headers:
      headers:
        customRequestHeaders:
          X-Forwarded-For: "{clientIp}"
```

Add an external network to the compose file so Traefik and Home Assistant can communicate:

```yaml
networks:
  hass-net:
    driver: bridge
  traefik-net:
    external: true
    name: traefik-net

services:
  homeassistant:
    networks:
      - hass-net
      - traefik-net
```

The `http.use_x_forwarded_for` and `trusted_proxies` settings in configuration.yaml ensure Home Assistant sees the real client IP behind Traefik.

## Home Assistant Backup Automation and Recovery

### Volume Backup Script

Create `/opt/homeassistant/backup.sh`:

```bash
#!/bin/bash
# Home Assistant Docker backup script
BACKUP_DIR=/opt/homeassistant/backups
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

cd /opt/homeassistant

# Stop the stack for consistent snapshots
docker compose pause

# Archive config directories
tar czf "$BACKUP_DIR/hass-config-$TIMESTAMP.tar.gz" \
  --exclude="config/.storage/auth*" \
  config/ \
  zigbee2mqtt/data/ \
  mqtt/config/

# Backup Home Assistant database separately (can be large)
docker compose exec -T homeassistant tar czf - /config/home-assistant_v2.db \
  > "$BACKUP_DIR/hass-db-$TIMESTAMP.tar.gz"

# Resume the stack
docker compose unpause

# Keep only last 14 days of backups
find "$BACKUP_DIR" -name "hass-*.tar.gz" -mtime +14 -delete

echo "Backup completed: $TIMESTAMP"
```

Set execute permission and test:

```bash
chmod +x /opt/homeassistant/backup.sh
/opt/homeassistant/backup.sh
```

### Automated Daily Backup with Systemd Timer

```bash
cat > /etc/systemd/system/hass-backup.service << 'EOF'
[Unit]
Description=Home Assistant Docker backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/opt/homeassistant/backup.sh
WorkingDirectory=/opt/homeassistant
User=root
EOF

cat > /etc/systemd/system/hass-backup.timer << 'EOF'
[Unit]
Description=Daily Home Assistant backup

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now hass-backup.timer
```

### Restore Procedure

To restore from backup on a fresh installation:

```bash
# Stop the stack
docker compose down -v

# Restore config
tar xzf /path/to/backup/hass-config-20250609-070000.tar.gz -C /opt/homeassistant/

# Restore database
docker compose up -d homeassistant
docker compose exec -T homeassistant bash -c 'tar xzf - -C /' \
  < /path/to/backup/hass-db-20250609-070000.tar.gz

# Restart everything
docker compose up -d
```

### Docker Image Updates with Watchtower

Add Watchtower to monitor the Home Assistant Docker images:

```bash
docker run -d \
  --name watchtower \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --interval 86400 \
  --cleanup \
  --scope hass-stack
```

Tag your compose services with `com.centurylinklabs.watchtower.scope=hass-stack` to scope updates:

```yaml
services:
  homeassistant:
    labels:
      - "com.centurylinklabs.watchtower.scope=hass-stack"
  zigbee2mqtt:
    labels:
      - "com.centurylinklabs.watchtower.scope=hass-stack"
```

## Conclusion

Running Home Assistant Core with Docker on Proxmox gives you a production-grade home automation stack that is fully local, fully under your control, and easy to maintain alongside your other homelab services.

The stack cost:
- 2 vCPUs, ~1.5 GB RAM at idle (with Zigbee2MQTT and Mosquitto)
- 4 Docker containers, all on a single bridge network
- Zero cloud dependency for core functionality

From here, explore:
- **Energy dashboard** — connect Shelly or Zigbee energy monitoring plugs
- **Local voice pipeline** — run Whisper + Piper for fully offline voice control
- **ESPHome** — flash ESP32/ESP8266 devices as custom sensors and relays
- **Node-RED** — visual automation flows beyond Home Assistant's built-in automations

For official documentation, visit [home-assistant.io](https://www.home-assistant.io) and the [Zigbee2MQTT docs](https://www.zigbee2mqtt.io).
