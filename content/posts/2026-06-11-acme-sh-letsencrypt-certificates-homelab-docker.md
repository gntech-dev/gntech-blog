---
title: "acme.sh Let's Encrypt Certificates for Homelab Docker Services"
description: "Automate Let's Encrypt SSL certificates in your homelab with acme.sh and Docker. Covers DNS-01 challenges, wildcard certs, auto-renewal, and reverse proxy integration."
date: 2026-06-11T14:00:00-04:00
tags:
  - docker
  - homelab
  - security
  - devops
  - reverse-proxy
keywords:
  - acme.sh Docker Let's Encrypt certificate automation homelab
  - DNS-01 challenge acme.sh wildcard certificates docker
  - acme.sh standalone mode Docker reverse proxy SSL TLS
  - Let's Encrypt auto-renewal acme.sh cron Docker homelab
  - acme.sh install configuration Docker container ACME client
  - automated SSL certificate management self-hosted services
  - acme.sh Traefik nginx deploy hook renewal scripts
summary: "Automate Let's Encrypt SSL/TLS certificates in your homelab using acme.sh and Docker. Includes DNS-01 wildcard certs, auto-renewal, and integration with Traefik, Nginx Proxy Manager, and Caddy."
canonical: "https://blog.gntech.me/posts/acme-sh-letsencrypt-certificates-homelab-docker/"
---

You run ten self-hosted services and every single one needs a valid TLS certificate. Certbot needs port 80 open and stops working when Traefik is already listening there. Wildcard certificates require DNS plugins most clients do not bundle. Renewal scripts break when you migrate containers between hosts.

acme.sh solves all of this with a single shell script that supports over three hundred DNS providers, runs in Docker without runtime dependencies, and handles auto-renewal through a built-in cron mode.

This guide walks through a complete acme.sh deployment on Docker — issuing wildcard Let's Encrypt certificates via DNS-01 challenge, automating renewal, and deploying certs to Traefik, Nginx, and Caddy on the same Docker network.

## Why acme.sh Over Certbot for Homelab Certificates

Certbot is the default ACME client for most administrators, but it has structural disadvantages in a Docker-forward homelab:

- **Dependency footprint:** Certbot is a Python application with plugins that pull in dozens of packages. acme.sh is a single POSIX shell script with zero runtime dependencies beyond curl and openssl.
- **DNS provider support:** Certbot's DNS-01 plugins are per-provider packages you install separately. acme.sh bundles support for over three hundred DNS providers in the script itself — no extra install step.
- **Multiple CA endpoints:** acme.sh supports Let's Encrypt, ZeroSSL, Buypass, Google Trust Services, and custom ACME endpoints. Switching CAs is a one-flag change.
- **Key types:** ECDSA (prime256v1, secp384r1) and RSA (2048, 4096) are first-class options, controlled by a single `--keylength` flag.
- **Deploy hooks:** acme.sh ships with built-in deploy hooks for nginx, apache, haproxy, cpanel, and custom commands. You write one reload command and every renewal triggers it.

If you already run Certbot and it works, keep it. If you are starting fresh or want wildcard certs without exposing port 80, acme.sh is the cleaner path.

## Installing acme.sh in Docker

The official image `neilpang/acme.sh` bundles the script with cron support. Create a compose file that mounts persistent volumes for the acme.sh data directory and the certificate output directory:

```yaml
# acme-compose.yml
services:
  acme.sh:
    image: neilpang/acme.sh:latest
    container_name: acme.sh
    restart: unless-stopped
    environment:
      - CF_Token=${CF_Token}
      - CF_Zone_ID=${CF_Zone_ID}
      - LE_WORKING_DIR=/acme.sh
      - LE_CONFIG_HOME=/acme.sh
    volumes:
      - ./acme_data:/acme.sh
      - ./certs:/certs
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - cert-net
    command: daemon

networks:
  cert-net:
    name: cert-net
    driver: bridge
```

Two volumes handle persistence:

- **`./acme_data`** — stores account keys, certificate files, and configuration. This is the only volume you need for restart survival.
- **`./certs`** — output directory where deploy hooks write certificates for consumption by reverse proxies. Optional if you use deploy hooks that write directly to mounted volumes.

The `daemon` command keeps the container running and enables the built-in cron for auto-renewal. For one-shot issuance you can also use `run --rm` mode:

```bash
docker compose -f acme-compose.yml run --rm acme.sh --register-account -m admin@example.com
```

This registers your account email with the default Let's Encrypt production endpoint. The `--server` flag switches to ZeroSSL or staging:

