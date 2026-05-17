---
title: "Pi-hole and Unbound — Recursive DNS with Ad Blocking for the Homelab"
description: "Deploy Pi-hole with Unbound recursive DNS in Docker for private, self-hosted network-wide ad blocking and DNS resolution without upstream logs."
date: 2026-05-16T17:00:00-04:00
tags:
  - dns
  - homelab
  - docker
  - networking
  - security
  - linux
keywords:
  - Pi-hole Unbound Docker Compose
  - recursive DNS homelab setup
  - Pi-hole Docker deployment 2026
  - network-wide ad blocking Docker
  - Pi-hole MikroTik DNS integration
  - Unbound recursive resolver Docker
  - Pi-hole v6 Docker configuration
summary: "Deploy Pi-hole v6 with Unbound as a recursive DNS resolver using Docker Compose. Covers ad blocking, privacy-focused recursive resolution, local DNS records for homelab services, MikroTik router integration, and query monitoring."
canonical: "https://gntech.dev/posts/pihole-unbound-recursive-dns/"
---

Every device on your network sends DNS queries — dozens per minute, even
when idle. Each query is a privacy leak. Your ISP, Google, Cloudflare, or
whoever runs your upstream DNS resolver logs every domain your devices
reach for.

Running Pi-hole with Unbound as a recursive DNS resolver gives you two
things: network-wide ad blocking and complete DNS privacy. Pi-hole filters
out tracking and ad domains at the DNS level. Unbound resolves queries
recursively from the root servers — no upstream provider sees your traffic.

This guide covers a production-grade Docker Compose deployment of Pi-hole
v6 and Unbound, local DNS records for homelab services, integration with
a MikroTik router, monitoring, and query analysis. Everything runs in
two containers with persistent configuration and log rotation.

---

## Why Recursive DNS Changes the Privacy Game

Most DNS setups use a forwarding resolver — Pi-hole receives a query and
forwards it to 1.1.1.1 (Cloudflare), 8.8.8.8 (Google), or your ISP's
resolver. That upstream provider knows every site you visit. They may
log, monetize, or share that data.

A recursive resolver like Unbound starts at the DNS root servers and
follows the delegation chain: root → TLD → authoritative nameserver.
The query is resolved entirely on your hardware. No third party ever sees
the full chain. The only entity that knows which domains you queried is
you.

The latency cost is small — approximately 10-30ms for the initial query
(cache miss), then zero for subsequent queries served from the local
cache. Unbound caches aggressively by default, so repeat queries to the
same domains incur no additional recursion.

**What you gain with the Pi-hole + Unbound stack:**

- **Ad and tracker blocking** — Pi-hole's blocklists strip ads from
  every device, including smart TVs and IoT gadgets that can't run
  ad blockers
- **DNS privacy** — no upstream logging of your queries. Unbound
  validates DNSSEC automatically
- **Local DNS** — resolve homelab services by hostname without external
  DNS providers or split-brain setups
- **Query insights** — see exactly which devices talk to which domains,
  and block suspicious outbound traffic

---

## Docker Compose — Pi-hole v6 and Unbound

This stack runs two containers sharing the same network namespace.
Unbound runs inside Pi-hole's network stack and listens on
`127.0.0.1:5335`. Pi-hole forwards queries to it as the only upstream
DNS server.

**Directory preparation:**

```bash
# Create persistent data directories
sudo mkdir -p /srv/docker/pihole/etc-pihole
sudo mkdir -p /srv/docker/pihole/etc-dnsmasq.d
sudo mkdir -p /srv/docker/unbound

# Set permissions — Pi-hole runs as UID 999/GID 999 by default
sudo chown -R 999:999 /srv/docker/pihole
sudo chmod -R 755 /srv/docker

# Create a custom Unbound config directory
mkdir -p ~/docker/pihole-unbound
cd ~/docker/pihole-unbound
```

**Docker Compose configuration:**

