---
title: "Monitor Your Last Successful Off-Site Proxmox Backup Restore"
description: "Restore a known file from an off-site PBS snapshot and publish the completion time only after its checksum matches."
date: 2026-11-14T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, monitoring, disaster-recovery]
keywords: [PBS restore drill, backup restore evidence, node exporter textfile collector]
summary: "Use a verified file restore to track when the off-site recovery path last worked."
cover:
  image: "/images/posts/pbs-restore-evidence/featured.webp"
  alt: "An operator checks a paper checklist at a warmly lit recovery workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A new snapshot at the recovery site tells you how far back you may need to go. A successful restore tells you that a specific recovery path worked at least once. Track both dates. A fresh snapshot can coexist with an expired restore credential, a missing encryption key, or a recovery host that can no longer reach the datastore.

This companion to [Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) restores a small file archive from a disposable off-site PBS namespace and compares the result with a trusted checksum. [Part 11](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) covers the Prometheus and Node Exporter setup. A passing file drill establishes evidence for that archive, credential and recovery host. Guest boot and application checks still belong in the full recovery exercise.

## 1. Prepare the test and its expected result

Use a Linux recovery host with the PBS 4.2 client, Bash and GNU coreutils. In a dedicated source namespace, back up a directory containing a single file called `marker.txt`. Record its SHA-256 digest on the source before copying the snapshot off-site. The following commands use example identifiers.

```bash
fixture="$(mktemp -d)"
printf '%s\n' 'PBS off-site restore drill fixture' > "$fixture/marker.txt"
sha256sum "$fixture/marker.txt"
proxmox-backup-client backup "drill.pxar:$fixture" \
  --repository 'writer@pbs@pbs-source.example:lab-store' \
  --ns restore-lab --backup-type host --backup-id restore-drill --crypt-mode none
```

Use your normal TLS trust procedure. Sync the lab namespace to the destination, then record the complete destination snapshot path from the PBS datastore inventory, including its timestamp. Keep the expected digest with that path in the runbook, independently of the copy being tested. For an encrypted drill, use the same fixture with your approved lab key when creating the snapshot, and supply the matching key file on the recovery host.

Use a dedicated restore account scoped to the destination lab namespace with `DatastoreReader`. The lab can use an interactive password prompt. For unattended use, configure a dedicated token and restrict both its ACL and the parent user's ACL to the lab namespace. The PBS client can read the token secret via `PBS_PASSWORD_FILE`. Confirm trust using the system CA or an independently verified fingerprint. Keep key files, passphrases and token secrets out of the collector directory and logs.

## 2. Record evidence only after verification

Set up Node Exporter's `--collector.textfile.directory` on the recovery host. Use a directory the drill account can write to and the exporter can read. Save the following as `restore-drill.sh`. Run one drill at a time for this metric file. Give the drill account a private scratch area on encrypted storage and set `TMPDIR` there if the recovered content requires it.

```bash
#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${PBS_REPOSITORY:?Set the off-site repository}"
: "${PBS_NAMESPACE:?Set the destination namespace}"
: "${PBS_SNAPSHOT:?Set the exact snapshot path}"
: "${PBS_EXPECTED_SHA256:?Set the trusted marker digest}"
: "${PBS_RESTORE_METRIC:?Set the absolute output .prom path}"

[[ "$PBS_EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]]
work="$(mktemp -d)"
temporary=''
trap 'rm -rf -- "$work"; if [[ -n "$temporary" ]]; then rm -f -- "$temporary"; fi' EXIT

options=(--repository "$PBS_REPOSITORY" --ns "$PBS_NAMESPACE")
if [[ -n "${PBS_RESTORE_KEYFILE:-}" ]]; then
  options+=(--keyfile "$PBS_RESTORE_KEYFILE")
else
  options+=(--crypt-mode none)
fi

proxmox-backup-client restore "$PBS_SNAPSHOT" drill.pxar "$work/restored" "${options[@]}"
printf '%s  %s\n' "$PBS_EXPECTED_SHA256" marker.txt |
  (cd "$work/restored" && sha256sum --check --strict)

temporary="$(mktemp "${PBS_RESTORE_METRIC}.XXXXXX")"
printf 'gntech_pbs_last_verified_restore_timestamp_seconds %s\n' "$(date +%s)" > "$temporary"
chmod 0644 "$temporary"
mv -f -- "$temporary" "$PBS_RESTORE_METRIC"
printf 'Verified restore completed for %s\n' "$PBS_SNAPSHOT"
```

Enter the values on the recovery host and run the drill. If the snapshot is encrypted, export `PBS_RESTORE_KEYFILE` with the path to its protected key first.

```bash
export PBS_REPOSITORY='reader@pbs@pbs-recovery.example:offsite'
export PBS_NAMESPACE='restore-lab'
export PBS_RESTORE_METRIC='/var/lib/node_exporter/textfile_collector/pbs_restore.prom'
read -r -p 'Destination snapshot path: ' PBS_SNAPSHOT
read -r -p 'Trusted marker SHA-256: ' PBS_EXPECTED_SHA256
export PBS_SNAPSHOT PBS_EXPECTED_SHA256
bash restore-drill.sh
```

Expect `marker.txt: OK`, then verify the metric appears on the recovery host's Node Exporter endpoint. The value is the UNIX time of the verified restore. The temporary filename does not end with `.prom`. Renaming it in the same directory makes the completed metric visible in one operation. The previous success remains visible when the next restore or checksum check fails. Check the command's exit status and log for failures as they happen.

## 3. Alert when the evidence expires

For a weekly drill with a two-day allowance, use the following expression in an alert rule. Replace `instance` with the recovery host's scrape label and choose a window that fits your recovery policy.

```promql
absent(gntech_pbs_last_verified_restore_timestamp_seconds{instance="recovery-monitor:9100"})
or
(time() - gntech_pbs_last_verified_restore_timestamp_seconds{instance="recovery-monitor:9100"} > 777600)
```

In the lab, use a separate metric path and start with no previous result. Confirm the missing-series alert, run a good restore, then run again with an incorrect but well-formed digest. The failing run should leave the success file byte-for-byte unchanged. Temporarily lower the expiry threshold to verify that existing evidence ages out. Return to the intended threshold and confirm a good drill refreshes the signal. Scrape health and alerts on failed drill executions provide separate evidence when the stored success is still recent.

A fixed fixture can test the same retained snapshot repeatedly. To cover changing backups, select a newer destination snapshot and its independently recorded digest together. Keep the exact snapshot path in the drill log and keep metric labels stable. Rotate the tested workload periodically if the goal is broader recovery coverage.

## References

- [Proxmox Backup Client usage and credentials](https://pbs.proxmox.com/docs/backup-client.html)
- [PBS client restore command](https://pbs.proxmox.com/docs/proxmox-backup-client/man1.html)
- [Node Exporter textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)
- [Prometheus query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/#absent)
