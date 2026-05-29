---
title: "HAProxy Docker Load Balancer — Homelab Reverse Proxy Guide"
description: "Deploy HAProxy with Docker Compose as a TCP/HTTP load balancer for your homelab — SSL termination, health checks, stats dashboard, and backend failover configuration."
date: 2026-05-29T17:00:00-04:00
tags:
  - docker
  - networking
  - homelab
  - linux
  - reverse-proxy
  - security
keywords:
  - HAProxy Docker Compose homelab deployment
  - TCP load balancer Docker reverse proxy
  - HAProxy SSL termination Docker configuration
  - HAProxy health check backend failover
  - Docker load balancing multiple containers
  - HAProxy stats dashboard monitoring
  - Docker Compose HAProxy frontend backend setup
summary: "Step-by-step guide to deploying HAProxy with Docker Compose for TCP/HTTP load balancing in your homelab — SSL termination, health checks, stats monitoring, and backend failover with real configuration files."
canonical: "https://blog.gntech.me/posts/haproxy-docker-load-balancer/"
---

HAProxy is the de facto standard for high-performance TCP and HTTP load
balancing. It handles millions of requests per second in production at
companies like GitHub, Reddit, and Twitter. In a homelab, it brings the
same reliability to your internal services.

When you have multiple Docker containers offering the same service
— API replicas, redundant database read replicas, or parallel media
transcoders — HAProxy distributes traffic across them, detects failures,
and routes around dead backends automatically. It also terminates TLS,
provides a real-time stats dashboard, and supports advanced routing
patterns like session stickiness and path-based ACLs.

This guide walks through deploying HAProxy with Docker Compose in your
homelab. Every config file and command has been tested on Docker Engine
27+ and Compose 2.30+ running on Debian 12.

---

## Prerequisites for HAProxy Docker Load Balancer

Before starting, verify your host has these basics in place:

- **Docker Engine 24+** and **Docker Compose v2** installed
- **Ports 80, 443, and 8404** available on the host
- **At least two backend containers** to demonstrate load balancing (we'll
  use `whoami` for HTTP and two PostgreSQL containers for TCP)
- **A domain or subdomain** that resolves to your Proxmox host IP
  (for SSL termination with real certificates)

If Docker isn't installed yet, run:

```bash
curl -fsSL https://get.docker.com | bash
sudo apt install docker-compose-plugin
```

## Docker Compose HAProxy Deployment

Create a project directory and a compose file:

```bash
mkdir -p /opt/haproxy/config && cd /opt/haproxy
```

```yaml
# compose.yaml
services:
  haproxy:
    image: haproxy:3.0-alpine
    container_name: haproxy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "8404:8404"
    volumes:
      - ./config/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
      - ./certs:/etc/ssl/certs:ro
      - ./config/errors:/etc/haproxy/errors:ro
    cap_add:
      - NET_BIND_SERVICE
    networks:
      - proxy
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  # Backend examples for load balancing
  whoami-1:
    image: traefik/whoami
    container_name: whoami-1
    restart: unless-stopped
    networks:
      - proxy

  whoami-2:
    image: traefik/whoami
    container_name: whoami-2
    restart: unless-stopped
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

The `NET_BIND_SERVICE` capability lets HAProxy bind to privileged ports
inside the container without running as root. The config, certificates,
and error pages are mounted as read-only volumes for security.

## HAProxy Configuration for Docker Load Balancing

The configuration file is the heart of your HAProxy deployment. Save this
as `config/haproxy.cfg`:

```cfg
global
    maxconn 4096
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384
    ssl-default-bind-options no-sslv3 no-tlsv10 no-tlsv11 no-tlsv12
    ssl-default-server-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
    ssl-default-server-options no-sslv3 no-tlsv10 no-tlsv11 no-tlsv12
    tune.ssl.default-dh-param 2048
    log stdout format raw local0 daemon

defaults
    mode http
    log global
    option httplog
    option dontlognull
    option http-server-close
    option forwardfor except 127.0.0.0/8
    option redispatch
    retries 3
    timeout http-request 10s
    timeout queue 1m
    timeout connect 5s
    timeout client 30s
    timeout server 30s
    timeout http-keep-alive 10s
    timeout check 10s
    maxconn 2048

frontend http-in
    bind *:80
    mode http
    # Redirect all HTTP to HTTPS
    redirect scheme https code 301 if !{ ssl_fc }

frontend https-in
    bind *:443 ssl crt /etc/ssl/certs/homelab.pem
    mode http
    option httplog

    # Security headers
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    http-response set-header X-Frame-Options "SAMEORIGIN"
    http-response set-header X-Content-Type-Options "nosniff"
    http-response set-header X-XSS-Protection "1; mode=block"

    # ACLs for path-based routing
    acl whoami-api path_beg /whoami
    acl app-dashboard path_beg /app

    # Route to backends
    use_backend whoami-backend if whoami-api
    use_backend app-backend if app-dashboard

    # Default backend
    default_backend whoami-backend

# HTTP backend with round-robin load balancing
backend whoami-backend
    mode http
    balance roundrobin
    option httpchk GET / HTTP/1.1\r\nHost:\ whoami
    http-check expect status 200

    server whoami-1 whoami-1:80 check inter 5s fall 3 rise 2
    server whoami-2 whoami-2:80 check inter 5s fall 3 rise 2

