---
title: "Linux Disk Health Monitoring with smartmontools and Scrutiny"
description: "Monitor disk health across your homelab with smartmontools and Scrutiny. Configure smartd for proactive SMART alerts, deploy the Scrutiny Docker dashboard, and catch failing drives before they fail."
date: 2026-06-05T21:00:00-04:00
tags:
  - linux
  - monitoring
  - storage
  - docker
  - homelab
keywords:
  - Linux SMART monitoring smartmontools homelab guide
  - Scrutiny Docker deployment disk health dashboard
  - smartd.conf proactive disk failure alerts email
  - NVMe SSD HDD health SMART attributes Linux
  - Multi-host disk monitoring Scrutiny collector Docker
  - Proactive hard drive failure prevention homelab
  - SMART short long self-test scheduling schedule
summary: "Monitor disk health proactively with smartmontools and Scrutiny. Covers smartd alert configuration, reading SMART attributes, and deploying a Scrutiny Docker dashboard for centralized multi-host disk health tracking."
canonical: "https://blog.gntech.me/posts/linux-disk-health-monitoring-smartmontools-scrutiny/"
---

## Why Disk Health Monitoring Matters in Your Homelab

Your homelab runs on disks. OS drives, ZFS pools, Docker volumes, media arrays — every service depends on storage that will eventually fail. The median time to failure for consumer HDDs hovers around three to five years. SSDs last longer but wear out silently. NVMe drives can fail with almost no warning.

The good news: every modern drive ships with S.M.A.R.T. (Self-Monitoring, Analysis and Reporting Technology) built in. The data is free, always available, and can give you weeks or months of warning before a catastrophic failure — if you actually read it.

This guide covers two complementary approaches to SMART monitoring in your homelab:

1. **smartmontools** — the battle-tested CLI suite. Installs in seconds, runs a daemon (`smartd`) that emails you the instant a drive reports trouble, and works on any Linux system.

2. **Scrutiny** — a self-hosted web dashboard for SMART data. Deployed via Docker, it auto-detects drives, shows historical trends, and compares your drive metrics against Backblaze's real-world failure database.

Use both: smartd for instant push alerts in the middle of the night, Scrutiny for the morning after visual inspection.

## Installing smartmontools

On any Debian or Ubuntu-based system:

```bash
sudo apt update
sudo apt install smartmontools
```

For Arch, CentOS, or other distros:

```bash
# Arch
sudo pacman -S smartmontools

# RHEL / Rocky / Alma
sudo dnf install smartmontools
```

Verify it detects your drives:

```bash
sudo smartctl --scan

# Typical output:
# /dev/sda -d scsi # /dev/sda, SCSI device
# /dev/nvme0 -d nvme # /dev/nvme0, NVMe device
```

If a drive isn't listed, the kernel may not have the driver loaded. `lsblk` and `lshw -class disk` help confirm drive identity.

### Quick Health Check

Run a one-liner to see if any drive reports a failing health status:

```bash
for d in /dev/sd?; do echo "$d: $(sudo smartctl -H $d | grep -i 'SMART overall-health' || echo 'OK - not failing')"; done
```

Output looks like:

```
/dev/sda: PASSED
/dev/sdb: PASSED
/dev/nvme0: PASSED
```

If you see **FAILING** on any drive, stop what you are doing and back up that drive immediately. Do not pass go. The drive is actively reporting imminent failure.

### Read Full SMART Attributes

```bash
# For a SATA/SAS HDD or SSD
sudo smartctl -a /dev/sda

# For an NVMe drive
sudo smartctl -a /dev/nvme0
```

## Understanding Key SMART Attributes

Not all SMART attributes are equally important. Focus on these:

| ID | Attribute | Device | What to Watch |
|----|-----------|--------|---------------|
| 5 | Reallocated_Sector_Count | HDD | Any increase means surface damage. Replace at 1+ |
| 197 | Current_Pending_Sector | HDD | Waiting to be remapped. Data at risk |
| 198 | Offline_Uncorrectable | HDD | Found bad sectors it cannot fix |
| 173 | Wear_Leveling_Count | SSD | Normalized. 100 = new, 1 = dead |
| 231 | SSD_Life_Left | SSD | Percentage remaining |
| 190 | Temperature_Celsius | Both | Over 50°C is concerning. Over 60°C is dangerous |
| 9 | Power_On_Hours | Both | Absolute lifespan indicator |
| — | Critical_Warning | NVMe | Bitmask. Any non-zero value needs investigation |
| — | Media_Errors | NVMe | Read errors. Rising = drive is degrading |

### HDD Indicators

For spinning rust, **Reallocated_Sector_Count** is the single most important attribute. Modern drives have spare sectors to swap in when part of the platter surface degrades. A value of 0 means zero bad sectors found so far. A value of 1 or higher means the drive has already started self-healing by sacrificing spares — and it will keep doing so until the spares run out.

Once reallocated sectors appear, the drive is statistically more likely to fail. Back it up and plan the replacement within weeks, not months.

### SSD / NVMe Indicators

