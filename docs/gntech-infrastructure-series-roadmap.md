# GNTECH Infrastructure Series — Editorial Roadmap

Created: 2026-11-01

## Goal and boundaries

Produce twelve reproducible English tutorials that explain a GNTECH-style hybrid infrastructure without exposing actual deployment secrets. The series index is at `content/gntech-infrastructure-series.md`. Keep existing posts at their established URLs. Treat them as references, not proof of a series installment.

## Production sequence

1. Architecture and design — topology, trust zones, address plan, management boundaries, assumptions.
2. Hetzner Proxmox foundation — install, ZFS, host routing, recovery access.
3. Dual MikroTik CHR — bridge topology, point-to-point transit, routed additional IPv4, isolated LANs. Existing article: `content/posts/2026-11-01-hetzner-proxmox-dual-mikrotik-chr.md`.
4. Proxmox firewall and IPv6 — forwarding rules, anti-spoofing, SNAT, explicit IPv6 routes.
5. Home/Hetzner connectivity — site-to-site design, route ownership, failover and isolation.
6. Windows Server and AD DS — DC roles, DNS, OU and policy design.
7. Entra hybrid identity — synchronization, conditional access, service identity, MFA.
8. Cloudflare Zero Trust — tunnel ingress, Access policies, private admin.
9. Docker/Traefik — deployment patterns, certificates, persistent storage.
10. Backup/recovery — PBS, ZFS snapshots, restore drills, failure scenarios.
11. Monitoring — Prometheus, Grafana, Loki, Blackbox, Uptime Kuma.
12. End-to-end security and operations — test matrix, runbooks, updates, handoff.

## Existing article inventory and reuse

- Part 01–02 background: `2026-05-08-proxmox-networking-bridges-vlans.md`, `2026-05-16-proxmox-cloudinit-vm-templates.md`, `2026-05-20-proxmox-security-hardening.md`.
- Part 03: `2026-11-01-hetzner-proxmox-dual-mikrotik-chr.md` (standalone; do not rewrite or renumber without review).
- Part 04–05: `2026-06-16-proxmox-firewall-security-hardening.md`, `2026-05-12-mikrotik-vlan-segmentation.md`, `2026-05-08-mikrotik-wireguard-vpn.md`, `r1-router-deployment.md`.
- Part 06–07: `2026-05-14-windows-server-2025-group-policy-management.md`, `2026-05-14-windows-server-2025-entra-connect-sync.md`, `2026-05-14-windows-server-2025-entra-hybrid-join.md`, `2026-11-01-windows-laps-ou-delegation.md`.
- Part 08: `2026-05-14-cloudflare-tunnel-docker.md`, `2026-10-31-meshcentral-cloudflare-tunnel.md`, `2026-11-01-guacamole-rdp-cloudflare-latency.md`.
- Part 09: `2026-05-08-docker-compose-patterns.md`, `2026-05-09-traefik-reverse-proxy-docker.md`.
- Part 10: `2026-05-08-proxmox-backup-server-setup.md`, `2026-05-23-proxmox-backup-strategies.md`, `2026-05-19-restic-docker-backup-strategy.md`.
- Part 11: `2026-05-17-homelab-monitoring-stack.md`, `2026-05-21-prometheus-grafana-monitoring-stack.md`, `2026-06-01-uptime-kuma-docker-monitoring-dashboard.md`.
- Part 12: `2026-05-24-mikrotik-firewall-rules.md`, `2026-10-30-intel-amt-sol-proxmox.md`.

## Editorial acceptance criteria

- Verify the exact source filename and Hugo URL before adding each link.
- Clearly label *planned*, *published*, and *validated* separately.
- Use safe sample IPs (RFC 5737 for IPv4), redacted hostnames and credentials.
- Provide a network diagram with useful alt text for each technical installment.
- Prefer `docker compose`, `cat` heredocs, and explicit verification/rollback commands.
- Cite official documentation for vendor-sensitive claims and identify version assumptions.
- Run Hugo build, internal-link and image checks in CI before merge.
- Never merge automatically; review each PR.
- After each installment, update the index status and link to the next planned part.

## Not in this PR

No Part 01 article, production topology disclosure, deployment change, or retrospective rewriting of existing posts.
