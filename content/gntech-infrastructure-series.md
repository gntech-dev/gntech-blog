---
title: "GNTECH Infrastructure Deployment Series"
description: "A guided roadmap for building a secure hybrid GNTECH-style infrastructure, from architecture to disaster recovery."
date: 2026-11-01T19:00:00-04:00
draft: false
ShowToc: true
---

# GNTECH Infrastructure Deployment Series

**Building a Secure Hybrid Homelab from Scratch**

This is the reading hub for a **planned twelve-part deployment series** covering Hetzner and home Proxmox, MikroTik routing, Microsoft identity, Cloudflare Zero Trust, container hosting, backups, and observability.

The sequence is a **publication plan**, not a claim that every component has been deployed or tested. All public-facing tutorials will use sanitized example addresses and credentials, identify prerequisites, and distinguish a reproducible example from a live-verified configuration.

## Publication roadmap

| Part | Topic | Status | Read now |
| --- | --- | --- | --- |
| 01 | Architecture and design: trust boundaries, network plan, inventory | Existing article | [Part 01 — Architecture and Design](/posts/2026-11-01-gntech-infrastructure-part-01-architecture/) |
| 02 | Hetzner Proxmox foundation: installation, ZFS, management, recovery | Article ready for review | [Part 02 — Hetzner Proxmox Foundation](/posts/2026-11-01-gntech-infrastructure-part-02-hetzner-proxmox/) |
| 03 | Two MikroTik CHR routers: isolated transit bridges and routed IPs | Article ready for review | [Part 03 — Dual MikroTik CHR](/posts/2026-11-01-hetzner-proxmox-dual-mikrotik-chr/) |
| 04 | Proxmox firewall: forwarding, SNAT, IPv6, isolation | Planned | [Proxmox firewall guide](/posts/2026-06-16-proxmox-firewall-security-hardening/) |
| 05 | Home-to-Hetzner networking: routing, VPN, fail-safe access | Planned | [MikroTik WireGuard](/posts/2026-05-08-mikrotik-wireguard-vpn/) |
| 06 | Active Directory: Windows Server, DNS, domain controllers | Planned | [Windows Server GPO guide](/posts/2026-05-14-windows-server-2025-group-policy-management/) |
| 07 | Hybrid identity: Entra ID, synchronization, SSO, MFA | Planned | [Entra Connect Sync](/posts/2026-05-14-windows-server-2025-entra-connect-sync/) |
| 08 | Cloudflare Zero Trust: tunnels and authenticated administration | Planned | [Cloudflare Tunnel for Docker](/posts/2026-05-14-cloudflare-tunnel-docker/) |
| 09 | Container platform: Docker Compose, Traefik, application deployment | Planned | [Traefik reverse proxy](/posts/2026-05-09-traefik-reverse-proxy-docker/) |
| 10 | Backup and disaster recovery: PBS, ZFS, restore drills | Planned | [PBS setup](/posts/2026-05-08-proxmox-backup-server-setup/) |
| 11 | Monitoring: Prometheus, Grafana, Loki, Uptime Kuma | Planned | [Monitoring stack](/posts/2026-05-17-homelab-monitoring-stack/) |
| 12 | End-to-end security validation and operational handoff | Planned | [MikroTik firewall rules](/posts/2026-05-24-mikrotik-firewall-rules/) |

**Status key:** *Planned* means the dedicated series installment is not yet written. A linked existing article is supporting reading, **not** a completed series part. Part 03 reuses the established URL of the original standalone tutorial; series metadata and safeguards are proposed for review.

## Supporting reading by workstream

### Network and virtualization
- [Proxmox bridges and VLANs](/posts/2026-05-08-proxmox-networking-bridges-vlans/)
- [Proxmox cloud-init templates](/posts/2026-05-16-proxmox-cloudinit-vm-templates/)
- [MikroTik VLAN segmentation](/posts/2026-05-12-mikrotik-vlan-segmentation/)
- [Building MikroTik R1](/posts/r1-router-deployment/)

### Remote administration and security
- [MeshCentral behind Cloudflare Tunnel](/posts/2026-10-31-meshcentral-cloudflare-tunnel/)
- [Troubleshoot Guacamole RDP latency](/posts/2026-11-01-guacamole-rdp-cloudflare-latency/)
- [Intel AMT Serial over LAN on Proxmox](/posts/2026-10-30-intel-amt-sol-proxmox/)
- [Windows LAPS OU delegation](/posts/2026-11-01-windows-laps-ou-delegation/)

### Containers, backup, and observability
- [Docker Compose patterns](/posts/2026-05-08-docker-compose-patterns/)
- [Proxmox backup strategy](/posts/2026-05-23-proxmox-backup-strategies/)
- [Restic recovery workflow](/posts/2026-05-19-restic-docker-backup-strategy/)
- [Prometheus and Grafana](/posts/2026-05-21-prometheus-grafana-monitoring-stack/)

## How the series will be published

Each future part should provide a scope and architecture diagram, prerequisites, version assumptions, copy/paste-ready commands with placeholders, a validation checklist, security notes, troubleshooting, rollback, and links to preceding and following parts. Never publish real public IP addresses, API tokens, domain secrets, internal credentials, or unique private identifiers.

Publication order should follow dependencies, but the index can be updated independently. Existing standalone articles remain at their current URLs to avoid breaking links; cross-link or add series metadata only after editorial review.

**Next planned deliverable:** Part 04 — Proxmox Firewall and Network Isolation.
