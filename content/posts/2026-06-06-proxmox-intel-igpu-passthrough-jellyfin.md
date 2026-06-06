---
title: "Proxmox Intel iGPU Passthrough for Jellyfin Hardware Transcoding"
description: "Step-by-step Intel QuickSync GPU passthrough on Proxmox for Jellyfin hardware transcoding. Covers IOMMU, vfio-pci binding, VM configuration, and Docker setup."
date: 2026-06-06T16:00:00-04:00
tags:
  - proxmox
  - virtualization
  - media
  - linux
  - docker
keywords:
  - Proxmox Intel iGPU passthrough Jellyfin hardware transcoding guide
  - Intel QuickSync GPU passthrough Proxmox VM configuration steps
  - vfio-pci driver bind Intel GPU Proxmox host isolation
  - Proxmox IOMMU group verification PCI passthrough troubleshooting
  - Jellyfin Docker hardware transcoding Intel iGPU setup
  - Proxmox VM GPU passthrough performance tuning tips
  - Intel Arc A380 transcoding Jellyfin Proxmox passthrough
summary: "Passthrough an Intel iGPU through Proxmox to a VM for Jellyfin hardware transcoding. Configure IOMMU, bind vfio-pci, verify groups, and tune performance."
canonical: "https://blog.gntech.me/posts/proxmox-intel-igpu-passthrough-jellyfin/"
---

## Why GPU Passthrough Matters for Your Homelab

Software transcoding looks fine on paper — until someone in the house starts streaming a 4K HEVC video to their phone while a second stream converts a Blu-ray rip to H.264 for an older TV. Your CPU pegs at 100%, the Jellyfin Web UI lags, and transcoding queues pile up.

Intel QuickSync changes the equation. A modern Intel iGPU (12th gen or newer) handles HEVC and AV1 encode/decode in dedicated silicon, drawing a fraction of the power the CPU would burn on software transcoding. A single Ice Lake or Tiger Lake iGPU can push 8–10 concurrent 1080p transcodes or 3–4 4K HDR streams with tone mapping, all at under 20W.

Beyond Jellyfin, the pass-through GPU is useful for:

- **Frigate** AI object detection with OpenVINO backend
- **Ollama** inference acceleration (Intel OpenVINO or SYCL)
- **HandBrake** CLI batch transcoding
- **Parsec/Moonlight** game streaming from a headless VM

If you run a single Proxmox host with Docker containers in a VM (or your services live in an LXC), passing the iGPU through is the difference between a responsive media server and one that chokes under load.

## Pre-Flight Checklist

Before touching any configs, verify your hardware supports passthrough.

**BIOS settings to enable:**

| Setting | Location |
|---------|----------|
| VT-d (Intel) / IOMMU (AMD) | Advanced → CPU Configuration |
| Above 4G Decoding / Resizable BAR | Advanced → PCI Subsystem |
| Primary Video / Init Display (if selecting a PCIe GPU) | Advanced → Graphics |

**CPU requirements:**

- Intel 8th gen (Coffee Lake) or newer for QuickSync H.265/HEVC
- Intel 11th gen (Tiger Lake) or newer for AV1 decode
- Intel 12th gen (Alder Lake) or newer for AV1 encode

**Essential backup access:**

> ⚠️ Do not pass through the only display output on your board without an alternative console. If the VM fails to boot or the GPU gets stuck in an unclean state, you lose all video output. SSH into Proxmox or use IPMI to recover.

## Step 1 — Enable IOMMU and Isolate the GPU

Edit `/etc/default/grub` on the Proxmox host:

```text
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt pcie_acs_override=downstream video=efifb:off"
```

The flags:

- `intel_iommu=on` — enables the IOMMU on Intel hardware
- `iommu=pt` — passthrough mode: devices not assigned to VMs are not affected by IOMMU
- `pcie_acs_override=downstream` — splits stubborn IOMMU groups on consumer boards (use only when your GPU shares a group with other devices)
- `video=efifb:off` — unbinds the EFI framebuffer so the GPU is free for passthrough

Update GRUB and reboot:

```bash
update-grub
reboot
```

