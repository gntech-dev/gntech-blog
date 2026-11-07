---
title: "Keep Linux Logs Across Reboots Without Letting the Journal Fill the Disk"
description: "Configure persistent systemd journal storage, set disk and age limits, verify a reboot marker, and distinguish rotation from destructive vacuuming."
date: 2026-11-07T06:00:00-04:00
draft: false
ShowToc: true
tags: [linux, systemd, logging, operations, homelab]
keywords: [persistent journal, journald retention, journalctl vacuum, Linux logs]
summary: "Keep the evidence needed for the next incident while setting an explicit storage budget for the systemd journal."
cover:
  image: "/images/posts/journald-retention/featured.webp"
  alt: "Laptop with amber light traces beside a compact server rack in a blue-lit room."
  caption: "AI-generated editorial artwork."
  relative: false
---

You restart a troubled server, open its logs, and discover that the previous boot is missing. On another guest, journal files consume more space than expected. Both problems deserve an explicit logging policy.

This procedure targets the default system journal on Debian 12/13 and Ubuntu 24.04 with systemd. It assumes sudo access, a writable local filesystem, and a planned reboot window for the final test. It is a reference procedure. The expected observations below have to be checked on your host.

## 1. Inspect storage before changing retention

Record the systemd version, current journal usage, and available boots. The merged configuration shows the main configuration and drop-ins, including vendor files that may affect your result.

```bash
systemd --version
sudo systemd-analyze cat-config systemd/journald.conf
sudo journalctl --disk-usage
sudo journalctl --list-boots
df -h /var /run
sudo ls -ld /var/log/journal /run/log/journal 2>/dev/null
```

A missing directory in the last command is possible. With `Storage=auto`, the existence of `/var/log/journal` controls whether persistence is enabled. Early boot can still use runtime storage until the journal is flushed to disk. Namespaced journals and containers with their own logging arrangements need a separate review.

Before reducing limits, preserve any records needed for an incident. Export a targeted time window to a controlled location with enough space. Journal export files can contain private data. Keep them out of public repositories.

## 2. Set a budget in one drop-in

The example gives the persistent journal a 512 MiB budget, asks it to leave 1 GiB free on its filesystem, and sets a maximum retention age of 14 days. These are sample values for a small guest. Review the current volume and disk size before applying them.

The commands stop if this exact drop-in already exists, so an existing policy is preserved for review.

```bash
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo test ! -e /etc/systemd/journald.conf.d/90-gntech-retention.conf &&
sudo sh -c 'set -C; cat > /etc/systemd/journald.conf.d/90-gntech-retention.conf' <<'CONF'
[Journal]
Storage=persistent
SystemMaxUse=512M
SystemKeepFree=1G
RuntimeMaxUse=64M
MaxRetentionSec=14day
CONF
```

Review the merged configuration again before restarting the journal service. Later-sorting drop-ins can override these settings.

```bash
sudo systemd-analyze cat-config systemd/journald.conf
sudo systemctl restart systemd-journald
sudo journalctl --flush
sudo systemctl status systemd-journald --no-pager
sudo journalctl -u systemd-journald --since '-5 minutes' --no-pager
sudo journalctl --disk-usage
```

Look for configuration parsing errors and storage failures. The persistent directory is created as needed when persistent storage is usable. If the filesystem is unavailable or unwritable, journald can fall back to runtime storage.

| Setting | Operational consequence |
| --- | --- |
| SystemMaxUse | Budget for persistent journal files. Active files and rotation granularity can prevent an immediate exact match. |
| SystemKeepFree | Space journald tries to leave free. Other writers can still consume the filesystem. |
| RuntimeMaxUse | Budget for the runtime journal under /run. |
| MaxRetentionSec | Maximum age for retained entries, subject to file rotation and cleanup. Disk pressure can remove history sooner. |

Fourteen days is an upper age policy. It does not guarantee fourteen days of evidence under a high log rate. Check the oldest available records and adjust capacity or remote retention if you need a minimum history.

## 3. Verify persistence with a reboot marker

Write a recognizable marker, synchronize journal writes, and confirm the marker is queryable before rebooting.

```bash
printf 'GNTECH journal persistence test at %s\n' "$(date -u +%FT%TZ)" |
  systemd-cat -t gntech-journal-check
sudo journalctl --sync
sudo journalctl -t gntech-journal-check --since '-5 minutes' --no-pager
sudo journalctl --list-boots
```

During your approved maintenance window, reboot normally. After reconnecting, run:

```bash
sudo journalctl --list-boots
sudo journalctl -b -1 -t gntech-journal-check --no-pager
sudo journalctl --disk-usage
```

If exactly one reboot occurred and retention has kept the record, the marker should appear in the previous boot. If several reboots occurred, select the recorded boot ID instead. A missing marker needs investigation of filesystem availability, effective configuration, and whether other cleanup removed the file.

Persistence keeps records on this guest's storage. For evidence that must survive guest or disk loss, send logs to a separately administered destination and test that delivery. The [monitoring stack guide](/posts/2026-05-17-homelab-monitoring-stack/) introduces the separate log pipeline.

## 4. Use vacuuming only when deletion is intended

Rotation closes active journal files and starts new ones. Vacuuming deletes archived files according to the supplied limits. The disk-usage report includes active files, which explains why its number can remain above a vacuum target.

The following is an optional, destructive cleanup after you have preserved needed evidence. It rotates the journal and deletes archived history to meet a size target. Deleted records cannot be recovered by increasing the limit later.

```bash
sudo journalctl --rotate --vacuum-size=512M
sudo journalctl --disk-usage
sudo journalctl --list-boots
```

Routine retention belongs in the reviewed configuration. Before adding scheduled vacuum jobs, investigate why the configured policy and observed usage differ. Separate logs written by rsyslog, application files, or Docker logging drivers have their own storage controls.

## 5. Roll back the policy and investigate growth

To remove only the drop-in introduced by this guide, run the commands below after confirming its filename. Journald returns to the remaining configuration. Previously expired or vacuumed records remain deleted.

```bash
sudo rm -- /etc/systemd/journald.conf.d/90-gntech-retention.conf
sudo systemctl restart systemd-journald
sudo systemd-analyze cat-config systemd/journald.conf
sudo journalctl --disk-usage
```

| Observation | Next check |
| --- | --- |
| Previous boot missing | Confirm persistence, filesystem writability, and the selected boot ID. |
| Little space reclaimed | Check active-file usage and whether the large files actually belong to journald. |
| History much shorter than expected | Examine log volume, free space, and competing retention settings. |
| Repeated messages dominate | Fix the failing service and inspect its rate-limit policy before changing retention. |

Record the chosen budget, oldest available boot, reboot-test result, and review date in your operations notes. For the next maintenance window, verify that the same evidence remains available and that the disk budget still fits the workload.

## Official references

- [systemd journal storage and retention settings](https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html)
- [journalctl flush, sync, rotate, and vacuum](https://www.freedesktop.org/software/systemd/man/latest/journalctl.html)
- [systemd journal service behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd-journald.service.html)
