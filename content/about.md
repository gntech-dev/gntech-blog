---
title: "About"
description: "About this blog, the person behind it, and the automation that writes it"
date: 2026-05-08
---

GnTech is a homelab tinkerer, network nerd, and automation enthusiast. This blog is where I write down what I build — and what breaks along the way — so future-me can actually remember how I solved that weird GPON issue at 2 AM.

### The Homelab Stack

- **Servers:** Proxmox cluster (SRV1 primary)
- **Network:** MikroTik E62iUGS-2axD5axT (R1), VLAN segmentation, GPON/FTTH, WireGuard VPN
- **Containers:** Docker, LXC
- **Automation:** OpenClaw Gateway (Zeny IA)
- **Monitoring:** Frigate NVR, Uptime Kuma, various dashboards
- **Cameras:** Tapo C100, Frigate with OpenVINO

### About This Blog

This site runs on [Hugo](https://gohugo.io/) with the [PaperMod](https://github.com/adityatelange/hugo-PaperMod) theme, served through Cloudflare Pages.

The interesting part? Posts are drafted automatically by an AI assistant (Zeny IA) every morning at 07:00 AST. A new topic is picked based on what's already covered, the draft is written with proper Hugo front matter, verified with a clean Hugo build, then sent to my Telegram with inline Approve/Skip buttons. If I tap Approve, it commits and deploys automatically.

This is both a blog and a living experiment in AI-assisted infrastructure documentation.

### What You'll Find Here

- Proxmox configurations and hard-won lessons
- MikroTik RouterOS deep dives (VLANs, WireGuard, Cloudflare Tunnels, GPON)
- Docker Compose patterns
- Security camera and NVR setups
- Network performance tuning
- Automation workflows
- Whatever else I'm tinkering with at 2 AM

Posts here are notes to future me — publicly posted in case they help someone else too.
