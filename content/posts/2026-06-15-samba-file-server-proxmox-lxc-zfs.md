---
title: "Samba File Server in Proxmox LXC with ZFS Dataset Passthrough"
description: "Build a lightweight, high-performance Samba NAS inside a Proxmox LXC with direct ZFS dataset passthrough. Covers privileged LXC setup, UID mapping, performance tuning, and backup integration."
date: 2026-06-15T14:30:00-04:00
tags:
  - homelab
  - linux
  - storage
  - proxmox
  - containers
keywords:
  - Samba file server Proxmox LXC setup
  - ZFS dataset passthrough LXC container homelab NAS
  - Privileged vs unprivileged LXC Samba performance comparison
  - Proxmox Samba share UID mapping user configuration
  - Samba performance tuning Linux kernel parameters
  - LXC container NAS file sharing Docker media server storage
  - Samba backup integration ZFS snapshot replication
summary: "Run Samba inside a Proxmox LXC with direct ZFS dataset access for a sub-1GB RAM NAS. Covers privileged LXC setup, ZFS passthrough, user configuration, and Samba performance tuning for homelab file sharing."
canonical: "https://blog.gntech.me/posts/samba-file-server-proxmox-lxc-zfs/"
---

Every homelab needs centralized file storage. Windows machines need network shares for backups, media servers need a library location, and configuration files need a home you can reach from any device. Running a full NAS VM — TrueNAS, OMV, or Unraid — eats 4-8GB of RAM and adds unnecessary overhead for a container that only serves files.

The sweet spot is combining **Samba** inside a **Proxmox LXC** with a **ZFS dataset passthrough**. The LXC gives you near-native file I/O with sub-1GB RAM usage. ZFS provides data integrity, compression, and snapshot-based backups. Samba serves CIFS/SMB shares to any client on your network.

This guide walks through the complete setup: creating the LXC, passing through a ZFS dataset, configuring Samba for performance, and integrating with ZFS snapshots for backup.

## Why LXC + Samba + ZFS Instead of a VM

The alternatives each make trade-offs that matter in a homelab:

- **NAS VM (TrueNAS, OMV, Unraid)** — Full OS kernel, 4-8GB RAM minimum, separate storage stack. Excellent features but heavy for a single-purpose file server.
- **Docker Samba containers** — dperson/samba or similar images. They work, but Docker's networking adds translation overhead for CIFS, and bind-mounting ZFS datasets into Docker requires careful permission mapping. Kernel-level CIFS in an LXC outperforms containerized Samba by a measurable margin on sequential reads.
- **Samba on the Proxmox host directly** — Works, but violates the principle of isolating services from the hypervisor. Updates, reboots, or a config mistake can affect running VMs.

LXC hits the sweet spot: a full userspace with kernel-native SMB performance, 256MB-1GB RAM footprint, and complete isolation from the Proxmox host.

## Prerequisites

- Proxmox VE 8.x or 9.x with a ZFS pool (e.g., `tank` or `rpool/data`)
- Root or sudo access on the Proxmox host
- Debian 12 (bookworm) container template available locally

Verify your templates are downloaded:

```bash
pveam list local | grep debian
```

If no Debian template exists, download one:

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
```

## Step 1 — Create the LXC Container

Create a Debian 12 LXC with a static IP on your storage VLAN. Adjust the CTID, IP, and storage pool to match your environment:

```bash
CTID=110
pvesm list local-zfs  # confirm your storage pool name

pct create $CTID local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --storage local-zfs \
  --rootfs local-zfs:16 \
  --hostname fileserver \
  --net0 name=eth0,bridge=vmbr0,ip=10.0.30.10/24,gw=10.0.30.1 \
  --cores 2 \
  --memory 1024 \
  --swap 512 \
  --unprivileged 0 \
  --ostype debian
```

Key flags explained:

- `--unprivileged 0` — Creates a **privileged** LXC. Important for Samba + ZFS compatibility, discussed in detail below.
- `--rootfs local-zfs:16` — 16GB root filesystem on your ZFS storage pool. Your data dataset is separate.
- `--memory 1024` — 1GB RAM. Samba typically uses 200-400MB under load.

Start and enter the container:

```bash
pct start $CTID
pct enter $CTID
```

## Step 2 — Privileged vs Unprivileged LXC — The Right Choice for Samba

This is the most common question when setting up Samba in LXC. Here is the trade-off:

**Unprivileged containers** use UID/GID mapping (subuid/subgid) to isolate the container's root from the host. This is more secure — a container breakout from root maps to a non-privileged user on the host. However, Samba's interaction with ZFS ACLs and Windows permission models becomes painful. File ownership on passthrough ZFS datasets will show as nobody:nogroup unless you configure complex UID mappings. Windows ACLs (NTFS-style) are nearly impossible to maintain correctly.

**Privileged containers** run as root on the host. This is less isolated — a container compromise means host root. However, for Samba with ZFS passthrough, it "just works":

- File ownership from the container maps directly to the ZFS dataset
- ZFS ACLs are natively supported
- Windows permission inheritance functions correctly
- No UID mapping headaches

The risk is manageable when you isolate the container on a storage-only VLAN (10.0.30.0/24 in this guide) and apply firewall rules.

If you must use unprivileged containers, you can work around UID mapping with `lxc.idmap` entries in the container config, but expect ongoing maintenance.

## Step 3 — Create and Pass Through the ZFS Dataset

Back on the Proxmox host, create a dedicated ZFS dataset for your Samba data:

```bash
# Create the dataset
zfs create tank/fileserver

