---
title: "Proxmox GPU Passthrough — Complete Setup Guide for VMs"
description: "Dedicate a physical GPU to a Proxmox VM for AI inference, transcoding, or gaming. Step-by-step IOMMU, VFIO binding, NVIDIA fixes, and automated VM config."
date: 2026-05-18T10:00:00-04:00
tags:
  - proxmox
  - linux
  - homelab
  - performance
  - security
keywords:
  - Proxmox GPU passthrough guide
  - VFIO PCI passthrough Proxmox
  - NVIDIA GPU passthrough VM
  - IOMMU groups configuration
  - Proxmox VM GPU acceleration
  - vendor-reset NVIDIA Proxmox
  - NVIDIA Error 43 fix virtualization
summary: "Complete guide to GPU passthrough on Proxmox VE — from IOMMU enablement and VFIO binding through NVIDIA Error 43 fixes and the vendor-reset kernel module."
canonical: "https://blog.gntech.me/posts/proxmox-gpu-passthrough-guide/"
---

Passing a GPU to a Proxmox VM sounds intimidating — IOMMU groups,
VFIO binding, driver blacklists, PCI IDs, and the dreaded NVIDIA
Error 43. But the actual process is a small, well-defined set of
kernel-level changes on the host plus a few VM config tweaks. Once
they click into place, the GPU appears inside the VM with bare-metal
performance.

This guide covers NVIDIA GPU passthrough on Proxmox VE 8.x, from
BIOS settings through automated VM configuration. Whether you are
offloading transcoding to a Plex LXC, running local LLMs in a GPU VM,
or building a remote gaming workstation, the steps are the same.

---

## Hardware Requirements and IOMMU Compatibility

Before touching any configs, verify your hardware supports passthrough:

- **CPU:** Intel with VT-d or AMD with AMD-Vi (virtually all modern
  desktop CPUs have this)
- **Motherboard:** BIOS option to enable VT-d / IOMMU and 4G decoding /
  Resizable BAR
- **GPU:** A second GPU for the Proxmox host (onboard Intel graphics
  is ideal) — the host needs a display output you are not trying to
  pass through
- **Proxmox:** VE 8.x or later, running kernel 6.8+

Run this quick check before proceeding:

```bash
# Check if kernel has IOMMU support compiled in
dmesg | grep -e DMAR -e IOMMU -e AMD-Vi

# Check for interrupt remapping (required for passthrough)
dmesg | grep 'remapping'
```

If `dmesg | grep IOMMU` returns nothing, IOMMU is not enabled at the
kernel level yet. That is the first step.

---

## Step 1: Enable IOMMU in BIOS and GRUB

### BIOS Settings

Reboot your server and enter the BIOS setup. Enable:

| Setting | Intel | AMD |
|---------|-------|-----|
| VT-d / IOMMU | Overclocking → CPU Features → Intel VT-d Tech | Advanced → IOMMU |
| Above 4G Decoding | PCI Subsystem Settings | Always enable |
| Resizable BAR | DMI/PCI Configuration | Sets correct MMIO window |
| Secure Boot | **Disable** | Causes driver issues with GPU |

### GRUB Command Line

SSH into the Proxmox host and edit `/etc/default/grub`:

```bash
nano /etc/default/grub
```

Find the `GRUB_CMDLINE_LINUX_DEFAULT` line. For **Intel** systems:

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"
```

For **AMD** systems:

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet amd_iommu=on iommu=pt"
```

The `iommu=pt` flag tells the kernel to skip IOMMU mapping for devices
that are not being passed through. It reduces overhead and is safe to
include regardless of vendor.

Apply the change and reboot:

```bash
update-grub
reboot
```

After reboot, verify IOMMU is live:

```bash
dmesg | grep -e DMAR -e IOMMU
# Expected output (Intel):
# DMAR: IOMMU enabled
# DMAR: Intel(R) Virtualization Technology for Directed I/O

dmesg | grep 'remapping'
# Expected: DMAR-IR: Enabled IRQ remapping or
#           AMD-Vi: Interrupt remapping enabled
```

If interrupt remapping is **not** enabled (older hardware), you can
work around it, though this reduces isolation:

```bash
echo "options vfio_iommu_type1 allow_unsafe_interrupts=1" \
  > /etc/modprobe.d/iommu_unsafe_interrupts.conf
```

---

## Step 2: Inspect IOMMU Groups

Your GPU must be in its own IOMMU group. Devices in the same group
must all be passed through together, which usually means passing both
the VGA controller and the audio device as a pair.

Run this to dump every group:

```bash
for d in /sys/kernel/iommu_groups/*/devices/*; do
  n=${d#*/iommu_groups/*}; n=${n%%/*}
  printf 'IOMMU Group %s  ' "$n"
  lspci -nns "${d##*/}"
done
```

