---
title: "systemd-networkd Homelab Networking — Bridges, VLANs, Bonds"
description: "Configure bridges, VLAN interfaces, and bond links with systemd-networkd on Debian 13 and Ubuntu 24.04. Practical homelab networking without NetworkManager or netplan."
date: 2026-06-07T07:00:00-04:00
tags:
  - linux
  - networking
  - selfhosting
  - homelab
  - docker
keywords:
  - systemd-networkd bridge VLAN configuration homelab guide
  - Linux networkd bridge setup KVM virtual machines Debian 13
  - systemd-networkd VLAN interface configuration Ubuntu 24.04
  - NetworkManager replacement systemd-networkd homelab server
  - systemd-networkd bond interface link aggregation configuration
  - Debian 13 systemd-networkd bridge VLAN trunk port setup
  - Linux systemd-networkd .network .netdev configuration examples
summary: "Configure bridges, VLANs, and bond interfaces using systemd-networkd on Debian 13 and Ubuntu 24.04. Real configuration files for KVM/Proxmox bridges, VLAN trunking, and link aggregation."
canonical: "https://blog.gntech.me/posts/systemd-networkd-homelab-networking-bridges-vlans-bonds/"
---

## Why systemd-networkd for Homelab Networking

If you've installed Debian 13 "Trixie" or Ubuntu 24.04 recently, your system already ships with **systemd-networkd** installed and ready. It's the default network manager on Arch Linux too. Despite this, many homelab guides still default to NetworkManager, netplan, or the legacy `/etc/network/interfaces` — and then hit a wall the moment they need a Linux bridge for KVM, a VLAN interface for network segmentation, or a bond for link aggregation.

systemd-networkd handles all of these natively with three configuration file types:

- **`.link`** — matches hardware devices by MAC, driver, or path and sets link-level parameters (MTU, MAC address, wake-on-lan)
- **`.netdev`** — defines virtual network devices (bridges, bonds, VLANs, VRFs, VXLANs)
- **`.network`** — applies IP addressing, routing, DNS, DHCP, and bridge port membership to any matched link

The configuration lives in `/etc/systemd/network/` and follows simple lexicographic ordering rules. No daemon restart required — `networkctl reconfigure` applies changes on the fly.

For a homelab hypervisor running Proxmox, KVM, or Docker on a Debian 13 host, switching to systemd-networkd means you get predictable, boot-order-independent networking with zero GUI dependencies.

## Checking Your Current Network State

Before changing anything, survey what you're running today:

```bash
# Is systemd-networkd running?
systemctl is-active systemd-networkd

# List all links with their current configuration source
networkctl list

# Detailed status of a specific interface
networkctl status enp2s0

# What else is managing your network?
systemctl list-units --type=service | grep -iE 'network|netplan|NetworkManager'
```

If `systemd-networkd` isn't active, you're likely running NetworkManager (common on Ubuntu Server desktop-flavored installs) or netplan (Ubuntu default up to 24.04). Both can coexist with systemd-networkd on different interfaces, but for simplicity, pick one — systemd-networkd — for all host-level networking.

## Preparing the Host: Disabling Conflicting Managers

You don't need to uninstall anything. Just stop and disable the services you aren't using:

```bash
# Disable NetworkManager
systemctl stop NetworkManager
systemctl disable NetworkManager

# Disable netplan (Ubuntu)
systemctl stop netplan-ovs-cleanup 2>/dev/null
systemctl disable netplan-ovs-cleanup 2>/dev/null
mv /etc/netplan/01-netcfg.yaml /etc/netplan/01-netcfg.yaml.bak 2>/dev/null

# Disable legacy ifupdown (Debian)
systemctl mask networking.service 2>/dev/null
mv /etc/network/interfaces /etc/network/interfaces.bak 2>/dev/null

# Enable and start systemd-networkd
systemctl enable systemd-networkd
systemctl start systemd-networkd

# Also enable systemd-resolved for DNS
systemctl enable systemd-resolved
systemctl start systemd-resolved
```

If you're on Ubuntu, also unlink the default `/etc/resolv.conf` so systemd-resolved manages DNS:

```bash
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

## Linux Bridge Configuration for KVM and Docker

The most common homelab networking scenario: you have a single physical NIC and need a **Linux bridge** so VMs and containers can share the host's connection to your LAN.

### Bridge Virtual Device — br0.netdev

Create `/etc/systemd/network/10-br0.netdev`:

```ini
[NetDev]
Name=br0
Kind=bridge
MACAddress=52:54:00:ab:cd:01
```

Setting a static MAC on the bridge is optional but recommended — it prevents the MAC from changing on reboot, which would break DHCP reservations and firewall rules.

### Bridge Port Membership — 20-br0-enp2s0.network

Create `/etc/systemd/network/20-br0-enp2s0.network`:

```ini
[Match]
Name=enp2s0

[Network]
Bridge=br0
```

That's it. The physical interface `enp2s0` becomes a bridge port. No IP address on the physical NIC — all addressing happens on the bridge.

### Bridge IP Configuration — 30-br0.network

Create `/etc/systemd/network/30-br0.network`:

```ini
[Match]
Name=br0

[Network]
DHCP=ipv4
DNS=1.1.1.1
DNS=8.8.8.8
IPv6AcceptRA=yes

[DHCPv4]
RouteMetric=100
UseDomains=true
```

For a static IP instead:

```ini
[Match]
Name=br0

[Network]
Address=10.0.20.50/24
Gateway=10.0.20.1
DNS=10.0.20.1
DNS=1.1.1.1
IPv6AcceptRA=no
```

Apply the configuration:

```bash
networkctl reconfigure br0
networkctl reconfigure enp2s0
```

Verify bridge state:

```bash
networkctl status br0
bridge link show
bridge vlan show
```

KVM guests can now attach their virtual NICs directly to `br0` via bridged networking, and Docker can be configured to use `br0` through macvlan or ipvlan.

## VLAN Interface Configuration for Network Segmentation

If your upstream switch delivers tagged VLANs, you need VLAN interfaces on the host. The standard pattern: attach the VLAN to the bridge so all VMs on the bridge can reach their respective VLAN — or attach VLANs directly to the physical NIC for host-only segmentation.

### VLAN on Physical NIC — VLAN 10 Management

Create `/etc/systemd/network/10-vlan10.netdev`:

```ini
[NetDev]
Name=vlan10
Kind=vlan

[VLAN]
Id=10
```

Then `/etc/systemd/network/30-vlan10.network`:

```ini
[Match]
Name=vlan10

[Network]
Address=10.0.10.5/24
Gateway=10.0.10.1
DNS=10.0.10.1
```

Attach the VLAN to the physical uplink by adding the parent reference in a .network file:

Create `/etc/systemd/network/20-enp2s0-vlan10.network`:

```ini
[Match]
Name=enp2s0

[Network]
VLAN=vlan10
```

Repeat for VLAN 20 (services) and VLAN 30 (IoT):

```bash
# /etc/systemd/network/11-vlan20.netdev
[NetDev]
Name=vlan20
Kind=vlan

[VLAN]
Id=20
```

And similarly for vlan30 with `Id=30`.

### VLAN Trunk on a Bridge (for VM access to multiple VLANs)

For KVM guests that need access to multiple VLANs, attach the VLAN interfaces to the bridge:

Create `/etc/systemd/network/10-br0.netdev` (add to existing):

```ini
[NetDev]
Name=br0
Kind=bridge
```

No VLAN reference in the bridge .netdev. Instead, modify `20-enp2s0.network` to list VLANs on the bridge port:

```ini
[Match]
Name=enp2s0

[Network]
Bridge=br0
VLAN=vlan10
VLAN=vlan20
VLAN=vlan30
```

And create .network files for each VLAN that set the bridge as their parent:

```ini
# /etc/systemd/network/40-vlan10-bridge.network
[Match]
Name=vlan10

