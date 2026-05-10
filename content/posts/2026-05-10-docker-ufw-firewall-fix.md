---
title: "Docker Bypasses UFW — How to Fix Firewall Rules Properly"
description: "Why Docker punches holes in your UFW firewall, the three real solutions in order of preference, and the one approach that actually fixes it without breaking container networking."
date: 2026-05-10T11:00:00-04:00
tags:
  - docker
  - networking
  - firewall
  - ufw
  - security
---

You set up UFW. You configured default deny incoming, opened only ports
22 and 443. You checked `ufw status verbose` — everything looks right.

Then you spin up a Postgres container publishing port 5432, and suddenly
port 5432 is open to the whole internet. Your UFW rules didn't stop it.

This isn't a bug. Docker modifies iptables directly in ways that bypass
user-level firewall tools like UFW. Every `docker run -p` creates a raw
iptables DNAT rule that sits *above* UFW's INPUT chain. The result:
containers are exposed regardless of your UFW policy.

This post covers why this happens and three actual fixes.

---

## Why Docker Ignores UFW

Docker's `dockerd` manages a `DOCKER` chain in iptables. When you publish
a container port, Docker inserts a DNAT rule that translates the host port
to the container IP. The packet flow looks like this:

```
Internet → PREROUTING (DNAT: host:5432 → container:5432)
         → FORWARD (filter rules)
         → container:5432

Notice: UFW's INPUT chain is never reached for forwarded traffic.
```

UFW controls INPUT and FORWARD *user* chains. Docker inserts its nat
rules in PREROUTING, which fires before FORWARD/INPUT filtering. Docker
also opens FORWARD by default via its `DOCKER-USER` chain.

The result: any published port is reachable from any network interface,
including WAN.

---

## Verify the Problem

Check if Docker's iptables rules override UFW:

```bash
# List nat rules — Docker's DNAT entries go in PREROUTING
sudo iptables -t nat -L PREROUTING -n --line-numbers

# Check FORWARD policy — Docker opens it wide
sudo iptables -L FORWARD -n -v

# UFW status — will show active but won't reflect Docker ports
sudo ufw status verbose
```

If you see `Chain FORWARD (policy DROP)` but Docker has added rules accepting
all forwarded traffic from its bridge, that's the hole.

---

## Solution 1: Docker-User Chain (Partial Fix, Simplest)

Docker provides a `DOCKER-USER` chain that fires before Docker's own
`DOCKER` FORWARD rules. You can add restrictions here.

**Block all forwarded traffic except from specific subnets:**

```bash
# Flush default DOCKER-USER rules
sudo iptables -F DOCKER-USER

# Allow only your LAN subnet (adjust to your network)
sudo iptables -I DOCKER-USER -i docker0 -s 10.0.0.0/16 -j ACCEPT
sudo iptables -I DOCKER-USER -i docker0 -s 192.168.0.0/16 -j ACCEPT

# Drop everything else forwarded to Docker
sudo iptables -I DOCKER-USER -i docker0 ! -s 10.0.0.0/16 -j DROP
```

Make these persistent after reboot:

```bash
# Debian/Ubuntu
sudo apt install iptables-persistent
sudo netfilter-persistent save
```

**Limitation:** This only restricts FORWARD chain traffic. Published ports
still appear as DNAT entries visible to the WAN interface on the host.
It's better than nothing but not a proper fix.

---

## Solution 2: Disable Docker's iptables (Drastic, Breaks Swarm/Overlay)

Set this in `/etc/docker/daemon.json`:

```json
{
  "iptables": false,
  "ip6tables": false
}
```

Then restart Docker:

```bash
sudo systemctl restart docker
```

Now Docker won't touch iptables at all. UFW rules apply normally.

**What breaks:**

- Containers can't reach the internet through NAT (no MASQUERADE rule)
- Published ports (`-p 80:80`) won't work — all DNAT rules are gone
- Docker Swarm overlay networks fail
- Inter-container DNS (embedded DNS resolver) may fail
- `docker-compose` networking between services on the same network stops working

This is the sledgehammer approach. Only use it if you're running Docker
in a non-routed development VM where you don't need port publishing.

---

## Solution 3: UFW-Docker Script (The Right Fix)

The `ufw-docker` approach by chaifeng on GitHub gives UFW full control
over Docker's forwarded traffic by inserting UFW rules *after* Docker's
DNAT but before FORWARD accepts everything.

