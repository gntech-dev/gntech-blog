---
title: "Proxmox ZFS Snapshot Replication for Automated VM Backup"
description: "Automate Proxmox VM backups with ZFS snapshot replication using zfs send/recv, sanoid, and syncoid. Real scripts, cron schedules, and disaster recovery walkthrough."
date: 2026-06-15T07:00:00-04:00
tags:
  - proxmox
  - zfs
  - backup
  - homelab
  - automation
  - storage
keywords:
  - Proxmox ZFS snapshot replication automated backup homelab setup
  - zfs send recv Proxmox VM backup automation guide
  - Sanoid Syncoid Proxmox ZFS snapshot management
  - Automated ZFS snapshot replication offsite backup homelab
  - Proxmox backup ZFS send incremental snapshot replication
  - ZFS snapshot schedule retention policy Proxmox VMs
  - Proxmox disaster recovery ZFS replication restore
summary: "Automate Proxmox VM backups using ZFS snapshot replication. Deploy sanoid for snapshot management, syncoid for push replication, and automate the entire workflow with systemd timers."
canonical: "https://blog.gntech.me/posts/proxmox-zfs-snapshot-replication-backup/"
---

If you run Proxmox on ZFS, you already have one of the best filesystems for virtualization. But running `zfs snapshot` by hand or relying solely on Proxmox's vzdump scheduler leaves gaps — manual effort, full-dump overhead, or recovery points that are too far apart.

ZFS snapshot replication fills those gaps. Snapshots are instant (copy-on-write), near-free in disk space (only changed blocks consume space), and incremental sends make off-site or secondary-host replication practical even over slow links.

This guide covers the full stack: **sanoid** for automated snapshot creation and retention, **syncoid** for push replication to a backup host, and systemd timers to tie it together. By the end, you'll have fully automated, versioned VM/CT backups replicated to a second Proxmox host or NAS without vzdump touching a single disk.

## ZFS Snapshot Primer for Proxmox Backups

Before we automate, understand what ZFS snapshots are good for in Proxmox. When you create a VM on a ZFS pool, Proxmox creates a ZFS volume (zvol) named `tank/vm-100-disk-0`. You can snapshot that zvol instantly — it takes milliseconds regardless of size:

```bash
zfs snapshot tank/vm-100-disk-0@pre-upgrade-20260615
```

List snapshots:

```bash
zfs list -t snapshot -o name,creation,used
```

Key differences from vzdump:

| Aspect | vzdump | ZFS snapshot |
|--------|--------|-------------|
| Speed | Minutes to hours (full VM read/write) | Milliseconds (CoW metadata) |
| Space | Full VM size per backup | Only changed blocks since last snapshot |
| Granularity | Bloated or compressed archive | Per-dataset, per-VM, per-CT |
| Restore | Full VM restore only | Rollback or clone individual disks |

Snapshots don't replace vzdump for full-system restores to bare metal — but for rapid recovery, rollback after a bad update, or incremental off-site replication, nothing beats ZFS snapshots.

## Installing and Configuring Sanoid

