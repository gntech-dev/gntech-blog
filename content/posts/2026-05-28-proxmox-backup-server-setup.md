---
title: "Proxmox Backup Server Setup: PBS Deployment Guide for Homelab"
description: "Complete guide to deploying Proxmox Backup Server (PBS) in a homelab: LXC or VM installation, datastore configuration, backup schedules, GFS retention, encryption, remote sync, and disaster recovery testing."
date: 2026-05-28
tags:
  - proxmox
  - backup
  - homelab
  - virtualization
  - storage
keywords:
  - Proxmox Backup Server setup guide
  - PBS homelab deployment
  - Proxmox backup automation schedule
  - GFS retention policy Proxmox
  - PBS remote sync offsite backup
  - Proxmox encrypted backup configuration
  - Proxmox disaster recovery testing
summary: "Step-by-step guide to deploying Proxmox Backup Server (PBS) on a homelab — from installation to automation, encryption, remote sync, and restore testing."
canonical: "https://blog.gntech.me/posts/2026-05-28-proxmox-backup-server-setup/"
---

# Proxmox Backup Server Setup: PBS Deployment Guide for Homelab

If you're running Proxmox VE in your homelab, backups are the one thing you shouldn't cut corners on. Proxmox Backup Server (PBS) is purpose-built for PVE — it gives you incremental forever backups, deduplication, encryption, and a Web UI that integrates directly with your hypervisor. This guide walks through a production-ready PBS deployment from scratch.

## Why PBS Instead of vzdump to NFS?

The default `vzdump` + NFS approach works, but has drawbacks:

- **Full backups every time** — no incremental support, so daily backups eat terabytes fast
- **No deduplication** — five identical VMs store five copies of the same OS data
- **No built-in verification** — you don't know if a backup is restorable until you need it
- **No encryption at rest** — if your NAS gets compromised, so do your VM images

PBS solves all of these with chunk-based deduplication, incremental backups that only transfer changed blocks, client-side encryption, and integrated verification tasks.

## Deployment Options: LXC vs VM

You can run PBS as either:

| Approach | Pros | Cons |
|----------|------|------|
| **LXC container** | Lower overhead, direct ZFS access | Requires `fuse3` or bind-mount; can't host PBS on same node if it goes down |
| **VM** | Portable, snapshots, live migration, dedicated kernel | Slightly higher overhead; needs virtio-scsi + discard for thin disks |
| **Dedicated hardware** | Best isolation, separate storage controller | Overkill for most homelabs |

For a homelab, **PBS in a VM** is the sweet spot. You get snapshot capability, live migration between cluster nodes, and clean storage passthrough.

### PBS in a VM

```bash
# Create the VM (4 vCPU, 8 GB RAM, 200 GB thin disk)
qm create 200 --name pbs --memory 8192 --cores 4 --net0 virtio,bridge=vmbr0
qm set 200 --scsi0 local-lvm:200 --scsihw virtio-scsi-single
qm set 200 --boot order=scsi0
qm set 200 --ide2 media:iso/proxmox-backup-server-3.2-1.iso,media=cdrom
qm set 200 --vga std --agent 1

# Start and install
qm start 200
qm terminal 200
```

### PBS in an LXC (alternative)

```bash
pveam update
pveam download local proxmox-backup-server-3.2-1.tar.xz
pct create 200 local:vztmpl/proxmox-backup-server-3.2-1.tar.xz \
  --storage local-lvm --rootfs 200 --memory 8192 --cores 4 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features fuse=1,nesting=1

pct start 200
```

## Initial PBS Configuration

After installation, access the Web UI at `https://<pbs-ip>:8007`. The default credentials are `root@pam` with the root password you set during install.

### Create a Datastore

```bash
# From the PBS shell or SSH
proxmox-backup-manager datastore create homelab-backups \
  /backup/homelab \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 3
```

This creates a datastore with **GFS retention**: 7 daily, 4 weekly, 3 monthly backups. Adjust these based on your storage budget.

### Add Storage

