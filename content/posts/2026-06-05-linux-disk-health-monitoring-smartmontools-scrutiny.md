---
title: "Linux Disk Health Monitoring with smartmontools and Scrutiny"
description: "Inspect SMART results without hiding errors, verify smartd alert delivery, and persist Scrutiny history with an explicit device mapping."
date: 2026-06-05T21:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [linux, monitoring, storage, docker, homelab]
keywords: [smartmontools disk monitoring, smartd alerts, Scrutiny Docker, smartctl exporter]
summary: "Collect disk-health evidence, test notifications, and keep monitoring separate from backup and recovery."
---

SMART monitoring can reveal storage problems, but a passing health result does not guarantee a drive will remain available. Keep independent backups and verify recovery regardless of dashboard color.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Upstream smartmontools, Scrutiny and Prometheus references reviewed on October 31, 2026. |
| Static checks | Bash syntax and embedded Compose YAML checked. |
| Runtime | No physical disk, smartd notification, Scrutiny deployment or exporter scrape tested for this revision. |
| Scope | Linux inspection workflow and a single-device SATA/SAS Scrutiny example; hardware support varies. |

## 1. Identify the actual device

On Debian or Ubuntu:

```bash
sudo apt update
sudo apt install smartmontools
sudo smartctl --scan
lsblk -o NAME,MODEL,SERIAL,SIZE,TYPE,MOUNTPOINTS
```

Match model and serial number to the physical device. USB bridges, RAID controllers, virtual disks and NVMe controllers may need different device types or passthrough. A guest VM often sees a virtual disk rather than the physical drive's SMART data.

Use the detected device and documented -d option where needed. Do not turn a missing device or failed command into a healthy result.

## 2. Preserve output and exit status

Run in Bash, selecting the actual device:

```bash
read -r -p 'Device path confirmed by scan: ' smart_device
if sudo smartctl -x "$smart_device"; then
  smart_status=0
else
  smart_status=$?
fi
printf 'smartctl exit-status bitmask: %s\n' "$smart_status"
```

smartctl's return value is a bitmask describing command problems and reported device conditions. It is not a simple “zero means safe forever, nonzero means replace immediately” verdict. Read the complete output and decode the bits using the [smartctl manual](https://github.com/smartmontools/smartmontools/blob/master/smartmontools/smartctl.8.in).

Track trends, error/self-test logs and workload symptoms alongside the health summary. Attribute names and normalization are vendor-specific. Do not assume one SSD wear attribute always means percent remaining, or apply one temperature limit to every HDD, SSD and NVMe model.

For a degraded or unreadable drive, prioritize recoverable data and investigate the storage path before adding demanding tests.

## 3. Separate self-tests from notification tests

A supported short or long self-test checks the device; it does not necessarily generate a notification when successful. Consult smartctl's reported completion estimate and read the test log afterwards. Support and duration vary by hardware.

smartd polls devices and reports configured conditions. It cannot guarantee an instant warning before every failure. Notification delivery also depends on its mail or script integration.

Preserve the existing smartd configuration before adapting it. Start with the packaged sample and installed manual:

```bash
man smartd.conf
systemctl list-unit-files 'smart*'
```

Choose the actual service unit provided by the distribution. Review existing monitoring and schedules before adding another daemon or test schedule.

For email, configure and test the delivery route, then use smartd's documented test-notification option with a real recipient. Verify receipt and daemon logs. Keep configuration directives on valid lines; inline comments after a continuation backslash can break the intended configuration.

Custom notification scripts consume smartd's documented SMARTD_* environment variables. Do not assume positional arguments contain device and event details. Test both successful delivery and a failed delivery route before depending on alerts.

## 4. Add a single-device Scrutiny dashboard

