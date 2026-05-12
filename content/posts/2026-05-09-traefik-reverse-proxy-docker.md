---
title: "Traefik as a Reverse Proxy for Docker — Automatic TLS, Routing, and Middleware"
description: "Full Traefik v3 setup for a Docker homelab — automatic container discovery, Let's Encrypt TLS, HTTP-to-HTTPS redirect, rate limiting, and IP whitelisting. All configs, no theory."
date: 2026-05-09T11:00:00-04:00
tags:
  - traefik
  - docker
  - reverse-proxy
  - networking
  - homelab
---

If your Docker homelab has more than three web services, you need a
reverse proxy. Without one, every container exposes its own port, you
manage certificates by hand (or skip HTTPS entirely), and changing a
service's URL means editing Nginx configs and reloading.

Traefik solves all of this. It watches the Docker socket, discovers new
containers automatically, provisions Let's Encrypt certificates for
any hostname you define via Docker labels, and handles middleware
(auth, rate limiting, headers) without touching a static config file.

This post deploys Traefik v3 on Docker with:
- Automatic container discovery via Docker labels
- Let's Encrypt (HTTP-01 and TLS-ALPN-01 challenges)
- HTTP→HTTPS redirect with permanent redirect middleware
- Rate limiting and IP whitelist examples
- Dashboard secured with HTTP Basic Auth
- Static and dynamic configuration split

---

## Architecture

```
                         Internet
                            │
                     ┌──────▼──────┐
                     │  Cloudflare │ (or any DNS provider)
                     │  ─────────  │
                     │  *.lab.io   │ → your public IP
                     └──────┬──────┘
                            │ port 80, 443
                     ┌──────▼──────┐
                     │   Traefik   │
                     │  ─────────  │
                     │  EntryPoints│
                     │  :80  :443  │
                     └──┬───────┬──┘
                        │       │
         ┌──────────────┼───────┼──────────────────┐
         │              │       │                    │
         │   Docker network: traefik                 │
         │                                            │
         │  ┌─────────┐  ┌─────────┐  ┌──────────┐  │
         │  │ Service A│  │ Service B│  │ Service C│  │
         │  │ web:80   │  │ web:3000│  │ web:8080 │  │
         │  └─────────┘  └─────────┘  └──────────┘  │
         └────────────────────────────────────────────┘
```

Traefik binds to ports 80 and 443 on the host. All other web services
bind to an internal Docker network and are exposed only through Traefik
routes defined by Docker labels. No port conflicts, no manual cert
renewal, no config reloads.

---

## Directory Layout

```
/opt/docker/traefik/
├── compose.yml
├── .env
├── traefik.yml              # Static config
├── config/
│   └── dynamic.yml           # Dynamic config (middleware, etc.)
└── acme.json                 # Let's Encrypt cert storage (auto-created)
```

The split between `traefik.yml` and `config/` is deliberate:
- **Static config** (`traefik.yml`) — entrypoints, providers, cert
  resolvers, logging. Needs a restart to reload.
- **Dynamic config** (`config/dynamic.yml`) — middleware definitions,
  error pages, catch-all routers. Watched and reloaded live by Traefik.

---

## 1. Static Configuration

```yaml
# /opt/docker/traefik/traefik.yml
api:
  dashboard: true
  debug: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
  websecure:
    address: ":443"

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: traefik
  file:
    filename: /etc/traefik/config/dynamic.yml
    watch: true

certificatesResolvers:
  letsencrypt:
    acme:
      email: "${ACME_EMAIL}"
      storage: /etc/traefik/acme.json
      caServer: "https://acme-v02.api.letsencrypt.org/directory"
      httpChallenge:
        entryPoint: web

  letsencrypt-staging:
    acme:
      email: "${ACME_EMAIL}"
      storage: /etc/traefik/acme-staging.json
      caServer: "https://acme-staging-v02.api.letsencrypt.org/directory"
      httpChallenge:
        entryPoint: web

log:
  level: INFO
  filePath: /var/log/traefik.log

accessLog:
  filePath: /var/log/traefik-access.log
  bufferingSize: 100
```

Key points:
- **`exposedByDefault: false`** — containers must explicitly opt in with
  labels. Prevents accidental exposure of services.
- **`network: traefik`** — Traefik only discovers containers connected
  to the `traefik` network.
- **Two cert resolvers** — `letsencrypt` for production, `letsencrypt-staging`
  for testing (avoids rate limit hits during testing).