```yaml
version: "3.8"

services:
  unbound:
    image: alpine/unbound:latest
    container_name: unbound
    restart: unless-stopped
    network_mode: service:pihole
    depends_on:
      pihole:
        condition: service_started
    volumes:
      - /srv/docker/unbound:/opt/unbound/etc/unbound:ro
    cap_add:
      - NET_ADMIN
      - NET_RAW
    healthcheck:
      test: ["CMD", "unbound-control", "status"]
      interval: 30s
      timeout: 10s
      retries: 3

  pihole:
    image: pihole/pihole:latest
    container_name: pihole
    restart: unless-stopped
    ports:
      - "53:53/tcp"
      - "53:53/udp"
      - "8081:80/tcp"
    environment:
      TZ: America/Santo_Domingo
      WEBPASSWORD: "your-admin-password-here"
      PIHOLE_DNS_: 127.0.0.1#5335
      DNSSEC: "true"
      CONDITIONAL_FORWARDING: "false"
      BLOCKING_ENABLED: "true"
      WEBTHEME: "default-darker"
      FTLCONF_REPLY_ADDR4: 10.0.20.10
      FTLCONF_LOCAL_IPV4: 10.0.20.10
    volumes:
      - /srv/docker/pihole/etc-pihole:/etc/pihole
      - /srv/docker/pihole/etc-dnsmasq.d:/etc/dnsmasq.d
    cap_add:
      - NET_ADMIN
      - NET_RAW
      - CHOWN
    healthcheck:
      test: ["CMD", "dig", "google.com", "@127.0.0.1", "+short"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
```

**Key configuration notes:**

- `PIHOLE_DNS_: 127.0.0.1#5335` — tells Pi-hole to use Unbound on
  localhost port 5335 as the single upstream. The trailing underscore
  is intentional (Pi-hole v6 parses this env var).
- `DNSSEC: "true"` — enables DNSSEC validation through Unbound.
  Unbound does the cryptographic verification; Pi-hole displays the
  results.
- `FTLCONF_REPLY_ADDR4` — Pi-hole v6 needs to know its own IP to
  respond correctly. Set this to the host IP where Pi-hole is bound.
- `network_mode: service:pihole` — Unbound shares Pi-hole's network
  stack, so localhost inside the container reaches both. No need to
  expose Unbound on any port.
- The web interface is mapped to port 8081 to avoid conflicts with
  other services on port 80.

**Deploy:**

```bash
docker compose up -d
```

---

## Unbound Configuration — Recursive Resolution

Unbound needs a config file that enables recursion and DNSSEC, and
binds to port 5335 instead of the default 53 (Pi-hole owns port 53).

**Create `/srv/docker/unbound/unbound.conf`:**

```ini
server:
    verbosity: 1
    interface: 127.0.0.1
    port: 5335
    do-ip4: yes
    do-ip6: no
    do-udp: yes
    do-tcp: yes
    
    # Access control — only Pi-hole on localhost
    access-control: 127.0.0.1 allow
    access-control: 172.20.0.0/24 allow
    
    # Privacy and security
    hide-identity: yes
    hide-version: yes
    harden-glue: yes
    harden-dnssec-stripped: yes
    use-caps-for-id: yes
    
    # Cache tuning for homelab
    cache-min-ttl: 3600
    cache-max-ttl: 86400
    prefetch: yes
    prefetch-key: yes
    msg-cache-size: 64m
    rrset-cache-size: 128m
    num-threads: 2
    
    # DNSSEC
    auto-trust-anchor-file: /opt/unbound/etc/unbound/root.key
    val-clean-additional: yes
    val-permissive-mode: no
    val-log-level: 2
    
    # Performance
    so-rcvbuf: 1m
    so-sndbuf: 1m
    unwanted-reply-threshold: 10000
    do-not-query-localhost: no

    # Root hints (fallback if root.key is unavailable)
    root-hints: /opt/unbound/etc/unbound/root.hints

    # Do not forward — this is a recursive resolver
    forward-zone:
        name: "."
        forward-first: no
```

**Set up root hints for bootstrap:**

```bash
# Download current root hints
curl -o /srv/docker/unbound/root.hints https://www.internic.net/domain/named.root

# Initialize DNSSEC root trust anchor
docker compose run --rm unbound unbound-anchor -a /opt/unbound/etc/unbound/root.key

# Set ownership
sudo chown -R 999:999 /srv/docker/unbound
sudo chmod 644 /srv/docker/unbound/*.key /srv/docker/unbound/*.hints /srv/docker/unbound/unbound.conf
```

The `do-not-query-localhost: no` directive is critical — without it,
Unbound refuses to answer queries on localhost. The `forward-zone`
block is intentionally commented out or empty: Unbound should resolve
recursively, not forward to another resolver.

