---
title: "Traefik Middleware Security Hardening — Headers, Rate Limiting, and Auth"
description: "Harden your homelab reverse proxy with Traefik middlewares — security headers, rate limiting, IP whitelisting, basic auth, and HSTS for an A+ security rating."
date: 2026-05-18T14:30:00-04:00
tags:
  - traefik
  - security
  - docker
  - homelab
  - networking
keywords:
  - Traefik security headers CSP HSTS configuration
  - Traefik rate limiting middleware Docker homelab
  - Traefik IP whitelisting basic auth middleware
  - Traefik HTTP redirect HTTPS middleware chain
  - Traefik middleware Docker compose labels
  - Traefik dynamic YAML middleware configuration
  - harden reverse proxy security score A+
summary: "Complete guide to Traefik middleware security hardening with real-world configs — security headers, rate limiting, IP whitelisting, basic auth, redirect schemes, and chaining middlewares for an A+ security rating."
canonical: "https://blog.gntech.me/posts/traefik-middleware-security-hardening/"
---

Traefik's automatic TLS and Docker service discovery make it the
most popular reverse proxy in the homelab space. But automatic HTTPS
is only the first step. Without security headers, rate limiting, and
access controls at the proxy layer, every exposed service is one
misconfiguration away from leaking server info, getting hammered by
a scraper, or serving content over HTTP.

Traefik middlewares are the mechanism for applying HTTP-level
policies between the edge and your upstream services. Every security
header, rate-limit rule, authentication check, and URL rewrite is a
discrete middleware object that you attach to a router.

This guide covers the middlewares every homelab should deploy:
security headers for an A+ rating, rate limiting to protect against
abuse, IP whitelisting for admin panels, basic auth for staging
environments, forced HTTPS, compression, and the art of chaining
them together. All configs work with Docker labels or dynamic YAML
files.

---

## How Traefik Middlewares Work

A middleware intercepts the request before it reaches your
application or the response before it leaves the proxy. Traefik
processes middlewares in the order they are listed on the router.

**Two ways to define middlewares:**

**1. Docker labels** — inline on the container:

```yaml
# docker-compose.yml
services:
  myapp:
    image: nginx
    labels:
      - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.myapp.middlewares=secHeaders@docker"
```

The `@docker` provider references a middleware defined with the
`traefik.http.middlewares.<name>` label prefix on the same or another
container.

**2. Dynamic YAML file** — reusable across all services:

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    secHeaders:
      headers:
        browserXssFilter: true
        contentTypeNosniff: true
        frameDeny: true
```

Reference it with `@file` provider:

```yaml
labels:
  - "traefik.http.routers.myapp.middlewares=secHeaders@file"
```

The YAML approach is cleaner for shared middlewares — define once,
use everywhere. The label approach is fine for per-service overrides.

---

## 1. Security Headers Middleware — A+ Rating

Security headers tell browsers how to behave when rendering your
content. Missing headers are the most common reason for low security
scores on tools like Mozilla Observatory and securityheaders.com.

### The Complete Security Headers Middleware

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    secHeaders:
      headers:
        # XSS Protection
        browserXssFilter: true
        contentTypeNosniff: true

        # Clickjacking protection
        frameDeny: true
        customFrameOptionsValue: "SAMEORIGIN"

        # HSTS — force HTTPS for 1 year
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true

        # Referrer policy
        referrerPolicy: "strict-origin-when-cross-origin"

        # Permissions policy — restrict browser features
        permissionsPolicy: |
          camera=(), microphone=(), geolocation=(),
          payment=(), usb=(), magnetometer=(), accelerometer=()

        # Content Security Policy
        contentSecurityPolicy: >
          default-src 'self';
          script-src 'self' 'unsafe-inline' 'unsafe-eval';
          style-src 'self' 'unsafe-inline';
          img-src 'self' data: https:;
          font-src 'self' data:;
          object-src 'none';
          base-uri 'none';
          form-action 'self';
          frame-ancestors 'self';
          upgrade-insecure-requests;

        # Strip server fingerprinting headers
        customResponseHeaders:
          server: ""
          x-powered-by: ""
```

