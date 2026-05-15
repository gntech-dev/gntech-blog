---
title: "Proxmox Backup Server — Full Homelab Deployment Guide"
description: "Deploy Proxmox Backup Server (PBS) in your homelab — bare-metal install, LXC container, and Docker-based setup with ZFS datastores, client integration, verification, and offsite sync."
date: 2026-05-15T12:00:00-04:00
tags:
  - proxmox
  - backup
  - zfs
  - homelab
  - linux
keywords:
  - Proxmox Backup Server deployment
  - PBS homelab setup
  - Proxmox backup ZFS datastore
  - PBS LXC container install
  - Proxmox backup verification and sync
  - PBS offsite backup strategy
  - Proxmox VE client integration
summary: "Deploy Proxmox Backup Server in your homelab — bare-metal, LXC, or Docker-based setup with ZFS datastores, client config, verification schedules, and offsite sync for a complete 3-2-1 backup strategy."
canonical: "https://gntech.dev/posts/proxmox-backup-server-deployment/"
---

If you run Proxmox VE, you need Proxmox Backup Server. PBS is not
optional — it's the difference between "I lost a VM" and "I restored
from yesterday's backup in five minutes."

This guide covers every deployment method (bare-metal, LXC, Docker),
datastore setup with ZFS, client configuration, automatic verification,
pruning, and offsite sync. By the end you'll have a backup system that
runs itself.

---

## Why PBS Instead of a Simple vzdump Cron Job

Proxmox ships with `vzdump`, and a cron job to dump VMs to an NFS share
will technically work. But PBS gives you:

- **Deduplication** — identical blocks across VMs are stored once.
- **Incremental forever** — after the first full backup, PBS only
  transfers changed blocks. Subsequent backups take seconds.
- **CRC verification** — every chunk is checksummed and verified.
- **Encryption at rest** — client-side encryption before data leaves
  the Proxmox host.
- **Fast restore** — restore a single file, a directory, or a full VM
  without extracting a giant archive.

A 50 GB VM with daily changes of ~500 MB takes a 50 GB initial backup
and ~500 MB increments. With vzdump to NFS, every backup is 50 GB.
Within a week you've saved 300 GB+ with PBS.

---

## Deployment Option 1: Install PBS Directly on Proxmox Host (Not Recommended)

Installing PBS on the same host you're backing up defeats the purpose.
If the host dies, you lose both the VMs and the backups. Don't do this
unless you have absolutely no second machine.

If you must, add the PBS repository:

```bash
echo "deb http://download.proxmox.com/debian/pbs bookworm pbs-no-subscription" \
  > /etc/apt/sources.list.d/pbs.list

wget -qO- https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg \
  | gpg --dearmor -o /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg

apt update && apt install proxmox-backup-server -y
```

---

## Deployment Option 2: Dedicated PBS LXC Container (Recommended for Homelabs)

The best option for most homelabs: a lightweight LXC on a separate
Proxmox host, or a privileged container with ZFS mount passthrough.

### Step 1 — Create the LXC Container

Use the Proxmox web UI or CLI to create a container:

```bash
pct create 200 \
  local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname pbs \
  --storage local-lvm \
  --rootfs local-lvm:32 \
  --memory 4096 \
  --swap 1024 \
  --cores 4 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 0 \
  --features nesting=1,fuse=1,mount=cgroup2
```

Key flags:
- `--unprivileged 0` — PBS needs direct disk access for ZFS datastores
- `--features nesting=1` — allows mount inside the container
- `--features fuse=1` — enables FUSE support for external backup targets

### Step 2 — Pass Through the Backup Storage

On the Proxmox host, identify your backup disk:

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | grep -v loop
```

If it's a dedicated disk (e.g., `/dev/sdb`), add it to the container:

```bash
pct set 200 -mp0 /dev/sdb,mp=/mnt/backup-disk
```

For ZFS pools, use bind mounts. On the host:

```bash
zpool create backup-pool /dev/sdb
zfs set mountpoint=/mnt/backup-pool backup-pool
pct set 200 -mp0 /mnt/backup-pool,mp=/mnt/backup-pool
```

### Step 3 — Install PBS Inside the Container

```bash
pct enter 200