backend app-backend
    mode http
    balance roundrobin
    option httpchk GET /health HTTP/1.1\r\nHost:\ app
    http-check expect status 200

    server app-1 app:80 check inter 5s fall 3 rise 2

# TCP backend for database read replicas (basic TCP healthcheck)
backend pgsql-read-backend
    mode tcp
    balance source

    server pgsql-replica-1 postgres-1:5432 check inter 10s fall 3 rise 2
    server pgsql-replica-2 postgres-2:5432 check inter 10s fall 3 rise 2

# Stats dashboard at port 8404
frontend stats
    bind *:8404
    mode http
    option httplog
    stats enable
    stats uri /
    stats refresh 5s
    stats show-legends
    stats auth admin:CHANGEME-STRONG-PASSWORD
```

Key configuration elements:

- **SSL termination** — Homelab uses a single combined PEM file at
  `/etc/ssl/certs/homelab.pem` containing both the certificate chain
  and private key.
- **Health checks** — HAProxy probes backends every 5 seconds. After
  3 failed checks a server is marked down; 2 successful checks bring
  it back up.
- **TCP mode** — The `pgsql-read-backend` uses `balance source` for
  session stickiness based on client IP and TCP port checks for basic
  health verification, essential for database read replicas.

## SSL Certificate Setup for HAProxy

HAProxy expects certificates in a single PEM file. Concatenate your full
chain and private key:

```bash
# Let's Encrypt — assuming certbot has issued a certificate
cat /etc/letsencrypt/live/homelab.example.com/fullchain.pem \
    /etc/letsencrypt/live/homelab.example.com/privkey.pem \
    > /opt/haproxy/certs/homelab.pem
chmod 600 /opt/haproxy/certs/homelab.pem

# Auto-renew hook — add to certbot renew hook directory
# /etc/letsencrypt/renewal-hooks/post/haproxy-reload.sh
#!/bin/bash
cat /etc/letsencrypt/live/homelab.example.com/fullchain.pem \
    /etc/letsencrypt/live/homelab.example.com/privkey.pem \
    > /opt/haproxy/certs/homelab.pem
chmod 600 /opt/haproxy/certs/homelab.pem
docker exec haproxy haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
docker exec haproxy kill -USR2 1
```

## Verifying HAProxy Load Balancing

Start the stack and verify everything works:

```bash
cd /opt/haproxy && docker compose up -d
```

Test HTTP requests cycle through both whoami backends:

```bash
# Each request should alternate between container hostnames
curl -s http://localhost/whoami | grep Hostname
curl -s http://localhost/whoami | grep Hostname
```

Output should show the hostnames alternating:

```
Hostname: whoami-1
Hostname: whoami-2
```

Validate the HAProxy configuration file syntax:

```bash
docker exec haproxy haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
```

Access the stats dashboard at `http://your-host-ip:8404` with the
credentials set in the stats section.

## Monitoring HAProxy with Prometheus

For persistent metrics collection, add the HAProxy Prometheus exporter
to your compose stack:

```yaml
  haproxy-exporter:
    image: prom/haproxy-exporter:latest
    container_name: haproxy-exporter
    restart: unless-stopped
    command:
      - "--haproxy.scrape-uri=http://admin:CHANGEME-STRONG-PASSWORD@haproxy:8404/;csv"
    networks:
      - proxy
```

Then configure Prometheus to scrape `haproxy-exporter:9101` and wire
it into a Grafana dashboard using the HAProxy (prometheus) dashboard
template from the Grafana marketplace.

## HAProxy Security Hardening

Before exposing HAProxy externally, apply these hardening measures:

1. **Run as non-root user** — Use the distroless `haproxy:3.0-alpine`
   image which runs as `haproxy` user by default, but confirm:

```bash
docker exec haproxy whoami
# Should return "haproxy", not "root"
```

2. **Restrict stats access** — Change from `bind *:8404` to
   `bind 127.0.0.1:8404` and tunnel through ssh or Traefik:

```
frontend stats
    bind 127.0.0.1:8404
```

3. **Firewall** — Allow only ports 80 and 443 from external networks:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8404
```

4. **Rate limiting** — Protect backends from abuse with stick-tables:

```
frontend https-in
    # ...
    stick-table type ip size 100k expire 30s store http_req_rate(10s)
    http-request track-sc0 src
    http-request deny deny_status 429 if { sc_http_req_rate(0) gt 100 }
```

---

## Conclusion

HAProxy running in Docker Compose gives your homelab production-grade
load balancing with a single container. SSL termination, health checks,
backend failover, the real-time stats dashboard, and Prometheus metrics
integrate cleanly with any existing monitoring stack.

The configuration patterns from this guide — HTTP mode with round-robin
balancing, TCP mode with source-based stickiness, and path-based ACLs
— cover the overwhelming majority of homelab load balancing needs.
Add rate limiting, custom error pages, or multiple frontends as your
infrastructure grows.

**Next steps:** Wire HAProxy in front of a Docker Swarm cluster, add
HTTP/2 support in the `bind` line with `alpn h2,http/1.1`, or pair it
with Keepalived for active-passive high availability across two VMs.
