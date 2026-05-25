---
title: "WireGuard VPN on Proxmox — LXC Setup Guide for Homelab Remote Access"
description: "Complete step-by-step guide to deploying WireGuard VPN in a Proxmox LXC container — lightweight setup with persistent config, client management, firewall rules, and routing for secure homelab remote access."
date: 2026-05-25T07:00:00-04:00
tags:
  - wireguard
  - vpn
  - proxmox
  - linux
  - networking
  - homelab
  - security
keywords:
  - WireGuard VPN Proxmox LXC container deployment
  - Proxmox WireGuard setup guide step-by-step
  - WireGuard LXC persistent configuration iptables NAT
  - WireGuard client management QR code wg-gen-web
  - Proxmox VPN container firewall port forwarding
  - WireGuard remote access homelab MikroTik
  - WireGuard kernel module nested container LXC
summary: "Deploy a lightweight WireGuard VPN server in a Proxmox LXC container — configure persistent tunnels, NAT routing, client generation, and firewall rules for secure remote access to your entire homelab network."
canonical: "https://gntech.dev/posts/wireguard-vpn-proxmox-lxc/"
---

You SSH into your homelab from a coffee shop, manage Proxmox
from your phone on cellular data, or need access to a dashboard
while traveling. A WireGuard VPN is the simplest, fastest, and
most secure way to reach your internal services without exposing
them to the public internet.

WireGuard lives inside the Linux kernel. On Proxmox, you can run
it in a lightweight LXC container that consumes ~64 MB of RAM and
practically zero CPU when idle. No VM overhead. No heavyweight
OpenSSL configuration. One UDP port, three config files, and
you're connected.

This guide covers the full deployment: creating a Debian 12 LXC,
installing WireGuard, configuring the server with NAT for homelab
routing, generating client configs, setting up persistence across
reboots, and securing the stack with firewall rules and a MikroTik
port forward.

---

## Why WireGuard in an LXC Instead of a VM

WireGuard runs natively in the Linux kernel. An LXC container
shares the host kernel, which means WireGuard kernel modules are
available without any extra work. The resource profile is
dramatically smaller than a VM:

| Approach          | RAM     | Disk   | Boot time | Complexity |
|-------------------|---------|--------|-----------|------------|
| WireGuard in LXC  | 64-128MB | 2 GB   | ~3 sec  | Low        |
| WireGuard in VM   | 512+ MB  | 8+ GB  | ~20 sec | Medium     |
| WireGuard on host | 0        | 0      | Instant  | High risk  |

Running WireGuard directly on the Proxmox host is possible but
frowned upon — it mixes host networking with VPN routing, and a
configuration mistake can lock you out of the host entirely. The
LXC approach isolates the VPN into its own network namespace, so
a misconfigured WireGuard tunnel never touches the Proxmox host.

The only caveat: LXC containers need a privileged container with
the `tun` device and the `wireguard` kernel module available. We
configure this during the container creation step.

---

## Step 1: Create the Debian 12 LXC Container

Create a new container in Proxmox or from the CLI. Privileged mode
is required because WireGuard needs access to create the `tun`
interface and set iptables rules.

```bash
# Create the container (adjust storage ID and bridge as needed)
pct create 200 \
  local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --storage local-zfs \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp,firewall=1 \
  --ostype debian \
  --arch amd64 \
  --cores 1 \
  --memory 128 \
  --swap 0 \
  --hostname wireguard \
  --unprivileged 0 \
  --features keyctl=1,nesting=1,fuse=1

# Start the container
pct start 200

# Enter the shell
pct enter 200
```

**What each flag does:**

- `--unprivileged 0` — Creates a privileged container, required
  for WireGuard to create kernel interfaces
- `--features keyctl=1,nesting=1` — Enables kernel key retention
  (used by WireGuard internally) and container nesting
- `--memory 128 --swap 0` — WireGuard needs almost no RAM; 128 MB
  is generous
- `firewall=1` on the network interface enables Proxmox's
  built-in firewall for this container

After entering the container, update the system:

```bash
apt update && apt upgrade -y
apt install -y curl gnupg wireguard-tools iptables resolvconf
```

Verify the WireGuard kernel module is available:

```bash
modprobe wireguard
lsmod | grep wireguard

# Output should show the module loaded
# wireguard           126976  0
# ip6_udp_tunnel      16384  1 wireguard
# udp_tunnel          32768  1 wireguard
```

