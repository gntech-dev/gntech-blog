---
title: "Homelab 10GbE Networking — Hardware, MikroTik Switch Setup, and Performance Tuning"
description: "Plan and deploy 10GbE networking for your homelab — MikroTik CRS switch configuration, SFP+ cabling choices, Proxmox host integration, and Linux NIC tuning for maximum throughput."
date: 2026-06-20T10:30:00-04:00
tags:
  - networking
  - mikrotik
  - homelab
  - linux
  - hardware
keywords:
  - Homelab 10GbE networking guide MikroTik Proxmox setup
  - MikroTik CRS3xx 10GbE switch SFP+ configuration best practices
  - SFP+ DAC cable vs fiber transceiver homelab comparison
  - Proxmox 10GbE NIC tuning Linux performance ethtool
  - Linux 10GbE network interface irqbalance RSS queue optimization
  - Homelab 10GbE switch MikroTik CRS309 CRS326 CRS317 comparison
  - 10 gigabit homelab network hardware planning cost efficient
summary: "Planning a 10GbE upgrade for your homelab? From MikroTik CRS switches and SFP+ cabling to Proxmox NIC tuning, this guide covers the hardware decisions, configs, and performance optimizations you need."
lastmod: 2026-10-30T12:00:00-04:00
---

A 10GbE upgrade can help when backups, storage traffic, or VM migrations saturate a 1GbE link. Start with a measured bottleneck, choose compatible hardware, and validate the network before changing TCP settings or enabling jumbo frames.

This example connects two Proxmox hosts through a MikroTik CRS switch. It uses ordinary 1500-byte MTU first, a separate management VLAN, and explicit access-port PVIDs.

## Hardware and Example Layout

Use a CRS model with enough SFP+ ports, supported SFP+ NICs, and compatible DAC cables or optical modules. Check each device's specification for supported speeds, optics, hardware offloading, power, and cooling. A 25GbE NIC does not necessarily work with every 10GbE cable or module.

| Connection | Switch port | VLAN handling |
|---|---|---|
| Upstream router | `sfp-sfpplus1` | Tagged VLAN 20 and 99 |
| Proxmox host A | `sfp-sfpplus3` | Untagged VLAN 20 |
| Proxmox host B | `sfp-sfpplus4` | Untagged VLAN 20 |
| Switch management | Bridge CPU through `vlan99` | Tagged VLAN 99 |

Example addresses: switch `10.0.99.2/24`, upstream management gateway `10.0.99.1`, hosts `10.0.20.10/24` and `10.0.20.20/24`. These are sample values, not discovery results. Configure the upstream router's tagged VLANs and management access before enabling filtering.

## 1. Back Up and Prepare the Switch

Use a local console or an independent management connection and RouterOS Safe Mode. These commands assume a spare switch with no existing `bridge10g`, port memberships, or conflicting IP addresses. Inspect and adapt an existing deployment instead of pasting the whole example into it.

```routeros
/export file=before-10gbe
/system backup save name=before-10gbe
/interface bridge print
/interface bridge port print
/ip address print
```

Download the backups before continuing. A binary backup is device-specific and may contain sensitive data. This guide does not require a factory reset. RouterOS `run-after-reset` expects a script filename, not inline configuration text.

## 2. Create the Bridge with Filtering Disabled

```routeros
/interface bridge add name=bridge10g protocol-mode=rstp vlan-filtering=no
/interface bridge port add bridge=bridge10g interface=sfp-sfpplus1 hw=yes ingress-filtering=yes frame-types=admit-only-vlan-tagged
/interface bridge port add bridge=bridge10g interface=sfp-sfpplus3 hw=yes pvid=20 ingress-filtering=yes frame-types=admit-only-untagged-and-priority-tagged
/interface bridge port add bridge=bridge10g interface=sfp-sfpplus4 hw=yes pvid=20 ingress-filtering=yes frame-types=admit-only-untagged-and-priority-tagged
/interface bridge vlan add bridge=bridge10g vlan-ids=20 tagged=sfp-sfpplus1 untagged=sfp-sfpplus3,sfp-sfpplus4
/interface bridge vlan add bridge=bridge10g vlan-ids=99 tagged=bridge10g,sfp-sfpplus1
/interface vlan add name=vlan99 interface=bridge10g vlan-id=99
/ip address add address=10.0.99.2/24 interface=vlan99
/interface bridge set [find name=bridge10g] frame-types=admit-only-vlan-tagged
```

The access ports need `pvid=20` to classify untagged **incoming** traffic. Listing a port as `untagged` in the VLAN table controls outgoing tagging; it does not replace the PVID.

The bridge itself is included in VLAN 99's tagged list because switch management needs CPU access on that VLAN. VLAN 20 is switched between ports without giving the switch CPU a VLAN 20 address.

## 3. Enable Filtering and Check Access

