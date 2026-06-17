---
title: "Step CA + ACME — Internal TLS Certificates for Your Homelab"
description: "Deploy step-ca in Docker as your own internal Certificate Authority with ACME support. Automatically issue and renew TLS certificates for internal services, integrate with Traefik reverse proxy, and distribute the root CA to clients."
date: 2026-05-22T17:00:00-04:00
tags:
  - docker
  - security
  - linux
  - homelab
  - networking
keywords:
  - step-ca Docker deployment homelab CA
  - ACME internal certificate authority step-ca
  - Traefik ACME step-ca integration internal services
  - internal CA TLS automatic renewal homelab
  - step-cli bootstrap root certificate distribution
  - DNS-01 ACME challenge step-ca homelab
  - internal PKI certificate management Docker
summary: "Run your own internal Certificate Authority with step-ca in Docker, issue TLS certificates via ACME, integrate with Traefik for automatic renewal, and distribute the root CA to all your devices — no more self-signed certificate warnings."
canonical: "https://gntech.dev/posts/step-ca-acme-internal-certificates/"
---

Public TLS certificates from Let's Encrypt work great for internet-facing
services, but they fall short for internal-only hosts. If you run a
homelab with services on `.internal`, `.local`, or RFC 1918 IP addresses,
you cannot get publicly trusted certificates for them. The typical
workaround — self-signed certificates — means browsers throw security
warnings, your monitoring tools fail TLS checks, and every new service
requires manual certificate generation and distribution.

You need an internal Certificate Authority (CA) that your devices trust,
combined with ACME automation so you never touch a certificate by hand.

