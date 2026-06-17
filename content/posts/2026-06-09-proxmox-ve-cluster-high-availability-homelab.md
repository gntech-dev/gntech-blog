---
title: "Proxmox VE Cluster Setup and High Availability for Homelab"
description: "Build a Proxmox VE cluster with live migration and HA failover. Covers corosync, quorum, 2-node QDevice setup, HA groups, and fencing for homelab high availability."
date: 2026-06-09T14:30:00-04:00
tags:
  - proxmox
  - virtualization
  - homelab
  - high-availability
  - linux
keywords:
  - Proxmox VE cluster setup high availability homelab guide
  - 2-node Proxmox cluster QDevice corosync quorum configuration
  - Proxmox HA group VM failover fencing watchdog
  - Proxmox corosync cluster network configuration best practices
  - Proxmox live migration shared storage NFS Ceph
  - Proxmox cluster quorum split-brain prevention
  - Homelab high availability Proxmox cluster step-by-step
summary: "A step-by-step guide to building a Proxmox VE cluster with high availability for your homelab — covering corosync setup, quorum with QDevice, HA groups, live migration, and fencing."
canonical: "https://blog.gntech.me/posts/proxmox-ve-cluster-high-availability-homelab/"
---

If you started your homelab on a single Proxmox host, you already know the pain: planned maintenance means shutting everything down, a hardware failure takes out every VM and container, and there is no live migration without a second node.

Adding a second Proxmox host is the natural next step, but a two-node cluster comes with its own challenges — especially around quorum and split-brain prevention. This guide walks through building a Proxmox VE cluster from scratch with high availability, using a **QDevice** as the tiebreaker vote to solve the two-node quorum problem, all while keeping the setup homelab-practical.

## Why Cluster Proxmox — Live Migration and HA Failover

Clustering Proxmox nodes unlocks three major capabilities you cannot get on standalone hosts:

- **Live migration** — move running VMs between nodes with zero downtime
- **Unified management** — single web UI across all nodes with cluster-wide resource views
- **High availability** — automatic VM failover when a node goes offline

Proxmox clustering uses **corosync** for membership and quorum communication, and **pmxcfs** (the Proxmox Cluster File System) to synchronise configuration across all nodes in real time.

## Prerequisites and Planning

Before creating the cluster, make sure you have:

- **Two or more Proxmox VE 9.x hosts** — all running the same major version
- **Shared storage** — NFS, iSCSI, Ceph, or ZFS over SSH for live migration
- **Dedicated cluster network** — a separate VLAN or physical link for corosync traffic (recommended)
- **A QDevice host** — a lightweight Debian machine (RPi, LXC container, or tiny VM) that will act as the quorum tiebreaker
- **Root SSH access** to all nodes and the QDevice host

For the rest of this guide, I will use these hostnames and IPs:

| Host | Role | IP |
|------|------|----|
| `proxmox01` | Cluster node 1 | 10.0.20.30 |
| `proxmox02` | Cluster node 2 | 10.0.20.31 |
| `pve-qdevice` | QDevice (LXC) | 10.0.20.10 |

## Creating the Proxmox Cluster

On the first node, initialise the cluster:

```bash
pvecm create homelab-cluster
```

This creates a corosync configuration, generates the necessary certificates, and starts the cluster services. Verify it worked:

```bash
pvecm status
```

On the second node, join the cluster using the IP of the first node and the cluster secret:

```bash
pvecm add 10.0.20.30
```

The `--force` flag bypasses the hostname conflict check. If you set unique hostnames during installation (which you should), you can omit it.

After both nodes are joined, confirm the cluster status:

```bash
pvecm status
# Cluster name: homelab-cluster
# Node(s):
#   Node name: proxmox01 (votes: 1)
#   Node name: proxmox02 (votes: 1)
# Quorum: 2/2
```

## Cluster Networking Best Practices

Corosync traffic should be isolated from regular VM and storage traffic. If your hosts have multiple NICs, configure a dedicated cluster network:

```bash
# On both nodes, add your cluster-only bridge (e.g. vmbr1)
# Then configure corosync to bind to that link.
```

Edit `/etc/pve/corosync.conf` to set the `bindnetaddr`:

```yaml
totem {
    version: 2
    cluster_name: homelab-cluster
    transport: knet
    crypto_cipher: aes-256-gcm
    crypto_hash: sha512
}

nodelist {
    node {
        ring0_addr: 10.0.20.30
        name: proxmox01
        nodeid: 1
    }
    node {
        ring0_addr: 10.0.20.31
        name: proxmox02
        nodeid: 2
    }
}

quorum {
    provider: corosync_votequorum
}
```

Verify corosync link health:

```bash
corosync-cfgtool -s
# Printing ring status.
# Local node ID 1
# RING ID 0
# 	id	= 10.0.20.30
# 	status	= ring 0 active with no faults
```

If you see "no faults", the cluster link is healthy. Any faults here indicate network issues that will cause HA failures later.

## Setting Up Shared Storage

VMs cannot live-migrate without shared storage. The simplest approach for a homelab is an NFS export from a NAS or a dedicated VM.

Add the NFS storage via the web UI (Datacenter → Storage → Add → NFS) or `/etc/pve/storage.cfg`:

```ini
nfs: nfs-storage
	path /mnt/pve/nfs-storage
	server 10.0.20.5
	export /srv/nfs/proxmox
	content images,rootdir,vztmpl,backup
	options vers=4.2,soft,timeo=600
	maxfiles 0
```

For homelabs without dedicated NAS hardware, **ZFS over SSH replication** is a solid alternative — configure a ZFS dataset on each node and use Proxmox's built-in replication scheduler. The trade-off is that replication is not real-time; typical intervals are 5–15 minutes.