**What each header does:**

| Header | Effect |
|--------|--------|
| `browserXssFilter` | Enables browser's reflected XSS filter (X-XSS-Protection: 1; mode=block) |
| `contentTypeNosniff` | Prevents MIME type sniffing (X-Content-Type-Options: nosniff) |
| `frameDeny` | Blocks all iframe embedding (X-Frame-Options: DENY) |
| `stsSeconds: 31536000` | HSTS for 1 year — browser remembers HTTPS-only |
| `stsPreload: true` | Eligible for browser HSTS preload lists |
| `referrerPolicy` | Controls Referer header sent with requests |
| `permissionsPolicy` | Disables unnecessary browser APIs (camera, mic, etc.) |
| `contentSecurityPolicy` | Whitelists allowed content sources |
| `customResponseHeaders` | Strips Server and X-Powered-By headers |

### Apply to All Routers — Default Middleware

Repeat this on every router label is tedious. Instead, define a
default middleware per entrypoint:

```yaml
# traefik.yml static config
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https

  websecure:
    address: ":443"
    http:
      middlewares:
        - secHeaders@file
        - rateLimit@file
```

Every request hitting the HTTPS entrypoint automatically gets the
security headers and rate limiting without per-router labels.

### CSP Tuning for Your Homelab

The CSP above is restrictive — it blocks inline scripts and external
resources by default. Most homelab apps need adjustments:

**For Grafana:**
```yaml
contentSecurityPolicy: >
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'unsafe-eval';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https://*.grafana.net https://*.grafana.com;
  font-src 'self' data:;
  object-src 'none';
  base-uri 'none';
  form-action 'self';
  frame-ancestors 'self';
  connect-src 'self' wss://your-domain.com;
```

**For Vaultwarden:**
```yaml
contentSecurityPolicy: >
  default-src 'self';
  script-src 'self' 'unsafe-inline';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data:;
  font-src 'self' data:;
  object-src 'none';
  base-uri 'none';
  form-action 'self';
  frame-ancestors 'none';
  upgrade-insecure-requests;
```

**For services that need WebSockets:**
```yaml
contentSecurityPolicy: >
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'unsafe-eval';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data:;
  font-src 'self' data:;
  connect-src 'self' wss:;
  frame-ancestors 'self';
  upgrade-insecure-requests;
```

Test your CSP with the browser console open — blocked resources show
as console errors with the directive that blocked them.

---

## 2. Rate Limiting Middleware — Protect Against Abuse

Rate limiting prevents a single client from overwhelming your
services. Traefik's rate limiter uses a token bucket algorithm.

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    rateLimit:
      rateLimit:
        # 100 requests per second average
        average: 100
        # Burst up to 200 requests
        burst: 200
        # Source extraction — use client IP
        sourceCriterion:
          ipStrategy:
            depth: 1
```

**Per-service rate limits for specific use cases:**

```yaml
    rateLimitStrict:
      rateLimit:
        average: 20
        burst: 40
        sourceCriterion:
          requestHeader:
            name: "X-Forwarded-For"
            # Use the real client IP when behind Cloudflare

    rateLimitAuth:
      rateLimit:
        average: 5
        burst: 10
        period: 1m  # 5 requests per minute, 10 burst
        sourceCriterion:
          ipStrategy:
            depth: 1

    rateLimitApi:
      rateLimit:
        average: 30
        burst: 60
        sourceCriterion:
          requestHost: true  # Rate limit per hostname
```

### Apply Rate Limits by Service Type

```yaml
# For a public-facing service
labels:
  - "traefik.http.routers.myapp.middlewares=secHeaders@file,rateLimit@file"

# For an admin panel — strict rate limiting
labels:
  - "traefik.http.routers.admin.middlewares=secHeaders@file,rateLimitAuth@file"

# For an API endpoint
labels:
  - "traefik.http.routers.api.middlewares=secHeaders@file,rateLimitApi@file"
