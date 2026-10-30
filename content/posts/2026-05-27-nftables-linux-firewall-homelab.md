---
title: "nftables Host Firewall for a Homelab — Add Rules Without Flushing Docker"
description: "Create and verify a separate nftables host-input policy, preserve service-owned tables, and understand why Docker published ports need forwarding rules."
date: 2026-05-27T13:30:00Z
tags:
  - linux
  - networking
  - security
  - firewall
  - homelab
keywords:
  - nftables Linux firewall homelab guide
  - nftables ruleset IPv4 IPv6 practical configuration
  - nftables Docker integration containers networking
  - nftables rate limiting SSH brute force protection
  - nftables logging dropped packets debugging
  - nftables systemd service rule persistence
  - nftables vs iptables migration 2026
summary: "Create and verify a separate nftables host-input policy, preserve service-owned tables, and understand why Docker published ports need forwarding rules."
lastmod: 2026-10-30T12:00:00-04:00
---

nftables can filter IPv4 and IPv6 traffic in one ruleset. The practical challenge is ownership: your host firewall, Docker, a VPN, and a virtualization platform may all create rules. A blanket `flush ruleset` can remove protections and networking rules belonging to those services.

This guide adds a small **host-input** policy in its own table. It does not replace a router firewall or control published Docker ports.

## 1. Check Who Owns the Firewall

Use console access or a tested recovery path before changing remote access rules. This example assumes a static-address Linux server with an IPv4 management subnet of `10.0.99.0/24`. Adapt it for your network, including DHCP or IPv6 management requirements.

```bash
sudo nft list ruleset
sudo iptables --version
sudo systemctl is-active nftables ufw firewalld
docker info 2>/dev/null
```

A command reporting an inactive or absent service is diagnostic information. If UFW, firewalld, Proxmox, or another platform already manages this host, configure its policy through that manager rather than stacking an unexplained additional firewall on top.

Save the existing ruleset for review:

```bash
sudo sh -c 'nft list ruleset > /root/nftables-before-host-policy.rules'
```

An `iptables` version containing `nf_tables` means its rules use the compatibility backend. It does not mean Docker is using its native nftables backend.

## 2. Write a Separate Host-Input Table

This policy permits established traffic, loopback, ICMP/ICMPv6, SSH from the management subnet, and public HTTP/HTTPS. It drops other new traffic addressed to the host. Remove HTTP/HTTPS if this server does not need them. Add explicit rules for any required DHCP, monitoring, VPN, or IPv6 management traffic **before loading it**.

```bash
sudo mkdir -p /etc/nftables.d
sudo tee /etc/nftables.d/gntech-host.nft >/dev/null <<'EOF'
table inet gntech_host {
    chain input {
        type filter hook input priority 0; policy drop;
        ct state invalid drop
        ct state established,related accept
        iifname "lo" accept
        ip protocol icmp accept
        meta l4proto ipv6-icmp accept
        ip saddr 10.0.99.0/24 tcp dport 22 ct state new accept
        tcp dport { 80, 443 } ct state new accept
        limit rate 5/second burst 10 packets log prefix "GNTECH-INPUT-DROP: "
        counter drop
    }
}
EOF
sudo nft -c -f /etc/nftables.d/gntech-host.nft
```

The `-c` check validates the proposed rules without applying them. It does not prove that your SSH client is inside the permitted subnet or that all required services are allowed.

ICMPv6 supports essential functions such as neighbor discovery and path-MTU discovery. Blocking it indiscriminately can break IPv6 even when TCP port rules look correct.

## 3. Load Once and Verify

Only load this file if there is no existing table named `gntech_host`:

```bash
sudo nft list table inet gntech_host
```

If the table does not exist and the syntax check passed:

```bash
sudo nft -f /etc/nftables.d/gntech-host.nft
sudo nft -a list table inet gntech_host
```

Keep the original administration session open. Start a **new** SSH connection from the management subnet, test required application ports, and test a blocked port from another client. An existing SSH session can survive through the established-connection rule while new logins fail.

Inspect counters and logs:

```bash
sudo nft list table inet gntech_host
sudo journalctl -k -g GNTECH-INPUT-DROP -n 50 --no-pager
```

The logging limit is global to this rule. It is not a per-source SSH rate limiter or a dynamic ban list.

## 4. Integrate Persistence Deliberately

The example is a runtime policy until your existing firewall startup process loads it. Integrate the file with that process and test a reboot from a console-accessible maintenance window. Repeatedly loading an additive rules file may duplicate rules, so review how your manager performs replacement.

Do not overwrite `/etc/nftables.conf` or enable an unfamiliar default file that contains `flush ruleset` on a host where Docker or another service owns tables. `nft -f` does not inherently protect other tables: the commands **inside the file** determine what is replaced or flushed.

## Docker Is a Separate Forwarding Path

Published ports on bridge-network containers generally traverse forwarding/NAT, not the host-input chain above. This policy therefore does not provide a container-port allowlist.

Keep Docker's firewall-rule creation enabled unless you deliberately implement all required NAT, isolation, and forwarding behavior yourself. A few `docker0` accept rules do not replace that behavior, and Compose networks normally use additional bridges.

Use the backend-specific procedure:

- [Docker with iptables and UFW](/posts/2026-05-10-docker-ufw-firewall-fix/)
- [Docker's native nftables backend](/posts/2026-06-06-docker-nftables-firewall-backend-homelab/)

For native nftables, place custom restrictions in your own table and account for base-chain priorities. An `accept` verdict in one base chain does not bypass a drop in another.

## Rollback

Remove only this guide's table:

```bash
sudo nft delete table inet gntech_host
```

Also remove its startup inclusion if you configured one. Other firewall tables remain intact. Recheck the host's resulting exposure; removing this table removes its restrictions.

## References

- [nftables: configuring chains and base-chain priorities](https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains)
- [Docker: packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Docker: native nftables backend](https://docs.docker.com/engine/network/firewall-nftables/)