- **HTTP→HTTPS redirect** — defined at the `web` entrypoint, permanent
  (301). No middleware needed for the basic case.

The `acme.json` file stores certificates. When Traefik starts, it creates
this file with mode 0600 (required). If it doesn't exist, create it:
```bash
touch /opt/docker/traefik/acme.json
chmod 600 /opt/docker/traefik/acme.json
```

---

## 2. Dynamic Configuration (Middlewares)

```yaml
# /opt/docker/traefik/config/dynamic.yml
http:
  middlewares:
    # Security headers for all services
    secHeaders:
      headers:
        browserXssFilter: true
        contentTypeNosniff: true
        frameDeny: true
        sslRedirect: true
        stsIncludeSubdomains: true
        stsPreload: true
        stsSeconds: 31536000
        customFrameOptionsValue: "SAMEORIGIN"
        referrerPolicy: "strict-origin-when-cross-origin"
        permissionsPolicy: "camera=(), microphone=(), geolocation=()"

    # Rate limiting: 100 req/min per IP
    ratelimit:
      rateLimit:
        average: 100
        burst: 50
        period: 1m
        sourceCriterion:
          ipStrategy:
            depth: 1

    # IP whitelist for internal services
    internalOnly:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "172.16.0.0/12"
          - "192.168.0.0/16"
          - "100.64.0.0/10"

    # Basic auth for Traefik dashboard
    dashboard-auth:
      basicAuth:
        users:
          - "${DASHBOARD_USER}:${DASHBOARD_PASSWORD_HASH}"

    # Compress responses
    compress:
      compress:
        excludedContentTypes:
          - text/event-stream
```

Split into reusable middleware building blocks. Services declare which
middleware they want with labels — no monolithic config.

Generate the password hash for basic auth:
```bash
# Install htpasswd
sudo apt install apache2-utils -y

# Generate hash for user "admin" — output goes in .env
echo "admin:$(openssl passwd -apr1)"
```

Take the hash output and put it in your `.env`:
```bash
# /opt/docker/traefik/.env
ACME_EMAIL=admin@example.com
DASHBOARD_USER=admin
DASHBOARD_PASSWORD_HASH=$apr1$xxxx...      # full hash from above
```

---

## 3. Docker Compose

```yaml
# /opt/docker/traefik/compose.yml
services:
  traefik:
    image: traefik:v3.2
    container_name: traefik
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    networks:
      - traefik
    ports:
      - "80:80"
      - "443:443"
    environment:
      - CF_API_EMAIL=${CF_API_EMAIL:-}
      - CF_API_KEY=${CF_API_KEY:-}
      - CF_DNS_API_TOKEN=${CF_DNS_API_TOKEN:-}
      - TZ=America/Santo_Domingo
    env_file:
      - .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
      - ./config:/etc/traefik/config:ro
      - ./acme.json:/etc/traefik/acme.json
      - ./logs:/var/log
    labels:
      # Enable Traefik for itself (dashboard)
      - "traefik.enable=true"

      # Router: dashboard
      - "traefik.http.routers.dashboard.rule=Host(`traefik.lab.io`)"
      - "traefik.http.routers.dashboard.service=api@internal"
      - "traefik.http.routers.dashboard.entrypoints=websecure"
      - "traefik.http.routers.dashboard.tls=true"
      - "traefik.http.routers.dashboard.tls.certresolver=letsencrypt"
      - "traefik.http.routers.dashboard.middlewares=dashboard-auth,secHeaders,ratelimit"

      # Catch-all router for 404 pages (optional)
      - "traefik.http.routers.catchall.rule=HostRegexp(`{host:.+}`)"
      - "traefik.http.routers.catchall.priority=1"
      - "traefik.http.routers.catchall.entrypoints=websecure"
      - "traefik.http.routers.catchall.tls=true"
      - "traefik.http.routers.catchall.middlewares=internalOnly"

networks:
  traefik:
    name: traefik
    external: false
```

**Security notes on cap_add:**
- `NET_BIND_SERVICE` is the minimum capability needed for Traefik to bind
  ports < 1024 (80 and 443).
- `cap_drop: ALL` removes all capabilities, then we add back only what's
  needed.
- The Docker socket is mounted `:ro` (read-only). Traefik only reads
  container metadata — it never writes to the socket.

---

## 4. Exposing Services with Docker Labels

This is where Traefik shines. Any container connected to the `traefik`
network with the right labels is automatically discovered, routed, and
TLS-protected.