# Enable ZSTD compression for space savings
zfs set compression=zstd tank/fileserver

# Set recordsize to 1M for Samba sequential workloads
zfs set recordsize=1M tank/fileserver

# Disable atime — reduces write amplification on NAS workloads
zfs set atime=off tank/fileserver

# Set a quota if needed (adjust as necessary)
zfs set quota=4T tank/fileserver
```

Mount the dataset into the LXC. From the Proxmox host (not the container):

```bash
pct set $CTID -mp0 /tank/fileserver,mp=/srv/fileserver
```

This creates a bind mount from the host path `/tank/fileserver` to the container's `/srv/fileserver`. Verify it worked:

```bash
pct enter $CTID
df -h /srv/fileserver
```

You should see the ZFS filesystem mounted inside the container with the size and usage of your dataset.

## Step 4 — Install and Configure Samba

Inside the container, install Samba:

```bash
apt update && apt install -y samba samba-common-bin
```

Back up the default configuration:

```bash
cp /etc/samba/smb.conf /etc/samba/smb.conf.default
```

Write the Samba configuration:

```bash
cat > /etc/samba/smb.conf << 'EOF'
[global]
   workgroup = WORKGROUP
   server string = %h fileserver
   netbios name = FILESERVER
   security = user
   map to guest = bad user
   server min protocol = SMB2_10
   server max protocol = SMB3
   disable netbios = yes
   smb ports = 445
   log file = /var/log/samba/log.%m
   max log size = 1000
   logging = file
   panic action = /usr/share/samba/panic-action %d

   # Performance tuning
   socket options = TCP_NODELAY IPTOS_LOWDELAY
   read raw = yes
   write raw = yes
   server signing = disabled
   strict sync = no
   disable spoolss = yes
   min receivefile size = 16384
   aio read size = 16384
   aio write size = 16384
   use sendfile = yes

[shares]
   comment = Homelab File Share
   path = /srv/fileserver
   browseable = yes
   read only = no
   guest ok = no
   create mask = 0664
   directory mask = 0775
   force user = nobody
   force group = nogroup
   veto files = /Thumbs.db/.DS_Store/.Trashes/
   delete veto files = yes
EOF
```

Create a Samba user and set directory permissions:

```bash
# Create a system user for Samba access
useradd -m -s /usr/sbin/nologin smbuser

# Set the Samba password (you will be prompted)
smbpasswd -a smbuser

# Set directory ownership on the shared dataset
chown nobody:nogroup /srv/fileserver
chmod 2775 /srv/fileserver
```

Restart Samba:

```bash
systemctl restart smbd
systemctl enable smbd
```

Test the Samba configuration:

```bash
testparm
```

## Step 5 — Performance Tuning for Maximum Throughput

Beyond ZFS settings, tune the Linux kernel network stack for Samba workloads. Add these to `/etc/sysctl.conf` on the LXC container:

```bash
cat >> /etc/sysctl.conf << 'EOF'

# Samba/network performance tuning
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
EOF

sysctl -p
```

Verify BBR is available:

```bash
sysctl net.ipv4.tcp_congestion_control
# Output: net.ipv4.tcp_congestion_control = bbr
```

If BBR is not available, load the module:

```bash
modprobe tcp_bbr
echo "tcp_bbr" >> /etc/modules
```

Run a quick throughput test from a Linux client:

```bash
# Write test
dd if=/dev/zero of=/mnt/fileserver/testfile bs=1M count=2048 oflag=direct

# Read test
dd if=/mnt/fileserver/testfile of=/dev/null bs=1M iflag=direct
```

On a modern homelab with 1GbE networking and SSDs, expect 110-118 MB/s sequential reads. With 2.5GbE, you should saturate the link at ~280 MB/s.

## Step 6 — Accessing Shares from Clients

### Windows

1. Open File Explorer
2. Right-click **This PC** → **Map network drive**
3. Folder: `\\10.0.30.10\shares`
4. Check **Connect using different credentials**
5. Enter the `smbuser` credentials you created
6. Click **Finish**

The share appears as a mapped drive. For persistent unmapped access, add the credentials to Windows Credential Manager.

### Linux Clients

Install cifs-utils and mount:

```bash
sudo apt install cifs-utils
sudo mkdir -p /mnt/fileserver

sudo mount -t cifs //10.0.30.10/shares /mnt/fileserver \
  -o username=smbuser,uid=1000,gid=1000,iocharset=utf8,vers=3.0

# Persistent mount in /etc/fstab
echo '//10.0.30.10/shares /mnt/fileserver cifs username=smbuser,password=SECRET,uid=1000,gid=1000,iocharset=utf8,vers=3.0,noexec,nodev,nosuid,_netdev 0 0' \
  | sudo tee -a /etc/fstab