**Verify Unbound is working:**

```bash
# Check Unbound status inside the container
docker exec unbound unbound-control status

# Test a recursive query
docker exec pihole dig google.com @127.0.0.1 -p 5335 +short

# Check the Pi-hole web interface at http://10.0.20.10:8081/admin
# The upstream DNS should show "127.0.0.1#5335" as the only server
```

If queries fail, check the Unbound logs:

```bash
docker compose logs unbound
docker compose logs pihole | grep -i dns
```

---

## Local DNS Records for Homelab Services

One of the most useful Pi-hole features for the homelab is local DNS
records. Instead of remembering IPs or relying on external DNS for
internal services, add them to Pi-hole's local DNS configuration.

**Access the Pi-hole container and add records:**

```bash
# Add local DNS records via the API
docker exec pihole pihole-FTL sqlite3 /etc/pihole/gravity.db \
  "INSERT OR IGNORE INTO domainlist (domain, type, enabled) VALUES \
  ('srv1.gntech.internal', 3, 1), \
  ('proxmox.gntech.internal', 3, 1), \
  ('traefik.gntech.internal', 3, 1), \
  ('pihole.gntech.internal', 3, 1), \
  ('grafana.gntech.internal', 3, 1), \
  ('monitoring.gntech.internal', 3, 1), \
  ('ai.gntech.internal', 3, 1);"

# Add corresponding A records
docker exec pihole pihole-FTL sqlite3 /etc/pihole/gravity.db \
  "INSERT OR IGNORE INTO custom_dns (domain, ip) VALUES \
  ('srv1.gntech.internal', '10.0.20.30'), \
  ('proxmox.gntech.internal', '10.0.20.30'), \
  ('traefik.gntech.internal', '10.0.20.10'), \
  ('pihole.gntech.internal', '10.0.20.10'), \
  ('grafana.gntech.internal', '10.0.20.15'), \
  ('monitoring.gntech.internal', '10.0.20.15'), \
  ('ai.gntech.internal', '10.0.20.50');"

# Restart DNS service to pick up changes
docker exec pihole pihole restartdns
```

**Or use the web UI:**

1. Login to `http://10.0.20.10:8081/admin`
2. Local DNS → DNS Records
3. Add each domain → IP mapping

Once configured, every device on your network resolves
`srv1.gntech.internal` and `proxmox.gntech.internal` to the correct IP —
no hosts files, no mDNS, no external DNS providers. This also works for
containers on the same Docker host that need to reach services by
hostname.

**Local DNS best practices:**

- Use a `.internal` or `.home.arpa` TLD — never use `.local` (mDNS
  conflict) or unregistered public TLDs
- Add CNAME records for common aliases (e.g., `srv1 → proxmox`)
- Keep records in sync with your actual IP assignments — document them
  in your homelab README
- Test resolution from a client: `nslookup pihole.gntech.internal
  10.0.20.10`

---

## MikroTik Router Integration

