# Repository-wide article source review — October 31, 2026

Reviewed snapshot: `6279bfa3a39de05942654f803ccf113ad89e26ec`.

## Coverage and limits

All **176 article files** in this snapshot were retrieved, including the Spanish AMT translation and historical introductory/deployment posts. Section index files are excluded. This is a complete source-level sweep, with targeted technical corrections; **it is not a full factual certification or an infrastructure execution test of every article**.

The earlier [October 30 audit](content-audit-2026-10-30.md) records the initial site-wide build and targeted corrections. Subsequent focused PRs rewrote many foundational guides. This pass checks the remaining collection together instead of assigning the reader another “next article.”

## Changes in this batch

**23 articles corrected.** Changes include malformed YAML and fence labels, undefined YAML anchors, incorrect Compose interpolation, misplaced Prometheus relabeling, inaccurate Compose version requirements, misleading Docker socket authorization wording, and undocumented blanket execution claims.

The Vaultwarden guide is rewritten around a private HTTPS bootstrap, registration closure, current notifications, complete recovery materials and a separate restore instance. Unsupported Bitwarden incident/free-tier claims, broken backup sidecars, missing rclone assumptions, and guessed ownership changes are removed.

No article URL or draft state is changed. No article is deleted or automatically unpublished. Existing PRs #35 and #38 retain their scope and remain separate.

## Checks actually run

| Check | Result |
|---|---|
| Article inventory and retrieval | 176/176 files, no retrieval failures |
| YAML/TOML front matter | Parsed for every article |
| Bash/sh/shell fences | 1,834 blocks parsed with bash -n, without execution |
| YAML/yml fences | 538 parsed after corrections; multi-document streams and application-specific tags supported |
| Embedded Vaultwarden Compose | Parsed; loopback publication checked |
| Markdown prose article/image source references | 117 checked; no missing source targets found |
| Runtime infrastructure tests | Not performed |
| Hugo rendering and rendered anchors | Delegated to this PR's publishing CI; source targets are not a replacement |
| External links and version facts | Selected primary references reviewed; no exhaustive freshness crawl |

YAML parsing does not establish Compose completeness, application schemas, permissions or runtime behavior. Some snippets are intentionally partial or show incorrect examples for comparison. Application-specific tags such as Home Assistant !secret and Oxidized !ruby/regexp are treated as tags, not syntax defects.

## Existing review PRs