It works by modifying the DOCKER-USER chain to hand control to UFW:

```bash
#!/bin/bash
# /opt/scripts/ufw-docker-fix.sh
# Run once after Docker starts, or add as a systemd override

# Reset DOCKER-USER to UFW-controlled defaults
sudo iptables -F DOCKER-USER
sudo iptables -A DOCKER-USER -j RETURN

# Default: block all forwarded traffic to containers
# unless UFW explicitly allows it
sudo iptables -I DOCKER-USER -i docker0 -j DOCKER-USER-RETURN

# Allow established/related
sudo iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Default deny for DOCKER-USER
sudo iptables -A DOCKER-USER -j DROP
```

But the better approach is to use the `ufw-after-docker` integration.
Install it as a systemd oneshot:

```ini
# /etc/systemd/system/ufw-docker-fix.service
[Unit]
Description=UFW Docker integration fix
After=docker.service network.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/scripts/ufw-docker-fix.sh

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ufw-docker-fix
```

---

## Solution 3b: Per-Port UFW Control (Best for Most Homelabs)

Instead of blanket blocking all Docker forwarded traffic, control it
per-port using UFW rules that match the Docker-proxy binding address.

When Docker publishes a port, it binds to `0.0.0.0:PORT` by default.
The trick is to **only bind to internal IPs**, then use UFW as normal.

**Step 1: Bind containers only to your LAN IP, not 0.0.0.0**

```yaml
# compose.yml
services:
  postgres:
    image: postgres:16
    ports:
      - "10.0.20.50:5432:5432"  # bind to LAN IP only, not 0.0.0.0
```

This means the port is only reachable on the LAN interface. The WAN
interface (public IP) doesn't bind the port, so no DNAT hole exists.

**Step 2: Verify binding**

```bash
sudo ss -tlnp | grep docker
# Should show: 10.0.20.50:5432    (not 0.0.0.0:5432)
```

**Step 3: Use UFW to control LAN access**

```bash
# Allow specific services through
sudo ufw allow from 10.0.0.0/16 to 10.0.20.50 port 5432 proto tcp

# Block everything else
sudo ufw default deny incoming
```

This is the cleanest approach for a homelab environment. You keep Docker's
internal networking intact, override the default `0.0.0.0` bind to
your internal IP, and let UFW handle the rest.

---

## The Catch: Docker's Port Publishing Default

By default, Docker publishes to `0.0.0.0`. This is the root cause.
You can change the default behavior with a daemon config:

```json
{
  "ip": "10.0.20.50"
}
```

This makes `-p 8080:80` bind to `10.0.20.50:8080` instead of
`0.0.0.0:8080`. Any published port without an explicit IP will now
only listen on your LAN interface.

**Important:** This only affects port publishing, not container-internal
networking or Docker bridge connectivity. It's the single config change
that fixes the UFW bypass for most homelabs.

---

## Verification Checklist

After applying any fix:

```bash
# 1. Check that published ports don't expose to 0.0.0.0
sudo ss -tlnp | grep -E 'docker|compose'
# Expect: 10.0.x.x:PORT     not 0.0.0.0:PORT

# 2. Scan from outside your LAN (use a phone hotspot or cloud shell)
# Install nmap and scan your public IP:
# nmap -p 5432,8080 <PUBLIC_IP>

# 3. Check that UFW still blocks what it should
sudo ufw status verbose

# 4. Verify Docker's iptables integration is sane
sudo iptables -L DOCKER-USER -n -v
```

---

## Summary

| Solution | Effort | Keeps Docker NAT | UFW Control | Homelab Recommended |
|----------|--------|-------------------|-------------|---------------------|
| DOCKER-USER FORWARD rules | Low | ✅ | Partial | ⚠️ |
| `iptables: false` | Low | ❌ Breaks | Full | ❌ |
| Bind to LAN IP + UFW | Medium | ✅ | Full | ✅ |
| ufw-docker script | Medium | ✅ | Full | ✅ |

For a typical homelab where containers need internet access but
databases/config dashboards should stay LAN-only, the cleanest fix is:

1. Set `"ip": "10.0.20.50"` in `/etc/docker/daemon.json`
2. Explicitly bind multi-interface services to `0.0.0.0` when needed
3. Add DOCKER-USER FORWARD restrictions as a safety net

Your UFW rules will finally mean what they say.
