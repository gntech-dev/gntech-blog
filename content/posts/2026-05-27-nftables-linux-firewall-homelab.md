---
title: "nftables Linux Firewall — Practical Homelab Security with nftables"
description: "Practical nftables firewall guide for homelab Linux servers — write IPv4/IPv6 rule sets, manage Docker integration, rate-limit SSH, log dropped packets, and persist rules with systemd."
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
summary: "A practical nftables firewall guide for homelab servers — write IPv4 and IPv6 rule sets, handle Docker integration, rate-limit SSH access, log dropped traffic, and persist rules with systemd on Debian 12 / Ubuntu 24.04."
canonical: "https://gntech.dev/posts/nftables-linux-firewall-homelab/"
---

## Why nftables?

If you're still editing `/etc/iptables/rules.v4` and `rules.v6` separately in 2026, it's time to move on. Debian 12 and Ubuntu 24.04 ship with nftables as the kernel firewall — iptables userspace tools are a compatibility wrapper on top of the nf_tables kernel API.

Check your own system:

```bash
iptables --version
```

Output:
```
iptables v1.8.10 (nf_tables)
```

That `(nf_tables)` means iptables commands are translated to nftables bytecode at runtime. You're already using nftables under the hood — but via a translation layer that's one more abstraction to debug.

**Why switch to native nftables:**

- **Single ruleset for IPv4 and IPv6** — one file, one `inet` family table, no duplicate rules
- **Atomic rule replacement** — `nft -f` applies the entire ruleset atomically; no intermediate window with no rules
- **Native rate limiting** — no external tools like fail2ban for simple rate-based blocking
- **Named sets and maps** — dynamic address lists, policy dispatch, all in-kernel
- **Cleaner syntax** — no arcane line numbering, no append/insert at position confusion
- **Performance** — single pass through the in-kernel bytecode VM

## nftables Basics — Tables, Chains, Rules

nftables organizes rules in three layers: **tables** contain **chains**, which contain **rules**.

### Tables and Address Families

Tables are scoped to an address family. The most useful for homelab servers:

| Family | Purpose |
|--------|---------|
| `inet` | IPv4 and IPv6 combined (default for host filtering) |
| `ip` | IPv4 only |
| `ip6` | IPv6 only |
| `arp` | ARP filtering |
| `bridge` | Bridge port filtering |
| `netdev` | Ingress filtering at the lowest level |

Create a table:

```bash
nft add table inet homelab-filter
```

### Chains and Hooks

Chains define the hook point and processing pipeline:

```bash
nft add chain inet homelab-filter input \
    { type filter hook input priority 0\; }
```

Chain types: `filter` (most rules), `nat` (NAT rules), `route` (policy routing). Priorities determine evaluation order within the same hook — `0` is the default for filter chains, lower numbers run first.

### Rules

Rules combine matches (packet criteria) with verdicts (actions):

```bash
nft add rule inet homelab-filter input tcp dport 22 accept
```

Verdicts: `accept`, `drop`, `reject`, `log`, `counter`, `jump` (sub-chain), `goto`.

### Ruleset Files — The Idiomatic Way

CLI commands are great for testing, but permanent configuration belongs in a file loaded with `nft -f`. The Debian convention is `/etc/nftables.conf`.

```bash
nft -f /etc/nftables.conf
```

## Writing a Practical Homelab Ruleset

Here's a complete, production-ready `/etc/nftables.conf` for a homelab Linux server. This covers a typical machine running SSH, HTTP/HTTPS, Docker containers, and a WireGuard VPN.