```bash
# If using ZFS
zpool create backup mirror /dev/sda /dev/sdb
zfs create backup/pbs
proxmox-backup-manager datastore create homelab-backups /backup/homelab/zfs/homelab-backups

# Configure the datastore path
proxmox-backup-manager datastore update homelab-backups \
  --path /backup/homelab
```

### Create Backup User

```bash
proxmox-backup-manager user create backup@pbs \
  --password 'your-secure-password'
proxmox-backup-manager acl update /backup/homelab \
  --auth-id backup@pbs --perm DatastoreBackup
```

## Connect PVE to PBS

On each Proxmox node, add PBS as a storage target:

```bash
pvesm add pbs pbs-homelab \
  --server 10.0.20.35 \
  --datastore homelab-backups \
  --username backup@pbs \
  --password 'your-secure-password' \
  --fingerprint xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
```

Get the fingerprint from PBS Web UI → Administration → Fingerprint, or via:

```bash
proxmox-backup-manager cert info | grep Fingerprint
```

## Backup Schedules

### Per-VM Backup Jobs

```bash
# Daily backup at 02:00 for all VMs on node SRV1
pvesh create /cluster/backup \
  --mode snapshot \
  --starttime "02:00" \
  --dow "mon,tue,wed,thu,fri,sat,sun" \
  --compress zstd \
  --prune-backups "keep-daily=7,keep-weekly=4,keep-monthly=3" \
  --storage pbs-homelab \
  --node SRV1 \
  --all 1
```

Or via the Web UI: Datacenter → Backups → Add → schedule, storage, selection mode.

### Critical VM vs Non-Critical Schedule

```yaml
# Critical VMs (daily + shorter retention)
# VM 100 (DC), VM 101 (DNS), VM 200 (PBS itself — backup to second datastore)
Backup ID range: 100-110
Schedule: daily 02:00
Retention: 14 daily, 8 weekly, 6 monthly

# Non-critical VMs (alternating days to spread load)
Backup ID range: 200-999
Schedule: daily 04:00
Retention: 7 daily, 4 weekly, 3 monthly
```

### Systems: Create separate backup jobs for LXC containers:

```plaintext
Datacenter → Backups → Add
- ID: 100-199 (VMs)
- Schedule: 02:00 daily
- Node: SRV1
- Storage: pbs-homelab
- Compression: ZSTD
- Mode: Snapshot

- ID: 200-299 (LXCs)
- Schedule: 03:00 daily
- Node: SRV1
- Storage: pbs-homelab
- Compression: ZSTD
- Mode: Snapshot
```

## Encryption

PBS supports client-side encryption so the backup server never sees plain data:

```bash
# Create encryption key on the PVE host
openssl enc -aes-256-cbc -k "your-passphrase" -P -md sha256 \
  | grep key | awk '{print $3}' > /etc/pve/priv/storage/pbs-homelab.enc.key
chmod 600 /etc/pve/priv/storage/pbs-homelab.enc.key

# Update storage config to use encryption
pvesm set pbs-homelab --encryption-key /etc/pve/priv/storage/pbs-homelab.enc.key
```

Verify encryption is active:

```bash
pvesm status | grep pbs-homelab
# Look for the encrypted flag in the output
```

## Remote Sync (Offsite Backups)

PBS can sync datastores to a remote PBS instance for the 3-2-1 rule:

```bash
# On the primary PBS
proxmox-backup-manager sync-job create \
  --datastore homelab-backups \
  --remote pbs@10.0.30.10:offsite-backups \
  --remote-datastore offsite-homelab \
  --owner root@pam \
  --schedule "daily 06:00"
```

Or if your remote is over the internet (via WireGuard, for example):

```bash
proxmox-backup-manager sync-job create \
  --datastore homelab-backups \
  --remote pbs@10.0.88.2:offsite-backups \
  --remote-datastore offsite-homelab \
  --owner root@pam \
  --schedule "wed,sat 22:00" \
  --transfer-last 2
```

The `--transfer-last 2` limits sync to the last 2 backups to keep bandwidth manageable.

