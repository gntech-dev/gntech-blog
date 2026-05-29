---
title: "Proxmox Datacenter Manager 1.1 — Centralized Multi-Cluster Management Guide"
description: "Deploy and configure Proxmox Datacenter Manager 1.1 for centralized multi-cluster management across sites. Automated installations, Ceph monitoring, subscription management, and world map visualization guide."
date: 2026-05-29T17:00:00-04:00
tags:
  - proxmox
  - virtualization
  - monitoring
  - infrastructure
  - automation
keywords:
  - Proxmox Datacenter Manager 1.1 deployment guide
  - centralized Proxmox multi-cluster management
  - PDM automated installation workflows
  - Proxmox Ceph monitoring centralized
  - Proxmox subscription key management
  - Proxmox Datacenter Manager world map visualization
  - PDM 1.1 upgrade from earlier versions
summary: "Step-by-step guide to deploying Proxmox Datacenter Manager 1.1 for centralized multi-cluster management. Covers automated installation workflows, Ceph monitoring, subscription key management, world map visualization, and upgrade procedures."
canonical: "https://blog.gntech.me/posts/proxmox-datacenter-manager-1-1/"
---

If you manage more than one Proxmox VE cluster, you know the pain of
jumping between separate web interfaces, checking cluster health in five
different browser tabs, and manually syncing configuration changes across
sites. Proxmox Datacenter Manager (PDM) removes all of that friction.

PDM is the centralized management plane for the Proxmox ecosystem. Think
of it as vCenter for Proxmox — a single pane of glass that aggregates
multiple Proxmox VE clusters and Proxmox Backup Server instances into
one unified dashboard. Released in version 1.0 earlier this year, PDM
hit 1.1 in late May 2026 with major additions: automated installation
workflows, centralized Ceph monitoring, subscription key management, a
world map visualization, and a refreshed platform built on Debian 13.5
"Trixie", Linux Kernel 7.0, and OpenZFS 2.4.

This guide covers everything you need to deploy PDM 1.1 in your homelab,
add remote clusters, use the new features, and upgrade from PDM 1.0.

## What Is Proxmox Datacenter Manager?

Proxmox Datacenter Manager provides a unified web interface at
`https://<pdm-ip>:8006` that connects to multiple independent PVE
clusters. You get:

- Aggregate resource overview across all linked clusters
- Centralized VM/CT migration between clusters
- Unified update management and subscription oversight
- A remote CLI via `proxmox-datacenter-manager-client`
- Role-based access control spanning all remotes

For homelab environments, PDM really shines once you cross the threshold
from a single-node setup to a multi-node or multi-site layout. Whether
you have two nodes in a living-room rack and one at a colo, or you run
a three-node cluster at home and a separate PBS for backups at a remote
site, PDM ties everything together without adding complexity.

## What's New in Proxmox Datacenter Manager 1.1

Version 1.1 is a significant feature drop. Here is what changed.

### 1. Automated Installation Workflows

The headline feature in PDM 1.1 is the Automated Installations tab under
the Remotes section. You can now define unattended installation profiles
for Proxmox VE nodes and Proxmox Backup Server systems directly from the
PDM web UI. The system tracks installation progress and reports results
back into the dashboard.

This is huge for provisioning new nodes at scale. Define an answer file
once, boot the target hardware from the Proxmox ISO with the automated
install flag, and PDM handles the rest.

### 2. Centralized Subscription Key Management

Managing enterprise subscription keys across a dozen nodes was a chore.
PDM 1.1 adds a centralized subscription management page where you can
upload, assign, and track subscription keys across all managed remotes.
Compliance validation runs automatically, so you always know which nodes
are covered and which are about to expire.

### 3. Centralized Ceph Monitoring

If you run Proxmox with hyper-converged Ceph storage, PDM 1.1 gives you
a single Ceph monitoring panel covering all linked clusters. Health
status, OSD utilization, PG states, and performance metrics are
aggregated in one view. No more SSH-ing into each monitor node to check
cluster health.

### 4. World Map Visualization

New in 1.1, the world map provides a geographic overview of all your
remotes. Assign coordinates to each site and PDM renders them on an
interactive map. Click a pin to jump into that cluster. It is a quality-
of-life feature that makes multi-site management feel less abstract.

### 5. Local Metric Collection Improvements

PDM 1.1 improves the metric collection pipeline with finer-grained
host-level data. CPU, memory, disk IO, and network metrics are now
collected locally on each remote node and forwarded to PDM at configurable
intervals. This feeds better capacity planning charts and trend analysis.

### 6. Updated Platform Components

PDM 1.1 moves to Debian 13.5 "Trixie" as its base, with Linux Kernel 7.0
and OpenZFS 2.4. The newer kernel brings improved hardware support and
performance improvements, while ZFS 2.4 adds faster snapshot operations
and compatibility with newer SSD and NVMe hardware.

## Deploying Proxmox Datacenter Manager 1.1

PDM runs as a standalone service on a dedicated Debian VM or physical
host. It does not require a Proxmox VE license for basic operation,
though some advanced features require an active subscription.

### Minimum Requirements

