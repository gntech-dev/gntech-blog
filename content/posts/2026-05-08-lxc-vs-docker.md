---
title: "Proxmox LXC vs Docker — Picking the Right Container for Every Homelab Job"
description: "A practical guide to when LXC containers make sense vs Docker, with real config examples from an existing VLAN-segmented Proxmox stack."
date: 2026-05-08T12:00:00-04:00
tags: ["proxmox", "docker", "lxc", "containers", "homelab"]
---

If you run Proxmox VE, you've got two container runtimes at your fingertips — LXC (built into Proxmox) and Docker (nested in an LXC or VM). Both are "containers" in the broad sense, but they solve different problems. Picking wrong means performance you don't need or isolation you don't have.

This post walks through the decision criteria, backed by configs from an existing homelab running Proxmox 8.x with VLAN segmentation.

```
┌─────────────────────────────────────────────────────┐
│                   Proxmox Host                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  LXC A   │  │  LXC B   │  │  Ubuntu VM        │  │
│  │ (sys)    │  │ (Docker) │  │  ┌──────────────┐ │  │
│  │          │  │          │  │  │ docker0       │ │  │
│  │ sshd,    │  │ ctr1 ctr2│  │  │ c1 │ c2 │ c3 │ │  │
│  │ nginx,   │  │          │  │  └──────────────┘ │  │
│  │ cron     │  │          │  │                    │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
     VLAN 20         VLAN 20           VLAN 20
     (LAB)           (LAB)             (LAB)
```

## The Core Trade-Off

| Aspect | LXC (Proxmox CT) | Docker (in LXC/VM) |
|--------|-------------------|---------------------|
| **Kernel** | Shares host kernel | Shares host kernel (Docker LXC) or own (VM) |
| **Startup** | ~1-2 seconds | ~200ms per container |
| **Overhead** | Near-zero | Minimal (+ Docker daemon) |
| **Filesystem** | Host filesystem (dir/ZFS) | Layered images, copy-on-write |
| **App lifecycle** | Systemd services | Declarative compose, restart policies |
| **Networking** | Bridge, VLAN, macvlan, routable | Bridge (NAT), host, macvlan, ipvlan |
| **Storage** | Bind mounts, mount points, ZFS subvols | Volumes, bind mounts, tmpfs |
| **Isolation** | Kernel namespace + AppArmor | Kernel namespace + seccomp + AppArmor |
| **Snapshot** | Native Proxmox snapshots (ZFS) | Not built-in (need external) |

## Rule of Thumb

**Use LXC when:**
- You need a full-system container (sshd, cron, syslog, traditional Linux app)
- The app expects systemd-level process management
- You want Proxmox-native snapshots and backups
- Network performance matters (direct bridge/VLAN attachment)
- Examples: Frigate NVR, Asterisk, Tailscale exit node, bind9, rsyslog

**Use Docker when:**
- The app is distributed as a Docker image (or you want to build one)
- You need per-container restart policies and health checks
- Reproducibility matters (Compose file = complete config)
- You want to run multiple instances of the same app
- Examples: Cloudflare Tunnel, Immich, Grafana+Prometheus stack, Nginx reverse proxy

## Real Configs

### LXC: Frigate NVR (system container)

A Frigate LXC is a good LXC candidate because it needs:
- Direct `/dev/dri/renderD128` access for VAAPI
- Raw USB or RTSP camera access
- Systemd service management for auto-restart

Create in Proxmox:

```bash
pct create <CTID> local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --storage local-zfs \
  --net0 name=eth0,bridge=vmbr0,vlan=50,ip=dhcp \
  --unprivileged 1 \
  --features nesting=0
```

Inside the CT:

```bash
apt update && apt install -y docker.io docker-compose-v2
```

Wait — this says Docker inside LXC. That's right — if you want Docker **and** you're already in a LXC, you nest Docker inside. Deployment is straightforward through the Proxmox API: create CT, install Docker, `docker compose up`.

### LXC Without Docker: System Services

For system-level services that don't benefit from containerization, skip Docker entirely:

```bash
pct create <CTID> local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --storage local-zfs \
  --net0 name=eth0,bridge=vmbr0,vlan=10,ip=dhcp \
  --unprivileged 1

# Inside: just install the service
pct enter <CTID>
apt update && apt install -y nginx-light bind9
systemctl enable --now nginx
```

Simple, direct, minimal overhead.

### Docker in VM: Heavy Isolation

For multi-tenant or security-sensitive workloads, nest Docker in a full VM:

```yaml
# qm create <VMID> --name docker-host
# Then inside the VM:
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      - TUNNEL_TOKEN=<TUNNEL_TOKEN>
    networks:
      - proxy

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

The VM adds a full kernel (own `overlay`, `iptables`, `br_netfilter` modules) so Docker networking behaves predictably. This is the approach used for Cloudflare Tunnel in this stack.

## Choosing Based on Workload Profile

### Lightweight, Many Instances → Docker

If you need 5+ instances of the same service (e.g., isolated web apps each with their own compose stack), Docker wins. A single LXC with 1GB RAM and 2 cores can run 10-15 Docker containers comfortably.

### Single Heavy Service → LXC (or VM)

For a single service that needs dedicated resources — like a database, media server, or Asterisk — a straight LXC is cleaner. You get standard systemd management, easier debugging (`pct enter`), and native ZFS snapshots for easy rollback.

### The Hybrid Approach

Most Proxmox homelabs settle on a pattern:

```
1 LXC → Docker host (medium, e.g. 4C/8G)
  └── cloudflared, nginx, grafana, telegraf, 5-10 other microservices

1 LXC → Frigate NVR (2C/4G, GPU passthrough)
  └── docker + frigate 

1 LXC → Main services (1C/2G)
  └── bind9, nginx, rsyslog, cron

1 VM → Kubernetes/docker-swarm node (4C/8G)
  └── For learning or production-grade orchestration
```

This keeps the management surface small — you maintain ~4 LXCs/VM instead of 20+ individual machines.

## Quick Start: Docker Host LXC

```bash
CTID=200
pct create $CTID local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --storage local-zfs \
  --cores 4 \
  --memory 8192 \
  --swap 1024 \
  --net0 name=eth0,bridge=vmbr0,vlan=20,ip=dhcp \
  --unprivileged 1 \
  --features keyctl=1,nesting=1

pct start $CTID
pct push $CTID ~/.ssh/id_ed25519.pub /root/.ssh/authorized_keys
ssh root@<CT-IP>

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Test
docker run --rm hello-world
```

Enable `keyctl=1,nesting=1` — without these, Docker inside LXC can't do overlay networks or use kernel keyrings.

## Summary

| Scenario | Pick |
|----------|------|
| Single well-known service (Nginx, Bind, NFS) | LXC |
| Docker-native app (Grafana, Immich, cloudflared) | Docker LXC |
| Multi-app stack with compose | Docker LXC |
| High-security / multi-tenant isolation | VM + Docker |
| GPU passthrough needed | LXC (or VM with PCIe passthrough) |
| Want Proxmox backups & snapshots | LXC |

There's no single right answer. The beauty of Proxmox is that you can mix all three approaches on the same host. Start with what fits the app, and move it later if the constraints change.
