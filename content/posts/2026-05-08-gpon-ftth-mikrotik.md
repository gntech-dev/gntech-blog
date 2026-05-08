---
title: "GPON/FTTH With MikroTik — Ditching the ISP Router for Direct Fiber"
description: "Bypass your ISP's GPON ONT/router and connect fiber directly to a MikroTik with an SFP GPON stick — VLAN tagging, VLAN filtering bridge, PPPoE, and practical gotchas from a real Dominican Republic FTTH deployment."
date: 2026-05-08T00:40:00-04:00
tags:
  - mikrotik
  - gpon
  - ftth
  - fiber
  - networking
  - routeros
  - homelab
categories:
  - homelab
  - networking
---

If you have fiber-to-the-home (FTTH), your ISP almost certainly gave you a combo ONT/router. It's a locked-down all-in-one box that does GPON optical termination, routing, Wi-Fi, and often double NAT. For a homelab with VLAN segmentation and a proper router like MikroTik, that box is a bottleneck — and you can bypass it entirely.

This post covers replacing the ISP ONT/router with a MikroTik router using an SFP GPON stick, covering the hardware, VLAN configurations, PPPoE quirks, and the gotchas that aren't in the marketing material. This is specifically from my experience with Dominican Republic FTTH providers, but the patterns apply to most GPON deployments globally.

---

## How GPON FTTH Works

GPON (Gigabit Passive Optical Network) uses a passive optical splitter between your home and the ISP's OLT (Optical Line Terminal). The ONT (Optical Network Terminal) on your side converts the optical signal to copper Ethernet.

Most ISPs ship a combined ONT + router device that does:

- Optical signal termination (GPON)
- 802.1Q VLAN tagging (Internet VLAN, IPTV VLAN, VoIP VLAN)
- PPPoE or DHCP client toward the ISP
- NAT, firewall, and Wi-Fi (usually mediocre)

