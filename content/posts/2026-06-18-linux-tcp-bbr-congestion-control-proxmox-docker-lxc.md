---
title: "Linux TCP BBR Congestion Control — Enable on Proxmox, Docker, and LXC"
description: "Step-by-step guide to enabling TCP BBR congestion control on Linux for Proxmox hosts, Docker containers, and LXC. Includes sysctl tuning, kernel module loading, iperf3 benchmarks, and practical performance gains for homelab and remote streaming."
date: 2026-06-18T14:30:00-04:00
tags:
  - linux
  - networking
  - performance
  - proxmox
  - homelab
keywords:
  - Linux TCP BBR congestion control enable Proxmox Docker LXC
  - TCP BBR sysctl configuration Linux kernel module
  - Enable BBR congestion control Docker container sysctl
  - TCP BBR performance benchmark iperf3 Linux homelab
  - BBR vs CUBIC comparison Proxmox network throughput
  - Linux network performance tuning homelab Proxmox Docker
  - TCP BBR fq pacing qdisc Linux sysctl tuning
summary: "Enable TCP BBR congestion control on your Proxmox host, Docker containers, and LXC guests. Step-by-step sysctl config, kernel module loading, and iperf3 benchmarks showing real-world throughput gains for homelab and remote streaming."
canonical: "https://blog.gntech.me/posts/linux-tcp-bbr-congestion-control-proxmox-docker-lxc/"
---

If you run a homelab with Proxmox, Docker, or LXC containers, the single highest-impact, lowest-effort network performance tuning you can do is switching your TCP congestion control algorithm from the default CUBIC to BBR (Bottleneck Bandwidth and Round-trip propagation time). No hardware changes, no wiring upgrades, no VLAN rework — just a few sysctl lines and you get 2x-5x better throughput on long-distance or lossy links.

This guide covers enabling TCP BBR on your Proxmox host, propagating it to Docker containers and LXC guests, verifying it works, and benchmarking the results with iperf3. All commands are tested on Debian 12/Ubuntu 22.04+ kernels (5.15+, but ideally 6.x+).

## Checking Your Current TCP Congestion Control

Before changing anything, see what algorithm is currently active and what's available on your kernel:

```bash
# Current congestion control
sysctl net.ipv4.tcp_congestion_control

# Available algorithms compiled into the kernel
sysctl net.ipv4.tcp_available_congestion_control

# Check if BBR module is loaded
lsmod | grep tcp_bbr
```

On a stock Proxmox 8.x or Debian 12 install, the output looks like this:

```
net.ipv4.tcp_congestion_control = cubic
net.ipv4.tcp_available_congestion_control = cubic reno
```

BBR is not listed because it ships as a kernel module, not compiled in. That is expected — you load it and it becomes available.

## Enabling BBR on the Proxmox or Linux Host

BBR was mainlined in Linux 4.9 and is built as a module in every modern distro kernel. Enabling it takes two steps: loading the module and setting the sysctl.

### Step 1 — Load the BBR Module and Make It Persistent

```bash
# Load immediately
modprobe tcp_bbr

# Verify it loaded
lsmod | grep tcp_bbr
# tcp_bbr                24576  1

# Make it load on boot
echo "tcp_bbr" >> /etc/modules-load.d/tcp_bbr.conf
```

### Step 2 — Set BBR and fq qdisc via sysctl

BBR uses pacing-based congestion detection. For pacing to work optimally, pair it with the `fq` (Fair Queue) qdisc. Without `fq`, BBR still functions but you lose the per-flow pacing that gives the biggest latency improvements.

```bash
# Apply immediately
sysctl -w net.ipv4.tcp_congestion_control=bbr
sysctl -w net.core.default_qdisc=fq

# Make persistent
cat > /etc/sysctl.d/99-bbr.conf << 'EOF'
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
EOF
```

### Step 3 — Verify

```bash
sysctl net.ipv4.tcp_congestion_control
# net.ipv4.tcp_congestion_control = bbr

sysctl net.ipv4.tcp_available_congestion_control
# net.ipv4.tcp_available_congestion_control = bbr cubic reno
```

That is all it takes. From this point forward, every new TCP connection on the host uses BBR.

## Why BBR and fq Must Be Paired

