---
title: "Proxmox Backup Server: Setup, Retention, and a First Restore Test"
description: "Set up a PBS datastore, connect Proxmox VE, schedule retention and verification, and restore a disposable guest before relying on backups."
date: 2026-05-08T04:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [proxmox, backup, pbs, storage, homelab]
categories: [homelab, storage]
aliases:
  - /posts/2026-05-28-proxmox-backup-server-setup/
summary: "One PBS setup workflow: dedicated storage, authenticated PVE access, maintenance jobs, and an isolated restore test."
---

Proxmox Backup Server (PBS) stores deduplicated guest backups for Proxmox VE (PVE). Start with one disposable guest and prove you can recover it before expanding the job to important systems.

This guide consolidates the earlier PBS setup articles. Installation uses the official ISO and configuration uses the web interfaces; menu labels can vary by installed release.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Reviewed against the official documentation linked below on October 31, 2026. |
| Examples | Names and schedules are proposed lab settings. No capacity or speed results are claimed. |
| Runtime | Installation, backups, encryption recovery, sync, and restore have not been executed for this revision. |
| Completion gate | Record a successful backup and isolated restore on your own installed versions. |

## 1. Choose the failure boundary

Prefer separate hardware and storage when backups must survive loss of the PVE host. A PBS VM is useful for learning, but a VM and datastore on that same physical host share its failure risks. Keep another independent copy before depending on that arrangement.

Download the current PBS ISO from [Proxmox](https://www.proxmox.com/en/downloads). Follow the [installation guide](https://pbs.proxmox.com/docs/installation.html), check its requirements, and identify the installation disk carefully: the installer overwrites its target. Use a separate backup disk or filesystem and document how it is attached.

After installation, open `https://YOUR-PBS-HOST:8007`, sign in with the administrator credentials created during installation, and configure updates for the installed release and subscription status. Avoid copying an older Debian repository stanza into a newer installation.

Record PBS and PVE versions, datastore location, network access, and recovery credentials somewhere accessible if the PVE host fails.

## 2. Prepare and create the datastore

Use PBS **Administration → Storage/Disks** to inspect storage. Creating a filesystem or pool can erase its selected disks; confirm device identities before proceeding. Follow the [storage documentation](https://pbs.proxmox.com/docs/storage.html) for the chosen filesystem.

Once the dedicated filesystem is mounted, add a datastore:

| Setting | Example |
|---|---|
| Name | `main` |
| Backing path | `/mnt/datastore/main` on the prepared backup filesystem |
| Capacity | Sized from measured backup growth and retention |

Creating a directory alone does not mount a backup disk. Check that the backing filesystem is present before creating the datastore, and confirm it returns after reboot. Keep access-time behavior compatible with PBS garbage collection; do not apply the old `atime=off` tuning example.

Let PBS manage datastore contents. Do not manually remove chunks to make space.

## 3. Connect PVE with a dedicated account

In PBS, create a dedicated `backup@pbs` user with a strong password. Grant the `DatastoreBackup` role on `/datastore/main` for this example. That ACL path identifies the PBS datastore; it is different from its filesystem path. Use an administrator separately for maintenance.

In PVE, open **Datacenter → Storage → Add → Proxmox Backup Server**:

| Field | Example |
|---|---|
| Storage ID | `pbs-main` |
| Server | Your PBS hostname or address |
| Datastore | `main` |
| Username | `backup@pbs` |
| Password | Enter through the interface |
| Fingerprint | Verify against the PBS dashboard when using a self-signed certificate |

Confirm storage becomes available and inspect any authentication errors. Do not disable TLS verification to work around a mismatch. For API tokens, follow the separate privilege rules in the [user management guide](https://pbs.proxmox.com/docs/user-management.html).

### Optional client-side encryption

Use the supported encryption configuration in the [PVE PBS storage documentation](https://pve.proxmox.com/pve-docs/chapter-pvesm.html#storage_pbs). Do not substitute raw OpenSSL output for a PBS key file.

Keep the encryption key and any required recovery secrets outside the PVE cluster. Confirm an encrypted backup can be restored using that saved material before relying on it. A working storage connection alone does not prove encryption or key recovery works.

## 4. Back up one disposable guest

Create a PVE backup job targeting `pbs-main`, selecting only the test guest initially. Run it manually and inspect the task log and resulting snapshot. Give the guest a recognizable test file so you can check recovered content later.

Choose backup mode using the [PVE backup documentation](https://pve.proxmox.com/pve-docs/chapter-vzdump.html): VM and container modes have different behavior and downtime requirements. Guest-agent filesystem freezing can help consistency; databases may also need application-specific backup procedures.

Each PBS snapshot represents a complete restore point, even though deduplication and incremental transfer reduce repeated work. Savings depend on the workload; measure them after several runs.

## 5. Schedule maintenance deliberately

Use the datastore's prune, garbage collection, and verification controls. Example starting points:

| Task | Lab policy |
|---|---|
| Backup | Daily at 00:00, after the manual test succeeds |
| Prune | Keep 7 daily, 4 weekly, 3 monthly restore points |
| Garbage collection | Daily in a separate maintenance window |
| Verify | Verify new backups and periodically reverify older ones |

Pruning removes snapshot metadata; garbage collection later reclaims eligible unreferenced chunks. The grace period means space may not return immediately. Verification checks stored backup integrity and complements a restore test. See [maintenance tasks](https://pbs.proxmox.com/docs/maintenance.html).

Check actual job duration before setting overlapping schedules. Send test notifications and review failed tasks, capacity, and the age of the last successful backup.

## 6. Restore into an isolated test guest

In PVE, open the PBS storage's backup list, select the test snapshot, and choose **Restore**. Use an unused guest ID and suitable destination storage. Leave automatic startup disabled.

Before starting the restored guest, inspect its network configuration and disconnect its network interfaces or attach them to an isolated test network. Avoid duplicate IP addresses and accidental access to production services.

Boot the restored guest, check the test file and application behavior, and record the snapshot, versions, elapsed recovery time, and result. If encrypted, include a recovery exercise using the separately saved key. Delete only the disposable restored guest after confirming its ID.

## 7. Prepare for host or site loss

Document how to reinstall PBS, reconnect surviving storage using **Reuse existing datastore**, recreate access settings, and reconnect PVE. Preserve server configuration and encryption keys separately; surviving chunks alone do not recreate every setting.

For another site, use a second PBS and a supported sync job. Start with a pull job on the destination, registering the source as a remote. Confirm permissions, destination capacity, retention, and whether vanished snapshots should be removed. Test recovery from that copy too. See [remotes and sync](https://pbs.proxmox.com/docs/managing-remotes.html).

## Continue reading

- [Proxmox bridges and VLANs](/posts/2026-05-08-proxmox-networking-bridges-vlans/) — Plan access between PVE and PBS.
- [Intel AMT Serial over LAN](/posts/2026-10-30-intel-amt-sol-proxmox/) — Prepare console access for host recovery.
- [Homelab monitoring](/posts/2026-05-17-homelab-monitoring-stack/) — Add operational visibility alongside backup task reviews.
