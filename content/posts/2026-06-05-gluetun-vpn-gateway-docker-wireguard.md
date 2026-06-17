---
title: "Gluetun VPN Gateway — Route Docker Containers Through WireGuard"
description: "Route Docker containers through a WireGuard VPN with Gluetun split-tunnel gateway. Full Compose config, kill switch, qBittorrent integration, and Traefik compatibility for homelab privacy."
date: 2026-06-05T16:00:00-04:00
tags:
  - docker
  - vpn
  - networking
  - homelab
  - security
keywords:
  - Gluetun Docker VPN gateway homelab configuration guide
  - Docker WireGuard split-tunnel Gluetun setup
  - Gluetun kill switch Docker container VPN protection
  - Docker Compose Gluetun qBittorrent VPN routing
  - Docker VPN gateway Traefik reverse proxy compatibility
  - qdm12 Gluetun docker compose WireGuard OpenVPN config
  - Homelab Docker container VPN split tunneling best practices
summary: "Route specific Docker containers through a WireGuard VPN while keeping the rest of your stack on the local network. Full Gluetun Docker Compose setup with kill switch, qBittorrent integration, and Traefik compatibility."
canonical: "https://blog.gntech.me/posts/gluetun-vpn-gateway-docker-wireguard/"
---

## Why Split-Tunnel VPN in Docker

A VPN on your entire Docker host creates friction. Plex and Jellyfin become unreachable from your local network. Traefik ACME challenges fail. Remote SSH access gets complicated. DNS resolution slows down through the VPN provider's resolvers. And every container — not just the ones that need privacy — pays the latency tax.

The solution is split-tunnel VPN routing: a dedicated VPN gateway container that only specific containers use, while the rest of your stack stays on your local network with full throughput and direct access.