Look for your GPU in its own group:

```
IOMMU Group 13  01:00.0 VGA compatible controller [0300]: NVIDIA ... [10de:2206]
IOMMU Group 13  01:00.1 Audio device [0403]: NVIDIA ... [10de:1aef]
```

If the GPU shares a group with unrelated devices (SATA controller, USB
controller, NVMe), passthrough is still possible but you must pass the
entire group — which includes those unrelated controllers. The
workaround is `pcie_acs_override` (detailed in the troubleshooting
section), but it weakens IOMMU isolation. For a homelab that is
usually acceptable; for a production environment, consider a different
PCIe slot.

---

## Step 3: Bind the GPU to VFIO at Boot

Find your GPU's PCI vendor and device IDs:

```bash
lspci -nn | grep -iE "nvidia|amd|vga|3d|audio"
# Example output:
# 01:00.0 VGA compatible controller [0300]: NVIDIA ... [10de:2206]
# 01:00.1 Audio device [0403]: NVIDIA ... [10de:1aef]
```

Copy both IDs (`10de:2206,10de:1aef`) — you need them for VFIO binding.

### 3.1 Blacklist Host GPU Drivers

The host must not load `nvidia` or `nouveau` for the passthrough GPU.
Blacklist both:

```bash
cat >> /etc/modprobe.d/blacklist.conf <<'EOF'
blacklist nouveau
blacklist nvidia
EOF
```

### 3.2 Load VFIO Kernel Modules at Boot

```bash
cat >> /etc/modules <<'EOF'
vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd
EOF
```

### 3.3 Bind the GPU PCI IDs to VFIO

Create the VFIO options file with your GPU's IDs:

```bash
cat > /etc/modprobe.d/vfio.conf <<'EOF'
options vfio-pci ids=10de:2206,10de:1aef disable_vga=1
EOF
```

Replace `10de:2206,10de:1aef` with your actual IDs. The `disable_vga=1`
prevents the VGA arbitration subsystem from interfering with the GPU.

### 3.4 Apply and Verify

```bash
update-initramfs -u -k all
reboot
```

After reboot, confirm VFIO has claimed the GPU:

```bash
lspci -nnk -d 10de:2206
# Expected: Kernel driver in use: vfio-pci
```

If you see `nvidia` or `nouveau` instead, the blacklist did not take
effect. Check that your blacklist file has no typos and that
`update-initramfs` ran successfully.

---

## Step 4: Create the Target VM

These settings are **not optional** for GPU passthrough. Deviating
from them is the most common source of failures.

### VM Creation Checklist

| Setting | Value | Why |
|---------|-------|-----|
| Machine | **q35** | Required for PCIe device assignment |
| BIOS | **OVMF (UEFI)** | Legacy BIOS cannot handle GPU ROM |
| EFI Disk | Add it | Required for OVMF; 64 MB is enough |
| CPU Type | **host** | Exposes host CPU features to the guest |
| Memory | Fixed amount, disable ballooning | Ballooning can conflict with GPU DMA |

You can set these from the CLI and avoid the web UI entirely:

```bash
VM_ID=200
VM_NAME="gpu-workstation"

qm create $VM_ID \
  --name $VM_NAME \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-zfs:1,format=qcow2,efitype=4m \
  --scsihw virtio-scsi-single \
  --cpu host \
  --memory 16384 \
  --balloon 0 \
  --net0 virtio,bridge=vmbr0 \
  --boot order=scsi0 \
  --ostype l26

# Attach a disk
qm set $VM_ID --scsi0 local-zfs:64,discard=on,ssd=1,iothread=1

# Attach VirtIO drivers ISO (for Windows guests)
# qm set $VM_ID --ide2 local:iso/virtio-win.iso,media=cdrom
```

Install the OS inside the VM normally before attaching the GPU. This
way you can install NVIDIA drivers without the GPU being active yet.

---

## Step 5: Attach the GPU to the VM

After the OS is installed and drivers are ready, shut down the VM and
attach the PCI device:

```bash
qm set $VM_ID \
  --hostpci0 01:00,pcie=1,x-vga=on,rombar=1
```

Breaking down the flags:

- **`01:00`** — PCI address of the GPU (vga + audio passed as pair per
  IOMMU group)
- **`pcie=1`** — Exposes the device on a PCIe bus inside the VM instead
  of PCI. Required for full bandwidth
- **`x-vga=on`** — Declares this GPU as the VM's primary display
- **`rombar=1`** — Exposes the GPU's Option ROM to the guest

Also set `vga: none` so the VM does not create a virtual VGA display
that conflicts:

```bash
qm set $VM_ID --vga none
```

Start the VM and verify the GPU is visible inside the guest:

```bash
# Inside the VM
lspci | grep -i nvidia
# 01:00.0 VGA compatible controller: NVIDIA ...
# 01:00.1 Audio device: NVIDIA ...
```

