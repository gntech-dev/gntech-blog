---
title: "GNTECH Infrastructure Part 09: Docker Compose and Traefik for Private Applications"
description: "Build a private HTTPS ingress on a Proxmox guest using Traefik's file provider, then verify that application data survives a container replacement."
date: 2026-11-04T06:00:00-04:00
draft: false
ShowToc: true
tags: [gntech-infrastructure, docker, docker-compose, traefik, homelab]
keywords: [Traefik file provider, private HTTPS, Docker Compose, named volumes]
summary: "Route one application through a socket-free Traefik gateway, verify TLS with a local trust anchor, and check that a container replacement keeps application data."
cover:
  image: "/images/posts/gntech-infrastructure-part-09/featured.webp"
  alt: "Compact black server rack with blue and amber status lights and neatly routed cables."
  caption: "AI-generated editorial artwork."
  relative: false
---

**Series** · [GNTECH Infrastructure Deployment Series](/gntech-infrastructure-series/) · **Part 09 of 12** · [Previous: Part 08 — Cloudflare Zero Trust](/posts/2026-11-03-gntech-infrastructure-part-08-cloudflare-zero-trust/) · [Next: Part 10 — Backup and Disaster Recovery](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/)

Part 08 set the rules for reaching an administrative application. This part builds the origin on a dedicated Linux guest. Traefik terminates HTTPS, reaches the app by its Docker service name, and reads its routes from a mounted directory. That keeps the Docker API out of the proxy container and gives you a route file to review before deploying a change.

This is a reference lab. It assumes Docker Engine with the Compose v2 plugin, Traefik v3.6, NGINX Alpine, OpenSSL, curl, and a free TCP port 8443 on the guest. Run the commands in a fresh directory on that guest with an account authorized to use Docker. The HTTPS endpoint binds to loopback for the exercise. The bridge carries plaintext HTTP between the two containers on the same host.

![A local curl client connects over HTTPS to Traefik on guest loopback. Traefik forwards HTTP on a Docker bridge to NGINX, which reads the named content volume.](/images/posts/gntech-infrastructure-part-09/request-path.svg)

## 1. Generate a lab certificate

The certificate has a DNS subject alternative name for `app.example.com`. The curl commands below trust that exact certificate and resolve the hostname to loopback. Keep the private key on the guest. Use a certificate issued by your organization's trusted CA or another appropriate issuer for a shared deployment.

```bash
mkdir -p ~/gntech-ingress-lab
cd ~/gntech-ingress-lab
mkdir -p routes
(umask 077
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 7 \
  -subj '/CN=app.example.com' \
  -addext 'subjectAltName=DNS:app.example.com' \
  -keyout certs/app.key -out certs/app.crt
)
```

## 2. Define the HTTPS route and Compose project

The router matches one host on the HTTPS entry point. The backend URL uses the Compose service name `app`. Docker can assign the replacement container a different address while preserving that name.

```bash
cat > routes/app.yml <<'YAML'
http:
  routers:
    app:
      entryPoints: [websecure]
      rule: Host(`app.example.com`)
      service: app
      tls: {}
  services:
    app:
      loadBalancer:
        servers:
          - url: http://app:80
tls:
  certificates:
    - certFile: /certs/app.crt
      keyFile: /certs/app.key
YAML

cat > compose.yaml <<'YAML'
services:
  proxy:
    image: traefik:v3.6
    command:
      - --entrypoints.websecure.address=:8443
      - --providers.file.directory=/etc/traefik/routes
      - --providers.file.watch=true
      - --accesslog=true
    ports:
      - "127.0.0.1:8443:8443"
    volumes:
      - ./routes:/etc/traefik/routes:ro
      - ./certs:/certs:ro
    networks: [ingress]
  app:
    image: nginx:alpine
    volumes:
      - site:/usr/share/nginx/html
    networks: [ingress]
networks:
  ingress:
volumes:
  site:
YAML
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
```

Only the proxy publishes a guest port. Both containers share one Compose bridge, so treat membership in that bridge as permission to reach the backend. Mount the route directory so the file provider can watch it when an editor replaces a route file atomically. For repeatable upgrades, record the exact image digests and use those references in your deployment configuration.

## 3. Test ingress and persistent data separately

```bash
docker compose exec -T app sh -c 'cat > /usr/share/nginx/html/index.html' <<'HTML'
<!doctype html><title>GNTECH ingress lab</title><p>gntech-volume-check</p>
HTML

check_page() {
  curl --fail --silent --show-error \
    --cacert certs/app.crt \
    --resolve app.example.com:8443:127.0.0.1 \
    https://app.example.com:8443/
}

check_page | grep -F gntech-volume-check
docker compose up -d --force-recreate --no-deps app
check_page | grep -F gntech-volume-check
```

Both requests should return the marker. A transient 502 immediately after replacement can mean NGINX is still starting. Retry the request after checking `docker compose ps`. To exercise the router's default response, keep the TLS name and send a different HTTP Host header:

```bash
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  --cacert certs/app.crt \
  --resolve app.example.com:8443:127.0.0.1 \
  -H 'Host: unmatched.example.com' https://app.example.com:8443/
```

Expect HTTP 404 for the unmatched host. From another machine, a request to the guest's LAN address on port 8443 should fail to connect. Check the bind with `docker compose ps` if it succeeds.

## 4. Diagnose failures and roll back

| Symptom | First check |
| --- | --- |
| TLS verification fails | Check the SAN, expiry, curl hostname, and mounted certificate paths. Use `docker compose logs proxy` for file loading errors. |
| Matching hostname returns 404 | Check the Host rule and confirm the router loaded on the websecure entry point. |
| Matching hostname returns 502 | Check `docker compose ps` and `docker compose logs app`. Confirm both services are on the ingress bridge. |
| The marker disappears after replacement | Check that Compose is using the same project and named volume. A different project name can select a different volume. |

Keep the known-good Compose and route files before making changes. To roll back an image or route update, restore those files and the known-good image references, run `docker compose up -d`, and rerun the HTTPS and marker tests. To stop the exercise, run `docker compose down` without `--volumes`. An application upgrade that changes its data format may also require a compatible data restore. The marker test checks container replacement only. Part 10 will cover recovery after losing the guest or its storage.

For a shared deployment, decide which clients should reach the origin before changing its bind. For instance, a tunnel connector running directly on the same guest can use the loopback endpoint with origin TLS verification and the matching server name. Use the [Part 08 access checks](/posts/2026-11-03-gntech-infrastructure-part-08-cloudflare-zero-trust/) to verify the identity policy separately from proxy health.

## Official references

- [Traefik file provider](https://doc.traefik.io/traefik/reference/dynamic-configuration/file/)
- [Traefik TLS certificates](https://doc.traefik.io/traefik/reference/routing-configuration/http/tls/tls-certificates/)
- [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
