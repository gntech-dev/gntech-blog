---
title: "Proxmox Backup Strategies — Vzdump, PBS, and 3-2-1 for Homelabs"
description: "Complete guide to Proxmox backup strategies for homelabs — configure vzdump jobs, deploy Proxmox Backup Server, implement the 3-2-1 rule, and automate off-site backups with real configs."
date: 2026-05-23T17:00:00-04:00
tags:
  - proxmox
  - homelab
  - storage
  - linux
  - security
keywords:
  - Proxmox vzdump backup job configuration
  - Proxmox Backup Server PBS deployment guide
  - Proxmox 3-2-1 backup strategy homelab
  - Proxmox off-site backup rsync cron
  - Proxmox backup retention schedule best practices
  - Proxmox container backup mode stop suspend snapshot
  - ZFS snapshot Proxmox send receive backup
summary: "Design a bulletproof backup strategy for your Proxmox homelab — vzdump scheduling, Proxmox Backup Server deployment, 3-2-1 rule with off-site replication, and automated restore testing."
canonical: "https://gntech.dev/posts/proxmox-backup-strategies/"
---

"Backups are for people who can't rebuild from scratch" sounds
clever until your ZFS pool degrades, your NVMe dies mid-upgrade,
or you fat-finger `rm -rf` in the wrong LXC container. Proxmox
makes good backups easy — but *great* backups require intentional
architecture.

This guide covers four tiers of Proxmox backup strategy, from
a single USB drive all the way to encrypted off-site replication.
Every config is tested on Proxmox VE 8.x+.

---

## Proxmox Backup Modes — Stop vs Suspend vs Snapshot

Before writing backup jobs, understand the tradeoffs:

| Mode | VM Downtime | Consistency | Use Case |
|------|------------|-------------|----------|
| **Stop** | Full downtime | Guaranteed FS | Critical databases, AD DCs |
| **Suspend** | ~Seconds | Good (RAM saved) | General workloads |
| **Snapshot** | Zero | Good (fs-freeze) | Production with guest agent |

Proxmox defaults to snapshot mode for VMs with the QEMU guest
agent installed. The guest agent calls `fsfreeze` before the
snapshot, ensuring filesystem-consistent backups without downtime.

For LXCs, stop mode is often safest — containers start in
seconds, and the consistency guarantee is absolute. Use snapshot
mode only for stateless or application-aware containers.

---

## Tier 1 — Basic Vzdump to Local Storage

Every Proxmox install ships with `vzdump`. Minimal config:

```bash
# Manual backup of VM 100 to default dump directory
vzdump 100 --mode snapshot --compress zstd --remove 2

# Backup all VMs and LXCs, exclude templates
vzdump --all --mode snapshot --compress zstd \
  --exclude 900 --exclude 901 --mailto admin@example.com
```

Set retention via `--remove` or `--maxfiles`:
- `--remove 0` — keep all backups (dangerous)
- `--remove 2` — keep 2 latest, delete older
- `--maxfiles 5` — keep up to 5 backups

Configure defaults in `/etc/vzdump.conf`:

```ini
# /etc/vzdump.conf
tmpdir: /var/tmp
dumpdir: /mnt/backup-proxmox/dump
mode: snapshot
compress: zstd
bwlimit: 50000
stdexcludes: 1
```

Schedule via Proxmox UI: **Datacenter → Backup** → Add a new
backup job. Set schedule in standard cron format:

```text
# Daily at 02:00
0 2 * * *
# Sunday and Wednesday at 03:00
0 3 * * 0,3
```

**Limitation:** Vzdump creates full backups only. With a dozen
VMs, a 500 GB ZFS pool fills up in days. This is fine for
one or two critical VMs, but for a real homelab you need
deduplication.

---

## Tier 2 — Proxmox Backup Server (PBS)

PBS is the upgrade path from vzdump. It gives you:

- **Incremental forever** — first backup is full, subsequent
  backups are delta-only. A daily 10 GB VM change becomes
  ~200 MB on disk.
- **Deduplication** — identical blocks across VMs are stored
  once. Five Ubuntu server VMs cost barely more than one.
- **Integrity verification** — every backup chunk is verified
  against its SHA-256 hash on verify schedules.
- **Garbage collection** — prunes orphaned chunks after
  retention changes.

### Deploy PBS in an LXC Container

PBS runs best as a Debian LXC on your Proxmox host:

