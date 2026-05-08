---
title: "Cloudflare Tunnel Inside MikroTik — No Dedicated Proxy VM Needed"
description: "Run Cloudflare Tunnel (cloudflared) as a container directly on MikroTik RouterOS to expose homelab services securely — no separate VM, no open ports, full firewall isolation with VLAN segmentation."
date: 2026-05-08T00:35:00-04:00
tags:
  - mikrotik
  - cloudflare
  - tunnel
  - containers
  - networking
  - routeros
  - homelab
categories:
  - homelab
  - networking
---

Cloudflare Tunnel gives you a secure outbound-only connection from your homelab to Cloudflare's edge, proxying public traffic without opening any firewall ports. No pinholes, no DMZ, no exposing your home IP.

The usual deployment is a Docker container or a systemd service on a Linux box. But if you have a MikroTik router running RouterOS 7.6+ with container support, you can run `cloudflared` directly on the router — zero extra hardware, zero extra VMs.

This post covers the full setup: enabling containers on MikroTik, pulling and configuring the cloudflared image, routing tunnel traffic through a specific VLAN, and tightening the firewall around the container.

---

## Why Run It on the Router

Putting Cloudflare Tunnel on the router instead of a separate host has three real advantages:

1. **No single-point-of-service host** — The tunnel lives on the device that's already always on. If your Docker host reboots for updates, the tunnel stays up.
2. **Cleaner VLAN routing** — The tunnel container can sit on a dedicated management VLAN (or even the bridge itself) and reach internal services through your existing inter-VLAN firewall rules instead of through Docker networking.
3. **One fewer thing to maintain** — No VM to patch, no Docker compose file to manage, no extra system to reboot. The container lifecycle is managed by RouterOS.

**The trade-off:** MikroTik containers run on a RouterOS-managed overlay filesystem with limited disk space. You won't have Docker-level tooling (no compose, no `docker exec` equivalent), and debugging is done through RouterOS commands. For a simple tunnel daemon that just needs to run, this is fine.

---

## Prerequisites

