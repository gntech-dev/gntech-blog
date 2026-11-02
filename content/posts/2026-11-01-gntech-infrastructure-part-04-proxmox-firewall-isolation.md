---
title: "GNTECH Infrastructure Part 04: Proxmox Firewall, NAT, and Network Isolation"
description: "Build and verify a scoped nftables forwarding policy for a Hetzner Proxmox host with two MikroTik CHR transit networks and a private VM LAN."
date: 2026-11-01T22:00:00-04:00
draft: false
ShowToc: true
tags: [gntech-infrastructure, proxmox, nftables, firewall, hetzner, ipv6, mikrotik]
keywords: [Proxmox nftables forwarding, Hetzner Proxmox NAT, vmbr3 isolation, MikroTik CHR firewall, IPv6 forwarding]
summary: "Protect the routing boundary before opening services: inventory firewall ownership, apply a deliberately scoped IPv4 forwarding and NAT lab, test negative paths, and keep a verified rollback."
cover:
  image: "/images/posts/gntech-infrastructure-part-04/featured.svg"
  alt: "Cinematic-style editorial illustration of protected datacenter servers and an illuminated shield; no monitoring figures or production status represented."
  caption: "Original conceptual cover art. A separate diagram below explains the actual network policy."
  relative: false
---

**Series:** [GNTECH Infrastructure Deployment Series](/gntech-infrastructure-series/) · **Part 04 of 12** · [Previous: Part 03 — Dual MikroTik CHR](/posts/2026-11-01-hetzner-proxmox-dual-mikrotik-chr/) · Next: Part 05 — Home-to-Hetzner Connectivity (planned)

A VM can reach its gateway yet still be isolated from the Internet. A firewall can protect the Proxmox host while accidentally allowing traffic between two internal zones. And a working NAT rule is **not** evidence that a forwarding policy is safe.

This installment builds a **small, explicitly scoped lab policy** for the topology introduced in Parts 02–03. It is a teaching example, not a production ruleset or a record of live GNTECH/PVR01 tests. Never apply firewall changes to your only reachable management path.

![Firewall boundary between the host WAN, two CHR transit networks and a separate private VM network](/images/posts/gntech-infrastructure-part-04/policy.svg)

## 1. Know which traffic you are filtering

| Interface | Example network | Responsibility |
| --- | --- | --- |
| `vmbr0` | Provider WAN (real addresses omitted) | Host uplink and public IP routing |
| `vmbr1` | `10.255.1.0/30` | Proxmox ↔ CHR-A transit |
| `vmbr2` | `10.255.2.0/30` | Proxmox ↔ CHR-B transit |
| `vmbr3` | `10.3.0.0/24` | General private VMs; host gateway `10.3.0.1` |

The public IPv4 routes for each CHR are **provider-specific**. This guide does not install, change, or infer them. A routed /32 is not automatically a NAT source, nor does the host firewall replace RouterOS's policy for the LAN behind the CHR.

A Linux host has distinct packet paths:

- **INPUT:** packets addressed to the Proxmox host, including SSH and port 8006.
- **OUTPUT:** packets originated by the host.
- **FORWARD:** packets passing through the host between interfaces, including routed VM Internet traffic.

This guide demonstrates **FORWARD plus POSTROUTING NAT**. It intentionally leaves host INPUT/OUTPUT access under the existing firewall owner and does not open management services.

## 2. Choose one deliberate firewall ownership model

Proxmox ships an established `pve-firewall` implementation and an nftables-based `proxmox-firewall` implementation. Their capabilities and support status can differ by installed Proxmox release. **Verify the current documentation and local services** before using host-forward rules or switching backends.

Proxmox's documentation notes that forwarded host/VNet policy requires the nftables-based backend; legacy `pve-firewall` ignores forward rules. It also allows custom nftables tables separate from the ones `proxmox-firewall` manages. Never assume an ACCEPT verdict in your custom table can override a DROP verdict in another base chain.

