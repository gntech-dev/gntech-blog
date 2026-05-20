---
title: "Nginx Docker Deployment — Reverse Proxy and Static Caching for Homelabs"
description: "Deploy Nginx with Docker Compose as a high-performance reverse proxy and caching layer for your homelab services. Covers caching, SSL, gzip, performance tuning, and multi-upstream configuration."
date: 2026-05-20T17:00:00-04:00
tags:
  - docker
  - networking
  - reverse-proxy
  - performance
keywords:
  - Nginx Docker reverse proxy homelab deployment
  - Nginx static file caching Docker Compose
  - Nginx reverse proxy multiple upstream services
  - Nginx performance tuning worker processes buffers
  - Nginx SSL termination Docker internal CA
  - Nginx gzip compression caching configuration
  - Docker Nginx health check logging setup
summary: "Complete guide to deploying Nginx with Docker Compose as a reverse proxy and caching layer. Covers multi-service proxying, static file caching, gzip compression, SSL termination, and performance tuning for homelab environments."
canonical: "https://blog.gntech.me/posts/nginx-reverse-proxy-docker/"
---

Traefik dominates the homelab reverse proxy conversation, and for good reason — automatic service discovery, Let's Encrypt integration, and a slick dashboard. But Traefik is not always the right tool. When you need raw throughput, fine-grained caching control, or a lightweight sidecar that sits in front of a single service, **Nginx** is faster, simpler, and uses fewer resources.

Nginx powers over 30% of the web for good reason: it handles 10,000+ concurrent connections with a single worker process, its caching subsystem supports cache purging and micro-caching, and a minimal config file is more readable than equivalent Traefik middleware chains.

This guide covers deploying Nginx with Docker Compose for four common homelab patterns: reverse proxying multiple services, static file caching with cache-busting, gzip compression, and SSL termination. Every config is copy-paste ready.

---

## Why Run Nginx in Docker

Running Nginx in Docker versus directly on the host gives you:

- **Isolated dependencies** — No nginx packages or PPA management on the host
- **Config-as-code** — Entire proxy setup lives in a compose file and volume mounts
- **Network integration** — Join existing Docker bridge networks to proxy internal services without exposing ports
- **Easy rollback** — Image tags let you pin or roll back Nginx versions instantly

The trade-off is a few milliseconds of Docker networking overhead per request. For homelab traffic (a few hundred requests per second at most), this is invisible.

---

## Step 1 — Basic Docker Compose Deployment

Start with a minimal deployment that serves static files:

```yaml
# /opt/nginx/docker-compose.yml
services:
  nginx:
    image: nginx:1.27-alpine
    container_name: nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./conf.d:/etc/nginx/conf.d:ro
      - ./html:/usr/share/nginx/html:ro
      - ./certs:/etc/nginx/certs:ro
      - ./cache:/var/cache/nginx
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
      - SETGID
      - SETUID
      - CHOWN
      - DAC_OVERRIDE
    healthcheck:
      test: ["CMD", "nginx", "-t"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: 3

networks:
  default:
    name: nginx-net
    external: true
```

Create the required directories:

```bash
mkdir -p /opt/nginx/{conf.d,html,certs,cache}
chmod 700 /opt/nginx/certs
touch /opt/nginx/conf.d/default.conf
```

The main Nginx configuration lives outside `conf.d/`:

```nginx
# /opt/nginx/nginx.conf
user  nginx;
worker_processes  auto;

error_log  /var/log/nginx/error.log warn;
pid        /var/run/nginx.pid;

events {
    worker_connections  4096;
    multi_accept on;
    use epoll;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;
    error_log   /var/log/nginx/error.log warn;

    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout  65;
    keepalive_requests 1000;
    types_hash_max_size 2048;
    server_tokens off;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml
        application/xml+rss
        application/atom+xml
        image/svg+xml;

    # Client body size
    client_max_body_size 100m;
    client_body_buffer_size 16k;

    # Buffer pool
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    output_buffers 2 64k;
    postpone_output 1460;

    # Proxy cache zone
    proxy_cache_path /var/cache/nginx/cache levels=1:2
                     keys_zone=static_cache:50m inactive=7d
                     max_size=1g use_temp_path=off;

    include /etc/nginx/conf.d/*.conf;
}
```

---

## Step 2 — Reverse Proxy Multiple Upstream Services

This is the most common homelab pattern. Define upstream servers and proxy pass rules in `conf.d/`:

```nginx
# /opt/nginx/conf.d/upstreams.conf
# ---- Grafana ----
upstream grafana_upstream {
    zone grafana 64k;
    server grafana:3000 resolve;
    keepalive 32;
}

# ---- GitLab ----
upstream gitea_upstream {
    zone gitea 64k;
    server gitea:3000 resolve;
    keepalive 32;
}

# ---- Home Assistant ----
upstream ha_upstream {
    zone ha 64k;
    server homeassistant:8123 resolve;
    keepalive 16;
}
```

