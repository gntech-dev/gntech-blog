---
title: "Docker Rootless Mode — Secure Container Runtime for Homelabs"
description: "Run Docker daemon and containers without root privileges — complete setup guide with networking fixes, systemd integration, and Proxmox LXC compatibility."
date: 2026-05-18T14:00:00-04:00
tags:
  - docker
  - security
  - linux
  - homelab
  - containers
keywords:
  - Docker rootless mode setup
  - run Docker without root
  - rootless Docker networking slirp4netns
  - Docker rootless Proxmox LXC
  - userns-remap Docker security
  - Docker rootless systemd socket activation
  - secure container runtime homelab
summary: "Complete guide to running Docker in rootless mode — no root daemon, no privileged containers. Covers installation, networking workarounds, Docker Compose, Proxmox LXC compatibility, and production readiness."
canonical: "https://blog.gntech.me/posts/docker-rootless-mode/"
---

Docker's default installation runs the daemon as root. Every container
you start inherits that privilege model — the container runtime
(`containerd`, `runc`) operates with full root capabilities on the
host. A single container escape, even from a well-configured
container, means the attacker has root on your machine.

Rootless mode changes this. The Docker daemon runs under an
unprivileged user, and all containers use the user's UID namespace
mapping. Container process UID 0 maps to an unprivileged host UID —
typically in the 100000-165536 range. Even a full break-out from the
container yields only that unprivileged user's permissions.

This guide covers everything you need to run Docker rootless in a
homelab: installation, networking, Docker Compose, systemd
integration, Proxmox LXC compatibility, and the real-world trade-offs
you need to understand before switching.

---

## Why Rootless Matters — The Privilege Problem

A standard Docker installation creates these attack vectors:

1. **Daemon socket**: `/var/run/docker.sock` owned by `root:docker`.
   Any user in the `docker` group has effective root access — they
   can mount the host filesystem, spawn privileged containers, and
   escape the namespace model entirely.

2. **Container break-out**: A kernel exploit inside a container
   running as root (UID 0 in the container namespace) gives the
   attacker root on the host because the container's UID 0 is the
   host's UID 0.

3. **Nested containerization**: Running Docker inside an LXC
   container on Proxmox typically requires a privileged container.
   If Docker runs as root inside a privileged LXC, the LXC's root is
   the host's root — one layer of isolation gone.

Rootless mode solves all three:

- The daemon runs as a non-root user — no root-owned socket.
- Container UID 0 maps to an unprivileged UID on the host.
- You can run Docker inside an unprivileged LXC container with no
  special permissions.

---

## How Rootless Mode Works

Rootless mode uses several Linux kernel features working together:

```
┌────────────────────────────────────────┐
│           Host (root user)             │
│  ┌──────────────────────────────────┐  │
│  │  dockerd (user: dockeruser)      │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │  rootlesskit               │  │  │
│  │  │  ┌──────────────────────┐  │  │  │
│  │  │  │  containerd          │  │  │  │
│  │  │  │  ┌────────────────┐  │  │  │  │
│  │  │  │  │  runc          │  │  │  │  │
│  │  │  │  │  (newuidmap)   │  │  │  │  │
│  │  │  │  │  UID: 100001   │  │  │  │  │
│  │  │  │  └────────────────┘  │  │  │  │
│  │  │  └──────────────────────┘  │  │  │
│  │  └────────────────────────────┘  │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

- **rootlesskit** — Reimplements network, mount, and PID namespaces
  without root. It uses `newuidmap`/`newgidmap` to create user
  namespaces with sub-UID/GID ranges.
- **slirp4netns** or **pasta** — Provides network connectivity from
  the user namespace to the host network without root. Traffic exits
  through a TAP device in a separate network namespace.
- **sub-UID/GID ranges** — The Linux kernel's user namespace support
  maps container UID 0 to an unprivileged host UID (e.g., 100000).
  `/etc/subuid` and `/etc/subgid` define these ranges.

The result: every containerized process runs under an unprivileged
UID on the host. `ps aux` inside the container shows UID 0, but
`ps aux` on the host shows the mapped unprivileged UID.

---

## Prerequisites

Rootless mode requires specific kernel features and tools:

### Kernel Requirements

```bash
# Verify user namespace support
uname -r
# Need 4.18+ (5.x recommended)

