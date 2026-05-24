---
title: "Caddy Reverse Proxy Docker — Automatic HTTPS and Zero-Downtime Reloads"
description: "Complete guide to running Caddy as a Docker reverse proxy — automatic Let's Encrypt HTTPS, Caddyfile snippets for security headers, zero-downtime reloads, Cloudflare DNS-01 wildcards, and production hardening for homelab services."
date: 2026-05-24T16:00:00-04:00
tags:
  - docker
  - docker-compose
  - homelab
  - networking
  - security
keywords:
  - Caddy reverse proxy Docker Compose automatic HTTPS
  - Caddyfile security headers snippet configuration
  - Caddy Docker zero-downtime reload workflow
  - Caddy Cloudflare DNS-01 wildcard certificate
  - Caddy admin API hardening production
  - Caddy HTTP/3 QUIC Docker container
  - Caddy reverse proxy homelab vs Traefik Nginx
summary: "Set up Caddy as a Docker reverse proxy for your homelab — automatic Let's Encrypt HTTPS with zero config, reusable Caddyfile snippets, zero-downtime reloads, Cloudflare DNS-01 wildcards, HTTP/3 support, and production security hardening."
canonical: "https://gntech.dev/posts/caddy-reverse-proxy-docker/"
---

Caddy is the only reverse proxy that gives you automatic HTTPS without plugins, sidecars, or 50 lines of YAML. Point it at a domain, and it provisions a Let's Encrypt certificate, redirects HTTP to HTTPS, sets up OCSP stapling, and renews before expiry — all on first request. No certbot cron, no Traefik middlewares, no Nginx SSL blocks.

If you are running a homelab with a dozen Docker services and a public domain, Caddy is the simplest path from `http://localhost:8080` to `https://app.yourlab.com` with an A+ SSL Labs rating.

This guide covers a production-grade Caddy 2.11+ deployment in Docker Compose: the compose file, the Caddyfile structure, reusable security headers and compression snippets, zero-downtime reloads, Cloudflare DNS-01 wildcard certificates, HTTP/3, admin API hardening, and a pattern for proxying any number of homelab services with virtually zero configuration per service.

Every config works on Docker Engine 24+ with Compose V2 on any Linux host. No Go, no xcaddy, no npm install.

---

## Why Caddy Instead of Nginx or Traefik

Each reverse proxy has a sweet spot. Here is where Caddy wins:

| Feature | Caddy | Nginx | Traefik |
|---|---|---|---|
| Automatic HTTPS | Built-in, enabled by default | Requires certbot/nginx | Requires ACME block + certresolver |
| Config syntax | Caddyfile (concise, readable) | nginx.conf (verbose) | Labels or dynamic YAML |
| Service discovery | Manual Caddyfile or Docker labels | Manual upstreams | Docker provider auto-discovers |
| Memory footprint | ~15 MB idle | ~3 MB idle | ~25 MB idle |
| HTTP/3 | Built-in (quic-go) | Requires nginx-quic build | Built-in |
| Plugin model | xcaddy build | Third-party modules | Provider system |

For a homelab where you want to add a service with exactly one line and get HTTPS immediately, Caddy is the fastest path. If you need Kubernetes-style auto-discovery, Traefik is stronger. If you need raw throughput on static content, Nginx still edges out both.

Caddy's killer feature is the Caddyfile: you define a snippet once (security headers, compression, logging), then apply it to every site with `import`. Adding a new service is a four-line block.

---

## Docker Compose Stack

Create a project directory and three files:

```bash
mkdir -p caddy-stack/caddy && cd caddy-stack
```

### compose.yaml

```yaml
services:
  caddy:
    image: caddy:2.11-alpine
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./caddy:/etc/caddy
      - caddy_data:/data
      - caddy_config:/config
    environment:
      - DOMAIN=${DOMAIN:-example.com}
      - ACME_EMAIL=${ACME_EMAIL:-admin@example.com}
    networks:
      - edge

  # Example services behind Caddy
  whoami:
    image: traefik/whoami:latest
    restart: unless-stopped
    networks:
      - edge

volumes:
  caddy_data:
  caddy_config:

networks:
  edge:
    driver: bridge
```

Key details in this file:

- **No `version:` key** — The Compose Spec deprecated the top-level `version:` field in 2023. Docker Compose V2 prints a deprecation warning if you include it.
- **`cap_add: NET_ADMIN`** — Allows quic-go to raise UDP buffer sizes for HTTP/3. Without it, HTTP/3 works but throughput suffers.
- **`caddy_data` volume** — Persists certificates, private keys, and OCSP staples. Treat this as non-ephemeral. If you delete it, Caddy re-issues every certificate from scratch, which triggers Let's Encrypt rate limits.
- **`caddy_config` volume** — Persists the API config (autosaves). Less critical than `data`, but nice to have.
- **`ports: "443:443/udp"`** — Needed for HTTP/3 (QUIC) over UDP.

### .env

```bash
DOMAIN=gntech.dev
ACME_EMAIL=admin@gntech.dev
```

---

## The Caddyfile

Save this as `caddy/Caddyfile`:

```caddy
# Global options block
{
    email {$ACME_EMAIL}
    admin 127.0.0.1:2019
    servers {
        trusted_proxies 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16
    }
}

# Reusable security headers snippet
(security) {
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        X-XSS-Protection "0"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "camera=(), geolocation=(), microphone=()"
        -Server
    }
}

# Reusable compression snippet
(compress) {
    encode gzip zstd
}

# Catch-all redirect — any unknown hostname → HTTPS with the base domain
{$DOMAIN} {
    redir https://www.{$DOMAIN}{uri}
}

www.{$DOMAIN} {
    redir https://{$DOMAIN}{uri}
}

# Primary site — reverse proxy to whoami container
{$DOMAIN} {
    import security
    import compress

    log {
        output file /data/access.log {
            roll_size 100mb
            roll_keep 5
            roll_keep_for 720h
        }
    }

    reverse_proxy whoami:80
}

# Subdomain example — any service you add gets its own block
api.{$DOMAIN} {
    import security
    import compress

    reverse_proxy whoami:80
}
```

Everything in this file is self-documenting:

- The `(security)` snippet is applied to every site block via `import security`. Add or remove headers in one place, and every site inherits the change.
- The `admin` directive binds the admin API to localhost only. More on this below.
- `trusted_proxies` tells Caddy which subnets are internal. Set this to your homelab IP ranges so Caddy respects `X-Forwarded-For` headers from your Docker bridge and any upstream load balancer.
- The `log` block writes structured logs to the data volume. Adjust `roll_size` to your homelab's traffic volume.

---

## Zero-Downtime Reloads

The Caddyfile is loaded on startup. When you edit the file on the host, the running container does not see the changes until you reload. Caddy supports a graceful, connection-draining reload:

```bash
docker compose exec -w /etc/caddy caddy caddy reload
```

This tells the running Caddy process to re-read `/etc/caddy/Caddyfile`, apply changes atomically, and keep existing connections alive until they complete. There is zero downtime — ongoing requests are not interrupted.

**Important:** The reload only works when `/etc/caddy` is mounted as a directory (not a single file bind). If you mount `./Caddyfile:/etc/caddy/Caddyfile`, the reload command fails because Caddy needs to write temporary files in the config directory.

If you script deploys via CI/CD (Gitea Actions, GitHub Actions), add this as the final step:

```bash
docker compose exec caddy caddy reload &
```

The `&` backgrounding avoids timeout issues when the previous connections take more than a few seconds to drain.

For fully automated reloads, use `inotifywait` on the host to watch the Caddyfile and trigger the reload automatically:

```bash
# Install inotify-tools once, then run:
while inotifywait -e modify /opt/caddy-stack/caddy/Caddyfile; do
  docker compose exec -w /etc/caddy caddy caddy reload
done
```

---

## Admin API Hardening

By default, the Caddy admin API listens on `localhost:2019`. This is the endpoint that `caddy reload` and the autosave engine talk to. In Docker, `localhost` inside the container is the container itself, so the default is safe — external hosts cannot reach it.

However, if you ever bind port `2019` in your compose file, you expose the admin API to your Docker network and potentially the LAN. Caddy's admin API has no built-in authentication — anyone who can reach it can:
- Read the entire config (including domain names and upstream addresses)
- Modify routes dynamically
- Trigger certificate re-issuance

**Never expose port 2019 externally.** If you need remote access to `caddy reload`, SSH into the host and run the command locally.

If you need to reverse-proxy the admin endpoint (for monitoring purposes), add authentication and IP whitelisting:

```caddy
admin.caddy.{$DOMAIN} {
    basicauth {
        admin $2a$14$HASHED_PASSWORD
    }
    reverse_proxy 127.0.0.1:2019
}
```

---

## Cloudflare DNS-01 Wildcard Certificates

The standard Caddy image does HTTP-01 challenges on port 80. This works for most homelab setups, but it has two limitations:

1. **No wildcard certificates** — HTTP-01 only validates specific hostnames. You need a separate certificate for `*.gntech.dev`.
2. **Port 80 must be open** — Not always possible behind NAT or CGNAT.

Cloudflare supports DNS-01 challenges, which verify domain ownership through TXT records instead of HTTP. Caddy handles DNS-01 via the `tls` directive, but you need a custom image with the Cloudflare DNS module.

### Custom Dockerfile

```dockerfile
FROM caddy:2.11-alpine AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2.11-alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
```

Build and tag it:

```bash
docker build -t caddy-cloudflare:2.11 .
docker compose build caddy  # if you reference it in compose
```

### Updated compose.yaml (service override)

```yaml
services:
  caddy:
    build:
      context: .
      dockerfile: Dockerfile
    # ... rest unchanged
```

### Caddyfile wildcard block

```caddy
*.{$DOMAIN}, {$DOMAIN} {
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }

    @api host api.{$DOMAIN}
    handle @api {
        reverse_proxy api-container:3000
    }

    @app host app.{$DOMAIN}
    handle @app {
        reverse_proxy app-container:8080
    }

    # Fallback
    handle {
        respond 404
    }
}
```

Add the Cloudflare API token to `.env`:

```bash
CLOUDFLARE_API_TOKEN=your_api_token_here
```

With this setup, you create one TXT record in Cloudflare, Caddy provisions a single wildcard certificate for `*.gntech.dev`, and every subdomain automatically gets valid HTTPS without individual challenges. DNS propagation takes 30-60 seconds — Caddy retries automatically.

---

## Adding New Services

To add a new homelab service behind Caddy, three steps:

1. **Add a service block** in the Caddyfile:

```caddy
jellyfin.{$DOMAIN} {
    import security
    import compress

    reverse_proxy jellyfin:8096
}
```

2. **Define the container** in `compose.yaml`:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    restart: unless-stopped
    networks:
      - edge
    volumes:
      - jellyfin_config:/config
      - /path/to/media:/media:ro
```

3. **Reload Caddy**:

```bash
docker compose exec -w /etc/caddy caddy caddy reload
```

That is it. Caddy provisions a certificate for `jellyfin.gntech.dev` on the first HTTPS request, and from that point on all traffic is encrypted. No certbot, no nginx sites-available symlinks, no Traefik labels on the container.

---

## Production Checklist

Before putting this stack in front of production-adjacent homelab services, run through these hardening steps:

1. **Disable HTTP/3 on container-to-container traffic** — QUIC over UDP has overhead inside Docker networks. Leave it on for external traffic, but use HTTP/1.1 or H2C for internal reverse_proxy destinations.

2. **Pin the Caddy image tag** — Never use `:latest` in production. Pin to a specific minor: `caddy:2.11-alpine`.

3. **Use Docker secrets for the Cloudflare token** — The `.env` file leaks the token into Compose V2's `docker compose config` output. Use a Docker secret or `--env-file` with restricted permissions:
```bash
chmod 600 .env
```

4. **Rate-limit the Caddy admin API** — If you must expose it to a monitoring tool, add `rate_limit` middleware:
```caddy
@admin_api {
    path /config/*
}
rate_limit @admin_api {
    zone admin_zone {
        key {remote_host}
        events 5
        window 30s
    }
}
```

5. **Monitor certificate expiry** — Caddy auto-renews, but verify with:
```bash
# List all certificates and their expiry dates
docker compose exec caddy caddy cert-info
```

6. **Set up log shipping** — Caddy writes structured JSON logs. Collect them with Loki or any log aggregator:
```yaml
# In compose.yaml
volumes:
  - caddy_data:/data
```
Then configure Promtail or Alloy to tail `/data/access.log`.

---

## Verification

Once deployed, verify everything is working:

```bash
# Check Caddy is running
docker compose ps

# Check the config is loaded
docker compose exec caddy caddy adapt

# Test HTTPS
curl -vI https://gntech.dev

# Check HTTP/3 (requires curl with quiche support)
curl --http3 -I https://gntech.dev

# Run SSL Labs test (web browser)
# https://www.ssllabs.com/ssltest/analyze.html?d=gntech.dev
```

Expected results: A+ rating, TLS 1.3 only, HSTS enabled, HTTP/3 available, no Server header leak.

---

Caddy gives you production-grade HTTPS in Docker with dramatically less boilerplate than the alternatives. For a homelab where services come and go and you want every domain to just work with TLS, it is the pragmatic choice. The Caddyfile pattern — snippets, import, one `reverse_proxy` line per service — scales from a single dashboard to thirty containers without becoming unmanageable.
