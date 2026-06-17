---
title: "FRRouting BGP on Linux — Dynamic Routing for Your Homelab Network"
description: "Deploy FRRouting on Linux for BGP dynamic routing in your homelab. Covers installation, iBGP/eBGP peering with MikroTik, route filtering, and OSPF redistribution with real configs."
date: 2026-05-31T12:00:00-04:00
tags:
  - networking
  - linux
  - homelab
  - bgp
  - routing
keywords:
  - FRRouting BGP Linux homelab deployment guide
  - BGP peering FRR MikroTik RouterOS dynamic routing
  - iBGP eBGP configuration FRRouting Linux server
  - FRR OSPF BGP route redistribution homelab setup
  - BGP route filtering prefix-list FRR configuration
  - dynamic routing protocol FRRouting installation configuration
  - Linux FRR BGP community tagging route-maps
summary: "Deploy FRRouting on Linux for BGP dynamic routing in your homelab. Covers FRR installation, iBGP/eBGP peering with MikroTik, route filtering, prefix-lists, and OSPF-to-BGP redistribution with production-ready configs."
canonical: "https://blog.gntech.me/posts/frrouting-bgp-linux-dynamic-routing-homelab/"
---

## Why Run BGP in Your Homelab

BGP is the routing protocol that runs the internet, but it is not just for ISPs and data centers. Running BGP in your homelab unlocks several practical capabilities that static routes cannot match.

If you have multiple routers, hypervisors with virtual routers, or a mix of MikroTik devices and Linux servers, BGP gives you automatic failover, traffic engineering with local-preference and community tags, and a hands-on learning environment for one of the most important protocols in networking.

FRRouting (FRR) is the modern fork of the Quagga routing suite. It is actively maintained, packaged for Debian and Ubuntu, and features a Cisco-style CLI through `vtysh`. This guide walks through deploying FRR on a Linux server, peering with MikroTik RouterOS over iBGP and eBGP, filtering routes with prefix-lists, redistributing OSPF into BGP, and applying community-based policy.

## Installing FRRouting on Debian or Ubuntu

FRR provides official packages through their apt repository. Add the repository, install the daemon, and enable the BGP process.

```bash
# Add FRR GPG key and repository
curl -s https://deb.frrouting.org/frr/keys.asc | gpg --dearmor | sudo tee /usr/share/keyrings/frr.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/frr.gpg] https://deb.frrouting.org/frr $(lsb_release -sc) frr-stable" | sudo tee /etc/apt/sources.list.d/frr.list

# Install FRR and utilities
sudo apt update && sudo apt install frr frr-pythontools

# Enable the BGP daemon
sudo sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons

# Enable IP forwarding
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.d/99-frr.conf
sudo sysctl -p /etc/sysctl.d/99-frr.conf

# Restart FRR
sudo systemctl restart frr
```

Verify the `vtysh` shell works:

```bash
vtysh -c "show version"
```

You should see the FRR version, build configuration, and enabled daemons.

## Basic iBGP Configuration Within a Single AS

iBGP (Internal BGP) runs between routers in the same autonomous system. In a homelab, use a private AS number from the 64512-65535 range.

This example configures two Linux servers in AS 64512. The first server (10.0.20.10) peers with the second (10.0.20.11) and advertises the 10.0.30.0/24 subnet.

```
# Enter vtysh configuration mode
sudo vtysh

# Configure in FRR CLI
configure terminal
router bgp 64512
 bgp router-id 10.0.20.10
 neighbor 10.0.20.11 remote-as 64512
 neighbor 10.0.20.11 description iBGP-Peer-1
 !
 address-family ipv4 unicast
  network 10.0.30.0/24
  neighbor 10.0.20.11 next-hop-self
 exit-address-family
end
write memory
```

Key points about iBGP:
- Every iBGP peer must form a full mesh or use route reflectors — FRR supports both
- `next-hop-self` ensures the router advertises itself as the next hop for routes learned from eBGP peers
- The `network` statement tells BGP which locally reachable prefixes to advertise