## Verification and Restore Testing

Backups you don't test aren't backups.

### Automated Verification

```bash
proxmox-backup-manager verify-job create \
  --datastore homelab-backups \
  --schedule "mon 03:00" \
  --owner root@pam
```

### One-Time Restore Test

```bash
# Restore a VM to a test location (doesn't overwrite original)
pvesm extract --storage pbs-homelab backup/ct/100/2026-05-28T00:00:00Z/
# Or via PBS GUI: Datastore → backup → Restore → choose target node
```

### Scripted Verification

```bash
#!/bin/bash
# /usr/local/bin/pbs-verify-all.sh
# Run monthly: 0 8 1 * * /usr/local/bin/pbs-verify-all.sh

LAST_VERIFIED=$(proxmox-backup-manager verify-job list \
  | grep -c "$(date +%Y-%m)")
if [ "$LAST_VERIFIED" -eq 0 ]; then
  proxmox-backup-manager verify-job run homelab-verify
  echo "Verification completed: $(date)" >> /var/log/pbs-verify.log
fi
```

## Monitoring

PBS exposes metrics via its API. Integrate with your monitoring stack:

```bash
# PBS API endpoint for backup status
curl -s -k \
  -H "Authorization: PVEAPIToken=backup@pam!monitor=your-token" \
  https://10.0.20.35:8007/api2/json/admin/datastore \
  | jq '.data[] | {name: .store, used: .used, avail: .avail, status: .status}'
```

Or set up a simple email notification on backup failure:

```bash
# From PBS Web UI: Administration → Notification → Mail Forwarder
# SMTP server: mail.example.com:587, user/pass
# Notification events: Backup Failed, Verification Failed, Sync Failed
```

## Disaster Recovery Checklist

When the worst happens, have a plan:

- [ ] **PBS VM dies** — restore PBS itself from its own backup (it backs up its config)
- [ ] **Primary server dies** — install PVE fresh, configure PBS storage, restore VMs
- [ ] **Both servers die** — deploy PBS on new hardware, sync back from offsite
- [ ] **Fire/theft** — use offsite sync; procure new hardware, restore from remote PBS

Test at least one full recovery quarterly:

```bash
# 1. On new hardware, install PVE
# 2. Add PBS storage
pvesm add pbs pbs-homelab \
  --server 10.0.20.35 --datastore homelab-backups \
  --username backup@pam --fingerprint F1:... --encryption-key /path/to/key

# 3. Restore critical VM first
qmrestore pbs-homelab:backup/vm/100/2026-05-28T00:00:00Z vzdump-qemu-100-2026_05_28-00_00_00.vma.zst \
  --storage local-lvm

# 4. Start and verify
qm start 100
# Check services, DNS, network connectivity
```

## Performance Tuning

PBS default settings work, but can be optimized for homelab hardware:

```bash
# Increase chunk size for large sequential workloads
proxmox-backup-manager datastore update homelab-backups \
  --chunk-size 4MiB

# Tune upload concurrency
sed -i 's/^#datastore-max-workers: 3/datastore-max-workers: 6/' \
  /etc/proxmox-backup/pbs.conf
  
sed -i 's/^#sync-max-workers: 1/sync-max-workers: 3/' \
  /etc/proxmox-backup/pbs.conf

# Disable network file sync if running on local storage
# (already default, verify with:)
grep -c "sync-file-range" /etc/proxmox-backup/pbs.conf
```

## Conclusion

Proxmox Backup Server transforms your backup strategy from "hope they work" to "know they work." The deduplication alone makes it worth it — my 3 TB of VM storage compresses to about 400 GB in PBS with daily incrementals. Combined with encryption, remote sync, and automated verification, you get enterprise-grade backup infrastructure without the enterprise price tag.

The key takeaways:
- PBS VM over LXC for portability and snapshots
- GFS retention keeps storage predictable
- Encryption is a one-time setup, worth doing from day one
- Test restores quarterly — the real test is recovery speed, not backup speed
- Remote sync completes the 3-2-1 strategy