# Check user namespace is enabled
cat /proc/sys/kernel/unprivileged_userns_clone
# Should output: 1

# If missing (Ubuntu), enable it:
echo 'kernel.unprivileged_userns_clone=1' \
  | sudo tee /etc/sysctl.d/99-userns.conf
sudo sysctl --system
```

### Required Packages

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y \
  uidmap \
  dbus-user-session \
  slirp4netns \
  fuse-overlayfs

# Verify sub-UID/GID ranges exist
grep ^$(whoami): /etc/subuid
grep ^$(whoami): /etc/subgid
# Output: username:100000:65536
```

The `uidmap` package provides `newuidmap` and `newgidmap` — the
setuid helpers that create user namespaces. Without them, rootless
mode cannot map UIDs.

### Docker Version

```bash
docker --version
# Need Docker 20.10+ for rootless mode
# Docker 24.x and 25.x have the most stable rootless support
```

---

## Installation — Rootless Mode

Do NOT install Docker rootless via `apt`. The distro package installs
a rootful daemon. Use Docker's official rootless installer instead.

### Method 1: Clean Install (No Existing Docker)

```bash
# Remove any existing Docker packages
sudo apt remove -y docker docker-engine docker.io containerd runc
sudo apt autoremove -y

# Download and run the rootless installer
curl -fsSL https://get.docker.com/rootless | sh
```

The installer:
1. Downloads the Docker static binaries
2. Sets up `~/.config/systemd/user/docker.service`
3. Configures environment in `~/.bashrc`
4. Starts the rootless daemon via systemd --user

After install, log out and back in, or source the env:

```bash
source ~/.bashrc
docker info --format '{{.SecurityOptions}}'
# Expected: [name=rootless]
```

### Method 2: Alongside Rootful Docker

If you already have rootful Docker and want both running:

```bash
# Stop rootful daemon
sudo systemctl stop docker.service docker.socket
sudo systemctl disable docker.service docker.socket

# Install rootless as described above
curl -fsSL https://get.docker.com/rootless | sh

# Switch between them (rootless is default after install)
# To go back to rootful temporarily:
sudo systemctl start docker
systemctl --user stop docker
```

### Method 3: Migrate from Rootful

This is the most common scenario for homelabs:

```bash
# 1. Backup Docker data
sudo tar czf ~/docker-rootful-backup.tar.gz /var/lib/docker

# 2. Stop and disable rootful Docker
sudo systemctl stop docker.socket docker
sudo systemctl disable docker.socket docker
sudo rm -f /var/run/docker.sock

# 3. Install rootless
curl -fsSL https://get.docker.com/rootless | sh
source ~/.bashrc

# 4. Verify
docker info --format '{{.SecurityOptions}}'
docker run hello-world
```

---

## Post-Installation Setup and Validation

### Verify Rootless Status

```bash
# Check the daemon is running without root
docker info | grep -i rootless
# Security Options: name=rootless

# Verify container processes run as non-root
docker run --rm alpine ps aux
# PID   USER     TIME   COMMAND
#     1 root      0:00 ps aux
# (Inside the container it shows root, but on the host...)

# On the host, find the container PID
CONTAINER_ID=$(docker run -d alpine sleep 60)
HOST_PID=$(docker inspect $CONTAINER_ID \
  --format '{{.State.Pid}}')
ps -o uid,pid,comm -p $HOST_PID
#   UID    PID COMMAND
# 100001  12345 sleep
# UID 100001 = mapped unprivileged user, NOT root (0)
```

### Environment Setup

The rootless installer adds this to `~/.bashrc`. Verify it:

```bash
grep docker ~/.bashrc
# export PATH=/home/youruser/bin:$PATH
# export DOCKER_HOST=unix:///run/user/1000/docker.sock
```

If SSH-ing into the machine, ensure `XDG_RUNTIME_DIR` is set:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

Add it to `~/.profile` for SSH sessions:

```bash
echo "export XDG_RUNTIME_DIR=/run/user/$(id -u)" >> ~/.profile
```

---

## Networking — The Biggest Difference

This is where rootless mode differs most from rootful Docker. In
rootless mode, containers cannot directly use host networking
(`--network host`) or expose ports on privileged ports (< 1024).

### Default Network: slirp4netns

Rootless containers use `slirp4netns` by default, which creates a
userspace TCP/IP stack:

```bash
# Does NOT work in rootless mode
docker run --network host nginx

# Works — port mapping through slirp4netns
docker run -d -p 8080:80 nginx
# Container's port 80 is reachable on host port 8080
# Performance: ~80% of native throughput
```

**Limitations:**
- No ICMP (no `ping` inside containers)
- No `--network host`
- No multicast or broadcast
- Throughput is lower than bridge networking
- Connection tracking is per-connection (higher latency)

### Pasta — The slirp4netns Replacement

Docker 25+ supports `pasta` (from the passt project), which performs
better than slirp4netns:

```bash
# Install pasta
sudo apt install -y passt

# Configure Docker rootless to use pasta
mkdir -p ~/.config/docker
cat > ~/.config/docker/daemon.json <<'EOF'
{
  "rootless": true,
  "experimental": true,
  "network": "pasta"
}
EOF

# Restart rootless daemon
systemctl --user restart docker
```

Pasta provides:
- Near-native throughput (~95%)
- Better port forwarding performance
- Reduced CPU overhead
- Still no `--network host` or ICMP

Benchmark comparison:

```bash
# Test throughput with iperf3 (rootful vs rootless)
# Rootful bridge:     ~940 Mbps (near line rate)
# Rootless slirp4netns: ~750 Mbps
# Rootless pasta:     ~890 Mbps
# Rootless host ns:   not available (skips this test)
```

### Exposing Ports Below 1024

By default, rootless cannot bind to ports below 1024. Three workarounds:

**A) authbind** — Grant a user permission to bind low ports:

```bash
sudo apt install -y authbind
sudo touch /etc/authbind/byport/80
sudo touch /etc/authbind/byport/443
sudo chown $USER:$USER /etc/authbind/byport/80
sudo chown $USER:$USER /etc/authbind/byport/443
sudo chmod 755 /etc/authbind/byport/80
sudo chmod 755 /etc/authbind/byport/443
```

Then configure Docker to use authbind (requires patching the
rootlesskit start script — not recommended).

**B) Proxy redirect — iptables REDIRECT on the host (recommended):**

```bash
# Redirect host port 80 to 8080 (where container listens)
sudo iptables -t nat -A PREROUTING \
  -p tcp --dport 80 -j REDIRECT --to-port 8080

sudo iptables -t nat -A PREROUTING \
  -p tcp --dport 443 -j REDIRECT --to-port 8443
```

Add to a systemd oneshot service for persistence:

```bash
# /etc/systemd/system/port-redirect.service
[Unit]
Description=Redirect privileged ports to unprivileged
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/iptables -t nat -A PREROUTING \
  -p tcp --dport 80 -j REDIRECT --to-port 8080
ExecStart=/usr/sbin/iptables -t nat -A PREROUTING \
  -p tcp --dport 443 -j REDIRECT --to-port 8443
RemainAfterExit=true
ExecStop=/usr/sbin/iptables -t nat -D PREROUTING \
  -p tcp --dport 80 -j REDIRECT --to-port 8080
ExecStop=/usr/sbin/iptables -t nat -D PREROUTING \
  -p tcp --dport 443 -j REDIRECT --to-port 8443

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now port-redirect.service
```

**C) Reverse proxy with CAP_NET_BIND_SERVICE:**

Run a reverse proxy (Caddy, Traefik, Nginx) in a rootful Docker with
only `CAP_NET_BIND_SERVICE` to bind low ports, then proxy to rootless
containers on high ports:

```bash
# Run Caddy as rootful container with minimal capability
docker run -d \
  --name caddy \
  --cap-add=NET_BIND_SERVICE \
  -p 80:80 \
  -p 443:443 \
  -v ./Caddyfile:/etc/caddy/Caddyfile \
  caddy:latest

# Caddyfile
example.com {
  reverse_proxy localhost:8080
}
```

Option B (iptables redirect) is the simplest for homelabs and does
not require any additional containers.

---

## Docker Compose with Rootless

Docker Compose works out of the box with rootless mode. No special
configuration needed.

```bash
# Install Compose plugin for rootless
# (typically already included with the Docker binaries)
docker compose version
# Docker Compose version v2.32.0

# Use it exactly as you would with rootful
mkdir -p ~/services/nginx
cat > ~/services/nginx/compose.yaml <<'EOF'
services:
  web:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./html:/usr/share/nginx/html:ro
EOF

docker compose -f ~/services/nginx/compose.yaml up -d
```