- [#38: Correct Btrfs versus ZFS support and storage comparison](https://github.com/gntech-dev/gntech-blog/pull/38) — open at inventory time.
- [#35: Consolidate overlapping ZFS replication guide and preserve its URL](https://github.com/gntech-dev/gntech-blog/pull/35) — open at inventory time.

## Remaining validation boundaries

The source sweep is complete. **Deep technical validation is not complete for the entire archive.** Historical release, pricing, performance and compatibility claims may still require verification. Do not interpret a clean parser result as a recommendation to execute a procedure.

The following source indicators are recorded per article for review: device/pool creation and deletion, privileged Docker access, mutable image tags, sample credentials and production/test claims. They are **triage indicators, not confirmed vulnerabilities or defects**. A legitimate cleanup section or explicitly labelled counterexample can match them.

Before relying on an applicable guide, validate its selected versions, dependencies and configuration schema in a disposable environment. Network/firewall, storage, identity, password-vault and upgrade procedures need console/recovery access and an end-to-end test appropriate to their scope. No credentials, messages, live services or user infrastructure were changed in this pass.

## Per-article coverage

Each row records completion of metadata and shell-source checks. “Corrected” means edited in this batch; “source checked” means no correction was established by this pass. Neither means lab-tested. The final column records targeted indicators for deeper review where present.

| Article | Source disposition | Scope notes |
|---|---|---|

| [es/posts/2026-10-30-intel-amt-sol-proxmox.md](../content/es/posts/2026-10-30-intel-amt-sol-proxmox.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-08-docker-compose-patterns.md](../content/posts/2026-05-08-docker-compose-patterns.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-08-docker-registry-mirror-cache.md](../content/posts/2026-05-08-docker-registry-mirror-cache.md) | Source checked | storage/delete commands: inspect scope; mutable image examples |
| [posts/2026-05-08-gpon-ftth-mikrotik.md](../content/posts/2026-05-08-gpon-ftth-mikrotik.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-08-lxc-vs-docker.md](../content/posts/2026-05-08-lxc-vs-docker.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-05-08-mikrotik-cloudflare-tunnel.md](../content/posts/2026-05-08-mikrotik-cloudflare-tunnel.md) | Source checked | mutable image examples |
| [posts/2026-05-08-mikrotik-wireguard-vpn.md](../content/posts/2026-05-08-mikrotik-wireguard-vpn.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-08-proxmox-backup-server-setup.md](../content/posts/2026-05-08-proxmox-backup-server-setup.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-08-proxmox-networking-bridges-vlans.md](../content/posts/2026-05-08-proxmox-networking-bridges-vlans.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-08-zfs-snapshot-strategies.md](../content/posts/2026-05-08-zfs-snapshot-strategies.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-09-traefik-reverse-proxy-docker.md](../content/posts/2026-05-09-traefik-reverse-proxy-docker.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-10-docker-ufw-firewall-fix.md](../content/posts/2026-05-10-docker-ufw-firewall-fix.md) | Source checked | firewall mutation: inspect scope |
| [posts/2026-05-11-docker-watchtower-auto-updates.md](../content/posts/2026-05-11-docker-watchtower-auto-updates.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; production/runtime claim: evidence not established |
| [posts/2026-05-12-mikrotik-vlan-segmentation.md](../content/posts/2026-05-12-mikrotik-vlan-segmentation.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-13-docker-compose-production-patterns.md](../content/posts/2026-05-13-docker-compose-production-patterns.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-13-docker-container-resource-limits.md](../content/posts/2026-05-13-docker-container-resource-limits.md) | Source checked | mutable image examples |
| [posts/2026-05-13-docker-macvlan-ipvlan-networking.md](../content/posts/2026-05-13-docker-macvlan-ipvlan-networking.md) | Source checked | mutable image examples |
| [posts/2026-05-13-linux-sysctl-kernel-tuning.md](../content/posts/2026-05-13-linux-sysctl-kernel-tuning.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-13-proxmox-pcie-passthrough.md](../content/posts/2026-05-13-proxmox-pcie-passthrough.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-cloudflare-tunnel-docker.md](../content/posts/2026-05-14-cloudflare-tunnel-docker.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-05-14-docker-compose-healthchecks.md](../content/posts/2026-05-14-docker-compose-healthchecks.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-docker-socket-proxy.md](../content/posts/2026-05-14-docker-socket-proxy.md) | Source checked | storage/delete commands: inspect scope; mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-14-grafana-alloy-log-collection.md](../content/posts/2026-05-14-grafana-alloy-log-collection.md) | Source checked | privileged/API access: inspect authorization |
| [posts/2026-05-14-proxmox-zfs-arc-tuning.md](../content/posts/2026-05-14-proxmox-zfs-arc-tuning.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-05-14-windows-server-2025-dhcp-failover.md](../content/posts/2026-05-14-windows-server-2025-dhcp-failover.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-dns-replication.md](../content/posts/2026-05-14-windows-server-2025-dns-replication.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-domain-controller.md](../content/posts/2026-05-14-windows-server-2025-domain-controller.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-entra-connect-sync.md](../content/posts/2026-05-14-windows-server-2025-entra-connect-sync.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-entra-hybrid-join.md](../content/posts/2026-05-14-windows-server-2025-entra-hybrid-join.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-group-policy-management.md](../content/posts/2026-05-14-windows-server-2025-group-policy-management.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-secondary-domain-controller.md](../content/posts/2026-05-14-windows-server-2025-secondary-domain-controller.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-windows-hello-hybrid-key-trust.md](../content/posts/2026-05-14-windows-server-2025-windows-hello-hybrid-key-trust.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-14-windows-server-2025-writeback-cloud-on-premises.md](../content/posts/2026-05-14-windows-server-2025-writeback-cloud-on-premises.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-15-docker-compose-networking-patterns.md](../content/posts/2026-05-15-docker-compose-networking-patterns.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-15-docker-container-security-hardening.md](../content/posts/2026-05-15-docker-container-security-hardening.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-15-mikrotik-capsman-vlan-configuration.md](../content/posts/2026-05-15-mikrotik-capsman-vlan-configuration.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-15-systemd-service-hardening.md](../content/posts/2026-05-15-systemd-service-hardening.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-16-docker-logging-log-management.md](../content/posts/2026-05-16-docker-logging-log-management.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; production/runtime claim: evidence not established |
| [posts/2026-05-16-docker-volume-management-homelab.md](../content/posts/2026-05-16-docker-volume-management-homelab.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-16-pihole-unbound-recursive-dns.md](../content/posts/2026-05-16-pihole-unbound-recursive-dns.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-16-proxmox-cloudinit-vm-templates.md](../content/posts/2026-05-16-proxmox-cloudinit-vm-templates.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-16-self-hosted-ai-ollama-open-webui.md](../content/posts/2026-05-16-self-hosted-ai-ollama-open-webui.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-17-crowdsec-docker-traefik-deployment.md](../content/posts/2026-05-17-crowdsec-docker-traefik-deployment.md) | Source checked | mutable image examples |
| [posts/2026-05-17-docker-proxmox-lxc-guide.md](../content/posts/2026-05-17-docker-proxmox-lxc-guide.md) | Source checked | mutable image examples |
| [posts/2026-05-17-homelab-monitoring-stack.md](../content/posts/2026-05-17-homelab-monitoring-stack.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-17-linux-kernel-performance-tuning.md](../content/posts/2026-05-17-linux-kernel-performance-tuning.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-17-vaultwarden-docker-deployment.md](../content/posts/2026-05-17-vaultwarden-docker-deployment.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-18-docker-multistage-builds.md](../content/posts/2026-05-18-docker-multistage-builds.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-18-docker-rootless-mode.md](../content/posts/2026-05-18-docker-rootless-mode.md) | Source checked | privileged/API access: inspect authorization |
| [posts/2026-05-18-gitea-docker-ci-cd-homelab.md](../content/posts/2026-05-18-gitea-docker-ci-cd-homelab.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-18-proxmox-gpu-passthrough-guide.md](../content/posts/2026-05-18-proxmox-gpu-passthrough-guide.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-18-traefik-middleware-security-hardening.md](../content/posts/2026-05-18-traefik-middleware-security-hardening.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-19-authentik-sso-traefik-homelab.md](../content/posts/2026-05-19-authentik-sso-traefik-homelab.md) | Source checked | mutable image examples; sample credentials: replace before use |
| [posts/2026-05-19-docker-secrets-management.md](../content/posts/2026-05-19-docker-secrets-management.md) | Source checked | mutable image examples |
| [posts/2026-05-19-headscale-self-hosted-tailscale-server.md](../content/posts/2026-05-19-headscale-self-hosted-tailscale-server.md) | Source checked | mutable image examples |
| [posts/2026-05-19-proxmox-sdn-software-defined-networking.md](../content/posts/2026-05-19-proxmox-sdn-software-defined-networking.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-19-restic-docker-backup-strategy.md](../content/posts/2026-05-19-restic-docker-backup-strategy.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-20-mikrotik-dns-doh-adlist.md](../content/posts/2026-05-20-mikrotik-dns-doh-adlist.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-20-nginx-reverse-proxy-docker.md](../content/posts/2026-05-20-nginx-reverse-proxy-docker.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-05-20-proxmox-security-hardening.md](../content/posts/2026-05-20-proxmox-security-hardening.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-20-valkey-docker-deployment-homelab.md](../content/posts/2026-05-20-valkey-docker-deployment-homelab.md) | Source checked | mutable image examples |
| [posts/2026-05-20-wireguard-kernel-performance-tuning.md](../content/posts/2026-05-20-wireguard-kernel-performance-tuning.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-21-docker-buildkit-cache-optimization.md](../content/posts/2026-05-21-docker-buildkit-cache-optimization.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-05-21-docker-ipv6-networking-guide.md](../content/posts/2026-05-21-docker-ipv6-networking-guide.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; sample credentials: replace before use |
| [posts/2026-05-21-mailcow-dockerized-selfhosted-email.md](../content/posts/2026-05-21-mailcow-dockerized-selfhosted-email.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-21-mikrotik-containers-docker-routeros.md](../content/posts/2026-05-21-mikrotik-containers-docker-routeros.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-21-prometheus-grafana-monitoring-stack.md](../content/posts/2026-05-21-prometheus-grafana-monitoring-stack.md) | Source checked | privileged/API access: inspect authorization; production/runtime claim: evidence not established |
| [posts/2026-05-22-docker-container-auto-healing.md](../content/posts/2026-05-22-docker-container-auto-healing.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-22-nginx-poolslip-security-advisory.md](../content/posts/2026-05-22-nginx-poolslip-security-advisory.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-22-plex-to-jellyfin-migration-guide.md](../content/posts/2026-05-22-plex-to-jellyfin-migration-guide.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-05-22-proxmox-9-2-upgrade-guide.md](../content/posts/2026-05-22-proxmox-9-2-upgrade-guide.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-22-step-ca-acme-internal-certificates.md](../content/posts/2026-05-22-step-ca-acme-internal-certificates.md) | Source checked | mutable image examples |
| [posts/2026-05-23-docker-gpu-acceleration-homelab.md](../content/posts/2026-05-23-docker-gpu-acceleration-homelab.md) | Source checked | mutable image examples |
| [posts/2026-05-23-k3s-kubernetes-homelab-deployment.md](../content/posts/2026-05-23-k3s-kubernetes-homelab-deployment.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-23-linux-storage-benchmarking.md](../content/posts/2026-05-23-linux-storage-benchmarking.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-23-proxmox-backup-strategies.md](../content/posts/2026-05-23-proxmox-backup-strategies.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-24-caddy-reverse-proxy-docker.md](../content/posts/2026-05-24-caddy-reverse-proxy-docker.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-05-24-docker-compose-env-variables.md](../content/posts/2026-05-24-docker-compose-env-variables.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-24-mikrotik-firewall-rules.md](../content/posts/2026-05-24-mikrotik-firewall-rules.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-24-proxmox-lxc-resource-management.md](../content/posts/2026-05-24-proxmox-lxc-resource-management.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-24-systemd-service-hardening-linux.md](../content/posts/2026-05-24-systemd-service-hardening-linux.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-25-docker-network-troubleshooting-guide.md](../content/posts/2026-05-25-docker-network-troubleshooting-guide.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-25-linux-disk-io-performance-tuning.md](../content/posts/2026-05-25-linux-disk-io-performance-tuning.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-25-nfs-storage-homelab-proxmox-docker.md](../content/posts/2026-05-25-nfs-storage-homelab-proxmox-docker.md) | Source checked | storage/delete commands: inspect scope; mutable image examples |
| [posts/2026-05-25-systemd-timer-automation-homelab.md](../content/posts/2026-05-25-systemd-timer-automation-homelab.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-05-25-wireguard-vpn-proxmox-lxc.md](../content/posts/2026-05-25-wireguard-vpn-proxmox-lxc.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-26-docker-healthchecks-compose-service-readiness.md](../content/posts/2026-05-26-docker-healthchecks-compose-service-readiness.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-26-docker-trivy-vulnerability-scanning.md](../content/posts/2026-05-26-docker-trivy-vulnerability-scanning.md) | Source checked | privileged/API access: inspect authorization |
| [posts/2026-05-26-mikrotik-routeros7-best-practices.md](../content/posts/2026-05-26-mikrotik-routeros7-best-practices.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-26-prometheus-grafana-homelab-monitoring.md](../content/posts/2026-05-26-prometheus-grafana-homelab-monitoring.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-26-zfs-pool-design-proxmox-homelab.md](../content/posts/2026-05-26-zfs-pool-design-proxmox-homelab.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-05-27-ansible-homelab-automation.md](../content/posts/2026-05-27-ansible-homelab-automation.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-27-docker-swarm-homelab-single-node-orchestration.md](../content/posts/2026-05-27-docker-swarm-homelab-single-node-orchestration.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; sample credentials: replace before use |
| [posts/2026-05-27-grafana-loki-centralized-docker-logging.md](../content/posts/2026-05-27-grafana-loki-centralized-docker-logging.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; production/runtime claim: evidence not established; sample credentials: replace before use |
| [posts/2026-05-27-immich-docker-homelab-deployment.md](../content/posts/2026-05-27-immich-docker-homelab-deployment.md) | Source checked | storage/delete commands: inspect scope; production/runtime claim: evidence not established |
| [posts/2026-05-27-n8n-docker-deployment-homelab-automation.md](../content/posts/2026-05-27-n8n-docker-deployment-homelab-automation.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-27-nftables-linux-firewall-homelab.md](../content/posts/2026-05-27-nftables-linux-firewall-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-27-proxmox-terraform-gitops-iac.md](../content/posts/2026-05-27-proxmox-terraform-gitops-iac.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-28-docker-container-migration-homelab.md](../content/posts/2026-05-28-docker-container-migration-homelab.md) | Source checked | mutable image examples |
| [posts/2026-05-28-mikrotik-routeros7-ospf-dynamic-routing.md](../content/posts/2026-05-28-mikrotik-routeros7-ospf-dynamic-routing.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-28-postgresql-docker-homelab-deployment.md](../content/posts/2026-05-28-postgresql-docker-homelab-deployment.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-29-docker-compose-profiles-homelab.md](../content/posts/2026-05-29-docker-compose-profiles-homelab.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; sample credentials: replace before use |
| [posts/2026-05-29-docker-container-dns-homelab-guide.md](../content/posts/2026-05-29-docker-container-dns-homelab-guide.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-29-haproxy-docker-load-balancer.md](../content/posts/2026-05-29-haproxy-docker-load-balancer.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-29-mikrotik-routeros7-bgp-configuration.md](../content/posts/2026-05-29-mikrotik-routeros7-bgp-configuration.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-05-29-proxmox-datacenter-manager-1-1.md](../content/posts/2026-05-29-proxmox-datacenter-manager-1-1.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-30-docker-cve-2026-31431-copy-fail-mitigation.md](../content/posts/2026-05-30-docker-cve-2026-31431-copy-fail-mitigation.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-30-netdata-docker-monitoring-homelab.md](../content/posts/2026-05-30-netdata-docker-monitoring-homelab.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-30-portainer-docker-deployment-homelab.md](../content/posts/2026-05-30-portainer-docker-deployment-homelab.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-05-30-searxng-self-hosted-meta-search-engine-docker.md](../content/posts/2026-05-30-searxng-self-hosted-meta-search-engine-docker.md) | Source checked | mutable image examples |
| [posts/2026-05-31-docker-compose-override-files-multi-environment.md](../content/posts/2026-05-31-docker-compose-override-files-multi-environment.md) | Source checked | mutable image examples |
| [posts/2026-05-31-frrouting-bgp-linux-dynamic-routing-homelab.md](../content/posts/2026-05-31-frrouting-bgp-linux-dynamic-routing-homelab.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-05-31-linux-cpu-frequency-scaling-power-management-homelab.md](../content/posts/2026-05-31-linux-cpu-frequency-scaling-power-management-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-31-mikrotik-routeros-7-23-stable-upgrade-guide.md](../content/posts/2026-05-31-mikrotik-routeros-7-23-stable-upgrade-guide.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-05-31-proxmox-vm-disk-performance-optimization.md](../content/posts/2026-05-31-proxmox-vm-disk-performance-optimization.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md](../content/posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-01-minio-docker-object-storage.md](../content/posts/2026-06-01-minio-docker-object-storage.md) | Source checked | mutable image examples; sample credentials: replace before use |
| [posts/2026-06-01-prometheus-snmp-exporter-mikrotik-monitoring.md](../content/posts/2026-06-01-prometheus-snmp-exporter-mikrotik-monitoring.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-01-renovate-bot-automated-docker-updates-homelab.md](../content/posts/2026-06-01-renovate-bot-automated-docker-updates-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-01-uptime-kuma-docker-monitoring-dashboard.md](../content/posts/2026-06-01-uptime-kuma-docker-monitoring-dashboard.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; production/runtime claim: evidence not established |
| [posts/2026-06-03-fail2ban-docker-deployment-homelab.md](../content/posts/2026-06-03-fail2ban-docker-deployment-homelab.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-03-homelab-mcp-server-docker-deployment.md](../content/posts/2026-06-03-homelab-mcp-server-docker-deployment.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-04-btrfs-vs-zfs-homelab-storage.md](../content/posts/2026-06-04-btrfs-vs-zfs-homelab-storage.md) | Source checked | storage/delete commands: inspect scope; production/runtime claim: evidence not established |
| [posts/2026-06-04-homepage-docker-dashboard-homelab.md](../content/posts/2026-06-04-homepage-docker-dashboard-homelab.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-06-04-mikrotik-routeros7-routing-filters-pbr.md](../content/posts/2026-06-04-mikrotik-routeros7-routing-filters-pbr.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-05-bookstack-docker-homelab-documentation.md](../content/posts/2026-06-05-bookstack-docker-homelab-documentation.md) | Source checked | mutable image examples |
| [posts/2026-06-05-docker-hardened-images-homelab-migration.md](../content/posts/2026-06-05-docker-hardened-images-homelab-migration.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-05-docker-image-security-hardening-distroless.md](../content/posts/2026-06-05-docker-image-security-hardening-distroless.md) | Source checked | mutable image examples |
| [posts/2026-06-05-gluetun-vpn-gateway-docker-wireguard.md](../content/posts/2026-06-05-gluetun-vpn-gateway-docker-wireguard.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-06-05-linux-disk-health-monitoring-smartmontools-scrutiny.md](../content/posts/2026-06-05-linux-disk-health-monitoring-smartmontools-scrutiny.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-06-docker-buildx-multi-architecture-images-homelab.md](../content/posts/2026-06-06-docker-buildx-multi-architecture-images-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-06-docker-nftables-firewall-backend-homelab.md](../content/posts/2026-06-06-docker-nftables-firewall-backend-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-06-linux-oom-management-docker-homelab.md](../content/posts/2026-06-06-linux-oom-management-docker-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-06-proxmox-intel-igpu-passthrough-jellyfin.md](../content/posts/2026-06-06-proxmox-intel-igpu-passthrough-jellyfin.md) | Source checked | mutable image examples |
| [posts/2026-06-07-librenms-docker-deployment-network-monitoring-homelab.md](../content/posts/2026-06-07-librenms-docker-deployment-network-monitoring-homelab.md) | Source checked | mutable image examples; sample credentials: replace before use |
| [posts/2026-06-07-linux-bridge-networking-debugging-docker-proxmox.md](../content/posts/2026-06-07-linux-bridge-networking-debugging-docker-proxmox.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-07-systemd-networkd-homelab-networking-bridges-vlans-bonds.md](../content/posts/2026-06-07-systemd-networkd-homelab-networking-bridges-vlans-bonds.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-08-mikrotik-routeros7-vrf-configuration.md](../content/posts/2026-06-08-mikrotik-routeros7-vrf-configuration.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-08-outline-wiki-docker-deployment.md](../content/posts/2026-06-08-outline-wiki-docker-deployment.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-06-09-docker-macvlan-homelab-networking.md](../content/posts/2026-06-09-docker-macvlan-homelab-networking.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-06-09-home-assistant-docker-deployment-proxmox.md](../content/posts/2026-06-09-home-assistant-docker-deployment-proxmox.md) | Source checked | mutable image examples; privileged/API access: inspect authorization; production/runtime claim: evidence not established |
| [posts/2026-06-09-linux-network-performance-tuning-homelab.md](../content/posts/2026-06-09-linux-network-performance-tuning-homelab.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-09-proxmox-datacenter-manager-1-1-automated-install-ceph-monitoring.md](../content/posts/2026-06-09-proxmox-datacenter-manager-1-1-automated-install-ceph-monitoring.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-09-proxmox-ve-cluster-high-availability-homelab.md](../content/posts/2026-06-09-proxmox-ve-cluster-high-availability-homelab.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-10-docker-compose-startup-dependencies-init-containers.md](../content/posts/2026-06-10-docker-compose-startup-dependencies-init-containers.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-11-acme-sh-letsencrypt-certificates-homelab-docker.md](../content/posts/2026-06-11-acme-sh-letsencrypt-certificates-homelab-docker.md) | Source checked | mutable image examples; privileged/API access: inspect authorization |
| [posts/2026-06-11-docker-container-storage-quotas-xfs.md](../content/posts/2026-06-11-docker-container-storage-quotas-xfs.md) | Source checked | storage/delete commands: inspect scope; mutable image examples |
| [posts/2026-06-11-docker-proxy-configuration-homelab.md](../content/posts/2026-06-11-docker-proxy-configuration-homelab.md) | Source checked | mutable image examples |
| [posts/2026-06-11-linux-auditd-security-auditing-homelab.md](../content/posts/2026-06-11-linux-auditd-security-auditing-homelab.md) | Source checked | privileged/API access: inspect authorization |
| [posts/2026-06-12-docker-compose-yaml-anchors-extensions.md](../content/posts/2026-06-12-docker-compose-yaml-anchors-extensions.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-12-docker-container-graceful-shutdown-signals.md](../content/posts/2026-06-12-docker-container-graceful-shutdown-signals.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-06-12-proxmox-vm-disk-performance-benchmark.md](../content/posts/2026-06-12-proxmox-vm-disk-performance-benchmark.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-13-docker-supply-chain-security-sbom-image-signing.md](../content/posts/2026-06-13-docker-supply-chain-security-sbom-image-signing.md) | Source checked | privileged/API access: inspect authorization |
| [posts/2026-06-13-podman-rootless-containers-docker-alternative-homelab.md](../content/posts/2026-06-13-podman-rootless-containers-docker-alternative-homelab.md) | Source checked | sample credentials: replace before use |
| [posts/2026-06-15-docker-monitoring-prometheus-grafana-homelab.md](../content/posts/2026-06-15-docker-monitoring-prometheus-grafana-homelab.md) | Source checked | mutable image examples; sample credentials: replace before use |
| [posts/2026-06-15-docker-overlay2-storage-driver-linux-guide.md](../content/posts/2026-06-15-docker-overlay2-storage-driver-linux-guide.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-06-15-mikrotik-routeros-container-apps-deployment.md](../content/posts/2026-06-15-mikrotik-routeros-container-apps-deployment.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-15-ntfy-self-hosted-push-notification-server-homelab.md](../content/posts/2026-06-15-ntfy-self-hosted-push-notification-server-homelab.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-06-15-opnsense-virtual-firewall-proxmox-homelab.md](../content/posts/2026-06-15-opnsense-virtual-firewall-proxmox-homelab.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-06-15-paperless-ngx-docker-deployment-homelab.md](../content/posts/2026-06-15-paperless-ngx-docker-deployment-homelab.md) | Source checked | mutable image examples; production/runtime claim: evidence not established |
| [posts/2026-06-15-proxmox-api-tokens-rbac-secure-automation.md](../content/posts/2026-06-15-proxmox-api-tokens-rbac-secure-automation.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-15-proxmox-zfs-snapshot-replication-backup.md](../content/posts/2026-06-15-proxmox-zfs-snapshot-replication-backup.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-06-15-samba-file-server-proxmox-lxc-zfs.md](../content/posts/2026-06-15-samba-file-server-proxmox-lxc-zfs.md) | Source checked | storage/delete commands: inspect scope |
| [posts/2026-06-16-container-runtimes-runc-vs-crun-docker.md](../content/posts/2026-06-16-container-runtimes-runc-vs-crun-docker.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-06-16-proxmox-firewall-security-hardening.md](../content/posts/2026-06-16-proxmox-firewall-security-hardening.md) | Source checked | production/runtime claim: evidence not established |
| [posts/2026-06-17-cgroups-v2-docker-container-resource-limits.md](../content/posts/2026-06-17-cgroups-v2-docker-container-resource-limits.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-17-cilium-cni-k3s-ebpf-networking-homelab.md](../content/posts/2026-06-17-cilium-cni-k3s-ebpf-networking-homelab.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-18-linux-tcp-bbr-congestion-control-proxmox-docker-lxc.md](../content/posts/2026-06-18-linux-tcp-bbr-congestion-control-proxmox-docker-lxc.md) | Corrected | Targeted correction; runtime remains unverified |
| [posts/2026-06-20-docusaurus-homelab-documentation-guide.md](../content/posts/2026-06-20-docusaurus-homelab-documentation-guide.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-06-20-homelab-10gbe-networking-mikrotik-proxmox.md](../content/posts/2026-06-20-homelab-10gbe-networking-mikrotik-proxmox.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-10-30-intel-amt-sol-proxmox.md](../content/posts/2026-10-30-intel-amt-sol-proxmox.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-10-30-powershell-modules-onedrive-cleanup.md](../content/posts/2026-10-30-powershell-modules-onedrive-cleanup.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/2026-10-30-thinkpad-t420-arch-i3.md](../content/posts/2026-10-30-thinkpad-t420-arch-i3.md) | Source checked | production/runtime claim: evidence not established |
| [posts/first-post.md](../content/posts/first-post.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/frigate-deployment.md](../content/posts/frigate-deployment.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
| [posts/r1-router-deployment.md](../content/posts/r1-router-deployment.md) | Source checked | No additional issue established by this source pass; runtime not repeated |
