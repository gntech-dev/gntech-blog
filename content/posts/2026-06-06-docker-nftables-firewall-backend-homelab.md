---
title: "Docker nftables Firewall Backend — Native Firewall for Containers"
description: "Migrate Docker from iptables to nftables with the native firewall backend. Configure, verify, and troubleshoot Docker nftables support on Debian 13 and Ubuntu 24.04 homelab hosts."
date: 2026-06-06T21:00:00+00:00
tags:
  - docker
  - firewall
  - networking
  - linux
  - security
keywords:
  - Docker nftables firewall backend configuration homelab guide
  - Migrate Docker iptables to nftables native Debian 13
  - Docker Engine 29 nftables experimental firewall setup
  - Docker nftables port publishing NAT rules troubleshooting
  - Linux nftables firewall Docker container isolation best practices
  - Docker daemon.json nftables backend configuration file
  - Debian 13 iptables-nft compatibility Docker networking fix
summary: "Migrate Docker from iptables to the native nftables firewall backend. Configure docker daemon.json for nftables on Debian 13, test port publishing, and troubleshoot common migration issues."
canonical: "https://blog.gntech.me/posts/docker-nftables-firewall-backend-homelab/"
---

## Why nftables Matters for Docker Homelabs

If you've deployed Debian 13 "Trixie" or Ubuntu 24.04 in your homelab recently, your system already runs **nftables** as the default firewall framework. These distros ship without iptables-legacy support in the default kernel. Docker, however, still defaults to managing iptables rules — even if what's actually running under the hood is `iptables-nft`, a compatibility shim that translates iptables commands into nftables bytecode.

This hybrid setup works most of the time, until it doesn't. The translation layer introduces subtle failures:

- **Duplicate rules** appear when both iptables-nft and native nftables rules touch the same chains
- **NAT port forwarding stops working** after a system update or firewall reload
- **Docker containers become unreachable** from the host or from other VLAN segments
- **Unexpected kernel module loads** waste memory with both iptable_* and nf_tables modules loaded simultaneously

Docker Engine 29 introduced an experimental **native nftables firewall backend** that bypasses the iptables compatibility layer entirely. Instead of translating iptables calls through nftables, Docker writes nftables rules directly using the `nft` command. The result: simpler rule chains, atomic rule updates, and one consistent firewall framework across your host.

This guide walks through enabling the nftables backend on a Debian 13 or Ubuntu 24.04 host, verifying it works, testing port publishing, and handling migration issues for existing Docker Compose stacks.

## Checking Your Current Firewall Backend

Before changing anything, confirm what Docker is using today:

```bash
# Check Docker's active firewall backend
docker info 2>/dev/null | grep -i firewall
```

If you're running Docker Engine 27 or older, the output is empty — Docker used iptables without advertising it. On Docker Engine 28+, you'll see:

```
Firewall: iptables
```

Or, if you've already switched:

```
Firewall: nftables
```

Next, check what's actually on the kernel side:

```bash
# Which iptables variant is installed?
iptables --version 2>/dev/null

# Kernel modules loaded
lsmod | grep -E '^(iptable_|nf_tables|nf_flow_table)'
```

On a default Debian 13 install, `iptables --version` returns something like `iptables v1.8.10 (nftables)` — the iptables-nft compat layer. You'll also see `nf_tables` and `nf_conntrack` loaded, plus `iptable_nat` and `iptable_filter` if Docker has been running.

Finally, inspect the rules Docker has created:

```bash
# Docker's NAT rules via iptables compat
iptables -t nat -L -n 2>/dev/null | head -25

# Compare with native nftables view
nft list table ip nat 2>/dev/null | head -30
```

On a hybrid system, both commands show the same logical rules but through different APIs. On a pure nftables system, `iptables -t nat -L -n` shows nothing (or flat out refuses to run) while `nft list ...` works perfectly.

## Prerequisites for the nftables Firewall Backend

The nftables backend requires:

- **Docker Engine 29.0 or newer** — check with `docker version | grep -i engine`
- **Linux kernel 6.8+** with nftables support compiled in (standard on Debian 13 and Ubuntu 24.04)
- **nftables userspace tools** — `apt install nftables` if not already installed
- **No legacy iptables scripts** that set rules in iptables format — they won't apply through the nftables backend

Verify kernel support:

```bash
# Check if nftables is available in the kernel
zgrep NFT_ /proc/config.gz 2>/dev/null || grep NFT_ /boot/config-$(uname -r) 2>/dev/null | head -5

# Load nftables kernel modules (should be auto-loaded)
modprobe nf_tables
modprobe nf_tables_ipv4
modprobe nf_tables_ipv6
```