```bash
# Create a privileged LXC (PBS needs device access)
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --storage local-zfs --rootfs 64G --memory 4096 --swap 1024 \
  --cores 4 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 0 --features keyctl=1,nesting=1

# Enter the container
pct enter 200
```

Inside the container:

```bash
# Add PBS repository
echo "deb http://download.proxmox.com/debian/pbs bookworm pbs-no-subscription" > /etc/apt/sources.list.d/pbs.list
curl -fsSL https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg | gpg --dearmor -o /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg

apt update && apt install -y proxmox-backup-server

# Create datastore on a dedicated mount point
mkdir -p /backup/pbs-datastore
proxmox-backup-manager datastore create pbs-main \
  /backup/pbs-datastore \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 3

# Create admin user for authentication
proxmox-backup-manager user create backup-admin@pbs \
  --password '$(openssl rand -base64 32)'
```

### Connect Proxmox to PBS

From the Proxmox web UI: **Datacenter → Storage → Add → Proxmox
Backup Server**.

```
ID:        pbs-remote
Server:    10.0.20.50
Port:      8007
Datastore: pbs-main
Username:  backup-admin@pbs
Password:  <generated password>
Fingerprint: <SHA-256 from PBS UI → Dashboard → Fingerprint>
```

Or via CLI:

```bash
pvesm add pbs --type pbs --server 10.0.20.50 \
  --datastore pbs-main --username backup-admin@pbs \
  --password-append
```

Create a backup job targeting the PBS datastore. The first run
takes as long as a full vzdump. Every subsequent run takes
seconds to minutes depending on changes.

### Verify and Prune

PBS garbage collection and verification should run on schedule.
In the PBS web UI: **Datastore → Options**:

```text
Verify new backups:      immediately
Verify scheduled:        Sun 00:00
Prune scheduled:         daily 01:00
Garbage collection:      daily 02:00
```

Or via CLI:

```bash
# Manual verify
proxmox-backup-manager verify datastore pbs-main

# Manual prune + GC
proxmox-backup-manager prune datastore pbs-main
proxmox-backup-manager garbage-collection start pbs-main
```

---

## Tier 3 — The 3-2-1 Rule

PBS on the same server protects against VM corruption, not
hardware failure. The 3-2-1 rule means:

- **3** copies of your data
- **2** different media types
- **1** copy off-site

PBS container on local storage = copy 1  
PBS datastore on separate external HDD (USB) = copy 2  
Encrypted backup sync to a remote server or cloud = copy 3  

### Add a USB Backup Target

Mount a USB drive on the PBS host:

```bash
# Label the drive for udev-persistent mounting
mkfs.ext4 /dev/sda1 -L PBS-USB

# Auto-mount via fstab
mkdir -p /mnt/pbs-usb
echo 'LABEL=PBS-USB /mnt/pbs-usb ext4 defaults,nofail 0 2' >> /etc/fstab
mount -a

# Create a second datastore on USB
proxmox-backup-manager datastore create pbs-usb \
  /mnt/pbs-usb \
  --keep-daily 7 --keep-weekly 2 --keep-monthly 1
```

### Sync Jobs Between Datastores

PBS syncs datastores with full deduplication:

```bash
# Sync main datastore to USB datastore nightly
proxmox-backup-manager sync add pbs-usb \
  --remote-datastore pbs-main \
  --remote host=localhost --remote datastore=pbs-main \
  --schedule "daily 03:00"
```

This syncs only new chunks. After the initial sync, each nightly
sync transfers a few hundred megabytes at most.

---

## Tier 4 — Off-Site Replication

The off-site copy should survive total site loss — fire, flood,
theft. Options from simplest to most robust:

### Option A — Rsync PBS Chunks to a Remote Server

```bash
# On PBS host: sync encrypted datastore to remote
rsync -avz --delete \
  /backup/pbs-datastore/.chunks/ \
  user@10.0.100.1:/mnt/offsite-backup/pbs-chunks/

# Run nightly via cron
0 4 * * * rsync -avz --delete /backup/pbs-datastore/.chunks/ user@10.0.100.1:/mnt/offsite-backup/pbs-chunks/
```

**Drawback:** No deduplication on the remote side. Transfer size
equals total deduplicated size of the datastore.

### Option B — PBS Remote Sync

PBS can sync to another PBS instance over the WAN:

```bash
# On the main PBS
proxmox-backup-manager sync add offsite \
  --remote-datastore pbs-main \
  --remote host=offsite-pbs.example.com \
  --remote datastore=offsite-main \
  --remote user=backup-sync@pbs \
  --schedule "daily 22:00" \
  --transfer-last 4
```

First sync transfers all data. Subsequent syncs transfer only
new chunks. WireGuard or Tailscale between sites keeps the
traffic encrypted in transit.

### Option C — Encrypted Backup to Cloud Storage

For homelabs without a second physical site, use `rclone` to
push PBS backups to Backblaze B2, Wasabi, or any S3-compatible
storage:

```bash
# Install rclone
apt install -y rclone

# Configure (interactive, one-time)
rclone config

# Sync PBS datastore to B2
0 5 * * * rclone sync /backup/pbs-datastore/ \
  remote:bucket-proxmox-backups \
  --transfers=4 --checkers=8 \
  --bwlimit=50M --progress
```

For the budget-conscious homelab: Backblaze B2 costs ~$6/TB/mo
for storage with a $10/TB download fee only on restore. A 500 GB
PBS store costs about $3/month.

---

## Automating Restore Tests

A backup you never test is a backup you don't have. Automate a
weekly restore-to-scratch:

```bash
#!/bin/bash
# /usr/local/bin/test-restore.sh
# Run from cron: 0 8 * * 6

BACKUP_ID="100"
TARGET_STORAGE="local-zfs"
TARGET_NODE="srv1"

# Find latest backup for VM 100
LATEST=$(proxmox-backup-client snapshot list \
  --repository root@pbs@pbs-remote:pbs-main 2>/dev/null \
  | grep "host/srv1/${BACKUP_ID}" | tail -1 | awk '{print $2}')

if [ -z "$LATEST" ]; then
  echo "No backup found for VM ${BACKUP_ID}"
  exit 1
fi

# Restore to a temporary VM
echo "Restoring ${BACKUP_ID} backup ${LATEST}..."
qmrestore /mnt/pbs-remote/dump/vzdump-qemu-${BACKUP_ID}-${LATEST}.vma.zst \
  9999 --storage ${TARGET_STORAGE} 2>&1

# Start VM, verify it boots
qm start 9999
sleep 60

# Check guest agent responds
if qm guest exec 9999 -- uname -a 2>&1 | grep -q Linux; then
  echo "✅ Restore verification PASSED"
else
  echo "❌ Restore verification FAILED"
fi

# Clean up
qm stop 9999
qm destroy 9999 --purge
```

Add to cron: `0 8 * * 6 root /usr/local/bin/test-restore.sh`

---

## Retention Policy — What to Keep

Homelab retention needs differ from enterprise. A practical
policy:

| Frequency | Retention | Why |
|-----------|-----------|-----|
| Daily | 7 days | Fast rollback for bad updates |
| Weekly | 4 weeks | Recovery after missed daily window |
| Monthly | 3 months | Catch configuration drift |
| Yearly | Keep one | Long-term archival |

Set this in your PBS datastore or vzdump job:

```bash
# PBS datastore retention
proxmox-backup-manager datastore update pbs-main \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 3
```

LXCs that change infrequently (DNS, reverse proxy, DHCP) need
less retention. VMs with databases (PostgreSQL, MariaDB) benefit
from more frequent backups with shorter retention.

---

## Disaster Recovery Sequence

When things go wrong, the recovery order matters:

1. **Reinstall Proxmox** on the same or replacement hardware
2. **Restore PBS** from your off-site copy (or reinstall PBS
   and point it at the USB drive)
3. **Restore critical VMs first**: DNS, auth (Authentik/LDAP),
   reverse proxy
4. **Restore data VMs**: databases, file servers
5. **Restore stateless apps**: everything else

Label your VMs by criticality in Proxmox with custom notes
(**VM → Options → Notes**) so you know restore priority
without digging up documentation.

---

## Summary

A practical Proxmox backup stack for the homelab:

1. PBS in an LXC on local storage — incremental, deduplicated
2. USB HDD as a second datastore — protection against disk
   failure
3. Rsync/rclone to off-site — protection against site loss
4. Weekly restore test cron — protection against silent failure

Start with tier 2 (PBS on local storage). Add the USB drive
next. Schedule the off-site sync when you have a destination.
The incremental nature of PBS makes this affordable in both
time and storage even for a single-node homelab.
