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
canonical: "https://blog.gntech.me/posts/homelab-10gbe-networking-mikrotik-proxmox/"
---

If you are running a homelab with multiple Proxmox hosts, a NAS, and Docker containers, your 1GbE network is probably the bottleneck. VM migrations crawl, NFS storage feels sluggish, and pulling container images takes longer than it should. A 10GbE upgrade changes that — but only if you pick the right hardware and configure it correctly.

This guide covers the full stack: choosing a MikroTik CRS switch and SFP+ NICs, cabling decisions, VLAN segmentation, Proxmox host integration, Linux performance tuning, and real-world throughput validation.

## Why Upgrade to 10GbE in Your Homelab

The jump from 1GbE to 10GbE is a 10x throughput increase. Here is where it matters most:

- **NFS / NAS storage** — A single 1GbE link caps at ~110 MB/s, which is slower than most SATA SSDs. 10GbE unlocks sequential reads at 800-1100 MB/s.
- **VM live migrations** — Moving a 64 GB VM over 1GbE takes ~9 minutes. Over 10GbE, under a minute.
- **Container registry pulls** — Downloading multi-gigabyte images at 110 MB/s is painful. 10GbE drops that to seconds.
- **Cluster storage replication** — Ceph or DRBD between Proxmox nodes benefits massively from 10GbE bandwidth.

If your homelab runs a single server with everything local, 1GbE is fine. Once you add a second host, shared storage, or backup infrastructure, 10GbE becomes the unlock.

## Choosing Your 10GbE Hardware — Switch, NICs, and Cabling

### MikroTik CRS Switches

The MikroTik CRS3xx series is the go-to for cost-effective 10GbE switching. Three models cover most homelab scenarios:

| Model | SFP+ Ports | 1GbE Ports | Form Factor | Notes |
|-------|-----------|------------|-------------|-------|
| CRS309-1G-8S+ | 8 | 1 | Fanless desktop | Best for small homelabs, silent |
| CRS317-1G-16S+ | 16 | 1 | 1U rackmount | 16 ports, more airflow noise |
| CRS326-24S+2Q+RM | 24 SFP+ + 2x40GbE | 0 | 1U rackmount | Overkill for most; future-proof |

The CRS309 is the sweet spot: fanless, 8 SFP+ ports, and RouterOS 7 with full hardware offloading. At about 8W idle, it runs cool and silent with DAC cables.

### Network Interface Cards

Your Proxmox hosts need SFP+ NICs. Reliable options:

- **Intel X710-DA2** — 2-port 10GbE SFP+, Linux-native driver (i40e), low power, well-supported
- **Mellanox ConnectX-3 Pro** — Older but cheap on eBay, driver (mlx4_core), solid performance
- **Mellanox ConnectX-4 Lx** — 2-port 25GbE (downward compatible to 10GbE), driver (mlx5_core)
- **Integrated on server motherboards** — Many Supermicro and Dell boards include x710 or x520 on-board

Check existing NICs on your Proxmox host:

```
lspci | grep -i ethernet
```

Verify current link speed:

```
ethtool eth0 | grep Speed
```

### Cabling: DAC vs Fiber vs Transceivers

Choosing the right cable type saves money and avoids signal issues:

- **Direct Attach Copper (DAC)** — Best for runs under 5m (same rack or adjacent racks). Passive, no transceivers needed, lowest power, cheapest. Use SFP+ passive DAC cables.
- **Fiber + SFP+ transceivers** — For runs over 5m or between rooms. Multimode fiber (OM3/OM4) with 10GBASE-SR transceivers supports up to 300m.
- **10GBASE-T SFP+ modules** — Only if you need RJ45 copper 10GbE. Higher power draw (~3-4W per port), runs hot, avoid if possible.

For most homelabs, DAC cables between the switch and server NICs are the right choice. Example: a 2m passive SFP+ DAC is about $8-15 on FS.com vs $30+ for a pair of transceivers plus fiber.

## MikroTik CRS Switch Configuration for 10GbE

Start by resetting the CRS to a clean switching configuration through RouterOS:

```
/system reset-configuration run-after-reset="
/interface bridge add name=bridge1 vlan-filtering=yes protocol-mode=rstp
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus1 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus2 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus3 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus4 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus5 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus6 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus7 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=sfp-sfpplus8 hw-offload=yes
/interface bridge port add bridge=bridge1 interface=ether1
/interface vlan add name=vlan10 interface=bridge1 vlan-id=10
/interface vlan add name=vlan20 interface=bridge1 vlan-id=20
/ip address add address=10.0.30.1/24 interface=vlan10
/ip address add address=10.0.20.1/24 interface=vlan20
"
```

