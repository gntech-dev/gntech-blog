---
title: "Proxmox VE 9.2 Upgrade Guide — From 8.x with Dynamic Load Balancer"
description: "Step-by-step guide to upgrading Proxmox VE from 8.x to 9.2, covering the new Dynamic Load Balancer, SDN WireGuard fabrics, kernel 7.0 migration, LXC fixes, and post-upgrade configuration for homelab clusters."
date: 2026-05-22T07:00:00-04:00
tags:
  - proxmox
  - homelab
  - linux
  - virtualization
  - performance
keywords:
  - Proxmox VE 9.2 upgrade guide homelab
  - Proxmox 8 to 9 in-place upgrade steps
  - Dynamic Load Balancer Proxmox HA configuration
  - Proxmox kernel 7.0 LXC container fix
  - SDN WireGuard fabric Proxmox 9.2
  - pve8to9 checklist script upgrade
  - Proxmox custom CPU profiles datacenter
summary: "Upgrade your homelab from Proxmox VE 8.x to 9.2 with this practical guide covering the new Dynamic Load Balancer, SDN WireGuard fabrics, kernel 7.0 migration, known LXC issues, and post-upgrade tuning."
canonical: "https://gntech.dev/posts/proxmox-9-2-upgrade-guide/"
---

If your homelab runs Proxmox VE, May 21, 2026 marks a major
release: **Proxmox VE 9.2** ships with QEMU 11.0, LXC 7.0, ZFS
2.4, the Linux 7.0 kernel, and a brand-new **Dynamic Load
Balancer** for automated cluster resource optimization.

This guide covers the full upgrade from Proxmox VE 8.4 to 9.2
— including the new features worth enabling after the reboot,
known pitfalls like LXC containers failing to start on kernel
7.0, and the config changes you need to make for a clean
upgrade on a homelab cluster.

---

## Why Upgrade to Proxmox VE 9.2?

Proxmox VE 9.2 bundles several major updates under the hood:

| Component | Proxmox 8.x | Proxmox 9.2 |
|-----------|-------------|-------------|
| Base OS | Debian 12 Bookworm | Debian 13 Trixie |
| Kernel | 6.8 (default) | 7.0 (Linux 7.0) |
| QEMU | 8.x | 11.0 |
| LXC | 5.x | 7.0 |
| ZFS | 2.1.x | 2.4 |
| Ceph | Squid 19 (optional) | Tentacle 20.2 (default) |

The headline feature is the **Dynamic Load Balancer**, which
automatically redistributes VMs and containers across cluster
nodes based on CPU and memory utilization — similar to VMware
DRS. Other notable additions include:

- **SDN WireGuard fabrics** — encrypted overlay networks between
  cluster nodes without dedicated VPN hardware.
- **BGP/EVPN route maps and prefix lists** — fine-grained control
  for advanced SDN setups.
- **Custom CPU profiles** in the web UI — create, edit, and
  remove CPU profiles per VM from Datacenter → Options.
- **HA rules replacing HA groups** — more flexible scheduling
  policies.

---

## Prerequisites

Before touching the upgrade, verify these prerequisites:

### 1. Run the Latest Proxmox VE 8.4

```bash
pveversion
# Must report at least 8.4.1
```

If your version is older, update first:

```bash
apt update && apt dist-upgrade -y
```

### 2. Run the Pre-Upgrade Checklist

The `pve8to9` script validates your system before the upgrade.
It is included in the latest Proxmox VE 8.4 packages:

```bash
pve8to9 --full
```

Run it now. It will flag:
- LVM volumes with autoactivation enabled (common on LVM-thin
  storages)
- Third-party repositories that might conflict with Trixie
- Packages that will be removed during the dist-upgrade

Fix each warning before proceeding. Re-run `pve8to9 --full`
after each fix.

### 3. Backup Everything

Do not skip this. Back up all VMs and containers to external or
NFS/SMB storage via the GUI or:

```bash
vzdump <VMID> --storage backup-nfs --mode snapshot
```

Also back up critical host config:

```bash
tar czf /root/pve-etc-backup-$(date +%F).tar.gz /etc/pve /etc/network/interfaces /etc/hostname /etc/resolv.conf
```

### 4. Ensure Enough Disk Space

```bash
df -h /
# Need at least 5 GB free, ideally 10+ GB
```

The dist-upgrade downloads hundreds of packages. The apt cache
alone can reach 1-2 GB during the process.

### 5. Use tmux or screen

If connecting via SSH (not IPMI/iKVM), wrap the session:

```bash
tmux new -s pve-upgrade
```

This protects against connection drops mid-upgrade.

---