After reboot, load the VFIO kernel modules and bind the GPU to vfio-pci at boot. Create `/etc/modprobe.d/vfio.conf`:

```text
options vfio-pci ids=8086:4690,8086:4680
```

Replace the PCI IDs with your GPU and its HDMI/DP audio controller. Find them with `lspci -nn`:

```bash
lspci -nn | grep -i vga
# Example output: 00:02.0 VGA compatible controller [0300]: Intel Corporation Raptor Lake-S GT1 [UHD Graphics 770] [8086:4690]
lspci -nn | grep -i audio
# 00:1f.3 Audio device [0403]: Intel Corporation Raptor Lake-P/U/H cAVS [8086:4680]
```

Add the VFIO modules to the initramfs. Edit `/etc/initramfs-tools/modules`:

```text
vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd
```

Rebuild initramfs and reboot again:

```bash
update-initramfs -u -k all
reboot
```

After the second reboot, confirm the GPU is bound to vfio-pci:

```bash
lspci -nnk -s 00:02.0
# Kernel driver in use: vfio-pci
```

## Step 2 — Verify IOMMU Groups

Run this script on the Proxmox host to check that the GPU is in its own IOMMU group:

```bash
#!/bin/bash
shopt -s nullglob
for g in /sys/kernel/iommu_groups/*; do
  echo "IOMMU Group ${g##*/}:"
  for d in "$g"/devices/*; do
    echo -e "\t$(lspci -nns ${d##*/})"
  done
done
```

You want the VGA device and its audio function in the same group together, without the NVMe controller or any network card. If the group contains unrelated devices, add `pcie_acs_override=downstream` to the kernel cmdline (already included above) or consider a different PCIe slot.

## Step 3 — Create and Configure the Proxmox VM

Create the VM with the correct machine type and firmware:

```bash
qm create 200 \
  --name jellyfin \
  --memory 4096 \
  --cores 4 \
  --cpu host \
  --machine q35 \
  --bios ovmf \
  --efidisk0 local-lvm:1 \
  --scsihw virtio-scsi-single \
  --net0 virtio,bridge=vmbr0
```

Attach a boot disk and install an OS (Ubuntu 24.04 LTS or Debian 12 work well). Then add the GPU:

```bash
qm set 200 \
  --hostpci0 0000:00:02.0,legacy-igd=1,x-vga=on,pcie=1 \
  --vga none
```

Key hostpci0 flags:

- `legacy-igd=1` — enables Intel GVT-g legacy mode for iGPU boot display emulation (prevents boot hangs)
- `x-vga=on` — marks this as the primary GPU in the VM; critical for drivers to detect the device
- `pcie=1` — presents the device as PCIe instead of PCI (required for q35 machine type)

Set `--vga none` since the GPU handles display output now. If you still want a console via noVNC, use `--vga virtio` instead and enable the SPICE display.

## Step 4 — Install Drivers in the Guest VM

Inside the VM, install the Intel media drivers:

```bash
# Ubuntu/Debian
apt update
apt install intel-media-va-driver-non-free vainfo intel-gpu-tools

# Verify
vainfo | grep -i intel
```

Expected output shows the driver version and supported profiles:

```text
libva info: VA-API version 1.22.0
libva info: Trying to open /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so
libva info: Found init function __vaDriverInit_1_22
vainfo: VA-API: Intel iHD driver for Intel(R) Gen Graphics - 24.3.4
vainfo: Driver version: 24.3.4
      VAProfileH264High               : VAEntrypointVLD
      VAProfileHEVCMain               : VAEntrypointVLD
      VAProfileHEVCMain10             : VAEntrypointVLD
      VAProfileVP9Profile0            : VAEntrypointVLD
      VAProfileVP9Profile2            : VAEntrypointVLD
      VAProfileAV1Profile0            : VAEntrypointVLD
```

If nothing shows up and `ls /dev/dri` only lists `dri/card0`, the vfio-pci binding on the host is likely correct but the guest kernel needs the `i915` module loaded:

```bash
modprobe i915
echo "i915" >> /etc/modules
```

## Step 5 — Configure Jellyfin Hardware Transcoding in Docker