The hack: replace the ONT with an **SFP GPON stick** (a small transceiver that plugs into your MikroTik's SFP cage) and configure RouterOS to do everything the ISP box was doing — VLAN tagging, PPPoE, and routing.

```
Before: Fiber → ISP ONT/Router (LAN) → MikroTik (behind ISP NAT)
After:  Fiber → SFP GPON Stick → MikroTik (direct to ISP)
```

The "after" setup gives you a public IP (or your own public IPv4/IPv6), no double NAT, full control over VLANs, and one fewer power brick.

---

## Hardware Requirements

### MikroTik With SFP

You need a MikroTik device with an SFP cage. Most CCR, RB4011, and some hAP models have one. I'm using an **RB5009** which has a single SFP+ cage, but an RB4011 with SFP or a CCR2004 works just as well.

### SFP GPON Stick

These are small form-factor SFP transceivers that do GPON optical termination. The common models are:

- **Huawei MA5671a** — Most popular, widely compatible
- **Nokia G-010S-P** — Solid, runs cool
- **FS.com GPON-ONU-34-20I** — Good alternative if Huawei/Nokia are hard to find
- **Generic "stick-es" (Ubiquiti-style)** — Workable but check OLT compatibility

Key specs to look for:
- **Class B+** optical budget (minimum, C+ is better for longer splits)
- **OMCCK v1/v2 support** — Some ISPs require specific management channel versions
- **SFP 1.25G/2.5G** — Most GPON sticks are 1.25G upstream, 2.5G downstream
- **SC/APC connector** — Match your ISP's fiber termination (almost always SC/APC for GPON)

> ⚠️
**Warning:** GPON sticks need to be provisioned with your ISP's OLT. Some require the ISP's GPON serial number (SN) and/or PLOAM password to authenticate. You'll need to extract this from your existing ONT before swapping.


---

## Extracting ISP ONT Credentials

This is the most critical step. You need at minimum the **GPON Serial Number**, and sometimes also a **PLOAM password** and **VLAN ID**.

### From the ISP ONT Web Interface

Log into your ISP router. Look for sections like:

- **Status → Device Info → GPON Serial Number**
- **WAN → VLAN Configuration**
- **ONT Authentication**

Write these down:
- **GPON SN** (format: `HWTCXXXXXXXX` for Huawei, `ALCLFXXXXXXX` for Alcatel, etc.)
- **PLOAM password** (sometimes called GPON password, LOID, or OMCC)
- **VLAN ID** for Internet (often 10, 100, 200, 300, or 832 — varies by ISP)
- **PPPoE credentials** (username/password for your ISP connection, if applicable)

### Via SSH/Telnet

Some ISP routers expose SSH or Telnet. If available:

```bash
# Show GPON info on many Huawei and ZTE ONTs
cat /proc/gpon/omcc_gsb
gpONserialNumber()

# Common busybox paths
cat /proc/gpon/status
omcicli mib get 131
```

### If You Can't Access the ONT

Some ISPs lock down their ONTs completely. Options:

1. **Clone the GPON SN to the SFP stick** using `omcc` or vendor tools (Huawei sticks support this via serial console)
2. **Call the ISP** and ask them to authorize a new ONT by GPON SN
3. **Use a managed media converter** in front of the MikroTik instead

---

## Configuring the SFP GPON Stick

Most GPON SFP sticks ship in a neutral/unconfigured state. You need to set the GPON serial number (and optionally the PLOAM password) before they'll authenticate.

### Via Serial Console (Huawei MA5671a)

These sticks have a serial console accessible via the SFP connector pins or a dedicated micro-USB port on some models. Connect at 115200 baud:

```
Login: root
Password: admin  (varies)

# Set GPON serial number
set sn HWTCXXXXXXXX

# Set PLOAM password (if needed)
set password xxxxxxxxx

# Save and reboot
save
reboot
```

### Via RouterOS — No Serial Cable

Some GPON sticks can be configured through RouterOS using the `omcc` protocol. This is vendor-specific and not universally supported. Check your stick's documentation.

For the full DIY approach, you can also use `otto` — an open-source tool for configuring GPON SFP sticks — running on a Linux host with the stick plugged in. But that requires a separate machine.

> ⚠️ If your stick's GPON serial doesn't match what the OLT expects, the VLAN doesn't exist, or the OLT rejects the PLOAM password, the link will show "LOS" (Loss of Signal) even though the fiber is physically connected. This is the #1 troubleshooting gotcha.

---

## RouterOS Configuration

Once the stick is plugged in and authenticated with the OLT, it shows up as an SFP interface. Here's how to configure it.

### Step 1 — Identify the Interface

```bash
/interface print where type="sfp"
```

Look for an interface like `sfp-sfpplus1`. The link should come up once the GPON authentication succeeds.

### Step 2 — VLAN Tagging

Most ISPs require VLAN tagging on the WAN-facing interface. The Internet VLAN ID is usually something like 10, 100, or 832. Find yours from the ISP ONT:

```bash
/interface vlan add interface=sfp-sfpplus1 name=vlan-isp vlan-id=100
```

If your ISP uses **VLAN stacking (QinQ)** — two VLAN tags — you need a VLAN interface on top of another VLAN:

```bash
/interface vlan add interface=sfp-sfpplus1 name=vlan-outer vlan-id=10
/interface vlan add interface=vlan-outer name=vlan-inner vlan-id=100
```

Check your ISP's requirements — some only tag the outer VLAN and expect the inner tag to come from a VLAN-aware bridge.

### Step 3 — PPPoE Client

Many FTTH providers use PPPoE for authentication. Create the PPPoE client on the VLAN interface:

```bash
/interface pppoe-client add \
    name=pppoe-isp \
    interface=vlan-isp \
    user="your_username@isp.com" \
    password="your_password" \
    add-default-route=yes \
    use-peer-dns=yes
```

DHCP-based ISPs are simpler — just set the VLAN interface as a DHCP client:

```bash
/ip dhcp-client add interface=vlan-isp disabled=no
```

### Step 4 — VLAN Filtering Bridge (VLANs Passed Through)

If your MikroTik is your core router and you use VLAN filtering, add the physical and bridge interfaces:

```bash
/interface bridge add name=bridge-local vlan-filtering=yes

# Add SFP port and LAN ports to the bridge
/interface bridge port add bridge=bridge-local interface=sfp-sfpplus1
/interface bridge port add bridge=bridge-local interface=ether2

# Tagged VLANs on bridge
/interface bridge vlan add bridge=bridge-local vlan-ids=100 tagged=sfp-sfpplus1,br-vlan-aware untagged=none
/interface bridge vlan add bridge=bridge-local vlan-ids=10,20,30,40,50 tagged=sfp-sfpplus1 untagged=none
```

This passes the WAN VLAN (100) and internal VLANs (10-50) cleanly through the bridge without extra config on each port.

---

## Firewall Rules for the GPON Interface

The SFP interface is connected directly to the ISP — it must be locked down tightly.

```bash
# Drop everything from WAN
/ip firewall filter add chain=input in-interface=sfp-sfpplus1 action=drop

# Allow only established/related
/ip firewall filter add chain=input in-interface=sfp-sfpplus1 connection-state=established,related action=accept

# Protect the router itself
/ip firewall filter add chain=input in-interface=sfp-sfpplus1 protocol=icmp action=accept comment="Allow ICMP from ISP"

# Don't forward from WAN to LAN unless it's a return packet
/ip firewall filter add chain=forward in-interface=sfp-sfpplus1 out-interface=bridge-local connection-state=established,related action=accept
/ip firewall filter add chain=forward in-interface=sfp-sfpplus1 out-interface=bridge-local action=drop
```

And the NAT masquerade so your LAN devices can reach the internet:

```bash
/ip firewall nat add chain=srcnat out-interface=pppoe-isp action=masquerade
```

---

## Common Gotchas

### "Link Is Down / LOS Red"

- GPON serial number mismatch — recheck the SN on the stick
- PLOAM password wrong or missing
- OLT requires a specific OMCC version the stick doesn't support
- Fiber is SC/APC but stick expects SC/UPC (connector mismatch)

### Speed Cap at ~950 Mbps

GPON has a shared medium. Your speed depends on the OLT split ratio and ISP provisioning. The SFP stick itself can handle 1.25G upstream / 2.5G downstream, but most ISPs provision ONTs at ~1G symmetrical. If you're getting exactly 950 Mbps, that's GPON overhead + PPPoE encapsulation — not a bottleneck.

### Jitter or Latency Spikes

- Disable **Energy-Efficient Ethernet** on the SFP interface if RouterOS supports it
- Ensure the SFP cage isn't thermally throttling (GPON sticks run hot — 60-70°C is normal)
- Check for OLT-side congestion during peak hours

### ISP Blocks Non-Standard ONTs

Some ISPs whitelist specific GPON serial number ranges or MAC addresses. Workarounds:
- Clone the GPON SN from your original ONT
- Ask your ISP to provision a new ONT by serial
- Use a managed GPON media converter (ONT in bridge mode) → MikroTik Ethernet

### VLAN Tagging Fails After Reboot

Double-check that the VLAN interface exists on the correct parent. RouterOS boots interfaces asynchronously, but VLAN interfaces should come up. If they don't, add a delay script:

```bash
/system script add name=pppoe-delay source={
    :delay 5
    /interface pppoe-client enable pppoe-isp
}
```

Add a scheduler to run the script at startup.

---

## Performance Comparison

| Metric | ISP ONT/Router | MikroTik + GPON Stick |
|--------|----------------|----------------------|
| Routing throughput | ~600-800 Mbps (NAT) | Line rate (2.5G capable) |
| Concurrent connections | ~4000 (consumer SoC) | ~1M+ (MikroTik offload) |
| Latency (inside LAN) | 0.3-0.5 ms | 0.1-0.2 ms |
| Firewall features | Minimal (no VLAN filtering) | Full (VLAN filtering, ACLs, mangle) |
| Double NAT? | Yes (if you want your own router) | No (direct public IP) |
| Power consumption | ~10-15W (whole device) | ~2-3W (just the SFP stick) |

The MikroTik already handles VLAN filtering and routing. Adding the GPON stick removes the ISP box from the equation entirely — you get lower latency, full control, and one less failure point.

---

## Summary

Ditching the ISP ONT/router and connecting fiber directly to a MikroTik via SFP GPON stick is a clean upgrade for any homelab with FTTH. The critical steps:

1. Extract the GPON serial number and VLAN IDs from your ISP device
2. Provision the SFP stick with the correct GPON SN
3. Configure the VLAN and PPPoE/DHCP client on RouterOS
4. Lock down the ISP-facing interface with firewall rules
5. Test, monitor temps, and handle any OLT compatibility quirks

It's not a 10-minute project — especially if you need a serial console to configure the stick or deal with ISP whitelisting — but the result is a single-router, single-SFP homelab with no double NAT and full control at the fiber level.
