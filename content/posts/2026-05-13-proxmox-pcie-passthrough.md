---
title: "Proxmox PCIe Passthrough — GPU, NVMe, and HBA Setup for Homelabs"
description: "Complete PCIe passthrough guide for Proxmox VE — GPU passthrough for Jellyfin, NVMe direct access, SAS HBA for TrueNAS. Real kernel configs, IOMMU groups, vfio-pci, and working VM settings."
date: 2026-05-13T15:30:00-04:00
tags:
  - proxmox
  - linux
  - storage
  - homelab
  - performance
keywords:
  - Proxmox PCIe passthrough
  - GPU passthrough Proxmox
  - NVMe passthrough VM
  - HBA passthrough Proxmox
  - IOMMU groups configuration
summary: "Complete Proxmox VE PCIe passthrough guide — GPU for Jellyfin transcoding, NVMe direct access, SAS HBA for NAS VMs. Kernel configs, vfio-pci, IOMMU groups, and working Proxmox VM settings."
canonical: "https://blog.gntech.me/posts/proxmox-pcie-passthrough/"
---

PCIe passthrough is how you take a single Proxmox host and get
bare-metal performance in a VM. Pass an NVIDIA GPU to a Jellyfin VM and
it transcode as if it owns the card. Pass a dedicated NVMe drive to a
TrueNAS VM and it manages SMART, TRIM, and power loss protection
directly. Pass a SAS HBA to a file server VM and it sees every disk
without Proxmox layering ZFS on top of ZFS.

This guide covers PCIe passthrough on Proxmox VE 8.x — from kernel
configuration through VM creation to troubleshooting the gotchas that
make people give up. Every step includes the exact commands and configs
used in a homelab running Proxmox 8.3 with an Intel Alder Lake system.

---

## What You Need Before Starting

Passthrough requires hardware that supports it. If your gear can't do
this, no amount of software config will make it work.

**CPU:** Must support VT-d (Intel) or AMD-Vi (AMD). Most consumer CPUs
from 2015 onward have it. Check with:

```bash
grep -E '(VMX|SVM)' /proc/cpuinfo
```

**Motherboard + BIOS:** IOMMU must be enabled in the BIOS, usually under
"VT-d" (Intel) or "IOMMU" (AMD). Some boards also need "Above 4G
Decoding" and "Resizable BAR" enabled for GPU passthrough.

**IOMMU grouping:** The PCIe device must be in its own IOMMU group or
its entire group must be passed through. Consumer platforms (non-HEDT)
often lump multiple devices into one group. You can work around this
with the ACS override patch, but that's a security trade-off.

**Dedicated GPU:** If you're passing a GPU, the host needs a separate
GPU for its own console — either integrated graphics or a second card.
An NVIDIA GTX 1650 for Plex transcoding? The host boots from the iGPU
and passes the NVIDIA card to the VM.

---

## Step 1: Enable IOMMU in the Kernel

Edit `/etc/default/grub` and add the IOMMU flag to `GRUB_CMDLINE_LINUX_DEFAULT`:

**Intel:**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"
```

**AMD:**
```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet amd_iommu=on iommu=pt"
```

The `iommu=pt` flag enables passthrough mode — the kernel only manages
devices assigned to the host, not every device behind an IOMMU. This is
important: without it, the host spends cycles translating addresses for
devices the VM will handle.

Add `pcie_acs_override=downstream,multifunction` if your IOMMU groups
are too wide (common on consumer hardware). This splits groups at the
downstream port level:

```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt pcie_acs_override=downstream,multifunction"
```

Apply and reboot:

```bash
update-grub
reboot
```

Verify IOMMU is active after reboot:

```bash
dmesg | grep -e DMAR -e IOMMU -e AMD-Vi
# You should see "IOMMU enabled" or similar

find /sys/kernel/iommu_groups/ -type l | head -10
# A populated directory confirms IOMMU groups exist
```

---

## Step 2: Load VFIO Kernel Modules

The VFIO (Virtual Function I/O) drivers take ownership of passed devices
from the native kernel driver and present them to the VM.

Create `/etc/modules-load.d/vfio.conf`:

```
vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd
```

Apply immediately:

```bash
echo "vfio" >> /etc/modules
echo "vfio_iommu_type1" >> /etc/modules
echo "vfio_pci" >> /etc/modules
update-initramfs -u -k all
```

---

## Step 3: Identify Devices and IOMMU Groups

List all PCIe devices with their IOMMU group:

```bash
#!/bin/bash
# iommu-groups.sh — show device-to-group mapping
shopt -s nullglob
for g in /sys/kernel/iommu_groups/*; do
    echo "IOMMU Group $(basename $g):"
    for d in $g/devices/*; do
        lspci -nns "${d##*/}"
    done
    echo
