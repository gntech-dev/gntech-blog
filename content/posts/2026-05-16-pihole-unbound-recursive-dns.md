---
title: "Pi-hole and Unbound — Recursive DNS with Ad Blocking for the Homelab"
description: "Connect Pi-hole v6 to a local Unbound resolver, verify DNSSEC and filtering, and test one client before changing DHCP settings."
date: 2026-05-16T17:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [dns, homelab, networking, security, linux]
keywords: [Pi-hole v6 Unbound, recursive DNS homelab, DNSSEC verification, Pi-hole local DNS]
summary: "A staged native Linux resolver workflow with explicit privacy limits, client tests, and rollback."
---

Pi-hole filters DNS requests; Unbound can resolve permitted requests recursively and validate DNSSEC. This gives you control over resolution and local policy, not complete DNS privacy.

Recursive queries still leave your network. Network observers and authoritative servers may see parts of that traffic. DNSSEC checks authenticity; it does not encrypt DNS or hide browsing activity. DNS blocking also cannot remove every advertisement or inspect all application traffic.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Official Pi-hole and Unbound references reviewed on October 31, 2026. |
| Static checks | Bash examples syntax checked. |
| Runtime | No Pi-hole installation, Unbound parser/service test, DNSSEC query or router change executed here. |
| Scope | Proposed native Linux lab with Pi-hole v6 and Unbound on the same machine. Docker requires a separate namespace/configuration design. |

## 1. Prepare a disposable resolver host

