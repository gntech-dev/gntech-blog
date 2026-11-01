---
title: "Start Here"
description: "Choose a practical reading path through Proxmox, MikroTik, Docker, and homelab administration."
date: 2026-10-30T14:00:00-04:00
draft: false
translationKey: start-here
ShowToc: true
lastmod: 2026-11-01
---

For a complete, ordered deployment journey, visit the [GNTECH Infrastructure Deployment Series](/gntech-infrastructure-series/), which tracks planned installments and related published guides.

Welcome to **GnTech**. Pick the problem you want to solve, then follow a short path through the guides. You do not need to read the blog in publication order.

| Your goal | Start with |
| --- | --- |
| Build a virtualized lab | [Proxmox foundations](#proxmox-foundations) |
| Separate users, servers, and devices | [MikroTik networking](#mikrotik-networking) |
| Run and maintain your own services | [Docker Compose](#docker-compose) |
| Back up services and prove recovery | [Backup and recovery](#backup-and-recovery) |
| Administer and recover your machines | [Administration and recovery](#administration-and-recovery) |

## Proxmox foundations

Begin with networking so you understand where the host and guests connect. Then make guest deployment repeatable and plan backups.

1. [Bridges, VLANs, and host topology](/posts/2026-05-08-proxmox-networking-bridges-vlans/) — understand the network before changing it.
2. [Cloud-init VM templates](/posts/2026-05-16-proxmox-cloudinit-vm-templates/) — prepare reusable guest configurations.
3. [Proxmox Backup Server](/posts/2026-05-08-proxmox-backup-server-setup/) — learn the backup service and datastore workflow.

**Practice goal:** draw the host-to-guest network path, deploy a disposable guest, and test recovery before relying on a backup.

## MikroTik networking

These guides assume you have access to the router and understand the interfaces you are changing. Keep a recovery connection available when working on management access or VLAN filtering.

1. [Building R1](/posts/r1-router-deployment/) — see the pieces of a segmented router configuration.
2. [VLAN segmentation](/posts/2026-05-12-mikrotik-vlan-segmentation/) — work through routing, DHCP, and isolation.
3. [Proxmox networking](/posts/2026-05-08-proxmox-networking-bridges-vlans/) — connect the router-side design to the virtualization host.

**Practice goal:** verify both permitted traffic and a connection that should be blocked.

## Docker Compose

Start with a small service stack. Understand its storage, configuration, and startup behavior before adding more applications.

1. [Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — organize services and their configuration.
2. [Health checks and startup dependencies](/posts/2026-05-14-docker-compose-healthchecks/) — distinguish a running process from a ready service.
3. [Frigate deployment](/posts/frigate-deployment/) — explore a concrete camera-system example after the basics.

**Practice goal:** recreate a disposable stack and confirm that its intended data survives. The Frigate guide describes an earlier deployment; check its version and hardware assumptions.

## Backup and recovery

Choose the recovery target first, then follow the relevant workflow:

1. [Backup strategy and independent copies](/posts/2026-05-23-proxmox-backup-strategies/) — define recovery targets and the failures each copy must survive.
2. For guests, use [PBS setup and isolated guest recovery](/posts/2026-05-08-proxmox-backup-server-setup/). For PostgreSQL, use the [dump, scheduling, and complete Restic-to-database recovery lab](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/).
3. Use the [Restic file and repository-copy lab](/posts/2026-05-19-restic-docker-backup-strategy/) to understand encrypted file recovery and separate repository passwords.

**Practice goal:** recover into an isolated destination using the copy and credentials that will be available after a failure. Local CI repositories demonstrate the commands; they do not prove your real off-site storage or hardware recovery.

## Administration and recovery

A comfortable client and a tested recovery console solve different parts of the administration problem.

1. [ThinkPad T420 with Arch Linux and i3](/posts/2026-10-30-thinkpad-t420-arch-i3/) — build a focused administration desktop.
2. [Intel AMT Serial over LAN on Proxmox](/posts/2026-10-30-intel-amt-sol-proxmox/) — set up text-console login and learn how to disconnect cleanly.

3. [MeshCentral with Cloudflare Tunnel](/posts/2026-10-31-meshcentral-cloudflare-tunnel/) — deploy a remote-support console, enroll a test agent, and check relayed sessions.
4. [Troubleshoot slow Guacamole RDP through Cloudflare Tunnel](/posts/2026-11-01-guacamole-rdp-cloudflare-latency/) — isolate browser, gateway, and Windows latency with a controlled A/B test.

**Practice goal:** connect to the intended host, verify its identity, log out, and reconnect to a fresh login prompt.

## How to use a guide

Check the prerequisites, software versions, and validation notes before copying commands. Separate measured lab results from example configurations. Keep backups and recovery access appropriate to the change, and verify the result instead of assuming a successful command means the whole system works.

For a specific symptom, use [search](/search/). For more context, browse [projects](/projects/), read [about the blog](/about/), or explore [all posts](/archives/). Follow new posts through [RSS](/index.xml).
