---
title: "OPNsense Virtual Firewall on Proxmox — Homelab Security"
description: "Deploy OPNsense as a virtual firewall in Proxmox for full network segmentation, VLAN routing, IDS/IPS with Suricata, and WireGuard VPN — real configs included."
date: 2026-06-15T14:00:00-04:00
tags:
  - proxmox
  - opnsense
  - firewall
  - networking
  - homelab
keywords:
  - OPNsense virtual firewall Proxmox homelab deployment
  - Proxmox OPNsense VM passthrough NIC configuration
  - OPNsense VLAN routing inter-VLAN firewall rules
  - OPNsense IDS IPS Suricata configuration homelab
  - OPNsense WireGuard VPN server setup Proxmox
  - Virtual firewall network segmentation homelab security
  - OPNsense VLANs Proxmox bridge trunk port
summary: "Deploy OPNsense as a virtualized firewall on Proxmox with VLAN segmentation, Suricata IDS/IPS, and WireGuard VPN. Real VM configs, bridge setup, firewall rules, and performance tuning."
canonical: "https://blog.gntech.me/posts/opnsense-virtual-firewall-proxmox-homelab/"
---

Firewalls are the single most important security device in any network. For years, dedicated hardware was the only serious option — a Protectli, a Netgate, or a MikroTik running the show. But if you already run Proxmox, virtualizing your firewall is cheaper, more flexible, and arguably more secure when done right.

This guide covers a production-grade OPNsense deployment as a Proxmox VM with:

- **VM setup** with virtio NICs and optimal resource allocation
- **WAN/LAN bridge topology** on the Proxmox host
- **VLAN trunking** and inter-VLAN firewall rules
- **Suricata IDS/IPS** inline on LAN interfaces
- **WireGuard VPN** for remote access
- **DNS, DHCP, and security hardening**

## Why OPNsense for a Virtualized Firewall?

OPNsense is a FreeBSD-based firewall that started as a pfSense fork but has since surpassed it in several areas: a cleaner web UI, regular 2-week release cycles, built-in WireGuard, native Suricata in business edition, and a plugin system without bloat. For a Proxmox homelab, it fills the gap between MikroTik RouterOS (powerful but CLI-heavy) and pfSense (stable but slower-moving).

Compared to running a MikroTik virtualized, OPNsense gives you:
- **Full IDS/IPS** with Suricata or Zenarmor (Sensei)
- **WireGuard** built into the kernel (MikroTik added it later, but CLI-only initially)
- **Unbound DNS** with DNSSEC, blocklists, and overrides baked in
- **VLAN management** through a web GUI — no `/interface vlan` commands

## Proxmox VM Setup for OPNsense

### VM Specifications

Create the VM with these specs:

- **CPU**: 2 vCPU cores (host type for AES-NI access)
- **RAM**: 4 GB minimum, 8 GB if running Suricata in IPS mode
- **Disk**: 32 GB on fast storage (ZFS mirror or NVMe)
- **NIC1 (WAN)**: VirtIO (paravirtualized) — bridged to vmbr0
- **NIC2 (LAN)**: VirtIO — bridged to vmbr1
- **Enable hardware virtualization**: check "Processor" options for aes flags

### Proxmox Bridge Configuration

Before creating the VM, set up two bridges on your Proxmox host. Modify `/etc/network/interfaces`:

```bash
# WAN — connected to your modem/ONT
auto vmbr0
iface vmbr0 inet manual
    bridge-ports enp3s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes

# LAN — trunk port to your switch
auto vmbr1
iface vmbr1 inet manual
    bridge-ports enp4s0
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware yes
```

**Critical detail**: do NOT assign an IP address to either bridge on the Proxmox host. The host's management IP should be on a VLAN interface within OPNsense. This keeps Proxmox behind the firewall.

### Install OPNsense

```bash
# Download the latest OPNsense ISO
wget https://mirror.ams1.nl.leaseweb.net/opnsense/releases/25.1/OPNsense-25.1-amd64.iso

# Import ISO to Proxmox storage
qm importdisk 100 OPNsense-25.1-amd64.iso local-zfs

# Or attach the ISO directly to the VM and boot from it
```

Boot the VM, attach to console, and run through the installer:
1. Select ZFS as filesystem (auto layout)
2. Set root password
3. Reboot, remove ISO

