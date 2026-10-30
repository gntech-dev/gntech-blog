---
title: "Projects"
description: "Explore GnTech projects and the practical guides behind the home lab."
date: 2026-05-08
lastmod: 2026-10-30
translationKey: projects
---

These projects connect the lab's infrastructure work to the guides on this blog. The links are reading paths, not a live service inventory.

## Networking and segmentation

MikroTik routing and VLANs provide the foundation for separating users, servers, and devices. Start with the router walkthrough, then follow how the Proxmox bridges connect to the network.

- [Building R1: a MikroTik router for a VLAN-segmented homelab](/posts/r1-router-deployment/)
- [Proxmox networking: bridges, VLANs, and host topology](/posts/2026-05-08-proxmox-networking-bridges-vlans/)

## Self-hosted services

Docker Compose provides repeatable definitions for services and their dependencies. These guides cover patterns used across deployments and a concrete camera-system project.

- [Docker Compose patterns for homelab stacks](/posts/2026-05-08-docker-compose-patterns/)
- [Deploying Frigate NVR on Proxmox](/posts/frigate-deployment/)

The Frigate article documents an earlier deployment. Check its environment and version assumptions before adapting it.

## Administration and recovery access

A useful administration setup includes a client machine and a way back into a host when its usual interface is unavailable.

- [ThinkPad T420 with Arch Linux and i3](/posts/2026-10-30-thinkpad-t420-arch-i3/)
- [Intel AMT Serial over LAN on Proxmox](/posts/2026-10-30-intel-amt-sol-proxmox/)

The T420 article separates the machine's installed hardware from planned upgrades. The SOL article separates observed console behavior from the generalized setup procedure.

## Documentation and publishing

This blog turns project notes into reviewed guides. AI helps prepare the material, and GitHub pull requests provide the review step before publication. See [About](/about/) for the process and its validation limits.

For more subjects, use [search](/search/), browse the [archives](/archives/), or [subscribe through RSS](/index.xml).