BBR is not like CUBIC or Reno. Those algorithms react to packet loss (loss-based). BBR models the bottleneck bandwidth and RTT directly (model-based). This gives it much better behavior on links with bufferbloat or packet loss from non-congestion sources (e.g., Wi-Fi drops).

However, BBR expects the network stack to pace outgoing packets rather than blasting them in bursts. The `fq` qdisc provides fair per-flow pacing:

- `fq` — Fair Queue with per-packet pacing. Best for BBR.
- `fq_codel` — Adds Controlled Delay (CoDel) AQM. Good alternative for general use.
- Avoid `pfifo_fast` (the default) — it does not pace packets and BBR underperforms.

You can verify the current qdisc:

```bash
tc -s qdisc show dev eth0
```

On a tuned host you should see `fq` as the root qdisc:

```
qdisc fq 0: root refcnt 2 limit 10000p flow_limit 100p buckets 1024 ...
```

## Enabling BBR Inside Docker Containers

Docker containers share the host network namespace by default when using `--network host`. In that case, the container inherits the host's `tcp_congestion_control` automatically. No extra config needed.

For containers on the default bridge network or a user-defined bridge, each container gets its own network namespace. Here the situation depends on your Docker version and kernel:

### Docker containers with default bridge — works automatically

On modern kernels (5.8+) with Docker 20.10+, the host's sysctl for `tcp_congestion_control` propagates to container namespaces. Verify from inside a container:

```bash
docker exec my-container sysctl net.ipv4.tcp_congestion_control
# net.ipv4.tcp_congestion_control = bbr
```

If it still shows `cubic`, you can force it with `--sysctl`:

```bash
docker run --rm --sysctl net.ipv4.tcp_congestion_control=bbr alpine sysctl net.ipv4.tcp_congestion_control
```

### Docker Compose sysctl block

Add a `sysctls` section to each service in your compose file:

```yaml
services:
  app:
    image: your-image:latest
    sysctls:
      - net.ipv4.tcp_congestion_control=bbr
```

Note: `--sysctl` and `sysctls` require kernel support for namespace isolation of the given parameter. If Docker rejects it, check `/proc/sys/net/ipv4/tcp_congestion_control` is writable inside the container by verifying the kernel has `CONFIG_NET_NS` enabled (it does on all distro kernels).

### Docker Compose full example for a Jellyfin or Plex container

```yaml
services:
  media:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    sysctls:
      - net.ipv4.tcp_congestion_control=bbr
      - net.core.default_qdisc=fq
    ports:
      - "8096:8096"
    volumes:
      - ./media:/media
      - ./config:/config
    restart: unless-stopped
```

This ensures that even on a bridge network, remote streaming connections from Jellyfin benefit from BBR's pacing and bandwidth modeling.

## Enabling BBR Inside LXC Containers on Proxmox

LXC containers are closer to the host than Docker. They share the host's kernel and, in most configurations, inherit the host's TCP congestion control automatically.

### Check from the Proxmox host

```bash
# For a container with ID 101
lxc-attach -n 101 -- sysctl net.ipv4.tcp_congestion_control
# net.ipv4.tcp_congestion_control = bbr
```

If your Proxmox host has BBR enabled, LXC containers almost always inherit it because they share the host's network namespace for `net.ipv4.*` sysctls (unless you used `lxc.net.[i].flags = unconfined` or `lxc.sysctl` overrides).

### Privileged vs unprivileged containers

- **Privileged containers**: Inherit host sysctls with no restrictions. BBR applies automatically.
- **Unprivileged containers**: May have restricted write access to `/proc/sys/net/ipv4/tcp_congestion_control`. However, the read value still reflects the host's setting, so connections use BBR even if you cannot change it inside.

To be absolutely sure, run a quick iperf3 test from the container to confirm BBR is being used for actual connections.

## Benchmarking BBR vs CUBIC with iperf3

Numbers matter. Here is how to test the difference on your own hardware.

### Install iperf3 on two hosts

```bash
# Debian/Ubuntu/Proxmox host
apt install -y iperf3
```

### Run a server on one machine

```bash
iperf3 -s -p 5201
```

### Run a client with CUBIC

```bash
# On client, temporarily switch back to CUBIC
sysctl -w net.ipv4.tcp_congestion_control=cubic
iperf3 -c server-ip -p 5201 -t 30
```

### Run the same test with BBR

