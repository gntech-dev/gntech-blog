---
title: "Cloudflare Tunnel with Docker — Expose Homelab Services Securely"
description: "Deploy Cloudflare Tunnel (cloudflared) in Docker to expose homelab services without opening ports — setup, ingress rules, multi-service routing, and security hardening for self-hosted apps."
date: 2026-05-14T17:00:00-04:00
tags:
  - cloudflare
  - docker
  - networking
  - security
  - reverse-proxy
keywords:
  - Cloudflare Tunnel Docker compose
  - cloudflared homelab setup
  - expose homelab without port forwarding
  - Cloudflare Zero Trust homelab
  - cloudflared ingress rules multi-service
  - secure selfhosted apps Cloudflare
  - Cloudflare Tunnel security best practices
summary: "Run Cloudflare Tunnel in Docker to expose homelab services through Cloudflare's edge. No open firewall ports, automatic HTTPS, and per-service ingress rules via a single cloudflared container."
canonical: "https://gntech.dev/posts/cloudflare-tunnel-docker/"
---

Opening a firewall port for every homelab service is a liability. One
vulnerability in a web dashboard and your LAN is exposed. Cloudflare
Tunnel solves this by creating an encrypted outbound connection from
your server to Cloudflare's edge — no inbound ports required.

All traffic to your domain hits Cloudflare first, gets inspected, and
is forwarded through the tunnel to your local service. HTTPS is
automatic. DDoS protection is included. And the best part: there's
nothing to lock down on your router.

This guide covers a full Docker Compose deployment of cloudflared
with multi-service ingress routing, authentication rules, and
production-ready security.

---

## Why Cloudflare Tunnel Over Port Forwarding

Compare the two approaches:

| Approach | Attack surface | HTTPS | Maintenance |
|---|---|---|---|
| Port forwarding | Your public IP, each open port | Manual certs | Firewall rules, cert renewal |
| Cloudflare Tunnel | Zero open ports | Automatic | One tunnel binary |

With port forwarding, every open port is a potential entry point. A
forgotten admin panel on port 8443 becomes a foothold. With Cloudflare
Tunnel, your server initiates an outbound TCP connection to Cloudflare
and keeps it alive. No iptables rules, no NAT hairpinning, no DMZ
configuration.

The tunnel also handles DNS automatically — each ingress entry
creates a CNAME record on your Cloudflare zone.

---

## Prerequisites

- A domain using Cloudflare DNS (nameservers pointed to Cloudflare)
- Docker and Docker Compose installed on your homelab server
- SSH or console access to the host running Docker
- A Cloudflare account with Zero Trust enabled (free tier works)

---

## Step 1: Authenticate Cloudflared

Cloudflare Tunnel requires authentication to link the tunnel to your
account. The quickest way is running the login container interactively:

```bash
docker run -it --rm \
  -v /opt/cloudflared:/home/nonroot/.cloudflared \
  cloudflare/cloudflared:latest tunnel login
```

This opens a URL in your browser. Log in to Cloudflare and select the
domain you want to use. The certificate saves to
`/opt/cloudflared/cert.pem`.

If your server has no browser (headless Proxmox LXC), copy the URL
from the output, open it on your desktop machine, authenticate, and
the cert file will be written back.

## Step 2: Create and Route the Tunnel

With the cert in place, create a named tunnel:

```bash
docker run -it --rm \
  -v /opt/cloudflared:/home/nonroot/.cloudflared \
  cloudflare/cloudflared:latest tunnel create homelab
```

This generates a tunnel UUID and saves credentials in
`/opt/cloudflared/<uuid>.json`. You now have a tunnel ID and a
credentials file — both needed for the Docker Compose setup.

Test the tunnel with a quick run against a single service:

```bash
docker run -it --rm \
  -v /opt/cloudflared:/home/nonroot/.cloudflared \
  cloudflare/cloudflared:latest tunnel --url http://localhost:8080
```

This starts an ad-hoc tunnel pointing at whatever is running on port
8080. Press Ctrl+C when confirmed working.

## Step 3: Docker Compose Configuration

Create a directory structure for your tunnel config:

```yaml
# /opt/cloudflared/docker-compose.yml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run
    volumes:
      - ./config:/etc/cloudflared:ro
    network_mode: host
```

The `network_mode: host` is intentional — cloudflared needs to reach
services listening on `localhost` and Docker bridge IPs. With host
networking, `localhost` inside the container is the host's localhost,
so you can tunnel any service regardless of its network setup.

### Config File — Ingress Rules

Create `config/config.yml` to define which domains map to which local
services:

```yaml
# /opt/cloudflared/config/config.yml
tunnel: homelab
credentials-file: /etc/cloudflared/<your-uuid>.json

ingress:
  - hostname: dashboard.yourdomain.com
    service: http://localhost:9090
  - hostname: grafana.yourdomain.com
    service: http://localhost:3000
  - hostname: frigate.yourdomain.com
    service: http://localhost:5000
  - hostname: status.yourdomain.com
    service: http://localhost:8081
  - hostname: uptime.yourdomain.com
    service: http://192.168.1.100:3001
  - hostname: traefik.yourdomain.com
    service: http://localhost:8080
  # Catch-all — return 404 for unmatched hostnames
  - service: http_status:404
```

Place the tunnel credentials JSON in the same `config/` directory:

```bash
cp /opt/cloudflared/<uuid>.json /opt/cloudflared/config/
```

Your config directory should look like:

```
/opt/cloudflared/
├── docker-compose.yml
└── config/
    ├── config.yml
    └── <uuid>.json
```

### Route DNS Records

Tell Cloudflare which domains use this tunnel:

```bash
docker run -it --rm \
  -v /opt/cloudflared/config:/etc/cloudflared \
  cloudflare/cloudflared:latest tunnel route dns homelab dashboard.yourdomain.com
docker run -it --rm \
  -v /opt/cloudflared/config:/etc/cloudflared \
  cloudflare/cloudflared:latest tunnel route dns homelab grafana.yourdomain.com
```

Repeat for each hostname in your ingress config. Cloudflare
automatically creates CNAME records pointing to the tunnel ID.

### Start the Tunnel

```bash
cd /opt/cloudflared
docker compose up -d
```

Check the logs:

```bash
docker compose logs -f
```

You should see lines like:

```
INF Connection 5c3c8a7d-... registered
INF Each of the 2 active connections is...
```

If you see connection errors, check your config file for typos in
hostnames and verify the credentials file path.

---

## Step 4: Securing Your Tunnel

A tunnel is only as secure as the applications it exposes. Here are
the essential hardening steps.

### Application-Level Authentication with Zero Trust

Cloudflare Zero Trust (free tier) adds an authentication gate before
traffic reaches your service. Go to **Cloudflare Dashboard → Zero
Trust → Access → Applications**, create a self-hosted application,
point it at your domain, and configure a policy (e.g., "Email OTP"
or "Google Workspace login").

Traffic flow becomes:

```
User → Cloudflare Edge → [Auth Check] → Tunnel → Service
```

If the user hasn't authenticated, Cloudflare shows a login page
before the request ever reaches your server. This is better than
HTTP basic auth because you get MFA, device posture checks, and
per-app policies — all without modifying your apps.

### Service-Level IP Whitelisting

Even though no ports are open, lock down the services themselves so
they reject traffic that didn't come via the tunnel. Add this to each
service's Docker Compose or application config.

For Traefik or Caddy, restrict access to Docker bridge networks or
specific paths. For Proxmox, enable the firewall and allow only the
Docker host IP.

### Use a Separate Tunnel for Sensitive Services

Don't put your SSH access behind the same ingress setup. Create a
second tunnel or use Cloudflare's browser-based SSH via Zero Trust.
Keep management interfaces (Proxmox, SSH, Docker API) off the public
ingress entirely unless protected with Zero Trust policies.

---

## Step 5: Running cloudflared as a Non-Root Container

Cloudflare publishes cloudflared with a non-root user. The
`docker-compose.yml` above uses it already. To verify:

```bash
docker exec cloudflared whoami
# nonroot
```

If you're binding volumes, ensure file permissions allow the nonroot
user (UID 1000 inside the container) to read the config:

```bash
chown -R 1000:1000 /opt/cloudflared/config/
chmod 600 /opt/cloudflared/config/*.json
chmod 644 /opt/cloudflared/config/config.yml
```

---

## Troubleshooting Common Issues

### Tunnel starts but returns 502

Your ingress `service:` URL is wrong or the destination isn't
listening. Test with `curl` from the host:

```bash
curl -I http://localhost:3000
```

If that works, check `config.yml` for exact hostname casing and port
mismatches.

### DNS records not resolving

DNS routing creates CNAME records, and CNAMEs can coexist on the same
zone as other record types. If a record isn't resolving, re-run:

```bash
cloudflared tunnel route dns homelab yourservice.yourdomain.com
```

Or create the CNAME manually in the Cloudflare dashboard targeting
`<tunnel-id>.cfargotunnel.com`.

### Tunnel disconnects frequently

Cloudflared keeps persistent TCP connections. Frequent drops usually
indicate ISP-level issues (CGNAT, aggressive firewall, or packet
loss). Add the following to `config.yml` to reconnect aggressively:

```yaml
retries: 5
grace-period: 5s
```

Or pass `--protocol quic` to use QUIC instead of TCP for the control
plane, which handles NAT rebinding better.

### Updating the tunnel

When you add a new ingress rule, just edit `config.yml` and restart
cloudflared:

```bash
docker compose restart
```

That's it. No DNS changes, no firewall updates, no certificate renewal.

---

## Production Checklist

- [ ] Set up Cloudflare Zero Trust Access policies for critical apps
- [ ] Run `chmod 600` on credentials files
- [ ] Pin cloudflared to a specific version tag, not `latest`
- [ ] Monitor tunnel uptime with a health check URL
- [ ] Keep tunnel logs shipped to your Grafana/Loki stack
- [ ] Test failover — stop cloudflared and confirm services are
      unreachable from outside (no backdoor ports)
- [ ] Use separate tunnels for internal vs external services
- [ ] Enable audit logging in Cloudflare Zero Trust

---

## Summary

Cloudflare Tunnel eliminates port forwarding entirely while adding
automatic HTTPS, DDoS protection, and a global CDN in front of your
homelab services. A single cloudflared container handles ingress for
dozens of services with a straightforward YAML config file.

Combined with Zero Trust access policies, you get enterprise-grade
remote access to your self-hosted apps without the attack surface of
open ports. For the cost of a domain name, it's the safest way to
expose services from behind NAT, CGNAT, or a dynamic IP.
