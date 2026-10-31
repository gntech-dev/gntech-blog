---
title: "MikroTik VLAN Segmentation — Inter-VLAN Routing, DHCP, and Firewall Rules"
description: "Plan bridge VLAN membership, routed interfaces, DHCP, and separate router-input and forwarding policies, then verify access from real clients."
date: 2026-05-12T11:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [mikrotik, networking, vlan, routeros, homelab]
categories: [homelab, networking]
---

VLANs separate layer-2 networks. Once a router has interfaces in those networks, firewall policy decides which routed connections are allowed. NAT does not grant permission through the firewall.

This guide describes a staged RouterOS 7 lab workflow. It replaces the earlier universal paste-in script with explicit configuration fields and verification gates. Adapt each stage to the installed release and current configuration.

## Verification status

| Area | Evidence and limits |
|---|---|
| Documentation review | Official MikroTik references reviewed on October 31, 2026. |
| Examples | Proposed lab settings, not a captured RB5009 or home-router deployment. |
| Commands | Read-only RouterOS inventory commands; no live parser or device execution performed. |
| Runtime | VLAN filtering, DHCP, firewall isolation, recovery, and WiFi mapping remain untested for this revision. |

## 1. Preserve access and inventory the router

Have a working console or separate recovery path before touching the bridge carrying management traffic. Save a configuration export and an appropriate protected backup outside the router, and document how to recover them. Exports can omit secrets and are not a complete substitute for a recovery plan.

