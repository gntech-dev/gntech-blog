---
title: "CrowdSec Docker Deployment — Collaborative IPS for Your Homelab"
description: "Deploy CrowdSec with Docker Compose and Traefik to protect your homelab services with collaborative threat intelligence. Covers bouncers, collections, custom scenarios, and remediation."
date: 2026-05-17T10:00:00-04:00
tags:
  - docker
  - docker-compose
  - security
  - homelab
  - traefik
keywords:
  - CrowdSec Docker Compose deployment guide
  - CrowdSec Traefik bouncer IPS setup
  - CrowdSec collaborative IP reputation homelab
  - CrowdSec scenarios custom rules configuration
  - CrowdSec collections nginx ssh protection
  - CrowdSec remediation firewall bouncer Docker
  - CrowdSec fail2ban alternative Docker 2026
summary: "Deploy CrowdSec with Docker Compose and Traefik to protect your homelab services with collaborative threat intelligence. Covers the LAPI agent, bouncers, collections, custom scenarios, and remediation pipeline with real configs."
canonical: "https://gntech.dev/posts/crowdsec-docker-traefik-deployment/"
---

Every homelab exposed to the internet collects unwanted traffic.
Port scanners, credential stuffers, botnets probing for
vulnerabilities. Fail2ban helps, but it works in isolation — one
server learns nothing from another, and your firewall only knows what
it has seen.

CrowdSec replaces this model with a collaborative, behavior-based
approach. When your CrowdSec agent detects a brute-force attempt on
your SSH server, it shares the attacker's IP with the community. You
get the same benefit — your agent pulls the global blocklist and blocks
attackers your neighbors have already seen.

This guide covers a full CrowdSec deployment with Docker Compose and
Traefik, including the LAPI agent, the Traefik bouncer (plugin), a
firewall bouncer for host-level blocking, collections for common
services, and custom scenarios. The result is an intrusion prevention
system that gets smarter the more nodes you add.

---

## How CrowdSec Works

CrowdSec is three components working together:

1. **Agent (LAPI)** — Reads logs, parses them with parsers, runs them
   through scenarios, and decides if an IP is malicious. Runs the Local
   API (LAPI) that bouncers query to check IP reputations.
2. **Bouncers** — The enforcement layer. Bouncers query the LAPI
   periodically or on each request. If the IP is on the blocklist, the
   bouncer drops the connection. Traefik has a native plugin bouncer.
   The firewall bouncer adds nftables/iptables rules at the host level.
3. **CrowdSec Console** — Optional web dashboard showing alerts,
   decisions, and community signals. Self-hosted or cloud.

Decisions flow through a remediation pipeline: **logs → parsers →
scenarios → alert → decision → bouncer → block**. The same pipeline
can also trigger CAPTCHA challenges, rate limiting, or country-based
filtering through the AppSec component.

---

## Step 1: Deploy CrowdSec with Docker Compose

Create the project directory and compose file:

```bash
mkdir -p /opt/crowdsec && cd /opt/crowdsec
```

**`/opt/crowdsec/docker-compose.yml`:**

```yaml
services:
  crowdsec:
    image: crowdsecurity/crowdsec:latest
    container_name: crowdsec
    restart: unless-stopped
    environment:
      - COLLECTIONS=crowdsecurity/nginx crowdsecurity/linux crowdsecurity/http-cve
      - GID=1000
      - CIDR=0.0.0.0/0
    volumes:
      - crowdsec_config:/etc/crowdsec
      - crowdsec_db:/var/lib/crowdsec/data
      - /var/log:/var/log:ro
      - /var/log/auth.log:/var/log/auth.log:ro
    ports:
      - "127.0.0.1:8080:8080"    # LAPI - internal only
    networks:
      - proxy

  # Firewall bouncer — applies nftables rules on the Docker host
  crowdsec-firewall-bouncer:
    image: crowdsecurity/firewall-bouncer:latest
    container_name: crowdsec-fw-bouncer
    restart: unless-stopped
    environment:
      - API_URL=http://crowdsec:8080
      - API_KEY=${FW_BOUNCER_KEY}
    cap_add:
      - NET_ADMIN
      - NET_RAW
    volumes:
      - /etc/nftables:/etc/nftables:rw
    network_mode: host
    depends_on:
      crowdsec:
        condition: service_healthy

volumes:
  crowdsec_config:
  crowdsec_db:

networks:
  proxy:
    external: true
```

The agent mounts host log directories so it can parse Nginx, SSH, and
system logs. The firewall bouncer runs in `network_mode: host` with
NET_ADMIN to install nftables rules. The LAPI port binds to localhost
only — the Traefik bouncer plugin accesses it through the Docker
network.