### Example: Whoogle Search (self-hosted search)

```yaml
services:
  whoogle:
    image: benbusby/whoogle-search:latest
    container_name: whoogle
    restart: unless-stopped
    networks:
      - traefik
    environment:
      - WHOOGLE_CONFIG_USER=user
      - WHOOGLE_CONFIG_PASS=pass
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.whoogle.rule=Host(`search.lab.io`)"
      - "traefik.http.routers.whoogle.entrypoints=websecure"
      - "traefik.http.routers.whoogle.tls=true"
      - "traefik.http.routers.whoogle.tls.certresolver=letsencrypt"
      - "traefik.http.services.whoogle.loadbalancer.server.port=5000"

networks:
  traefik:
    external: true
```

Only three label groups matter:

| Label | Purpose |
|-------|---------|
| `traefik.enable=true` | Opt-in (required because `exposedByDefault: false`) |
| `traefik.http.routers.<name>.rule=Host(\`host.domain\`)` | Routing rule |
| `traefik.http.routers.<name>.tls.certresolver=letsencrypt` | Auto-get cert |
| `traefik.http.services.<name>.loadbalancer.server.port=<port>` | Container port |

**When you don't need the last label:** If your container exposes port
`80` (or only one port), Traefik auto-detects it. Use the explicit
`.server.port` label when your service uses a non-standard port.

### Example: Grafana with middleware

```yaml
services:
  grafana:
    image: grafana/grafana:11.3.0
    container_name: grafana
    restart: unless-stopped
    networks:
      - traefik
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`grafana.lab.io`)"
      - "traefik.http.routers.grafana.entrypoints=websecure"
      - "traefik.http.routers.grafana.tls=true"
      - "traefik.http.routers.grafana.tls.certresolver=letsencrypt"
      - "traefik.http.routers.grafana.middlewares=secHeaders,ratelimit"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"

networks:
  traefik:
    external: true
```

### Example: Internal-only service (Vaultwarden)

```yaml
services:
  vaultwarden:
    image: vaultwarden/server:latest
    container_name: vaultwarden
    restart: unless-stopped
    networks:
      - traefik
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.vault.rule=Host(`vault.lab.io`)"
      - "traefik.http.routers.vault.entrypoints=websecure"
      - "traefik.http.routers.vault.tls=true"
      - "traefik.http.routers.vault.tls.certresolver=letsencrypt"
      - "traefik.http.routers.vault.middlewares=internalOnly,secHeaders"
      - "traefik.http.services.vault.loadbalancer.server.port=80"

networks:
  traefik:
    external: true
```

The `internalOnly` middleware blocks all traffic not originating from
RFC1918 IPs. If you want to access it externally, use a VPN instead
of exposing it to the internet.

---

## 5. DNS Challenge with Cloudflare

The default HTTP-01 challenge works when Traefik can reach Let's Encrypt
servers on port 80, which it does by default. But if:
- You want wildcard certificates (`*.lab.io`)
- Port 80 is blocked by your ISP
- Your service is behind a NAT where LE can't reach you

Swap to DNS-01 challenge with Cloudflare:

```yaml
# In traefik.yml, replace the cert resolver:
certificatesResolvers:
  letsencrypt:
    acme:
      email: "${ACME_EMAIL}"
      storage: /etc/traefik/acme.json
      caServer: "https://acme-v02.api.letsencrypt.org/directory"
      dnsChallenge:
        provider: cloudflare
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
```

And in `.env`:
```bash
# Global API Key (legacy)
CF_API_EMAIL=admin@example.com
CF_API_KEY=your_global_api_key

# OR — API Token (recommended)
CF_DNS_API_TOKEN=your_dns_api_token
```

Create a Cloudflare API Token with permissions:
- Zone → DNS → Edit
- Zone → Zone → Read

Then with `dnsChallenge`, Traefik can issue wildcard certs — every
`*.lab.io` subdomain is covered by one cert.

---

## 6. Deploying

```bash
# Prepare
mkdir -p /opt/docker/traefik/{config,logs}
touch /opt/docker/traefik/acme.json
chmod 600 /opt/docker/traefik/acme.json

# Edit .env with your email and admin password hash
# Generate the hash:
# openssl passwd -apr1

# Pull and start
cd /opt/docker/traefik
docker compose pull
docker compose up -d

# Check logs
docker compose logs -f --tail=100

# Verify API is running
curl -s -o /dev/null -w "%{http_code}" http://localhost:80
# Should return 301 (redirect to HTTPS)

# Traefik health endpoint
curl -s http://localhost:80/api/http/routers | jq '.[].rule'
```