---

## Step 6: NVIDIA Driver Installation and Error 43

### Modern Drivers (465+)

NVIDIA drivers starting at version 465 no longer check the
virtualization flag by default. If you are on driver 550 or newer,
skip Error 43 workarounds — just install the driver normally:

```bash
# Inside the VM (Ubuntu/Debian)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
apt update
apt install -y cuda-toolkit-12-8 nvidia-driver-570
reboot
nvidia-smi
```

### Legacy or Stubborn Drivers — Hide the Hypervisor

If `nvidia-smi` shows "No devices were found" or Error 43, the driver
is detecting KVM and refusing to load. Hide it:

Add these lines to `/etc/pve/qemu-server/$VM_ID.conf`:

```
cpu: host,hidden=1
args: -cpu 'host,hv_vendor_id=NV43FIX,kvm=off'
```

- **`hidden=1`** — QEMU hides the KVM signature from CPUID leaves
- **`hv_vendor_id=NV43FIX`** — Spoofs the Hyper-V vendor ID string
  (any 12-character value works)
- **`kvm=off`** — Clears the KVM feature bit so the driver sees a
  physical environment

After editing, reboot the VM. Verify with:

```bash
# Inside the VM — should show nothing
cat /proc/cpuinfo | grep hypervisor
# No output means the hypervisor is hidden
```

### Windows VM — Ignore MSRs

Windows NVIDIA drivers sometimes issue unhandled Model-Specific
Register (MSR) accesses that crash the VM. Prevent this on the host:

```bash
echo "options kvm ignore_msrs=1 report_ignored_msrs=0" \
  > /etc/modprobe.d/kvm.conf
update-initramfs -u -k all
```

---

## Step 7: Tesla P40 / Datacenter Cards for AI

The NVIDIA Tesla P40 is the sweet spot for homelab AI workloads. It
has 24 GB of GDDR5 VRAM, costs €100–150 used, and has no display
output — it is a pure compute card.

### P40-Specific Configuration

```bash
# Create the VM with extra-large MMIO window for 24 GB VRAM
qm create $VM_ID \
  --machine q35 \
  --bios ovmf \
  --cpu host \
  --memory 32768 \
  --balloon 0
```

The P40's 24 GB VRAM requires a larger MMIO window than OVMF's
default 32 GB allocation. Using `cpu: host` (as above) resolves this
automatically because OVMF adjusts the window based on host properties.
If you must use a different CPU type:

```bash
qm set $VM_ID --cpu x86-64-v2-AES,phys-bits=host,flags=+pdpe1gb
```

Attach the P40 without `x-vga=on` since datacenter cards have no
display output:

```bash
qm set $VM_ID --hostpci0 01:00,pcie=1,rombar=1
qm set $VM_ID --vga serial0
```

Install the CUDA toolkit inside the VM:

```bash
nvidia-smi
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 570.86.15    Driver Version: 570.86.15    CUDA Version: 12.8     |
# |-------------------------------+----------------------+----------------------+
# | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# | Tesla P40           Off  | 00000000:01:00.0     Off |                    0 |
# | Fan N/A    Temp 42C      P0     68W / 250W  |  24576MiB / 24576MiB |    0% |
# +-------------------------------+----------------------+----------------------+
```

The P40 has passive cooling (no fans). In a desktop case, point a
120 mm fan directly at the card's heatsink. In a server chassis, the
chassis fans must provide enough airflow — monitor temperatures with
`nvidia-smi -l 5` during load.

---

## Step 8: GPU Reset Fix with vendor-reset

Some NVIDIA cards (especially consumer models) cannot complete a PCIe
reset after the VM shuts down. The GPU goes into a hung state and the
host requires a full power cycle to recover.

Install the `vendor-reset` kernel module to fix this:

```bash
apt update
apt install -y pve-headers build-essential git
git clone https://github.com/gnif/vendor-reset.git /usr/src/vendor-reset
cd /usr/src/vendor-reset
make
make install

# Load at boot
echo vendor-reset >> /etc/modules
update-initramfs -u -k all
reboot
```

After reboot, verify:

```bash
lsmod | grep vendor_reset
# vendor_reset          32768  0
```

With vendor-reset loaded, you can stop and start the GPU VM without
needing a full server reboot. This is essential for homelabs running
multiple GPU workloads that cycle VMs daily.

---

## Automated Passthrough Setup Script

Save this as a one-shot script for future GPU installations:

```bash
#!/bin/bash
# gpu-passthrough.sh — Bind GPU to VFIO and configure host
# Usage: ./gpu-passthrough.sh <PCI_ID:H:M.F> <VENDOR:DEVICE_ID>

PCI_ADDR="$1"    # e.g., "01:00.0"
IDS="$2"         # e.g., "10de:2206,10de:1aef"

if [ -z "$PCI_ADDR" ] || [ -z "$IDS" ]; then
  echo "Usage: $0 <PCI_ADDR> <VFIO_IDS>"
  echo "Example: $0 01:00.0 10de:2206,10de:1aef"
  exit 1
fi

# Blacklist NVIDIA drivers
cat > /etc/modprobe.d/blacklist-nvidia.conf <<'EOF'
blacklist nouveau
blacklist nvidia
EOF

# Load VFIO modules at boot
grep -q vfio /etc/modules || cat >> /etc/modules <<'EOF'
vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd
EOF

# Bind GPU to VFIO
echo "options vfio-pci ids=$IDS disable_vga=1" > /etc/modprobe.d/vfio.conf

# Enable IOMMU in GRUB if not already set
if ! grep -q 'intel_iommu=on\|amd_iommu=on' /etc/default/grub; then
  sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="intel_iommu=on iommu=pt /' /etc/default/grub
  update-grub
fi

update-initramfs -u -k all
echo "Reboot required. Run: lspci -nnk -s $PCI_ADDR to verify vfio-pci driver"
```

---

## Step 9: Performance Tuning

### Enable Hugepages

Hugepages reduce TLB pressure when the GPU does DMA to VM memory:

```bash
# Allocate 8 GB of 2 MB hugepages (4096 pages)
echo 4096 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# Make persistent
cat >> /etc/sysctl.d/99-hugepages.conf <<'EOF'
vm.nr_hugepages=4096
EOF
```

### Pin CPU Cores

Pin physical CPU cores to the VM to avoid NUMA migration overhead:

```bash
qm set $VM_ID \
  --numa 1 \
  --cpulimit 8 \
  --sockets 1 \
  --cores 8 \
  --cpupin 0-7
```

### Use NUMA If the Host Has Multiple Sockets

```bash
qm set $VM_ID --numa 1 --numa0 cpus=0-7,memory=16384
```

This tells the VM to map its NUMA node 0 to host NUMA node 0,
matching memory and CPU topology with the physical architecture.
GPU DMA to remote NUMA memory is 2-3× slower.

---

## Troubleshooting Common Failures

### GPU Not Visible Inside VM

```bash
# On host — confirm VFIO binding
lspci -nnk -s 01:00.0 | grep "Kernel driver"
# Must show: vfio-pci

# On host — check IOMMU group isolation
ls -la /sys/kernel/iommu_groups/*/devices/ | grep 01:00

# On VM — check if PCI device is enumerated
lspci | grep -i nvidia
```

Most likely causes:
- Machine type is `i440fx` instead of `q35`
- BIOS is Seabios instead of OVMF
- GPU is still claimed by `nvidia` or `nouveau` on the host

### Black Screen After VM Boot

```
Possible fixes:
- qm set $VM_ID --vga none
- Remove any --vga std or --vga virtio from VM config
- Ensure x-vga=on is set on the hostpci device
- Verify PCI address is correct
```

### NVIDIA Error 43

This means the driver detected it is running in a VM and refused to
load. Apply the hypervisor hiding steps from Step 6, then retry.

### GPU Hangs After VM Stop / Reset Bug

Install vendor-reset (Step 8). If it still hangs:
- Check that `vendor-reset` is listed in `lsmod`
- Try `echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove` then
  `echo 1 > /sys/bus/pci/rescan` on the host to re-detect
- As a last resort, the GPU's PCIe slot may need a physical power
  cycle (cold boot)

### Bad IOMMU Groups — ACS Override

If your GPU shares a group with unrelated devices, the nuclear option
is PCIe ACS override. It reduces isolation but works:

Add to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`:

```
pcie_acs_override=downstream,multifunction
```

Then `update-grub && reboot`. Only use this when you cannot physically
move the GPU to another slot that isolates properly.

---

## Summary

GPU passthrough on Proxmox is a well-trodden path with predictable
steps:

1. **BIOS** — Enable VT-d/AMD-Vi, Above 4G Decoding, disable Secure Boot
2. **GRUB** — `intel_iommu=on` (or `amd_iommu=on`) + `iommu=pt`
3. **VFIO** — Blacklist host GPU drivers, bind GPU PCI IDs to vfio-pci
4. **VM** — Machine q35, BIOS OVMF, CPU host, disabled ballooning
5. **Attach** — `hostpci0` with `pcie=1,x-vga=on` and `vga: none`
6. **Drivers** — NVIDIA 550+ works out of the box; older drivers need
   hypervisor hiding
7. **Reset** — Install vendor-reset to avoid hard-locking the GPU on
   VM stop

Once configured, the VM sees the GPU as a bare-metal device. AI
inference, hardware transcoding, CUDA workloads, and even gaming VMs
all benefit from near-native performance without dedicating an entire
machine to each workload.