If `zgrep NFT_` returns nothing, your kernel was compiled without nftables — unlikely on any 2024+ distro but worth confirming.

## Configuring Docker to Use nftables

Enable the nftables backend by editing the Docker daemon configuration:

```bash
# Create or edit /etc/docker/daemon.json
cat > /etc/docker/daemon.json << 'EOF'
{
  "firewall-backend": "nftables",
  "iptables": false
}
EOF
```

The `"iptables": false` flag prevents Docker from falling back to iptables rules or touching the iptables compat chains. Without this, Docker may still create iptables-nft rules as a safety net, defeating the purpose of the migration.

If you have other daemon options (log driver, registry mirrors, data root), merge them in. A real-world example:

```json
{
  "data-root": "/var/lib/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "firewall-backend": "nftables",
  "iptables": false,
  "experimental": true
}
```

Restart Docker and verify:

```bash
systemctl daemon-reload
systemctl restart docker

# Confirm the nftables backend is active
docker info 2>/dev/null | grep -i firewall
```

Expected output:

```
Firewall: nftables
```

Docker now writes firewall rules directly through the nftables API. Inspect what it created:

```bash
# View Docker's nftables table
nft list table ip docker

# View Docker's NAT rules
nft list table ip nat | head -30
```

You'll see chains like `DOCKER`, `DOCKER-ISOLATION`, and `DOCKER-USER` in the `ip docker` table, plus entries in the `nat` table's `PREROUTING` and `POSTROUTING` chains for port publishing.

## Testing Port Publishing with nftables

Launch test containers to validate the nftables backend handles port mapping correctly:

```bash
# Start two test services
docker run -d --name web-test -p 8080:80 nginx:alpine
docker run -d --name whoami -p 9000:80 traefik/whoami

# Test connectivity
curl -sI http://localhost:8080 | head -5
curl -s http://localhost:9000
```

Both should respond immediately. If they don't, the nftables NAT rules aren't being created — check the next section.

Now inspect the nftables NAT chains Docker created:

```bash
nft list table ip nat
```

Expected output shows `dnat` rules in the `PREROUTING` chain for each published port:

```
table ip nat {
    chain PREROUTING {
        type nat hook prerouting priority dstnat; policy accept;
        fib daddr type local counter jump DOCKER
    }

    chain POSTROUTING {
        type nat hook postrouting priority srcnat; policy accept;
        oifname "docker0" counter masquerade
        oifname "br-<net-id>" counter masquerade
    }

    chain DOCKER {
        iifname "docker0" counter return
        iifname != "docker0" meta l4proto tcp ip daddr 172.17.0.2 tcp dport 80 counter dnat to 172.17.0.2:80
        iifname != "docker0" meta l4proto tcp ip daddr 172.17.0.3 tcp dport 80 counter dnat to 172.17.0.3:80
    }
}
```

Test inter-container communication on a user-defined bridge network:

```bash
# Create a user-defined network
docker network create --driver bridge app-net

# Launch two containers on it
docker run -d --net app-net --name app1 alpine sleep 300
docker run -d --net app-net --name app2 alpine sleep 300

# Verify DNS resolution and ICMP
docker exec app1 ping -c 2 app2
docker exec app2 ping -c 2 app1
```

Inter-container traffic on user-defined networks bypasses `FORWARD` chain filtering (Docker inserts ACCEPT rules for these networks). On the default `docker0` bridge, isolated containers can still reach each other unless `--icc=false` is set on the daemon.

## Migrating Existing Docker Compose Stacks

The nftables backend operates at the daemon level, not the compose level. **No compose file changes are needed.** All port mappings defined in `docker-compose.yml` continue to work:

```yaml
# This compose file works identically under nftables backend
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro

  app:
    image: my-app:latest
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
```

Restart your stacks after switching:

```bash
docker compose -f /opt/stacks/nginx/docker-compose.yml down
docker compose -f /opt/stacks/nginx/docker-compose.yml up -d
```

**Where migration requires attention:** custom iptables rules you wrote alongside Docker. If you have firewall scripts that run `iptables -A FORWARD ...` or `iptables -t nat -A POSTROUTING ...`, those commands call the iptables-nft compat layer — they still run under the nftables backend but behave differently.

Convert critical rules using `iptables-translate`:

```bash
# iptables rule
iptables -A INPUT -s 10.0.20.0/24 -p tcp --dport 9090 -j ACCEPT

# Translate to nftables syntax
iptables-translate -A INPUT -s 10.0.20.0/24 -p tcp --dport 9090 -j ACCEPT

# Output:
# nft add rule ip filter INPUT ip saddr 10.0.20.0/24 tcp dport 9090 accept
```