- MikroTik router running **RouterOS 7.6+** (7.22.x tested here)
- **Container mode supported** (ARM64 or x86 — check `/system resource` for architecture)
- A **USB drive or NVMe** for container storage (the router's flash is too small for images)
- A **Cloudflare account** with a domain added
- A **Cloudflare Zero Trust Tunnel** created (free tier works)

The router in this guide is an RB5009UG+S+IN (ARM64, 1 GB RAM), but the steps are the same for any RouterOS device with container support — CCR2004, CCR2116, CHR, etc.

---

## Step 1 — Prepare Storage

Containers need space. RouterOS flash is typically 128–512 MB — fine for the OS, not for container images. Mount external storage:

```routeros
# If using USB or NVMe — format and mount
/disk format-drive usb1 file-system=ext4 label=CONTAINERS
/disk set-smb-enabled disabled=yes

/container mounts add dst=/mnt/containers src=usb1
```

Create a working directory for container data:

```routeros
/container envs add key=TZ value=America/Santo_Domingo name=cloudflared-tz

# Verify mount
/container mounts print
```

---

## Step 2 — Enable Container Mode

```routeros
/container config set ram-high=512M ram-total=1G
```

Set `ram-high` to the maximum memory you want containers to use (512 MB is plenty for cloudflared). `ram-total` is the total RAM available to the container subsystem.

Enable the container feature (idempotent; safe to run again):

```routeros
/system device-mode update container=yes
```

This requires a reboot on first enable:

```routeros
/system reboot
```

After reboot, confirm containers are available:

```routeros
/container config print
```

Expected output:
```
                       ram-high: 512.0MiB
                      ram-total: 1.0GiB
                      registry-url: https://registry-1.docker.io
```

---

## Step 3 — Pull the cloudflared Image

RouterOS uses Docker registries. Add Docker Hub and pull the cloudflared image:

```routeros
/container config set registry-url=https://registry-1.docker.io

/container add
    remote-image=cloudflare/cloudflared:latest
    interface=vlan10
    root-disk=128M
    mounts=CONTAINERS
    envlist=cloudflared-tz
    start-on-boot=yes
    logging=yes
    workdir=/mnt/containers/cloudflared
```

**Notes:**
- `interface=vlan10` — Run the container on a dedicated management/storage VLAN. Adjust to your topology. If you want the tunnel to reach all internal VLANs, attach it to the bridge directly and handle routing through your firewall rules.
- `root-disk=128M` — Minimum working size for cloudflared. It uses about 80 MB at rest.
- `start-on-boot=yes` — Tunnel comes up automatically after router reboot.
- `envlist` — Pass timezone to the container.

First pull can take a while depending on your internet speed. Check progress:

```routeros
/container print detail
```

The `status` field goes through: `pulling` → `extracting` → `stopped` (once extracted, not yet started).

---

## Step 4 — Authenticate the Tunnel

Start the container:

```routeros
/container start [find where tag=cloudflared]
```

The container won't do much yet — it needs authentication. Enter the container shell:

```routeros
/container shell [find where tag=cloudflared]
```

Inside the shell, authenticate and create the tunnel:

```bash
# Authenticate — this prints a URL to visit
cloudflared tunnel login

# Create the tunnel (name it something descriptive)
cloudflared tunnel create homelab

# This creates ~/.cloudflared/<tunnel-id>.json with credentials
```

The `cloudflared tunnel login` command prints a URL. Visit it in a browser, authorize with your Cloudflare account, and the container saves a `cert.pem` to its config directory.

**Alternative — manual token creation:** If you prefer to avoid the browser flow, create the tunnel from the Cloudflare Zero Trust dashboard:

1. Go to **Zero Trust → Networks → Tunnels**
2. Create a new tunnel, choose **Cloudflared**
3. Copy the tunnel token
4. Back in the container shell: `cloudflared tunnel run --token <token>`

The tunnel token method is easier to automate and works well here since the router doesn't have a browser.

---

## Step 5 — Configure DNS and Routing

Back in the container shell, set up your DNS entries. Create or edit the config file:

```bash
mkdir -p /mnt/containers/cloudflared
cat > /mnt/containers/cloudflared/config.yml << 'EOF'
tunnel: <tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  # Grafana on internal monitoring host
  - hostname: monitoring.gntech.me
    service: https://10.0.20.50:3000
    originRequest:
      noTLSVerify: true

  # Uptime Kuma on internal monitoring host
  - hostname: status.gntech.me
    service: http://10.0.20.50:3001

  # Proxmox web UI
  - hostname: proxmox.gntech.me
    service: https://10.0.20.30:8006
    originRequest:
      noTLSVerify: true

  # Catch-all — reject unknown hostnames
  - service: http_status:404
EOF
```

**Wait — this file lives inside the container's overlay.** It will vanish on container restart. For persistence, mount the directory from step 1. Create the config on the mounted storage:

```bash
# Inside the container shell, symlink or copy
mkdir -p /mnt/containers/config
cp /root/.cloudflared/config.yml /mnt/containers/config/
```

Then configure the container to mount it:

```routeros
/container mounts add
    dst=/root/.cloudflared/config.yml
    src=/mnt/containers/config/config.yml
    type=bind

/container mount [find where tag=cloudflared]
```

This makes the config file persistent across container restarts and image updates.

---

## Step 6 — Route DNS to Cloudflare

Back on the Cloudflare dashboard, create DNS CNAME records that point to the tunnel:

```
CNAME  monitoring   <tunnel-id>.cfargotunnel.com   Proxied (orange cloud)
CNAME  status       <tunnel-id>.cfargotunnel.com   Proxied (orange cloud)
CNAME  proxmox      <tunnel-id>.cfargotunnel.com   Proxied (orange cloud)
```

Or use the Cloudflare CLI inside the container:

```bash
cloudflared tunnel route dns homelab monitoring.gntech.me
cloudflared tunnel route dns homelab status.gntech.me
cloudflared tunnel route dns homelab proxmox.gntech.me
```

---

## Step 7 — Start the Tunnel

```bash
cloudflared tunnel run homelab
```

The first run downloads the cloudflared binary's dependencies and establishes the four outbound connections to Cloudflare edge. Check the logs for:

```
+ If using quick tunnels or token: 2026-05-08T00:35:00Z INF Connection <conn-id> registered connIndex=0 location=MIA
+ Ingress rules configured
```

If everything looks good, configure it to start automatically on container boot by modifying the entrypoint. Create a startup script on the persistent mount:

```bash
cat > /mnt/containers/config/start.sh << 'SCRIPT'
#!/bin/sh
cloudflared tunnel run --token <your-token>
SCRIPT
chmod +x /mnt/containers/config/start.sh
```

Then set the container's entrypoint to this script:

```routeros
/container set [find where tag=cloudflared] cmd="/mnt/containers/config/start.sh"
/container stop [find where tag=cloudflared]
/container start [find where tag=cloudflared]
```

---

## Firewall — Lock Down the Container

The container needs outbound access to Cloudflare's IP ranges and nothing else. On RouterOS, isolate it:

```routeros
# Allow only Cloudflare edge IPs
/ip firewall address-list
add address=198.41.128.0/17 list=cloudflare-ipv4
add address=162.158.0.0/15 list=cloudflare-ipv4
add address=104.16.0.0/12 list=cloudflare-ipv4
add address=172.64.0.0/13 list=cloudflare-ipv4
add address=2a06:98c0::/29 list=cloudflare-ipv6

# Firewall filter — container VLAN outbound only to Cloudflare
/ip firewall filter
add chain=forward
    src-address=10.0.10.0/24
    dst-address-list=cloudflare-ipv4
    action=accept
    comment="Cloudflared → Cloudflare"

add chain=forward
    src-address=10.0.10.0/24
    action=drop
    comment="Drop other outbound from container VLAN"
```

The container sits on VLAN 10 (management). It can reach internal services on other VLANs through your existing inter-VLAN forward rules, but all external traffic is restricted to Cloudflare's IP ranges only. No DNS, no NTP, no general internet — just the tunnel.

---

## Step 9 — Verify and Monitor

Check tunnel health from the container:

```bash
cloudflared tunnel info homelab
```

Monitor from RouterOS:

```routeros
/container print detail
/container logs [find where tag=cloudflared]
```

Set up a health check on Uptime Kuma pointing at one of your tunneled services — it confirms both the tunnel and Kuma are working.

---

## Performance Notes

- **Latency overhead:** Cloudflare Tunnel adds roughly 5–20 ms for a homelab geographically close to a Cloudflare edge. For SSH and web UIs, it's unnoticeable.
- **Throughput:** Cloudflared caps around 50–100 Mbps on a MikroTik RB5009 under load. If you need higher throughput, run cloudflared on a dedicated host instead.
- **Memory:** cloudflared uses 60–80 MB resident on ARM64 total for the tunnel and ingress routing. The RouterOS container overhead adds about 20 MB.
- **CPU:** Near-zero idle. Under load, about 5–10% of one core on RB5009 for a handful of proxied services.

The router isn't a proxy server — it's a tunnel endpoint. For heavy traffic (file transfers, video streaming), bypass the tunnel and access services directly on your LAN or through WireGuard.

---

## Updating cloudflared

RouterOS doesn't have auto-update for containers. Update manually:

```routeros
/container remove [find where tag=cloudflared]
/container add
    remote-image=cloudflare/cloudflared:latest
    interface=vlan10
    root-disk=128M
    mounts=CONTAINERS
    envlist=cloudflared-tz
    start-on-boot=yes
    cmd="..."
    workdir=/mnt/containers/cloudflared
```

The pull grabs the latest image automatically. Your persistent config mount survives the rebuild.

To stay notified, watch the Cloudflare blog or subscribe to the [cloudflared releases](https://github.com/cloudflare/cloudflared/releases) on GitHub.

---

## Alternative: Cloudflare Tunnel via Docker (for Reference)

If you'd rather run it on a Docker host inside the VM/container, the compose file is simpler:

```yaml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run --token <your-token>
    networks:
      - internal
    volumes:
      - ./config:/root/.cloudflared

networks:
  internal:
    driver: bridge
```

This is the "standard" approach documented everywhere. The MikroTik container approach eliminates the host dependency — pick whichever fits your architecture.

---

## Summary

```
                     ┌──────────────┐
                     │  Cloudflare   │
                     │    Edge       │
                     └──────┬───────┘
                            │ 4x outbound QUIC
                            │
                     ┌──────┴───────┐
                     │  MikroTik R1  │
                     │  (VLAN 10)    │
                     │  ┌─────────┐  │
                     │  │cloud-   │  │
                     │  │flared   │  │
                     │  └─────────┘  │
                     └──────┬───────┘
                            │ inter-VLAN routing
                            │
               ┌────────────┼────────────┐
               │            │            │
        ┌──────┴─────┐ ┌───┴────┐ ┌────┴────┐
        │  Proxmox   │ │Grafana │ │Uptime   │
        │   Web UI   │ │        │ │ Kuma    │
        └────────────┘ └────────┘ └─────────┘
```

Cloudflare Tunnel on MikroTik is an elegant way to expose homelab services without an extra host. The router's already running 24/7 with redundant power and connectivity — offloading the tunnel to it removes a potential point of failure and keeps your VM/container hosts independent.
