---
title: "Headscale — Self-Hosted Tailscale Mesh VPN Server with Docker Compose"
description: "Deploy Headscale, a self-hosted Tailscale control server, with Docker Compose to create your own WireGuard-based mesh VPN. Covers setup, client registration, ACLs, subnet routing, and reverse proxy configuration."
date: 2026-05-19T17:15:00-04:00
tags:
  - docker
  - networking
  - vpn
  - homelab
  - selfhosting
keywords:
  - Headscale self-hosted Tailscale server Docker Compose
  - WireGuard mesh VPN homelab deployment
  - Headscale Docker setup configuration guide
  - self-hosted Tailscale alternative headscale
  - Headscale ACL subnet routing configuration
  - Docker Compose Headscale reverse proxy Traefik
  - mesh VPN homelab headscale tailscale
summary: "Deploy Headscale with Docker Compose to run your own WireGuard mesh VPN control plane. Complete guide from setup to client registration, ACL configuration, subnet routing, and production hardening."
canonical: "https://gntech.dev/posts/headscale-self-hosted-tailscale-server/"
---

Tailscale makes connecting devices dead simple — install the client,
authenticate, and every machine on your tailnet can reach every
other machine over an encrypted WireGuard tunnel. No port
forwarding, no dynamic DNS, no public IP required.

The catch: the official Tailscale control server is proprietary
and hosted in Tailscale's cloud. While the free tier is generous,
you're trusting someone else's infrastructure with your network
topology metadata, and the free tier caps at 100 devices with 3
users.

Enter **Headscale** — an open-source, self-hosted implementation of
the Tailscale control server. You run the coordination plane on
your own hardware, use the same official Tailscale clients on
every device, and keep full control over authentication, ACLs, and
routing metadata.

This guide covers deploying Headscale with Docker Compose, securing
it behind Traefik with Let's Encrypt, registering clients, defining
ACLs for network segmentation, and enabling subnet routing so your
entire homelab LAN becomes reachable from anywhere.

---

## How Headscale and Tailscale Work

Understanding the architecture helps when things don't work.

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────┐
│  Laptop      │      │  Headscale       │      │  Phone       │
│  tailscale   │◄────►│  Control Plane   │◄────►│  tailscale   │
│  10.0.0.2    │      │  10.0.0.1        │      │  10.0.0.3    │
└──────┬───────┘      └──────────────────┘      └──────┬───────┘
       │                                                │
       │                WireGuard Direct                │
       └────────────────────────────────────────────────┘
                      (NAT traversal)
```

- **Control Plane (Headscale):** Authenticates devices, exchanges
  public WireGuard keys, distributes the network map. Your traffic
  never passes through it — it's just the phone book.
- **Data Plane (Tailscale client):** Each device establishes direct
  WireGuard tunnels to every other device. Traffic is peer-to-peer,
  end-to-end encrypted, with NAT traversal via STUN and DERP relay
  servers as fallback.
- **Private IP allocation:** Every node gets a unique IP in the
  Tailscale range (default `100.64.0.0/10`). These IPs are
  reachable from any connected device.

Headscale replaces only the control plane. The clients are the
same official Tailscale clients — no proprietary fork needed.

---

## Step 1 — Prerequisites

You need:

- A server with Docker and Docker Compose (a $5 VPS or your
  Proxmox host works fine)
- A domain name pointing to the server's public IP
- Port 443 (HTTPS) reachable from the internet
- Traefik or another reverse proxy already running (this guide
  assumes Traefik, but any reverse proxy works)

Headscale is extremely lightweight. A single-core VM with 512MB RAM
handles 50+ devices without breaking a sweat — the control plane
exchanges key material and coordinates routes but never touches
traffic.

---

## Step 2 — Directory Structure and Configuration

```bash
mkdir -p /opt/headscale/{config,lib}
cd /opt/headscale
```

Download the Headscale configuration file for the latest stable
release:

```bash
HEADSCALE_VERSION="0.28.0"
curl -o config/config.yaml \
  "https://raw.githubusercontent.com/juanfont/headscale/v${HEADSCALE_VERSION}/config-example.yaml"
```

Edit `config/config.yaml` with the minimal changes needed:

```yaml
# /opt/headscale/config/config.yaml

# Listen on all interfaces inside the container (port 8080)
listen_addr: 0.0.0.0:8080