```bash
#!/usr/sbin/nft -f

# Flush existing ruleset
flush ruleset

# ── Main table (IPv4 + IPv6) ────────────────────────────────
table inet homelab-filter {

    # ── Named set for SSH rate-limiting (dynamic deny list) ─
    set ssh-bad-guys {
        type ipv4_addr
        flags dynamic
    }

    # ── Base policies ────────────────────────────────────────
    chain input {
        type filter hook input priority 0; policy drop;

        # Allow established / related connections
        ct state established,related accept

        # Allow loopback
        iif lo accept

        # Drop invalid packets early
        ct state invalid drop

        # ICMP — allow key types for IPv4 and IPv6
        ip protocol icmp icmp type {
            echo-request, echo-reply, destination-unreachable,
            time-exceeded, parameter-problem
        } accept

        ip6 nexthdr icmpv6 icmpv6 type {
            echo-request, echo-reply, destination-unreachable,
            packet-too-big, time-exceeded, parameter-problem,
            nd-router-solicit, nd-router-advert,
            nd-neighbor-solicit, nd-neighbor-advert,
            mld-listener-query, mld-listener-report,
            mld-listener-done
        } accept

        # SSH — rate limited, with dynamic deny after abuse
        tcp dport 22 add @ssh-bad-guys { \
            ip saddr limit rate 3/minute burst 5 packets \
        } accept

        # HTTP / HTTPS
        tcp dport { 80, 443 } accept

        # WireGuard
        udp dport 51820 accept

        # Rate-limited logging for dropped packets
        limit rate 5/second burst 10 packets \
            log prefix "NFTABLES-INPUT-DROP: " counter drop

        # Catch-all drop (policy handles this, but log above fires)
    }

    # ── Forward chain — handles Docker bridge traffic ────────
    chain forward {
        type filter hook forward priority 0; policy drop;

        # Allow established / related
        ct state established,related accept

        # Allow docker0 bridge traffic (containers ↔ host)
        iif docker0 accept
        oif docker0 accept

        # Allow forwarding from Docker to physical ports
        iif docker0 oif eth0 accept

        # Allow forwarded traffic from your LAN to Docker services
        iif eth0 oif docker0 ct state new,established accept

        # Rate-limited log for dropped forwards
        limit rate 5/second burst 10 packets \
            log prefix "NFTABLES-FORWARD-DROP: " counter drop
    }

    # ── Output chain ─────────────────────────────────────────
    chain output {
        type filter hook output priority 0; policy accept;
    }
}
```

**Key points in this ruleset:**

- **`inet` family** — one table covers both IPv4 and IPv6
- **`ct state established,related accept`** — necessary in both `input` and `forward` to keep ongoing connections alive
- **ICMPv6** needs more types than ICMPv4 because IPv6 Neighbor Discovery Protocol (NDP) is required for link-layer communication
- **`ssh-bad-guys` set** tracks IPs that exceed the rate limit and blocks them automatically (see section 5)
- **Docker bridge rules** in the `forward` chain — essential when you disable Docker's iptables management

## Docker + nftables — Making Them Work Together

Docker by default manipulates iptables rules to handle container networking. Since Debian 12 / Ubuntu 24.04 use the nftables kernel backend, Docker's `iptables` calls are transparently translated — so it *works* out of the box.

The problem? If you flush the nftables ruleset with `nft flush ruleset`, Docker's rules disappear too. And if your nftables ruleset includes a `forward` chain with `policy drop`, Docker containers lose external connectivity until you add explicit forward rules.

### The Clean Solution: Disable Docker iptables Management

Edit `/etc/docker/daemon.json`:

```json
{
  "iptables": false
}
```

```bash
systemctl restart docker
```

**Caution:** With `"iptables": false`, Docker does not create any firewall rules. Your containers can still reach the internet through the Docker bridge, but only if your nftables `forward` chain explicitly allows it. The ruleset above includes `docker0` rules that make this work.

### Alternative: Let Docker Manage iptables and Don't Flush

If you prefer minimal configuration, leave Docker's default behavior alone. Your nftables ruleset must *add* rules rather than flush everything. Instead of `flush ruleset`, use `nft -f` to create new tables without affecting Docker's internal rules. This approach is simpler but means you lose atomic ruleset replacement.