If `modprobe wireguard` fails, the module may need to be loaded
on the Proxmox host first. Exit the container (`exit`) and run:

```bash
# On the Proxmox host
modprobe wireguard
echo "wireguard" >> /etc/modules
pct push 200 /etc/modules /etc/modules
```

Then re-enter and verify again.

---

## Step 2: Server Configuration

Generate the server key pair inside the container:

```bash
cd /etc/wireguard
umask 077
wg genkey | tee server.key | wg pubkey > server.pub
chmod 600 server.key server.pub
```

Create the server config at `/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = $(cat /etc/wireguard/server.key)
Address = 10.10.10.1/24
ListenPort = 51820

# NAT traffic to the homelab network
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -o wg0 -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -o wg0 -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Optional: DNS pushed to clients
# (use your internal DNS resolver IP here)
DNS = 10.0.20.10

# Enable routing
IPForward = yes
```

Enable IP forwarding on the container:

```bash
echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf
echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.conf
sysctl -p
```

**Explanation of the routing:**
- `Address = 10.10.10.1/24` — This is the VPN subnet. Clients
  get IPs in this range.
- The `PostUp` iptables rules forward VPN traffic to eth0
  (your homelab network) and apply NAT masquerade so responses
  route back through the container.
- `IPForward = yes` — Required for the kernel to route traffic
  between wg0 and eth0.

Without the NAT masquerade, clients could reach the container
but not other hosts on your homelab (10.0.20.0/24 in this
example). The masquerade rewrites the source IP to the
container's eth0 address, making replies reachable.

---

## Step 3: Add a Client

Client configs follow the same key generation pattern. Inside
the container:

```bash
# Generate client keys
cd /etc/wireguard
wg genkey | tee laptop.key | wg pubkey > laptop.pub
chmod 600 laptop.key laptop.pub
```

Append the client peer to the server config:

```bash
cat >> /etc/wireguard/wg0.conf << 'EOF'

[Peer]
# laptop
PublicKey = $(cat /etc/wireguard/laptop.pub)
AllowedIPs = 10.10.10.2/32
EOF
```

Now substitute the actual public key by writing it directly:

```bash
cat >> /etc/wireguard/wg0.conf << EOF

[Peer]
# laptop
PublicKey = $(cat /etc/wireguard/laptop.pub)
AllowedIPs = 10.10.10.2/32
EOF
```

**Repeat for each client.** Use a new `/32` address per client.
Keep a mapping file:

```bash
cat > /etc/wireguard/clients.txt << 'EOF'
# Client          IP              Public key
# laptop          10.10.10.2      <key>
# phone           10.10.10.3      <key>
# tablet          10.10.10.4      <key>
# server-remote   10.10.10.10     <key>
EOF
```

Generate the client config file to import on the client device:

```bash
# Generate client wg config
cat > /etc/wireguard/laptop.conf << EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/laptop.key)
Address = 10.10.10.2/32
DNS = 10.0.20.10

[Peer]
PublicKey = $(cat /etc/wireguard/server.pub)
Endpoint = vpn.gntech.dev:51820
AllowedIPs = 10.0.20.0/24, 10.10.10.0/24
PersistentKeepalive = 25
EOF
```

**Key details in the client config:**
- `Endpoint` — Your public-facing hostname or IP, plus the UDP
  port 51820
- `AllowedIPs` — Which networks route through the VPN. Include
  your homelab subnet (`10.0.20.0/24`) and the VPN subnet
  itself (`10.10.10.0/24`). Add `0.0.0.0/0` for full-tunnel
  (all traffic routes through home)
- `PersistentKeepalive = 25` — Sends a keepalive every 25
  seconds, essential for NAT traversal if your client is behind
  a carrier-grade NAT

For quick client deployment, generate a QR code:

```bash
apt install -y qrencode
qrencode -t ansiutf8 < /etc/wireguard/laptop.conf
```

Scan this directly with the WireGuard mobile app — no file
transfer needed.

---

## Step 4: Enable and Start the Tunnel

```bash
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
systemctl status wg-quick@wg0

# Verify the interface is up
wg show

# Output should look like:
# interface: wg0
#   public key: <server public key>
#   private key: (hidden)
#   listening port: 51820
#
# peer: <laptop public key>
#   endpoint: <client public IP>:<ephemeral port>
#   allowed ips: 10.10.10.2/32
#   transfer: 1.23 KiB received, 4.56 KiB sent
```