done
```

Run this script and look at the output. A device in its own group is
ideal. If you see a group with multiple unrelated devices (e.g., the GPU
and a USB controller in the same group), you need the ACS override
patch mentioned in Step 1 or can't isolate them.

For a GPU passthrough target, note the vendor and device IDs from
the `lspci -nns` output — you'll need them to bind the device to
vfio-pci:

```text
IOMMU Group 19:
01:00.0 VGA compatible controller [0300]: NVIDIA Corporation
         GA106 [GeForce RTX 3060 Lite Hash Rate] [10de:2503] (rev a1)
01:00.1 Audio device [0403]: NVIDIA Corporation GA106
         High Definition Audio Controller [10de:228e] (rev a1)
```

Both functions (GPU core and HDMI audio) are in the same IOMMU group.
You must pass both to the VM for the GPU to work.

---

## Step 4: Bind Devices to vfio-pci

Tell the kernel to bind the target PCIe devices to `vfio-pci` instead of
their native drivers. The safest way is via the kernel command line,
before any driver loads.

Add to GRUB_CMDLINE_LINUX_DEFAULT (same line as your IOMMU flag):

```bash
vfio-pci.ids=10de:2503,10de:228e
```

Full GRUB line example for Intel with an RTX 3060:

```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt vfio-pci.ids=10de:2503,10de:228e"
```

Alternatively, use `driverctl` to rebind at runtime without a reboot:

```bash
apt install driverctl
driverctl set-override 0000:01:00.0 vfio-pci
driverctl set-override 0000:01:00.1 vfio-pci
```

After reboot (or driver override), verify:

```bash
lspci -nnk -s 01:00
# Kernel driver in use: vfio-pci  ← confirms binding
```

---

## Step 5: VM Configuration for PCIe Passthrough

Create the VM with the right machine type and firmware. These settings
cannot be changed after creation, so get them right.

### During VM creation (via web UI or CLI):

| Setting | Value | Why |
|---------|-------|-----|
| Machine | q35 | Supports PCIe topology natively |
| BIOS | OVMF (UEFI) | Required for PCIe; legacy SeaBIOS doesn't work |
| SCSI Controller | VirtIO SCSI single | Best performance for virtio-blk |
| CPU type | host | Exposes host CPU features to the VM |

### After creation, add the PCIe device:

In the Proxmox web UI, go to the VM → Hardware → Add → PCI Device.

- **Raw Device:** Select the GPU from the dropdown
- **All Functions:** Check — passes both the video and audio controller
- **ROM-Bar:** Check (needed for NVIDIA cards to initialize properly)
- **PCI-Express:** Check — this is critical. Unchecked means legacy PCI
  mode, which breaks GPU initialization
- **Primary GPU:** Uncheck (only check if this is the VM's boot GPU)

The equivalent `qm` command:

```bash
qm set <VMID> \
  -hostpci0 01:00,pcie=1,rombar=1 \
  -machine q35 \
  -cpu host
```

---

## Step 6: GPU Passthrough — NVIDIA and AMD Specifics

### NVIDIA

NVIDIA consumer cards (GeForce series) don't officially support
passthrough. They work, but the driver checks for the hypervisor and
refuses to load with error code 43 in Windows or driver init failure in
Linux.

Fix: Add a hidden KVM flag to the VM config. Edit `/etc/pve/qemu-server/<VMID>.conf` and append to the `args` line:

```
args: -cpu 'host,+kvm_pv_unused' -accel kvm -machine q35,viotlb=on
```

Or create `/etc/modprobe.d/kvm.conf` on the host:

```ini
options kvm ignore_msrs=1
```

For the VM's guest OS, inject the vendor ID so NVIDIA doesn't detect
a hypervisor:

```bash
# In qemu-server config:
args: -cpu 'host,hv_vendor_id=1234567890ab,kvm=off'
```

### AMD

AMD cards generally work without tricks. The one quirk is the reset
bug on older Polaris/Vega cards — after stopping the VM, the GPU
doesn't reset properly and the VM needs a full host reboot before it
works again. Workaround: pass a reset tool like `reset-vega.sh` or
bind the card to the AMDGPU driver on the host before VM shutdown.

---

## Step 7: NVMe and Storage Device Passthrough

For passing an NVMe drive or a full SATA/SAS HBA to a VM, the process
is the same as GPU passthrough, but simpler.

### NVMe Direct Passthrough

Pass the NVMe controller itself, not a partition on it. The VM gets
full TRIM, SMART, and firmware update capability.

```bash
# Find the NVMe device in IOMMU groups (usually group 12-16)
lspci | grep Non-Volatile