- 2 vCPUs (4 recommended for more than 5 remotes)
- 4 GB RAM (8 GB for heavy monitoring loads)
- 32 GB disk (SSD preferred)
- Debian 13 "Trixie" or the official PDM ISO
- Network reachability to all managed PVE clusters (port 8006)

### Installation from Proxmox Repository

Set up the repository and install the package:

```bash
# Add the Proxmox Datacenter Manager repository
echo "deb http://download.proxmox.com/debian/pdm trixie pdm-no-subscription" | \
  sudo tee /etc/apt/sources.list.d/pdm.list

# Import the Proxmox GPG key
wget -qO- https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg | \
  sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/proxmox.gpg

# Install
sudo apt update
sudo apt install proxmox-datacenter-manager
```

The installer configures the web interface, sets up the local database,
and starts the PDM service automatically.

### First Login

Open a browser to `https://<pdm-ip>:8006`. The first login prompts you
to create the admin account and upload a TLS certificate. For a homelab, a
self-signed certificate is fine — just accept the browser warning.

After the initial setup, you land on the Dashboard. It is empty until you
add remote clusters.

## Adding and Managing Remote Clusters

### Via the Web UI

Navigate to Datacenter → Remotes → Add. Enter the cluster name, the
Proxmox VE node IP or hostname, and authentication credentials. You can
use either `root@pam` with a password or an API token (preferred).

```bash
# Create an API token on the PVE node for PDM
pveum user add pdm-mon@pve
pveum acl modify / --user pdm-mon@pve --role PVEAuditor
pveum token add pdm-mon@pve --tokenid pdm-token --privsep 0
```

### Via the Command Line

```bash
proxmox-datacenter-manager-client remote add homelab \
  --host 10.0.20.30 \
  --user root@pam \
  --password
```

PDM polls each remote every 30 seconds by default. The status panel shows
connection health, resource usage, and pending updates for every linked
cluster in real time.

## Using Automated Installation Workflows

The Automated Installations feature requires a Proxmox VE or PBS ISO
configured with an answer file. From the Remotes → Automated Installations
tab in PDM:

1. Upload or paste your answer file (YAML format)
2. Assign a profile name and description
3. Boot the target hardware from the ISO with the `auto-install` kernel
   parameter pointing at the PDM server URL

PDM tracks each installation in the dashboard. You see provisioning
progress, any errors, and the final deployment status. This is invaluable
when rolling out multiple nodes to a freshly built rack.

## Monitoring Ceph Across Clusters

If any of your remotes run Ceph, the Ceph Monitoring panel under the
storage section aggregates everything:

- Overall cluster health (HEALTH_OK / HEALTH_WARN / HEALTH_ERR)
- OSD count, status, and utilization per cluster
- Pool statistics and PG distribution
- Performance dashboards (IOPS, throughput, latency)

All data is read from the remote Ceph monitors via the PVE API — no extra
agents or daemons needed on the Ceph nodes.

## Upgrading from PDM 1.0 to 1.1

Upgrading is a straightforward in-place operation. Run these steps on
the PDM host:

```bash
# Backup the PDM configuration
sudo cp -r /etc/proxmox-datacenter-manager \
  /etc/proxmox-datacenter-manager.backup

# Update repository info and upgrade
sudo apt update
sudo apt full-upgrade

# Reboot to load the new kernel
sudo reboot

# Verify the installed version
proxmox-datacenter-manager-client version
```

If you use the enterprise repository, make sure your subscription key
is valid before upgrading:

```bash
# Enterprise repository
# deb https://enterprise.proxmox.com/debian/pdm trixie pdm-enterprise
```

### Pre-Upgrade Checklist

- [ ] Back up PDM configuration files
- [ ] Verify all managed PVE clusters are healthy
- [ ] Confirm sufficient disk space on the PDM host (2 GB free minimum)
- [ ] Check that no remote upgrades are in progress
- [ ] Review the official PDM 1.1 release notes

## Proxmox Datacenter Manager Configuration Tips

A few things I have learned running PDM in production:

- **Use API tokens, not passwords.** Passwordless tokens with scoped
  permissions (`PVEAuditor` or `PVEAdmin`) are more secure and survive
  password rotations.
- **Run PDM in its own VM.** It does not need to be on a PVE cluster node,
  and isolating it keeps the management plane independent of your
  workload infrastructure.
- **Configure alerting early.** PDM can forward cluster alerts via email
  or webhook. Set this up at deploy time rather than after something
  goes wrong.
- **Lock the remote poll interval.** The default 30-second poll is fine
  for most homelabs. If you manage many clusters and see CPU load, bump
  it to 60 seconds under Datacenter → Options.

## Conclusion

Proxmox Datacenter Manager 1.1 transforms multi-cluster management from
a series of SSH sessions and browser tabs into a unified, well-organized
dashboard. Automated installations, centralized Ceph monitoring, and
subscription management make it genuinely useful for anyone running more
than a single Proxmox node — whether in a homelab or at enterprise scale.

The best part? PDM is free to use with up to three managed nodes without
a subscription. That covers a huge range of homelab setups. Give it a try
on a lightweight Debian VM and see how much smoother your multi-cluster
workflow becomes.

For more details, check the [Proxmox Datacenter Manager documentation](https://pdm.proxmox.com/wiki/).
