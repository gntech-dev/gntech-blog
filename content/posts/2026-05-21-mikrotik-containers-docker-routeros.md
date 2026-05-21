---
title: "MikroTik Containers — Run Docker Images on RouterOS"
description: "Deploy Docker containers directly on MikroTik RouterOS 7 — enable container mode, configure veth bridges, pull images, and run Pi-hole, AdGuard Home, Tailscale, or NetBird on your router."
date: 2026-05-21T17:00:00-04:00
tags:
  - mikrotik
  - containers
  - routeros
  - homelab
  - networking
keywords:
  - MikroTik containers RouterOS Docker images
  - MikroTik container mode setup veth bridge
  - Pi-hole on MikroTik RouterOS 7
  - AdGuard Home MikroTik container deployment
  - MikroTik container veth interface bridge config
  - RouterOS container registry Docker Hub pull
  - MikroTik container mount volume persistent storage
summary: "Run Docker containers directly on MikroTik RouterOS 7 — enable container mode, configure veth bridges, pull images from Docker Hub, and deploy Pi-hole or AdGuard Home without extra hardware."
canonical: "https://blog.gntech.me/posts/2026-05-21-mikrotik-containers-docker-routeros/"
---

RouterOS has supported Linux containers since v7.4beta, and the
feature has matured significantly through v7.16+ and into 2026's
v7.18 releases. You can pull container images from Docker Hub,
GCR, Quay, or any OCI-compatible registry and run them directly
on your MikroTik router — no separate server required.

Think about it: your MikroTik router sits at the edge of your
network with a direct view of all traffic. Running lightweight
containers like Pi-hole, AdGuard Home, Tailscale, or NetBird
on the router itself eliminates an extra hop, reduces power
consumption, and simplifies your stack.

This guide covers the full setup from scratch: enabling
container mode, configuring networking, pulling images, setting
up persistent storage, and practical real-world use cases.

---

## Requirements and Limitations

Before diving in, check that your hardware is compatible.

### Hardware Support

The container package works on **arm, arm64, and x86**
architectures. Not all RouterBOARD models support it:

- **ARM64 (recommended):** RB5009, CCR2116, CCR2216, hAP
  ax³/l³, L009, Chateau 5G — these have enough RAM and storage
- **ARM (32-bit):** hEX Refresh (RB750Gr3) — only arm32v5 images,
  limited selection
- **x86:** CHR and x86 installations — full support with external
  storage
- **Not supported:** Older MIPSBE, MIPSBLE, and Tile-based
  devices (RB7xx, RB9xx, RB1100, and most pre-2019 hardware)

### Storage Requirements

Containers consume significant storage. RouterOS internal flash
(usually 16MB–512MB) is not enough. You **must** attach external
storage:

- USB flash drive or SSD
- SATA SSD (on models with SATA ports like RB5009 or CCR series)
- microSD card (on hAP ax³ or L009 — use A2-rated for speed)

Recommendation: at least 8GB, preferably 16GB+ for multiple
containers. The filesystem should be ext4, which RouterOS
supports natively.

### Performance Considerations

Each container consumes CPU and RAM. A RouterBOARD RB5009 with
its 4-core Cortex-A72 can comfortably run 3–5 lightweight
containers (Pi-hole, Tailscale, Node Exporter). Resource-heavy
containers like databases or media transcoders are not suitable.

MikroTik recommends external storage with at least 100 MB/s
sequential read/write and 10K random IOPS — easily met by a
USB 3.0 SSD.

---

## Step 1 — Enable Container Mode

Container mode is gated behind device-mode for security reasons.
Physical access to the router is required for the first step.

### On ARM/ARM64 Devices

From a terminal session on the router (SSH or serial):

```
/system/device-mode/update container=yes
```

The router will prompt you to press the **physical reset button**
within 30 seconds. Press and hold the button until the LED
pattern changes. The device reboots with container mode enabled.

### On x86 / CHR

For x86 and CHR installations, cold-reboot the VM or machine
instead of the reset button:

```
/system/device-mode/update container=yes
```

Then reboot:

```
/system/reboot
```

### Install the Container Package

RouterOS packages are managed via the package menu:

```
/system/package/update/set channel=stable
/system/package/update/install
```

After updating, verify the container package is available:

```
/container/config/print
```

If you see output like `registry-url: https://lscr.io`, the
package is installed and ready.

If not, install it from the packages menu at **System >
Packages > Available Packages** in WinBox, or use:

```
/system/package/install container
/reboot
```

---

## Step 2 — Configure Container Networking

Containers need a virtual Ethernet (veth) interface and a bridge
to communicate with the rest of your network.

### Create the Bridge

```
/interface/bridge/add name=containers
/ip/address/add address=172.17.0.1/24 interface=containers
```

### Create a Veth Interface

```
/interface/veth/add name=veth1 address=172.17.0.2/24 gateway=172.17.0.1
```

### Attach Veth to Bridge

```
/interface/bridge/port add bridge=containers interface=veth1
```

