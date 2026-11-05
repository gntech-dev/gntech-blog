---
title: "GNTECH Infrastructure Part 11: Alert When Backup Evidence Goes Stale"
description: "Build a small Prometheus monitoring lab that distinguishes old backup evidence, missing metrics, and a failed scrape."
date: 2026-11-05T06:00:00-04:00
draft: false
ShowToc: true
tags: [gntech-infrastructure, prometheus, monitoring, backups, observability]
keywords: [backup freshness, Prometheus absent, node exporter textfile collector]
summary: "Use a synthetic backup timestamp to test freshness and missing-data alerts before connecting real backup automation."
cover:
  image: "/images/posts/gntech-infrastructure-part-11/featured.webp"
  alt: "Nighttime operations desk beside a server rack with green and amber monitoring traces on two screens."
  caption: "AI-generated editorial artwork."
  relative: false
---

**Series** · [GNTECH Infrastructure Deployment Series](/gntech-infrastructure-series/) · **Part 11 of 12** · [Previous: Part 10 — Backup and Disaster Recovery](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) · Next: Part 12 — Security Validation and Operations (planned)

The off-site restore drill in Part 10 gives you recovery evidence for one point in time. Monitoring helps you notice when that evidence stops arriving. A reachable backup server can still hold an old backup, and an empty dashboard can mean the collector has stopped reporting.

This reference lab uses Prometheus 3, Node Exporter's textfile collector, Bash, and Docker Compose v2 on a Linux guest. It creates synthetic data in a dedicated project. The timestamp stands for the most recent backup that passed your acceptance criteria. A production collector must derive it from actual task and snapshot evidence. Running the lab does not validate a Proxmox backup.

## 1. Decide what each signal means

| Signal | Question it answers |
| --- | --- |
| Last accepted backup timestamp | How old is the latest recovery point that passed the chosen checks? |
| Missing timestamp metric | Has this job stopped supplying evidence? |
| Exporter scrape status | Can Prometheus collect anything from this exporter? |
| Textfile collector error | Did a metric file fail to parse? |

Use [the existing monitoring stack guide](/posts/2026-05-17-homelab-monitoring-stack/) for Grafana, Alertmanager, and logs. This installment concentrates on the freshness boundary. Grafana can display the same age expression, while Loki holds task logs for investigation. Blackbox or Uptime Kuma probes test reachability separately from backup quality.

## 2. Start a private metrics lab

Choose supported image releases for your environment and record their digests when promoting the lab. The example tags track major release lines. Only Prometheus publishes a guest port, bound to loopback.

```bash
mkdir -p ~/gntech-freshness-lab
cd ~/gntech-freshness-lab
mkdir -p textfile rules

cat > compose.yaml <<'YAML'
services:
  prometheus:
    image: prom/prometheus:v3
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./rules:/etc/prometheus/rules:ro
  exporter:
    image: prom/node-exporter:v1
    command:
      - --collector.disable-defaults
      - --collector.textfile
      - --collector.textfile.directory=/textfile
    volumes:
      - ./textfile:/textfile:ro
YAML

cat > prometheus.yml <<'YAML'
global:
  scrape_interval: 15s
  evaluation_interval: 15s
rule_files:
  - /etc/prometheus/rules/*.yml
scrape_configs:
  - job_name: backup-evidence-lab
    static_configs:
      - targets: ['exporter:9100']
YAML

cat > rules/backup.yml <<'YAML'
groups:
  - name: backup-evidence-lab
    rules:
      - alert: LabBackupEvidenceOld
        expr: time() - gntech_backup_last_accepted_timestamp_seconds{job="backup-evidence-lab",backup_job="lab"} > 300
        for: 30s
        labels:
          severity: warning
      - alert: LabBackupEvidenceMissing
        expr: absent(gntech_backup_last_accepted_timestamp_seconds{job="backup-evidence-lab",backup_job="lab"})
        for: 1m
        labels:
          severity: warning
      - alert: LabBackupExporterDown
        expr: up{job="backup-evidence-lab"} == 0
        for: 1m
        labels:
          severity: warning
      - alert: LabBackupMetricParseError
        expr: node_textfile_scrape_error{job="backup-evidence-lab"} == 1
        for: 1m
        labels:
          severity: warning
YAML
```

