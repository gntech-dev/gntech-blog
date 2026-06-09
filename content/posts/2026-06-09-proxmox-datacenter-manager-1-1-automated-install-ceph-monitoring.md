---
title: "Proxmox Datacenter Manager 1.1 — Automated Installs & Ceph Monitoring"
description: "Proxmox Datacenter Manager 1.1 adds automated answer-file installations, centralized Ceph monitoring, and subscription management. A practical guide to PDM for your homelab."
date: 2026-06-09T14:30:00-04:00
tags:
  - proxmox
  - virtualization
  - homelab
  - monitoring
  - linux
keywords:
  - Proxmox Datacenter Manager 1.1 automated installation answer file
  - Proxmox multi-cluster management centralized Ceph monitoring
  - PDM 1.1 subscription key management deployment guide
  - Proxmox Datacenter Manager installation Debian 13 Trixie
  - Ceph health monitoring Proxmox distributed storage homelab
  - Proxmox remote management automated install token security
  - Unified Proxmox cluster management vCenter alternative homelab
summary: "Proxmox Datacenter Manager 1.1 is out — with automated answer-file installations, unified Ceph monitoring across remotes, and centralized subscription management. Here's what's new and how to deploy it."
canonical: "https://blog.gntech.me/posts/proxmox-datacenter-manager-1-1-automated-install-ceph-monitoring/"
---

If you run more than one Proxmox VE cluster, you know the pain: bouncing between browser tabs, checking dashboards separately, logging into different nodes to verify Ceph health or manage subscriptions. For years, this was the gap in the Proxmox ecosystem — a missing centralized pane of glass for multi-cluster operations.

**Proxmox Datacenter Manager (PDM)** exists to solve exactly that. Think of it as "vCenter for Proxmox" — an official, first-party management platform that unifies your entire Proxmox estate. Version 1.1, released on May 28, 2026, is the most significant update yet, adding automated answer-file installations, centralized subscription management, and unified Ceph monitoring across all connected remotes.

Here's a deep dive into what PDM 1.1 brings to your homelab and how to get it running.

## What Is Proxmox Datacenter Manager?

PDM is a standalone management appliance that provides a single web UI for monitoring and operating multiple Proxmox VE clusters and standalone nodes. It sits alongside your existing infrastructure — remotes continue running independently even if PDM goes down, so it is not a single point of failure.

### PDM 1.1 Software Stack

- **Base OS:** Debian 13.5 "Trixie"
- **Kernel:** Linux 7.0 (stable default)
- **Filesystem:** ZFS 2.4.2
- **Web UI:** HTTPS on port 8006 (same familiar Proxmox interface style)

### System Requirements

| Use Case | CPU | RAM | Storage |
|----------|-----|-----|---------|
| Evaluation | 1 core | 1 GiB | 10 GB |
| Production | 2+ cores | 4 GiB | 40 GB+ |

For a homelab with 2–5 nodes, a VM with 2 vCPUs and 4 GB RAM is plenty. You can run it as a VM on one of your existing Proxmox hosts.

## Automated Installations — The Killer Feature

The headline feature of PDM 1.1 is the **automated installation** integration. If you have ever deployed Proxmox VE across multiple nodes manually — answering the same prompts over and over — you will appreciate this immediately.

PDM now lets you create **answer files** directly from its web interface using a dedicated wizard. These answer files are served to target systems via HTTPS during installation, so new nodes boot, fetch their configuration, and deploy without hands-on interaction.

### Creating an Answer File

In the PDM web UI, navigate to **Automated Installations → Prepared Answers** and click **Create**. The wizard walks you through:

- **Network settings** — interface names, IP addresses (CIDR), gateway, DNS servers
- **Disk layout** — target disk, partition scheme, filesystem type (ZFS, ext4, BTRFS)
- **Locale and keyboard** — timezone, language, keymap
- **Administrator credentials** — root password, SSH keys, email
- **Subscription key** — optional, auto-registers the node

### MiniJinja Templating for Unique Configs

One of the cleverest details is **MiniJinja templating** (Jinja2-inspired). You can template fields like hostname, IP address, and gateway to auto-generate unique configurations for each installation:

```
{{ product.product }}{{ installation_nr }}.lab.example.com
```

The `installation_nr` counter auto-increments each time an answer file is served. Combined with the system information data that the installer sends when it fetches the answer, you get fully dynamic provisioning per target.

### Target Filters

Answer files can be scoped with **target filters** — key-value pairs that match the identifying information the installer sends during boot:

- `/product/product=pve` — only Proxmox VE installations
- `/network/interfaces/0/mac=00:1a:2b:*` — match specific MAC ranges
- Default fallback — an answer marked as default is used when no specific filter matches

### Security Tokens

Each automated installation requires an **authentication token** tied to a specific prepared answer. This prevents unauthorized systems from pulling configuration data. The token is embedded into the ISO when you prepare it with `proxmox-auto-install-assistant`:

```bash
proxmox-auto-install-assistant prepare-iso \
  --fetch-answer https://pdm.lab.example.com:8006/api2/json/auto-install/answer \
  /path/to/proxmox-ve-9.2.iso
```