# The public URL of your Headscale instance — this must be reachable
# by ALL clients. Set this to your reverse proxy URL.
server_url: https://headscale.example.org

# Listen address for gRPC (for headscale CLI commands)
grpc_listen_addr: 0.0.0.0:50443

# Enable gRPC for CLI access
grpc_allow_insecure: false

# Database — SQLite is fine for homelab use (< 100 devices).
# For HA setups, switch to PostgreSQL.
database:
  type: sqlite3
  sqlite:
    path: /var/lib/headscale/db.sqlite

# WireGuard settings
wireguard:
  private_key_path: /var/lib/headscale/wireguard.key

# Tuning
acme_url: https://acme-v02.api.letsencrypt.org/directory
acme_email: "admin@example.org"
dns:
  # Base domain for your tailnet — this is where your internal DNS
  # MagicDNS names live (e.g., laptop.example-tailnet.ts.net)
  domain: example-headscale.ts.net

  # Whether to override the local DNS on clients
  magic_dns: true

  # DNS servers to push to clients (can serve internal services)
  nameservers:
    - 10.0.20.1     # Your homelab DNS (Pi-hole, Unbound, etc.)
    - 1.1.1.1
    - 8.8.8.8

  # Search domains — handy for resolving internal hostnames
  search_domains:
    - homelab.internal

# Randomize client port for better NAT traversal
randomize_client_port: true
```

Key configuration details:

- **`server_url`**: Must be the HTTPS URL clients use to reach
  Headscale. Change this to your actual domain.
- **`magic_dns`**: When enabled, every device gets a DNS name like
  `laptop.example-headscale.ts.net`. Clients can resolve each other
  by hostname instead of IP.
- **`nameservers`**: Push your homelab DNS servers to connected
  clients so internal hostnames resolve on the VPN.

---

## Step 3 — Docker Compose Deployment

```yaml
# /opt/headscale/docker-compose.yml
services:
  headscale:
    image: headscale/headscale:0.28.0
    container_name: headscale
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /var/run/headscale
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:9090:9090"
    volumes:
      - ./config:/etc/headscale:ro
      - ./lib:/var/lib/headscale
    environment:
      - TZ=America/Santo_Domingo
    command: serve
    healthcheck:
      test: ["CMD", "headscale", "health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

About this setup:

- **`ports: 127.0.0.1:8080:8080`**: Only binds to localhost.
  Headscale is NOT exposed directly — your reverse proxy handles
  external traffic. This is a critical security boundary.
- **`read_only: true`**: The container filesystem is immutable.
  Runtime data lives in the `tmpfs` mount (for PID/socket files)
  and the `lib` volume (for the database and keys).
- **Port 9090**: gRPC endpoint for CLI operations. Only needed for
  `docker exec` commands.

Start it:

```bash
docker compose up -d
```

Verify it's healthy:

```bash
curl http://127.0.0.1:8080/health
# {"status":"pass"}
```

---

## Step 4 — Traefik Reverse Proxy Configuration

If you're already running Traefik (see the Gitea or Authentik
deployment guides on this blog), add a new router and service:

```yaml
# Traefik dynamic config — add to your existing Traefik config
services:
  headscale:
    loadBalancer:
      servers:
        - url: "http://10.0.20.30:8080"

routers:
  headscale:
    rule: "Host(`headscale.example.org`)"
    entryPoints:
      - websecure
    service: headscale
    tls:
      certResolver: letsencrypt
```

Or in Docker Compose with labels (if Traefik auto-discovers):

```yaml
services:
  headscale:
    # ... rest of the service config
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.headscale.rule=Host(`headscale.example.org`)"
      - "traefik.http.routers.headscale.entrypoints=websecure"
      - "traefik.http.routers.headscale.tls.certResolver=letsencrypt"
      - "traefik.http.services.headscale.loadbalancer.server.port=8080"
```

If you use Nginx Proxy Manager or Caddy, the setup is similar:
proxy pass to `http://127.0.0.1:8080`, enable WebSocket support,
and terminate TLS with Let's Encrypt.

Verify the public endpoint:

```bash
curl https://headscale.example.org/health
# {"status":"pass"}
```

---

## Step 5 — Create Users and Namespaces

Headscale groups devices by **users** (previously called namespaces
in older versions). Devices under the same user can see each other
by default.