```

### Rate Limit + CrowdSec (From Last Week's Post)

Combine rate limiting with CrowdSec for layered protection:

```yaml
labels:
  - "traefik.http.routers.myapp.middlewares=crowdsec-bouncer@file,rateLimit@file,secHeaders@file"
```

Order matters: CrowdSec blocks malicious IPs first (at the
application edge), rate limiting prevents bursts from getting through
to your app, and security headers protect the browser. If CrowdSec
misses a burst, the rate limiter catches it.

---

## 3. IP Whitelisting — Admin Panels and Internal Services

Never expose admin interfaces, dashboards, or management UIs to the
internet. Whitelist them to your home IP or VPN subnet.

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    internalOnly:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "192.168.0.0/16"
          - "172.16.0.0/12"
          - "YOUR_HOME_PUBLIC_IP/32"  # Your static IP if you access remotely
```

**Apply to sensitive services:**

```yaml
# Proxmox web interface via Traefik
labels:
  - "traefik.http.routers.proxmox.rule=Host(`proxmox.example.com`)"
  - "traefik.http.routers.proxmox.middlewares=secHeaders@file,internalOnly@file"

# Portainer
labels:
  - "traefik.http.routers.portainer.rule=Host(`portainer.example.com`)"
  - "traefik.http.routers.portainer.middlewares=secHeaders@file,internalOnly@file"
```

### VPN-Aware Whitelisting

If you use WireGuard or Tailscale for remote access, whitelist the
VPN subnet:

```yaml
    vpnOnly:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "100.64.0.0/10"  # Tailscale / Tailscale IP range
          - "10.100.0.0/16"  # WireGuard subnet
```

When combined with Cloudflare Tunnel (which replaces the visitor IP
with Cloudflare IPs), you need the `X-Forwarded-For` strategy:

```yaml
    cloudflareInternal:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "192.168.0.0/16"
        ipStrategy:
          depth: 2  # Cloudflare adds one hop — look one deeper
```

---

## 4. Basic Auth Middleware — Staging and Private Services

Basic authentication adds an HTTP login prompt to any service without
application-level changes. Invaluable for staging environments,
development dashboards, or services that lack their own auth.

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    stagingAuth:
      basicAuth:
        realm: "Staging Environment"
        users:
          - "admin:$2y$10$..."   # bcrypt hash
          - "reader:$2y$10$..."  # read-only user
```

**Generate the bcrypt hash:**

```bash
# Install htpasswd if needed
sudo apt install -y apache2-utils

# Generate bcrypt hash (interactive — prompts for password)
htpasswd -nB admin | cut -d: -f2

# Or one-liner
htpasswd -nB admin 2>/dev/null
# Enter password when prompted, copy the hash after the colon
```

**With Docker labels (inline users):**

```yaml
services:
  staging:
    image: nginx
    labels:
      - "traefik.http.routers.staging.rule=Host(`staging.example.com`)"
      - "traefik.http.routers.staging.middlewares=stagingAuth@docker"
      - "traefik.http.middlewares.stagingAuth.basicauth.users=admin:$$2y$$10$$..."
```

**Important:** In Docker labels, escape `$` as `$$` — Docker Compose
interprets `$` as variable substitution, so a `$2y$10$...` hash
becomes `$$2y$$10$$...` in the label.

### Multi-User Auth for Teams

```yaml
    teamAuth:
      basicAuth:
        realm: "Team Dashboard"
        usersFile: "/etc/traefik/auth/users.txt"
```

```bash
# /etc/traefik/auth/users.txt (one user per line)
admin:$2y$10$abcdefghijklmnopqrstuvwxyz1234567890abcdefghijklmno
dev1:$2y$10$bcdefghijklmnopqrstuvwxyz1234567890abcdefghijklmnop
ops:$2y$10$cdefghijklmnopqrstuvwxyz1234567890abcdefghijklmnopq
```

Mount the file:

```yaml
volumes:
  - /etc/traefik/auth:/etc/traefik/auth:ro
