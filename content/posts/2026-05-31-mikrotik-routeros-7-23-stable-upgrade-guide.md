---
title: "MikroTik RouterOS 7.23: HTTPS, MLAG Fixes, and Upgrade Guide"
description: "RouterOS 7.23 stable: HTTPS-default upgrades, bridge MAC sync for MLAG, WiFi VLAN fixes, and DHCP snooping enhancements. Full changelog and upgrade guide."
date: 2026-05-31T07:30:00-04:00
tags:
  - mikrotik
  - routeros
  - networking
  - homelab
keywords:
  - MikroTik RouterOS 7.23 stable upgrade guide changelog
  - RouterOS 7.23 HTTPS by default upgrade security
  - MikroTik bridge MLAG MAC synchronization fix 7.23
  - RouterOS 7.23 WiFi VLAN dynamic update DHCP snooping
  - How to upgrade MikroTik RouterOS from 7.22 to 7.23
  - RouterOS 7.23 new features app platform container
  - MikroTik RouterOS 7.23 download install steps
summary: "RouterOS 7.23 stable is out with HTTPS-default upgrades, improved MLAG bridge MAC synchronization, WiFi VLAN fixes, and DHCP snooping message-type recognition. This guide covers the changelog, key fixes, and step-by-step upgrade steps for your MikroTik devices."
canonical: "https://blog.gntech.me/posts/mikrotik-routeros-7-23-stable-upgrade-guide/"
---

MikroTik released RouterOS 7.23 to the stable channel on May 25, 2026, bringing several important fixes and security improvements. This release focuses on upgrade security, bridge reliability for MLAG deployments, and WiFi VLAN handling. RouterOS 7.24beta1 followed on May 26 with additional app platform and container improvements, confirming that RouterOS development continues at a steady pace.

This post covers every notable change in 7.23, the step-by-step upgrade process, and post-upgrade verification steps to ensure your network stays stable.

## RouterOS 7.23 HTTPS Upgrade Security Hardening

The headline change in 7.23 is marked with a breaking-change indicator:

> **!)** upgrade — use HTTPS by default when connecting to MikroTik upgrade servers

Before 7.23, RouterOS devices contacted `upgrade.mikrotik.com` over plain HTTP to check for and download firmware updates. An attacker on the local network or upstream path could potentially inject a malicious firmware image via a man-in-the-middle attack. Starting with 7.23, HTTPS is the default transport for all upgrade-server communication.

MikroTik also added the option to configure the HTTP/HTTPS mode:

```
/system upgrade set http=no
```

To enforce HTTPS only (recommended):

```
/system upgrade set http=no
/system upgrade check-update
```

To revert to HTTP if you have compatibility issues with specific network configurations (not recommended):

```
/system upgrade set http=yes
```

Check your current upgrade channel and settings:

```
/system upgrade print
```

This change alone makes 7.23 a must-update for any MikroTik deployment. The security improvement eliminates a long-standing attack surface that affected every auto-upgrade across all RouterOS versions prior to 7.23.

## Bridge MLAG MAC Synchronization Fix

Multi-chassis Link Aggregation (MLAG) lets you connect a single downstream device to two switches for redundancy. The switches present themselves as a single logical LAG endpoint, which requires continuous MAC address synchronization between the peers.

RouterOS 7.23 addresses a significant bug in MLAG deployments:

> **bridge** — improved MAC synchronization for MLAG

In earlier releases, MAC entries learned on one MLAG peer could take too long to propagate to the other peer during failover events. This caused temporary blackholing of traffic — the downstream switch sent frames to switch A, but switch A had already aged out the MAC or hadn't received the update from switch B. Environments using LACP + MLAG on CRS3xx or CRS5xx series switches should notice improved convergence times during link or node failures.

## WiFi VLAN Dynamic Update Fixes

A practical issue for wireless deployments is fixed:

> **bridge** — fixed dynamic VLAN update for WiFi interfaces

When using CAPsMAN or local WiFi interfaces with VLAN tagging, bridge VLAN configuration changes sometimes failed to propagate to WiFi interfaces dynamically. Clients would lose connectivity until a manual interface restart or CAP reboot. RouterOS 7.23 ensures that VLAN membership updates for wireless interfaces apply in real time without service disruption.

If you manage APs with per-VLAN SSIDs or dynamic VLAN assignment via RADIUS, this fix is directly relevant to your setup.

## DHCP Snooping Enhancement

DHCP snooping received a meaningful improvement:

> **bridge** — recognize more DHCP message types when dhcp-snooping is enabled

RouterOS now processes DHCPDECLINE, DHCPRELEASE, and DHCPINFORM messages through snooping. Previously the snooping engine only tracked DHCPACK and DHCPOFFER messages for building the DHCP snooping binding table. This enhancement provides more complete visibility into DHCP activity on your network:

- **DHCPDECLINE** — detects when a client rejects an offered address (potential IP conflict)
- **DHCPRELEASE** — tracks when clients voluntarily release addresses
- **DHCPINFORM** — monitors clients requesting only configuration parameters without lease