For the Docker-USER chain (rules evaluated before Docker's FORWARD rules), the equivalent nftables rule looks like:

```bash
# Only allow forwarding from management VLAN through Docker
nft add rule ip docker DOCKER-USER ip saddr 10.0.20.0/24 counter accept
nft add rule ip docker DOCKER-USER counter drop
```

Save your nftables ruleset to survive reboots:

```bash
nft list ruleset > /etc/nftables.conf
systemctl enable nftables
systemctl start nftables
```

## Troubleshooting Common Issues

### Docker won't start with nftables backend

```
Job for docker.service failed because the control process exited with error code.
```

**Diagnosis:**

```bash
# Check daemon logs
journalctl -u docker --no-pager -n 40 | grep -i nft

# Check kernel support
modprobe nf_tables
lsmod | grep nf_tables

# Check Docker Engine version
docker version | grep -i engine
```

**Fix:** Docker Engine 28 or older doesn't support the nftables backend. Upgrade from the official Docker repository:

```bash
curl -fsSL https://get.docker.com | sh
```

If Docker 29+ but still failing, revert daemon.json, restart, and check the full daemon log:

```json
{
  "firewall-backend": "nftables",
  "iptables": false,
  "debug": true
}
```

### Port publishing not working after migration

Services start but `curl http://localhost:8080` times out.

**Diagnosis:**

```bash
# Are the nftables NAT chains present?
nft list table ip nat 2>/dev/null | grep -q DOCKER && echo "DOCKER chain exists" || echo "No DOCKER chain"

# Is docker0 up?
ip addr show docker0

# Check Docker port mapping
docker port web-test

# Force Docker to recreate rules
systemctl restart docker
docker start web-test
```

**Fix:** The most common cause is that Docker's nftables rules were partially created during startup. A full `systemctl restart docker` followed by container restarts usually resolves it.

### UFW blocking Docker traffic

If you use UFW alongside Docker, UFW's default rules block forwarded traffic from Docker's bridge networks:

```bash
# Check UFW status
ufw status verbose

# Allow Docker user chains through UFW
sed -i '/^COMMIT/i *filter\n-A ufw-after-forward -i docker0 -j ACCEPT\n-A ufw-after-forward -o docker0 -j ACCEPT\nCOMMIT' /etc/ufw/after.rules
ufw reload
```

Under the nftables backend, UFW also uses nftables. Conflicts arise when both UFW and Docker write rules to the same hook. The cleanest approach is to use the `DOCKER-USER` chain in nftables rather than overlapping with UFW:

```bash
# Accept forward traffic on Docker bridges in DOCKER-USER
nft add rule ip docker DOCKER-USER iifname "docker*" oifname "docker*" counter accept
nft add rule ip docker DOCKER-USER oifname "docker*" meta l4proto { tcp, udp } ct state related,established counter accept
nft add rule ip docker DOCKER-USER iifname "docker*" meta l4proto { tcp, udp } ct state related,established counter accept
```

### Existing containers unreachable after switch

Because Docker flushes its old iptables rules when switching backends, containers that were running before the migration need to be recreated:

```bash
# Regenerate network sandbox and firewall rules
docker update --restart=no $(docker ps -q) >/dev/null 2>&1
docker restart $(docker ps -q)
```

Or simply reboot the host after enabling the nftables backend to ensure all networking is reconstructed cleanly.

## Rolling Back to iptables

If the nftables backend causes persistent issues, rollback is straightforward:

```bash
# Remove nftables backend setting
cat > /etc/docker/daemon.json << 'EOF'
{
  "iptables": true
}
EOF

systemctl restart docker
docker info | grep -i firewall
```

The output reverts to `Firewall: iptables` or shows no firewall line on older engines. Then restart your containers so they re-register with the iptables ruleset.

## Conclusion

The Docker nftables firewall backend is a significant step forward for homelabs running modern Linux distributions. By eliminating the iptables-nft compatibility layer, you get atomic rule updates, direct nftables chain management, and one consistent firewall framework across your host. For new Debian 13 or Ubuntu 24.04 deployments, starting with the nftables backend avoids the hybrid firewall headache entirely.

Test the migration in a maintenance window, verify your published ports work, and convert any custom firewall rules to nftables syntax using `iptables-translate`. The nftables backend is stable enough for homelab use — and with Docker Engine 29+, it's the direction the ecosystem is heading.