For most homelab setups, disabling Docker's iptables and writing explicit forward rules is more predictable and auditable.

## Rate Limiting SSH and Brute Force Protection

nftables handles rate limiting natively — no additional packages needed.

### Static Rate Limit (Simple)

The simplest approach: limit SSH connections from any single source to 10 per minute with a burst of 5. Packets exceeding the limit are dropped:

```bash
nft add rule inet homelab-filter input \
    tcp dport 22 \
    limit rate 10/minute burst 5 packets accept
```

Place this before any general SSH accept rule.

### Dynamic Deny Set (Advanced)

For better brute force protection, use a dynamic set that adds offenders to a deny list. Once an IP exceeds the rate limit, it's blocked for the lifetime of the set:

```bash
nft add set inet homelab-filter ssh-bad-guys \
    { type ipv4_addr\; flags dynamic\; }

nft add rule inet homelab-filter input \
    tcp dport 22 add @ssh-bad-guys \
    { ip saddr limit rate 3/minute burst 5 packets\; } accept
```

The first time an IP exceeds 3 connections per minute (burst allowed up to 5), it gets added to `@ssh-bad-guys`. The set has `flags dynamic`, which means matching entries are added at evaluation time. Subsequent packets from that IP hit the set and are dropped by the policy.

To view the current deny list:

```bash
nft list set inet homelab-filter ssh-bad-guys
```

To clear the deny list:

```bash
nft flush set inet homelab-filter ssh-bad-guys
```

## Logging Firewall Events

Logging is essential for debugging and security auditing. But naive logging floods syslog — a single SSH scan can generate thousands of log lines per second. Always rate-limit your log rules.

### Logging with Rate Limits

```bash
nft add rule inet homelab-filter input \
    limit rate 5/second burst 10 packets \
    log prefix "NFTABLES-INPUT-DROP: " counter drop
```

This logs at most 5 packets per second (with a burst of 10), prefixing each log line with `NFTABLES-INPUT-DROP: `. The `counter` tracks how many packets hit this rule — useful for dashboards.

### Viewing Logs

```bash
# Follow in real time, filtering for nftables entries
journalctl -k -f -g NFTABLES

# View the last 50 relevant kernel messages
journalctl -k -g NFTABLES -n 50

# Or grep syslog directly
grep NFTABLES-INPUT-DROP /var/log/syslog | tail -20
```

### Dedicated Log File

Route nftables logs to a separate file via rsyslog. Create `/etc/rsyslog.d/30-nftables.conf`:

```
:msg, contains, "NFTABLES-INPUT-DROP" /var/log/nftables-input.log
:msg, contains, "NFTABLES-FORWARD-DROP" /var/log/nftables-forward.log
& stop
```

```bash
systemctl restart rsyslog
```

This also makes log scraping for Grafana/Loki straightforward — point Promtail at `/var/log/nftables-*.log`.

## Rule Persistence with systemd

Debian and Ubuntu ship the `nftables.service` systemd unit. The default config file is `/etc/nftables.conf`.

### Enable and Start

```bash
systemctl enable nftables
systemctl start nftables
```

### Check Status

```bash
systemctl status nftables
```

The service loads the ruleset at boot. If there's a syntax error, the service fails and you lose your firewall — always validate before reloading.

### Atomic Reload Script

```bash
#!/bin/bash
# /usr/local/bin/nft-reload
# Validate and atomically apply nftables ruleset

CONFIG="/etc/nftables.conf"
TEMP=$(mktemp /tmp/nftables.XXXXXX.conf)

cp "$CONFIG" "$TEMP"

# Syntax check
if ! nft -c -f "$TEMP"; then
    echo "ERROR: Syntax check failed — ruleset NOT applied"
    rm -f "$TEMP"
    exit 1
fi

# Apply — atomic with -f
nft -f "$TEMP" && echo "Ruleset applied successfully"
rm -f "$TEMP"
```