```bash
# Create a user for your primary network
docker compose exec headscale headscale users create homelab

# Create separate users for isolation
docker compose exec headscale headscale users create servers
docker compose exec headscale headscale users create iot

# List users
docker compose exec headscale headscale users list
```

Output:

```
ID | Name    | Created
1  | homelab | 2026-05-19 17:05:00
2  | servers | 2026-05-19 17:05:00
3  | iot     | 2026-05-19 17:05:00
```

**Why separate users?** Devices in different users are isolated.
Use this to segment trusted devices (your laptop, phone) from
untrusted ones (IoT widgets, guest VMs).

---

## Step 6 — Register Client Devices

### Method A: Interactive Registration (for laptops and workstations)

Install the Tailscale client on your device:

```bash
# Linux
curl -fsSL https://tailscale.com/install.sh | sh

# macOS
brew install tailscale
```

On the client, start the connection pointing at your Headscale
server:

```bash
sudo tailscale up --login-server https://headscale.example.org
```

The client prints an authentication URL:

```
To authenticate, visit:
  https://headscale.example.org/register/STqfQR4wnKr-eerDXam3_RYi
```

Open that URL in a browser. It shows the node key and a command
to run on your headscale server:

```bash
# Run this on the headscale server
docker compose exec headscale headscale nodes register \
  --key STqfQR4wnKr-eerDXam3_RYi \
  --user homelab

# Node registered
```

Verify the node is connected:

```bash
docker compose exec headscale headscale nodes list
```

Output:

```
ID | Hostname | User    | IP addresses      | Connected | Last seen
1  | laptop   | homelab | 100.64.0.1, fd7a:... | Yes  | 2026-05-19 17:10
```

From the laptop, test connectivity:

```bash
tailscale status  # show all connected devices
ping 100.64.0.2   # ping another connected node
```

### Method B: Pre-Auth Keys (for servers and automation)

Pre-auth keys let you register devices without interactive
authentication — perfect for CI/CD, deployment scripts, or
headless servers:

```bash
# Generate a pre-auth key for the servers user, reusable
docker compose exec headscale headscale preauthkeys create \
  --user servers \
  --reusable \
  --expiration 24h

# Output: c932d8c4e4a8d2209cf539e6d3ef0a4212330b8a24e60d49
```

On the server node:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --authkey c932d8c4e4a8d2209cf539e6d3ef0a4212330b8a24e60d49
```

The node registers silently and appears in the list immediately.

**Key options:**

| Flag | Purpose |
|------|---------|
| `--reusable` | Use the same key for multiple devices |
| `--ephemeral` | Node disappears from the list when it disconnects |
| `--expiration 24h` | Key auto-expires (recommended for security) |

---

## Step 7 — Subnet Routing (Access Your Full LAN)

By default, Tailscale only gives you access to the Tailscale IPs
of connected devices. If you want to reach your entire 10.0.20.0/24
homelab LAN from a remote laptop, enable subnet routing.

### 7a — Configure the Exit Node

On the server that sits on your homelab LAN (e.g., your Proxmox
host), advertise the subnet:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --advertise-routes=10.0.20.0/24
```

### 7b — Approve Routes on Headscale

```bash
docker compose exec headscale headscale routes list

# ID | Machine      | Prefix       | Enabled | Primary
# 1  | proxmox-host | 10.0.20.0/24 | false   | false

docker compose exec headscale headscale routes enable -r 1

# Route enabled
```

### 7c — Accept Routes on Clients

On each client that needs LAN access:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --accept-routes
```

Now from your laptop anywhere in the world:

```bash
ping 10.0.20.1      # Your router
curl http://10.0.20.30:8888  # SearXNG on Proxmox (if accessible)
ssh admin@10.0.20.30         # SSH to Proxmox
```

Your entire LAN is reachable as if you were sitting at home.

### Exit Node (Full Tunnel)

For full traffic routing (like a traditional VPN), advertise as an
exit node:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --advertise-routes=0.0.0.0/0,::/0
```

Approve the `0.0.0.0/0` route on Headscale:

```bash
docker compose exec headscale headscale routes enable -r <route-id>
```