## Step-by-Step: In-Place Upgrade to Proxmox VE 9.2

### Step 1: Update Repositories to Debian Trixie

Switch Debian base and Proxmox repositories from Bookworm to
Trixie:

```bash
# Update Debian base repos
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list

# Update Proxmox enterprise or no-subscription repo
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/pve-enterprise.list 2>/dev/null || true
```

### Step 2: Add Proxmox VE 9 Repositories (deb822 Format)

Replace the old `.list` files with the new deb822 `.sources`
format. For the **no-subscription** repository (most homelabs):

```bash
cat > /etc/apt/sources.list.d/proxmox.sources << 'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
```

If you have an enterprise subscription:

```bash
cat > /etc/apt/sources.list.d/pve-enterprise.sources << 'EOF'
Types: deb
URIs: https://enterprise.proxmox.com/debian/pve
Suites: trixie
Components: pve-enterprise
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF
```

Remove the old `.list` files after verifying the new ones work:

```bash
apt update && apt policy
# Verify output shows trixie repositories

# Then remove old repo files
rm -f /etc/apt/sources.list.d/pve-enterprise.list
rm -f /etc/apt/sources.list.d/pve-install-repo.list
apt update
```

### Step 3: Run the Dist-Upgrade

```bash
apt dist-upgrade
```

This upgrades the entire system from Debian 12 → 13 and Proxmox
VE 8 → 9 in one pass. Expect 5-60 minutes depending on disk
speed.

During the process you will be prompted about config file
changes. Recommended choices:

| File | Recommendation |
|------|---------------|
| `/etc/issue` | Keep current (cosmetic only) |
| `/etc/lvm/lvm.conf` | Install maintainer version |
| `/etc/ssh/sshd_config` | Install maintainer version |
| `/etc/default/grub` | Keep current (review diffs first) |
| `/etc/chrony/chrony.conf` | Install maintainer version |

### Step 4: Reboot

```bash
reboot
```

After reboot, verify the kernel:

```bash
uname -r
# Should show: 7.0.x-pve
pveversion
# Should show: pve-manager/9.2.x
```

### Step 5: Clean Up apt Repositories (Optional)

Modernize remaining `.list` files to deb822 format:

```bash
apt modernize-sources
```

This creates `.sources` files and renames old `.list` files to
`.list.bak`. Verify everything works and delete the `.bak`
files once confirmed.

---

## Post-Upgrade: What to Fix First

### LVM Autoactivation Migration

Upgrading from PVE 8, your existing LVM guest volumes may still
have autoactivation enabled. This causes issues on shared LVM
storages in clusters. Run the migration script:

```bash
/usr/share/pve-manager/migrations/pve-lvm-disable-autoactivation
```

Re-run `pve8to9 --full` to confirm the warning is gone.

### LXC Containers Not Starting on Kernel 7.0

A common issue reported on kernel 7.0 is LXC containers failing
to start with errors like:

```
lxc_map_ids: newuidmap failed to write mapping
```

This is caused by `systemd-tmpfiles` not creating `/run/pve`
early enough. Fix:

```bash
systemctl status pve-guests.service
# Check for failures

# Ensure tmpfiles.d is configured correctly
systemd-tmpfiles --cat-config | grep pve

# If /run/pve is missing, create it and restart:
mkdir -p /run/pve
pve-container restart --all
```

For persistent issues, ensure `pve-container` and
`pve-guests` services are enabled:

```bash
systemctl enable --now pve-guests.service
systemctl enable --now pve-container.service
```

### Disable Audit Noise (Optional)

Debian Trixie enables kernel audit logging by default. To
suppress excessive audit messages during normal operation:

```bash
systemctl mask --now systemd-journald-audit.socket
```

---

## Configuring the Dynamic Load Balancer

The Dynamic Load Balancer is the standout feature in 9.2. It
automatically rebalances VMs and containers across cluster nodes
based on resource utilization — no more manually deciding where
to place guests.

### Prerequisites

- All cluster nodes must be on Proxmox VE 9.2.
- HA must be enabled on the cluster (Datacenter → HA).
- A valid quorum (at least 3 nodes or a QDevice).

### Enable Dynamic Load Balancing

Navigate to **Datacenter → Options** and set:

- **HA Scheduling:** `Dynamic Load`
- **Re-balance method:** `Default (bruteforce)` or `TOPSIS`
- **Automatically re-balance HA resources:** ✓ enabled

From the CLI:

```bash
pvesh set /cluster/ha/options \
  --scheduler dynamic \
  --rebalance-method bruteforce \
  --rebalance-automatic 1
```