```

---

## 5. Redirect Scheme — Force HTTPS

HTTP→HTTPS redirect should be the first middleware in every chain.
Traefik handles this at the entrypoint level — cleaner than a
middleware.

```yaml
# traefik.yml static config — the simplest approach
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
```

**Alternative — middleware approach (for selective redirects):**

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    redirectHttps:
      redirectScheme:
        scheme: https
        port: 443
        permanent: true
```

Apply to routers that should only accept HTTPS:

```yaml
labels:
  - "traefik.http.routers.myapp-http.rule=Host(`app.example.com`)"
  - "traefik.http.routers.myapp-http.middlewares=redirectHttps@file"
  - "traefik.http.routers.myapp-http.entrypoints=web"

  - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
  - "traefik.http.routers.myapp.middlewares=secHeaders@file"
  - "traefik.http.routers.myapp.entrypoints=websecure"
  - "traefik.http.routers.myapp.tls.certresolver=letsencrypt"
```

---

## 6. Compression Middleware — Reduce Bandwidth

Gzip or Brotli compression reduces transfer size by 60-80% for text
content. Traefik handles compression transparently.

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    compress:
      compress:
        minContentLength: 256  # Don't compress tiny responses
        excludedContentTypes:
          - "image/png"
          - "image/jpeg"
          - "image/webp"
          - "video/mp4"
          - "application/zip"
```

**Add to the default entrypoint middleware chain:**

```yaml
entryPoints:
  websecure:
    address: ":443"
    http:
      middlewares:
        - compress@file
        - secHeaders@file
        - rateLimit@file
```

Compression is safe for most content but should be skipped for
already-compressed types (images, videos, archives). The
`excludedContentTypes` list prevents double-compression.

---

## 7. Custom Error Pages Middleware

Replace Traefik's generic 404/503 pages with branded or
informational pages.

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    errorPages:
      errors:
        status:
          - "404"
          - "500-599"
        service: errorPagesService
        query: "/{status}.html"
```

Define the error page service:

```yaml
# /opt/traefik/dynamic/services.yml
http:
  services:
    errorPagesService:
      loadBalancer:
        servers:
          - url: "http://host:8083"  # Static file server
```

Or use a simple Docker container serving custom HTML:

```yaml
services:
  error-pages:
    image: tarampampam/error-pages:latest
    environment:
      - TEMPLATE=app-down
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.error-pages.rule=Host(`errors.local`)"
      - "traefik.http.routers.error-pages.internal=true"
```

---

## 8. Chaining Middlewares — Putting It All Together

The real power of Traefik middlewares is chaining. A single router
can pass through multiple middlewares in sequence.

### Default Chain for All Services

```yaml
# traefik.yml
entryPoints:
  websecure:
    address: ":443"
    http:
      middlewares:
        - compress@file        # 1. Compress response
        - secHeaders@file      # 2. Add security headers
        - rateLimit@file       # 3. Rate limit traffic
```

Every service behind this entrypoint gets all three automatically.

### Per-Service Overrides

Add or override middlewares for specific services:

```yaml
# Public service — everything from default chain, plus nothing extra
labels:
  - "traefik.http.routers.public.middlewares="

# Admin service — default chain + IP whitelist
labels:
  - "traefik.http.routers.admin.middlewares=internalOnly@file"

# Staging — default chain + basic auth (added before default chain)
labels:
  - "traefik.http.routers.staging.middlewares=stagingAuth@file"
```

### How Middleware Order Works

Traefik processes middlewares in the exact order listed:

```yaml
labels:
  - "traefik.http.routers.myapp.middlewares=crowdsec-bouncer@file,rateLimitAuth@file,stagingAuth@file,internalOnly@file"
```

Flow:
1. CrowdSec blocks known malicious IPs
2. Rate limiter caps requests to 5/min for auth-heavy routes
3. Basic auth challenges the user for credentials
4. IP whitelist checks if the IP is in the allowed range
5. Default entrypoint chain adds compression + security headers

If any middleware rejects the request, subsequent middlewares never
run. The 403 from the IP whitelist is returned directly.

### Docker Compose Example — Complete Service with All Middlewares

