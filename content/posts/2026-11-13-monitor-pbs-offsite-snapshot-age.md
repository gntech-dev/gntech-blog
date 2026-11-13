---
title: "Monitor the Age of an Off-Site Proxmox Backup Snapshot"
description: "Query the recovery datastore directly and distinguish an old snapshot, a missing group, and a failed PBS query."
date: 2026-11-13T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, monitoring, disaster-recovery]
keywords: [PBS off-site snapshot age, Proxmox Backup monitoring, node exporter textfile]
summary: "Replace the synthetic timestamp from the monitoring lab with evidence from the PBS recovery destination."
cover:
  image: "/images/posts/pbs-offsite-snapshot-age/featured.webp"
  alt: "An analog clock beside a backup appliance on a warmly lit workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

When a sync job finishes successfully, it tells you how the job ran. The question during recovery is how recent the newest snapshot for a particular guest is at the destination. A namespace mismatch or group filter can leave one guest behind while the job keeps reporting success.

[Part 11](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) tests freshness alerts using a synthetic timestamp. This follow-up supplies a read-only collector for one expected group on the off-site PBS 4.2 datastore. It checks inventory age. Keep datastore verification, key retrieval and test restores in your recovery plan.

## 1. Query the recovery destination

Use a Linux monitoring host with the PBS client, Python 3 and Node Exporter. Enable Node Exporter's textfile collector with `--collector.textfile.directory` pointed at a directory that the collector account can write to and Node Exporter can read. Keep export access restricted to the monitoring network. Give the probe a dedicated PBS API token and grant the token and its parent user `DatastoreAudit` on the destination namespace. That role is for inventory access. Confirm it can list the expected group. Use a trusted TLS certificate or independently verify and configure `PBS_FINGERPRINT`.

Set the following values under the account that will run the collector. Put only the token secret in the password file, readable by its owner only. Use a dedicated service environment so another PBS password variable cannot override it.

```bash
export PBS_REPOSITORY='monitor@pbs!snapshot-probe@pbs-recovery.example:offsite'
export PBS_PASSWORD_FILE="$HOME/.config/pbs-monitor/token"
export PBS_NAMESPACE='recovery'
export PBS_EXPECTED_GROUP='vm/100'
export PBS_TEXTFILE='/var/lib/node_exporter/textfile_collector/pbs_offsite.prom'

proxmox-backup-client snapshot list --repository "$PBS_REPOSITORY" \
  --ns "$PBS_NAMESPACE" --output-format json
```

Replace the example datastore, namespace and group. This example queries a named namespace. It lists the namespace and matches an exact group locally, so an empty successful response can be distinguished from a failed command.

## 2. Publish the newest snapshot and the probe result

Save this as `pbs-offsite-probe.py`. It replaces one metric file atomically. On a failed query it emits the probe result and drops the snapshot sample, so an old metric line cannot stand in for a completed inventory query.

```python
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

destination = Path(os.environ["PBS_TEXTFILE"])
group_type, group_id = os.environ["PBS_EXPECTED_GROUP"].split("/", 1)
command = [
    "proxmox-backup-client", "snapshot", "list",
    "--repository", os.environ["PBS_REPOSITORY"],
    "--ns", os.environ["PBS_NAMESPACE"], "--output-format", "json",
]
try:
    result = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("expected a list")
    timestamps = [
        row["backup-time"] for row in rows
        if row["backup-type"] == group_type and row["backup-id"] == group_id
    ]
    if any(
        type(stamp) is not int or not 0 < stamp <= time.time() + 300
        for stamp in timestamps
    ):
        raise ValueError("snapshot time invalid or more than five minutes ahead")
except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
    print(f"PBS inventory probe failed: {type(exc).__name__}")
    metrics = ["gntech_pbs_offsite_query_success 0"]
else:
    metrics = [
        "gntech_pbs_offsite_query_success 1",
        f"gntech_pbs_offsite_group_present {int(bool(timestamps))}",
    ]
    if timestamps:
        metrics.append(f"gntech_pbs_offsite_snapshot_timestamp_seconds {max(timestamps)}")

metrics.append(f"gntech_pbs_offsite_probe_timestamp_seconds {int(time.time())}")
with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False, mode="w") as output:
    temporary = Path(output.name)
    output.write("\n".join(metrics) + "\n")
try:
    temporary.chmod(0o644)
    temporary.replace(destination)
finally:
    temporary.unlink(missing_ok=True)
```

Run `python3 pbs-offsite-probe.py` and inspect the metric file. Then schedule the same command every five minutes as the collector account, with the same environment and absolute paths. For systemd, set the repository, namespace, group and output path in an environment file and point `PBS_PASSWORD_FILE` to the separate token file. Keep the host clocks synchronized. The probe timestamp measures whether the script is still running, while the snapshot timestamp measures when PBS created the backup represented by the recovery point.

## 3. Alert on separate failure modes

Use these expressions in Prometheus alerting rules. Set `instance` to the actual Node Exporter scrape label. The example allows fifteen minutes for probe execution and thirty hours for a daily recovery point. Set the second threshold from your recovery objective, backup schedule and expected sync delay.

| Alert | PromQL expression |
| --- | --- |
| Probe missing or stopped | `absent(gntech_pbs_offsite_probe_timestamp_seconds{instance="recovery-monitor:9100"}) or (time() - gntech_pbs_offsite_probe_timestamp_seconds{instance="recovery-monitor:9100"} > 900)` |
| Destination query failed | `gntech_pbs_offsite_query_success{instance="recovery-monitor:9100"} == 0` |
| Expected group missing | `gntech_pbs_offsite_group_present{instance="recovery-monitor:9100"} == 0` |
| Snapshot too old | `time() - gntech_pbs_offsite_snapshot_timestamp_seconds{instance="recovery-monitor:9100"} > 108000` |

Use a short `for` interval if a transient scrape failure should page only after it persists. The probe alert also covers a stopped timer that leaves an old file behind. Check the exporter and timer first when that alert fires. A query failure points to TLS, credentials, permissions or reachability. A successful query with a missing group points to namespace, group visibility or sync selection. For an old recovery point, compare the source and destination timestamps to distinguish a stale source backup from delayed replication.

## 4. Rehearse and restore

Use a separate lab metric file and a disposable namespace. First run with a visible group and compare the exported timestamp to the newest snapshot listed on the destination. Next change the expected group to a nonexistent ID, then use an invalid repository or credential, and finally stop the scheduled probe. Check that each case produces the corresponding signal. Temporarily lower the age threshold in the lab to exercise the stale-snapshot rule without deleting anything.

Restore the original lab settings and verify that the alert resolves after a successful poll. Finish by restoring a known file or test guest from the destination, as described in [Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/). Record that result alongside the inventory evidence.

## References

- [Proxmox Backup Client usage and authentication](https://pbs.proxmox.com/docs/backup-client.html)
- [PBS snapshot listing command](https://pbs.proxmox.com/docs/proxmox-backup-client/man1.html)
- [PBS roles and token permissions](https://pbs.proxmox.com/docs/user-management.html)
- [Node Exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