### Compose Rootful vs Rootless Differences

| Feature | Rootful | Rootless |
|---------|---------|----------|
| Port bindings < 1024 | Yes | No (use redirect) |
| `network_mode: host` | Yes | No |
| `volumes` with host paths | Full access | User-owned paths only |
| `privileged: true` | Yes | Ignored (no effect) |
| `cap_add` | All capabilities | Limited to user-ns-safe caps |

### Volume Mounts — User Permission Model

Rootless Docker can only mount directories the user owns or has
permission to read. If your compose file references `/var/log` or
`/etc/nginx`, those mounts will fail:

```bash
# This works — files in the user's home
services:
  app:
    image: nginx
    volumes:
      - ~/nginx/html:/usr/share/nginx/html

# This fails — root-owned path
services:
  app:
    image: nginx
    volumes:
      - /etc/nginx:/etc/nginx  # Permission denied
```

Fix by copying files into your home directory or creating a symlink
farm with bind mounts from a rootful service.

---

## Systemd Integration — User Services

Rootless Docker runs as a systemd user service. This is critical for
homelab uptime — it must survive reboots and SSH session closures.

### Enable linger for the Docker user

```bash
# Keeps the user's systemd instance running even after logout
sudo loginctl enable-linger $USER

# Verify
loginctl show-user $USER | grep Linger
# Linger=yes
```

### Verify the docker service starts at boot

```bash
systemctl --user status docker
# ● docker.service - Docker Application Container Engine (Rootless)
#    Loaded: loaded ...
#    Active: active (running)

# Enable autostart (should already be enabled by installer)
systemctl --user enable docker
systemctl --user start docker
```

### Running Custom Containers as Systemd User Services

Each container can run as its own systemd unit with automatic restart:

```bash
# Create a service template
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/container-nginx.service <<'EOF'
[Unit]
Description=Nginx container (rootless)
After=docker.service
Requires=docker.service

[Service]
ExecStartPre=-/usr/bin/docker rm -f nginx-rootless
ExecStart=/usr/bin/docker run --rm --name nginx-rootless \
  -p 8080:80 \
  -v %h/nginx/html:/usr/share/nginx/html:ro \
  nginx:alpine
ExecStop=/usr/bin/docker stop nginx-rootless
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now container-nginx
```

---

## Running Rootless Docker Inside Proxmox LXC

This is where rootless mode shines for homelabs. Instead of creating
a full VM for Docker (which wastes RAM on a kernel and init), you can
run rootless Docker inside an unprivileged LXC container.

### LXC Container Configuration

Create the container on Proxmox with these settings:

```bash
# Create unprivileged container
pct create 300 local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst \
  --unprivileged 1 \
  --nesting 1 \
  --features keyctl=1,nesting=1 \
  --storage local-zfs \
  --cores 4 \
  --memory 8192 \
  --swap 0 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp

pct start 300
pct enter 300
```

### Inside the LXC — Install Rootless Docker

```bash
# Inside the LXC
apt update
apt install -y curl uidmap slirp4netns fuse-overlayfs
curl -fsSL https://get.docker.com/rootless | sh
```

### Important: Sub-UID/GID Ranges Inside LXC

Unprivileged LXC containers have their own UID mapping. The container
itself is mapped to a sub-UID range on the Proxmox host (e.g.,
UID 100000 on the host = UID 0 inside the container). Nested Docker
rootless maps AGAIN from that range.

This means a container process has these UID translations:

```
Docker container UID 0
  → LXC container UID 100000 (via LXC's subuid mapping)
    → Proxmox host UID 101000 (typical nested mapping)
```

This triple-nesting is safe and works reliably when:
- The LXC container is unprivileged
- `/etc/subuid` and `/etc/subgid` inside the LXC have enough range
  (65536 minimum)
- `kernel.keys.maxkeys` is set high enough inside the LXC

```bash
# Inside the LXC — verify subuid range
grep ^$(whoami): /etc/subuid
# username:100000:65536

# Increase kernel key limits inside the LXC
cat >> /etc/sysctl.d/99-docker-rootless.conf <<'EOF'
kernel.keys.maxkeys=2000
kernel.keys.maxbytes=250000
EOF
sysctl --system
```