Use Linux Docker Engine on a host that can read the physical device. Choose a reviewed **omnibus** image tag or digest from [Scrutiny](https://github.com/AnalogJ/scrutiny). The following example is for a supported SATA/SAS device; it is not an NVMe/controller recipe.

Raw device access and SYS_RAWIO are sensitive privileges. Limit mappings to reviewed devices. For NVMe, consult upstream's additional capability requirements rather than granting privileged mode indiscriminately.

```bash
scrutiny_lab_dir=$(mktemp -d -t scrutiny-lab.XXXXXX)
cd "$scrutiny_lab_dir" || exit 1
read -r -p 'Reviewed Scrutiny omnibus image: ' SCRUTINY_IMAGE
read -r -p 'Confirmed SATA/SAS device path: ' SMART_DEVICE
export SCRUTINY_IMAGE SMART_DEVICE
test -b "$SMART_DEVICE" || exit 1

cat > compose.yaml <<'EOF'
services:
  scrutiny:
    image: ${SCRUTINY_IMAGE:?Set a reviewed omnibus image}
    cap_add:
      - SYS_RAWIO
    devices:
      - "${SMART_DEVICE:?Set the physical device}:${SMART_DEVICE:?Set the physical device}"
    volumes:
      - /run/udev:/run/udev:ro
      - scrutiny_config:/opt/scrutiny/config
      - scrutiny_history:/opt/scrutiny/influxdb
    ports:
      - "127.0.0.1:18081:8080"
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"

volumes:
  scrutiny_config:
  scrutiny_history:
EOF

docker compose config --quiet
docker compose up -d
docker compose logs --tail=80 scrutiny
```

The history volume targets the omnibus InfluxDB directory, not the web application directory. Review the [upstream omnibus example](https://github.com/AnalogJ/scrutiny/blob/master/docker/example.omnibus.docker-compose.yml) for the selected release. The UI is loopback-only; use a protected access method for remote viewing.

## 5. Verify collection and freshness

Trigger a collection using the documented binary, then inspect logs and the UI:

```bash
docker compose exec scrutiny /opt/scrutiny/bin/scrutiny-collector-metrics run
docker compose logs --tail=80 scrutiny
```

Open http://127.0.0.1:18081 on the Docker host. Confirm the expected model/serial, collection timestamp, and returned attributes. A running container or green dashboard with stale data is insufficient evidence.

Check the actual collector schedule for the selected image; do not assume a thirty-minute interval. Web/API and collector configuration are separate files. See the upstream [collector example](https://github.com/AnalogJ/scrutiny/blob/master/example.collector.yaml) before adding device-type overrides or remote collectors.

To stop this project while retaining configuration and history:

```bash
docker compose down
```

## 6. Use the correct Prometheus exporter

node_exporter's diskstats collector reports operating-system disk I/O statistics, not SMART attributes. The old --collector.smartmon and --collector.smartctl flags are not valid built-in collectors.

Use a dedicated [smartctl_exporter](https://github.com/prometheus-community/smartctl_exporter), or a supported external collector writing metrics for [node_exporter's textfile collector](https://github.com/prometheus/node_exporter). Inspect the actual /metrics output before choosing metric names, labels or alert rules.

Alert on failed collection and stale data as well as the device conditions you care about. Test the alert route independently from device self-tests.

## 7. Turn observations into a recovery plan

Record device identity, firmware, host, collection freshness, errors, test history, and changes over time. Compare warnings with vendor documentation and storage-system logs.

Do not use fixed age, reallocated-sector, wear, or temperature rules as universal replacement guarantees. Investigate changes and preserve data; some failures occur without useful SMART warning.

Coordinate tests with scrubs and workloads. Monitoring, filesystem integrity checks, redundancy and backups cover different failures. No combination guarantees advance warning of every disk loss.

## Continue reading

- [ZFS snapshots and recovery](/posts/2026-05-08-zfs-snapshot-strategies/) — Understand storage recovery boundaries.
- [PBS setup and restore test](/posts/2026-05-08-proxmox-backup-server-setup/) — Verify guest recovery.
- [Restic backup workflow](/posts/2026-05-19-restic-docker-backup-strategy/) — Test an independent file backup.