**Environment file — `/opt/crowdsec/.env`:**

```env
# Generate and set after starting CrowdSec (see below)
FW_BOUNCER_KEY=
```

Start CrowdSec first, then generate the bouncer key:

```bash
docker compose up -d crowdsec

# Wait for it to be healthy, then generate a bouncer API key
docker compose exec crowdsec cscli bouncers add fw-bouncer

# Copy the output key and add it to .env
# Then start the firewall bouncer
docker compose up -d crowdsec-firewall-bouncer
```

---

## Step 2: Install the Traefik CrowdSec Bouncer Plugin

The Traefik plugin bouncer checks every incoming HTTP request against
the CrowdSec LAPI before forwarding it to your service. If the
requester's IP is on the blocklist, Traefik returns a 403 without
touching your backend.

**Enable the plugin in your Traefik static config (`traefik.yml` or CLI
args):**

```yaml
# /opt/traefik/traefik.yml
experimental:
  plugins:
    crowdsec-bouncer:
      moduleName: github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin
      version: v1.6.1
```

**Generate a dedicated bouncer key for Traefik:**

```bash
docker compose exec crowdsec cscli bouncers add traefik-bouncer
# Copy the output
```

**Add the middleware in Traefik dynamic config or file provider:**

```yaml
# /opt/traefik/dynamic/crowdsec.yml
http:
  middlewares:
    crowdsec-bouncer:
      plugin:
        crowdsec-bouncer:
          enabled: true
          logLevel: "error"
          crowdsecMode: "live"
          crowdsecLapiUrl: "http://crowdsec:8080"
          crowdsecLapiKey: "YOUR-TRAEFIK-BOUNCER-KEY"
          crowdsecLapiScheme: "http"
          defaultDecision: "bypass"
```

**Apply the middleware to any router that should be protected:**

```yaml
# Traefik router label or dynamic config
labels:
  - "traefik.http.routers.myapp.middlewares=crowdsec-bouncer@file"
```

Traefik now checks every incoming request against CrowdSec before
reaching your application. The `defaultDecision: bypass` setting means
requests get through if the LAPI is unreachable — fail open, not closed.

---

## Step 3: Collections — Ready-Made Detection Rules

Collections bundle parsers and scenarios for specific services. The
environment variable `COLLECTIONS` in the compose file already pulls:

```yaml
environment:
  - COLLECTIONS=crowdsecurity/nginx crowdsecurity/linux crowdsecurity/http-cve
```

**Add more collections after deployment:**

```bash
# List available collections
docker compose exec crowdsec cscli collections list

# Install specific collections
docker compose exec crowdsec cscli collections install crowdsecurity/sshd
docker compose exec crowdsec cscli collections install crowdsecurity/postfix
docker compose exec crowdsec cscli collections install crowdsecurity/mysql

# See what parsers and scenarios are in a collection
docker compose exec crowdsec cscli collections inspect crowdsecurity/nginx
```

**When running in a Docker homelab, start with these:**

| Collection | What it detects |
|-----------|----------------|
| `crowdsecurity/nginx` | HTTP scans, directory brute-force, 404 probing, SQL injection probes |
| `crowdsecurity/linux` | SSH brute-force, sudo failures, system log anomalies |
| `crowdsecurity/http-cve` | Known CVE exploitation attempts on HTTP services |
| `crowdsecurity/sshd` | SSH dictionary attacks, connection floods |
| `crowdsecurity/base-http-scenarios` | Generic HTTP abuse (rate limiting, path traversal) |
| `crowdsecurity/whitelist-good-actors` | Avoid false positives from known good IPs (Googlebot, Cloudflare, your home IP) |

After installing new collections, reload CrowdSec:

```bash
docker compose exec crowdsec cscli hub update
docker compose exec crowdsec cscli hub upgrade
docker compose restart crowdsec
```

---

## Step 4: Custom Scenarios for Your Lab

Scenarios define the conditions that trigger an alert. Default
collections cover common attacks, but your homelab has unique traffic
patterns. Custom scenarios let you tune detection to your environment.

**Example — Block IPs that hit non-existent subdomains:**

```yaml
# /opt/crowdsec/config/scenarios/myapp-scan.yaml
# Save locally, mount into container later
name: myapp/scan-detection
description: "Detect scanning of non-existent subdomains"
filter: |
  evt.Meta.log_type == 'http_accesslog'
  && evt.Meta.http_status == '404'
  && evt.Meta.http_path startsWith '/'
  && !evt.Meta.http_path matches '^/(robots\.txt|favicon\.ico|healthz)$'
groupby: "evt.Meta.source_ip"
distinct: "evt.Meta.http_path"
capacity: 10
leakspeed: "30s"
blackhole: "5m"
reprocess: true
```