Use a supported dedicated Linux VM or host, with console access, a stable address, working time synchronization, and current backups. Install Pi-hole using its [official installation instructions](https://docs.pi-hole.net/main/basic-install/) for the selected OS.

Keep clients on their current DNS service while testing. Record the old DHCP DNS values, resolver configuration, and a working administration path independent of the new resolver.

On Debian or Ubuntu, install the resolver and query tools:

```bash
sudo apt update
sudo apt install unbound dnsutils
sudo ss -lntup
timedatectl status
```

Pi-hole needs its DNS listener; Unbound in this design uses loopback port 5335. Check for conflicts before applying changes. Package startup may fail if another service already owns the default DNS port; inspect logs and configure the intended listener rather than disabling unrelated services blindly.

## 2. Configure loopback recursion

Follow the [Pi-hole Unbound guide](https://docs.pi-hole.net/guides/dns/unbound/) and the installed distribution's trust-anchor setup. Root hints locate root servers; a DNSSEC trust anchor serves a different purpose. One is not a fallback for the other.

The following minimal example is for a fresh lab with no existing pi-hole.conf snippet. It preserves other packaged Unbound configuration, including distribution-managed trust-anchor handling.

```bash
(
set -euo pipefail
test ! -e /etc/unbound/unbound.conf.d/pi-hole.conf

sudo tee /etc/unbound/unbound.conf.d/pi-hole.conf > /dev/null <<'EOF'
server:
    interface: 127.0.0.1
    port: 5335
    do-ip4: yes
    do-ip6: no
    do-udp: yes
    do-tcp: yes
    hide-identity: yes
    hide-version: yes
    harden-dnssec-stripped: yes
    qname-minimisation: yes
    edns-buffer-size: 1232
EOF

sudo unbound-checkconf
sudo systemctl restart unbound
sudo systemctl status unbound --no-pager
)
```

Inspect all included configuration for conflicting listeners or forwarding zones. This design has no forward-zone: recursion is the goal. If validation fails, inspect the diagnostics before restarting. The new snippet remains for review; remove or correct only that lab file when reverting.

DNSSEC needs a valid trust anchor and correct time. Verify both rather than assuming a successful service start establishes validation. See the [Unbound configuration reference](https://unbound.docs.nlnetlabs.nl/en/latest/manpages/unbound.conf.html).

The do-ip6 setting above limits Unbound's outbound transport in this lab; it does not stop clients asking for AAAA records or prevent clients using another IPv6 DNS server.

## 3. Test Unbound before connecting Pi-hole

```bash
dig @127.0.0.1 -p 5335 example.com A
dig @127.0.0.1 -p 5335 example.com A +tcp
sudo journalctl -u unbound -n 60 --no-pager
```

Inspect DNS status and answers, not just dig's process exit status: a DNS failure response can still arrive successfully.

Use the current valid-signed and deliberately broken DNSSEC test names documented in the Pi-hole guide. Confirm a valid signed response succeeds and a bogus signature produces SERVFAIL, while ordinary resolution still works. Test names and their external availability can change; record the actual queries and results.

Do not weaken validation merely to make the negative test return an answer.

## 4. Connect Pi-hole and verify filtering

In Pi-hole's supported DNS settings, select 127.0.0.1#5335 as the only upstream for this native same-host test. Remove other upstream choices for the exercise, then verify a query through Pi-hole itself.

Use the web interface or supported v6 configuration/API to add a local test record, such as lab.home.arpa pointing to a disposable lab address. Do not insert records directly into gravity.db: blocklist tables are not local DNS records.

From one test client, query the resolver's actual LAN address. Check:

- External resolution and a local record.
- A deliberately blocked test domain and its query-log policy result.
- Both UDP and TCP DNS reachability.
- The expected client address and recent query timestamp.

Client identity can be obscured by a forwarding router or NAT. A blocked-query percentage is not a health target, and one blocked request is not proof that a device is compromised.

Use the [v6 configuration reference](https://docs.pi-hole.net/ftldns/configfile/) rather than old API paths or guessed SQL schemas. Start with a small known policy and investigate breakage before adding broad allowlists.

## 5. Roll out DHCP without creating a loop

Advertise the tested Pi-hole address to one client group first, renew its lease, and confirm which DNS servers it actually uses. Keep routing and firewall access to the resolver limited to intended client networks.

DHCP advertises DNS; it does not force clients to obey. A public secondary resolver can bypass filtering because clients need not treat it strictly as a standby.

Do not configure Pi-hole to forward to a router that forwards back to Pi-hole. Preserve a working bootstrap path for the resolver host itself. If the new service fails, restore the recorded DHCP values and renew test-client leases before expanding the rollout.

Port-53 redirection applies to conventional DNS, not DoH on HTTPS or DoT on its separate transport. Broad NAT rules can also capture the resolver's own outbound traffic and create loops. This guide intentionally provides no blanket interception rule.

Review IPv6 DNS advertisements, VPN resolvers, browser secure-DNS settings, and managed-device policy separately. A short IP blocklist is not a complete encrypted-DNS enforcement strategy.

See the [MikroTik VLAN guide](/posts/2026-05-12-mikrotik-vlan-segmentation/) for separate router-input and forwarding policies.

## 6. If you use Docker, redesign the boundaries

This native loopback example is not a two-container recipe. Separate containers do not share localhost unless explicitly configured to share a network namespace.

Pi-hole v6 uses documented FTLCONF_* settings, including FTLCONF_dns_upstreams and FTLCONF_webserver_api_password. Do not assume the older PIHOLE_DNS_ or WEBPASSWORD variables configure a v6 image. Environment-managed settings can also constrain UI changes.

Check the selected Unbound image's actual config path, executable, user and writable trust-anchor storage. An unbound-control status probe requires control support to be configured; it is not a universal image health check.

Use the [official Docker documentation](https://docs.pi-hole.net/docker/) for the selected release. Avoid recursive chmod/chown on shared Docker directories, unnecessary capabilities, and public DNS exposure. DNS-over-TCP support is required alongside UDP.

## 7. Back up and prove recovery

Use Pi-hole's supported configuration export/import and back up additional required state consistently. Preserve Unbound configuration, trust-anchor handling, versions and router/DHCP settings separately.

Restore into an isolated lab host and repeat the resolution, filtering, local-record and DNSSEC checks. Do not delete a guessed Docker volume to test recovery. Historical query data and application configuration may have different backup requirements.

Pi-hole's API is not automatically a Prometheus exposition endpoint. Select an exporter explicitly compatible with v6, verify authentication, and inspect actual metrics before configuring a scrape job.

## Continue reading

- [Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — Review namespaces, mounts and environment handling.
- [Monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) — Add service visibility after DNS tests pass.
- [Backup strategy](/posts/2026-05-23-proxmox-backup-strategies/) — Preserve recovery access when infrastructure fails.
