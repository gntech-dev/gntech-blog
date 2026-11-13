---
title: "Audit Proxmox Backup Sync Filters and Off-Site Retention"
description: "Compare exact PBS snapshot paths across sites and preview destination pruning before changing retention."
date: 2026-11-13T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, disaster-recovery, homelab]
keywords: [PBS sync group filters, off-site backup retention, PBS prune dry run]
summary: "Use two disposable backup groups to distinguish a snapshot that never arrived from one that the off-site prune policy would remove."
cover:
  image: "/images/posts/pbs-offsite-retention/featured.webp"
  alt: "Two backup appliances on shelves lit by warm amber and cool blue light."
  caption: "AI-generated editorial artwork."
  relative: false
---

A successful sync job can copy every snapshot it was asked to copy and still leave out the one you need. A second job may then prune older recovery points at the destination. To find the difference, compare the actual snapshot paths after a controlled sync and preview the destination's prune policy against those same paths.

This lab extends the [off-site recovery design in Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/). It focuses on two backup groups that represent the old and new generations of a key rotation. You can use unencrypted disposable fixtures to test the selection and retention mechanics. If you use encrypted snapshots, keep both corresponding keys and finish with a restore from the destination. The observations below are expected results for a PBS 4.2 lab.

## 1. Seed two groups in an isolated namespace

Use two PBS instances, a source datastore with an empty namespace called `retention-source`, and a destination datastore with an empty namespace called `retention-target`. Set up a remote on the destination with independently verified TLS trust and read access to the source namespace. Use a separate lab writer on the source and keep scheduled jobs away from both lab namespaces during the exercise.

From a Linux lab client with `proxmox-backup-client`, replace the example repository with the source writer's repository. Use trusted TLS for both servers. Enter account passwords at the prompts.

```bash
set -e
umask 077
work="$(mktemp -d)"
mkdir "$work/fixture"
source_repo='lab-writer@pbs@pbs-source.example:lab-store'

for sample in old new-first new-second; do
  group="rotation-${sample%%-*}"
  printf '%s\n' "$sample" > "$work/fixture/marker.txt"
  proxmox-backup-client backup "fixture.pxar:$work/fixture" \
    --backup-id "$group" --backup-type host --crypt-mode none \
    --repository "$source_repo" --ns retention-source
  sleep 2
done
```

Record the exact snapshot paths from the source. There should be one in `host/rotation-old` and two in `host/rotation-new`. Those three paths are the baseline.

## 2. Make a filter omission visible

On the **destination** PBS, create a manual pull sync job. Select the source remote and datastore, map `retention-source` to `retention-target`, and set namespace depth to zero. Leave **Remove Vanished**, **Encrypted Only**, and **Verified Only** off for this fixture, and leave **Transfer Last** unset. In the group filter, include only the exact group `host/rotation-new`. Run the job and inspect its task log.

On the lab client, use accounts that can list both groups in their respective namespaces. Replace both repository values and run this after the job finishes.

```bash
source_read='lab-reader@pbs@pbs-source.example:lab-store'
target_read='lab-reader@pbs@pbs-target.example:lab-store'

proxmox-backup-client snapshot list --repository "$source_read" \
  --ns retention-source --output-format json > "$work/source.json"
proxmox-backup-client snapshot list --repository "$target_read" \
  --ns retention-target --output-format json > "$work/target.json"

python3 - "$work/source.json" "$work/target.json" <<'PY'
import json
import sys
from datetime import datetime, timezone

def paths(filename):
    with open(filename, encoding="utf-8") as stream:
        snapshots = json.load(stream)
    result = set()
    for snapshot in snapshots:
        stamp = datetime.fromtimestamp(snapshot["backup-time"], timezone.utc)
        result.add(f'{snapshot["backup-type"]}/{snapshot["backup-id"]}/{stamp:%Y-%m-%dT%H:%M:%SZ}')
    return result

source, target = map(paths, sys.argv[1:])
for label, entries in (("Only at source", source - target), ("Only at destination", target - source)):
    print(label)
    print("\n".join(sorted(entries)) or "(none)")
PY
```

Expect the old snapshot under **Only at source** even if the job reports success. Add an exact include for `host/rotation-old` alongside the existing new-group include. Run the same job again and repeat the comparison. Both lists should now be empty. A blank comparison is meaningful only after confirming that the source listing contains all three fixture snapshots and that the credentials can see both groups.

Group filters select groups. **Transfer Last** caps snapshots transferred per selected group. A low cap can omit earlier snapshots on the first sync even if both group filters are correct. See the [PBS sync settings](https://pbs.proxmox.com/docs/managing-remotes.html).

## 3. Preview the destination prune policy

Use a lab account authorized to prune the target namespace. Keep the preview flag in place. Run the command once per group, replacing the example repository with the destination account.

```bash
target_prune='lab-pruner@pbs@pbs-target.example:lab-store'
for group in host/rotation-old host/rotation-new; do
  proxmox-backup-client prune "$group" --repository "$target_prune" \
    --ns retention-target --keep-last 1 --dry-run
done
```

| Group | Expected preview with `keep-last 1` |
| --- | --- |
| Old generation | Keep its only snapshot. |
| New generation | Keep the newest snapshot and mark the earlier one for removal. |

Prune applies per group. An old generation stored in its own group can therefore remain indefinitely under a keep-last rule. If both key generations are in the **same** group, that rule can instead remove the final snapshot that needs the old key. Preview the actual production policy against the actual destination group layout before approving a change. Include any broader prune job whose namespace scope covers the target.

If you protect a required snapshot at the source, check its status independently at the destination. PBS does not copy the protected flag through sync. With **Remove Vanished** enabled, a pull job can also remove eligible destination snapshots that disappeared from the source. Leave it disabled for this independent-retention exercise. See the [PBS pruning and protection documentation](https://pbs.proxmox.com/docs/backup-client.html#pruning-and-removing-backups).

## 4. Record what the audit proves

Save the source and destination snapshot lists, sync job configuration, and prune preview. If the production objective is to retain one restore point from each encryption generation, name those exact paths in the record. Restore the old snapshot and the newest snapshot from the destination. Use the exact paths from the comparison.

```bash
read -r -p 'Old snapshot path: ' old_snapshot
read -r -p 'Newest snapshot path: ' new_snapshot
proxmox-backup-client restore "$old_snapshot" fixture.pxar "$work/restore-old" \
  --repository "$target_read" --ns retention-target --crypt-mode none
proxmox-backup-client restore "$new_snapshot" fixture.pxar "$work/restore-new" \
  --repository "$target_read" --ns retention-target --crypt-mode none
printf '%s\n' old | cmp - "$work/restore-old/marker.txt"
printf '%s\n' new-second | cmp - "$work/restore-new/marker.txt"
```

Both comparisons should exit successfully. For encrypted data, use `--keyfile` with the matching recovery key in each command and omit `--crypt-mode none`.

To undo the lab configuration, remove the manual sync job and have the lab owner clean up the disposable namespaces after reviewing their contents. No actual prune is needed for this exercise.

## References

- [PBS remotes and sync jobs](https://pbs.proxmox.com/docs/managing-remotes.html)
- [PBS command reference](https://pbs.proxmox.com/docs/command-syntax.html)
- [PBS prune jobs and scope](https://pbs.proxmox.com/docs/maintenance.html#prune-jobs)