On the peer, configure the same AS with the router's own ID:

```
configure terminal
router bgp 64512
 bgp router-id 10.0.20.11
 neighbor 10.0.20.10 remote-as 64512
 neighbor 10.0.20.10 description iBGP-Peer-0
 !
 address-family ipv4 unicast
  neighbor 10.0.20.10 next-hop-self
 exit-address-family
end
write memory
```

Verify the BGP session:

```bash
vtysh -c "show ip bgp summary"
```

You should see the peer state as `Established` with prefixes exchanged.

## eBGP Peering with MikroTik RouterOS

eBGP connects routers in different autonomous systems. This is the same protocol that ISPs use to exchange routes, and it gives you full control over route preference through local-preference, AS-path prepending, and community tagging.

This setup peers a Linux FRR router (AS 64512) with a MikroTik router (AS 65000) over a shared transit network.

**FRR side (Linux at 10.0.10.1):**

```
configure terminal
router bgp 64512
 bgp router-id 10.0.10.1
 neighbor 10.0.10.2 remote-as 65000
 neighbor 10.0.10.2 description eBGP-MikroTik
 neighbor 10.0.10.2 ebgp-multihop 2
 neighbor 10.0.10.2 password encrypted-secret-here
 !
 address-family ipv4 unicast
  network 10.0.20.0/24
  neighbor 10.0.10.2 route-map OUTBOUND-FILTER out
  neighbor 10.0.10.2 route-map INBOUND-FILTER in
 exit-address-family
end
write memory
```

**MikroTik RouterOS side (7.x):**

```
/routing/bgp/connection
add name=eBGP-FRR \
    remote.address=10.0.10.1/32 \
    remote.as=64512 \
    local.role=ebgp \
    local.address=10.0.10.2 \
    multihop=yes \
    tcp.md5.key=encrypted-secret-here \
    routing-table=main \
    address-families=ipv4 \
    templates=default

/routing/bgp/connection/eBGP-FRR/network
add network=10.0.30.0/24
add network=192.168.1.0/24
```

Verify both sides:

```bash
vtysh -c "show ip bgp neighbors 10.0.10.2"
```

On MikroTik:

```
/routing/bgp/connection/print detail
/routing/route/print where bgp
```

The session should show `established` with routes exchanged in both directions.

## Route Filtering with Prefix-Lists and Route Maps

Filtering BGP routes prevents unwanted prefixes from entering your routing table and controls what you advertise to peers. In a homelab this is especially important if you are experimenting with route redistribution or connecting multiple routing domains.

**FRR prefix-list to allow specific subnets inbound:**

```
configure terminal
ip prefix-list ALLOW-LAN seq 5 permit 10.0.0.0/8 ge 16 le 24
ip prefix-list ALLOW-LAN seq 10 permit 192.168.0.0/16 ge 24 le 24
ip prefix-list ALLOW-LAN seq 15 deny 0.0.0.0/0 le 32

route-map INBOUND-FILTER permit 10
 match ip address prefix-list ALLOW-LAN
 set local-preference 150

route-map INBOUND-FILTER deny 100
end
write memory
```

**Outbound filter to advertise only specific subnets to MikroTik:**

```
configure terminal
ip prefix-list ADVERTISE-LAN seq 5 permit 10.0.20.0/24
ip prefix-list ADVERTISE-LAN seq 10 permit 10.0.30.0/24
ip prefix-list ADVERTISE-LAN seq 15 deny 0.0.0.0/0 le 32

route-map OUTBOUND-FILTER permit 10
 match ip address prefix-list ADVERTISE-LAN

route-map OUTBOUND-FILTER deny 100
end
write memory
```

Apply to the neighbor and verify:

```bash
vtysh -c "show ip bgp prefix-list ALLOW-LAN"
vtysh -c "show ip bgp neighbors 10.0.10.2 advertised-routes"
```