After first reboot, assign interfaces:
- **WAN**: vtnet0 (your NIC1 / vmbr0)
- **LAN**: vtnet1 (your NIC2 / vmbr1)

Set the LAN IP to `10.0.0.1/24` temporarily for first web GUI access, then immediately change it to a more structured IP like `10.0.10.1/24` for your management VLAN.

### VLAN Trunk Configuration

From the OPNsense web GUI, create VLANs on the LAN interface (**Interfaces → Other Types → VLAN**):

| VLAN ID | Name | Description |
|---------|------|-------------|
| 10 | mgmt | Management — servers, hypervisors |
| 20 | trusted | Trusted user devices, workstations |
| 30 | iot | IoT devices — cameras, sensors, smart plugs |
| 40 | guest | Guest WiFi — internet only, isolated |
| 99 | dmz | DMZ — public-facing services |

After creating VLANs, assign each one (**Interfaces → Assignments**), enable them, and set IPs/DHCP:

```text
mgmt:   10.0.10.1/24
trusted: 10.0.20.1/24
iot:     10.0.30.1/24
guest:   10.0.40.1/24
dmz:     10.0.99.1/24
```

## Inter-VLAN Firewall Rules — Lock It Down

By default, OPNsense allows all traffic. You need explicit deny rules. The approach:

1. **Default deny all inter-VLAN** traffic at the top of each VLAN interface
2. **Allow established/related** state tracking
3. **Explicit allow** only what's needed

Example — IoT VLAN rules (interface: IoT, direction: in):

```text
# Rule 1: Allow established traffic back in
IPv4 * * * * * * * * Keep state

# Rule 2: Block all inter-VLAN by default
IPv4 * * * 10.0.0.0/8 * * * * * * Block

# Rule 3: Allow IoT to reach DNS on mgmt VLAN
IPv4 UDP * * 10.0.10.53 53 * * * * Allow

# Rule 4: Allow Internet access
IPv4 * * * !10.0.0.0/8 * * * * * Allow
```

The `!10.0.0.0/8` in Rule 4 means "destination is NOT in RFC1918 space" — internet only. This keeps IoT devices from phoning home to your servers while still getting firmware updates.

Guest VLAN rules — allow DNS and internet only:

```text
# Allow DNS (OPNsense resolver)
IPv4 UDP * * 10.0.10.1 53 * * * * Allow

# Block all private ranges
IPv4 * * * 10.0.0.0/8 * * * * * Block
IPv4 * * * 172.16.0.0/12 * * * * * Block
IPv4 * * * 192.168.0.0/16 * * * * * Block

# Allow internet
IPv4 * * * * * * * * Allow
```

## Suricata IDS/IPS — Inline on LAN

Install the Suricata plugin: **System → Firmware → Plugins → os-suricata**.

### Suricata Configuration

Navigate to **Services → Suricata → Settings**:

```text
Interface: vtnet1 (LAN parent — captures all VLAN traffic)
Pattern match limit: 50000000
Defrag: enabled
Stream engine: enabled
Inline mode: IPS (enabled)
Rule categories:
  - enable: emerging-exploit, emerging-malware, emerging-attack-response
  - enable: emerging-policy, emerging-scan
  - disable: emerging-info (noise, false positives)
  - disable: audio, video, chat (not relevant)
```

After enabling, go to the **Updates** tab and download the Emerging Threats Open ruleset:

```bash
# OPNsense auto-downloads on schedule, but manual download after config
# The output log lives at /var/log/suricata/suricata.log
```

### Reducing False Positives

Suricata in IPS mode will block traffic matching rules. Start in IDS (alert-only) mode for 48 hours:

```bash
# Check alerts via web GUI
Services → Suricata → Alerts

# Add suppressions for known local traffic patterns
# Services → Suricata → Suppress → Add pass rule
# Example: suppress SID:2013026 (DNS query for local domain)
```

Common suppressions for homelabs:
- **SMB traffic** between your workstation and NAS
- **Plex** media streaming to LAN clients
- **DNS queries** to your internal resolver

After tuning, switch to IPS mode. Suricata IPS on a 4-core VM handles 500 Mbps comfortably. For 1 Gbps, give it 4 vCPU and verify your NICs use VirtIO (not e1000).