The five-minute threshold is deliberately short for testing. Choose production thresholds from the recovery-point objective plus the expected backup, sync, verification, and polling delays. Keep one missing-data rule per expected job or join against an explicit inventory. A generic absence expression across many jobs will miss an individual job disappearing while others remain.

## 3. Publish the timestamp atomically

Create a small lab writer. It accepts a Unix timestamp and atomically renames a temporary file in the same directory. Node Exporter reads files ending in `.prom`, so it will not read the temporary file halfway through a write.

```bash
cat > write-lab-metric.sh <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
stamp="${1:?Supply a Unix timestamp}"
[[ "$stamp" =~ ^[0-9]+$ ]] || exit 2
tmp="$(mktemp textfile/backup.tmp.XXXXXX)"
trap 'rm -f -- "$tmp"' EXIT
printf '# HELP gntech_backup_last_accepted_timestamp_seconds Last accepted backup time in Unix seconds.\n# TYPE gntech_backup_last_accepted_timestamp_seconds gauge\ngntech_backup_last_accepted_timestamp_seconds{backup_job="lab"} %s\n' "$stamp" > "$tmp"
chmod 0644 "$tmp"
mv -- "$tmp" textfile/backup.prom
BASH
chmod +x write-lab-metric.sh
./write-lab-metric.sh "$(date +%s)"
docker compose run --rm --no-deps --entrypoint /bin/promtool prometheus \
  check config /etc/prometheus/prometheus.yml
docker compose up -d
docker compose ps
```

Open `http://127.0.0.1:9090` on the guest, or use a trusted SSH tunnel if working remotely. Inspect **Targets**, then query the metric and `up{job="backup-evidence-lab"}`. Expect the scrape to be up and the timestamp age to be small after the first collection.

## 4. Exercise all three data states

Keep the Prometheus alerts page open. A rule becomes pending when its expression first matches, then firing after its `for` interval has elapsed. Allow for scrape and evaluation intervals.

```bash
# An old recovery point should trigger the age rule.
./write-lab-metric.sh "$(( $(date +%s) - 600 ))"

# Run after observing the age alert. Restore a fresh value.
./write-lab-metric.sh "$(date +%s)"
```

Run the next test only after observing the previous alert resolve.

```bash
# Missing evidence should trigger its own rule after a successful scrape.
mv textfile/backup.prom textfile/backup.disabled

# Run after observing the missing-evidence alert.
./write-lab-metric.sh "$(date +%s)"

# Run after evidence returns. A stopped exporter should trigger the scrape rule.
docker compose stop exporter

# Run after observing the exporter-down alert.
docker compose start exporter
```

Record which alerts fired and resolved, with timestamps. A missing-evidence alert may also fire during an exporter outage once the metric becomes stale. Use Alertmanager grouping and inhibition deliberately when moving beyond the lab. These rules demonstrate state transitions in Prometheus. Notification delivery requires a configured Alertmanager and receiver, and a separate test that a person actually receives the alert.

## 5. Connect real evidence and keep a runbook

For production, poll the relevant backup system on a schedule with a read-only identity. Confirm the expected guest, namespace, snapshot timestamp, task result, and verification policy. Publish the snapshot's timestamp as the metric value. Advancing it to the current polling time would hide an old backup. Keep the last accepted value on a failed check and expose a separate collector-health signal so a broken poller is distinguishable from an old recovery point.

Do not add snapshot IDs or task IDs as ever-changing metric labels. Keep detailed identifiers in the logs and link the alert's runbook to those logs. Check clock synchronization because the age expression compares two clocks.

| Failure | First investigation |
| --- | --- |
| Old evidence | Check latest accepted snapshot, failed backup/sync/verification jobs, and schedule delays. |
| Missing evidence with scrape up | Check the expected job label, file presence, and textfile parse errors. |
| Scrape down | Check exporter process, DNS, network path, and Prometheus target error. |
| Alert firing but nobody notified | Check Alertmanager connectivity, routing, silences, and receiver delivery. |

Stop the isolated lab with `docker compose down`. Its Prometheus history is disposable. Keep the files if you want to repeat the drill. When adding these rules to an existing system, preserve its known-good configuration, validate before reload, and restore that configuration if validation or expected collection fails.

Part 12 will bring the recovery, access, and monitoring checks into an operational handoff with named owners and evidence.

## Official references

- [Node Exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
- [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Prometheus query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
