---
title: "Docker GPU Acceleration — NVIDIA Container Toolkit for Homelab"
description: "Enable GPU acceleration in Docker containers using the NVIDIA Container Toolkit. Covers installation, Docker Compose GPU device config, Ollama AI inference, Jellyfin transcoding, and troubleshooting."
date: 2026-05-23T07:00:00-04:00
tags:
  - docker
  - homelab
  - nvidia
  - containers
  - performance
keywords:
  - NVIDIA Container Toolkit Docker installation guide
  - Docker Compose GPU device reservation
  - Ollama Docker GPU acceleration homelab
  - Jellyfin NVIDIA NVENC transcoding Docker
  - nvidia-smi container GPU passthrough
  - Docker runtime nvidia container configuration
  - GPU accelerated containers homelab performance
summary: "Set up GPU acceleration in Docker containers with the NVIDIA Container Toolkit — from installation to real workloads like Ollama AI inference, Jellyfin hardware transcoding, and Frigate object detection."
canonical: "https://gntech.dev/posts/docker-gpu-acceleration-homelab/"
---

Your homelab server has an NVIDIA GPU sitting idle in the PCIe
slot. Docker containers run fine without it, but every AI query
runs on CPU at a crawl, every Jellyfin stream pegs the processor
for transcoding, and Frigate object detection chugs through
frames at single-digit FPS.

The NVIDIA Container Toolkit fixes this. It exposes the GPU to
Docker containers as a natively accessible resource — no
privileged mode, no raw device passthrough, no manual file
descriptor forwarding. Just install the runtime, set a single
Compose option, and your containers see the GPU as if it were
running on bare metal.

This guide covers the complete setup from a fresh install
through production workloads on Ubuntu/Debian and Proxmox LXC
hosts.

---

## Why GPU Accelerate Docker Containers?

A GPU in a Docker workflow is not about gaming or rendering. In
a homelab, the three workloads that benefit most are:

- **AI inference** — Ollama runs LLMs 5–10× faster on GPU than
  CPU. A $200 Tesla P4 or RTX 3060 handles 7B–13B parameter
  models comfortably.
- **Media transcoding** — Jellyfin (or Plex) uses NVIDIA NVENC
  for hardware-accelerated video encoding. A single transcode
  stream on CPU uses 60–80% of a modern processor; NVENC does it
  for under 5%.
- **Computer vision** — Frigate uses TensorRT or OpenCV with CUDA
  for real-time object detection on camera feeds. GPU detection
  slashes inference latency from 500ms to under 30ms per frame.

All three share the same underlying setup: the NVIDIA Container
Toolkit. Once it is running, any Docker container can request GPU
access with a single line in its Compose file.

---

## Prerequisites

- Linux host (Debian 12, Ubuntu 24.04, or Proxmox LXC)
- NVIDIA GPU (Turing or newer for NVENC — GTX 1650, RTX 2060+,
  Tesla P4/P40, A-series)
- NVIDIA proprietary driver installed (`nvidia-smi` works)
- Docker Engine 24+ with `containerd`

### Verify the Driver

```bash
nvidia-smi
```

You should see the driver version, CUDA version, and your GPU:

```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 550.120    Driver Version: 550.120    CUDA Version: 12.4         |
|-------------------------------+----------------------+----------------------+
| GPU  Name            TCC/WDDM | Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|===============================|======================|======================|
|   0  Tesla P4            Off   | 00000000:02:00.0 Off |                  Off |
| N/A   48C    P0   23W /  75W  |     10MiB /   7680MiB |      0%      Default |
+-----------------------------------------------------------------------------+
```

If `nvidia-smi` returns a command-not-found or driver error,
install the driver first:

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y nvidia-driver-550-server
sudo reboot
```

---

## Install the NVIDIA Container Toolkit

The toolkit provides the `nvidia-container-runtime` that Docker
uses to inject GPU devices into containers.

### Add the Repository

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

### Install and Configure Docker

```bash
sudo apt update
sudo apt install -y nvidia-container-toolkit

# Configure Docker daemon to use nvidia runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

The configure step adds the NVIDIA runtime to
`/etc/docker/daemon.json`:

```json
{
  "runtimes": {
    "nvidia": {
      "args": [],
      "path": "nvidia-container-runtime"
    }
  }
}
```

### Verify the Installation

```bash
docker run --rm --runtime=nvidia \
  nvidia/cuda:12.4-base-ubuntu22.04 nvidia-smi
```

You should see the same `nvidia-smi` output inside the container.
This confirms the GPU is accessible within the container
namespace with no manual device mapping.

---

## Docker Compose GPU Configuration

The modern way to expose GPUs in Docker Compose is the
`deploy.resources.reservations.devices` block. This works with
Compose v2.23+ and Docker Engine 24+.

```yaml
services:
  gpu-workload:
    image: my-workload:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

For a specific GPU in a multi-GPU system:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ["GPU-12a3b4c5-def6-7890-abcd-ef1234567890"]
              capabilities: [gpu]
```

To request specific compute capabilities:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, utility, compute]
```

The `capabilities` list controls what is exposed:
- `gpu` — basic GPU device access
- `utility` — `nvidia-smi` monitoring counters
- `compute` — CUDA compute API
- `video` — NVENC/NVDEC video encode/decode
- `display` — display output

For Jellyfin and Frigate, always include `video`:

```yaml
capabilities: [gpu, video]
```

---

## Real Workload: Ollama with GPU Acceleration

Ollama is the most straightforward GPU-accelerated workload for
a homelab. It detects the GPU automatically when the NVIDIA
runtime is configured.

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    volumes:
      - ./ollama_data:/root/.ollama
    environment:
      - OLLAMA_KEEP_ALIVE=24h
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, utility]
    ports:
      - "11434:11434"
```