Read-only inventory:

```bash
pveversion -v | head -n 20
systemctl is-active pve-firewall proxmox-firewall nftables || true
pve-firewall status 2>&1 || true
nft -a list ruleset
iptables-save 2>/dev/null | head -n 100
ip -br address
ip -4 route
ip -6 route
```

**Stop if** you find unexplained custom forwarding/NAT tables, duplicated `vmbr3` masquerade rules, pending interface changes, or a Proxmox backend migration. Consolidate ownership before adding another ruleset. Do not disable either firewall service simply to make these examples work.

## 3. Protect recovery before testing

You need a tested Hetzner rescue/console path **independent of the two CHR VMs**, a second admin connection, an outage window, and an explicit rollback operator.

Capture the running rules without changing them:

```bash
install -d -m 700 /root/gntech-firewall-audit
nft -a list ruleset > /root/gntech-firewall-audit/ruleset.before
ip -4 route > /root/gntech-firewall-audit/ipv4.before
ip -6 route > /root/gntech-firewall-audit/ipv6.before
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding \
  > /root/gntech-firewall-audit/forwarding.before
chmod 600 /root/gntech-firewall-audit/*
```

An on-host copy is useful for inspection but **not** an off-host backup. Keep recovery credentials and an external copy separately. A full `nft -f` restore from an old host dump can conflict with Proxmox-managed tables; rollback should normally remove **only the tables you added**, and the existing owners should regenerate their own rules.

## 4. Define the specific lab policy

The initial lab accepts these **only**:

1. New IPv4 flows from `vmbr3` to `vmbr0`, when their source is `10.3.0.0/24`.
2. Established replies from `vmbr0` back to `vmbr3`.
3. No unsolicited WAN-to-`vmbr3` traffic.
4. No forwarding between `vmbr3` and `vmbr1`/`vmbr2`.
5. No IPv6 forwarding to or from `vmbr3` until separately designed.

**Not covered by this starter:** authorization for CHR public /32 forwarding. It remains governed by the existing host firewall and CHR deployment design. A broad pass-through for unrelated interfaces in a lab-specific chain does **not** replace the host's existing firewall.

### Stage a scoped nftables filter file

The commands below create a **new file only**. They do not apply firewall rules.

```bash
cat > /root/gntech-vm3-filter.nft <<'EOF'
table inet gntech_vm3_filter {
    chain forward {
        type filter hook forward priority -10; policy accept;

        # Never forward bogus or invalid VM3-originated packets.
        iifname "vmbr3" ct state invalid counter drop
        iifname "vmbr3" ip saddr != 10.3.0.0/24 counter drop

        # IPv6 is intentionally blocked on this lab segment.
        iifname "vmbr3" meta nfproto ipv6 counter drop
        oifname "vmbr3" meta nfproto ipv6 counter drop

        # Only established replies may enter VM3 from WAN.
        iifname "vmbr0" oifname "vmbr3" ct state established,related counter accept
        iifname "vmbr0" oifname "vmbr3" counter drop

        # Approved IPv4 VM3 outbound path.
        iifname "vmbr3" oifname "vmbr0" ip saddr 10.3.0.0/24 \
          ct state new,established,related counter accept

        # All other forwarding *to or from* VM3 is denied.
        iifname "vmbr3" counter drop
        oifname "vmbr3" counter drop
    }
}
EOF
```

**Why an `inet` table?** It observes both address families and can intentionally deny IPv6 on VM3 while allowing carefully scoped IPv4 forwarding. The explicit `vmbr3` ingress/egress drops leave CHR transit traffic untouched by this *particular* table. The default ACCEPT is appropriate only because this is a **supplemental, narrowly scoped chain** and all other forwarding already has a separate policy owner. For a new host lacking that baseline, stop and design the complete host firewall first.

The `ct state established` rules should only be meaningful for traffic that entered through an approved outbound path. They do not mean another base chain cannot reject a packet.

### Stage source NAT separately