# Pass it in the Proxmox UI: Hardware → Add → PCI Device
# Select the NVMe controller, check PCI-Express and All Functions

# CLI:
qm set <VMID> -hostpci1 02:00.0,pcie=1
```

### HBA Passthrough

For storage-heavy VMs (TrueNAS, OMV, or a ZFS file server), pass the
entire SAS/SATA controller. The VM owns all disks attached to it and
manages SMART, pools, and RAID directly.

```bash
# Common HBAs: LSI 9211-8i (SAS2008), LSI 9300 (SAS3008)
lspci | grep -i 'SAS\|LSI\|Avago\|Broadcom'

# The HBA must be in IT mode (initiator target — no RAID firmware)
# for the VM to see individual disks

qm set <VMID> -hostpci2 03:00.0,pcie=1
```

**Why HBA passthrough over disk passthrough:** A single PCIe slot gives
the VM 8-24 disks directly. Disk-by-disk passthrough requires one device
per disk and hits a VM device limit much faster.

---

## Troubleshooting Common Issues

### "No IOMMU groups found"

Your hardware doesn't support it, or it's disabled in the BIOS. Check:

```bash
dmesg | grep -i iommu
# Empty output = BIOS disabled or kernel booted without flags

cat /proc/cmdline
# Verify your GRUB flags are present
```

If flags are present but IOMMU is still missing, your motherboard may
not implement VT-d/AMD-Vi despite the CPU supporting it. This is common
on budget boards. Update the BIOS and check the manual for the exact
VT-d toggle name.

### "GPU works in Linux VM but no video output"

You're likely missing one of:
- PCI-Express checkbox in the VM device config
- OVMF (UEFI) instead of SeaBIOS
- ROM-Bar unchecked
- All functions unchecked (needed for NVIDIA + audio)

For headless GPU compute (no monitor attached), add this to the VM's
kernel cmdline:
```
video=efifb:off
```

### "VM won't start — cannot get device"

The device is still bound to its native driver. Verify:

```bash
lspci -nnk -s 01:00
# Should show "Kernel driver in use: vfio-pci"
```

If it shows `nvidia`, `amdgpu`, or `nvme` instead, the vfio-pci binding
didn't work. Check your GRUB line for typos in the vendor:device IDs.

### "NVIDIA Code 43 in Windows VM"

Standard NVIDIA anti-hypervisor check. Ensure:
- `kvm=off` is in the CPU args
- `hv_vendor_id` is set to a non-empty string
- The GPU has UEFI firmware (most post-2016 cards do)
- CSM/Legacy boot is disabled in the VM's UEFI

### "VM can't see NVMe after passthrough — device not found"

Some NVMe controllers need the `nvme_core.default_ps_max_latency_us=0`
kernel parameter passed to the **guest** VM to prevent power state
confusion:

```bash
# Inside the VM's GRUB:
GRUB_CMDLINE_LINUX_DEFAULT="quiet nvme_core.default_ps_max_latency_us=0"
```

---

## Performance: Is It Worth It?

Passing a device through is always faster than emulation, but the delta
varies:

- **NVMe passthrough vs virtio-blk:** 5-10% latency improvement.
  Virtio-blk is already very good. NVMe passthrough matters most for
  heavy database workloads.

- **GPU passthrough vs no GPU:** Night and day. A VM without a GPU
  can't transcode video at all. With passthrough, a single RTX 3060
  handles 10+ simultaneous 4K transcodes in Jellyfin.

- **HBA passthrough vs virtio-scsi:** Marginal latency improvement.
  The real win is ZFS management — the VM does its own ARC, log ZIL,
  and SMART, all outside Proxmox's storage layer.

---

## Final Checklist

Before declaring passthrough done, run through this:

- [ ] IOMMU enabled in BIOS (VT-d / AMD-Vi)
- [ ] Above 4G Decoding enabled in BIOS
- [ ] GRUB has `intel_iommu=on` (or `amd_iommu=on`) + `iommu=pt`
- [ ] VFIO modules loaded and in initramfs
- [ ] Target device shows `Kernel driver in use: vfio-pci`
- [ ] VM uses q35 machine type (not i440fx)
- [ ] VM uses OVMF (UEFI) firmware (not SeaBIOS)
- [ ] PCI-Express checkbox checked on PCIe device
- [ ] All Functions checked for devices with multiple sub-devices
- [ ] ROM-Bar checked for GPUs
- [ ] `kvm=off` set in CPU args for NVIDIA GPUs

PCIe passthrough transforms what you can do with a single homelab host.
One box runs the file server, a media transcoder, a game streaming VM,
and the management plane — each with access to the hardware it needs at
native speed.
