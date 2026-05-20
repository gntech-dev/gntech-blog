---
title: "MikroTik RouterOS 7 DNS Over HTTPS and Adlist — Block Ads Without Pi-Hole"
description: "Configure DNS over HTTPS and the built-in DNS Adlist feature on MikroTik RouterOS 7 to block ads, trackers, and malware at the router level with zero extra hardware or containers."
date: 2026-05-20T10:00:00-04:00
tags:
  - mikrotik
  - dns
  - security
  - networking
keywords:
  - MikroTik RouterOS 7 DNS over HTTPS configuration
  - MikroTik DNS Adlist ad blocking router
  - RouterOS 7 DoH setup step by step
  - MikroTik block ads without Pi-hole
  - DNS Adlist automatic update MikroTik
  - RouterOS DNS cache cache-size configuration
  - MikroTik DNS filtering network-wide blocking
summary: "Configure DNS over HTTPS and the built-in DNS Adlist feature on MikroTik RouterOS 7 to block ads, trackers, and malware network-wide — no Pi-hole, no extra hardware, no containers needed."
canonical: "https://blog.gntech.me/posts/mikrotik-dns-doh-adlist/"
---

There is a recurring question on r/mikrotik: *"Any real benefit to
running Pi-hole for DNS at this point?"* The short answer is less
and less every release. RouterOS 7 gained three features that make
the router itself a credible DNS security appliance:

1. **DNS over HTTPS (DoH)** — Encrypted DNS queries that prevent
   snooping and DNS poisoning
2. **DNS Adlist** — Native domain blocking with automatic list
   updates, null-routing ad/tracker/malware domains to `0.0.0.0`
3. **Built-in DNS cache** — Configurable up to 4 GB, capable of
   handling hundreds of concurrent clients

If you already own a MikroTik router, you can eliminate the
Pi-hole container, reclaim its RAM and CPU, and simplify your
network stack — all while keeping ad blocking at the same level.

This guide covers the complete configuration: DoH setup with
certificate validation, DNS Adlist configuration with automatic
updates, performance tuning, and a comparison against the Pi-hole
approach so you can decide if RouterOS-native DNS is right for you.

---

## What RouterOS 7 DNS Can Do

The DNS subsystem in RouterOS 7 has evolved significantly:

| Feature | RouterOS 6 | RouterOS 7.14+ |
|---------|-----------|-----------------|
| DNS over HTTPS | No | Yes (single server) |
| DNS Adlist | No | Yes |
| Cache size limit | 2048 KiB | Up to 4 GiB |
| Concurrent queries | 100 | 1000+ configurable |
| Regular expression static entries | Yes | Yes (preserved) |
| Firewall address-list integration | Manual | Automatic with `address-list` on DNS static |

The Adlist feature is the key differentiator. It mirrors what
Pi-hole does — maintain a blocklist of known ad/tracker/malware
domains — but runs entirely in RouterOS firmware. No container, no
overlay filesystem, no extra power draw.

### When RouterOS DNS Is Not Enough

Before we dive in, be honest about the limitations:

- **Single DoH server only** — RouterOS supports exactly one DoH
  upstream. No fallback if that server is unreachable.
- **No per-client filtering** — The Adlist applies to all clients
  equally. You cannot have different blocklists for kids vs. adults.
- **No query logging UI** — RouterOS does not have a Pi-hole-style
  dashboard showing top blocked domains, query volume, or client
  statistics.
- **Adlist is static** — Lists are fetched on a schedule. You
  cannot whitelist a blocked domain interactively without editing
  the adlist configuration.
- **No HTTP2 DoH support** — Quad9 uses HTTP2 and will not work
  with RouterOS.

If you need per-client filtering, a detailed dashboard, or
interactive whitelisting, Pi-hole remains the better tool. For
everything else — 80% of homelab use cases — RouterOS DNS is
sufficient and simpler.

---

## Step 1 — Increase DNS Cache Size

The default RouterOS DNS cache is 2048 KiB (2 MB). Adlists consume
cache space — a standard blocklist of 100k domains takes roughly
10-15 MB. Increase the cache to accommodate both cached resolutions
and Adlist entries.

Access your router via SSH or WinBox and run:

```text
/ip dns set cache-size=65536
```

This sets a 64 MB cache. On a router with 256 MB RAM, this is
trivial. For larger blocklists or busy networks:

```text
/ip dns set cache-size=262144
```

256 MB is the practical maximum for most RouterOS devices. Verify:

```text
/ip dns print
```

Look for `cache-size: 262144KiB`.