```bash
chmod +x /usr/local/bin/nft-reload
```

### Reload Without Dropping Connections

```bash
systemctl reload nftables
# or
nft -f /etc/nftables.conf
```

`nft -f` replaces rules atomically without flushing connection tracking — existing established connections are unaffected.

## Tools and Debugging

### List the Full Ruleset

```bash
nft list ruleset
```

Watch it live as you make changes:

```bash
watch -n 2 'nft list ruleset'
```

### Packet Tracing with nft monitor

`nft monitor` shows packet traversal through the ruleset in real time:

```bash
nft monitor trace
```

You need to add a trace rule first:

```bash
nft add rule inet homelab-filter input tcp dport 22 meta nftrace set 1
```

Then packets to port 22 will show each chain and rule evaluated with the verdict reached.

### tcpdump for Deep Inspection

nftables tells you what *it* did with a packet. tcpdump tells you what the packet contains:

```bash
tcpdump -i eth0 port 22
```

Combine both when debugging connectivity issues — the firewall rule, and the actual traffic.

### Common Pitfalls

**Missing semicolons in chain declarations:**
```bash
# WRONG — missing escaped semicolon
nft add chain inet homelab-filter input { type filter hook input priority 0 }

# RIGHT — semicolon escaped with backslash
nft add chain inet homelab-filter input { type filter hook input priority 0\; }
```

**Semicolons in nft -f files are NOT escaped** — the shell is not involved when reading from a file.

**IPv6 scoped addresses:** On multi-homed hosts with link-local IPv6, specify the zone ID explicitly:
```bash
nft add rule inet homelab-filter input ip6 saddr fe80::/10 accept
```

**Rule order:** nftables evaluates rules in order. Put your most specific rules first, general rules last. The policy handles anything not explicitly matched.

## Advanced: nftables Sets and Maps

Sets are one of nftables' killer features — in-kernel lookup tables with O(1) performance.

### Named Sets for Dynamic Blocklists

```bash
nft add set inet homelab-filter blocklist { type ipv4_addr\; }

# Add entries
nft add element inet homelab-filter blocklist { 10.0.0.55, 192.168.1.100 }

# Use in a rule
nft add rule inet homelab-filter input ip saddr @blocklist drop
```

### Interval Sets for CIDR Ranges

```bash
nft add set inet homelab-filter lan-allowed \
    { type ipv4_addr\; flags interval\; }

nft add element inet homelab-filter lan-allowed \
    { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }
```

### Maps for Policy Dispatch

Maps let you define service-specific policies:

```bash
nft add map inet homelab-filter port-proto-map \
    { type inet_service\; verdict\; }

nft add element inet homelab-filter port-proto-map \
    { 22 : accept, 80 : accept, 443 : accept, 3306 : drop }

nft add rule inet homelab-filter input tcp dport vmap @port-proto-map
```

## Security Considerations

- **Rule order matters.** Specific rules (accepted services, established connections) must come before catch-all logging and drops. nftables evaluates top-to-bottom per chain.
- **Default deny, allow by exception.** Your base policy for `input` and `forward` should be `drop`. Only open ports you explicitly need.
- **Separate logging chains** keep the main path clean. For complex rulesets, `jump` to a `logging` chain instead of sprinkling `log` verdicts everywhere.
- **Audit your ruleset regularly.** Save `nft list ruleset` output and diff it over time:
  ```bash
  nft list ruleset > /root/firewall-baseline-$(date +%F).txt
  ```
- **Backup `/etc/nftables.conf`** alongside other server configs. Include it in whatever backup strategy you use for `/etc/`.

nftables replaces the legacy iptables/ip6tables/arptables/ebtables stack with one unified, faster, more expressive framework. The migration from Debian 11 to 12 or Ubuntu 22.04 to 24.04 is the perfect time to make the switch — the tools are already on your system, your kernel supports it, and the syntax is clean enough that a single config file can secure a server for years.