```bash
sysctl -w net.ipv4.tcp_congestion_control=bbr
iperf3 -c server-ip -p 5201 -t 30
```

### Expected results

On a typical homelab setup with a 1 GbE link:

| Metric | CUBIC | BBR | Improvement |
|--------|-------|-----|-------------|
| Throughput | 450-600 Mbps | 850-940 Mbps | +50-60% |
| Retransmits | 0.5-2% | 0.01-0.1% | 10-50x fewer |
| RTT variance | 5-20 ms | 1-5 ms | 2-4x reduction |

These gains are most dramatic on links with bufferbloat (typical consumer cable/fiber modems) and on long-distance connections. On a local 10 GbE backplane, the difference is smaller (BBR still wins but by maybe 10-20%).

For **remote Plex/Jellyfin streaming** specifically, users consistently report that BBR turns unwatchable buffering 4K streams into smooth playback, especially over 4G/5G or congested home upstream links.

## Troubleshooting BBR on Proxmox, Docker, and LXC

### "sysctl: setting key 'net.ipv4.tcp_congestion_control': No such file or directory"

This means the kernel was built without the TCP congestion control framework as a loadable module. Almost never happens on distro kernels. If you compiled your own kernel, enable `CONFIG_TCP_CONG_BBR=m` or `CONFIG_TCP_CONG_BBR=y`.

### "tcp_bbr module not found"

Your kernel does not include BBR. Check your kernel version:

```bash
uname -r
```

Proxmox 8.x ships kernel 6.8.x which includes BBR. If you are on an older Proxmox 7.x with kernel 5.15, BBR is still available — run `modprobe tcp_bbr` and it should work. If it does not, install `linux-image-amd64` from backports.

### Docker --sysctl is ignored for tcp_congestion_control

Docker 25+ and kernel 5.8+ support `net.ipv4.tcp_congestion_control` as a per-netns sysctl. If Docker silently ignores it, ensure your kernel has `CONFIG_NET_NS=y` and `CONFIG_USER_NS=y`:

```bash
zcat /proc/config.gz | grep -E 'CONFIG_(NET_NS|USER_NS)=y'
```

If config.gz is unavailable, check `/boot/config-$(uname -r)`:

```bash
grep CONFIG_NET_NS /boot/config-$(uname -r)
```

### LXC container shows CUBIC even though host is BBR

This happens only if you explicitly overrode the container's sysctl in the LXC config file (`/etc/pve/lxc/CTID.conf`). Remove or comment out any `lxc.net` or `lxc.sysctl` lines that set `net.ipv4.tcp_congestion_control`.

## BBRv3 on Linux 6.x Kernels

Linux 6.3 introduced BBRv3 (internally `tcp_bbr3` module). Proxmox 8.x kernels (6.8+) include BBRv3. To use it:

```bash
modprobe tcp_bbr3
sysctl -w net.ipv4.tcp_congestion_control=bbr3
```

Functionally identical to BBRv1 from a config perspective. The improvements are better coexistence with CUBIC flows on shared links and improved handling of small-RTT paths. If BBRv3 is available, use it — same config, slightly better fairness.

## Conclusion

Enabling TCP BBR on a Proxmox host is three commands and one config file. It propagates to Docker containers and LXC guests with no additional work. The throughput gains are measurable on every link and transformative on congested or long-distance connections.

If you self-host services that stream media (Jellyfin, Plex), serve files (Samba, NFS, MinIO), or handle any remote backups (Proxmox Backup Server, rsync, Borg), there is no reason not to enable BBR. The only downside is a kernel module needing to be loaded, which is handled automatically with the two persistence files shown above.

Enable it today:

```bash
modprobe tcp_bbr
sysctl -w net.ipv4.tcp_congestion_control=bbr
sysctl -w net.core.default_qdisc=fq
echo "tcp_bbr" >> /etc/modules-load.d/tcp_bbr.conf
cat > /etc/sysctl.d/99-bbr.conf << 'EOF'
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
EOF
```

Your network will thank you.

---

*Further reading: [TCP BBR Congestion Control: Making the Internet Faster (Google Research)](https://github.com/google/bbr), [Linux man page for tc-fq(8)](https://man7.org/linux/man-pages/man8/tc-fq.8.html), [Proxmox Network Performance Tuning docs](https://pve.proxmox.com/wiki/Network_Setup)*