# Add PBS repository
echo "deb http://download.proxmox.com/debian/pbs bookworm pbs-no-subscription" \
  > /etc/apt/sources.list.d/pbs.list

wget -qO- https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg \
  | gpg --dearmor -o /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg

apt update && apt install proxmox-backup-server -y
```

PBS web interface is now available at `https://<container-ip>:8007`.

---

## Deployment Option 3: PBS in Docker (Minimal Resource Usage)

PBS can run in Docker with minimal overhead. This is useful if you
don't want a dedicated LXC but have Docker on a secondary machine.

```yaml
# docker-compose.yml
services:
  proxmox-backup-server:
    image: ayufan/proxmox-backup-server:latest
    container_name: pbs
    hostname: pbs
    restart: unless-stopped
    privileged: true
    network_mode: host
    volumes:
      - ./pbs/etc:/etc/proxmox-backup
      - ./pbs/var:/var/lib/proxmox-backup
      - ./pbs/logs:/var/log/proxmox-backup
      - /mnt/backup-pool:/mnt/datastore:rshared
    environment:
      PBS_PASSWORD: "${PBS_PASSWORD}"
      PBS_EMAIL: "admin@example.com"
    tmpfs:
      - /tmp
```

Note: PBS in Docker requires `privileged: true` and `network_mode: host`
for proper ZFS and network performance. Some features (like ZFS native
datastores inside the container) may not work — use ext4 or XFS on the
bind-mounted directory instead.

---

## Configuring ZFS Datastores

A ZFS datastore gives you compression, deduplication (at the pool
level), snapshots, and checksums on the storage side.

### Option A: ZFS on the Host, Datastore on a Directory

Set up the pool on the host, mount it into the PBS container, then
configure the datastore as a plain directory:

```bash
# On the host
zpool create backup-pool /dev/sdb
zfs set compression=zstd backup-pool
zfs set atime=off backup-pool
zfs set recordsize=1M backup-pool
```

In the PBS web UI:
1. **Administration → Storage → Add Datastore**
2. Name: `backup-store`
3. Path: `/mnt/backup-pool/backup-store`
4. Verify new backups: `Yes`
5. Set notification mode as desired

### Option B: ZFS Pool Directly in PBS (Bare Metal Only)

When PBS runs on bare metal or a VM with direct disk access:

```bash
zpool create pbs-pool /dev/sdb
zfs set compression=zstd-9 pbs-pool
zfs set atime=off pbs-pool
zfs set xattr=sa pbs-pool

# Create the datastore directory
zfs create pbs-pool/backups

proxmox-backup-manager datastore create pbs-datastore \
  /pbs-pool/backups \
  --gc-schedule "daily" \
  --verify-new \
  --verify-existing
```

Zstd compression at level 9 gives excellent ratios for VM disk images
with minimal CPU overhead on modern hardware.

---

## Configuring Proxmox VE Clients

### Step 1 — Add PBS as a Storage Target

In the Proxmox VE web UI:
1. **Datacenter → Storage → Add → Proxmox Backup Server**
2. ID: `pbs-remote`
3. Server: `<pbs-ip>` (or hostname)
4. Datastore: `backup-store`
5. Username: `root@pam` (or a dedicated PBS user)
6. Password: `<password>`
7. Fingerprint: Copy from PBS web UI → Dashboard → Fingerprint

Or via the CLI:

```bash
pvesm add pbs --server 10.0.20.50 \
  --datastore backup-store \
  --username root@pam \
  --password 'your-password' \
  --fingerprint xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
```

### Step 2 — Schedule Backups Per VM

