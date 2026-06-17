---
title: "MikroTik RouterOS Container Apps — One-Click Service Deployment"
description: "Deploy Gitea, Home Assistant, and other services on MikroTik RouterOS with the new App catalog. One-click container setup with automatic firewall, NAT, and networking."
date: 2026-06-15T16:00:00-04:00
tags:
  - mikrotik
  - routeros
  - containers
  - homelab
  - networking
keywords:
  - MikroTik RouterOS Container Apps one-click deployment guide
  - RouterOS 7.24 App catalog Gitea Home Assistant setup
  - MikroTik container mode setup Apps wizard RouterOS
  - RouterOS App store container deployment configuration
  - MikroTik App menu container management RouterOS 7
  - Self-hosted containers on MikroTik router without Linux host
  - RouterOS container application auto configuration firewall NAT
summary: "Deploy containers on your MikroTik router in minutes using the new Apps catalog. Automatic firewall rules, NAT, and veth interfaces — no manual Docker setup required."
canonical: "https://blog.gntech.me/posts/mikrotik-routeros-container-apps-deployment/"
---

If you have run containers on MikroTik before, you know the drill: enable device mode, configure a bridge, set up veth interfaces, write firewall rules, configure NAT, mount storage, and pull images by hand. It works, but it is a lot of steps for what should be simple.

RouterOS 7.14 introduced the **Apps** subsystem (`/app`), and the 7.24 beta cycle expanded the catalog with well-known services like Gitea and Home Assistant. The Apps system is MikroTik's answer to one-click container deployment — it handles networking, firewall rules, port mapping, and storage automatically.

This guide walks through everything: enabling container mode, running the setup wizard, deploying apps, and customizing configurations for your homelab.

## Why the RouterOS App Catalog Matters for Homelab

Before Apps, deploying a container on RouterOS required a half-dozen manual steps in the CLI or WinBox. The new `/app` system abstracts all of that into a catalog.

**What the App system does automatically:**

- Creates and attaches veth interfaces to your LAN bridge
- Generates firewall filter rules and NAT dstnat entries
- Pulls container images from Docker Hub, GCR, or Quay
- Configures environment variables from a YAML manifest
- Generates a UI-URL for web access via WebFig

This is not a replacement for a full Docker host. The MikroTik container runtime is lightweight — it runs on the router itself, sharing its CPU and RAM. That makes it ideal for lightweight services that benefit from living on the network edge: a local Gitea mirror, a Home Assistant instance, or an ad-blocking DNS container.

## Requirements and Prerequisites

Before you start, confirm your device meets the requirements:

| Requirement | Details |
|---|---|
| RouterOS version | 7.14+ (7.24 beta for newest catalog entries) |
| Architecture | arm64 or x86 (not MIPSBE / EN7562CT) |
| Container package | Must be installed (`/system/package/print`) |
| Device mode | Container mode must be enabled |
| Storage | External USB, NVMe, or SATA recommended (at least 4 GB) |
| RAM | Minimum 512 MB free for containers |

Check your device:

```bash
# Verify container package is installed
/system/package/print where name=container

# Check available architecture
/system/resource/print

# List available disks
/disk/print
```

If the container package is missing, install it:

```bash
/system/package/install container
```

Reboot after installation.

## Step 1: Enable Container Mode

Container mode requires physical access to the device and a configuration reset. This is a one-time step.

```bash
# Check current device mode
/system/device-mode/print

# Enable container mode (requires confirmation and reboot)
/system/device-mode/update container=yes
```

The device will prompt for confirmation, then reboot. After the reboot, container mode is permanently enabled. You can verify:

```bash
/system/device-mode/print
# Output should show: container: yes
```

> **Important**: Enabling container mode must be done with physical console or serial access. It cannot be enabled remotely via SSH or API.

## Step 2: Run the Setup Wizard

The `/app setup` wizard automates storage selection, bridge configuration, and IP assignment.

