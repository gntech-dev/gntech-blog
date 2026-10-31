# Consolidated archive audit — October 31, 2026

Reviewed source snapshot: `ddb84c82adbb53ba33f6e7b58f4d8b754c3a5ca4`, the tested integrated-recovery PR head before this follow-up.

## Scope and result

All **175 current article files** were included in the source pass, including the Spanish AMT edition. Files matching the snapshot's blob SHA were reused from the earlier fetched inventory; all 27 changed article blobs were freshly retrieved. This is a source audit with targeted technical review, not a claim that all 175 procedures were executed or every historical fact refreshed.

This follow-up corrects **19 additional articles**. The combined PR also includes the already tested PostgreSQL/Restic recovery-chain article and harness, giving **20 changed articles** in one review. No article is deleted, unpublished, or assigned a new URL. English and Spanish Start Here pages now give a clear backup/recovery path.

## Corrections

| Article | Correction |
|---|---|
| [2026-05-14-docker-socket-proxy](../content/posts/2026-05-14-docker-socket-proxy.md) | Documented Tecnativa controls; private read-oriented policy; no per-client or socket-mount authorization claims. |
| [2026-05-14-windows-server-2025-writeback-cloud-on-premises](../content/posts/2026-05-14-windows-server-2025-writeback-cloud-on-premises.md) | Device-registration class/scenario corrections; removed guessed ACL/account and status-output examples. |
| [2026-05-15-docker-compose-networking-patterns](../content/posts/2026-05-15-docker-compose-networking-patterns.md) | Recreation retains volumes. |
| [2026-05-16-docker-volume-management-homelab](../content/posts/2026-05-16-docker-volume-management-homelab.md) | Consistent backup handoff; NFS retry/root-squash guidance; accurate volume cleanup/portability rules. |
| [2026-05-18-docker-multistage-builds](../content/posts/2026-05-18-docker-multistage-builds.md) | Removed incompatible/unverified Python distroless dependency-copy example. |
| [2026-05-19-restic-docker-backup-strategy](../content/posts/2026-05-19-restic-docker-backup-strategy.md) | Clear link to the complete database recovery exercise and its limits. |
| [2026-05-23-k3s-kubernetes-homelab-deployment](../content/posts/2026-05-23-k3s-kubernetes-homelab-deployment.md) | Replaced invalid upgrade flag with supported upgrade planning. |
| [2026-05-23-proxmox-backup-strategies](../content/posts/2026-05-23-proxmox-backup-strategies.md) | Distinguishes guest recovery from database/file recovery. |
| [2026-05-25-docker-network-troubleshooting-guide](../content/posts/2026-05-25-docker-network-troubleshooting-guide.md) | Managed/external network distinction; no volume deletion to repair networks. |
| [2026-05-28-docker-container-migration-homelab](../content/posts/2026-05-28-docker-container-migration-homelab.md) | NFS persistent-data mount retains locking and hard retries; states outage test boundary. |
| [2026-05-28-postgresql-docker-homelab-deployment](../content/posts/2026-05-28-postgresql-docker-homelab-deployment.md) | Replaced destructive/incomplete recovery and replica examples; secret bootstrap, extensions, roles, and upgrade boundaries. |
| [2026-06-05-docker-hardened-images-homelab-migration](../content/posts/2026-06-05-docker-hardened-images-homelab-migration.md) | Removed guessed catalog tags, fixed CVE counts, and drop-in guarantees; compatibility-first workflow. |
| [2026-06-05-docker-image-security-hardening-distroless](../content/posts/2026-06-05-docker-image-security-hardening-distroless.md) | Non-root-accessible Python environment and ASGI startup; corrected scanner, runtime, and image assumptions. |
| [2026-06-09-home-assistant-docker-deployment-proxmox](../content/posts/2026-06-09-home-assistant-docker-deployment-proxmox.md) | Replaced pause/exec and live database overwrite workflow with supported, isolated backup/recovery planning. |
| [2026-06-09-proxmox-ve-cluster-high-availability-homelab](../content/posts/2026-06-09-proxmox-ve-cluster-high-availability-homelab.md) | Hard NFS mount for persistent storage; explicit HA test boundary. |
| [2026-06-10-docker-compose-startup-dependencies-init-containers](../content/posts/2026-06-10-docker-compose-startup-dependencies-init-containers.md) | Profile dependency semantics and health diagnostics; no volume deletion/cache-reset fiction. |
| [2026-06-11-docker-container-storage-quotas-xfs](../content/posts/2026-06-11-docker-container-storage-quotas-xfs.md) | Backend-aware quota scope; removed guessed destructive migration and unbounded fill test. |
| [2026-06-15-docker-overlay2-storage-driver-linux-guide](../content/posts/2026-06-15-docker-overlay2-storage-driver-linux-guide.md) | Classic/containerd distinction; removed bypass setting and automatic volume pruning; inventory timer. |
| [2026-06-17-cilium-cni-k3s-ebpf-networking-homelab](../content/posts/2026-06-17-cilium-cni-k3s-ebpf-networking-homelab.md) | Official CLI installation path and locally forwarded relay access. |