This configures VLAN filtering on the CRS bridge, assigns all SFP+ ports to the bridge with hardware offloading, and creates VLAN interfaces for management access.

For VLAN segmentation, define which ports carry which VLANs:

```
/interface bridge vlan
add bridge=bridge1 vlan-ids=10 tagged=bridge1,sfp-sfpplus1,sfp-sfpplus2 untagged=
add bridge=bridge1 vlan-ids=20 tagged=bridge1,sfp-sfpplus1,sfp-sfpplus2 untagged=sfp-sfpplus3,sfp-sfpplus4
```

Verify that all ports are hardware-offloaded:

```
/interface bridge port print where hw-offload=no
```

If any port shows `hw-offload=no`, check that the CPU interface (`/interface bridge port` without a physical interface) is not accidentally forwarding traffic. On CRS3xx switches, the switch chip handles all forwarding when properly configured.

## Proxmox Host 10GbE NIC Setup

After physically installing the SFP+ NIC, ensure the kernel driver is loaded:

```
lsmod | grep -E "i40e|mlx4_core|mlx5_core"
```

For Intel X710-based NICs:

```
modprobe i40e
echo "i40e" >> /etc/modules
```

Configure a static IP on the 10GbE interface in Proxmox's `/etc/network/interfaces`. Example with a bridge for VM traffic:

```
auto enp4s0f0
iface enp4s0f0 inet manual
    mtu 9000

auto vmbr10
iface vmbr10 inet static
    address 10.0.30.10/24
    mtu 9000
    bridge-ports enp4s0f0
    bridge-stp off
    bridge-fd 0
```

For dual-NIC bonding with LACP (802.3ad), the MikroTik switch side needs a bond interface:

```
/interface bonding add name=bond1 mode=802.3ad slaves=sfp-sfpplus1,sfp-sfpplus2
/interface bridge port add bridge=bridge1 interface=bond1 hw-offload=yes
```

And on the Proxmox host:

```
auto enp4s0f0
iface enp4s0f0 inet manual
    mtu 9000

auto enp4s0f1
iface enp4s0f1 inet manual
    mtu 9000

auto bond0
iface bond0 inet manual
    mtu 9000
    bond-slaves enp4s0f0 enp4s0f1
    bond-mode 802.3ad
    bond-miimon 100
    bond-lacp-rate 1

auto vmbr10
iface vmbr10 inet static
    address 10.0.30.10/24
    mtu 9000
    bridge-ports bond0
    bridge-stp off
    bridge-fd 0
```

## Linux 10GbE Performance Tuning for Maximum Throughput

Getting full line-rate 10GbE requires tuning beyond the defaults. The Linux network stack defaults to conservative values optimized for 1GbE.

### Ring Buffer Size

Default ring buffers are often 256 or 512 descriptors, which can starve 10GbE throughput under load.

```
ethtool -g eth0
ethtool -G eth0 rx 4096 tx 4096
```

Make this persistent via a systemd service or by adding the command to `/etc/rc.local`.

### IRQ Affinity and RSS Queues

10GbE NICs expose multiple MSI-X interrupt vectors, one per RSS queue. Distribute them across CPU cores:

```
cat /proc/interrupts | grep eth0
```

List the MSI-X IRQs:

```
ls /sys/class/net/eth0/device/msi_irqs/
```

On systems with 4+ cores, `irqbalance` handles this automatically. Verify:

```
systemctl status irqbalance
```

For manual pinning, set each IRQ's `smp_affinity` to a different core mask:

```
echo 1 > /proc/irq/125/smp_affinity   # core 0
echo 2 > /proc/irq/126/smp_affinity   # core 1
echo 4 > /proc/irq/127/smp_affinity   # core 2
echo 8 > /proc/irq/128/smp_affinity   # core 3
```

### TCP Stack Tuning

Append these to `/etc/sysctl.d/90-network-tune.conf`:

```
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.netdev_budget = 600
net.core.netdev_budget_usecs = 4000
```

Apply immediately:

```
sysctl -p /etc/sysctl.d/90-network-tune.conf
```

BBR (Bottleneck Bandwidth and Round-trip) congestion control is critical for long flows. It handles bufferbloat better than CUBIC on high-speed links.

### Jumbo Frames

Enable 9000-byte MTU on every hop: switch ports, host interfaces, and storage targets.

On the switch, set MTU on each SFP+ port:

```
/interface ethernet set sfp-sfpplus1 mtu=9000
/interface ethernet set sfp-sfpplus2 mtu=9000
```

On the Proxmox host:

```
ip link set dev enp4s0f0 mtu 9000
```

Make it permanent in `/etc/network/interfaces` by adding `mtu 9000` to each interface stanza.

### Testing Throughput with iperf3

Validate the setup end-to-end between two 10GbE-connected hosts:

```
iperf3 -c 10.0.30.20 -P 4 -t 30
```

Expected output on a properly tuned link:

```
[ ID] Interval           Transfer     Bitrate
[  5]   0.00-30.00  sec  34.0 GBytes  9.77 Gbits/sec                  receiver
```

If you see under 9 Gbps, check CRC errors and IRQ distribution.

## Storage Performance with 10GbE

Mounting NFS shares over the 10GbE VLAN makes a dramatic difference. Optimize mount options:

```
10.0.30.5:/volume1/nfs /mnt/nfs nfs4 rw,hard,intr,rsize=1048576,wsize=1048576,noatime,vers=4.2 0 0
```

For Proxmox, add a dedicated NFS storage pointing to your NAS over the 10GbE VLAN:

```
pvesm add nfs fast-storage --server 10.0.30.5 --export /volume1/nfs --path /mnt/pve/fast-storage --options vers=4.2,rsize=1048576,wsize=1048576
```

Backup operations that used to take 45 minutes over 1GbE finish in 5-7 minutes over 10GbE. VM storage migrations drop from 9 minutes to under a minute.

## Power and Thermal Considerations

10GbE can add measurable heat to your rack. Some practical notes:

- **DAC cables** are passive and generate negligible heat. Plug-and-play.
- **SFP+ optical transceivers** consume 0.5-1W each and produce noticeable heat. A switch with 8 populated SFP+ transceivers can run 10-15°C hotter than with DACs.
- **10GBASE-T SFP+ modules** consume 2.5-4W each and need active cooling. Avoid if possible.
- **CRS309** with DACs runs fanless at ~45-50°C case temperature in ambient 25°C. With fiber transceivers, expect 55-60°C.
- **NIC power draw** — A dual-port Intel X710 draws about 8-10W idle. Mellanox ConnectX-3 draws about 9-12W.

## Troubleshooting Common 10GbE Issues

### Link Training Failure

If the SFP+ link does not establish, check transceiver compatibility. MikroTik devices work with generic SFP+ modules when `set sfp-sfpplus1 advertise=10G-full` is set, but DAC cables (MikroTik or FS.com compatible) are more reliable.

### CRC and Error Counters

Run on the Proxmox host:

```
ethtool -S eth0 | grep -E "crc|error|miss"
```

Any non-zero CRC counter indicates signal integrity issues. Try reseating the cable, cleaning fiber end-faces with a cleaning pen, or swapping the DAC.

### Port Flapping

A link that drops and reconnects repeatedly is often a power-saving setting on the NIC:

```
ethtool --set-priv-flags eth0 disable-fw-lro on
```

Or disable energy-efficient Ethernet:

```
ethtool --set-eee eth0 eee off
```

### Link Negotiates at 1GbE Instead of 10GbE

This usually means a cable or transceiver mismatch. Manually advertise 10GbE on the MikroTik port:

```
/interface ethernet set sfp-sfpplus1 advertise=10G-full
```

Then check:

```
/interface ethernet monitor sfp-sfpplus1 once
```

## Conclusion

Deploying 10GbE in a homelab is straightforward when you follow the right sequence: pick a MikroTik CRS switch and DAC cables, configure hardware-offloaded bridging with VLANs, install and tune the NIC on your Proxmox host, and validate with iperf3.

### Quick Checklist

- [ ] Choose switch form factor: CRS309 (desktop, silent) or CRS317 (1U, more ports)
- [ ] Buy passive DAC cables for each server-to-switch link
- [ ] Reset CRS switch, configure bridge with vlan-filtering and hw-offload
- [ ] Install SFP+ NIC in Proxmox host, load driver
- [ ] Configure /etc/network/interfaces with bridge and optional bond
- [ ] Tune ring buffers, IRQ affinity, TCP sysctls, and jumbo frames
- [ ] Validate with iperf3 — expect 9.4+ Gbps
- [ ] Mount NFS shares with optimal rsize/wsize over the 10GbE VLAN

The performance difference is transformative. Once you have done a VM migration in 30 seconds or a backup in 5 minutes, you will not want to go back to 1GbE.
