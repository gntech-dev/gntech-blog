---
title: "About"
description: "Gerlin Nolasco, the GnTech homelab, and how these practical infrastructure guides are prepared."
date: 2026-05-08
lastmod: 2026-10-30
translationKey: about
---

Hi, I'm **Gerlin Nolasco**, the person behind **GnTech**.

I document the infrastructure I build, troubleshoot, and maintain: Proxmox hosts, MikroTik networks, Linux and Windows systems, Docker services, and remote administration tools. The goal is to turn a real problem into a guide another person can understand and follow.

## What you'll find here

- **Virtualization and storage:** Proxmox VE, VMs, LXC, ZFS, and backups.
- **Networking:** MikroTik, VLANs, routing, VPNs, and management access.
- **Self-hosting:** Docker Compose, reverse proxies, monitoring, and service maintenance.
- **Troubleshooting:** the symptoms, diagnostic steps, changes, and verification behind a fix.
- **Useful older hardware:** practical experiments such as my ThinkPad T420 administration laptop.

Browse the [projects](/projects/) for a starting point, use [search](/search/) for a specific problem, or explore the [archives](/archives/).

## The lab behind the posts

My work spans a home lab and hosted infrastructure. Proxmox provides the virtualization layer; MikroTik handles routing and segmentation; Docker and LXC host services. Monitoring, backups, and recovery access are part of the work too.

The lab changes over time. Each guide describes its own environment; an older hardware list or diagram should not be treated as a live inventory. I keep public examples focused on the details needed to explain the procedure.

## How posts are prepared

AI assists with drafting, organizing explanations, preparing illustrations, and checking examples. I review proposed changes through GitHub pull requests before merging them. Merging a publication-ready post triggers the site's normal Cloudflare Pages deployment.

Automated checks can catch build problems, missing assets, broken internal links, and some syntax errors. They cannot establish that a command works on a particular machine or that a procedure is safe for every environment.

The articles should distinguish observed lab results from proposed examples and explain relevant validation limits. A syntax check is not a hardware test. Check prerequisites and versions, preserve a recovery path, and verify the result in your own environment.

Generated illustrations are identified as illustrations. Real screenshots and command output, when included, serve a different purpose: showing what was actually observed.

## About the site

GnTech runs on [Hugo](https://gohugo.io/) with the [PaperMod theme](https://github.com/adityatelange/hugo-PaperMod), hosted on Cloudflare Pages. The blog is available in English and Spanish; translation coverage grows as guides are reviewed.

## Connect

- [GitHub: gntech-dev](https://github.com/gntech-dev)
- [LinkedIn: Gerlin Nolasco](https://www.linkedin.com/in/gnolascohernandez/)
- [Subscribe through RSS](/index.xml)