```bash
/app setup
```

The wizard walks through three steps:

### Step 2a: Storage Selection

The scanner detects formatted disks (nvme1, usb1, sata1, etc.). If no disk appears, format one first:

```bash
# Format a USB drive as ext4
/disk/format-drive usb1 file-system=ext4

# Test storage performance (min 100 MB/s sequential recommended)
/disk/test usb1
```

Pick the disk when prompted. The wizard creates the necessary directory structure.

### Step 2b: Bridge Configuration

Select the LAN bridge interface (typically `bridge` or `bridge_lan`). The wizard will:

- Create virtual ethernet (veth) interfaces for each app
- Attach them to the selected bridge
- Configure IP addressing for container connectivity

### Step 2c: Router IP

Enter the IP address used to access the router's web interface. This is used for UI-URL generation and automatic WebFig integration links.

After completion, verify the settings:

```bash
/app/settings/print
```

Expected output shows your disk, bridge, router-ip, and auto-configured paths:

```
  app-store-urls: https://apps.mikrotik.com/container/index.yaml
  auto-update: no
  disk: usb1
  download-path: usb1/media/downloads
  media-path: usb1/media
  lan-bridge: bridge
  router-ip: 10.0.20.1
  show-in-webfig: yes
```

## Step 3: Browse and Deploy Apps

List available apps from the MikroTik catalog:

```bash
/app/print
```

This shows all discoverable apps with their status, size, and UI URL (if running). Flags indicate state:

- `X` = disabled
- `R` = running

### Deploy Gitea

```bash
/app/enable gitea
```

RouterOS downloads the Gitea container image, creates the veth interface, adds firewall rules, and configures port forwarding. In seconds, Gitea is accessible at the generated UI-URL (typically `http://10.0.20.1:3000`).

You can verify the automatic configuration:

```bash
# Check the veth interface
/interface/print where name~"veth"

# View auto-generated firewall rules
/ip/firewall/filter/print where comment~"app"

# View auto-generated NAT rules
/ip/firewall/nat/print where comment~"app"
```

### Deploy Home Assistant

```bash
/app/enable home-assistant
```

Home Assistant deploys with its web UI mapped to port 8123 by default. The app includes automatic mDNS advertisements for discovery on the local network.

Monitor deployment status:

```bash
/app/print detail where name=home-assistant
```

The output shows `status: running`, memory usage, CPU usage, data size, and the UI-URL.

### Check Running Apps

```bash
/app/print
# X - DISABLED, R - RUNNING
# Columns: NAME, STATUS, CPU-USAGE, MEMORY-CURRENT, UI-URL
```

## Configuring App Parameters

Apps are not locked down. Every parameter in the YAML manifest can be overridden before or after deployment.

### Environment Variables

```bash
/app/set environment="GITEA__server__DOMAIN=git.lab.example.com, GITEA__server__ROOT_URL=https://git.lab.example.com" gitea
```

### Custom Mounts

```bash
/app/set extra-mounts="usb1/media/gitea-data:/data" gitea
```

### Port Redirects

Override auto-generated port maps:

```bash
/app/set firewall-redirects="443:3000, 80:3000" gitea
```

This maps host ports 443 and 80 to container port 3000.

### Enable Auto-Update

```bash
/app/set auto-update=yes gitea
```

Or set globally for all apps:

```bash
/app/settings/set auto-update=yes
```

### Custom App Stores

Run apps from a private or third-party catalog:

```bash
/app/settings/set app-store-urls="https://apps.example.com/catalog.yaml"
```

The custom store URL must point to a YAML array where each element describes an app with name, image, ports, and environment variables matching the MikroTik App schema.

## Apps vs Manual Container Setup