```bash
docker compose -f acme-compose.yml run --rm acme.sh \
  --register-account -m admin@example.com \
  --server zerossl
```

## DNS-01 Challenge for Wildcard Certificates

The HTTP-01 challenge requires port 80 on the host and cannot issue wildcard certificates. The DNS-01 challenge requires no open ports and can issue `*.example.com` certs that cover every subdomain.

### Cloudflare DNS API Integration

Cloudflare is the most common provider in homelabs. Generate an API token from the Cloudflare dashboard with `Zone:DNS:Edit` permission, then export it to the environment:

```bash
export CF_Token="your_cloudflare_api_token_here"
export CF_Zone_ID="your_zone_id_here"
```

Issue a wildcard certificate covering both `*.example.com` and the bare domain:

```bash
docker compose -f acme-compose.yml run --rm acme.sh \
  --issue \
  --dns dns_cf \
  -d *.example.com \
  -d example.com \
  --keylength ec-256
```

The `ec-256` flag requests an ECDSA P-256 key. ECDSA certificates are smaller, faster to negotiate, and supported by every modern client. For RSA compatibility with legacy clients, omit `--keylength` or use `--keylength 2048`.

acme.sh creates a DNS TXT record at `_acme-challenge.example.com`, polls for propagation, and removes it after validation. The whole process takes about thirty seconds.

### Other DNS Providers

The same pattern works for dozens of providers. Set the required environment variables and change the `--dns` flag:

| Provider       | Environment Variables                        | --dns flag   |
|----------------|---------------------------------------------|--------------|
| Cloudflare     | CF_Token, CF_Zone_ID                        | dns_cf        |
| DigitalOcean   | DO_API_KEY                                  | dns_dgon      |
| AWS Route53    | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY    | dns_aws       |
| Hetzner        | HETZNER_API_TOKEN                           | dns_hetzner   |
| Gandi          | GANDI_LIVEDNS_KEY                           | dns_gandi_livedns |
| DuckDNS        | DuckDNS_Token                               | dns_duckdns   |

Run `acme.sh --list-dns` inside the container to see every supported provider.

## Auto-Renewal Setup

acme.sh includes a cron mode that checks all certificates daily and renews those expiring within sixty days. The `daemon` start command in the compose file enables this automatically.

To trigger renewal manually or test the cron logic:

```bash
docker compose -f acme-compose.yml exec acme.sh --cron --force
```

Enable the auto-upgrade feature so acme.sh updates itself:

```bash
docker compose -f acme-compose.yml run --rm acme.sh --upgrade --auto-upgrade
```

This writes the upgrade configuration to `~/.acme.sh/account.conf` inside the container. Combined with the daily cron, your certificate pipeline becomes fully self-maintaining.

### Systemd Timer Alternative

If you prefer host-level scheduling over Docker cron, disable the daemon mode and run acme.sh via a systemd timer:

```ini
# /etc/systemd/system/acme-renewal.service
[Unit]
Description=acme.sh certificate renewal
After=docker.service

[Service]
Type=oneshot
ExecStart=docker compose -f /opt/acme/acme-compose.yml run --rm acme.sh --cron
```

```ini
# /etc/systemd/system/acme-renewal.timer
[Unit]
Description=Daily acme.sh renewal
Requires=acme-renewal.service

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now acme-renewal.timer
```

## Deploy Hooks — Updating Reverse Proxies

A certificate renewal is useless if running services do not reload with the new key pair. acme.sh deploy hooks automate this.

### Traefik Integration

Traefik reads certificates from file. Create a deploy hook that writes the renewal output to the Traefik dynamic configuration volume:

```bash
docker compose -f acme-compose.yml run --rm acme.sh \
  --install-cert -d *.example.com \
  --ecc \
  --cert-file /certs/traefik/cert.pem \
  --key-file /certs/traefik/key.pem \
  --fullchain-file /certs/traefik/fullchain.pem \
  --reloadcmd "docker exec traefik kill -HUP 1"
```

Configure Traefik to serve the file-based certificates:

```yaml
# traefik-dynamic.yml — mounted into /etc/traefik/dynamic
tls:
  certificates:
    - certFile: /certs/traefik/fullchain.pem
      keyFile: /certs/traefik/key.pem
```

### Nginx Integration

For Nginx, the deploy hook writes certificates and reloads the service:

```bash
docker compose -f acme-compose.yml run --rm acme.sh \
  --install-cert -d *.example.com \
  --ecc \
  --fullchain-file /etc/nginx/certs/fullchain.pem \
  --key-file /etc/nginx/certs/key.pem \
  --reloadcmd "docker exec nginx nginx -s reload"
```