## Checks actually performed

| Check | Result |
|---|---|
| Article front matter | 175/175 parsed with title/date present |
| Bash/sh/shell examples | 1765 blocks pass `bash -n`, without execution |
| YAML/yml examples | 522 blocks parse, including multi-document/application-tagged snippets |
| Prose internal article/image references | 178 source targets checked; zero missing (rendered fragments are checked by CI) |
| Hugo production/draft builds and rendered link/anchor checks | Run by the combined PR's publishing CI; inspect its final head result |
| PostgreSQL scheduler and recovery chain | Existing dated runtime evidence remains linked in the article; CI replays it for the combined PR |
| Restic recovery | Existing dated runtime evidence remains linked; CI replays the file/copy lab |
| Other revised infrastructure procedures | Source review only; not executed against user systems |

## Evidence and remaining operational boundaries

The [verification-status guidance](article-verification-status.md) lists the dated PostgreSQL and Restic lab records. Tested Docker labs cover synthetic data and local repositories. They do not establish actual off-site access, host/site-loss durability, production roles/extensions/attachments, external notifications, overdue-run monitoring, or hardware restoration.

New source corrections to identity, routing, NFS, Kubernetes, image builds, storage migration, and service policy still need validation in their own intended environments. Historical release/pricing/performance claims throughout the archive were not exhaustively remeasured. A parsed YAML fragment is not necessarily a complete Compose/application configuration; a shell parser cannot establish privileges, dependencies, or safe targets.

The older audits are historical records, including their then-open PR lists. This combined review supersedes the earlier request to advance small article fixes one PR at a time. Runtime validation gaps are recorded here rather than presented as completed tests or silently deferred documentation fixes.

## Source coverage inventory

“Source checked” records metadata/example parsing and the targeted pattern sweep. It does not certify every factual statement. “Corrected” identifies this follow-up's additional article edits. The integrated recovery article retains its prior runtime evidence.