| Aspect | App Catalog (`/app`) | Manual (`/container`) |
|---|---|---|
| Setup time | 2 minutes + wizard | 15-30 minutes |
| Network config | Automatic (veth + bridge) | Manual (veth + bridge) |
| Firewall rules | Auto-generated | Manual configuration |
| NAT / port forwarding | Auto dstnat | Manual dstnat rules |
| Storage mounts | Configured in wizard | Manual bind mounts |
| Image pull | On enable | `/container/config/set` + pull |
| Custom images | Via custom app store | Any image |
| Multi-container | Supported (YAML groups) | Manual stacking |
| Granular control | Limited (preset parameters) | Full control |

**When to use Apps:** Quick deployments, learning containers on RouterOS, standard services (Gitea, Home Assistant), or when you want one-command repeatability.

**When to use manual:** Custom images, multi-stage networking, non-standard port schemes, or when you need fine-grained resource limits and device passthrough.

## Viewing the App YAML Manifest

Every app is defined by a YAML manifest. You can inspect it:

```bash
/app/print yaml where name=gitea
```

This shows the full compose-style definition including image source, environment variables, volumes, ports, and device requirements. You can export and modify it for custom app store deployment.

## Security Considerations

Running containers on your router expands the attack surface. Keep these points in mind:

**Physical access requirement**: Container mode requires physical console access to enable. This is a deliberate security boundary — a remote compromise cannot enable containers without prior physical setup.

**Third-party images**: MikroTik catalogs point to upstream registries. Verify image integrity when deploying critical services:

```bash
/app/set check-certificate=yes gitea
```

**Device resources**: A container that exhausts RAM or CPU can affect routing performance. Monitor usage:

```bash
/app/print detail
```

**Network isolation**: By default, apps use `network=default` which provides LAN access with NAT for outbound traffic. Use `network=internal` for services that should not be reachable from the LAN:

```bash
/app/set network=internal sensitive-app
```

## Troubleshooting Common Issues

### Container Won't Start

Check available memory and disk space:

```bash
/system/resource/print
/disk/print
/disk/usb1/print
```

If storage is full, the image extraction fails. Free space or use a larger disk.

### App Not Found in Catalog

Ensure the catalog URL is reachable:

```bash
/app/settings/print
# Verify app-store-urls is set
/app/check-store
```

For custom apps, verify the YAML endpoint returns a valid array.

### Networking Issues

If the container UI is unreachable:

```bash
# Check veth interface exists and is in bridge
/interface/print where name~"veth"

# Verify NAT rules
/ip/firewall/nat/print where comment~"app"

# Check container logs
/log/print where topics~"container"
```

## Real-World Example: Full Gitea Deployment

Here is the complete sequence from zero to running Gitea on a RouterOS device:

```bash
# 1. Install container package (if missing)
/system/package/install container
/system/reboot

# 2. Enable container mode (physical console required)
/system/device-mode/update container=yes

# 3. Format USB storage
/disk/format-drive usb1 file-system=ext4
/disk/test usb1

# 4. Run setup wizard
/app setup

# 5. Deploy Gitea
/app/enable gitea

# 6. Customize
/app/set environment="GITEA__server__ROOT_URL=http://git.lab:3000" gitea

# 7. Verify
/app/print
# Run your browser to http://10.0.20.1:3000
```

## Conclusion

The RouterOS App catalog transforms container deployment on MikroTik from a multi-step CLI exercise into a guided, repeatable process. For homelab users running capable hardware like the RB5009, CCR2004, or CHR, this means lightweight services can live at the network edge without a separate Linux host.

The sweet spot for Apps is standard services with predictable configurations — Gitea for local code mirrors, Home Assistant for home automation, or similar light workloads. When you need exotic images or full control, the manual `/container` path is still there.

The catalog is evolving. With the 7.24 beta adding Gitea and Home Assistant support, expect more entries in future releases. Whether you are new to RouterOS containers or a veteran of manual veth configuration, give `/app setup` a try — it might save you fifteen minutes and a few firewall headaches.