The Nginx config references the shared cert volume:

```nginx
server {
    listen 443 ssl;
    server_name app.example.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;

    location / {
        proxy_pass http://app:3000;
    }
}
```

### Caddy Integration

Caddy can use certificates from a mounted directory with the `file_server` or `tls` directive. The deploy hook writes to the shared path:

```bash
docker compose -f acme-compose.yml run --rm acme.sh \
  --install-cert -d *.example.com \
  --ecc \
  --fullchain-file /etc/caddy/certs/fullchain.pem \
  --key-file /etc/caddy/certs/key.pem \
  --reloadcmd "docker exec caddy caddy reload --config /etc/caddy/Caddyfile"
```

And the Caddyfile references the cert files:

```
app.example.com {
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/key.pem
    reverse_proxy app:3000
}
```

## Complete Docker Compose Stack with Traefik

Here is a full working stack that issues certificates and serves applications behind Traefik:

```yaml
# docker-compose.yml
services:
  acme.sh:
    image: neilpang/acme.sh:latest
    container_name: acme.sh
    restart: unless-stopped
    environment:
      - CF_Token=${CF_Token}
      - CF_Zone_ID=${CF_Zone_ID}
      - LE_WORKING_DIR=/acme.sh
    volumes:
      - ./acme_data:/acme.sh
      - ./certs:/certs
    networks:
      - cert-net
    command: daemon

  traefik:
    image: traefik:v3.3
    container_name: traefik
    restart: unless-stopped
    ports:
      - 80:80
      - 443:443
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
      - ./traefik-dynamic.yml:/etc/traefik/dynamic/traefik-dynamic.yml:ro
      - ./certs:/certs:ro
    networks:
      - cert-net
      - proxy

  whoami:
    image: traefik/whoami
    container_name: whoami
    labels:
      - traefik.enabled=true
      - traefik.http.routers.whoami.rule=Host(`whoami.example.com`)
      - traefik.http.routers.whoami.tls=true
      - traefik.http.services.whoami.loadbalancer.server.port=80
    networks:
      - proxy

networks:
  cert-net:
    name: cert-net
    driver: bridge
  proxy:
    name: proxy
    driver: bridge
```

The certificate issuance flow: acme.sh runs the DNS-01 challenge, stores the certificate in `./certs/traefik/`, and Traefik references those files via the shared volume. On renewal, the `--reloadcmd` signals Traefik to reload configuration without dropping connections.

## Verification and Troubleshooting

### Check Certificate Details

Use openssl to verify certificate attributes:

```bash
docker compose -f acme-compose.yml run --rm acme.sh --list

openssl x509 -in ./certs/traefik/fullchain.pem -noout -text | grep -E "Subject:|Not Before|Not After"
```

### Review acme.sh Logs

acme.sh writes detailed logs to `$LE_WORKING_DIR/acme.sh.log`:

```bash
tail -50 ./acme_data/acme.sh.log
```

### Common Issues

- **DNS propagation delay:** Some providers take longer than others. acme.sh waits 120 seconds by default. Increase with `--dnssleep 300` for slow providers.
- **Rate limits:** Let's Encrypt allows 50 certificates per week per registered domain. Use the staging endpoint during testing to avoid exhausting production limits:

  ```bash
  acme.sh --issue --dns dns_cf -d *.example.com --server letsencrypt-staging
  ```

- **Permission errors on cert files:** Ensure the reverse proxy container can read the certificate files. Use `chmod 644` on the cert volume or run the proxy container with the same UID that wrote the certificates.

- **Cron not running inside container:** Verify the container is in daemon mode and cron is enabled by checking the container logs:

  ```bash
  docker logs acme.sh | grep cron
  ```

  If cron is not active, exec into the container and start the daemon manually:

  ```bash
  docker exec acme.sh /bin/sh -c "crond -b && acme.sh --cron"
  ```

## Conclusion

acme.sh eliminates every friction point in homelab certificate management. The single-script architecture works anywhere a shell runs. The DNS-01 provider matrix covers practically every DNS service in use today. Deploy hooks bridge the gap between certificate issuance and service reload so that renewal is completely hands-off.

For a homelab running ten, twenty, or fifty services behind a reverse proxy, setting up acme.sh once with wildcard certificates and auto-renewal saves more time than any other TLS management approach. The compose stack in this guide can be running in ten minutes — and then never needs attention again unless you add a new domain.

The full configuration files are available on the blog repository. Drop the compose file on any Docker host, set your Cloudflare API token, and your services will never serve an expired certificate again.