---

## Monitoring and Maintenance

### Logging

Rootless Docker logs go to the user's systemd journal:

```bash
# View daemon logs
journalctl --user -u docker -f

# View a specific container logs
docker logs -f container_name
```

### Updates

Update the rootless binaries when Docker releases a new version:

```bash
# Re-run the installer — it updates in place
curl -fsSL https://get.docker.com/rootless | sh

# Or update via the static binaries directly
docker update --help | grep update
# (There is no built-in updater — re-run the installer)
```

### Backup

The rootless Docker data directory is at `~/.local/share/docker/`:

```bash
# Backup volumes and container data
tar czf ~/docker-rootless-backup-$(date +%F).tar.gz \
  ~/.local/share/docker/

# This is your equivalent of /var/lib/docker/
# Restore:
# tar xzf backup.tar.gz -C ~/.local/share/docker/
```

---

## Common Issues and Fixes

### "Failed to connect to bus" or "XDG_RUNTIME_DIR not set"

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
```

Add both to `~/.profile` for persistence.

### "newuidmap: write to uid_map failed: Operation not permitted"

The sub-UID/GID ranges are missing or misconfigured:

```bash
# Check ranges
cat /etc/subuid
cat /etc/subgid

# Fix (requires root)
sudo usermod --add-subuids 100000-165535 $USER
sudo usermod --add-subgids 100000-165535 $USER
```

### "overlayfs: missing upperdir" or overlay not supported

Rootless Docker prefers `fuse-overlayfs` when the kernel's overlay
in user namespace is not available:

```bash
# Install fuse-overlayfs
sudo apt install -y fuse-overlayfs

# Configure Docker to use it
mkdir -p ~/.config/docker
cat > ~/.config/docker/daemon.json <<'EOF'
{
  "storage-driver": "fuse-overlayfs"
}
EOF
systemctl --user restart docker
```

### Container Cannot Write to Mounted Host Directory

The container UID inside the user namespace (e.g., UID 100001 on
host) must own the host directory:

```bash
# Find the mapped host UID for container user
# In most rootless setups, container UID 0 = host UID 100000

# Fix — change directory ownership to the mapped UID
sudo chown -R 100000:100000 ~/service-data/
```

Or use `podman`-style subuid mount options (Docker 25+):

```yaml
# compose.yaml — use :U flag for automatic chown
services:
  app:
    image: nginx
    volumes:
      - ./data:/data:U
```

---

## Trade-offs — When Not to Use Rootless

Rootless mode is not always the right choice:

| Scenario | Recommendation |
|----------|---------------|
| Single-user homelab, no untrusted services | Rootless is fine, adds defense-in-depth |
| Running Docker in an LXC on Proxmox | **Rootless strongly recommended** — avoids privileged LXC |
| Need `--network host` for performance | Rootless cannot do this. Use rootful or use pasta |
| Need ICMP/ping inside containers | Rootless cannot provide this |
| Services must bind port 80/443 directly | Use iptables redirect or reverse proxy |
| GPU passthrough to containers | Rootless adds complexity with `/dev/dri` access |
| Full production with strict SLAs | Evaluate carefully — rootless has higher overhead |

For most homelab use cases — where you run a reverse proxy on one
port and web services on high ports behind it — the trade-offs are
minimal. The security benefit of removing root from the container
runtime is worth the networking compromises.

---

## Summary

Docker rootless mode eliminates the largest security risk of
containerization — the root-privileged daemon and the `docker` group
backdoor. The installation is a single command:

```bash
curl -fsSL https://get.docker.com/rootless | sh
```

Key takeaways:

- **Security**: Daemon and containers run under an unprivileged UID.
  Container break-outs yield a non-root user, not host root.
- **Networking**: Use pasta for near-native throughput. Redirect
  privileged ports with iptables. Accept the loss of `--network host`
  and ICMP.
- **Proxmox**: Rootless Docker inside an unprivileged LXC is the most
  resource-efficient and secure Docker hosting pattern on Proxmox.
- **Systemd**: Enable linger, verify the user service autostarts, and
  optionally wrap critical containers as systemd user services.

Rootless mode converts Docker from "root with extra steps" to a
genuinely sandboxed container runtime. For a homelab where security
matters — and it should — the transition takes ten minutes and pays
dividends in reduced attack surface.