Clients can then use this node as an exit node:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --exit-node=proxmox-host
```

All traffic routes through your home connection — useful for
public Wi-Fi security or accessing geo-restricted services.

---

## Step 8 — Access Control Lists (ACLs)

Without ACLs, any device can talk to any other device. ACLs let
you define who can talk to whom with a simple declarative syntax.

Create `/opt/headscale/config/acls.hujson`:

```json
{
  "groups": {
    "group:admin": ["homelab"],
    "group:servers": ["servers"],
    "group:iot": ["iot"]
  },
  "acls": [
    // Admins can access everything
    {"action": "accept", "src": ["group:admin"], "dst": ["*:*"]},

    // Servers can talk to each other on all ports
    {"action": "accept", "src": ["group:servers"], "dst": ["group:servers:*"]},

    // Admin can access servers on SSH and HTTPS only
    {"action": "accept", "src": ["group:admin"], "dst": ["group:servers:22,443"]},

    // IoT devices can only reach the internet (exit node)
    // and cannot initiate connections to admin or server devices
    {"action": "accept", "src": ["group:iot"], "dst": ["*:80,443"]},

    // Default deny — anything not explicitly allowed is blocked
    {"action": "deny", "src": ["*"], "dst": ["*:*"]}
  ],
  // Tag-based ACLs for more granular control
  "tagOwners": {
    "tag:monitoring-server": ["group:admin"]
  }
}
```

Reference this file in `config.yaml`:

```yaml
# /opt/headscale/config/config.yaml
acl_policy_path: /etc/headscale/acls.hujson
```

Then apply and test:

```bash
docker compose restart headscale

# Test ACLs
docker compose exec headscale headscale acl debug \
  --host 100.64.0.1 --port 22
# Action: accept
```

ACL best practices:

- **Start restrictive:** Default deny, then grant specific access
- **Use groups:** Group devices by function, not by hostname
- **Protocol-aware:** Tag-based ACLs let you match on Tailscale
  tags instead of user membership
- **Test changes:** Run `acl debug` before deploying to prevent
  accidental lockouts

---

## Step 9 — DERP Relay Servers

Tailscale prefers direct peer-to-peer connections, but when NAT
traversal fails (symmetric NAT, strict firewalls), it falls back
to DERP (Detour Encrypted Routing Protocol) relay servers.

Headscale includes a built-in DERP server. Enable it in
`config.yaml`:

```yaml
derp:
  server:
    enabled: true
    region_id: 999
    region_code: "homelab-derp"
    region_name: "Homelab DERP"
    stun_listen_addr: "0.0.0.0:3478"
  urls:
    # Pull official Tailscale DERP servers as fallback
    - https://controlplane.tailscale.com/derpmap/default
```

Add the STUN port to your firewall:

```bash
# On the host
sudo ufw allow 3478/udp
```

If you don't want to depend on Tailscale's DERP servers at all
(self-contained tailnet with no external dependencies), set
`urls: []` — but this breaks connectivity between clients behind
symmetric NAT that can't establish direct WireGuard tunnels.

---

## Step 10 — Production Hardening

### 10a — Regular Backups

Your Headscale data is in `/opt/headscale/lib/`. Back up the entire
directory:

```bash
# Add to your nightly backup script
tar czf /backups/headscale-$(date +%Y%m%d).tar.gz -C /opt/headscale lib/
```

If you lose this data, all registered devices need to
re-authenticate. The database contains the WireGuard public keys,
node assignments, and ACL configuration.

### 10b — Monitoring and Alerts

Add health checks to your monitoring stack:

```yaml
# Prometheus scrape config for Headscale metrics
scrape_configs:
  - job_name: 'headscale'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['headscale.example.org']
```

Grafana dashboard metrics to watch:

- `headscale_nodes_total` — registered device count
- `headscale_nodes_online` — currently connected devices
- `headscale_requests_total` — API request volume
- Certificate expiry (from Traefik)

### 10c — Key Rotation

```bash
# Force re-authentication for all nodes (after a compromise)
docker compose exec headscale headscale nodes expire --all

# Regenerate your WireGuard key
docker compose exec headscale headscale node delete --all
docker compose exec headscale headscale nodes expire --all
# Then restart headscale and re-register clients
```

### 10d — Restrict gRPC Access

The gRPC port (9090) is bound to localhost by default and should
stay that way. If you need remote CLI access, tunnel through SSH:

```bash
ssh admin@headscale-host \
  "docker compose exec headscale headscale nodes list"
```

---

## Step 11 — Client Tuning Tips

### macOS/iOS clients

Add DNS search domains for your homelab:

```bash
sudo tailscale up \
  --login-server https://headscale.example.org \
  --accept-dns=false