The load balancer periodically evaluates node utilization and
moves low-priority VMs from overloaded nodes to underutilized
ones. Migration thresholds are configurable:

```bash
pvesh set /cluster/ha/options \
  --cpu-threshold-overloaded 80 \
  --memory-threshold-overloaded 85 \
  --cpu-threshold-underloaded 30 \
  --memory-threshold-underloaded 40
```

### HA Rules vs. HA Groups

Proxmox VE 9 deprecates HA groups in favor of HA rules. If you
upgrade from PVE 8 with existing HA groups, they are
automatically migrated to HA rules once all cluster nodes are on
PVE 9.

Verify the migration:

```bash
journalctl -eu pve-ha-crm
```

Create new rules from the GUI or CLI:

```bash
pvesh create /cluster/ha/rules \
  --id my-rule \
  --type resource \
  --match "tags:critical" \
  --action spread \
  --priority 100
```

---

## Other New Features Worth Enabling

### SDN WireGuard Fabrics

Proxmox VE 9.2 adds WireGuard as a native SDN fabric protocol.
This creates encrypted overlay networks between cluster nodes
without configuring WireGuard manually on each host.

**Datacenter → SDN → Zones → Add → Fabric**

Select `WireGuard` as the fabric type, assign a subnet, and
select which nodes participate. The zone is automatically
provisioned and key exchange is handled by the cluster
configuration.

### Custom CPU Profiles

Navigate to **Datacenter → Options → CPU Profiles** to create
custom CPU type profiles. Useful for:

- Exposing specific CPU features to VMs (e.g., AVX-512 for AI
  workloads)
- Matching CPU models across heterogeneous cluster hardware
- Hiding features for cross-cluster migration compatibility

### BGP/EVPN Route Maps

If you run BGP/EVPN in your homelab (for example, integrating
Proxmox SDN with RouterOS or FRR), the new route maps and prefix
lists give you fine-grained control over route advertisement.
Configure under **Datacenter → SDN → IPAM / Route Maps**.

---

## Known Issues and Workarounds

### Veeam Backup Compatibility

PVE 9.2 uses QEMU machine version 10.0+ by default. Veeam has
not adapted to the new internal disk attachment changes. If you
use Veeam for backups, pin affected VMs to machine version
`9.2+pve1`:

```bash
qm set <VMID> --machine pc-q35-9.2+pve1
```

### /tmp is Now tmpfs

Debian Trixie mounts `/tmp` as tmpfs using up to 50% of system
memory by default. If your workflows depend on large temp files,
adjust the mount:

```bash
mount -o remount,size=10G /tmp
```

Or revert to disk-backed `/tmp`:

```bash
systemctl mask tmp.mount
```

### Ceph Updates

If you run hyper-converged Ceph, the default is now Ceph
Tentacle 20.2.1. Ceph Squid 19.2.3 remains available as an
alternative. Check compatibility before upgrading:

```bash
ceph --version
```

---

## Verifying a Clean Upgrade

Run the checklist once more after reboot:

```bash
pve8to9 --full
```

Expected clean output — no warnings or errors. Then:

```bash
pveversion -v | head -10
# pve-manager: 9.2.x
# proxmox-ve: 9.2.x
# proxmox-kernel-7.0: 7.0.x
# qemu-server: 11.x
# lxc-pve: 7.x
```

Check all VMs start properly:

```bash
qm list
pct list
```

Test HA rebalancing by creating a test VM with HA enabled,
loading it with stress, and verifying the dynamic load balancer
moves it:

```bash
# Install stress in a test VM
apt install stress
stress --cpu 4 --timeout 120

# Monitor load balancer activity
journalctl -fu pve-ha-crm
```

---

## Summary

Proxmox VE 9.2 is a significant release for homelab users. The
Dynamic Load Balancer eliminates the manual guesswork of VM
placement, SDN WireGuard fabrics simplify encrypted cluster
networking, and the underlying upgrade to Debian Trixie with
Linux 7.0 brings modern kernel features.

Key takeaways:

1. **Run `pve8to9 --full`** before and after the upgrade.
2. **Use tmux** — this is a long-running dist-upgrade.
3. **Fix LVM autoactivation** post-upgrade to avoid storage
   issues in clusters.
4. **Enable the Dynamic Load Balancer** after all nodes are
   upgraded.
5. **Pin Veeam-backed VMs** to machine version `9.2+pve1` if
   needed.
6. **Test LXC containers** after the kernel 7.0 upgrade and
   apply the tmpfiles fix if they fail to start.

The 9.2 release transforms Proxmox from a capable hypervisor
into an actively load-managed virtualization platform — and for
homelab operators managing multiple nodes, that alone is worth
the upgrade.