## Solving the Two-Node Quorum Problem with QDevice

A two-node cluster has a fundamental problem: if one node fails, the surviving node holds only 1 out of 2 votes — not enough to reach quorum. This triggers corosync to fence (reboot) the surviving node, taking down every VM.

The fix is an external **QDevice** — a lightweight third vote that does not run any VMs. It lives on a separate host and votes alongside the cluster nodes.

### Step 1 — Prepare the QDevice Host

I run my QDevice as a Debian LXC container on a third Proxmox host (or the same hardware, on a different physical link). Install the required package:

```bash
apt update && apt install -y corosync-qdevice
```

The QDevice host needs SSH root access from the cluster nodes. Generate a key on the first cluster node and copy it:

```bash
ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_qdevice
ssh-copy-id -i /root/.ssh/id_qdevice root@10.0.20.10
```

### Step 2 — Add the QDevice to the Cluster

From any cluster node, run:

```bash
pvecm qdevice setup 10.0.20.10 --ssh-identity /root/.ssh/id_qdevice
```

This pushes the cluster certificate to the QDevice, configures corosync-qdevice on both sides, and starts the service.

### Step 3 — Verify Quorum

```bash
pvecm status
```

You should now see three votes available:

```
Quorum information:
  Votes:          2
  Expected votes: 3
  Quorum:         2/3
```

The QDevice does not appear in the Proxmox web UI, but `pvecm status` and `corosync-quorumtool -s` confirm it is active. The cluster now tolerates a single node going offline — 2 out of 3 votes still form quorum.

## Enabling High Availability

With quorum solved, enable the Proxmox HA stack:

```bash
systemctl enable --now pve-ha-lrm pve-ha-manager
```

Run this on **every node** in the cluster.

### Fencing

Fencing (STONITH) ensures that a non-responsive node is forcefully rebooted before the cluster tries to recover its VMs. Proxmox uses **watchdog** timers for self-fencing.

On each node, check the watchdog:

```bash
dmesg | grep watchdog
# [    0.456789] softdog: initialized. soft_noboot=0 soft_margin=60 sec
```

If no hardware watchdog is available, the `softdog` kernel module provides a software watchdog:

```bash
echo softdog > /etc/modules-load.d/watchdog.conf
modprobe softdog
systemctl restart corosync
```

With fencing in place, a failed node will be fenced within 60 seconds, and the surviving node will restart the impacted VMs.

## Creating HA Groups and Resources

HA groups control the order and preferred nodes for VM placement.

### Create an HA Group

Via the CLI:

```bash
ha-manager add_group critical \
    --nodes "proxmox01,proxmox02" \
    --type ordered \
    --nofailback 0
```

- `--type ordered` — prefer the first-listed node
- `--nofailback 0` — allow failback when the preferred node returns

### Add VMs to HA

```bash
# Add VM 100 to the critical group with max 2 restart attempts
ha-manager add vm:100 --group critical --max_restart 2
```

For containers, use `ct:` instead of `vm:`:

```bash
ha-manager add ct:200 --group critical
```

### Monitor HA Status

```bash
ha-manager status
# quorum  OK
# Group(s):
#   critical:
#     nodes proxmox01,proxmox02
#     VM 100   proxmox01    started
#     CT 200   proxmox01    started
```

From the web UI: navigate to Datacenter → HA → Groups to manage groups visually, or Datacenter → HA → Resources to add and watch managed VMs.

## Testing HA Failover

Do not skip this step. A cluster is only as trustworthy as the testing you put it through.

### Graceful Failover Test

Stop corosync on the active node:

```bash
# On proxmox01
systemctl stop corosync
```

On proxmox02, the HA manager will detect the loss of quorum for proxmox01, wait for the watchdog to fence it, then start VMs:

```bash
watch ha-manager status
```

Within 60–120 seconds, you should see:

```
VM 100   proxmox02    started
CT 200   proxmox02    started
```

To bring the node back, start corosync:

```bash
systemctl start corosync
```

The node rejoins automatically. If nofailback is enabled, VMs stay on proxmox02 until you manually migrate them back.

### Hard Fencing Test

For a more realistic test, pull the power (or unplug the network) on one node. The other node should fence and recover VMs within the watchdog timeout window.

## Production Considerations for Homelab Clusters

A few things to keep in mind as you move beyond the basic setup:

- **Three nodes eliminate the QDevice need entirely.** With three Proxmox hosts, you can run Ceph as native shared storage and have natural quorum (2/3 votes). This is the ideal homelab topology if you have the hardware.
- **Run the QDevice as an LXC on a third Proxmox host** to avoid adding a separate physical machine. Create a Debian 13 unprivileged container with nesting enabled and install `corosync-qdevice` inside it. This is what I do, and it works flawlessly.
- **Backups are still mandatory.** High availability handles node failure, not filesystem corruption, accidental `rm -rf`, or data loss. Pair your HA cluster with **Proxmox Backup Server** for scheduled backups.
- **Cluster filesystem replication.** pmxcfs synchronises `/etc/pve/` across all nodes — including `corosync.conf`, storage configs, user permissions, and VM configs. Any change on one node propagates instantly.

## Conclusion

Building a Proxmox VE cluster with high availability in your homelab is not as complicated as it sounds. The core stack — corosync for membership, QDevice for quorum, watchdog for fencing, and the HA manager for recovery — has been battle-tested in production environments for years. With two modest Proxmox hosts, a cheap Raspberry Pi (or a spare LXC), and shared storage, you get enterprise-grade HA at homelab prices.

Start with one cluster, enable HA on your most critical VMs, run the failover test, and then expand from there.