SSDs write to NAND flash cells that wear out over time. The **Media_Wearout_Indicator** (or Wear_Leveling_Count) shows how much life remains. When it approaches the manufacturer's rated endurance, the drive will shift to read-only mode.

NVMe drives expose a `Critical_Warning` field as a bitmask. Any nonzero value means the drive controller has detected something wrong — temperature exceeded threshold, spare capacity below threshold, or reliability degraded. Run `sudo smartctl -H /dev/nvme0n1` to see the raw critical warning.

## Configuring smartd for Proactive Alerts

The `smartd` daemon runs in the background, checks your drives on a schedule, and alerts you the instant something goes wrong. This is the heart of your passive disk monitoring setup.

### Edit /etc/smartd.conf

The config file uses a single line per drive or a `DEVICESCAN` directive for automatic detection:

```bash
sudo tee /etc/smartd.conf > /dev/null << 'SMARTDEOF'
# Monitor all detected drives
DEVICESCAN -d auto \
  -H \                     # Check overall SMART health status
  -f \                     # Report any current SMART failures
  -l error \               # Monitor error log for changes
  -l selftest \            # Monitor self-test log for new failures
  -s (S/../.././02|L/../../6/03) \   # Short test daily @2am, Long test Sat @3am
  -m admin@example.com \   # Email address for alerts
  -M exec /usr/share/smartmontools/smartd-runner   # Delivery method
SMARTDEOF
```

Replace `admin@example.com` with an email address that goes to your phone or a monitoring alias.

### What Each Flag Does

- `-H`: Check overall-health. If the drive self-reports as FAILING, smartd sends an alert immediately.
- `-f`: Check for any attribute that has exceeded its failure threshold. This catches things like reallocated sectors crossing the vendor threshold.
- `-l error`: Monitors the ATA error log. If new entries appear, the drive has encountered IO errors — often a precursor to failure.
- `-l selftest`: Monitors self-test log. Tests can report errors that the health check does not catch.
- `-s (S/../.././02|L/../../6/03)`: Schedules SMART tests. Daily short test at 2 AM. Weekly long test on Saturday at 3 AM. Long tests scan the entire surface and can take hours on large HDDs.
- `-m`: Email recipient for failure notifications. Requires a working MTA (postfix, msmtp, or nullmailer).
- `-M exec`: Use the smartd runner script which handles email delivery via the local MTA.

### Enable and Start the Daemon

```bash
sudo systemctl enable smartd
sudo systemctl start smartd

# Verify it is running
sudo systemctl status smartd

# Check the logs
sudo journalctl -u smartd -n 20 --no-pager
```

### Test Your Alert Configuration

Before trusting smartd, verify emails actually work:

```bash
# First, check that mail is working at all
echo "smartd test" | mail -s "SMART Test" admin@example.com

# Run a short test on a drive
sudo smartctl -t short /dev/sda

# Wait 2 minutes for the test to complete, then check results
sudo smartctl -l selftest /dev/sda
```

If mail is not set up, smartd can also write to syslog or trigger a custom script. For homelabs without a mail infrastructure, consider pairing smartd with a simple webhook.

### Alternative: Custom Alert Script

If you do not run a mail server, configure smartd to execute a script that sends a notification via your preferred channel:

```bash
# In /etc/smartd.conf, replace -m with -M test and a script path
DEVICESCAN ... -M exec /usr/local/bin/smartd-notify.sh
```

Example webhook script:

```bash
#!/bin/bash
# /usr/local/bin/smartd-notify.sh
# Called by smartd with: $1 = type, $2 = event, $3 = device

MESSAGE="SMART alert on $3: $1 - $2"
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"$MESSAGE\"}" \
  https://hooks.example.com/smart-alert
```

Make it executable with `chmod +x /usr/local/bin/smartd-notify.sh`.

## Deploying Scrutiny — A Web Dashboard for Disk Health

Scrutiny is a self-hosted web application that reads SMART data from your drives, stores it in a SQLite database, and presents it in a clean dashboard with historical trends. It also compares your drive metrics against real-world failure data from Backblaze, giving context to raw attribute values.

The easiest way to run Scrutiny is via its all-in-one "omnibus" Docker image, which bundles the collector, web server, and database in a single container.

### Docker Compose Configuration

```yaml
services:
  scrutiny:
    image: ghcr.io/analogj/scrutiny:master-omnibus
    container_name: scrutiny
    cap_add:
      - SYS_RAWIO
    devices:
      - /dev/sda:/dev/sda
      - /dev/sdb:/dev/sdb
      - /dev/sdc:/dev/sdc
      - /dev/nvme0n1:/dev/nvme0n1
    volumes:
      - /run/udev:/run/udev:ro
      - scrutiny_config:/opt/scrutiny/config
      - scrutiny_data:/opt/scrutiny/web
    ports:
      - "8080:8080"
    restart: unless-stopped

volumes:
  scrutiny_config:
  scrutiny_data:
```

Replace the `devices:` list with the actual block devices on your host. You must explicitly pass each drive to the container because Scrutiny requires raw block device access to read SMART data.

### Configuration File

Create a `scrutiny/scrutiny.yaml` config to customize collection behavior:

```yaml
version: 1
log:
  level: info
web:
  listen:
    port: 8080
    host: 0.0.0.0
collector:
  api-endpoint: http://localhost:8080
  devices:
    - /dev/sda
    - /dev/sdb
    - /dev/nvme0n1
```

If you use a bind-mounted config directory, mount it as shown above — the container reads `scrutiny.yaml` from the config directory automatically.

### Deploy and Access

```bash
docker compose up -d
```

Open `http://your-server:8080` in your browser. Scrutiny scans all configured drives and presents a color-coded dashboard:

- **Green**: Drive is healthy
- **Yellow**: Some attributes are outside normal range
- **Red**: Drive is at risk — take action

The dashboard shows the full SMART table for each drive with color highlighting on abnormal values, along with a failure prediction score based on Backblaze's anonymized data.

## Adding Multiple Hosts to Scrutiny

A single Scrutiny web instance can collect data from multiple machines. This is useful if you have a Proxmox host, a NAS, and a Docker server that all need disk health monitoring.

### Architecture

Run the all-in-one container on your primary host (or a lightweight VM/LXC). On each additional host, run a collector-only container that sends data to the web hub.

### Collector Container

```yaml
services:
  scrutiny-collector:
    image: ghcr.io/analogj/scrutiny:master-collector
    container_name: scrutiny-collector
    cap_add:
      - SYS_RAWIO
    devices:
      - /dev/sda:/dev/sda
    volumes:
      - /run/udev:/run/udev:ro
    environment:
      COLLECTOR_API_ENDPOINT: http://10.0.20.100:8080
      COLLECTOR_HOST_ID: hostname-of-this-node
    restart: unless-stopped
```

Set `COLLECTOR_API_ENDPOINT` to the IP or hostname of the Scrutiny web hub. Set `COLLECTOR_HOST_ID` to a unique name for the node so drives are labeled correctly in the dashboard.

Collectors push data periodically — normally every 30 minutes. Within minutes of starting, the drives appear in the web dashboard grouped by host.

## Integrating with Your Existing Monitoring Stack

If you already run Prometheus and Grafana in your homelab, you can scrape SMART data directly with the Prometheus node_exporter.

### Enable SMART Metrics in node_exporter

The node_exporter has a built-in collector for SMART data. Enable it with:

```bash
# When starting node_exporter
./node_exporter --collector.diskstats --collector.smartmon --collector.smartctl
```

Or if running node_exporter as a systemd service, add the flags:

```ini
# /etc/default/node_exporter
ARGS="--collector.diskstats --collector.smartmon --collector.smartctl"
```

The key metrics exposed include:

```
smartmon_device_health_ok
smartmon_pending_sectors
smartmon_reallocated_sectors
smartmon_temperature_celsius
smartmon_power_on_hours
```

### Grafana Dashboard

Create a Grafana panel with the query:

```promql
smartmon_reallocated_sectors{device="/dev/sda"}
```

Set the threshold to 0 with a red alert color. Any value above zero triggers the alert. This gives you a second monitoring layer alongside Scrutiny and smartd.

### Combined Strategy

- **smartd**: Instant email/Slack alert when a drive fails health check
- **Scrutiny**: Morning-after dashboard review with historical trends
- **Prometheus + Grafana**: Long-term storage of SMART metrics and alerting rules

## Proactive Maintenance Practices

Monitoring is useless without action. Build these habits into your homelab routine:

- **Run weekly long self-tests**: Long surface scans catch growing defects that short tests miss. smartd handles this with the `-s` scheduling flag.
- **Replace at the first reallocated sector**: One is enough. The failure data from Backblaze and Google shows that drives with reallocated sectors fail 15x more often than clean drives.
- **Keep drives cool**: Every 10°C above 40°C roughly doubles the failure rate for HDDs. Good airflow through your drive bays matters.
- **Log all drive ages**: Track power-on hours. A drive with 40,000+ hours (roughly 4.5 years) is past the reliable zone. Start budgeting replacements.
- **Document serial numbers**: Label every drive with its serial, install date, and host. Makes replacement quick when a drive inevitably fails.
- **Test your alerts**: Every quarter, force a SMART test and verify that smartd actually sends a notification. The worst time to discover email is broken is during an actual failure.

## Conclusion

Disk health monitoring is the cheapest insurance policy for your homelab data. With a two-minute install of smartmontools and five minutes of config, you get 24/7 monitoring that alerts you when a drive is about to fail. Add Scrutiny for a visual dashboard that makes drive health obvious at a glance.

Three layers — smartd for push alerts, Scrutiny for daily review, and Prometheus/Grafana for historical tracking — cover every failure scenario. No excuses. Five minutes of setup saves you the headache of an unplanned rebuild at 2 AM.

**Related guides:**
- [ZFS Snapshot Strategies for Your Homelab](/posts/zfs-snapshot-strategies/)
- [Proxmox Backup Server Deployment Guide](/posts/proxmox-backup-server-deployment/)
- [Restic Docker Backup Strategy](/posts/restic-docker-backup-strategy/)