Pointing your MikroTik router at Pi-hole makes the entire network use
your filtered, private DNS — including devices that hardcode their own
DNS settings (most IoT devices use the router's DHCP-provided DNS).

**Set Pi-hole as the system DNS on RouterOS:**

```bash
# Via CLI on your MikroTik
/ip dns set servers=10.0.20.10 allow-remote-requests=no
```

**Or through WinBox/WebFig:**

1. IP → DNS
2. Set Servers: `10.0.20.10`
3. Uncheck "Allow Remote Requests" (you don't want your router acting
   as an open resolver)

**Force all devices to use Pi-hole via DHCP:**

```bash
# Set Pi-hole as the DNS server in your DHCP server config
/ip dhcp-server network set [find address=10.0.20.0/24] \
  dns-server=10.0.20.10

# For multiple VLANs
/ip dhcp-server network set [find address=10.0.30.0/24] \
  dns-server=10.0.20.10
/ip dhcp-server network set [find address=10.0.40.0/24] \
  dns-server=10.0.20.10
```

**Redirect all DNS traffic (even hardcoded DoH/DoT):**

Some devices (Chromecast, Samsung TVs, certain IoT) use hardcoded DNS
like 8.8.8.8 or DNS-over-HTTPS. MikroTik can hijack those:

```bash
# Redirect all port 53 UDP traffic to Pi-hole
/ip firewall nat add chain=dstnat \
  protocol=udp dst-port=53 \
  action=dst-nat to-addresses=10.0.20.10 to-ports=53 \
  comment="Force DNS to Pi-hole"

/ip firewall nat add chain=dstnat \
  protocol=tcp dst-port=53 \
  action=dst-nat to-addresses=10.0.20.10 to-ports=53 \
  comment="Force TCP DNS to Pi-hole"
```

This NAT rule intercepts every DNS packet regardless of the destination
server and redirects it to Pi-hole. Devices using hardcoded 8.8.8.8
still get filtered through your blocklists.

**Block DNS-over-HTTPS (DoH) at the firewall level:**

```bash
# Block known DoH providers at the firewall
/ip firewall filter add chain=forward \
  dst-address-list=doh-providers \
  action=drop comment="Block DNS-over-HTTPS"

# Create the DoH provider address list
/ip firewall address-list add list=doh-providers \
  address=1.1.1.1 comment="Cloudflare DoH"
/ip firewall address-list add list=doh-providers \
  address=8.8.8.8 comment="Google DoH"
/ip firewall address-list add list=doh-providers \
  address=8.8.4.4 comment="Google DoH 2"
/ip firewall address-list add list=doh-providers \
  address=9.9.9.9 comment="Quad9 DoH"
```

**Monitor Pi-hole client activity from MikroTik:**

Enable conditional forwarding or simply check Pi-hole's query log at
`http://10.0.20.10:8081/admin/querylog.php` — every query shows the
client IP, so you can identify which device generated it.

---

## Blocklists and Query Tuning

Pi-hole ships with a default blocklist, but for a homelab, you want
more aggressive blocking without breaking legitimate services.

**Recommended blocklist strategy:**

```bash
# Add these via the Pi-hole web UI (Group Management → Adlists)

# 1. Default list (good baseline)
https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts

# 2. OISD full (balanced — blocks ads and trackers without breakage)
https://small.oisd.nl/

# 3. NoCoin (cryptominers in browser)
https://raw.githubusercontent.com/hoshsadiq/adblock-nocoin-list/master/hosts.txt

# 4. Smart TV blocking (Samsung, LG, Roku telemetry)
https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt

# 5. Firebog Ticked list (community-curated, aggressive)
https://v.firebog.net/hosts/lists.php?type=tick
```

**Update gravity (blocklist database):**

```bash
docker exec pihole pihole updateGravity
```

**Common whitelist entries for homelab services:**

Some legit services get caught in aggressive blocklists. Whitelist them
as needed from the Pi-hole web UI (Group Management → Domain
Whitelist):

- `api.github.com` — Git operations and CI/CD
- `alerts.snyk.io` — vulnerability scanning
- `dc.services.visualstudio.com` — VS Code telemetry (only if you use
  it)
- `device-messaging.owox.com` — monitoring tools
- `firebase-settings.crashlytics.com` — crash reporting
- `graph.facebook.com` — if you use Facebook/Instagram on this
  network
- `push.services.mozilla.com` — Firefox push notifications
- `download.docker.com` — Docker pulls

Monitor the query log for the first week after deployment. Whitelist
what breaks, add lists that catch more trackers. The sweet spot blocks
20-30% of queries on a typical homelab network without breaking anything
useful.

---

## Monitoring and Query Analysis

Pi-hole's web interface provides real-time and historical query data.
The dashboard shows:

- **Total queries** over time (daily, weekly, monthly)
- **Blocked percentage** — target 20-30% on a typical home network.
  Higher means aggressive lists breaking things; lower means you could
  add more lists
- **Top blocked domains** — identifies the worst offenders (often
  analytics, ad networks, telemetry)
- **Top clients** — sorted by query count. Surprising insight into
  which devices talk to the internet most
- **Query log** — real-time feed of every DNS query with client IP,
  domain, and action (allowed/blocked)

**Grafana dashboard for Pi-hole metrics:**

If you already run Grafana (as covered in the homelab monitoring stack),
Pi-hole exposes Prometheus metrics on port 8081:

```yaml
# In your prometheus.yml scrape config
  - job_name: 'pihole'
    static_configs:
      - targets: ['10.0.20.10:8081']
    metrics_path: '/admin/api.php'
    params:
      summary: ['true']
```

Or use the community Pi-hole exporter for richer metrics:

```bash
docker run -d \
  --name pihole-exporter \
  --restart unless-stopped \
  -e PIHOLE_HOSTNAME=10.0.20.10 \
  -e PIHOLE_API_TOKEN=your-api-token-here \
  -p 9617:9617 \
  ekofr/pihole-exporter:latest
```

Then scrape `10.0.20.10:9617` in Prometheus and build a Grafana dashboard
for Pi-hole queries over time, blocked percentages, top clients, and DNS
response times.

**Automation triggers using query patterns:**

The query log can detect compromised devices. A sudden spike in queries
to suspicious domains from a single client is a red flag. Set up
alerting:

- **Query rate alerts** — if a client exceeds 1000 queries/hour,
  investigate. Could be a malware beacon.
- **New domain probing** — repeated NXDOMAIN responses to random
  subdomains (DNS tunneling indicator)
- **Cryptominer domains** — if the NoCoin list blocks a query from a
  device that shouldn't be mining, that device is compromised

---

## Updates, Backups, and Maintenance

**Updating the containers:**

```bash
# Pi-hole and Unbound are updated independently
docker compose pull
docker compose up -d

# Refresh the root hints periodically (every 3 months)
curl -o /srv/docker/unbound/root.hints https://www.internic.net/domain/named.root
```

**Updating blocklists (automated):**

Pi-hole's gravity updates every 7 days by default. Run an immediate
update after adding new lists:

```bash
docker exec pihole pihole updateGravity
```

**Backup strategy:**

Pi-hole's data volume contains everything — blocklist configuration,
local DNS records, client history, and query logs. Back it up regularly:

```bash
#!/bin/bash
# pihole-backup.sh — daily backup to /backups

BACKUP_DIR="/backups/pihole"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

# Backup the entire Pi-hole config volume
docker run --rm \
  -v pihole_etc-pihole:/data \
  -v "$BACKUP_DIR":/backup \
  alpine:latest \
  tar czf "/backup/pihole-config-${DATE}.tar.gz" -C /data .

# Backup Unbound config
tar czf "$BACKUP_DIR/unbound-config-${DATE}.tar.gz" \
  -C /srv/docker unbound/

# Keep 30 days of backups
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "Pi-hole backup complete: ${DATE}"
```

**Restoring from backup:**

```bash
# Stop the stack
docker compose down

# Restore Pi-hole data
docker volume rm pihole_etc-pihole
docker volume create pihole_etc-pihole
docker run --rm \
  -v pihole_etc-pihole:/data \
  -v /backups/pihole:/backup \
  alpine:latest \
  tar xzf "/backup/pihole-config-20260516.tar.gz" -C /data .

# Restart
docker compose up -d
```

---

## Summary

```bash
# Quick reference — essential commands

# Deploy the stack
cd ~/docker/pihole-unbound
docker compose up -d

# Update gravity (blocklists)
docker exec pihole pihole updateGravity

# View real-time query log
docker exec pihole pihole tail

# Check Unbound status
docker exec unbound unbound-control status

# Test recursive DNS
dig google.com @10.0.20.10 +short

# Restart DNS service after config changes
docker exec pihole pihole restartdns

# Web interface
# http://10.0.20.10:8081/admin
```

**Key takeaways:**

1. **Pi-hole + Unbound is the privacy gold standard** — no upstream DNS
   provider logs your queries. Every resolution starts from the root
   servers on your hardware.
2. **The network-mode trick avoids port conflicts** — Unbound runs inside
   Pi-hole's network stack and uses port 5335. Only Pi-hole's port 53 is
   exposed.
3. **Force all DNS through Pi-hole** with MikroTik NAT rules to catch
   devices with hardcoded DNS — IoT and smart TVs are the worst offenders.
4. **Local DNS records eliminate IP management** — add
   `*.gntech.internal` records in Pi-hole and never type an IP address
   again.
5. **Monitor the query log** — it's the best network visibility tool in
   your homelab. Compromised devices, unexpected call-home behavior, and
   DNS tunneling all show up here first.

DNS is the backbone of every homelab. Running it yourself with ad
blocking and recursive resolution isn't just about privacy — it's about
network visibility, control, and understanding what every device on your
network is actually doing.