Use [RouterOS configuration management and Safe Mode](https://help.mikrotik.com/docs/spaces/ROS/pages/328155/Configuration+Management). Make small changes and verify them before committing. Safe Mode has limits; it does not replace console access or backups.

Run in the RouterOS terminal:

```routeros
/system resource print
/system package print
/interface print
/interface bridge print detail
/interface bridge port print detail
/interface bridge vlan print detail
/interface vlan print detail
/ip address print
/interface list member print
/ip firewall filter print detail
/ip firewall nat print detail
```

Record the current management path, WAN interface, bridge membership, rule order, and interface lists. Do not delete the existing firewall or add ports already assigned to a bridge.

## 2. Write the port and subnet plan

Example for a small lab, with management on tagged VLAN 99:

| VLAN | Purpose | Example gateway | Access expectation |
|---|---|---|---|
| 99 | Management | 10.0.99.1/24 | Administrative devices only |
| 20 | Servers | 10.0.20.1/24 | Explicit application access |
| 40 | IoT | 10.0.40.1/24 | Only required destinations |
| 70 | Guest | 10.0.70.1/24 | Internet access, no internal access |

The guest VLAN is an example, not a claim about an existing home deployment.

| Port | Role | VLAN handling |
|---|---|---|
| Actual WAN interface | ISP uplink | Outside the LAN bridge in this design |
| ether2 | Lab switch trunk | Tagged 20, 40, 70, 99 |
| ether3 | Dedicated management access port | Untagged 99, PVID 99 |
| ether4 | IoT test access port | Untagged 40, PVID 40 |
| ether5 | Guest test access port | Untagged 70, PVID 70 |

Confirm that these names exist on your device. A PPPoE WAN may be a logical interface, so do not assume the WAN is always ether1.

For the Proxmox uplink, match the switch's actual egress behavior: tagged management needs a corresponding host VLAN interface; untagged management uses a different host design. See the [Proxmox networking guide](/posts/2026-05-08-proxmox-networking-bridges-vlans/).

## 3. Configure the bridge in stages

In WinBox or WebFig, use **Bridge → Ports** and **Bridge → VLANs**. On a disposable lab router, prepare membership before enabling VLAN filtering; on an existing router, review its active configuration rather than creating a parallel bridge blindly.

For each access port, set its PVID, untagged membership, ingress filtering, and an admission policy appropriate for untagged access traffic. For the fully tagged trunk, allow tagged frames and ingress filtering with the required VLAN memberships.

For each routed VLAN, include the bridge CPU port as a tagged member, along with the trunk. Include only that VLAN's intended access ports as untagged members. A VLAN switched entirely between ports does not need router CPU access merely to be switched.

Create the management VLAN interface and address, prepare router-input permissions, and test the intended management path before retiring the old path. Enable VLAN filtering only when the VLAN table and recovery access are ready.

Inspect dynamic as well as static entries. Removing a static VLAN 1 entry alone does not remove dynamic membership caused by PVIDs. Review actual admission and membership settings instead of treating a VLAN number as a security control.

Follow [MikroTik's bridge VLAN table guide](https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge+VLAN+Table) for the detailed fields and CPU-port behavior.

## 4. Add routed interfaces and DHCP deliberately

For each subnet the router serves, create a VLAN interface on the LAN bridge, assign its gateway address, and configure a matching DHCP pool, server, and network record.

| IoT test field | Example |
|---|---|
| VLAN interface | vlan40-iot on the LAN bridge, VLAN ID 40 |
| Router address | 10.0.40.1/24 |
| Pool | 10.0.40.100–10.0.40.199 |
| DHCP server interface | vlan40-iot |
| DHCP network | 10.0.40.0/24 |
| Gateway option | 10.0.40.1 |
| DNS option | An intentionally reachable resolver |

Verify the DHCP server is enabled and valid. Keep static addresses outside dynamic pools or use reservations; a long lease is not a static assignment. If clients use the router as DNS, configure the resolver and permit the required router-input traffic. If they use another subnet's resolver, allow that exact forwarding path.

Repeat for other VLANs after the first client gets the correct lease. See [RouterOS DHCP](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP).

## 5. Define input and forwarding separately

**Input** controls traffic addressed to the router, including administration and router-hosted DNS. **Forward** controls routed client traffic. Protect both; isolating subnets in forward does not protect the router's own services.

Write the intended policy before translating it into rules:

| New connection | Intended result |
|---|---|
| Selected management device → router administration | Allow required services |
| Guest/IoT → router administration | Deny |
| Client → chosen DNS/NTP service | Allow exact required path |
| Selected client → selected server application | Allow exact addresses and ports |
| Guest → internal networks, VPNs, or other local destinations | Deny |
| Guest → intended WAN | Allow subject to policy |
| Other inter-VLAN traffic | Deny |

Review existing rules before adding more. Establish state handling, required management and infrastructure access, specific forwarding exceptions, and explicit terminal drops in the relevant chains. Keep invalid-packet handling and WAN protection consistent with the existing design. Restrict source/interface matches and review address lists, interface lists, VPNs, and destination NAT exceptions.

Do not append a rule below an earlier matching accept or drop and assume it is effective. NAT masquerading changes addresses; it does not override a forward drop. The old expression `dst-address=!0.0.0.0/0` does not identify private networks: the negated prefix covers no IPv4 destinations.

FastTrack and existing tracked connections can affect policy testing. Use fresh connections and review FastTrack against the intended policy. IPv6 requires its own firewall review and tests; IPv4 rules alone do not establish dual-stack isolation.

Consult the [filter reference](https://manual.mikrotik.com/docs/cli-reference/ip/firewall/filter/) and [packet-flow documentation](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/packet-flow-in-routeros/). This policy table is not a complete replacement firewall to paste into a live router.

## 6. Test from real endpoints

Use a laptop or disposable guest actually connected to each test VLAN. A router-originated traceroute exercises a different path from a client's forwarded connection.

```routeros
/interface bridge vlan print detail
/interface bridge port print
/ip dhcp-server print
/ip dhcp-server lease print
/ip firewall filter print stats
/ip route print
```

Verify the assigned subnet, gateway, DNS, and an allowed application connection. Test denied connections to both another VLAN and the router's management service. Compare firewall counter changes while making new connections. A failed ping alone does not prove isolation.

Check that guest internet access works while internal and VPN destinations remain blocked. For wireless guest clients, test same-VLAN client isolation separately: routed firewall rules do not automatically block layer-2 peers.

If access is lost, use the recovery path and known-good configuration. Confirm the restored management connection before making another change.

## WiFi and performance are device-specific

Finish the wired test before mapping SSIDs. Legacy `/caps-man` and newer `/interface wifi` CAPsMAN belong to different stacks. Choose the documentation matching the AP's installed package and forwarding mode; do not mix their commands. Use unique credentials rather than shared example passwords. See [WiFi CAPsMAN](https://manual.mikrotik.com/docs/wireless/wifi/capsman/).

Hardware offload depends on switch chip, software release, and configuration. Check active port flags and measured behavior; do not promise a fixed inter-VLAN throughput. Review [basic VLAN switching](https://manual.mikrotik.com/docs/bridging-and-switching/user-guides/basic-vlan-switching/) for the relevant hardware.

## Continue reading

- [Proxmox bridges and VLANs](/posts/2026-05-08-proxmox-networking-bridges-vlans/) — Match the hypervisor uplink to this port plan.
- [Intel AMT Serial over LAN](/posts/2026-10-30-intel-amt-sol-proxmox/) — Prepare host console recovery.
- [Monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) — Add visibility after verifying the network.