```yaml
# /opt/services/webapp/docker-compose.yml
services:
  webapp:
    image: nginx:alpine
    volumes:
      - ./html:/usr/share/nginx/html:ro
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.webapp.entrypoints=websecure"
      - "traefik.http.routers.webapp.tls=true"
      - "traefik.http.routers.webapp.tls.certresolver=letsencrypt"
      - "traefik.http.routers.webapp.middlewares=compress@file,secHeaders@file,rateLimit@file"
    networks:
      - traefik

  admin:
    image: nginx:alpine
    volumes:
      - ./admin:/usr/share/nginx/html:ro
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.admin.rule=Host(`admin.example.com`)"
      - "traefik.http.routers.admin.entrypoints=websecure"
      - "traefik.http.routers.admin.tls=true"
      - "traefik.http.routers.admin.tls.certresolver=letsencrypt"
      - "traefik.http.routers.admin.middlewares=compress@file,secHeaders@file,rateLimitAuth@file,internalOnly@file"
    networks:
      - traefik

networks:
  traefik:
    external: true
```

---

## 9. Testing Your Middleware Configuration

Validate middleware headers and behavior before relying on them.

### Quick Header Check with curl

```bash
# Check security headers
curl -sI https://app.example.com | grep -iE '^(HTTP|X-|Strict|Content-Security|Referrer|Permissions)'

# Expected output:
# HTTP/2 200
# content-security-policy: default-src 'self'; ...
# strict-transport-security: max-age=31536000; includeSubDomains; preload
# x-content-type-options: nosniff
# x-frame-options: DENY
# x-xss-protection: 1; mode=block
# referrer-policy: strict-origin-when-cross-origin
# permissions-policy: camera=(), microphone=(), ...
```

### Test Rate Limiting

```bash
# Rapid-fire requests — expect 429 after burst is exhausted
for i in $(seq 1 50); do
  curl -s -o /dev/null -w "%{http_code} " http://localhost:8080/
done

# Output: 200 200 ... 200 429 429 429 ...
```

### Test IP Whitelist

```bash
# From a non-whitelisted IP (use a different machine/proxy)
curl -s -o /dev/null -w "%{http_code}" https://admin.example.com
# Expected: 403
```

### Test Basic Auth

```bash
# Without credentials
curl -s -o /dev/null -w "%{http_code}" https://staging.example.com
# Expected: 401

# With correct credentials
curl -s -u admin:password -o /dev/null -w "%{http_code}" https://staging.example.com
# Expected: 200

# With wrong password
curl -s -u admin:wrong -o /dev/null -w "%{http_code}" https://staging.example.com
# Expected: 401
```

### Full Security Scan

```bash
# Install Mozilla Observatory CLI
pip install observatory-cli

# Run scan
observatory --host app.example.com

# Or check manually with their web tool:
# https://developer.mozilla.org/en-US/observatory/
```

A properly configured setup should score A or A+ with no missing
headers.

---

## 10. Common Problems and Fixes

### "HSTS header missing on HTTP redirect"

HSTS only applies to HTTPS responses. Traefik's entrypoint-level
redirect happens before the middleware chain. Keep `stsSeconds` on
the `websecure` entrypoint only — don't add it to `web`.

### "My WebSocket connection is broken"

Rate limiting can interfere with WebSocket upgrade requests:

```yaml
# Exclude WebSocket routers from rate limiting
labels:
  - "traefik.http.routers.websocket.middlewares=secHeaders@file"
  - "traefik.http.routers.websocket.rule=Host(`ws.example.com`)"
  - "traefik.http.routers.websocket.middlewares=secHeaders@file"
```

### "CSP is blocking my dashboard scripts"

Open the browser console. The error message tells you exactly which
directive and source is blocked. Add the needed source to the
appropriate CSP directive. Most homelab apps need `'unsafe-inline'`
and `'unsafe-eval'` in `script-src`.

### "Rate limiting is blocking legitimate traffic"

Increase `average` and `burst` values, or switch to per-client source
criterion. Traffic from a reverse proxy (Cloudflare Tunnel) may all
appear from one source IP — use `X-Forwarded-For` header extraction:

```yaml
rateLimit:
  rateLimit:
    average: 200
    burst: 400
    sourceCriterion:
      requestHeader:
        name: "X-Forwarded-For"
```

### "Basic auth password hash has $ in it"

In Docker Compose labels, every `$` must be doubled:

```yaml
# Wrong — Docker Compose eats the $:
"traefik.http.middlewares.auth.basicauth.users=admin:$2y$10$hash..."

# Correct — double the $:
"traefik.http.middlewares.auth.basicauth.users=admin:$$2y$$10$$hash..."
```

---

## Putting It All Together — A Hardened Homelab Proxy

A complete, hardened Traefik configuration for a homelab:

```yaml
# /opt/traefik/traefik.yml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https

  websecure:
    address: ":443"
    http:
      middlewares:
        - compress@file
        - secHeaders@file
        - rateLimit@file

providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web
```

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    secHeaders:
      headers:
        browserXssFilter: true
        contentTypeNosniff: true
        frameDeny: true
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        referrerPolicy: "strict-origin-when-cross-origin"
        permissionsPolicy: |
          camera=(), microphone=(), geolocation=(),
          payment=(), usb=(), magnetometer=(), accelerometer=()
        contentSecurityPolicy: >
          default-src 'self';
          script-src 'self' 'unsafe-inline' 'unsafe-eval';
          style-src 'self' 'unsafe-inline';
          img-src 'self' data: https:;
          font-src 'self' data:;
          object-src 'none';
          base-uri 'none';
          form-action 'self';
          frame-ancestors 'self';
          upgrade-insecure-requests;
        customResponseHeaders:
          server: ""
          x-powered-by: ""

    rateLimit:
      rateLimit:
        average: 100
        burst: 200
        sourceCriterion:
          ipStrategy:
            depth: 1

    compress:
      compress:
        minContentLength: 256
        excludedContentTypes:
          - image/png
          - image/jpeg
          - image/webp
          - video/mp4
          - application/zip

    internalOnly:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "192.168.0.0/16"
          - "172.16.0.0/12"

    stagingAuth:
      basicAuth:
        realm: "Staging"
        users:
          - "admin:$2y$10$hash..."
```

Reference these middlewares in your service labels:

```yaml
# Public service — default chain handles headers, rate limit, compression
labels:
  - "traefik.http.routers.webapp.rule=Host(`app.example.com`)"
  - "traefik.http.routers.webapp.tls=true"

# Admin service — restricted by IP
labels:
  - "traefik.http.routers.admin.rule=Host(`admin.example.com`)"
  - "traefik.http.routers.admin.tls=true"
  - "traefik.http.routers.admin.middlewares=internalOnly@file"

# Staging — requires basic auth
labels:
  - "traefik.http.routers.staging.rule=Host(`staging.example.com`)"
  - "traefik.http.routers.staging.tls=true"
  - "traefik.http.routers.staging.middlewares=stagingAuth@file"
```

---

## Summary

Traefik middlewares are the difference between a reverse proxy that
merely forwards traffic and one that actively defends your services.
The five middlewares in this guide cover the essential security
layers:

1. **Security headers** (secHeaders) — CSP, HSTS, XSS protection,
   frame denial, server header stripping. The foundation of an A+
   security score.

2. **Rate limiting** (rateLimit) — Token-bucket algorithm prevents
   any single client from overwhelming your services. Tune the
   average/burst per endpoint.

3. **IP whitelisting** (internalOnly) — Keep admin panels, Proxmox,
   Portainer, and dashboards accessible only from your trusted
   subnets and VPN ranges.

4. **Basic auth** (stagingAuth) — Add HTTP authentication to any
   service without modifying the application. Essential for staging
   and dev environments.

5. **Compression** (compress) — Brotli/gzip reduces bandwidth by
   60-80% for text content. Exclude already-compressed types.

Chain them in the right order, apply defaults at the entrypoint
level, and override per-service when needed. The result is a reverse
proxy that scores A+ on security audits, protects against abuse, and
keeps internal services invisible to the public internet — all
without touching a single application configuration.