```bash
# Backup VM 100 daily at 02:00
pvesh create /cluster/backup \
  --id backup-vm100 \
  --storage pbs-remote \
  --mode snapshot \
  --compress zstd \
  --all 0 \
  --vmid 100 \
  --schedule "02:00" \
  --repeat-missed 1 \
  --remove 1
```

Or use the web UI: **Datacenter → Backup → Add**.

### Step 3 — Verify the Connection

```bash
# List backup content from PBS
proxmox-backup-client list --backup-id 100

# Check datastore usage on PBS
proxmox-backup-manager datastore list
```

---

## Setting Up Verification and Pruning

PBS doesn't verify backups by default. Configure automatic verification
so you know your backups are restorable before you need them.

### Verification Schedule

In PBS web UI: **Datastore → Options → Verification Schedule**.

Set it to:

```
verify-new:       true           # Verify immediately after creation
verify-existing:  true           # Reverify existing backups
verify-schedule:  sun 03:00      # Weekly full verification on Sundays
```

Or via CLI:

```bash
proxmox-backup-manager datastore update backup-store \
  --verify-new \
  --verify-existing
```

Add a systemd timer for verification:

```bash
cat > /etc/systemd/system/pbs-verify.service << 'UNIT'
[Unit]
Description=Proxmox Backup Server Verification

[Service]
Type=oneshot
ExecStart=proxmox-backup-manager verify backup-store

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pbs-verify.timer << 'UNIT'
[Unit]
Description=Weekly PBS Verification

[Timer]
OnCalendar=Sun 03:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now pbs-verify.timer
```

### Pruning (Retention) Policy

Pruning removes old backups based on retention rules. This is separate
from garbage collection — pruning marks chunks for deletion, GC actually
removes them.

Recommended homelab retention:

```bash
proxmox-backup-manager prune backup-store \
  --keep-last 3 \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 2
```

| Retention | What It Saves | Storage Impact |
|-----------|--------------|----------------|
| `--keep-last 3` | 3 most recent backups | Low — ensures quick recovery |
| `--keep-daily 7` | Last 7 daily backups | ~3-7 GB/day depending on changes |
| `--keep-weekly 4` | 4 weekly backups (Sundays) | ~1-2 GB/week increment |
| `--keep-monthly 2` | 2 monthly backups | Minimal — first of month |

Configure pruning weekly to run after verification:

```bash
cat > /etc/systemd/system/pbs-prune.service << 'UNIT'
[Description=Proxmox Backup Server Pruning]

[Service]
Type=oneshot
ExecStart=proxmox-backup-manager prune backup-store \
  --keep-last 3 \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 2

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pbs-prune.timer << 'UNIT'
[Description=Weekly PBS Pruning]

[Timer]
OnCalendar=Sun 04:00
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now pbs-prune.timer
```

---

## Offsite Sync (The 3-2-1 Rule)

PBS has native sync jobs. You can sync to another PBS instance on a
second machine, a cloud VPS, or any remote server running PBS.

### Remote PBS Sync

On the primary PBS:

```bash
proxmox-backup-manager sync add \
  --remote <remote-pbs-ip>:8007 \
  --remote-datastore offsite-store \
  --local-datastore backup-store \
  --owner root@pam \
  --schedule "daily 05:00" \
  --transfer-last 3
```

This syncs the last 3 backups of every namespace to the remote PBS
every morning at 5 AM. Only changed chunks are transferred — typically
a few hundred MB for incremental backups of a 50 GB VM.

### Offsite PBS on a Cloud VPS

For the remote end, a cheap 4 GB RAM / 100 GB storage VPS works:

```bash
# On the VPS
apt install proxmox-backup-server -y

# Create a datastore with limited retention (keep less offsite)
proxmox-backup-manager datastore create offsite-store \
  /var/lib/backups \
  --keep-last 3
```

Make sure the API endpoint is secured:

```bash
# Generate a TLS certificate
proxmox-backup-manager cert generate \
  --hostname pbs.example.com

# Restrict API to TLS only
proxmox-backup-manager network set \
  --port 8007 \
  --tls 1
```