**Gluetun** ([github.com/qdm12/gluetun](https://github.com/qdm12/gluetun)) is a lightweight Go-based Docker container that connects to your VPN provider over WireGuard or OpenVPN and exposes itself as a network gateway for other containers. It includes a built-in firewall that acts as a kill switch — when the VPN drops, all traffic from attached containers is blocked immediately. No leaks.

## How Gluetun Works as a Docker Network Gateway

Gluetun does not run as a sidecar container that you exec into. It owns its own network namespace, and you attach other containers to it using Docker's `network_mode: "service:gluetun"` directive. Traffic from those containers flows through Gluetun's interface — encrypted and routed through your VPN provider.

The data flow looks like this:

```
qBittorrent → [network_mode: service:gluetun] → Gluetun → WireGuard tunnel → VPN provider → Internet
```

The rest of your Docker stack — Traefik, Grafana, Homepage — stays on the `docker bridge` or your custom network and connects directly. No latency, no routing conflicts.

Gluetun supports over 30 VPN providers natively including Mullvad, ProtonVPN, NordVPN, IVPN, Windscribe, AirVPN, Surfshark, Private Internet Access, CyberGhost, and VyprVPN. You can also configure a custom WireGuard or OpenVPN configuration for any provider.

## Docker Compose Setup with WireGuard

Here is a production-ready Compose file using Mullvad with WireGuard. Adjust the environment variables for your provider and credentials.

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun:latest
    container_name: gluetun
    cap_add:
      - NET_ADMIN
    environment:
      - VPN_SERVICE_PROVIDER=mullvad
      - VPN_TYPE=wireguard
      - WIREGUARD_PRIVATE_KEY=your_private_key_here
      - WIREGUARD_ADDRESSES=10.64.x.x/32
      - SERVER_REGIONS=us-east
      - TZ=America/Santo_Domingo
    ports:
      # qBittorrent WebUI — expose through Gluetun
      - 8080:8080/tcp
      # qBittorrent DHT / transfer ports
      - 56881:56881/udp
      - 56881:56881/tcp
    restart: unless-stopped

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    network_mode: "service:gluetun"
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
      - WEBUI_PORT=8080
    volumes:
      - ./qbittorrent/config:/config
      - ./qbittorrent/downloads:/downloads
    depends_on:
      gluetun:
        condition: service_healthy
    restart: unless-stopped
```

The critical lines:

- `network_mode: "service:gluetun"` — qBittorrent shares Gluetun's network namespace. All its outbound traffic routes through the VPN.
- `ports:` are declared on the **Gluetun** service (not qBittorrent) — the `network_mode` directive means qBittorrent cannot bind ports directly. Only the service that owns the namespace (Gluetun) can publish ports.
- `cap_add: NET_ADMIN` — required for Gluetun to manage firewall rules and network interfaces inside the container.
- `depends_on: gluetun: condition: service_healthy` — waits for Gluetun's health check to pass (VPN connected and stable) before starting qBittorrent.

### Environment Variable Reference

Gluetun uses a flat environment variable scheme. The most important ones:

| Variable | Purpose |
|----------|---------|
| `VPN_SERVICE_PROVIDER` | Your provider (mullvad, protonvpn, nordvpn, etc.) |
| `VPN_TYPE` | wireguard or openvpn |
| `WIREGUARD_PRIVATE_KEY` | Your WireGuard private key |
| `WIREGUARD_ADDRESSES` | Internal address assigned by provider |
| `SERVER_REGIONS` | Comma-separated preferred regions |
| `SERVER_COUNTRIES` | Alternative to SERVER_REGIONS |
| `VPN_PORT_FORWARDING` | Enable port forwarding (provider dependent) |
| `FIREWALL_VPN_INPUT_PORTS` | Ports allowed in through the firewall |
| `FIREWALL_OUTBOUND_SUBNETS` | Subnets accessible outside the VPN (LAN, Docker networks) |

### Firewall — Allowing Access to Local Subnets

By default, Gluetun's kill switch blocks ALL non-VPN traffic, including connections to your local network. That means qBittorrent won't be able to reach your SMB/NFS shares or local indexers. Add `FIREWALL_OUTBOUND_SUBNETS` to allow LAN traffic:

```yaml
environment:
  - FIREWALL_OUTBOUND_SUBNETS=10.0.20.0/24,172.17.0.0/16
```

This allows containers behind the VPN to reach your homelab subnet without breaking the kill switch for internet traffic.

## Attaching Multiple Containers to the Same Gateway

You can attach multiple downstream containers to the same Gluetun instance. Each container uses `network_mode: "service:gluetun"`. Ports must be unique across all services — you cannot have two containers both exposing port 8080 through the same gateway.

```yaml
services:
  gluetun:
    # ... as above
    ports:
      - 8080:8080/tcp   # qBittorrent
      - 9696:9696/tcp   # Prowlarr
      - 7878:7878/tcp   # Radarr

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    network_mode: "service:gluetun"
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
    volumes:
      - ./prowlarr/config:/config
    depends_on:
      gluetun:
        condition: service_healthy
    restart: unless-stopped

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    network_mode: "service:gluetun"
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
    volumes:
      - ./radarr/config:/config
      - ./qbittorrent/downloads:/downloads
    depends_on:
      gluetun:
        condition: service_healthy
    restart: unless-stopped
```

## Integration with Traefik Reverse Proxy

Containers behind Gluetun's `network_mode` cannot be reached through Docker provider service discovery. Traefik runs on a different network so it cannot route traffic to qBittorrent's port 8080 via the usual Docker labels.

The solution: **Traefik routes to Gluetun's published ports**, not to the downstream container directly.

On your Traefik network, add Gluetun and label it for routing:

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun:latest
    container_name: gluetun
    cap_add:
      - NET_ADMIN
    networks:
      - traefik_network  # attach to Traefik's network
    environment:
      # ... VPN config same as above
    ports:
      - 8080:8080/tcp
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.qbittorrent.rule=Host(`qb.homelab.example.com`)"
      - "traefik.http.routers.qbittorrent.entrypoints=https"
      - "traefik.http.services.qbittorrent.loadbalancer.server.port=8080"
    restart: unless-stopped
```

The Traefik labels go on the **Gluetun** service, not on qBittorrent, because Gluetun publishes the port. Downstream containers are isolated from any network that Traefik can reach — only Gluetun connects both sides.

## Verifying the Kill Switch

After starting the stack, verify that traffic is routing through the VPN:

```bash
# Check Gluetun logs
docker compose logs gluetun | grep -i "connection"

# Verify qBittorrent's public IP
docker compose exec qbittorrent curl -s ifconfig.me

# Confirm Gluetun health
docker compose ps gluetun

# Test DNS resolution through the VPN
docker compose exec qbittorrent curl -s https://ipinfo.io/json
```

Simulate a VPN disconnection to confirm the kill switch:

```bash
# Restart Gluetun to simulate disconnect
docker compose restart gluetun

# While it reconnects, try reaching the internet from qBittorrent
docker compose exec qbittorrent curl -s ifconfig.me
# Should hang or fail — traffic is blocked
```

When the kill switch works correctly, `curl ifconfig.me` will fail or hang while Gluetun reconnects. Once connected, it returns the VPN exit IP.

## Troubleshooting Common Issues

**Port binding conflicts**: If two services behind the same Gluetun instance need the same port (e.g., both use :8080), you must run separate Gluetun instances with different port mappings.

**Traefik 503 errors**: The Gluetun container must be on the same Docker network as Traefik. Labels go on the Gluetun service, not downstream containers. Verify the container resolves from Traefik's network.

**DNS leaks**: Gluetun uses DNS over TLS by default. If you see DNS queries bypassing the VPN, set `DNS_OVER_TLS=on` and `DNS_ADDRESS=1.1.1.1:853` explicitly.

**WireGuard handshake failures**: Check your private key and allowed IPs. Mullvad requires a specific WireGuard key generated from their account page, not just any key:

```bash
# Generate a WireGuard key pair (does NOT work with Mullvad — use their tool)
# Mullvad requires keys generated via their API or account page
```

**Routing to local services from VPN containers**: The firewall blocks non-VPN subnets by default. Use `FIREWALL_OUTBOUND_SUBNETS` to explicitly allow specific subnets. This does not weaken the kill switch — it only opens routes to IPs you specify.

## Summary

Gluetun solves the fundamental tension between privacy and accessibility in homelab Docker deployments. By routing only specific containers through a VPN gateway with a built-in kill switch, you keep Plex, Jellyfin, Traefik, and your management tools on the local network while your download stack exits through an encrypted tunnel.

The WireGuard setup provides excellent performance — near line-speed throughput with minimal CPU overhead compared to OpenVPN. Combined with `depends_on: condition: service_healthy` for ordered startup and `FIREWALL_OUTBOUND_SUBNETS` for LAN access, this pattern handles the full breadth of homelab VPN routing needs without the operational headache of running a VPN on the host.