Then create a virtual host for each service:

```nginx
# /opt/nginx/conf.d/grafana.conf
server {
    listen 80;
    server_name grafana.gntech.me;

    location / {
        proxy_pass http://grafana_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 16k;
        proxy_busy_buffers_size 64k;

        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

The key to making Docker service discovery work is configuring Nginx's DNS resolver. Add this to the `http` block in `nginx.conf`:

```nginx
resolver 127.0.0.11 ipv6=off valid=10s;
```

Docker's embedded DNS server runs at `127.0.0.11` on every container. With the `resolve` parameter on each upstream server line, Nginx dynamically resolves container IPs — so you can restart services without reloading Nginx.

---

## Step 3 — Static File Caching with Cache Purging

Static assets like JavaScript bundles, CSS, fonts, and images benefit massively from caching. Nginx's `proxy_cache` subsystem stores responses on disk for a configurable TTL:

```nginx
# /opt/nginx/conf.d/homepage.conf
server {
    listen 80;
    server_name homepage.gntech.me;

    location / {
        proxy_pass http://homepage_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;

        # Caching rules
        proxy_cache static_cache;
        proxy_cache_key "$host$request_uri";
        proxy_cache_valid 200 302 1h;
        proxy_cache_valid 404 1m;

        # Cache status header for debugging
        add_header X-Cache-Status $upstream_cache_status;

        # Bypass cache for admin or dynamic paths
        proxy_cache_bypass $cookie_session;
        proxy_no_cache $cookie_session;

        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Cache purge endpoint (requires ngx_cache_purge or Lua)
    location ~ /purge(/.*) {
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
        proxy_cache_purge static_cache "$host$1";
    }
}
```

The `X-Cache-Status` header tells you whether a request hit (`HIT`), missed (`MISS`), or was served stale (`STALE`). Check it with:

```bash
curl -I http://homepage.gntech.me/
# X-Cache-Status: MISS  (first request)
# X-Cache-Status: HIT   (subsequent requests)
```

For a cache-first workflow, combine `try_files` with `proxy_pass` to serve cached files even when the upstream is down:

```nginx
location /assets/ {
    # Serve from disk cache first, fall back to upstream
    try_files $uri @backend;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

location @backend {
    proxy_pass http://backend_upstream;
    proxy_cache static_cache;
    proxy_cache_valid 200 30d;
}
```

---

## Step 4 — Gzip Compression and Performance Tuning

Nginx's gzip compression reduces bandwidth by 60-80% for text-based responses. The configuration in the base `nginx.conf` enables it globally. Tune these parameters for your homelab:

| Parameter | Default | Recommended | Rationale |
|-----------|---------|-------------|----------|
| `gzip_comp_level` | 1 | 5 | Level 6+ yields diminishing returns for CPU cost |
| `gzip_min_length` | 20 | 256 | Skip tiny responses where compression adds overhead |
| `gzip_types` | text/html | Full list in config above | Include JS, CSS, JSON, XML, SVG |
| `gzip_proxied` | off | any | Compress proxied responses too |

**Worker process tuning** — Nginx can auto-detect core count with `worker_processes auto;`, but for Docker containers you should match the container CPU limit instead:

```nginx
# Match Docker --cpus or deploy.resources.limits.cpus
worker_processes 2;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    multi_accept on;
}
```

If Nginx runs on a single-core container (e.g., a small LXC), the defaults are fine. For front-end caching tier on a multi-core VM, scale `worker_connections` to `8192` and increase the `proxy_buffers`:

```nginx
proxy_buffer_size   8k;
proxy_buffers       16 16k;
proxy_busy_buffers_size 64k;
```

**Sendfile and direct I/O** — For serving large static files (videos, ISOs, backups), enable direct I/O to bypass page cache:

```nginx
location /downloads/ {
    root /var/www/files;
    directio 4m;
    sendfile on;
    sendfile_max_chunk 512k;
    aio threads;
    output_buffers 4 512k;
}
```

`directio 4m` means files over 4 MB bypass the kernel page cache and read directly from disk. Combined with `aio threads`, Nginx reads ahead asynchronously — essential for multi-GB file downloads without blocking worker processes.

---

## Step 5 — SSL Termination with Internal CA

For a homelab, using an internal CA (OpenSSL or Step CA) is simpler and more secure than self-signed certs with trust-store gymnastics. Generate a wildcard cert for your internal domain:

```bash
# Generate a CA key and cert (do this once)
openssl genrsa -out /opt/nginx/certs/ca.key 4096
openssl req -x509 -new -nodes -key /opt/nginx/certs/ca.key \
  -sha256 -days 3650 \
  -out /opt/nginx/certs/ca.crt \
  -subj "/CN=HomeLab Internal CA"

# Generate a wildcard cert for *.gntech.me
openssl genrsa -out /opt/nginx/certs/wildcard.key 2048
openssl req -new -key /opt/nginx/certs/wildcard.key \
  -out /opt/nginx/certs/wildcard.csr \
  -subj "/CN=*.gntech.me"

# Sign with your CA
openssl x509 -req -in /opt/nginx/certs/wildcard.csr \
  -CA /opt/nginx/certs/ca.crt \
  -CAkey /opt/nginx/certs/ca.key \
  -CAcreateserial -out /opt/nginx/certs/wildcard.crt \
  -days 365 -sha256 \
  -extfile <(echo -e "subjectAltName=DNS:*.gntech.me,DNS:gntech.me")
```

Then configure SSL in your virtual host:

```nginx
# /opt/nginx/conf.d/grafana-ssl.conf
server {
    listen 443 ssl http2;
    server_name grafana.gntech.me;

    ssl_certificate     /etc/nginx/certs/wildcard.crt;
    ssl_certificate_key /etc/nginx/certs/wildcard.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # Redirect HTTP to HTTPS
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://grafana_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Add an HTTP-to-HTTPS redirect:

```nginx
server {
    listen 80;
    server_name grafana.gntech.me;
    return 301 https://$server_name$request_uri;
}
```

Install the `ca.crt` on each client machine (desktop, phone, browser) to eliminate SSL warnings — then every internal service gets valid TLS without Let's Encrypt's rate limits.

---

## Step 6 — Connecting to Existing Docker Networks

For Nginx to reach your upstream services, it must be on the same Docker network. The recommended approach is to create a shared network and attach all services to it:

```bash
docker network create proxy-net
```

Update the Nginx compose to attach:

```yaml
networks:
  proxy-net:
    external: true
```

Then add `networks: [proxy-net]` to every service you want Nginx to proxy. For example:

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    networks:
      - proxy-net
    # No ports needed — Nginx reaches it via the internal network
```

Traefik users will recognize this pattern. The difference is that Nginx requires manual `server` blocks instead of automatic label discovery — a trade-off that gives you explicit control over every upstream config line.

---

## Step 7 — Health Checks and Logging

The health check in the compose file runs `nginx -t` every 30 seconds. This validates the config syntax without making actual HTTP requests. For deeper monitoring, add an endpoint:

```nginx
server {
    listen 127.0.0.1:8080;
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
```

Then point your monitoring stack at `http://nginx:8080/health` (from within the Docker network).

**Log rotation** in Docker is handled by the `max-size` and `max-file` options in the compose file. For structured access logging, switch to JSON format:

```nginx
log_format json escape=json
    '{'
        '"time":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'
        '"body_bytes":$body_bytes_sent,'
        '"referer":"$http_referer",'
        '"user_agent":"$http_user_agent",'
        '"request_time":$request_time,'
        '"upstream_cache_status":"$upstream_cache_status"'
    '}';

access_log /var/log/nginx/access.log json;
```

This JSON format feeds directly into Loki, OpenSearch, or any log aggregator without additional parsing.

---

## When to Use Nginx vs. Traefik

| Use Case | Nginx | Traefik |
|----------|-------|---------|
| Static file serving | ✅ Best in class | ⚠️ Must proxy to separate container |
| Multi-service caching | ✅ Native proxy_cache | ⚠️ Requires plugin/middleware |
| Single-service sidecar | ✅ Minimal config | ⚠️ Overkill |
| Dynamic service discovery | ⚠️ Manual server blocks | ✅ Auto-detect via labels |
| Let's Encrypt automation | ⚠️ Requires certbot sidecar | ✅ Built-in ACME |
| WebSocket/gRPC | ✅ Native support | ✅ Native support |

For a homelab running 3-5 services behind a single Nginx, the manual config is a few dozen lines — perfectly maintainable and faster at serving cached content than any alternative.

---

## Putting It All Together

The complete deployment flow:

```bash
# 1. Create directories and files
mkdir -p /opt/nginx/{conf.d,html,certs,cache}

# 2. Copy nginx.conf and the conf.d/ files from this guide

# 3. Create a shared Docker network
docker network create proxy-net

# 4. Update each service's compose to join proxy-net

# 5. Attach Nginx to proxy-net
docker compose up -d

# 6. Test
curl -H "Host: grafana.gntech.me" http://localhost/
curl -s -o /dev/null -w "%{http_code}" http://localhost/
```

Nginx won't auto-discover new services like Traefik. When you add a service, create a new `conf.d/` file and reload:

```bash
docker exec nginx nginx -s reload
```

That reload takes milliseconds with zero dropped connections — no downtime, no container restart.

---

Nginx in Docker gives you a production-grade reverse proxy and caching layer with minimal complexity. It is the right choice when you need deterministic caching behavior, maximum static file throughput, or a lightweight sidecar that stays out of your way. The configs in this guide handle the everyday homelab patterns: proxying internal services, caching static assets, compressing responses, and terminating TLS — all running in a single Alpine container under 20 MB.