You can also use a WireGuard tunnel between the two PBS instances so
the sync traffic never touches the public internet:

```bash
# Set up WireGuard on both ends, then sync over the tunnel IP
proxmox-backup-manager sync add \
  --remote 10.0.100.2:8007 \
  --remote-datastore offsite-store \
  --local-datastore backup-store \
  --transfer-last 3 \
  --schedule "daily 05:00"
```

---

## Client-Side Encryption

Encrypt backups before they leave the Proxmox host. PBS supports
encryption keys per backup namespace.

### Generate an Encryption Key

```bash
proxmox-backup-client encrypt-key \
  --kdf my-backup-key.json
```

The key file contains the encryption key and a recovery password. Store
this key file somewhere safe — without it, your encrypted backups are
unrecoverable.

### Register the Key with PBS

In the web UI: **Administration → Encryption Keys → Add**.

Or on the Proxmox VE host:

```bash
proxmox-backup-client key add \
  --keyfile /root/my-backup-key.json \
  --backup-id 100
```

Now all backups for VM 100 will be encrypted on the client before
transmission. PBS stores only encrypted blobs:

```bash
# On PBS, you'll see encrypted chunks
ls /mnt/backup-pool/backups/ns/100/
# encrypt.blob  index.json.blob  ...
```

If someone steals the PBS disk, they get encrypted data. Only the
key file on the Proxmox host can decrypt it.

---

## Restoring from PBS

### Full VM Restore

From the Proxmox VE web UI:
1. **Select the backup → Restore**
2. Choose target storage
3. Click **Restore**

From CLI:

```bash
# List available backups
pvesm list pbs-remote --vmid 100

# Restore VM 100 from the latest backup
pvesm restore pbs-remote 100 latest \
  --storage local-zfs
```

### File-Level Restore (Without Restoring the VM)

PBS supports FUSE-based mount for extracting individual files:

```bash
# Mount the backup as a filesystem
proxmox-backup-client mount \
  /backup-store/ns/100/latest \
  /mnt/restore

# Browse and copy files
cp /mnt/restor/etc/nginx/sites-enabled/mysite.conf .
cp -r /mnt/restore/var/www/html ./restored-html

# Unmount when done
proxmox-backup-client umount /mnt/restore
```

This works for both file-level backups (CT containers) and block-level
backups (VMs — you get a block device that can be mounted with
`qemu-nbd`).

### Restore a Single Container

```bash
pct restore 101 /var/lib/vzdump/dump/vzdump-lxc-101-2026_05_14-00_00_00.tar.zst \
  --storage local-zfs
```

Or restore from PBS using the backup content:

```bash
pct restore 101 backup-store:backup/101/2026-05-14T00:00:00Z \
  --storage local-zfs
```

---

## Monitoring and Alerts

PBS emits reports via email by default. Configure SMTP in the web UI
at **Administration → Notification → Mail Forwarding**.

For homelab dashboards, expose PBS metrics to Prometheus:

```bash
# Install the PBS metrics exporter
cat > /etc/systemd/system/pbs-metrics-exporter.service << 'UNIT'
[Unit]
Description=PBS Metrics Exporter for Prometheus
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/proxmox-backup-manager metrics list --output-format json
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
```

PBS also writes structured logs to the systemd journal:

```bash
# Check last backup run
journalctl -u proxmox-backup-proxy --since "24 hours ago" \
  | grep -E "backup|verify|prune|sync"

# Check datastore health
proxmox-backup-manager datastore status backup-store --verbose
```

For Telegram or Discord alerts, create a passive check script:

```bash
#!/bin/bash
# /usr/local/bin/pbs-healthcheck.sh

STATUS=$(proxmox-backup-manager datastore status backup-store --verbose 2>&1)
LAST_BACKUP=$(echo "$STATUS" | grep "last_backup" | awk '{print $2}')

if [ -z "$LAST_BACKUP" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=$CHAT_ID" \
    -d "text=⚠️ PBS: No backups found for backup-store"
  exit 1
fi

# Check if last backup is older than 36 hours
NOW=$(date +%s)
BACKUP_TS=$(date -d "$LAST_BACKUP" +%s)
AGE=$(( (NOW - BACKUP_TS) / 3600 ))

if [ $AGE -gt 36 ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d "chat_id=$CHAT_ID" \
    -d "text=⚠️ PBS: Last backup was ${AGE}h ago on backup-store"
fi
```

---

## Garbage Collection

PBS uses reference-counted chunk storage. When you prune old backups,
chunks are marked for deletion but not immediately removed. Garbage
collection reclaims this space.

Run GC weekly after pruning:

```bash
proxmox-backup-manager garbage-collection start backup-store
```

Or schedule it:

```bash
cat > /etc/systemd/system/pbs-gc.service << 'UNIT'
[Description=Proxmox Backup Server Garbage Collection]

[Service]
Type=oneshot
ExecStart=proxmox-backup-manager garbage-collection start backup-store

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/pbs-gc.timer << 'UNIT'
[Description=Weekly PBS Garbage Collection]

[Timer]
OnCalendar=Sun 05:00
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now pbs-gc.timer
```

GC is I/O intensive. Running it on Sunday morning (after verification
and pruning) means the week's active chunk data is settled and you have
the weekend to re-index.

---

## Putting It All Together: The Complete Backup Pipeline

Here's the weekly pipeline in chronological order:

```
Sunday 03:00 — Verify existing backups (checksum all chunks)
Sunday 04:00 — Prune old backups (mark chunks for deletion)
Sunday 05:00 — Garbage collection (reclaim disk space)
Daily  02:00 — Backup all VMs (incremental snapshot mode)
Daily  05:00 — Sync last 3 backups to offsite PBS
```

Total GC/reclaim time for a 1 TB datastore running 15 VMs: ~10-15
minutes. Daily backup window: 2-5 minutes per VM depending on change
rate. Sync window: 10-20 MB/s over a 1 Gbps link.

### Complete Bootstrap Script

Run this on a fresh PBS to get everything configured at once:

```bash
#!/bin/bash
# bootstrap-pbs.sh — run once on a fresh PBS

DATASET=/mnt/backup-pool/backup-store
mkdir -p "$DATASET"

# Create the datastore
proxmox-backup-manager datastore create backup-store "$DATASET" \
  --gc-schedule "sun 05:00" \
  --verify-new \
  --verify-existing

# Set retention
proxmox-backup-manager prune backup-store \
  --keep-last 3 \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 2

# Add a remote sync target (if configured)
if [ -n "$REMOTE_PBS" ]; then
  proxmox-backup-manager sync add \
    --remote "$REMOTE_PBS:8007" \
    --remote-datastore offsite-store \
    --local-datastore backup-store \
    --transfer-last 3 \
    --schedule "daily 05:00"
fi

echo "PBS configured. Log in at https://$(hostname -I | awk '{print $1}'):8007"
```

---

## Summary

Proxmox Backup Server transforms backup from "I hope this works" to
"I know this works." The key takeaways:

1. **Dedicated PBS is worth it** — separate machine or LXC on a
   different host. Never co-locate backups and production on the same
   server.
2. **ZFS datastores with zstd compression** give excellent storage
   efficiency. A 100 GB pool of VMs typically compresses to 40-60 GB.
3. **Verify, prune, and GC on a schedule** — verification is the only
   way to know backups are restorable before disaster strikes.
4. **Sync offsite** — even a cheap VPS with 100 GB of storage gives you
   the third copy that makes 3-2-1 real.
5. **Client-side encryption** ensures confidentiality even if the
   backup disk leaves your control.

PBS runs itself once configured. The systemd timers handle everything:
daily backups, weekly verification and pruning, and offsite sync. Your
job is to check the dashboard once a week and confirm the last backup
timestamp is fresh.