# Then manually configure DNS in System Settings
```

### Linux server clients (no GUI)

```bash
# Headless setup for servers
sudo systemctl enable --now tailscaled

# Register with pre-auth key (no browser needed)
sudo tailscale up \
  --login-server https://headscale.example.org \
  --authkey <preauth-key> \
  --hostname web-server-01

# Advertise routes
sudo tailscale up \
  --login-server https://headscale.example.org \
  --authkey <preauth-key> \
  --advertise-routes=10.0.20.0/24 \
  --accept-routes
```

### Docker containers on the tailnet

Use a Tailscale sidecar container for Docker services:

```yaml
services:
  tailscale-sidecar:
    image: tailscale/tailscale:latest
    container_name: tailscale-sidecar
    hostname: my-service
    environment:
      - TS_AUTHKEY=<preauth-key>
      - TS_EXTRA_ARGS=--login-server=https://headscale.example.org
      - TS_USERSPACE=true
      - TS_STATE_DIR=/var/lib/tailscale
    volumes:
      - tailscale-state:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - net_admin
      - sys_module
    restart: unless-stopped

volumes:
  tailscale-state:
```

Then route traffic through the sidecar's Tailscale IP. This gives
each Docker service its own stable mesh IP without installing
anything on the host.

---

## Why Headscale Over Direct WireGuard or Tailscale SaaS

| Feature | Headscale | Tailscale SaaS | WireGuard only |
|---------|-----------|----------------|----------------|
| **Control plane** | Self-hosted | Cloud-only | None (manual) |
| **Client count** | Unlimited | 100 (free) | Unlimited |
| **NAT traversal** | Built-in | Built-in | Manual (STUN) |
| **ACLs** | Declarative HuJSON | Web UI + ACLs | iptables/nftables |
| **MagicDNS** | Yes | Yes | No |
| **Subnet routing** | Yes | Yes | Manual routes |
| **Exit nodes** | Yes | Yes | Manual NAT |
| **Data sovereignty** | Full | None | Full |
| **Setup complexity** | Medium | Low | High |
| **Cost** | VPS + domain | Free tier | Free |

**Choose Headscale when:** You want Tailscale's zero-config
WireGuard mesh without depending on Tailscale's infrastructure,
need unlimited devices, or want full ACL control with declarative
policies.

**Choose Tailscale SaaS when:** You want the easiest possible
setup, don't mind the dependency, and your device count is under
100.

**Choose raw WireGuard when:** You need a simple site-to-site VPN
with a known peer count and can manage keys manually.

---

## Troubleshooting

### Clients can't connect

```bash
# Check Headscale server health
curl https://headscale.example.org/health

# Check DNS resolution
dig +short headscale.example.org

# Check port reachability from outside
nc -zv headscale.example.org 443

# View server logs
docker compose logs --tail=50 headscale
```

### Nodes show "offline" in the list

```bash
# Restart tailscaled on the client
sudo systemctl restart tailscaled

# Then re-authenticate
sudo tailscale up --login-server https://headscale.example.org
```

### MagicDNS not resolving

```bash
# On the client, verify DNS configuration
tailscale dns status

# If MagicDNS is disabled or misconfigured, restart tailscaled
sudo tailscale down
sudo tailscale up --login-server https://headscale.example.org --accept-dns
```

### ACL change not taking effect

```bash
# Restart headscale to reload ACLs
docker compose restart headscale

# Debug specific traffic
docker compose exec headscale headscale acl debug \
  --src 100.64.0.1 --dst 100.64.0.2 --port 443
```

---

## Summary

Headscale gives you the best of both worlds: Tailscale's
zero-config WireGuard mesh with WireGuard's full data sovereignty.
Running it in Docker Compose with Traefik is straightforward and
maintainable:

1. Deploy Headscale behind a reverse proxy on port 443
2. Create users to segment devices logically
3. Register clients interactively or with pre-auth keys
4. Enable subnet routing to reach your full homelab LAN
5. Define ACLs with HuJSON for least-privilege access
6. Add DERP relay for reliable NAT traversal
7. Back up the lib directory — without it, every device
   re-authenticates

The result is a mesh VPN that connects your laptop, phone, servers,
and IoT devices into a single private network with zero manual
WireGuard key management, no port forwarding, and no third-party
dependency.