This scenario triggers when a single IP hits 10 different 404 paths
within 30 seconds. The `blackhole: 5m` means the IP is blocked for
5 minutes. Adjust the threshold based on your legitimate traffic.

**Mount custom scenarios:**

Add a volume mount in the compose file:

```yaml
services:
  crowdsec:
    volumes:
      - ./config/scenarios:/etc/crowdsec/scenarios:ro
```

Test the scenario with:

```bash
# Simulate alerts locally (uses the scenario without real data)
docker compose exec crowdsec cscli explain --file /var/log/nginx/access.log --type nginx --scenario myapp/scan-detection
```

---

## Step 5: The Remediation Pipeline — What Happens When CrowdSec Fires

Understanding the alert → decision → remediation flow helps you
troubleshoot and tune.

**1. An IP triggers a scenario**

Example: SSH brute-force from 198.51.100.50 triggers
`crowdsecurity/ssh-bf` after 5 failed logins in 10 seconds.

**2. CrowdSec creates an alert**

```bash
# View active alerts
docker compose exec crowdsec cscli alerts list

# Output:
# ┌──────┬──────────────────┬──────────────┬──────────┬──────────┐
# │  ID  │   Scenario       │   Source     │  Scope   │  Action  │
# ├──────┼──────────────────┼──────────────┼──────────┼──────────┤
# │  42  │ ssh-bf           │ 198.51.100.50│ Ip       │  ban     │
# └──────┴──────────────────┴──────────────┴──────────┴──────────┘
```

**3. CrowdSec creates a decision**

```bash
# View active decisions
docker compose exec crowdsec cscli decisions list

# Output shows IP, duration, scope, and reason
```

**4. Bouncers enforce the decision**

- **Traefik bouncer**: Checks each HTTP request against the LAPI. If
  the IP is banned, Traefik returns 403 before the request reaches your
  service. Latency impact: ~5ms per request.
- **Firewall bouncer**: Adds an nftables drop rule for the IP. The
  kernel drops the packet before any application sees it.

**5. The IP is shared with the CrowdSec community**

If you opt in to the community blocklist (default), your alerts from
public-facing services are shared. In exchange, your agent receives
the global blocklist updates.

**Check what CrowdSec is sharing:**

```bash
docker compose exec crowdsec cscli decisions list --origin CAPI
```

These are community-sourced blocks — IPs other CrowdSec users have
reported.

---

## Step 6: Monitoring and Observability

CrowdSec exposes metrics that integrate with your homelab monitoring
stack.

**Built-in metrics endpoint:**

```yaml
# docker-compose.yml — add to crowdsec service
environment:
  - METRICS_PORT=6060
ports:
  - "127.0.0.1:6060:6060"
```

```bash
# Check live metrics
curl http://127.0.0.1:6060/metrics | grep crowdsec

# Key metrics to watch:
# crowdsec_active_decisions     — Currently blocked IPs
# crowdsec_parsed_logs_total    — Log throughput
# crowdsec_alerts_total         — Alert volume
```

**Prometheus scraping config:**

```yaml
# In your prometheus.yml
scrape_configs:
  - job_name: crowdsec
    static_configs:
      - targets: ["10.0.20.30:6060"]
```

**Grafana dashboard for CrowdSec:**

Import the community dashboard (ID from Grafana.com or build your own
with these panels):

- **Active decisions gauge** — How many IPs are currently blocked
- **Alerts by scenario** — Which attacks are hitting your setup
- **Top blocked IPs** — Worst offenders by alert count
- **Parsed logs rate** — Log throughput (should match your service volume)
- **Bouncer latency** — LAPI response time (should be under 10ms)

**Quick health check:**

```bash
# Check CrowdSec status
docker compose exec crowdsec cscli metrics

# Verify bouncers are connected
docker compose exec crowdsec cscli bouncers list

# Output should show both bouncers with "healthy" status
# ┌──────────────────┬──────────────────────┬────────┬──────────────┐
# │       Name       │        IP            │ Valid  │  Last Pull   │
# ├──────────────────┼──────────────────────┼────────┼──────────────┤
# │ fw-bouncer       │ 10.0.20.30           │ ✔      │ 2s ago       │
# │ traefik-bouncer  │ 10.0.20.30           │ ✔      │ 1s ago       │
# └──────────────────┴──────────────────────┴────────┴──────────────┘
```

---

## Step 7: Whitelisting and Tuning

False positives happen. The whitelist allows you to exclude trusted
sources from enforcement.

**Whitelist your home IP or VPN range:**