[Sanoid](https://github.com/jimsalterjrs/sanoid) is the de-facto standard for ZFS snapshot lifecycle management. It creates snapshots on schedule and prunes old ones based on retention policies you define. Install it on your primary Proxmox host:

```bash
cd /opt
git clone https://github.com/jimsalterjrs/sanoid.git
cd sanoid
ln -s /opt/sanoid/sanoid /usr/local/sbin/sanoid
ln -s /opt/sanoid/syncoid /usr/local/sbin/syncoid
cp sanoid.defaults.conf /etc/sanoid/sanoid.defaults.conf
```

Create `/etc/sanoid/sanoid.conf` with your dataset policies:

```ini
[tank]
    recursive = yes
    use_template = production

[tank/vm-100-disk-0]
    use_template = production
    hourly = 24
    daily = 30
    monthly = 12
    yearly = 0

[tank/vm-200-disk-0]
    use_template = critical
    hourly = 48
    daily = 60
    monthly = 24

[template_production]
    hourly = 6
    daily = 14
    monthly = 6
    yearly = 0
    autosnap = yes
    autoprune = yes

[template_critical]
    hourly = 24
    daily = 30
    monthly = 12
    yearly = 0
    autosnap = yes
    autoprune = yes
```

Test the configuration:

```bash
sanoid --cron --verbose
```

Set up a systemd timer to run sanoid every 15 minutes. Create `/etc/systemd/system/sanoid.timer`:

```ini
[Unit]
Description=Sanoid ZFS snapshot timer

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

And `/etc/systemd/system/sanoid.service`:

```ini
[Unit]
Description=Sanoid ZFS snapshot management
After=zfs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sanoid --cron
Nice=19
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now sanoid.timer
```

## Setting Up Syncoid for Replication

Sanoid handles snapshots locally. Syncoid pushes them to a remote host over SSH.

### SSH Key Authentication

Generate a dedicated SSH key on the primary host for the replication user:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_syncoid -N ""
ssh-copy-id -i ~/.ssh/id_syncoid.pub root@backup-host
```

Test the connection:

```bash
ssh -i ~/.ssh/id_syncoid root@backup-host "zfs list -t filesystem"
```

### Basic One-Shot Replication

Push your VM zvol snapshots to the backup host:

```bash
syncoid --recursive tank root@backup-host:tank/backup
```

Flags explained:
- `--recursive`: replicate all child datasets
- `--no-sync-snap`: create temporary sync snapshots during transfer
- `--compress=lz4`: compress the stream (add this for WAN links)

Syncoid automatically detects which snapshots the target already has and sends only the incremental difference. The first run sends everything; subsequent runs are near-instant.

### Bandwidth Limited Replication

For WAN replication over slower links:

```bash
syncoid --recursive --compress=lz4 --bwlimit=10m \
  tank root@backup-host:tank/backup
```

The `--bwlimit` flag passes through to `pv` or `mbuffer` internally, throttling the transfer to 10 MB/s.

## Full Automation Script

Tie sanoid and syncoid together in a single script that runs on a schedule, handles errors, and notifies you on failure.

Create `/usr/local/bin/zfs-backup.sh`:

```bash
#!/bin/bash
set -euo pipefail

LOG="/var/log/zfs-backup.log"
DATE="$(date +%Y-%m-%d_%H:%M:%S)"
REMOTE="root@backup-host"
ERROR_MSG=""

# Log helper
log() {
    echo "[$DATE] $*" >> "$LOG"
}

# Create local snapshots via sanoid
log "Running sanoid --cron"
if ! /usr/local/sbin/sanoid --cron >> "$LOG" 2>&1; then
    ERROR_MSG="sanoid failed"
fi

# Replicate to backup host
log "Starting syncoid replication"
for DATASET in tank/vm-100-disk-0 tank/vm-200-disk-0 tank/vm-300-disk-0; do
    log "Replicating $DATASET"
    if ! /usr/local/sbin/syncoid --recursive --compress=lz4 \
        "$DATASET" "${REMOTE}:tank/backup/${DATASET}" >> "$LOG" 2>&1; then
        ERROR_MSG="syncoid failed for $DATASET"
        break
    fi
done

# Check zpool health on both hosts
if ! zpool status tank | grep -q "ONLINE"; then
    ERROR_MSG="${ERROR_MSG} | Primary pool health check failed"
fi

if ! ssh "$REMOTE" "zpool status tank | grep -q ONLINE"; then
    ERROR_MSG="${ERROR_MSG} | Remote pool health check failed"
fi

# Send notification on failure
if [ -n "$ERROR_MSG" ]; then
    log "ERROR: $ERROR_MSG"
    # Optional: add Telegram/email/webhook notification here
    exit 1
fi

log "Backup completed successfully"
```

Make it executable and test:

```bash
chmod +x /usr/local/bin/zfs-backup.sh
/usr/local/bin/zfs-backup.sh
```

### Systemd Timer for Daily Replication

Create `/etc/systemd/system/zfs-replication.service`:

```ini
[Unit]
Description=ZFS snapshot replication to backup host
After=zfs.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/zfs-backup.sh
Nice=10
IOSchedulingClass=idle
```

And `/etc/systemd/system/zfs-replication.timer`:

```ini
[Unit]
Description=Daily ZFS replication timer

[Timer]
OnCalendar=daily
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
systemctl daemon-reload
systemctl enable --now zfs-replication.timer
```

## Disaster Recovery

When a VM fails and you need to restore from your replicated snapshots, you have several paths.

### Option A: Restore via Syncoid Reverse

Pull the snapshot back from the backup host:

```bash
syncoid --recursive root@backup-host:tank/backup/tank/vm-100-disk-0 tank/vm-100-disk-0
```

### Option B: Manual zfs send/recv

List available snapshots on the backup host:

```bash
ssh root@backup-host "zfs list -t snapshot -r tank/backup/tank/vm-100-disk-0"
# Send the latest snapshot back over SSH
ssh root@backup-host \
  "zfs send -R tank/backup/tank/vm-100-disk-0@autosnap-2026-06-15_00:00:00-daily" \
  | zfs receive -F tank/vm-100-disk-0
```

The `-F` flag forces a rollback of the target to match the received snapshot. Use with care — it discards data on the target that is newer than the received snapshot.

### Option C: Emergency VM Restore from Replicated Dataset

If Proxmox itself is inaccessible but the backup host has the replicated zvols:

1. On the backup host, clone the snapshot to a temporary zvol
2. Attach that zvol to a recovery VM (or raw qemu)

```bash
zfs clone tank/backup/tank/vm-100-disk-0@autosnap-latest tank/restore-vm-100
# Check if the zvol is available as a block device
ls -la /dev/zvol/tank/restore-vm-100
```

### Validate Restorability

Periodically verify your snapshots are actually usable:

```bash
zfs holds -r tank@snap-before-update
zfs diff tank/vm-100-disk-0@yesterday tank/vm-100-disk-0@today
```

Conduct a quarterly restore test: bring up a temporary VM from a replicated snapshot and confirm the data is intact.

## Monitoring and Maintenance

Keep an eye on the replication pipeline with these checks:

```bash
# Check last replication log
tail -50 /var/log/zfs-backup.log

# Check sanoid activity
journalctl -u sanoid.service --since "24 hours ago"

# Verify pool health
zpool status tank

# Check replication lag (compare snapshot timestamps)
ssh root@backup-host "zfs list -t snapshot -r tank/backup" | tail -5
```

Schedule ZFS scrubs to catch silent data corruption early:

```bash
echo "0 3 * * 0 root zpool scrub tank" > /etc/cron.d/zfs-scrub
```

And verify the remote pool is scrubbing too:

```bash
ssh root@backup-host "echo '0 4 * * 0 root zpool scrub tank' > /etc/cron.d/zfs-scrub"
```

## Conclusion

ZFS snapshot replication with sanoid and syncoid transforms VM backup from a manual chore into a hands-off, reliable process. Snapshots are instant, incremental sends are bandwidth-efficient, and the retention policies ensure you never accidentally keep snapshots forever nor delete them too soon.

In my homelab, this setup runs on two Proxmox hosts — one primary with a 4x NVMe ZFS mirror pool, and a secondary with spinning disks for backup. The daily replication completes in under 5 minutes for a dozen VMs. For the three times I've needed to roll back a VM after a bad apt upgrade or a misconfigured container, having hourly snapshots on both hosts saved hours of rebuild time.

If you run Proxmox on ZFS, there's no excuse not to automate this. Install sanoid, configure your retention, point syncoid at a backup host, and let systemd handle the rest.