```routeros
/interface bridge set [find name=bridge10g] vlan-filtering=yes
/interface bridge port print
/interface bridge vlan print detail
/interface ethernet monitor sfp-sfpplus1 once
```

Verify management connectivity from an authorized VLAN 99 client before leaving Safe Mode. The `H` flag in bridge-port output indicates active hardware offloading; `hw=yes` requests it. Actual support depends on the switch chip, RouterOS version, and features in use.

If management fails, use the independent connection or Safe Mode rollback. Do not keep adding VLAN rules through an unstable management session.

## 4. Connect the Proxmox Hosts

Check the NIC driver, interface name, and negotiated speed on each host:

```bash
lspci -nnk | grep -A3 -i ethernet
ip -br link
ethtool enp4s0f0
```

Replace `enp4s0f0` with the actual interface. Drivers normally load automatically when supported; do not append duplicate module entries as a default step.

The switch's access ports deliver untagged VLAN 20. This **additional** Proxmox bridge therefore needs no VLAN subinterface:

```text
auto enp4s0f0
iface enp4s0f0 inet manual
    mtu 1500

auto vmbr10
iface vmbr10 inet static
    address 10.0.20.10/24
    mtu 1500
    bridge-ports enp4s0f0
    bridge-stp off
    bridge-fd 0
```

Use `10.0.20.20/24` on host B. Do not add a second default gateway. This example assumes VLAN 20 is not already configured on another interface on the same host.

Back up the configuration first:

```bash
sudo cp -a /etc/network/interfaces /root/interfaces.before-10gbe
```

Apply the additional bridge through the Proxmox network editor, review the pending changes, and use **Apply Configuration** from a console-accessible session. Do not overwrite the complete existing interfaces file with this fragment.

## 5. Measure Before Tuning

Install `iperf3` on both hosts if needed. On host B, start a server bound to the storage-network address:

```bash
iperf3 -s -B 10.0.20.20
```

Allow TCP port 5201 only between the test hosts in their firewalls. On host A:

```bash
iperf3 -c 10.0.20.20 -t 30
iperf3 -c 10.0.20.20 -P 4 -t 30
iperf3 -c 10.0.20.20 -P 4 -t 30 -R
```

Stop the server with Ctrl+C afterward. Record the measured throughput, CPU use, retransmissions, and link errors. Values near line rate are possible, but throughput depends on the hosts and protocol overhead; an example number is not a benchmark from your hardware.

Inspect errors before and after each test:

```bash
ethtool -S enp4s0f0 | grep -Ei 'crc|error|drop|miss'
ip -s link show enp4s0f0
```

Look for **increasing** counters. An old nonzero counter alone does not establish an active fault. Test network throughput separately from storage throughput: disks, compression, encryption, and application behavior can limit backups even when the network is fast.

## Optional: Jumbo Frames and LACP

Keep MTU 1500 unless testing demonstrates a reason to change it. For MTU 9000, every endpoint, bridge, VLAN interface, and switch path must support the required frame size. Check the switch's **L2MTU** and device-specific limits; changing a physical interface's IP MTU alone does not prove the switching path supports jumbo frames.

After configuring the entire path, test IPv4 without fragmentation:

```bash
ping -M do -s 8972 -c 4 10.0.20.20
```

If it fails, revert the path consistently to MTU 1500 and investigate. Do not use jumbo frames as an unexplained default.

LACP is a separate design choice. Remove member ports from standalone bridge membership before adding a bond, and put the bond itself into the VLAN table. Configure both ends consistently and verify switch-chip offload support. LACP distributes flows; it does not automatically double the throughput of one TCP connection.

## Troubleshooting

- **No link:** verify cable/module compatibility, NIC firmware, and supported link modes at both ends. Use RouterOS tab completion for version-specific speed names rather than copying an old `advertise` value.
- **No connectivity on access ports:** check PVIDs, VLAN membership, upstream routing, and host firewall rules.
- **Low throughput:** compare single-stream and parallel results, inspect CPU load and increasing error counters, and test a known-good cable.
- **Flapping:** inspect switch and NIC logs before changing driver flags. Private `ethtool` flags and EEE settings are device-specific.
- **Remote management lost:** use the console or Safe Mode rollback. Restore the reviewed configuration from your backup rather than resetting blindly.

Do not apply arbitrary IRQ masks, ring sizes, BBR, or large TCP buffers as a universal 10GbE fix. Inspect available settings and test one change at a time against the baseline.

## References

- [MikroTik: Bridge VLAN Table](https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge+VLAN+Table)
- [MikroTik: Bridging and Switching](https://help.mikrotik.com/docs/spaces/ROS/pages/328068/Bridging+and+Switching)
- [Proxmox: Network Configuration](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#sysadmin_network_configuration)
- [iperf3 documentation](https://software.es.net/iperf/)