Use NAT **only** for the general-purpose VM subnet, not for CHR-A or CHR-B public addresses:

```bash
cat > /root/gntech-vm3-nat.nft <<'EOF'
table ip gntech_vm3_nat {
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr 10.3.0.0/24 oifname "vmbr0" counter masquerade
    }
}
EOF
```

Do **not** apply this if your Proxmox, RouterOS, nftables, or iptables configuration already NATs `10.3.0.0/24`; duplicate NAT is difficult to debug. The `masquerade` statement deliberately uses the WAN's current source address, so it is for VM3 private Internet egress—not for a CHR's provider-routed public /32.

## 5. Validate the syntax and plan activation

These are checks, not a deployment:

```bash
nft -c -f /root/gntech-vm3-filter.nft
nft -c -f /root/gntech-vm3-nat.nft
nft list table inet gntech_vm3_filter 2>/dev/null || true
nft list table ip gntech_vm3_nat 2>/dev/null || true
sysctl net.ipv4.ip_forward
```

For the route to work, IPv4 forwarding must be enabled **and** the authoritative forwarding policy must permit this path. To stage a persistent sysctl for later review, **do not overwrite an existing value or file**:

```bash
# Inspect first; do not automatically apply during a remote session.
grep -R 'net.ipv4.ip_forward' /etc/sysctl.conf /etc/sysctl.d/ 2>/dev/null || true
```

After confirming no conflicting policy and a tested independent recovery path, an operator can explicitly execute the following **from a maintenance console**. These actions change live packet filtering and may disrupt connections:

```bash
# CHANGE WINDOW ONLY — no automatic execution in this article.
# nft -f /root/gntech-vm3-filter.nft
# nft -f /root/gntech-vm3-nat.nft
# sysctl -w net.ipv4.ip_forward=1
```

Neither temporary rules nor the runtime sysctl setting survives all reboot scenarios by default. **Persistence is intentionally not enabled in this lab**. Integrate changes with your existing Proxmox/nftables management mechanism only after the acceptance tests pass.

## 6. Anti-spoofing for the router transit links

For routed CHR addressing, verify source-address ownership in the appropriate *existing* forwarding firewall. An example **design condition** is that `vmbr1` may originate its assigned transit address and provider-authorized CHR-A public IP, but never CHR-B's IP.

**Do not apply the following as a working WAN policy.** RFC 5737 public addresses are illustrative and cannot validate provider routing:

```text
vmbr1 allowed sources: 10.255.1.2/32 and <actual routed CHR-A IPv4>/32
vmbr2 allowed sources: 10.255.2.2/32 and <actual routed CHR-B IPv4>/32
vmbr3 allowed sources: 10.3.0.0/24 (NAT egress only)
WAN inbound: provider-routed /32 → designated CHR transit, no cross-delivery
```

Before implementing filters, decide whether each CHR is doing its own NAT for an internal LAN or routing prefixes transparently. The set of valid source addresses changes accordingly. Do not indiscriminately block private source traffic across CHR transit if your design legitimately carries routed private subnets; instead enumerate and permit each justified prefix under an explicit policy.

Also consider asymmetric routing and reverse-path filtering (`rp_filter`). Defaulting to strict reverse-path checking without understanding multiple routes can break legitimate flows; document and test before changing sysctls.

## 7. IPv6: never assume IPv4 NAT protects it

A Hetzner IPv6 /64 is typically routed toward the host according to the purchased product's network model. Treat IPv6 as a separate routed and filtered service.

Our lab intentionally **does not forward IPv6** on `vmbr3`. To enable it later you must:

- Verify the actual delegated prefix and next-hop behavior.
- Choose whether hosts use separate routed prefixes, /128 routes, or another explicitly supported design; do not assign the same /64 independently to multiple LANs.
- Review `net.ipv6.conf.all.forwarding` and default-route / Router Advertisement interactions.
- Permit essential ICMPv6 for Neighbor Discovery and Packet Too Big where appropriate, while restricting unsolicited service ingress.
- Test an authorized IPv6 flow and a blocked one. IPv4 `masquerade` does **nothing** to filter IPv6.

