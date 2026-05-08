---
title: "Deploying Frigate NVR on Proxmox — Tapo C100, OpenVINO, and Telegram Alerts"
description: "Setting up Frigate with hardware-accelerated object detection on a Proxmox LXC using OpenVINO, a Tapo C100 camera, and a custom Telegram notifier."
date: 2026-05-07
tags:
  - frigate
  - proxmox
  - docker
  - cameras
categories:
  - homelab
  - monitoring
---

Frigate is an open-source NVR built for real-time object detection with local processing. No cloud subscriptions, no vendor lock-in — just cameras, a GPU, and decent detection models.

This is how I set it up on my Proxmox host, with a Tapo C100 camera, Intel GPU inference via OpenVINO, MQTT eventing, and Telegram notifications.

---

## Architecture

```
┌──────────────┐    RTSP (stream1/stream2)    ┌──────────────┐
│   Tapo C100  │ ───────────────────────────▶ │   Frigate    │
│  10.0.50.101 │                              │  10.0.20.15  │
└──────────────┘                              │              │
                    CCTV VLAN (50)            │  Web UI:5000 │
                                               │  RTSP :8554  │
   ┌──────────┐                                │  WebRTC:8555 │
   │ Telegram │ ◀──── MQTT events ────────    │  go2rtc:1984 │
   │  alerts  │     (frigate-notifier)         │  API   :8971 │
   └──────────┘                                └──────┬───────┘
                                                       │
                                               ┌──────▼───────┐
                                               │  Mosquitto   │
                                               │   MQTT:1883  │
                                               └──────────────┘
```

The camera lives on VLAN 50 (CCTV). Frigate runs on a Debian LXC on VLAN 20 (LAB). The router's firewall allows Frigate's host (10.0.20.15) to reach the camera subnet — nothing else touches CCTV.

---

## Host Setup

Frigate runs on an **HP ProDesk G3 DM** (i5-7500T, 2 GB RAM) as a Debian LXC on Proxmox:

```
IP:            10.0.20.15/24 (VLAN 20 LAB)
CPU:           Intel i5-7500T @ 2.70GHz (2 cores)
RAM:           2 GB
GPU:           Intel HD Graphics 630
Storage:       ~17 GB zvol + 8.5 GB for recordings
OS:            Debian Bookworm
```

Key requirement: the LXC needs `/dev/dri/renderD128` passed through for Intel GPU access. In Proxmox, this means the LXC must be **privileged** (or use device cgroup), and you add to `/etc/pve/lxc/<CT_ID>.conf`:

```
lxc.cgroup2.devices.allow: c 226:128 rwm
lxc.mount.entry: /dev/dri/renderD128 dev/dri/renderD128 none bind,optional,create=file
```

Inside the container, the `render` group must match the host's GID. This gives VAAPI and OpenVINO access for hardware-accelerated decoding and inference.

---

## Docker Stack

Frigate ships as Docker containers, along with Mosquitto for MQTT and a custom notifier:

```yaml
version: "3.9"

services:
  frigate:
    container_name: frigate
    restart: unless-stopped
    stop_grace_period: 30s
    image: ghcr.io/blakeblackshear/frigate:stable
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ./config:/config
      - ./storage:/media/frigate
      - type: tmpfs
        target: /tmp/cache
        tmpfs:
          size: 1000000000
    ports:
      - "5000:5000"    # Web UI
      - "8554:8554"    # RTSP
      - "8555:8555/tcp"
      - "8555:8555/udp" # WebRTC
      - "1984:1984"    # go2rtc
      - "8971:8971"    # API
    devices:
      - /dev/dri/renderD128:/dev/dri/renderD128
    cap_add:
      - CAP_PERFMON
    shm_size: "512mb"

  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
      - ./mosquitto/log:/mosquitto/log
```

Mosquitto requires a password file:

```bash
docker exec mosquitto mosquitto_passwd -c /mosquitto/config/pwfile frigate
```

With `mosquitto.conf`:

```
allow_anonymous false
password_file /mosquitto/config/pwfile
listener 1883
persistence true
persistence_location /mosquitto/data/
log_dest file /mosquitto/log/mosquitto.log
```

---

## Camera

The **Tapo C100** is an indoor WiFi camera that speaks RTSP — no proprietary app required for local streaming. RTSP must be enabled in the Tapo app's advanced settings.