Deploy Jellyfin with Docker in the guest VM. Create a docker-compose.yml:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
    volumes:
      - ./config:/config
      - ./cache:/cache
      - /media:/media:ro
    devices:
      - /dev/dri:/dev/dri
    ports:
      - "8096:8096"
      - "8920:8920"
    restart: unless-stopped
```

The key line is `devices: - /dev/dri:/dev/dri`. This passes the host (guest VM's) DRI device nodes into the container.

**Permissions fix**: If Jellyfin can't access the GPU, add the jellyfin user to the `render` and `video` groups inside the container, or set the container to run in privileged mode temporarily for debugging:

```bash
# Check ownership
ls -la /dev/dri/
# crw-rw---- 1 root video  226,   0 ...
# crw-rw---- 1 root render 226, 128 ...

# Add container user to groups
docker exec jellyfin usermod -aG video jellyfin
docker exec jellyfin usermod -aG render jellyfin
```

Inside the Jellyfin admin panel:

1. Go to Dashboard → Playback → Transcoding
2. Set **Hardware acceleration** to **VA-API**
3. Select **Intel iHD** driver (or Intel i965 for older hardware)
4. Enable **Enable hardware encoding** and **Allow encoding in HEVC format**
5. Toggle **Enable VPP tone mapping** (HDR→SDR, uses iGPU fixed-function hardware)
6. Save and test by playing a video that requires transcoding (e.g., play a high-bitrate 4K file on a browser tab)

## Performance Tuning and Troubleshooting

### Common Issues

**"Failed to initialise VAAPI connection"**

```bash
# Inside the guest VM, not the container
ls /dev/dri
# Should show renderD128 and card0
dmesg | grep i915
# Check for driver errors
```

If the i915 driver isn't loaded: `modprobe i915`.

**"Render node not found"** — the Jellyfin container user doesn't have permission:

```bash
# Add container user to render group
docker exec jellyfin usermod -aG video jellyfin
docker exec jellyfin usermod -aG render jellyfin
```

Or run the container with `group_add`:

```yaml
services:
  jellyfin:
    # ...
    group_add:
      - "44"   # video
      - "107"  # render
```

**Transcoding is slow or pixelated** — the VM may not be passing the GPU topology correctly:

```bash
# Check inside the guest
intel_gpu_top
```

This shows real-time GPU utilization, decode/encode engine load, and memory bandwidth. If the GPU engines stay at 0% during playback, hardware acceleration isn't engaged.

### Tuning Tips

**CPU pinning** isolates physical cores for the VM, reducing cache thrashing:

```bash
qm set 200 --numa 1
# Then pin cores: qm set 200 --cpulimit 4 --cpuunits 1024
# Or set the CPU pinning in /etc/pve/qemu-server/200.conf
# cpu: 0-3
```

**Hugepages** reduce TLB pressure for memory-intensive transcoding:

```bash
# On the Proxmox host
echo "vm.nr_hugepages=2048" >> /etc/sysctl.conf
sysctl -p
qm set 200 --hugepages any
```

## When to Use an Intel Arc A380 Instead

If your CPU lacks QuickSync or you need more transcode throughput, the Intel Arc A380 is a drop-in replacement that uses the same passthrough technique:

- Full AV1 hardware encode/decode (10-bit, HDR metadata passthrough)
- Handles 6–8 simultaneous 4K HDR tone-mapped transcodes
- Idle power draw ~8W, load ~35W
- Available for ~$100–130 USD on secondary market

The only difference in setup is the PCIe slot and device ID. Everything else — IOMMU verification, vfio-pci binding, VM config — is identical. The Arc uses the same `i915` kernel driver in the guest.

## Conclusion

GPU passthrough on Proxmox transforms a homelab media server from a CPU-bound bottleneck into an efficient, quiet transcoding powerhouse. The upfront effort — enabling IOMMU, binding vfio-pci, and setting the correct VM flags — pays off every time someone streams on a phone, a tablet, or an older TV that doesn't support HEVC.

The same GPU can also accelerate Frigate object detection, offload Ollama inference, or batch-transcode your media library with HandBrake CLI. One pass-through device, many workloads.

Set yours up and let me know how it goes in the comments. Got an Arc card in your homelab? I'd love to hear about your experience with AV1 transcoding.