[Network]
Bridge=br0
```

This way, the host bridge `br0` carries untagged traffic, while VLANs 10, 20, and 30 are trunked through the bridge. VMs attached to `br0` can be configured with VLAN filtering in libvirt.

Apply everything:

```bash
networkctl reconfigure enp2s0
networkctl reconfigure vlan10
networkctl reconfigure vlan20
networkctl reconfigure vlan30
```

Verify VLAN tagging:

```bash
bridge vlan show
```

Output should show the PVID on the bridge port and the tagged VLANs:

```
port              vlan-id
enp2s0            1 PVID Egress Untagged
                  10
                  20
                  30
br0               1 PVID Egress Untagged
```

## Bond (Link Aggregation) Configuration

For servers with dual NICs, a bond provides redundancy and increased throughput. systemd-networkd supports all standard bonding modes — for homelab use, `802.3ad` (LACP) is the standard choice when your switch supports it.

### Bond Virtual Device — bond0.netdev

Create `/etc/systemd/network/10-bond0.netdev`:

```ini
[NetDev]
Name=bond0
Kind=bond

[Bond]
Mode=802.3ad
MIIMonitorSec=100ms
UpDelaySec=200ms
DownDelaySec=200ms
LACPTransmitRate=fast
```

### Bond Slave Interfaces

Create `/etc/systemd/network/20-enp2s0-bond.network`:

```ini
[Match]
Name=enp2s0

[Network]
Bond=bond0
```

Create `/etc/systemd/network/21-enp3s0-bond.network`:

```ini
[Match]
Name=enp3s0

[Network]
Bond=bond0
```

### Bond IP Configuration

Create `/etc/systemd/network/30-bond0.network`:

```ini
[Match]
Name=bond0

[Network]
DHCP=ipv4
```

Or static:

```ini
[Match]
Name=bond0

[Network]
Address=10.0.20.51/24
Gateway=10.0.20.1
DNS=10.0.20.1
```

Apply:

```bash
networkctl reconfigure bond0
networkctl reconfigure enp2s0
networkctl reconfigure enp3s0
```

Verify bonding:

```bash
cat /proc/net/bonding/bond0
networkctl status bond0
```

Look for `MII Status: up` on each slave and `Bonding Mode: IEEE 802.3ad Dynamic link aggregation`.

### Combining Bond and Bridge

Need both bonding and bridging? Layer them — bond first, bridge on top:

`10-bond0.netdev` as above, then `10-br0.netdev` with `Kind=bridge`, and:

```ini
# 20-bond0-bridge.network
[Match]
Name=bond0

[Network]
Bridge=br0
```

This gives you a bonded, bridged setup where VMs, LXC containers, and Docker can all share redundant uplinks.

## Applying Changes and Rolling Back

systemd-networkd applies configuration files in lexicographic order. The standard naming convention is `XX-name.type` where `XX` is a two-digit priority — lower numbers apply first.

**Apply a single interface:**

```bash
networkctl reconfigure br0
```

**Reload all configuration:**

```bash
systemctl restart systemd-networkd
```

**Roll back a change:** simply rename or remove the .network or .netdev file and reconfigure:

```bash
mv /etc/systemd/network/30-br0.network{,.bak}
networkctl reconfigure br0
```

**Common gotcha:** if you reconfigure the interface carrying your SSH session, you get locked out. Always test changes through an out-of-band management interface (IPMI, iDRAC, serial console), or use `at now + 1 minute` to schedule a rollback before applying breaking config changes:

```bash
echo "mv /etc/systemd/network/30-br0.network.bak /etc/systemd/network/30-br0.network; networkctl reconfigure br0" | at now + 2 minutes
```

## Conclusion

systemd-networkd is the most straightforward way to manage Linux networking in a homelab. Its declarative `.network` and `.netdev` files make bridge, VLAN, and bond configuration predictable and repeatable — no daemon GUI, no Python-generated config files, just clean INI-style files that work on every modern distro.

For a Debian 13 hypervisor running KVM, LXC, and Docker, the combination of a Linux bridge with tagged VLAN interfaces and optional LACP bonding covers every networking scenario you'll encounter. And because systemd-networkd is built into systemd itself, there's no additional package to install or maintain.

Next time you provision a new homelab host, skip NetworkManager and write a `.network` file instead. Your future self — the one adding a second NIC or creating a VLAN trunk — will thank you.