**step-ca** from [Smallstep](https://smallstep.com/docs/step-ca/) is the
best tool for this job. It runs in a single Docker container, speaks
ACME (the same protocol Let's Encrypt uses), supports DNS-01 and HTTP-01
challenges, and integrates directly with Traefik, Caddy, and certbot.

This guide walks through deploying step-ca in Docker, bootstrapping
clients, setting up ACME, integrating with Traefik for automatic
certificate provisioning, and distributing the root CA to every device
in your homelab.

---

## Why an Internal CA Beats Self-Signed Certificates

Self-signed certificates work for testing, but they have real problems in
a homelab:

- **Browser warnings**: Every self-signed cert triggers a full-page "Your
  connection is not private" warning with no easy way to trust it
  permanently.
- **No automation**: You regenerate and redistribute certs manually every
  time they expire.
- **No revocation**: If a key is compromised, you cannot revoke the
  certificate.

An internal CA solves all three. You install the root CA once on each
device, and every certificate signed by that CA is automatically trusted.
ACME automates issuance and renewal. And step-ca supports certificate
revocation via CRL and OCSP if needed.

---

## Deploying step-ca with Docker Compose

Create a project directory and a `docker-compose.yml` for step-ca:

```yaml
# docker-compose.yml
services:
  step-ca:
    image: smallstep/step-ca:latest
    container_name: step-ca
    restart: unless-stopped
    hostname: ca.internal
    ports:
      - "10.0.20.30:9000:9000"
    volumes:
      - step-config:/home/step
    environment:
      - DOCKER_STEPCA_INIT_NAME=GnTech Internal CA
      - DOCKER_STEPCA_INIT_DNS_NAMES=ca.internal,10.0.20.30,localhost
      - DOCKER_STEPCA_INIT_PROVISIONER_NAME=admin
```

Bind the port to a specific IP (your Docker host's LAN address) instead of
`0.0.0.0` to avoid exposing the CA to VLANs that should not talk to it
directly.

Fire it up:

```bash
docker compose up -d
```

On first run, the container initializes the CA. It generates a root
certificate, an intermediate certificate, a password for the encrypted
CA keys, and the initial JWK provisioner. The CA password is saved
inside the Docker volume.

Retrieve the fingerprint needed for client bootstrapping:

```bash
docker run --rm -v step-config:/home/step smallstep/step-ca \
  step certificate fingerprint /home/step/certs/root_ca.crt
```

Save this fingerprint — you need it for every client that bootstraps
with the CA.

Retrieve the automatically generated CA password:

```bash
docker run --rm -v step-config:/home/step smallstep/step-ca \
  cat /home/step/secrets/password
```

You need this password when issuing certificates with the admin
provisioner.

---

## Installing the step CLI on Clients

Every machine that needs to interact with the CA — your Docker host,
workstations, or other servers — needs the `step` CLI.

### On Debian/Ubuntu

```bash
wget -O /tmp/step-cli.deb \
  https://dl.smallstep.com/gh-release/cli/gh-release-header/v0.28.10/step-cli_0.28.10_amd64.deb
sudo dpkg -i /tmp/step-cli.deb
```

### On macOS

```bash
brew install step
```

### On Alpine Linux

```bash
apk add step-cli
```

---

## Bootstrapping Clients

With the CLI installed and the CA running, bootstrap a client:

```bash
CA_URL=https://10.0.20.30:9000
CA_FINGERPRINT=86a278f34e58c7ab04313aff0e8e5114f1d1da955ecb20412b3d32cc2267ddcd

step ca bootstrap \
  --ca-url $CA_URL \
  --fingerprint $CA_FINGERPRINT
```

This downloads the root CA certificate, saves it to `~/.step/certs/root_ca.crt`,
and writes the defaults configuration. After bootstrapping, you can issue
certificates directly from the client:

```bash
step ca certificate \
  "nginx.internal" \
  nginx.internal.crt \
  nginx.internal.key
```

You are prompted for the admin provisioner password (from the secrets
file). The result is a TLS certificate signed by your internal CA, valid
for 24 hours by default.

---

## Enabling the ACME Provisioner

The JWK provisioner works fine for manual operations, but ACME is where
step-ca really shines. Add an ACME provisioner to the CA configuration.

Read the current CA config from the volume:

```bash
docker run --rm -v step-config:/home/step smallstep/step-ca \
  cat /home/step/config/ca.json
```

Look for the `"provisioners"` array. Add an ACME provisioner entry: create
a file called `ca.json` on the volume path by copying the existing config
and adding:

```json
{
  "type": "ACME",
  "name": "acme",
  "forceCN": true,
  "options": {
    "x509": {
      "template": "/home/step/templates/acme.tpl"
    },
    "claims": {
      "enableX509CA": false,
      "minTLSDur": "1h",
      "maxTLSDur": "2160h"
    }
  }
}
```

The easier approach — edit the config file stored in the Docker volume.
On the Docker host:

```bash
# Copy the config out
docker cp step-ca:/home/step/config/ca.json /tmp/ca.json

# Edit — add the ACME provisioner (use jq for precision)
jq '.provisioners += [{
  "type": "ACME",
  "name": "acme",
  "forceCN": true,
  "options": {
    "claims": {
      "enableX509CA": false,
      "minTLSDur": "1h",
      "maxTLSDur": "2160h"
    }
  }
}]' /tmp/ca.json > /tmp/ca-new.json

# Copy it back
docker cp /tmp/ca-new.json step-ca:/home/step/config/ca.json

# Restart step-ca to pick up the change
docker compose restart
```

Now any ACME client — Traefik, Caddy, or certbot — can request certificates
from your internal CA.

---

## Integrating with Traefik

If you run [Traefik](https://traefik.io/traefik/) as your reverse proxy
(covered in our [Traefik setup guide](/posts/traefik-reverse-proxy-docker/)),
adding the internal CA as an ACME certificate provider is
straightforward.

First, make Traefik trust your internal CA. Mount the root certificate
and update the Traefik static configuration:

```yaml
# traefik.yml
certificatesResolvers:
  letsencrypt:
    acme:
      # ...existing LE DNS-01 config for public services...
  
  internal:
    acme:
      caServer: https://10.0.20.30:9000/acme/acme/directory
      email: admin@gntech.dev
      storage: /etc/traefik/acme-internal.json
      httpChallenge:
        entryPoint: web
      # keyType: EC256  # Optional — use ECDSA keys
```

And mount the root CA into the Traefik container:

```yaml
services:
  traefik:
    image: traefik:v3.3
    volumes:
      - /etc/ssl/certs/ca-certificates.crt:/etc/ssl/certs/ca-certificates.crt:ro
      - ~/.step/certs/root_ca.crt:/usr/local/share/ca-certificates/step-ca.crt:ro
```

Run `update-ca-certificates` inside the container or rebuild the image with
the CA bundled. For the easiest path, bind-mount the CA file and configure
Traefik to use the system trust store by adding to the entrypoint.

Now annotate services that need internal certificates with the `internal`
resolver in their Docker labels:

```yaml
services:
  grafana:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`grafana.internal`)"
      - "traefik.http.routers.grafana.entrypoints=websecure"
      - "traefik.http.routers.grafana.tls.certresolver=internal"
```

Traefik automatically requests a certificate from step-ca via ACME for
`grafana.internal`, renews it before expiry, and terminates TLS.

---

## DNS-01 Challenges for Wildcard Certificates

For wildcard certificates like `*.internal`, use DNS-01 instead of HTTP-01.
step-ca supports DNS-01 out of the box, and you can pair it with any DNS
provider that has an API.

If you run your own DNS server (like Pi-hole or Unbound), the simplest
approach is a manual DNS challenge script. Create a script that the
ACME client calls to set and clear TXT records:

```bash
#!/bin/bash
# /usr/local/bin/dns-step-hook.sh
# Called by ACME client with:
# $1 = action (present/cleanup)
# $2 = FQDN
# $3 = token value

set -euo pipefail

ACTION=$1
FQDN=$2
TOKEN=$3

# If your DNS server has an API (e.g., PowerDNS, Bind with nsupdate)
# Update the TXT record for _acme-challenge.$FQDN

case $ACTION in
  present)
    # nsupdate -k /etc/bind/rndc.key <<EOF
    # server ns.internal 53
    # zone internal
    # update add _acme-challenge.$FQDN 60 TXT "$TOKEN"
    # send
    # EOF
    echo "DNS challenge: $FQDN -> $TOKEN"
    ;;
  cleanup)
    # Remove the TXT record
    echo "DNS cleanup: $FQDN"
    ;;
esac
```

Or use certbot with step-ca's ACME endpoint and the DNS plugin for your
provider:

```bash
certbot certonly \
  --manual \
  --preferred-challenges dns \
  --manual-auth-hook /usr/local/bin/dns-step-hook.sh \
  --manual-cleanup-hook /usr/local/bin/dns-step-hook.sh \
  --server https://10.0.20.30:9000/acme/acme/directory \
  -d "*.internal" \
  --non-interactive
```

---

## Managing Certificate Lifetime

step-ca issues short-lived certificates by default — 24 hours — which means
renewal is frequent but revocation risk is minimal. For homelab use,
24 hours is short enough to be annoying if something breaks. Extend the
default via the CA configuration:

```json
{
  "claims": {
    "minTLSDur": "24h",
    "maxTLSDur": "2160h",
    "defaultTLSDur": "720h"
  }
}
```

This sets the default to 30 days (720h), with a maximum of 90 days (2160h).
ACME clients can request a specific duration within this range.

---

## Distributing the Root CA to Clients

Every device that needs to trust your internal certificates must have the
root CA installed. Here is how to distribute it to common platforms.

### Linux (Debian/Ubuntu)

```bash
# On the Docker host where step-ca runs
sudo cp ~/.step/certs/root_ca.crt /usr/local/share/ca-certificates/step-ca.crt
sudo update-ca-certificates
```

For other machines, copy the root CA file and run the same commands.

### Windows (via Group Policy or script)

```powershell
# Run as Administrator
Import-Certificate -FilePath "\\server\share\step-ca.crt" -CertStoreLocation "Cert:\LocalMachine\Root"
```

### macOS

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain ~/.step/certs/root_ca.crt
```

### Android

Copy the `.crt` file to the device, then go to **Settings → Security →
Encryption & credentials → Install a certificate → CA certificate** and
select the file.

### iOS/iPadOS

Send the `.crt` file via email or AirDrop, tap to install, then go to
**Settings → General → About → Certificate Trust Settings** and enable
the root CA.

### Firefox (separate trust store)

Firefox uses its own certificate store, not the system one:

```bash
# Import root CA into Firefox profile
certutil -A -n "GnTech Internal CA" \
  -t "TCu,Cu,Tu" \
  -i ~/.step/certs/root_ca.crt \
  -d sql:/home/user/.mozilla/firefox/*.default-release
```

---

## Health Checks and Monitoring

Verify the CA is running and healthy:

```bash
curl -k https://10.0.20.30:9000/health
# {"status":"ok"}
```

Add step-ca to your [monitoring stack](/posts/homelab-monitoring-stack/):

```yaml
# prometheus scrape config via blackbox exporter
- job_name: step-ca-health
  metrics_path: /probe
  params:
    module: [http_2xx]
  static_configs:
    - targets:
        - https://10.0.20.30:9000/health
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: blackbox:9115
```

Monitor certificate expiry for your critical services using
[Uptime Kuma](https://github.com/louislam/uptime-kuma) or
[Prometheus Blackbox Exporter](https://github.com/prometheus/blackbox_exporter)
with the `ssl_certificate_expiry` probe. Set alerts at 7, 3, and 1 day
before expiry.

---

## Security Considerations

Running an internal CA is powerful, but treat it with care:

- **Keep the CA password safe**: The encrypted root key is in the Docker
  volume's `secrets/` directory. Backup this directory, but never share
  the password.
- **Restrict network access**: Bind step-ca to a management IP or use
  firewall rules to limit who can reach port 9000.
- **Use a dedicated volume**: Step-ca stores private keys on the Docker
  volume. Keep regular backups.
- **Rotate provisioner keys**: The admin JWK provisioner is powerful.
  Create separate ACME provisioners with shorter lifespans for different
  use cases.
- **Audit certificate issuance**: step-ca logs every certificate request.
  Monitor logs for unexpected issuance.

Backup the step-ca volume regularly:

```bash
docker run --rm -v step-config:/home/step -v /backup:/backup \
  alpine tar czf /backup/step-ca-$(date +%F).tar.gz -C /home/step .
```

To restore, extract the archive into a new volume of the same name.

---

## Summary

An internal CA with ACME support is the missing piece in most homelab
TLS setups. With step-ca in Docker you get:

- **Automatic certificates** for any internal hostname or IP
- **No browser warnings** once the root CA is trusted
- **Traefik integration** for seamless reverse proxy TLS
- **Short-lived certificates** that minimize revocation risk
- **Open source** with no licensing costs

One deploy and root CA distribution session eliminates self-signed
certificate pain forever. Every new service you add — whether it is
Grafana, Home Assistant, or a custom API — gets valid TLS automatically.