## OSPF-to-BGP Route Redistribution

Many homelabs run OSPF for internal dynamic routing between hypervisors and storage networks. Redistributing OSPF routes into BGP lets you propagate internal prefixes to eBGP peers without duplicating `network` statements.

First, configure OSPF on FRR:

```
configure terminal
router ospf
 router-id 10.0.20.10
 network 10.0.20.0/24 area 0
 network 10.0.30.0/24 area 0
 passive-interface default
 no passive-interface eth0
exit
```

Redistribute OSPF routes into BGP with a route-map filter:

```
configure terminal
route-map OSPF-TO-BGP permit 10
 match ip address prefix-list OSPF-INTERNAL
 set community 64512:1000

router bgp 64512
 address-family ipv4 unicast
  redistribute ospf route-map OSPF-TO-BGP
 exit-address-family
end
write memory
```

Create the prefix-list for redistribution:

```
configure terminal
ip prefix-list OSPF-INTERNAL seq 5 permit 10.0.20.0/24
ip prefix-list OSPF-INTERNAL seq 10 permit 10.0.30.0/24
ip prefix-list OSPF-INTERNAL seq 15 deny 0.0.0.0/0 le 32
end
write memory
```

Verify redistributed routes:

```bash
vtysh -c "show ip bgp"
```

Routes from OSPF should appear with the `>` marker and a community of `64512:1000`.

## BGP Community Tagging for Advanced Policy

Communities are BGP attributes that tag routes with metadata. Other routers can match these tags and apply policy — change local-preference, filter, or prepend AS-path.

FRR supports setting and matching communities in route-maps.

**Set a no-export community to keep routes within your AS:**

```
configure terminal
route-map SET-NO-EXPORT permit 10
 set community 64512:999 no-export
 set local-preference 200

router bgp 64512
 address-family ipv4 unicast
  neighbor 10.0.10.2 route-map SET-NO-EXPORT out
 exit-address-family
end
write memory
```

**Match a custom community and apply policy:**

```
configure terminal
ip community-list standard DMZ permit 64512:500

route-map DMZ-POLICY permit 10
 match community DMZ
 set local-preference 50

router bgp 64512
 neighbor 10.0.10.2 route-map DMZ-POLICY in
end
write memory
```

View community information in the BGP table:

```bash
vtysh -c "show ip bgp 10.0.30.0/24"
```

## Monitoring and Troubleshooting BGP Sessions

FRR provides the `vtysh` shell with familiar Cisco-style show and debug commands.

**Check BGP neighbor state:**

```bash
vtysh -c "show ip bgp summary"
```

**Display the full BGP table:**

```bash
vtysh -c "show ip bgp"
```

**View the kernel routing table for BGP-learned routes:**

```bash
ip route show proto bgp
```

**Enable BGP debug logging (use carefully in production):**

```
configure terminal
debug bgp updates
debug bgp keepalives
debug bgp events
log file /var/log/frr/bgpd.log
end
write memory
```

Tail the log:

```bash
sudo tail -f /var/log/frr/bgpd.log
```

**Confirm configuration persistence:**

```bash
vtysh -c "show running-config"
```

FRR saves to `/etc/frr/frr.conf` with the `write memory` command.

## Conclusion

FRRouting turns any Linux server into a full-featured BGP router. With iBGP for communication within a single AS, eBGP for peering with MikroTik or other vendors, prefix-list filtering for route hygiene, redistribution from OSPF, and community tagging for advanced policy, you have the same toolkit that ISPs and data centers use every day.

From here you can explore more advanced topologies: anycast services using BGP (such as DNS anycast with Unbound), VXLAN EVPN for multi-tenant L2 stretching across hosts, or BGP-based load balancing with BGP PIC (Prefix Independent Convergence).

The FRR documentation at [docs.frrouting.org](https://docs.frrouting.org/) covers every feature in detail. For homelab-specific routing topologies, check the earlier posts on MikroTik OSPF configuration and WireGuard performance tuning.