Enable DHCP snooping on your bridges if not already done:

```
/interface bridge set [find] dhcp-snooping=yes
```

## Timezone Data and Other Smaller Changes

- **timezone** — updated timezone information from the `tzdata2026b` release. This affects systems using automatic timezone detection or DST transition rules. If you schedule maintenance windows or log analysis around DST boundaries, verify your timezone configuration after upgrading.

- **upgrade** — added the option to configure HTTP/HTTPS modes when connecting (mentioned above).

## Preparing Your MikroTik Device for Upgrade

Before upgrading, run through this checklist:

1. **Back up everything**

```
/export file=backup-pre-723
/system backup save name=backup-pre-723
```

The `/export` gives you a human-readable script. The `.backup` file is binary but preserves everything including passwords and certificates. Keep both on a separate machine.

2. **Check available storage**

```
/system resource print
```

Verify you have at least 20 MB of free space. The 7.23 package is ~18 MB for most architectures.

3. **Identify your architecture**

```
/system resource print
```

Confirm your device model is supported by 7.23 (all current ARM, MIPS, MIPSBE, PPC, and x86 devices are covered).

4. **Check current version**

```
/system resource print
```

Note your current version. If you are on 7.21 or earlier, read the 7.22 changelog for any intermediate changes that might affect your configuration.

## Upgrading to RouterOS 7.23 — Step by Step

### Method 1: WinBox GUI

1. Open WinBox and connect to your MikroTik device
2. Click **System > RouterBOARD** or **System > Upgrade**
3. The upgrade dialog shows available versions — select 7.23 (stable)
4. Click **Download & Upgrade**
5. The device downloads the package, reboots, and comes back online

### Method 2: CLI Upgrade

This is more scriptable and works over SSH:

```
/system upgrade check-update
/system upgrade download
/system reboot
```

The first command checks the latest available version for your configured channel. The second downloads the packages. After reboot, the new version activates automatically.

### Method 3: Manual Package Upload

If your device is isolated from the internet:

1. Download the 7.23 NPK package from [mikrotik.com/download](https://mikrotik.com/download)
2. Upload via WinBox (Files) or SCP:

```
scp routeros-7.23-arm.npk admin@10.0.20.1:
```

3. Reboot the device:

```
/system reboot
```

The package is installed during the boot process.

## Verifying a Successful Upgrade

After the device reboots, confirm everything is working:

```
/system resource print
```

Look for `version: 7.23` in the output.

Check upgrade logs:

```
/log print where topics=upgrade
```

Walk through these functional checks:

- **Bridge connectivity** — ping between VLAN-tagged and untagged interfaces
- **MLAG** — if applicable, trigger a link failure on one peer and measure convergence
- **WiFi clients** — verify wireless clients on VLAN SSIDs connect and maintain DHCP leases
- **DHCP snooping** — check the binding table with `/ip dhcp-snooping print`
- **Routing protocols** — confirm BGP/OSPF neighbors are established
- **Firewall rules** — run your standard connectivity tests in both directions

```
/ping 10.0.20.1 count=5
/ip dhcp-snooping print
/ip route print
```

## Should You Upgrade to RouterOS 7.23?

**Upgrade immediately if:**

- Your devices have direct internet access (HTTPS upgrade fix applies)
- You run MLAG between CRS3xx/5xx switches
- You use CAPsMAN with VLAN-tagged SSIDs
- You rely on DHCP snooping for network security

**Test in staging first if:**

- You run production containers on RouterOS (consider beta testing with 7.24beta1)
- You have custom firewall scripts or BGP policies (safe in 7.23, but always test)
- Your devices are in remote locations without console access

## Looking Ahead to RouterOS 7.24beta

RouterOS 7.24beta1 was released the day after 7.23 stable, on May 26, 2026. Early changes include:

- **adlist** — improved service stability when adjusting adlist configuration
- **app** — added `network-outgoing` permission for app platform apps

If you run the RouterOS container feature or the adlist/AdBlock functionality, the 7.24 development branch is worth watching. The `network-outgoing` permission for apps is particularly interesting for deploying custom monitoring or integration tools directly on your MikroTik device.

## Conclusion

RouterOS 7.23 is a focused stable release that rounds out the bridge and upgrade security improvements introduced in the 7.22 cycle. The HTTPS-default upgrade change is the most impactful — it closes a security gap that affected every auto-upgrade scenario since RouterOS gained internet-based upgrade capabilities. Combined with MLAG MAC synchronization fixes and WiFi VLAN dynamic updates, 7.23 is a solid, recommended upgrade for all production MikroTik devices.

Download RouterOS 7.23 at [mikrotik.com/download](https://mikrotik.com/download) or check for it via your device's built-in upgrade system. For a searchable changelog across all RouterOS versions, check out [MikroTik Changelog Tracker](https://mct.hextet.net/) by Hextet Systems.