| Setting | Value |
|---------|-------|
| IP | 10.0.50.101 (VLAN 50 CCTV) |
| Model | Tapo C100 |
| Stream 1 (main) | `rtsp://<user>:<pass>@10.0.50.101:554/stream1` — 1280×720 @ 5fps |
| Stream 2 (sub) | `rtsp://<user>:<pass>@10.0.50.101:554/stream2` — lower res + audio |

---

## Frigate Config

```yaml
mqtt:
  enabled: true
  host: mosquitto
  port: 1883
  user: frigate
  password: <mosquitto-password>

detectors:
  ov:
    type: openvino
    device: GPU
    model_path: /openvino-model/ssdlite_mobilenet_v2.xml

model:
  width: 300
  height: 300

objects:
  track:
    - person

cameras:
  tapo:
    ffmpeg:
      inputs:
        - path: rtsp://<user>:<pass>@10.0.50.101:554/stream1
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 720
      fps: 5
    motion:
      threshold: 8
      contour_area: 10
      improve_contrast: true
    objects:
      track:
        - person

snapshots:
  enabled: true
  retain:
    default: 7

record:
  enabled: true
  motion:
    days: 7

go2rtc:
  streams:
    tapo:
      - rtsp://<user>:<pass>@10.0.50.101:554/stream1
```

### Why OpenVINO over Coral TPU?

The i5-7500T's integrated HD 630 GPU is perfectly adequate for a single 720p camera doing person detection. A Coral TPU would be overkill for this scale and adds cost + USB passthrough complexity. OpenVINO at 300×300 inference runs comfortably at 5fps with minimal CPU load.

---

## Detection Model

Frigate 0.17 ships with OpenVINO models. The config specifies `ssdlite_mobilenet_v2.xml` (300×300) which Frigate maps to the actual model path at runtime.

For a single camera, this is fast enough. If scaling to multiple cameras:
- Bump resolution to 320×320 for slightly better accuracy
- Drop to the `cpu` detector as fallback
- Or add a Coral TPU via USB

---

## Firewall Rules

On the router, Frigate traffic flows through these rules:

- **All VLANs → server 10.0.20.15** — generic allow for any VLAN to reach the Frigate host
- **Frigate hosts → CCTV VLAN** — `src-address=10.0.20.15 dst-address=10.0.50.0/24`
- Inter-VLAN default-drop ensures nothing else reaches CCTV

This means the Frigate container on VLAN 20 can pull RTSP from the camera on VLAN 50, while the camera itself is completely isolated from the rest of the network.

---

## Telegram Notifications

Frigate's built-in notifications are disabled. Instead, a custom Python notifier (`frigate-notifier`) subscribes to MQTT events at topic prefix `frigate` and pushes detection clips and snapshots to a Telegram chat.

The notifier:
- Listens for `frigate/events` for new detections
- Downloads the snapshot and clip from Frigate's API
- Sends them via Telegram bot
- Filters to `person` detections only

This gives real-time alerts when someone approaches the house, with video evidence, no cloud storage involved.

---

## Storage

| Type | Path | Retention |
|------|------|-----------|
| Recordings | `/media/frigate/recordings/` | Continuous: 1d, Motion: 7d |
| Clips/Snapshots | `/media/frigate/clips/` | 7 days |
| Cache | tmpfs (1 GB) | Ephemeral |

Storage is modest — ~150 MB for a few days with one camera at 720p. A dedicated disk or larger zvol would matter at scale.

---

## Results & Caveats

**What works well:**
- Real-time person detection — alerts within seconds of motion
- go2rtc for WebRTC live view (sub-second latency in the UI)
- MQTT event integration works reliably for automation
- No subscription costs

**What to watch for:**
- WiFi cameras drop frames under load — wire them if possible
- The C100 RTSP stream can disconnect; Frigate auto-reconnects but you'll lose a few seconds
- OpenVINO on iGPU uses system RAM as VRAM — 2 GB RAM is tight, 4 GB is safer
- 720p detection at 5fps is fine for walkway coverage — adjust based on your scene

---

## Future

Next steps:
- Add a second camera (doorbell or driveway)
- Move to Coral TPU if adding more cameras
- Integrate with Home Assistant for richer automations
- Semantic search for reviewing footage by description