```yaml
# /opt/crowdsec/config/parsers/whitelist.yaml
name: crowdsecurity/whitelists
description: "Whitelist trusted IPs for the homelab"
whitelist:
  reason: "trusted internal IP"
  ip:
    - "10.0.0.0/8"
    - "192.168.0.0/16"
    - "172.16.0.0/12"
    - "YOUR_HOME_IP"         # Add your public IP if you access from outside
```

**Whitelist Cloudflare IPs (if you use Cloudflare Tunnel):**

```bash
# Download the latest Cloudflare IP list
curl -s https://www.cloudflare.com/ips-v4 -o /opt/crowdsec/config/cloudflare-ips.txt

# Add to whitelist.yaml
#  ip:
#    - include: /etc/crowdsec/cloudflare-ips.txt
```

**Tune scenario sensitivity per service:**

```bash
# View current scenario parameters
docker compose exec crowdsec cscli scenarios inspect crowdsecurity/ssh-bf

# Override parameters with a local profile
# /opt/crowdsec/config/profiles.yaml
# (CrowdSec applies this on top of collection defaults)
```

If you run a staging environment that generates intentional traffic
anomalies (deploy pipelines, test harnesses), whitelist those source IPs
first before troubleshooting "CrowdSec is blocking my DeployBot."

---

## Step 8: Alert Notifications

CrowdSec sends notifications through plugins. Telegram is the most
useful for the homelab — you get a message when an IP is blocked.

**Enable the Telegram notification plugin:**

```bash
docker compose exec crowdsec cscli plugins install notify-telegram
```

**Create the notification config file:**

```yaml
# /opt/crowdsec/config/notifications/telegram.yaml
type: telegram
name: telegram_default
log_level: info
format: |
  {{range .}}
  🚨 *CrowdSec Alert*
  Scenario: {{.Scenario}}
  Source IP: {{.SourceIP}}
  Action: remediate
  {{end}}
telegram_config:
  token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"
  template: notification
```

**Create a profile that uses this notification:**

```yaml
# /opt/crowdsec/config/profiles.yaml
name: default_profile
filters:
  - Alert.Remediation == true
decisions:
  - type: ban
    duration: 4h
notifications:
  - telegram_default
```

Reload config:

```bash
docker compose restart crowdsec
```

When CrowdSec blocks an IP, the Telegram notification fires
immediately. You can also set up email, Slack, Discord, or webhook
notifications through the same plugin system.

---

## Integrating with the Larger Homelab

CrowdSec in a single stack is useful. CrowdSec across multiple hosts
is transformative. If you run several Proxmox VMs or physical machines:

**Multi-agent setup with a central LAPI:**

- One host runs the CrowdSec agent with LAPI enabled (the setup above)
- Other hosts run CrowdSec agents in **send-only mode** — they parse
  logs and send alerts to the central LAPI, but don't host bouncers
  directly
- The central LAPI keeps the single source of truth for decisions
- All bouncers query the central LAPI

```yaml
# On worker nodes — send-only docker-compose.yml
services:
  crowdsec:
    image: crowdsecurity/crowdsec:latest
    container_name: crowdsec
    restart: unless-stopped
    environment:
      - DISABLE_LOCAL_API=true
      - AGENT_USER_MODE=send
      - AGENT_SERVER=YOUR_CENTRAL_LAPI_IP:8080
      - COLLECTIONS=crowdsecurity/linux crowdsecurity/nginx
    volumes:
      - /var/log:/var/log:ro
```

This setup means a scanner hitting any of your machines gets blocked
across all of them — the first host to detect it shares the decision
with every bouncer in the lab.

---

## Summary

CrowdSec replaces the isolated, reactive security model of Fail2ban
with a collaborative IPS that detects, shares, and blocks threats at
the application and network layers.

The Docker Compose deployment in this guide gives you:

- **Automatic threat detection** — Pre-built collections for Nginx, SSH,
  HTTP CVEs, and more, with community blocklist enrichment
- **Dual-layer enforcement** — Traefik plugin bouncer blocks at the
  reverse proxy level, firewall bouncer blocks at the kernel level
- **Custom detection rules** — Write scenarios tuned to your specific
  homelab traffic patterns
- **Real-time notifications** — Telegram alerts when incidents are detected
- **Multi-host sharing** — One LAPI instance serves all your machines,
  sharing intelligence across the lab

CrowdSec doesn't replace good firewall rules or regular updates. It
adds a behavioral detection layer on top of them. The community
blocklist means you benefit from attacks other homelabs have already
seen, and your blocked IPs help protect the rest of the community in
return.

The compose stack from this guide protects every exposed service.
Traefik middleware catches web-based attacks before they reach your
applications. The firewall bouncer drops SSH scanners, port probes,
and any other connection from a known malicious IP. And when something
new hits one of your services, CrowdSec learns from it — and the rest
of your lab is protected within seconds.