Also raise the concurrent query limit if you have many clients:

```text
/ip dns set max-concurrent-queries=500
/ip dns set max-concurrent-tcp-sessions=50
```

---

## Step 2 — Configure DNS over HTTPS (DoH)

DoH prevents your ISP, anyone on your local network, or a MITM
attacker from seeing which domains your clients resolve. RouterOS
supports DoH with HTTPS/1.1 only.

### Step 2a — Configure a Standard DNS Fallback

RouterOS needs at least one regular DNS server to resolve the DoH
server's own hostname. This is a chicken-and-egg problem: DoH needs
to resolve the DoH server URL, but DNS is needed to do that.

```text
/ip dns set servers=1.1.1.1
```

Once DoH is active, RouterOS stops using standard DNS queries
entirely — the regular server is only for the initial DoH hostname
resolution and as a fallback if DoH fails.

### Step 2b — Choose a DoH Provider

RouterOS is compatible with these DoH providers:

| Provider | DoH URL | Notes |
|----------|---------|-------|
| Cloudflare | `https://cloudflare-dns.com/dns-query` | Fastest, global anycast |
| Google | `https://dns.google/dns-query` | Reliable, good uptime |
| NextDNS | `https://[your-id].dns.nextdns.io/dns-query` | Custom filtering, analytics |
| OpenDNS | `https://doh.opendns.com/dns-query` | Cisco-backed, family filter options |

**Avoid:** Quad9 (HTTP2 only), Mullvad, Yandex (not supported).

### Step 2c — Install the Root CA Certificate

For `verify-doh-cert=yes`, RouterOS needs the root CA that signed
the DoH server's TLS certificate. Cloudflare uses a certificate
signed by Baltimore CyberTrust Root or GlobalSign. The easiest way:

```text
/tool fetch url="https://curl.se/ca/cacert-2025-12-01.pem"
/certificate import file-name=cacert-2025-12-01.pem
```

Or install a specific CA. For Cloudflare, download the Baltimore
root:

```text
/tool fetch url="https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem"
/certificate import file-name=DigiCertGlobalRootCA.crt.pem
```

Then trust it:

```text
/certificate set [find where common-name~"DigiCert Global Root"] trusted=yes
```

### Step 2d — Enable DoH

```text
/ip dns set use-doh-server=https://cloudflare-dns.com/dns-query \
  verify-doh-cert=yes
```

Verify DoH is active:

```text
/ip dns print
```

Look for `use-doh-server: https://cloudflare-dns.com/dns-query`
and `verify-doh-cert: yes`. The `dynamic-servers` field should show
the DoH server IP.

Test with a domain resolution:

```text
:put ([ resolve "google.com" ]);
```

If this returns an IP address, DoH is working. If it fails, check
the DoH server URL spelling and certificate installation.

### Troubleshooting DoH

```text
# Check for DNS errors in the log
/log print where topics~"dns"
# Verify certificate
/certificate print where trusted=yes
# Flush cache and retry
/ip dns cache flush
```

Common issues:
- **Certificate validation fails** — Wrong CA or missing intermediate
  cert. Try `verify-doh-cert=no` to confirm DoH works, then fix certs
- **DoH timeout** — The DoH server hostname cannot resolve. Verify
  `servers` setting has at least one working DNS server
- **No response** — RouterOS firmware too old. Minimum version: 7.13

---

## Step 3 — Configure DNS Adlist for Ad Blocking

The DNS Adlist feature was introduced in RouterOS 7.14. It
downloads a list of domains from a URL and null-routes A/AAAA
queries for those domains to `0.0.0.0`.

### Step 3a — Find Blocklist Sources

RouterOS expects a plain text file with one domain per line (no
`0.0.0.0` prefix, no `127.0.0.1` prefix — just domain names).