Pull and run a model to validate GPU usage:

```bash
docker compose exec ollama ollama pull mistral:7b
docker compose exec ollama ollama run mistral:7b "Why is GPU inference faster than CPU?"
```

Check GPU utilization during inference:

```bash
watch -n1 nvidia-smi
```

You should see 60–95% GPU compute utilization during token
generation. Compare this to the same model running on CPU —
typical speedup is 5–10× depending on the model size.

---

## Real Workload: Jellyfin with NVENC Transcoding

Jellyfin uses NVIDIA NVENC for hardware-accelerated video
transcoding. This requires the `video` capability in addition
to `gpu`.

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    volumes:
      - ./jellyfin_config:/config
      - ./media:/media
    group_add:
      - "44"  # video group on host
    environment:
      - NVIDIA_DRIVER_CAPABILITIES=all
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, video]
    ports:
      - "8096:8096"
```

After deployment:

1. Open Jellyfin admin dashboard → Playback → Transcoding
2. Set **Hardware acceleration** to **NVIDIA NVENC**
3. Select the GPU device from the dropdown
4. Enable **Hardware encoding** and **Hardware decoding**
5. Save and test by playing a 4K HEVC file through the web
   client — check the playback info for "Hardware: yes"

To verify transcoding is GPU-accelerated:

```bash
# Monitor encoder utilization
nvidia-smi -q -d ENCODER

# Watch decoder utilization
nvidia-smi -q -d DECODER
```

A single Tesla P4 handles 4–6 simultaneous 1080p transcodes or
2–3 4K → 1080p transcodes without breaking a sweat.

---

## Real Workload: Frigate with TensorRT Detection

Frigate 0.15+ supports NVIDIA TensorRT for hardware-accelerated
object detection. This dramatically reduces inference latency
compared to the default CPU-based OpenVINO or Coral TPU modes.

```yaml
services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:stable
    container_name: frigate
    restart: unless-stopped
    privileged: false
    volumes:
      - ./frigate_config:/config
      - ./frigate_storage:/media/frigate
    environment:
      - FRIGATE_RTSP_PASSWORD=${RTSP_PASSWORD}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, utility, compute]
    tmpfs:
      - /tmp/cache:size=1G
    ports:
      - "5000:5000"
```

Frigate config snippet for TensorRT:

```yaml
# /config/config.yml
detectors:
  tensorrt:
    type: tensorrt
    device: 0

model:
  path: /config/modelcache/tensorrt/yolov7-320.trt
  width: 320
  height: 320
  input_tensor: nchw
  input_pixel_format: rgb
```

With GPU detection, frame processing goes from 2–3 FPS on CPU
to 25–30 FPS on a Tesla P4 — the difference between missing
motion events and catching everything.

---

## Proxmox LXC Considerations

Running Docker inside a Proxmox LXC requires an extra step to
pass the GPU into the container. Add these lines to the LXC
config file (`/etc/pve/lxc/<ID>.conf`):

```ini
lxc.cgroup2.devices.allow: c 195:* rwm
lxc.cgroup2.devices.allow: c 509:* rwm
lxc.cgroup2.devices.allow: c 226:* rwm
lxc.mount.entry: /dev/nvidia0 dev/nvidia0 none bind,optional,create=file
lxc.mount.entry: /dev/nvidiactl dev/nvidiactl none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-modeset dev/nvidia-modeset none bind,optional,create=file
lxc.mount.entry: /dev/nvidia-uvm dev/nvidia-uvm none bind,optional,create=file
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
```

Then run `pct reboot <ID>` to apply. After reboot, install the
NVIDIA driver and Container Toolkit inside the LXC as described
above.

---

## Troubleshooting

### "No available runtime" or "Unknown runtime nvidia"

The Docker daemon does not see the NVIDIA runtime:

```bash
# Check daemon.json
cat /etc/docker/daemon.json

# Re-run the toolkit config
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### "could not select device driver" error

The Compose file references `driver: nvidia` but the runtime is
not registered. This is the same fix as above — run
`nvidia-ctk runtime configure` and restart Docker.

### Container sees no GPU despite runtime

```bash
# Verify from the host
nvidia-smi

# Verify inside the container
docker run --rm --gpus all ubuntu:22.04 nvidia-smi

# If the container still fails, check the nvidia-fabricmanager
sudo systemctl status nvidia-fabricmanager
sudo systemctl restart nvidia-fabricmanager
```

Fabric Manager is required for multi-GPU Tesla cards (P40, A2,
T4) in certain configurations.

### NVENC not available in Jellyfin

The `video` capability must be in the `capabilities` list, and
the GPU must support NVENC. Check your GPU's encode/decode
support:

```bash
# List supported codecs for your GPU
nvidia-smi -q -d ENCODER
nvidia-smi -q -d DECODER
```

GPUs without NVENC (GTX 10-series non-Ti, older Kepler cards)
cannot accelerate encoding. If your card lacks NVENC, use the
Intel QuickSync path instead.

---

## Summary

The NVIDIA Container Toolkit transforms a homelab GPU from an
idle PCIe occupant into a shared accelerator for every container
on the host. The setup is four commands:

1. Install `nvidia-container-toolkit`
2. Configure the Docker runtime
3. Add `deploy.resources.reservations.devices` to your Compose
   files
4. Deploy GPU-accelerated Ollama, Jellyfin, or Frigate

No Kubernetes, no custom images, no privileged containers. Just
a GPU that actually earns its slot in the case.