### Masquerade Outbound Traffic

Containers need NAT to reach the internet:

```
/ip/firewall/nat/add chain=srcnat action=masquerade src-address=172.17.0.0/24
```

### Enable IP Forwarding (if not already)

```
/ip/settings/set forward=yes
```

At this point, any container attached to this veth interface
will have outbound internet access through the router's WAN.

### Multiple Containers per Veth

You can attach multiple containers to the same veth interface
if they listen on different ports. Alternatively, create
isolated veth pairs per container:

```
/interface/veth/add name=veth-pihole address=172.17.0.3/24 gateway=172.17.0.1
/interface/veth/add name=veth-tailscale address=172.17.0.4/24 gateway=172.17.0.1
/interface/bridge/port add bridge=containers interface=veth-pihole
/interface/bridge/port add bridge=containers interface=veth-tailscale
```

---

## Step 3 — Configure the Container Registry

RouterOS supports multiple registries. Set Docker Hub as your
primary source:

```
/container/config/set \
    registry-url=https://registry-1.docker.io \
    tmpdir=disk1/tmp
```

Replace `disk1` with your external drive label. Find yours:

```
/disk/print
```

The `tmpdir` is where container images are extracted. Point it
to external storage to avoid filling the internal flash.

---

## Step 4 — Set Up Persistent Storage

Containers are ephemeral by default. For stateful services like
Pi-hole (which stores DNS logs and blocklists), mount directories
from your external disk.

### Create Mount Directories

From the RouterOS shell:

```
/file/print
/file/mkdir disk1/containers/pihole
/file/mkdir disk1/containers/pihole-dnsmasq
/file/mkdir disk1/containers/adguard/work
/file/mkdir disk1/containers/adguard/conf
```

### Register Mounts for Pi-hole

```
/container/mounts/add \
    list=MOUNT_PIHOLE \
    src=disk1/containers/pihole \
    dst=/etc/pihole

/container/mounts/add \
    list=MOUNT_PIHOLE_DNSMASQ \
    src=disk1/containers/pihole-dnsmasq \
    dst=/etc/dnsmasq.d
```

On first start, the container will populate the mount directory
with its default files.

---

## Step 5 — Deploy Pi-hole

Pi-hole is the most common container on RouterOS and one of the
most practical — it turns your router into a network-wide ad
blocker with a web dashboard.

### Set Environment Variables

```
/container/envs/add list=ENV_PIHOLE key=TZ value="America/Santo_Domingo"
/container/envs/add list=ENV_PIHOLE key=FTLCONF_webserver_api_password value="your-secure-password"
/container/envs/add list=ENV_PIHOLE key=DNSMASQ_USER value="root"
/container/envs/add list=ENV_PIHOLE key=WEBPASSWORD value="your-admin-password"
```

### Add the Container

```
/container/add \
    remote-image=pihole/pihole:latest \
    interface=veth1 \
    root-dir=disk1/images/pihole \
    envlist=ENV_PIHOLE \
    mountlists=MOUNT_PIHOLE,MOUNT_PIHOLE_DNSMASQ \
    start-on-boot=yes \
    logging=no \
    name=pihole
```

### Wait for the Pull and Extract

Monitor progress:

```
/container/print detail
```

Wait until `status` changes to `stopped`. This means the image
has been pulled and extracted. Then start it:

```
/container/start pihole
```

### Enable DNS Forwarding

Configure RouterOS to forward DNS queries to the container:

```
/ip/dns/set allow-remote-requests=yes servers=172.17.0.2
```

### Expose the Web Interface

Add a destination NAT rule to access the Pi-hole admin panel:

```
/ip/firewall/nat/add \
    chain=dstnat \
    dst-address=192.168.88.1 \
    dst-port=80 \
    protocol=tcp \
    action=dst-nat \
    to-addresses=172.17.0.2 \
    to-ports=80
```

Replace `192.168.88.1` with your router's LAN IP. Now access
the admin panel at `http://192.168.88.1/admin/`.

---

## Step 6 — Deploy AdGuard Home (Alternative)

AdGuard Home is a popular Pi-hole alternative with a more modern
interface and built-in DHCP server support.

### Environment Variables

```
/container/envs/add list=ENV_ADGUARD key=TZ value="America/Santo_Domingo"
```

### Mounts

```
/container/mounts/add \
    list=MOUNT_ADGUARD_WORK \
    src=disk1/containers/adguard/work \
    dst=/opt/adguardhome/work

/container/mounts/add \
    list=MOUNT_ADGUARD_CONF \
    src=disk1/containers/adguard/conf \
    dst=/opt/adguardhome/conf
```

### Add and Start

```
/container/add \
    remote-image=adguard/adguardhome:latest \
    interface=veth1 \
    root-dir=disk1/images/adguard \
    envlist=ENV_ADGUARD \
    mountlists=MOUNT_ADGUARD_WORK,MOUNT_ADGUARD_CONF \
    start-on-boot=yes \
    name=adguard
```