The [mikrotik-adlist](https://github.com/IgorKha/mikrotik-adlist)
project on GitHub maintains curated blocklists in the exact format
RouterOS requires. Lists are auto-generated from the AdGuard Host
Lists Registry and updated weekly.

Available lists (raw URLs for direct use):

| List | URL | Domains | Focus |
|------|-----|---------|-------|
| Standard | `https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/standard.txt` | ~35k | Ads + trackers |
| Strict | `https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/strict.txt` | ~80k | Ads + trackers + analytics |
| DNS Blocklist | `https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt` | ~15k | Minimal ad blocking |

For a first deployment, start with the **standard** list. It
catches 95% of ads without false positives on legitimate services.

### Step 3b — Add the Adlist Entry

```text
/ip dns adlist add url=https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/standard.txt
```

RouterOS immediately downloads and processes the list. Verify:

```text
/ip dns adlist print
```

Output should show:

```text
Flags: *, U - UPDATED
 0   url="https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/standard.txt"
      ssl-verify=yes status=done
```

The `status=done` means the list was downloaded and loaded
successfully. Check how many entries were added:

```text
/ip dns adlist stats
```

### Step 3c — Add Multiple Lists

You can add up to several adlist entries. RouterOS merges them all:

```text
/ip dns adlist add url=https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/standard.txt
/ip dns adlist add url=https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/strict.txt
```

Test that blocking works:

```text
:put ([ resolve "doubleclick.net" ]);
```

Expected result: `0.0.0.0`. If it returns a real IP, the domain is
not in the list.

### Step 3d — Configure Automatic Updates

Adlists change constantly — new ad domains appear, old ones go
away. Schedule a weekly update:

```text
/system scheduler add name=update-adlists \
  interval=7d \
  start-time=03:00:00 \
  on-event="/ip dns adlist update"
```

Verify the scheduler:

```text
/system scheduler print where name=update-adlists
```

The scheduler runs at 3:00 AM every 7 days, refreshes all adlists,
and flushes the DNS cache so stale blocked entries are cleared.

### Step 3e — Whitelist a Domain

If a legitimate service breaks because its domain is in the adlist,
RouterOS has no interactive whitelist UI. Work around it with DNS
static entries:

```text
/ip dns static add name=example.com address=REAL_IP
```

This static entry takes priority over the adlist. To find the real
IP of the blocked domain, temporarily disable the adlist:

```text
/ip dns adlist disable [find]
```

Then resolve the domain:

```text
:put ([ resolve "example.com" ]);
```

Re-enable the adlist:

```text
/ip dns adlist enable [find]
```

---

## Step 4 — Lock Down DNS Access

With DoH and ad blocking active, prevent clients from bypassing
your router's DNS by redirecting all outbound DNS traffic.

### Block External DNS (Firewall Rule)

Add a firewall rule that drops DNS requests to external servers:

```text
/ip firewall filter add chain=forward \
  protocol=udp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=drop \
  comment="Block external DNS (UDP)"

/ip firewall filter add chain=forward \
  protocol=tcp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=drop \
  comment="Block external DNS (TCP)"
```

Replace `10.0.0.0/16` with your LAN subnet and `10.0.0.1` with your
router's LAN IP. Add these rules *after* your allow rules but
*before* the default forward drop rule.

### Force All DNS Through Router (NAT Redirect)

Redirect any DNS traffic destined elsewhere to the router:

```text
/ip firewall nat add chain=dstnat \
  protocol=udp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=redirect to-ports=53 \
  comment="Redirect external DNS to router"
```

This catches clients with hardcoded DNS like `8.8.8.8` and silently
redirects their queries to the RouterOS DNS cache with DoH and
adlist filtering.

---

## Step 5 — Performance Tuning

The DNS cache on a MikroTik is not infinitely scalable. Tune these
parameters for a busy network:

### Cache TTL Tuning

RouterOS honors upstream TTLs but caps them:

```text
/ip dns set cache-max-ttl=4h
```

Setting a max TTL of 4 hours prevents rarely-queried domains from
occupying cache space for the default 7 days. More aggressive:

```text
/ip dns set cache-max-ttl=1h
```

Use 1h on memory-constrained devices (hAP ac², RB750 series).

### DoH Connection Pooling

```text
/ip dns set doh-max-server-connections=10
/ip dns set doh-max-concurrent-queries=200
```

Default values are conservative (5 connections, 50 queries). Doubling
them on a CCR or RB5009 handles burst traffic from many clients.

### Monitor Cache Usage

```text
/ip dns print
```

Check the `cache-used` field. If it approaches `cache-size`, the
cache is thrashing — increase cache size or reduce `cache-max-ttl`.

```text
# Top-level domains in cache
/ip dns cache all print count-only
```

---

## Step 6 — Comparison: RouterOS DNS vs. Pi-hole

| Aspect | RouterOS Adlist | Pi-hole Docker |
|--------|----------------|----------------|
| Hardware required | MikroTik router | Any Docker host |
| RAM usage | ~20-50 MB | ~150-300 MB |
| Setup time | 10 minutes | 30-60 minutes |
| Blocklist management | URL-based, auto-update | UI-based, gravity |
| Whitelisting | Manual static entries | Interactive UI |
| Query dashboard | None | Rich web interface |
| Per-client filtering | No | Yes (groups) |
| DHCP integration | Built-in | Requires DHCP relay |
| DoH upstream | Single server | Multiple (via Unbound) |
| Edge case blocking | DNS-based only | DNS + regex + PID |
| Maintenance | None | Update container |
| Network complexity | Same | + Docker network |

**Choose RouterOS DNS when:**
- You have a MikroTik router with 128 MB+ RAM
- You want zero-maintenance blocking
- You do not need a query dashboard
- The Docker host is resource-constrained
- You want simpler network topology

**Choose Pi-hole when:**
- You need per-client filtering (kids vs. adults)
- You want a rich dashboard with historical data
- You need regex-based ad blocking
- You want interactive whitelisting/blacklisting
- Your router does not support Adlist (pre-7.14)

---

## Step 7 — Full Configuration Script

Here is a complete, copy-paste script for a fresh RouterOS 7
configuration:

```text
# ==========================================
# MikroTik RouterOS 7 DNS Security Setup
# ==========================================

# 1. Increase cache and performance limits
/ip dns set cache-size=65536
/ip dns set cache-max-ttl=4h
/ip dns set max-concurrent-queries=500
/ip dns set max-concurrent-tcp-sessions=50

# 2. Standard DNS fallback
/ip dns set servers=1.1.1.1

# 3. Enable DoH with Cloudflare
/ip dns set use-doh-server=https://cloudflare-dns.com/dns-query \
  verify-doh-cert=yes

# 4. Add DNS Adlist for ad blocking
/ip dns adlist add \
  url=https://raw.githubusercontent.com/IgorKha/mikrotik-adlist/main/hosts/standard.txt \
  ssl-verify=yes

# 5. Schedule weekly adlist updates
/system scheduler add name=update-adlists \
  interval=7d \
  start-time=03:00:00 \
  on-event="/ip dns adlist update"

# 6. Allow remote requests
/ip dns set allow-remote-requests=yes

# 7. Block external DNS bypass
/ip firewall filter add chain=forward \
  protocol=udp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=drop \
  comment="Block external DNS (UDP)"

/ip firewall filter add chain=forward \
  protocol=tcp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=drop \
  comment="Block external DNS (TCP)"

# 8. Redirect hardcoded DNS to router
/ip firewall nat add chain=dstnat \
  protocol=udp dst-port=53 \
  src-address=10.0.0.0/16 \
  dst-address=!10.0.0.1 \
  action=redirect to-ports=53 \
  comment="Redirect external DNS to router"
```

Adjust `src-address` and `dst-address` to match your LAN subnet and
router IP before pasting.

---

## Verifying Everything Works

Test each layer independently:

**1. DoH is encrypting queries:**
```text
/ip dns print
```
Confirm `use-doh-server` is set and `dynamic-servers` is populated.

**2. Adlist is blocking ads:**
```text
:put ([ resolve "doubleclick.net" ]);
:put ([ resolve "googleads.g.doubleclick.net" ]);
:put ([ resolve "pagead2.googlesyndication.com" ]);
```
All should return `0.0.0.0`.

**3. Legitimate resolution still works:**
```text
:put ([ resolve "google.com" ]);
:put ([ resolve "github.com" ]);
:put ([ resolve "mikrotik.com" ]);
```
Should return real IP addresses.

**4. DNS bypass is blocked:**
From a client, run:
```bash
dig @8.8.8.8 google.com
```
This should time out or return a RouterOS-cached response.

**5. Cache is performing:**
```text
/ip dns print
```
`cache-used` should be non-zero and growing.

---

## Summary

RouterOS 7's DNS Adlist and DoH features transform a MikroTik
router from a basic DNS forwarder into a credible network-level
ad-blocking appliance. For the majority of homelab setups, this
eliminates the need for a separate Pi-hole container — saving RAM,
CPU, and network complexity.

The configuration is straightforward:

1. **Increase cache size** to 64-256 MB to accommodate the adlist
2. **Enable DoH** with Cloudflare or Google for encrypted queries
3. **Add Adlist URLs** from GitHub-hosted blocklists in RouterOS
   format
4. **Schedule weekly updates** so the blocklist stays current
5. **Lock down DNS** by blocking external port 53 traffic and
   redirecting hardcoded resolvers
6. **Verify** each layer independently

If you need rich query analytics or per-client filtering, Pi-hole
still has an edge. But for a clean, minimal, single-device DNS
security stack that requires zero maintenance, RouterOS native DNS
is hard to beat.