Verify routing works:

```bash
# From the container, ping a client (not connected yet)
# From a connected client, ping the homelab
# Internal homelab host
ping 10.0.20.1
ping 10.0.20.30  # Proxmox host
```

---

## Step 5: Firewall and Port Forwarding

WireGuard listens on UDP 51820. You need to forward this port
from your edge router to the LXC container's IP address.

### MikroTik Port Forward

If your edge router is MikroTik (like the GnTech homelab):

```bash
/ip firewall nat
add chain=dstnat \
  protocol=udp \
  dst-port=51820 \
  action=dst-nat \
  to-addresses=10.0.20.200 \
  to-ports=51820 \
  comment="WireGuard VPN"

/ip firewall filter
add chain=input \
  protocol=udp \
  dst-port=51820 \
  action=accept \
  comment="Allow WireGuard"
```

### UFW Inside the Container

If you use UFW inside the LXC:

```bash
ufw allow 51820/udp comment "WireGuard VPN"
ufw reload
```

### Proxmox Firewall (if enabled)

```bash
# On Proxmox host
pct set 200 --net0 name=eth0,bridge=vmbr0,ip=dhcp,firewall=1

# Create/append firewall rules for CT 200
cat > /etc/pve/firewall/200.fw << 'EOF'
[IN]
DROP
LOG_INVALID

[INET]
ACCEPT udp dport 51820
ACCEPT icmp
EOF
```

---

## Step 6: iptables Persistence

WireGuard's `wg-quick` runs the PostUp/PostDown rules when the
interface comes up, but if the container reboots and iptables
rules get flushed before wg-quick starts, there's a brief gap.
Install iptables-persistent to lock in the forwarding rules:

```bash
apt install -y iptables-persistent
```

During installation it will prompt to save current rules. Answer
yes, or save manually after:

```bash
iptables-save > /etc/iptables/rules.v4
ip6tables-save > /etc/iptables/rules.v6
```

This ensures the container can still forward packets even if
wg-quick hasn't started yet on boot.

---

## Step 7: Managing Clients at Scale

For more than 3-4 clients, managing individual key files gets
tedious. Two options:

### Option A: wg-gen-web (Web UI)