```

### macOS

1. Open Finder → **Go** → **Connect to Server**
2. Enter: `smb://10.0.30.10/shares`
3. Click **Connect**
4. Enter the `smbuser` credentials
5. The share mounts on your desktop and in `/Volumes/shares`

## Step 7 — Backup Integration with ZFS Snapshots

The real power of this setup is ZFS-native backups. Since the data lives on a ZFS dataset, you can snapshot and replicate it independently of the container.

### Automated Snapshots on the Proxmox Host

Create a snapshot script:

```bash
cat > /usr/local/bin/snapshot-fileserver.sh << 'EOF'
#!/bin/bash
DATASET="tank/fileserver"
SNAPSHOT_NAME="${DATASET}@daily-$(date +%Y%m%d-%H%M)"

zfs snapshot "$SNAPSHOT_NAME"
zfs list -t snapshot -o name | grep "${DATASET}@" | tail -7

# Prune snapshots older than 7 days
zfs list -t snapshot -o name -H | grep "${DATASET}@" | \
  head -n -7 | while read snap; do zfs destroy "$snap"; done
EOF

chmod +x /usr/local/bin/snapshot-fileserver.sh
```

Create a systemd timer to run it daily:

```bash
cat > /etc/systemd/system/fileserver-snapshot.service << 'EOF'
[Unit]
Description=ZFS snapshot for file server dataset
[Service]
Type=oneshot
ExecStart=/usr/local/bin/snapshot-fileserver.sh
EOF

cat > /etc/systemd/system/fileserver-snapshot.timer << 'EOF'
[Unit]
Description=Daily ZFS snapshot for file server
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now fileserver-snapshot.timer
```

### Send Snapshots to Proxmox Backup Server

If you run Proxmox Backup Server, use `proxmox-backup-client` to send the dataset snapshot off-host:

```bash
# Install the client on the Proxmox host (if not present)
apt install proxmox-backup-client

# Create and pipe a snapshot to PBS
zfs send tank/fileserver@daily-20260615-0230 | \
  proxmox-backup-client backup fs.pxar:/proc/self/fd/0 \
    --repository root@pbs@10.0.20.40:store-backup
```

Alternatively, replicate directly to a remote ZFS pool:

```bash
zfs send tank/fileserver@daily-20260615-0230 \
  | ssh backup-server zfs recv backup-tank/fileserver
```

The LXC itself is also backed up via Proxmox's standard container backup:

```bash
vzdump 110 --mode snapshot --compress zstd --storage pbs-remote
```

## Step 8 — Security Hardening

Isolate the file server on a dedicated storage VLAN. In your MikroTik or managed switch:

- VLAN 30: Storage (LXC file server, NFS clients)
- Firewall rule: only allow SMB (TCP 445) and ICMP from client VLANs

In the LXC itself, add these lines to the `[global]` section of `/etc/samba/smb.conf`:

```ini
hosts allow = 10.0.0.0/8 192.168.0.0/16 127.0.0.1
hosts deny = 0.0.0.0/0
```

Enable UFW in the LXC:

```bash
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow from 10.0.0.0/8 to any port 445 proto tcp
ufw allow from 192.168.0.0/16 to any port 445 proto tcp
ufw --force enable
```

Additional settings to verify or add to `/etc/samba/smb.conf`:

```ini
# Disable guest access entirely
map to guest = never

# Disable printer sharing
load printers = no
printing = bsd
printcap name = /dev/null
disable spoolss = yes
```

## Monitoring and Logging

Samba logs to `/var/log/samba/`. Keep an eye on authentication failures:

```bash
grep -i "password mismatch" /var/log/samba/log.smbd
grep -i "invalid user" /var/log/samba/log.smbd
```

Monitor active connections:

```bash
smbstatus
```

Sample output showing connected clients and open files:

```
Samba version 4.17.12
PID     Username     Group        Machine
12345   smbuser      smbuser      10.0.20.50     (192.168.1.50)

Service  pid     Machine       Connected at                    Encryption   Signing
shares   12345   10.0.20.50    Mon Jun 15 12:34:56 2026 AST   -            -
```

## Conclusion

Samba in a Proxmox LXC with ZFS dataset passthrough gives you a file server that is:

- **Lightweight** — 256MB-1GB RAM, no separate OS to manage
- **Fast** — kernel-level CIFS with BBR congestion control, tuned ZFS recordsize, and sendfile
- **Backed up** — ZFS snapshots, PBS integration, and standard container backups
- **Simple** — one LXC config line for the mount, one smb.conf for the share

Start by creating a Debian 12 privileged LXC, pass your ZFS dataset through as a mount point, configure Samba with the performance settings above, and set up daily ZFS snapshots. Your clients will see a fast SMB share, your Proxmox host will see minimal overhead, and your backups will be handled by ZFS automation.

For the homelab that needs centralized storage without running a full NAS VM, the LXC + Samba + ZFS combination is the most efficient path to a reliable file server.