Useful non-destructive checks:

```bash
ip -6 address show
ip -6 route
sysctl net.ipv6.conf.all.forwarding
nft list ruleset | grep -E 'ip6|icmpv6|vmbr3' || true
```

## 8. Test both allowed and denied traffic

Do not call the deployment verified because `ping 1.1.1.1` succeeds. Perform the tests from a disposable VM attached to `vmbr3`, and from another test endpoint in a separate zone.

| Test | Intended result | Evidence to record |
| --- | --- | --- |
| VM3 → `10.3.0.1` | Reach host gateway if INPUT policy allows | Route, ping/ARP, host counters |
| VM3 → external HTTPS IPv4 | Allowed | TCP connection, NAT counters, observed egress |
| WAN → VM3 unsolicited | Blocked | Controlled incoming TCP probe, drop counters |
| VM3 → CHR-A / CHR-B transits | Blocked | Controlled TCP probe, forward drop counters |
| CHR-A ↔ CHR-B | Only explicitly routed/authorized traffic | Existing firewall and RouterOS counters |
| VM3 → external IPv6 | Blocked at this stage | IPv6 attempt and explicit drop counter |
| Hypervisor management | Existing authorized management still works | Independent admin session |
| Host rescue | Available without CHR | Provider recovery method tested |

Example read-only commands after staged activation:

```bash
nft -a list table inet gntech_vm3_filter
nft -a list table ip gntech_vm3_nat
ip -4 route
conntrack -L 2>/dev/null | head -n 20 || true
```

Counters are stronger than guesses, but concurrent traffic can change them. Ideally use unique controlled test destinations/ports and note the before-and-after values.

**Important nuance:** traffic destined for `10.3.0.1` is **INPUT**, not FORWARD. Likewise, Proxmox VM-to-VM traffic on the same Linux bridge may never pass through the routed host FORWARD path. Use bridge/VM firewall rules if you need to isolate guests on the same L2 network.

## 9. Targeted rollback and recovery

The two files above use unique table names so their rollback is narrow. If you applied them and validation fails, an operator at the **independent console** can remove only those tables:

```bash
# CHANGE WINDOW ONLY — use only if these tables were created by this lab.
# nft delete table inet gntech_vm3_filter
# nft delete table ip gntech_vm3_nat
```

If you also enabled forwarding with `sysctl -w`, restore the **original recorded value** rather than unconditionally setting it to 0: other workloads might depend on it. If Proxmox manages other tables, do not run `nft flush ruleset` or restart firewall services indiscriminately.

If management disappears, use Hetzner's tested independent recovery console or rescue workflow and inspect the current host tables before changing anything. A firewall rollback is only complete once your original connectivity and zone-isolation tests pass again.

## 10. What is and isn't proven

**Provided:** a staged, copyable filter/NAT lab, explicit policy boundaries, a test matrix, and rollback commands.

**Not proven:** installation of these rules on an actual server, WAN/IPv6 reachability, the source routing of CHR public IPv4, compatibility with every version/backend of Proxmox, or resistance to all forms of spoofing. A production deployment needs a complete ruleset review and measured negative tests on its own host.

**Next:** Part 05 — Home-to-Hetzner Connectivity, covering site-to-site transport, route ownership, routing failure modes, and recovery paths.

### Official references

- [Proxmox VE firewall documentation](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#chapter_pve_firewall)
- [Proxmox firewall source documentation](https://github.com/proxmox/pve-docs/blob/master/pve-firewall.adoc)
- [Hetzner additional IP addresses and routed virtualization](https://docs.hetzner.com/robot/dedicated-server/ip/additional-ip-adresses/)
- [Netfilter nftables project](https://wiki.nftables.org/wiki-nftables/index.php/Main_Page)