---

## 7. Testing Certificates with Staging

Before hitting production Let's Encrypt rate limits (50 certs/week per
registered domain), test with the staging resolver:

```yaml
# In a test compose file:
labels:
  - "traefik.http.routers.test.tls.certresolver=letsencrypt-staging"
```

Staging certificates show as untrusted in the browser but confirm your
challenge workflow works. Once it works, switch to `letsencrypt` and
Traefik will replace the cert automatically.

To clear a staging cert:
```bash
docker compose exec traefik rm /etc/traefik/acme-staging.json
docker compose restart traefik
```

---

## 8. Troubleshooting

### "404 page not found" on a new service
- Is the container connected to the `traefik` network?
- Does it have `traefik.enable=true`?
- Does the hostname in `rule=Host(\`...\`)` resolve to this host?
- Check `docker compose logs traefik` for router registration logs.

### Certificate doesn't renew
- Check ACME logs: `docker compose logs traefik | grep acme`
- If using HTTP-01, verify port 80 is reachable from the internet
- If using DNS-01, verify the API token has DNS:Edit permission

### "too many routes" warning in logs
- Every container with `traefik.enable=true` creates at least one
  router. Keep `exposedByDefault: false` and only enable what you need.
- Old containers (stopped or removed) can leave orphaned routes until
  Traefik refreshes from Docker (every few seconds).

### Dashboard shows "Internal Server Error"
- Check basic auth credentials — the hash format must match what
  `openssl passwd -apr1` generates.
- Traefik's own labels must be correct since it discovers routes via
  the same Docker provider as everything else.

### Port 80/443 already in use
- Traefik must be the only service listening on 80/443. If you have
  another web server or Nginx, either stop it or change Traefik's
  bind ports in the compose file and add port mapping at the router
  level.

---

## Why Traefik Over Nginx/Caddy for a Homelab

| Feature | Traefik | Nginx Proxy Manager | Caddy |
|---------|---------|--------------------|-------|
| Auto container discovery | ✅ Native via Docker socket | ❌ Manual per-service | ❌ Manual (or plugin) |
| Auto TLS (LE) | ✅ Built-in | ✅ Built-in | ✅ Built-in |
| Dynamic config (no reload) | ✅ Live reload | ✅ UI-based | ⚠️ File-based |
| Middleware (rate limit, auth) | ✅ Declarative (labels) | ✅ UI-based | ⚠️ Limited |
| Resource usage (idle) | ~40-60 MB RAM | ~60-80 MB RAM | ~15-25 MB RAM |
| Wildcard certs | ✅ DNS-01 | ✅ DNS-01 | ✅ DNS-01 |
| Kubernetes-style labels | ✅ Same syntax | ❌ | ❌ |

I used Nginx Proxy Manager for over a year. It works, but the UI becomes
tedious once you have more than 10 services. Traefik's Docker-native
discovery means you add labels when you write the compose file — one
step, not two. And if you ever move to Kubernetes (or Nomad), Traefik
runs there with the exact same config model.

---

## Resource Usage

| Component | RAM | Disk |
|-----------|-----|------|
| Traefik (idle, 10 routes) | ~45 MB | ~50 MB (logs, certs) |
| Cert storage (10 domains) | — | ~50 KB per cert |
| Access logs (rotated daily) | — | ~10 MB/day (typical lab) |

Negligible. Traefik is written in Go and runs with zero overhead until
traffic hits it.

---

## Summary

```bash
# Quick deploy
mkdir -p /opt/docker/traefik/{config,logs}
touch acme.json && chmod 600 acme.json
# Write traefik.yml, config/dynamic.yml, compose.yml, .env
docker compose up -d

# Add any web service:
#   networks: [traefik] + labels above → auto TLS and routing
```

A reverse proxy is the backbone of a self-hosted Docker environment.
Traefik makes it automatic — you declare routes as container labels
instead of maintaining a config file, TLS is zero-config with Let's
Encrypt, and middleware chains handle security, rate limiting, and
access control without touching a config file.

If you're still mapping port 8080 → container A, port 8081 → container
B, and juggling self-signed certs, spend 20 minutes setting this up.
It's the last reverse proxy config you'll ever write.
