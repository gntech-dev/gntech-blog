---
title: "About"
description: "About this blog, the person behind it, and the automation that writes it"
date: 2026-05-08
lastmod: 2026-05-10
---

Hi, I'm **Gerlin Nolasco** — the person behind **GnTech**.

GnTech is my personal tech space where I document, test, and share practical knowledge about **networking, homelab infrastructure, servers, virtualization, automation, cybersecurity basics, and self-hosted services**.

This blog is focused on real-world learning. Most of the content comes from things I personally build, break, fix, and improve in my own lab environment.

My goal with GnTech is simple: create useful technical notes, guides, and project write-ups that can help others understand complex topics in a clear and practical way. I believe the best way to learn technology is by building it yourself. That is why this blog is not just theory — it is based on hands-on experience, troubleshooting, and continuous improvement.

---

### What You'll Find Here

- **Networking & Routing** — MikroTik RouterOS, VLAN segmentation, IPv6, GPON/FTTH
- **Virtualization** — Proxmox VE, container orchestration, VM management
- **Self-Hosting** — Docker services, Cloudflare Tunnels, monitoring stacks, backup strategies
- **Security** — Firewall design, VLAN isolation, IoT hardening, secure remote access
- **Automation** — AI-assisted ops, scripting, Telegram bots, cron workflows
- **Infrastructure** — Linux and Windows Server, storage, rack hardware, cabling

---

### The Homelab Stack

- **Router:** MikroTik hAP ax S (R1) — Edge gateway, ROS 7.22.1
- **Wi-Fi / Switch:** MikroTik hAP ac² (R2) — Secondary AP, downstream switch
- **Servers:** Proxmox cluster: G3 (i5-7500T), G4 (Ryzen 2400GE), G1 (i3-4030U), H1 (Xeon E-2276G remote)
- **Containers:** Docker, LXC
- **Automation:** OpenClaw Gateway (Zeny IA)
- **Monitoring:** Uptime Kuma, Grafana dashboards
- **Cameras:** Frigate NVR, Tapo C100
- **VPN:** WireGuard via MikroTik DDNS
- **WAN:** Claro GPON FTTH via PPPoE on VLAN 100

---

### About This Blog

This site runs on [Hugo](https://gohugo.io/) with the [PaperMod](https://github.com/adityatelange/hugo-PaperMod) theme, served through Cloudflare Pages.

The interesting part? Posts are drafted automatically by an AI assistant (Zeny IA) every morning at 07:00 AST. A new topic is picked based on what's already covered, the draft is written with proper Hugo front matter, verified with a clean Hugo build, then sent to my Telegram with inline Approve/Skip buttons. If I tap Approve, it commits and deploys automatically.

This is both a blog and a living experiment in AI-assisted infrastructure documentation.

---

### Connect With Me

- GitHub: [gntech-dev](https://github.com/gntech-dev)
- LinkedIn: [gnolascohernandez](https://www.linkedin.com/in/gnolascohernandez/)

---

**GnTech — Building, learning, and documenting technology one lab at a time.**