Deploy [wg-gen-web](https://github.com/vx3r/wg-gen-web) in a
separate container or via Docker. It provides a clean web UI
for adding/removing clients and generates QR codes.

```bash
# Docker compose for wg-gen-web
docker run -d \
  --name wg-gen-web \
  -p 8080:8080 \
  -v /etc/wireguard:/data \
  -e WG_INTERFACE=wg0 \
  vx3r/wg-gen-web:latest
```

**Security note:** Do not expose this to the internet. Access it
through your WireGuard VPN or a Tailscale/ZeroTier connection.

### Option B: Scripted Client Creation

A simple bash wrapper for client management:

```bash
#!/bin/bash
# /usr/local/bin/wg-add-client.sh
# Usage: wg-add-client.sh <client-name> <vpn-ip>

CLIENT=$1
IP=$2

cd /etc/wireguard || exit 1

# Generate keys
wg genkey | tee "${CLIENT}.key" | wg pubkey > "${CLIENT}.pub"
chmod 600 "${CLIENT}.key" "${CLIENT}.pub"

# Add to server config
cat >> wg0.conf << EOF

[Peer]
# ${CLIENT}
PublicKey = $(cat "${CLIENT}.pub")
AllowedIPs = ${IP}/32
EOF

# Generate client config
cat > "${CLIENT}.conf" << EOF
[Interface]
PrivateKey = $(cat "${CLIENT}.key")
Address = ${IP}/32
DNS = 10.0.20.10

[Peer]
PublicKey = $(cat server.pub)
Endpoint = vpn.gntech.dev:51820
AllowedIPs = 10.0.20.0/24, 10.10.10.0/24
PersistentKeepalive = 25
EOF

# Reload WireGuard
wg syncconf wg0 <(wg-quick strip wg0)

echo "Client ${CLIENT} created at ${IP}"
echo "Config: /etc/wireguard/${CLIENT}.conf"
qrencode -t ansiutf8 < "${CLIENT}.conf"
```

Usage:

```bash
chmod +x /usr/local/bin/wg-add-client.sh
/usr/local/bin/wg-add-client.sh phone 10.10.10.3
```

---

## Step 8: Testing and Verification

From a connected client, run these checks:

```bash
# Check the tunnel is up
ping 10.10.10.1

# Verify LAN access (your internal Proxmox host or a service)
curl -I https://10.0.20.30:8006  # Proxmox web UI

# Verify DNS resolves through your internal server
nslookup pihole.lan

# Check transfer stats
wg show
```

Back on the server, monitor connections:

```bash
# Watch live WireGuard peers
watch -n 2 wg show

# Check handshake timing — a recent handshake (< 2 min) means
# the client is actively connected
# Check iptables NAT counters
iptables -t nat -L POSTROUTING -v -n
```

If a client can reach the container but not other LAN hosts:

```bash
# Verify IP forwarding on the container
sysctl net.ipv4.ip_forward
# Should return 1

# Check iptables FORWARD chain — ensure it's not set to DROP
iptables -L FORWARD -v -n

# If FORWARD policy is DROP, add explicit ACCEPT rules
iptables -I FORWARD 1 -i wg0 -j ACCEPT
iptables -I FORWARD 1 -o wg0 -j ACCEPT
```

---

## Performance Tuning

WireGuard is already fast — kernel-mode encryption with ChaCha20
and Poly1305 is hardware-accelerated on modern x86_64 and ARM
CPUs. But a few tweaks apply in the LXC context:

### MTU

The default WireGuard MTU of 1420 is conservative. If your
homelab has jumbo frame support (MTU 9000 on internal links),
you can increase the tunnel MTU:

```ini
[Interface]
PrivateKey = ...
Address = 10.10.10.1/24
MTU = 1500  # Up from 1420 default
ListenPort = 51820
```

Calculate MTU as physical MTU minus 80 bytes (60 IP/UDP header
+ 20 WireGuard overhead). For 9000 MTU internal networks,
8920 works.

### CPU Pinning

If you have many simultaneous VPN clients or high-throughput
transfers, pin the container to a specific core:

```bash
# On Proxmox host
echo "0" > /sys/fs/cgroup/cpuset/lxc/200/cpuset.cpus
```

Or in the container config (`/etc/pve/lxc/200.conf`):

```text
lxc.cgroup2.cpuset.cpus: 0
lxc.cgroup2.cpuset.mems: 0
```

### Kernel Module Verification

When WireGuard appears slow, verify you're using the kernel
module, not the userspace Go implementation:

```bash
# Check which implementation is loaded
lsmod | grep wireguard
# If the module isn't loaded, wg-quick falls back to
# boringtun (a userspace implementation) which is 2-3x slower

# Force kernel module
modprobe wireguard
```

---

## Backing Up the WireGuard Config

The entire WireGuard state lives in `/etc/wireguard/`. On a
Proxmox host, back this up from the host side:

```bash
# Copy config out of the container for backup
pct pull 200 /etc/wireguard /backup/wireguard-$(date +%F)

# Or use a cron job inside the container
cat > /etc/cron.daily/wireguard-backup << 'SCRIPT'
#!/bin/bash
tar czf "/root/wireguard-backup-$(date +%F).tar.gz" /etc/wireguard/
find /root/ -name "wireguard-*.tar.gz" -mtime +30 -delete
SCRIPT
chmod +x /etc/cron.daily/wireguard-backup
```

If you ever need to restore, just copy the configs back and
restart:

```bash
systemctl restart wg-quick@wg0
```

---

## Summary

WireGuard in a Proxmox LXC is the ideal VPN solution for
homelab remote access:

1. **Create a privileged Debian 12 LXC** with 128 MB RAM —
   smaller than any VM alternative
2. **Configure WireGuard** with key-based authentication, NAT
   masquerade, and the VPN subnet `10.10.10.0/24`
3. **Set up clients** with minimal config files or QR codes —
   no client software needed beyond the official WireGuard apps
4. **Forward UDP port 51820** from your edge router (MikroTik,
   OPNsense, or consumer router) to the LXC IP
5. **Enable IP forwarding and iptables persistence** for reliable
   routing across reboots

The result: secure, wire-speed access to your entire homelab
from any device, anywhere, with under 30 minutes of setup time.
No public-facing dashboards, no VPN appliance VMs, no
subscription fees — just a container, a config, and a fast UDP
tunnel.