| Article | Disposition |
|---|---|
| [content/es/posts/2026-10-30-intel-amt-sol-proxmox.md](../content/es/posts/2026-10-30-intel-amt-sol-proxmox.md) | Source checked |
| [content/posts/2026-05-08-docker-compose-patterns.md](../content/posts/2026-05-08-docker-compose-patterns.md) | Source checked |
| [content/posts/2026-05-08-docker-registry-mirror-cache.md](../content/posts/2026-05-08-docker-registry-mirror-cache.md) | Source checked |
| [content/posts/2026-05-08-gpon-ftth-mikrotik.md](../content/posts/2026-05-08-gpon-ftth-mikrotik.md) | Source checked |
| [content/posts/2026-05-08-lxc-vs-docker.md](../content/posts/2026-05-08-lxc-vs-docker.md) | Source checked |
| [content/posts/2026-05-08-mikrotik-cloudflare-tunnel.md](../content/posts/2026-05-08-mikrotik-cloudflare-tunnel.md) | Source checked |
| [content/posts/2026-05-08-mikrotik-wireguard-vpn.md](../content/posts/2026-05-08-mikrotik-wireguard-vpn.md) | Source checked |
| [content/posts/2026-05-08-proxmox-backup-server-setup.md](../content/posts/2026-05-08-proxmox-backup-server-setup.md) | Source checked |
| [content/posts/2026-05-08-proxmox-networking-bridges-vlans.md](../content/posts/2026-05-08-proxmox-networking-bridges-vlans.md) | Source checked |
| [content/posts/2026-05-08-zfs-snapshot-strategies.md](../content/posts/2026-05-08-zfs-snapshot-strategies.md) | Source checked |
| [content/posts/2026-05-09-traefik-reverse-proxy-docker.md](../content/posts/2026-05-09-traefik-reverse-proxy-docker.md) | Source checked |
| [content/posts/2026-05-10-docker-ufw-firewall-fix.md](../content/posts/2026-05-10-docker-ufw-firewall-fix.md) | Source checked |
| [content/posts/2026-05-11-docker-watchtower-auto-updates.md](../content/posts/2026-05-11-docker-watchtower-auto-updates.md) | Source checked |
| [content/posts/2026-05-12-mikrotik-vlan-segmentation.md](../content/posts/2026-05-12-mikrotik-vlan-segmentation.md) | Source checked |
| [content/posts/2026-05-13-docker-compose-production-patterns.md](../content/posts/2026-05-13-docker-compose-production-patterns.md) | Source checked |
| [content/posts/2026-05-13-docker-container-resource-limits.md](../content/posts/2026-05-13-docker-container-resource-limits.md) | Source checked |
| [content/posts/2026-05-13-docker-macvlan-ipvlan-networking.md](../content/posts/2026-05-13-docker-macvlan-ipvlan-networking.md) | Source checked |
| [content/posts/2026-05-13-linux-sysctl-kernel-tuning.md](../content/posts/2026-05-13-linux-sysctl-kernel-tuning.md) | Source checked |
| [content/posts/2026-05-13-proxmox-pcie-passthrough.md](../content/posts/2026-05-13-proxmox-pcie-passthrough.md) | Source checked |
| [content/posts/2026-05-14-cloudflare-tunnel-docker.md](../content/posts/2026-05-14-cloudflare-tunnel-docker.md) | Source checked |
| [content/posts/2026-05-14-docker-compose-healthchecks.md](../content/posts/2026-05-14-docker-compose-healthchecks.md) | Source checked |
| [content/posts/2026-05-14-docker-socket-proxy.md](../content/posts/2026-05-14-docker-socket-proxy.md) | Corrected |
| [content/posts/2026-05-14-grafana-alloy-log-collection.md](../content/posts/2026-05-14-grafana-alloy-log-collection.md) | Source checked |
| [content/posts/2026-05-14-proxmox-zfs-arc-tuning.md](../content/posts/2026-05-14-proxmox-zfs-arc-tuning.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-dhcp-failover.md](../content/posts/2026-05-14-windows-server-2025-dhcp-failover.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-dns-replication.md](../content/posts/2026-05-14-windows-server-2025-dns-replication.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-domain-controller.md](../content/posts/2026-05-14-windows-server-2025-domain-controller.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-entra-connect-sync.md](../content/posts/2026-05-14-windows-server-2025-entra-connect-sync.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-entra-hybrid-join.md](../content/posts/2026-05-14-windows-server-2025-entra-hybrid-join.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-group-policy-management.md](../content/posts/2026-05-14-windows-server-2025-group-policy-management.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-secondary-domain-controller.md](../content/posts/2026-05-14-windows-server-2025-secondary-domain-controller.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-windows-hello-hybrid-key-trust.md](../content/posts/2026-05-14-windows-server-2025-windows-hello-hybrid-key-trust.md) | Source checked |
| [content/posts/2026-05-14-windows-server-2025-writeback-cloud-on-premises.md](../content/posts/2026-05-14-windows-server-2025-writeback-cloud-on-premises.md) | Corrected |
| [content/posts/2026-05-15-docker-compose-networking-patterns.md](../content/posts/2026-05-15-docker-compose-networking-patterns.md) | Corrected |
| [content/posts/2026-05-15-docker-container-security-hardening.md](../content/posts/2026-05-15-docker-container-security-hardening.md) | Source checked |
| [content/posts/2026-05-15-mikrotik-capsman-vlan-configuration.md](../content/posts/2026-05-15-mikrotik-capsman-vlan-configuration.md) | Source checked |
| [content/posts/2026-05-15-systemd-service-hardening.md](../content/posts/2026-05-15-systemd-service-hardening.md) | Source checked |
| [content/posts/2026-05-16-docker-logging-log-management.md](../content/posts/2026-05-16-docker-logging-log-management.md) | Source checked |
| [content/posts/2026-05-16-docker-volume-management-homelab.md](../content/posts/2026-05-16-docker-volume-management-homelab.md) | Corrected |
| [content/posts/2026-05-16-pihole-unbound-recursive-dns.md](../content/posts/2026-05-16-pihole-unbound-recursive-dns.md) | Source checked |
| [content/posts/2026-05-16-proxmox-cloudinit-vm-templates.md](../content/posts/2026-05-16-proxmox-cloudinit-vm-templates.md) | Source checked |
| [content/posts/2026-05-16-self-hosted-ai-ollama-open-webui.md](../content/posts/2026-05-16-self-hosted-ai-ollama-open-webui.md) | Source checked |
| [content/posts/2026-05-17-crowdsec-docker-traefik-deployment.md](../content/posts/2026-05-17-crowdsec-docker-traefik-deployment.md) | Source checked |
| [content/posts/2026-05-17-docker-proxmox-lxc-guide.md](../content/posts/2026-05-17-docker-proxmox-lxc-guide.md) | Source checked |
| [content/posts/2026-05-17-homelab-monitoring-stack.md](../content/posts/2026-05-17-homelab-monitoring-stack.md) | Source checked |
| [content/posts/2026-05-17-linux-kernel-performance-tuning.md](../content/posts/2026-05-17-linux-kernel-performance-tuning.md) | Source checked |
| [content/posts/2026-05-17-vaultwarden-docker-deployment.md](../content/posts/2026-05-17-vaultwarden-docker-deployment.md) | Source checked |
| [content/posts/2026-05-18-docker-multistage-builds.md](../content/posts/2026-05-18-docker-multistage-builds.md) | Corrected |
| [content/posts/2026-05-18-docker-rootless-mode.md](../content/posts/2026-05-18-docker-rootless-mode.md) | Source checked |
| [content/posts/2026-05-18-gitea-docker-ci-cd-homelab.md](../content/posts/2026-05-18-gitea-docker-ci-cd-homelab.md) | Source checked |
| [content/posts/2026-05-18-proxmox-gpu-passthrough-guide.md](../content/posts/2026-05-18-proxmox-gpu-passthrough-guide.md) | Source checked |
| [content/posts/2026-05-18-traefik-middleware-security-hardening.md](../content/posts/2026-05-18-traefik-middleware-security-hardening.md) | Source checked |
| [content/posts/2026-05-19-authentik-sso-traefik-homelab.md](../content/posts/2026-05-19-authentik-sso-traefik-homelab.md) | Source checked |
| [content/posts/2026-05-19-docker-secrets-management.md](../content/posts/2026-05-19-docker-secrets-management.md) | Source checked |
| [content/posts/2026-05-19-headscale-self-hosted-tailscale-server.md](../content/posts/2026-05-19-headscale-self-hosted-tailscale-server.md) | Source checked |
| [content/posts/2026-05-19-proxmox-sdn-software-defined-networking.md](../content/posts/2026-05-19-proxmox-sdn-software-defined-networking.md) | Source checked |
| [content/posts/2026-05-19-restic-docker-backup-strategy.md](../content/posts/2026-05-19-restic-docker-backup-strategy.md) | Corrected |
| [content/posts/2026-05-20-mikrotik-dns-doh-adlist.md](../content/posts/2026-05-20-mikrotik-dns-doh-adlist.md) | Source checked |
| [content/posts/2026-05-20-nginx-reverse-proxy-docker.md](../content/posts/2026-05-20-nginx-reverse-proxy-docker.md) | Source checked |
| [content/posts/2026-05-20-proxmox-security-hardening.md](../content/posts/2026-05-20-proxmox-security-hardening.md) | Source checked |
| [content/posts/2026-05-20-valkey-docker-deployment-homelab.md](../content/posts/2026-05-20-valkey-docker-deployment-homelab.md) | Source checked |
| [content/posts/2026-05-20-wireguard-kernel-performance-tuning.md](../content/posts/2026-05-20-wireguard-kernel-performance-tuning.md) | Source checked |
| [content/posts/2026-05-21-docker-buildkit-cache-optimization.md](../content/posts/2026-05-21-docker-buildkit-cache-optimization.md) | Source checked |
| [content/posts/2026-05-21-docker-ipv6-networking-guide.md](../content/posts/2026-05-21-docker-ipv6-networking-guide.md) | Source checked |
| [content/posts/2026-05-21-mailcow-dockerized-selfhosted-email.md](../content/posts/2026-05-21-mailcow-dockerized-selfhosted-email.md) | Source checked |
| [content/posts/2026-05-21-mikrotik-containers-docker-routeros.md](../content/posts/2026-05-21-mikrotik-containers-docker-routeros.md) | Source checked |
| [content/posts/2026-05-21-prometheus-grafana-monitoring-stack.md](../content/posts/2026-05-21-prometheus-grafana-monitoring-stack.md) | Source checked |
| [content/posts/2026-05-22-docker-container-auto-healing.md](../content/posts/2026-05-22-docker-container-auto-healing.md) | Source checked |
| [content/posts/2026-05-22-nginx-poolslip-security-advisory.md](../content/posts/2026-05-22-nginx-poolslip-security-advisory.md) | Source checked |
| [content/posts/2026-05-22-plex-to-jellyfin-migration-guide.md](../content/posts/2026-05-22-plex-to-jellyfin-migration-guide.md) | Source checked |
| [content/posts/2026-05-22-proxmox-9-2-upgrade-guide.md](../content/posts/2026-05-22-proxmox-9-2-upgrade-guide.md) | Source checked |
| [content/posts/2026-05-22-step-ca-acme-internal-certificates.md](../content/posts/2026-05-22-step-ca-acme-internal-certificates.md) | Source checked |
| [content/posts/2026-05-23-docker-gpu-acceleration-homelab.md](../content/posts/2026-05-23-docker-gpu-acceleration-homelab.md) | Source checked |
| [content/posts/2026-05-23-k3s-kubernetes-homelab-deployment.md](../content/posts/2026-05-23-k3s-kubernetes-homelab-deployment.md) | Corrected |
| [content/posts/2026-05-23-linux-storage-benchmarking.md](../content/posts/2026-05-23-linux-storage-benchmarking.md) | Source checked |
| [content/posts/2026-05-23-proxmox-backup-strategies.md](../content/posts/2026-05-23-proxmox-backup-strategies.md) | Corrected |
| [content/posts/2026-05-24-caddy-reverse-proxy-docker.md](../content/posts/2026-05-24-caddy-reverse-proxy-docker.md) | Source checked |
| [content/posts/2026-05-24-docker-compose-env-variables.md](../content/posts/2026-05-24-docker-compose-env-variables.md) | Source checked |
| [content/posts/2026-05-24-mikrotik-firewall-rules.md](../content/posts/2026-05-24-mikrotik-firewall-rules.md) | Source checked |
| [content/posts/2026-05-24-proxmox-lxc-resource-management.md](../content/posts/2026-05-24-proxmox-lxc-resource-management.md) | Source checked |
| [content/posts/2026-05-24-systemd-service-hardening-linux.md](../content/posts/2026-05-24-systemd-service-hardening-linux.md) | Source checked |
| [content/posts/2026-05-25-docker-network-troubleshooting-guide.md](../content/posts/2026-05-25-docker-network-troubleshooting-guide.md) | Corrected |
| [content/posts/2026-05-25-linux-disk-io-performance-tuning.md](../content/posts/2026-05-25-linux-disk-io-performance-tuning.md) | Source checked |
| [content/posts/2026-05-25-nfs-storage-homelab-proxmox-docker.md](../content/posts/2026-05-25-nfs-storage-homelab-proxmox-docker.md) | Source checked |
| [content/posts/2026-05-25-systemd-timer-automation-homelab.md](../content/posts/2026-05-25-systemd-timer-automation-homelab.md) | Source checked |
| [content/posts/2026-05-25-wireguard-vpn-proxmox-lxc.md](../content/posts/2026-05-25-wireguard-vpn-proxmox-lxc.md) | Source checked |
| [content/posts/2026-05-26-docker-healthchecks-compose-service-readiness.md](../content/posts/2026-05-26-docker-healthchecks-compose-service-readiness.md) | Source checked |
| [content/posts/2026-05-26-docker-trivy-vulnerability-scanning.md](../content/posts/2026-05-26-docker-trivy-vulnerability-scanning.md) | Source checked |
| [content/posts/2026-05-26-mikrotik-routeros7-best-practices.md](../content/posts/2026-05-26-mikrotik-routeros7-best-practices.md) | Source checked |
| [content/posts/2026-05-26-prometheus-grafana-homelab-monitoring.md](../content/posts/2026-05-26-prometheus-grafana-homelab-monitoring.md) | Source checked |
| [content/posts/2026-05-26-zfs-pool-design-proxmox-homelab.md](../content/posts/2026-05-26-zfs-pool-design-proxmox-homelab.md) | Source checked |
| [content/posts/2026-05-27-ansible-homelab-automation.md](../content/posts/2026-05-27-ansible-homelab-automation.md) | Source checked |
| [content/posts/2026-05-27-docker-swarm-homelab-single-node-orchestration.md](../content/posts/2026-05-27-docker-swarm-homelab-single-node-orchestration.md) | Source checked |
| [content/posts/2026-05-27-grafana-loki-centralized-docker-logging.md](../content/posts/2026-05-27-grafana-loki-centralized-docker-logging.md) | Source checked |
| [content/posts/2026-05-27-immich-docker-homelab-deployment.md](../content/posts/2026-05-27-immich-docker-homelab-deployment.md) | Source checked |
| [content/posts/2026-05-27-n8n-docker-deployment-homelab-automation.md](../content/posts/2026-05-27-n8n-docker-deployment-homelab-automation.md) | Source checked |
| [content/posts/2026-05-27-nftables-linux-firewall-homelab.md](../content/posts/2026-05-27-nftables-linux-firewall-homelab.md) | Source checked |
| [content/posts/2026-05-27-proxmox-terraform-gitops-iac.md](../content/posts/2026-05-27-proxmox-terraform-gitops-iac.md) | Source checked |
| [content/posts/2026-05-28-docker-container-migration-homelab.md](../content/posts/2026-05-28-docker-container-migration-homelab.md) | Corrected |
| [content/posts/2026-05-28-mikrotik-routeros7-ospf-dynamic-routing.md](../content/posts/2026-05-28-mikrotik-routeros7-ospf-dynamic-routing.md) | Source checked |
| [content/posts/2026-05-28-postgresql-docker-homelab-deployment.md](../content/posts/2026-05-28-postgresql-docker-homelab-deployment.md) | Corrected |
| [content/posts/2026-05-29-docker-compose-profiles-homelab.md](../content/posts/2026-05-29-docker-compose-profiles-homelab.md) | Source checked |
| [content/posts/2026-05-29-docker-container-dns-homelab-guide.md](../content/posts/2026-05-29-docker-container-dns-homelab-guide.md) | Source checked |
| [content/posts/2026-05-29-haproxy-docker-load-balancer.md](../content/posts/2026-05-29-haproxy-docker-load-balancer.md) | Source checked |
| [content/posts/2026-05-29-mikrotik-routeros7-bgp-configuration.md](../content/posts/2026-05-29-mikrotik-routeros7-bgp-configuration.md) | Source checked |
| [content/posts/2026-05-29-proxmox-datacenter-manager-1-1.md](../content/posts/2026-05-29-proxmox-datacenter-manager-1-1.md) | Source checked |
| [content/posts/2026-05-30-docker-cve-2026-31431-copy-fail-mitigation.md](../content/posts/2026-05-30-docker-cve-2026-31431-copy-fail-mitigation.md) | Source checked |
| [content/posts/2026-05-30-netdata-docker-monitoring-homelab.md](../content/posts/2026-05-30-netdata-docker-monitoring-homelab.md) | Source checked |
| [content/posts/2026-05-30-portainer-docker-deployment-homelab.md](../content/posts/2026-05-30-portainer-docker-deployment-homelab.md) | Source checked |
| [content/posts/2026-05-30-searxng-self-hosted-meta-search-engine-docker.md](../content/posts/2026-05-30-searxng-self-hosted-meta-search-engine-docker.md) | Source checked |
| [content/posts/2026-05-31-docker-compose-override-files-multi-environment.md](../content/posts/2026-05-31-docker-compose-override-files-multi-environment.md) | Source checked |
| [content/posts/2026-05-31-frrouting-bgp-linux-dynamic-routing-homelab.md](../content/posts/2026-05-31-frrouting-bgp-linux-dynamic-routing-homelab.md) | Source checked |
| [content/posts/2026-05-31-linux-cpu-frequency-scaling-power-management-homelab.md](../content/posts/2026-05-31-linux-cpu-frequency-scaling-power-management-homelab.md) | Source checked |
| [content/posts/2026-05-31-mikrotik-routeros-7-23-stable-upgrade-guide.md](../content/posts/2026-05-31-mikrotik-routeros-7-23-stable-upgrade-guide.md) | Source checked |
| [content/posts/2026-05-31-proxmox-vm-disk-performance-optimization.md](../content/posts/2026-05-31-proxmox-vm-disk-performance-optimization.md) | Source checked |
| [content/posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md](../content/posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md) | Source checked; integrated runtime lab recorded |
| [content/posts/2026-06-01-minio-docker-object-storage.md](../content/posts/2026-06-01-minio-docker-object-storage.md) | Source checked |
| [content/posts/2026-06-01-prometheus-snmp-exporter-mikrotik-monitoring.md](../content/posts/2026-06-01-prometheus-snmp-exporter-mikrotik-monitoring.md) | Source checked |
| [content/posts/2026-06-01-renovate-bot-automated-docker-updates-homelab.md](../content/posts/2026-06-01-renovate-bot-automated-docker-updates-homelab.md) | Source checked |
| [content/posts/2026-06-01-uptime-kuma-docker-monitoring-dashboard.md](../content/posts/2026-06-01-uptime-kuma-docker-monitoring-dashboard.md) | Source checked |
| [content/posts/2026-06-03-fail2ban-docker-deployment-homelab.md](../content/posts/2026-06-03-fail2ban-docker-deployment-homelab.md) | Source checked |
| [content/posts/2026-06-03-homelab-mcp-server-docker-deployment.md](../content/posts/2026-06-03-homelab-mcp-server-docker-deployment.md) | Source checked |
| [content/posts/2026-06-04-btrfs-vs-zfs-homelab-storage.md](../content/posts/2026-06-04-btrfs-vs-zfs-homelab-storage.md) | Source checked |
| [content/posts/2026-06-04-homepage-docker-dashboard-homelab.md](../content/posts/2026-06-04-homepage-docker-dashboard-homelab.md) | Source checked |
| [content/posts/2026-06-04-mikrotik-routeros7-routing-filters-pbr.md](../content/posts/2026-06-04-mikrotik-routeros7-routing-filters-pbr.md) | Source checked |
| [content/posts/2026-06-05-bookstack-docker-homelab-documentation.md](../content/posts/2026-06-05-bookstack-docker-homelab-documentation.md) | Source checked |
| [content/posts/2026-06-05-docker-hardened-images-homelab-migration.md](../content/posts/2026-06-05-docker-hardened-images-homelab-migration.md) | Corrected |
| [content/posts/2026-06-05-docker-image-security-hardening-distroless.md](../content/posts/2026-06-05-docker-image-security-hardening-distroless.md) | Corrected |
| [content/posts/2026-06-05-gluetun-vpn-gateway-docker-wireguard.md](../content/posts/2026-06-05-gluetun-vpn-gateway-docker-wireguard.md) | Source checked |
| [content/posts/2026-06-05-linux-disk-health-monitoring-smartmontools-scrutiny.md](../content/posts/2026-06-05-linux-disk-health-monitoring-smartmontools-scrutiny.md) | Source checked |
| [content/posts/2026-06-06-docker-buildx-multi-architecture-images-homelab.md](../content/posts/2026-06-06-docker-buildx-multi-architecture-images-homelab.md) | Source checked |
| [content/posts/2026-06-06-docker-nftables-firewall-backend-homelab.md](../content/posts/2026-06-06-docker-nftables-firewall-backend-homelab.md) | Source checked |
| [content/posts/2026-06-06-linux-oom-management-docker-homelab.md](../content/posts/2026-06-06-linux-oom-management-docker-homelab.md) | Source checked |
| [content/posts/2026-06-06-proxmox-intel-igpu-passthrough-jellyfin.md](../content/posts/2026-06-06-proxmox-intel-igpu-passthrough-jellyfin.md) | Source checked |
| [content/posts/2026-06-07-librenms-docker-deployment-network-monitoring-homelab.md](../content/posts/2026-06-07-librenms-docker-deployment-network-monitoring-homelab.md) | Source checked |
| [content/posts/2026-06-07-linux-bridge-networking-debugging-docker-proxmox.md](../content/posts/2026-06-07-linux-bridge-networking-debugging-docker-proxmox.md) | Source checked |
| [content/posts/2026-06-07-systemd-networkd-homelab-networking-bridges-vlans-bonds.md](../content/posts/2026-06-07-systemd-networkd-homelab-networking-bridges-vlans-bonds.md) | Source checked |
| [content/posts/2026-06-08-mikrotik-routeros7-vrf-configuration.md](../content/posts/2026-06-08-mikrotik-routeros7-vrf-configuration.md) | Source checked |
| [content/posts/2026-06-08-outline-wiki-docker-deployment.md](../content/posts/2026-06-08-outline-wiki-docker-deployment.md) | Source checked |
| [content/posts/2026-06-09-docker-macvlan-homelab-networking.md](../content/posts/2026-06-09-docker-macvlan-homelab-networking.md) | Source checked |
| [content/posts/2026-06-09-home-assistant-docker-deployment-proxmox.md](../content/posts/2026-06-09-home-assistant-docker-deployment-proxmox.md) | Corrected |
| [content/posts/2026-06-09-linux-network-performance-tuning-homelab.md](../content/posts/2026-06-09-linux-network-performance-tuning-homelab.md) | Source checked |
| [content/posts/2026-06-09-proxmox-datacenter-manager-1-1-automated-install-ceph-monitoring.md](../content/posts/2026-06-09-proxmox-datacenter-manager-1-1-automated-install-ceph-monitoring.md) | Source checked |
| [content/posts/2026-06-09-proxmox-ve-cluster-high-availability-homelab.md](../content/posts/2026-06-09-proxmox-ve-cluster-high-availability-homelab.md) | Corrected |
| [content/posts/2026-06-10-docker-compose-startup-dependencies-init-containers.md](../content/posts/2026-06-10-docker-compose-startup-dependencies-init-containers.md) | Corrected |
| [content/posts/2026-06-11-acme-sh-letsencrypt-certificates-homelab-docker.md](../content/posts/2026-06-11-acme-sh-letsencrypt-certificates-homelab-docker.md) | Source checked |
| [content/posts/2026-06-11-docker-container-storage-quotas-xfs.md](../content/posts/2026-06-11-docker-container-storage-quotas-xfs.md) | Corrected |
| [content/posts/2026-06-11-docker-proxy-configuration-homelab.md](../content/posts/2026-06-11-docker-proxy-configuration-homelab.md) | Source checked |
| [content/posts/2026-06-11-linux-auditd-security-auditing-homelab.md](../content/posts/2026-06-11-linux-auditd-security-auditing-homelab.md) | Source checked |
| [content/posts/2026-06-12-docker-compose-yaml-anchors-extensions.md](../content/posts/2026-06-12-docker-compose-yaml-anchors-extensions.md) | Source checked |
| [content/posts/2026-06-12-docker-container-graceful-shutdown-signals.md](../content/posts/2026-06-12-docker-container-graceful-shutdown-signals.md) | Source checked |
| [content/posts/2026-06-12-proxmox-vm-disk-performance-benchmark.md](../content/posts/2026-06-12-proxmox-vm-disk-performance-benchmark.md) | Source checked |
| [content/posts/2026-06-13-docker-supply-chain-security-sbom-image-signing.md](../content/posts/2026-06-13-docker-supply-chain-security-sbom-image-signing.md) | Source checked |
| [content/posts/2026-06-13-podman-rootless-containers-docker-alternative-homelab.md](../content/posts/2026-06-13-podman-rootless-containers-docker-alternative-homelab.md) | Source checked |
| [content/posts/2026-06-15-docker-monitoring-prometheus-grafana-homelab.md](../content/posts/2026-06-15-docker-monitoring-prometheus-grafana-homelab.md) | Source checked |
| [content/posts/2026-06-15-docker-overlay2-storage-driver-linux-guide.md](../content/posts/2026-06-15-docker-overlay2-storage-driver-linux-guide.md) | Corrected |
| [content/posts/2026-06-15-mikrotik-routeros-container-apps-deployment.md](../content/posts/2026-06-15-mikrotik-routeros-container-apps-deployment.md) | Source checked |
| [content/posts/2026-06-15-ntfy-self-hosted-push-notification-server-homelab.md](../content/posts/2026-06-15-ntfy-self-hosted-push-notification-server-homelab.md) | Source checked |
| [content/posts/2026-06-15-opnsense-virtual-firewall-proxmox-homelab.md](../content/posts/2026-06-15-opnsense-virtual-firewall-proxmox-homelab.md) | Source checked |
| [content/posts/2026-06-15-paperless-ngx-docker-deployment-homelab.md](../content/posts/2026-06-15-paperless-ngx-docker-deployment-homelab.md) | Source checked |
| [content/posts/2026-06-15-proxmox-api-tokens-rbac-secure-automation.md](../content/posts/2026-06-15-proxmox-api-tokens-rbac-secure-automation.md) | Source checked |
| [content/posts/2026-06-15-samba-file-server-proxmox-lxc-zfs.md](../content/posts/2026-06-15-samba-file-server-proxmox-lxc-zfs.md) | Source checked |
| [content/posts/2026-06-16-container-runtimes-runc-vs-crun-docker.md](../content/posts/2026-06-16-container-runtimes-runc-vs-crun-docker.md) | Source checked |
| [content/posts/2026-06-16-proxmox-firewall-security-hardening.md](../content/posts/2026-06-16-proxmox-firewall-security-hardening.md) | Source checked |
| [content/posts/2026-06-17-cgroups-v2-docker-container-resource-limits.md](../content/posts/2026-06-17-cgroups-v2-docker-container-resource-limits.md) | Source checked |
| [content/posts/2026-06-17-cilium-cni-k3s-ebpf-networking-homelab.md](../content/posts/2026-06-17-cilium-cni-k3s-ebpf-networking-homelab.md) | Corrected |
| [content/posts/2026-06-18-linux-tcp-bbr-congestion-control-proxmox-docker-lxc.md](../content/posts/2026-06-18-linux-tcp-bbr-congestion-control-proxmox-docker-lxc.md) | Source checked |
| [content/posts/2026-06-20-docusaurus-homelab-documentation-guide.md](../content/posts/2026-06-20-docusaurus-homelab-documentation-guide.md) | Source checked |
| [content/posts/2026-06-20-homelab-10gbe-networking-mikrotik-proxmox.md](../content/posts/2026-06-20-homelab-10gbe-networking-mikrotik-proxmox.md) | Source checked |
| [content/posts/2026-10-30-intel-amt-sol-proxmox.md](../content/posts/2026-10-30-intel-amt-sol-proxmox.md) | Source checked |
| [content/posts/2026-10-30-powershell-modules-onedrive-cleanup.md](../content/posts/2026-10-30-powershell-modules-onedrive-cleanup.md) | Source checked |
| [content/posts/2026-10-30-thinkpad-t420-arch-i3.md](../content/posts/2026-10-30-thinkpad-t420-arch-i3.md) | Source checked |
| [content/posts/first-post.md](../content/posts/first-post.md) | Source checked |
| [content/posts/frigate-deployment.md](../content/posts/frigate-deployment.md) | Source checked |
| [content/posts/r1-router-deployment.md](../content/posts/r1-router-deployment.md) | Source checked |