Add the `--answer-token` flag with the token generated in PDM under **Automated Installations → Authentication Tokens**:

```bash
proxmox-auto-install-assistant prepare-iso \
  --fetch-answer https://pdm.lab.example.com:8006/api2/json/auto-install/answer \
  --answer-token pdt-abc123def456 \
  -o /output/proxmox-ve-9.2-auto.iso \
  /path/to/proxmox-ve-9.2.iso
```

Boot the prepared ISO on any target hardware, and it will reach out to PDM, match an answer file, and install fully unattended. Installation progress is visible from the PDM web interface.

## Centralized Subscription Management

If you manage multiple Proxmox nodes — even with the free community repository — keeping track of which nodes have active subscriptions is a chore. PDM 1.1 fixes this with a **centralized subscription key pool**.

From the PDM UI, you can:

- Upload subscription keys
- View which remotes have assigned keys
- Auto-assign keys to remotes without one
- Bring new nodes under subscription automatically (via the answer file subscription key field)

This is especially useful for homelabbers who run a small cluster with a paid subscription on the hypervisor node and want to keep everything consistent without logging into each host.

## Unified Ceph Monitoring

Ceph is a popular choice for hyperconverged storage in Proxmox homelabs, but monitoring Ceph across multiple clusters usually means switching between cluster dashboards. PDM 1.1 aggregates all Ceph health and performance metrics into a single view.

### What You See in the PDM Ceph Dashboard

- **Cluster health** — HEALTH_OK, HEALTH_WARN, HEALTH_ERR status per cluster
- **Capacity** — total and used storage per pool, fill percentages
- **Performance** — OPS, throughput, and latency trends
- **Monitors** — quorum status, mapping
- **Managers** — active/standby state
- **OSDs** — up/down status, weight, utilization, per-OSD IOPS
- **Pools** — PG count, placement groups status, space usage

Instead of clicking through each Proxmox cluster to check "is Ceph healthy?", you glance at a single dashboard and see the status of every Ceph deployment across your entire infrastructure.

## Enhanced Guest and Snapshot Management

PDM 1.1 expands its guest management capabilities. The **unified guest list** shows VMs and containers from all connected remotes in one table, with filtering and sorting across clusters. You can:

- Create, restart, and stop VMs from the central view
- Create and delete snapshots
- Monitor migration status
- Check basic guest configuration without navigating to the remote's interface

Future releases (per the [PDM roadmap](https://pdm.proxmox.com/docs/roadmap.html)) will add bulk actions on virtual guests across the entire selection, richer migration dialogs with bandwidth limits, and a backup-job overview with last-execution status.

## Installing PDM 1.1 in Your Homelab

### Download the ISO

Grab the Proxmox Datacenter Manager ISO from [proxmox.com/downloads](https://www.proxmox.com/downloads).

### Prepare Installation Media

```bash
# Identify your USB device
lsblk

# Write the ISO to USB (replace /dev/sdX with your device)
dd bs=1M conv=fdatasync \
  if=./proxmox-datacenter-manager_1.1.iso \
  of=/dev/sdX
```

### Deploy as a VM on Your Existing Proxmox Host

1. Upload the ISO to your Proxmox VE storage
2. Create a new VM with:
   - **2 vCPUs** (host-type recommended)
   - **4 GB RAM**
   - **40 GB disk** (on your fastest storage)
   - **VirtIO SCSI controller**
   - **Network bridge** on your management VLAN
3. Boot from the ISO and follow the interactive installer
4. After installation, access the web UI at `https://<pdm-ip>:8006/`

### Adding Your First Remote

1. Log into PDM web interface
2. Navigate to **Datacenter → Remotes → Add**
3. Enter your Proxmox VE node IP or hostname
4. Provide root credentials or an API token
5. PDM discovers the remote's capabilities and adds it to your central dashboard

You can add standalone nodes or entire clusters — PDM handles both. Once connected, you see VMs, storage, Ceph health, and subscription status from one screen.

## The Road Ahead

The [PDM roadmap](https://pdm.proxmox.com/docs/roadmap.html) reveals an ambitious future:

- **Resource organization** — folders as hierarchical entities, independent tag labeling, finer-grained ACL schema
- **SDN integration** — stretch EVPN VNets across clusters, multi-VRF support, automated route-target import/export
- **Integrated firewall management**
- **Proxmox Backup Server** deeper integration — job status, datastore browsing, prune retention
- **Proxmox Mail Gateway** as a remote type
- **Notifications** — PDM as a notification target for remotes
- **Active-standby high availability** for PDM itself

The foundation being laid in 1.1 — automated installs, unified monitoring, centralized subscriptions — sets the stage for PDM to become the indispensable management layer for Proxmox at any scale.

## Conclusion

Proxmox Datacenter Manager 1.1 is a significant leap forward. The automated installation system alone makes it worth deploying in any homelab with more than one node — no more manual clicking through installation prompts, no more configuration drift across hosts. Add unified Ceph monitoring and centralized subscriptions, and you have a management tool that closes the gap between Proxmox and proprietary hypervisor platforms.

If you run multiple Proxmox nodes, spin up a PDM VM today. The vCenter-for-Proxmox dream is real, and it keeps getting better.