### DNS and Port Forwarding

```
/ip/firewall/nat/add \
    chain=dstnat \
    dst-address=192.168.88.1 \
    dst-port=80 \
    protocol=tcp \
    action=dst-nat \
    to-addresses=172.17.0.2 \
    to-ports=80

/ip/dns/set servers=172.17.0.2
```

AdGuard Home listens on port 3000 for the initial setup wizard.
Forward it temporarily:

```
/ip/firewall/nat/add \
    chain=dstnat \
    dst-address=192.168.88.1 \
    dst-port=3000 \
    protocol=tcp \
    action=dst-nat \
    to-addresses=172.17.0.2 \
    to-ports=3000
```

After initial configuration, AdGuard Home runs its admin
interface on port 80.

---

## Step 7 — Deploy Tailscale on MikroTik

Tailscale in a container on your MikroTik router creates a mesh
VPN endpoint without any additional hardware. This is useful
for accessing management interfaces from outside your LAN.

```
/container/envs/add \
    list=ENV_TAILSCALE \
    key=TS_AUTHKEY value="tskey-auth-xxxxxxxx"

/container/envs/add \
    list=ENV_TAILSCALE \
    key=TS_STATE_DIR value="/var/lib/tailscale"

/container/mounts/add \
    list=MOUNT_TAILSCALE \
    src=disk1/containers/tailscale \
    dst=/var/lib/tailscale

/container/add \
    remote-image=tailscale/tailscale:latest \
    interface=veth1 \
    root-dir=disk1/images/tailscale \
    envlist=ENV_TAILSCALE \
    mountlists=MOUNT_TAILSCALE \
    start-on-boot=yes \
    name=tailscale
```

Important: the Tailscale container needs `--privileged`-like
capabilities to create the WireGuard tunnel. RouterOS containers
have limited support for the `devices` property. On some RouterOS
versions, you may need to add:

```
/container/set devices=tun tailscale
```

After starting the container and authorizing the node, your
router becomes part of your Tailscale tailnet.

---

## Step 8 — Management and Monitoring

### View Running Containers

```
/container/print detail
```

Key fields: `status` (running/stopped), `uptime`, `cpu-load`,
`memory-current`, and `root-dir` usage.

### Container Shell Access

Enter a running container's shell:

```
/container/shell pihole
```

This drops you into an interactive shell inside the container.
Exit with `Ctrl+D` or type `exit`.

### Stop and Start

```
/container/stop pihole
/container/start pihole
```

### Update a Container Image

```
/container/update pihole
```

This pulls the latest image, extracts it, and replaces the
existing one. The container will restart automatically.

### View Container Logs

```
/log/print where topics~"container"
```

Or enable logging per container:

```
/container/set logging=yes pihole
```

Disable it afterward to avoid log noise:

```
/container/set logging=no pihole
```

### Resource Limits

Prevent a container from consuming all RAM:

```
/container/set memory-max=134217728 pihole  # 128 MB limit
/container/set memory-high=67108864 pihole   # 64 MB soft limit
```

---

## Troubleshooting

### Container Fails to Start

```
/container/print detail
```

Look for `status` and `last-error` fields. Common causes:

- Storage full — check `/disk/print` and free up space
- Image not fully extracted — wait and check `status=extracting`
- veth interface missing — verify `/interface/veth/print`

### DNS Resolution Inside Container

If the container cannot resolve domain names, set explicit DNS:

```
/container/set dns=1.1.1.1 pihole
```

### Pull Timeout for Large Images

Large images may time out on slow connections. Increase the
timeout by adjusting the pull settings (not directly
configurable in older ROS versions). Alternatively, download
the image on a PC and import it manually:

```
/container/add file=pihole.tar.gz name=pihole-local
```

### Container Image Compatibility

Use the architecture tag matching your CPU:

- ARM64 (RB5009, CCR): `arm64v8/` or generic `:latest`
- ARM32 (hEX Refresh): `arm32v5/` — very limited library
- x86/CHR: `amd64/` or generic `:latest`

## Summary

MikroTik Container support in RouterOS is a powerful feature
that turns your network edge device into a lightweight
application host. For homelab use cases like DNS filtering
(Pi-hole / AdGuard Home), mesh VPN (Tailscale / NetBird), or
monitoring (Node Exporter), running a container directly on the
router is more efficient than spinning up a separate machine.

Key takeaways:

- **External storage is mandatory** — USB SSD or SATA, ext4
  formatted, at least 8 GB
- **Container mode requires physical access** once, then remote
  management works normally
- **Use the registry cache** — repeated `container/update` calls
  reuse the extracted image layer to save bandwidth
- **Monitor memory** — RouterOS has limited RAM on most boards;
  set `memory-max` per container
- **Start with Pi-hole** — it is the most tested, well-documented
  container image for RouterOS

The same setup works for dozens of other lightweight Docker
images. Just ensure the architecture matches your RouterBOARD
and keep resource limits tight. Your router is now a router
_and_ a container host.