## WireGuard VPN Server

OPNsense includes WireGuard in the base install — no plugin needed since 25.1. Navigate to **VPN → WireGuard**.

### Server Config

```text
# Instance settings
Enabled: yes
Listen port: 51820
Tunnel address: 10.200.0.1/24
Private key: (auto-generated, back this up)
MTU: 1420
DNS servers: 10.0.10.1, 1.1.1.1
```

### Peer Config

```text
# Peer settings
Enabled: yes
Public key: (from your client, e.g., `wg genkey | tee privatekey | wg pubkey > publickey`)
Preshared key: (generate with `wg genpsk`)
Allowed IPs: 10.200.0.2/32, 10.0.0.0/8
```

The Allowed IPs include the WireGuard tunnel address *and* your entire LAN. This means when connected, your client can reach any device in any VLAN.

### WAN Firewall Rule

```text
# Firewall → Rules → WAN → Add
Protocol: UDP
Source: any
Destination: WAN address
Destination port: 51820
Description: Allow WireGuard
```

### NAT for VPN Clients

If you want VPN clients to reach the internet through OPNsense, add an outbound NAT rule:

```text
Firewall → NAT → Outbound → Add
Interface: WAN
Source: 10.200.0.0/24
Destination: any
NAT address: WAN address
Static port: no
```

## DNS and DHCP Best Practices

OPNsense runs Unbound as the local DNS resolver. Enable it with blocklists:

**Services → Unbound DNS → General**:
```text
Enable: yes
Port: 53 (leave default)
DNSSEC: enabled
Register DHCP leases: yes
Register DHCP static mappings: yes
```

**DNS over TLS (DoT)** for upstream queries:
```text
DNS Query Forwarding: enabled
DNS Query Forwarding servers:
  1.1.1.1@853  (Cloudflare)
  9.9.9.9@853  (Quad9)
```

**DHCP static mappings** per VLAN:
```text
Services → DHCPv4 → [mgmt]
Create static mapping for each server:
  proxmox1 → 10.0.10.30
  nas-01   → 10.0.10.31
  docker1  → 10.0.10.32
```

With "Register DHCP static mappings" enabled, Unbound automatically adds A and PTR records for every static lease. No manual `/etc/hosts` editing.

## Security Hardening Checklist

Before putting this firewall into production, lock it down:

- **System → Settings → Administration**: disable web GUI on WAN and change port to 8443
- **System → Settings → SSH**: bind to LAN only, disable password auth, use key-only
- **System → Access → Users**: enable 2FA (TOTP) for admin and your user
- **Firewall → Settings**: disable ICMP redirects, disable directed broadcast
- **System → Firmware → Settings**: set update branch to "Business" (stable, 2-week cycle)
- **System → Settings → Tunables**: enable TCP SYN cookies, set `net.inet.tcp.blackhole` to `2`

To verify your hardening from outside, use a VPS or mobile hotspot (not on your network):

```bash
nmap -sS -p 22,443,8443 <your-public-ip>
# All should show filtered
```

## Monitoring and Logging

OPNsense's firewall live view is useful for debugging, but for long-term retention, export logs:

**Syslog to Loki/Grafana** — configure in **Services → Syslog → Settings**:

```text
Syslog server: 10.0.10.50:514 (your Grafana Alloy/Loki host)
Transport: UDP
Syslog facility: local7
Content filter: enabled — log only blocked traffic and errors
```

**Netflow export** — install `os-netflow` plugin and send to Grafana via:

```text
Services → Netflow → General
Protocol: UDP
Destination: 10.0.10.50:2055
Engine ID: 1
```

## Conclusion

Virtualizing OPNsense on Proxmox is not a compromise. With VirtIO NICs, proper bridge topology, and enough resources for Suricata, your virtual firewall outperforms many dedicated appliances. The real value is in the flexibility — you can snapshot the firewall VM before config changes, clone it for testing, and migrate it between Proxmox hosts.

For your first week, run Suricata in IDS-only mode while tuning down false positives. Lock down WAN access to the admin GUI immediately. Start with management and IoT VLANs, then expand to guest WiFi and DMZ as you gain confidence.

Next steps: add CARP for high-availability with a second Proxmox host, integrate with Authentik for LDAP authentication, and set up Zenarmor (Sensei) for application-level traffic control.
