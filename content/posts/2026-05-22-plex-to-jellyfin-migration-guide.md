---
title: "Plex to Jellyfin Migration Guide — Docker Homelab Setup 2026"
description: "Complete guide to migrating from Plex to Jellyfin in Docker — library migration, watch history transfer, hardware transcoding with Intel QuickSync/NVIDIA, Traefik reverse proxy, and the full arrs stack integration for your homelab."
date: 2026-05-22T10:00:00-04:00
tags:
  - docker
  - homelab
  - linux
  - selfhosting
  - media
keywords:
  - Plex to Jellyfin migration guide homelab
  - Jellyfin Docker Compose hardware transcoding
  - Jellyfin Intel QuickSync NVIDIA NVENC setup
  - Jellyfin Traefik reverse proxy configuration
  - Plex watch history transfer to Jellyfin
  - Sonarr Radarr Jellyfin integration homelab
  - self-hosted media server 2026 Docker stack
summary: "Migrate from Plex to Jellyfin on Docker with this complete guide covering library setup, watch history transfer, hardware transcoding with Intel QSV or NVIDIA NVENC, Traefik reverse proxy, and full arrs stack integration for your homelab media server."
canonical: "https://gntech.dev/posts/plex-to-jellyfin-migration-guide/"
---

Plex raised prices, removed the lifetime pass as a purchase
option, and pushed cloud-dependent features harder than ever.
If you're running a homelab media server, now is the time to
switch to [Jellyfin](https://jellyfin.org) — a fully open-source,
free, self-hosted alternative with no subscriptions, no phoning
home, and complete control over your library.

This guide walks through the full migration from Plex to
Jellyfin in Docker on a Linux homelab: setting up the stack,
configuring hardware transcoding with Intel QuickSync or
NVIDIA NVENC, exposing it securely through Traefik, and
integrating it with Sonarr, Radarr, and the rest of the arrs
ecosystem.

---

## Why Jellyfin Over Plex in 2026

| Feature | Plex | Jellyfin |
|---------|------|----------|
| License | Proprietary (subscription) | GPL 2.0 / AGPL 3.0 |
| Cost | $120/yr or legacy lifetime | Free |
| Hardware transcoding | Plex Pass required | Built-in, no paywall |
| Intro skip | Plex Pass required | Free + plugin |
| Client support | Wide (native apps) | Wide (web, Android TV, Roku, LG, Samsung) |
| Offline mode | Requires cloud auth | Fully offline capable |
| Docker support | Official image | Official + linuxserver images |
| Remote access | Relay/prerequisite auth | Direct or reverse proxy |

The bottom line: Jellyfin gives you everything Plex charges
for — and without sending metadata or authentication through
Jellyfin's servers.

## Prerequisites

- Docker and Docker Compose v2 installed on the host
- Media files on a mounted volume (local, NFS, or NAS)
- (Optional) Intel iGPU or NVIDIA GPU for transcoding
- (Optional) Traefik or Nginx for secure remote access
- `docker` user in the `render` and `video` groups for GPU access

## Step 1: Jellyfin Docker Compose Setup

Create a project directory and compose file:

```bash
mkdir -p /opt/jellyfin
cd /opt/jellyfin
```

```yaml
# docker-compose.yml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config:/config
      - ./cache:/cache
      - /path/to/media:/media:ro
    devices:
      - /dev/dri:/dev/dri          # Intel/AMD GPU transcoding
      # - /dev/dri/renderD128:/dev/dri/renderD128
    environment:
      - JELLYFIN_PublishedServerUrl=homeserver.local  # local hostname
      - PUID=1000
      - PGID=1000
    group_add:
      - "44"     # video
      - "107"    # render
      - "1000"   # user primary group
```

Key decisions:

- **`network_mode: host`** avoids container networking overhead for
  UPnP/DLNA and simplifies hardware transcoding device access. Use
  a bridge network with Traefik if you need per-service networking
  (shown in Step 5).
- **Volume mounts**: bind-mount your media read-only (`:ro`) to
  prevent accidental deletion or modification from Jellyfin.
- **Device passthrough**: `/dev/dri` exposes Intel or AMD iGPUs.
  For NVIDIA, use `nvidia-container-toolkit`.
- **`group_add`** ensures the container process can access DRI
  render nodes. Check `getent group video` and `getent group render`
  on your host for the correct GIDs.

Start the container:

```bash
docker compose up -d
```

Access Jellyfin at `http://homeserver.local:8096` and complete
the initial setup wizard — choose your language, create the admin
account, and point to your media folders.

### NVIDIA GPU Transcoding Setup

If you use an NVIDIA GPU instead of Intel QuickSync:

```bash
# Install nvidia-container-toolkit on the host
sudo apt install nvidia-container-toolkit
sudo systemctl restart docker
```

```yaml
# docker-compose.yml (NVIDIA variant)
services:
  jellyfin:
    image: nvcr.io/nvidia/jellyfin:latest  # or jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config:/config
      - ./cache:/cache
      - /path/to/media:/media:ro
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, video]
```

Enable **NVIDIA NVENC** in Jellyfin Admin → Playback →
Transcoding → Hardware acceleration: select **NVIDIA NVENC**.

## Step 2: Hardware Transcoding Configuration

Log into Jellyfin at `http://homeserver.local:8096`, go to
**Administration → Dashboard → Playback → Transcoding**.

**For Intel QuickSync (QSV):**

- Hardware acceleration: **Intel QuickSync (QSV)**
- Enable: `H.264`, `HEVC`, `VC1`, `MPEG2`, `VP9`, `AV1` (if supported)
- Enable: **Allow encoding in HEVC format**
- Enable: **Allow subtitle extraction on the fly**
- Enable: **Enable VPP tone mapping** (HDR → SDR conversion)
- Enable: **Deinterlacing** (hardware)
- Prefer OS native DXVA: unchecked (Linux)

**For NVIDIA NVENC:**

- Hardware acceleration: **NVIDIA NVENC**
- Enable: `H.264 (NVENC)`, `HEVC (NVENC)`, `AV1 (NVENC)`
- Check **Enable hardware encoding**
- Set **Thread count** to `0` (auto)
- Enable **Tone mapping** (NVENC handles HDR → SDR)

**Verify transcoding works:**

```bash
# Watch Jellyfin logs while playing a 4K video
docker compose logs -f
```

You should see lines like:

```
[INF] [1080p/H264] DirectPlay
[INF] [4K/HDR] Transcoding to 1080p H264 — encoder: QSV h264_qsv
```

If transcoding falls back to software, check:

1. Container user has `video` and `render` group membership
2. `/dev/dri` exists inside the container: `ls -la /dev/dri`
3. Intel GPU drivers are installed: `sudo apt install intel-media-va-driver-non-free`
4. Verify VA-API: `sudo vainfo`

## Step 3: Transferring Watch History from Plex (Optional)

Jellyfin doesn't import Plex data natively, but third-party
tools make the migration painless.

### Option A: jellywatch.app (Automated)

[jellywatch.app](https://jellywatch.app) provides a web-based
tool that exports your Plex watch state and imports it directly
into Jellyfin. It handles:

- Watched/unwatched status per user
- Ratings and review data
- Playlist migration
- Collection metadata

This is the easiest option for most users — ~10 minutes for
a large library.

### Option B: Plex-Trakt-Sync + Trakt (Manual)

If you already use Trakt:

```bash
# Export Plex watch state to Trakt
pip install plex_trakt_sync
plex_trakt_sync sync
```

Then set up the [Jellyfin Trakt plugin](https://github.com/jellyfin/jellyfin-plugin-trakt)
in Admin Dashboard → Plugins → Catalog → Trakt.
Configure your Trakt credentials and it backfills Jellyfin
playback history from Trakt.

### Option C: Direct Database Migration (Advanced)

For users comfortable with SQLite:

```bash
# Download and run plex-to-jellyfin script
wget https://raw.githubusercontent.com/jwetzell/Plex-To-Jellyfin/main/Plex_To_Jellyfin.py
python3 Plex_To_Jellyfin.py \
  --plex-db /path/to/Plex/Media/Server/Plug-in Support/Databases/com.plexapp.plugins.library.db \
  --jellyfin-db /opt/jellyfin/config/data/library.db
```

This copies directly at the database level — fast but comes
with no warranty. Always back up both databases first.

## Step 4: Arrs Integration (Sonarr / Radarr)

Jellyfin connects to Sonarr and Radarr through its API — no
special plugin required.

**In Sonarr** (and similarly for Radarr):

1. Settings → Media Management → Import Lists
2. Add → Jellyfin
3. Fill in:
   - Server URL: `http://homeserver.local:8096`
   - API Key: from Jellyfin Admin Dashboard → API Keys
4. Test connection

**Why this matters**: Sonarr/Radarr can automatically scan and
import new media when Jellyfin refreshes — but more importantly,
the two-way integration means Sonarr removes episodes from
Jellyfin's "Continue Watching" when they're deleted.

**Recommended arrs stack:**

```yaml
services:
  # ... jellyfin config above ...

  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./sonarr/config:/config
      - /path/to/media:/media

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./radarr/config:/config
      - /path/to/media:/media

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./prowlarr/config:/config

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./qbittorrent/config:/config
      - /path/to/downloads:/downloads
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Santo_Domingo
```

## Step 5: Traefik Reverse Proxy for Remote Access

Running on `network_mode: host` your media server is confined to
internal access. To expose Jellyfin securely through Traefik on
a bridge network, create a separate compose file with proper
networking:

```yaml
# jellyfin-traefik.yml
services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    networks:
      - proxy
    volumes:
      - ./config:/config
      - ./cache:/cache
      - /path/to/media:/media:ro
    devices:
      - /dev/dri:/dev/dri
    environment:
      - JELLYFIN_PublishedServerUrl=https://media.yourdomain.com
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.jellyfin.entrypoints=websecure"
      - "traefik.http.routers.jellyfin.rule=Host(`media.yourdomain.com`)"
      - "traefik.http.routers.jellyfin.tls.certresolver=letsencrypt"
      - "traefik.http.services.jellyfin.loadbalancer.server.port=8096"
      - "traefik.http.routers.jellyfin.middlewares=secHeaders@file,rateLimit@file"
      - "traefik.http.routers.jellyfin-ws.rule=Host(`media.yourdomain.com`) && PathPrefix(`/socket`)"
      - "traefik.http.routers.jellyfin-ws.service=jellyfin"
      - "traefik.http.routers.jellyfin-ws.entrypoints=websecure"
      - "traefik.http.routers.jellyfin-ws.tls.certresolver=letsencrypt"

networks:
  proxy:
    external: true
```

Key details:

- **WebSocket routing** is required for Jellyfin's real-time
  playback sync and live TV features. Without the separate
  `jellyfin-ws` router, WebSocket connections fail.
- **`JELLYFIN_PublishedServerUrl`** must match your external
  hostname for client redirects to work correctly.
- **Rate limiting** via `rateLimit@file` prevents the login
  endpoint from being brute-forced remotely.

If you run the Traefik setup, set `internal_networks` in
CrowdSec or your firewall rules to only allow LAN IPs
access to `port 8096` directly (avoid exposing the backend
port remotely — always route through Traefik).

## Step 6: Client Migration

Jellyfin has clients for virtually every platform:

| Platform | Client |
|----------|--------|
| Android TV / Fire TV | Jellyfin for Android TV (Play Store or direct APK) |
| Apple TV | Swiftfin (App Store) |
| LG WebOS | Jellyfin for WebOS (developer mode) |
| Samsung Tizen | Jellyfin for Tizen (developer mode) |
| Roku | Jellyfin for Roku (private channel) |
| Web Browser | https://media.yourdomain.com (direct) |
| iOS | Swiftfin or Jellyfin Mobile (App Store) |
| Kodi | Jellyfin for Kodi plugin |
| Game Consoles | PS4/5 via browser, Xbox via browser or UWP |

Most clients support Direct Play when on the same network,
and gracefully fall back to transcoding over remote connections.

## Post-Migration Checklist

1. **Verify playback**: Test 4K HDR → 1080p SDR transcoding
2. **Check remote access**: Login from external network
3. **Test mobile clients**: Install Swiftfin on iOS/Android
4. **Configure backups**: Back up `/opt/jellyfin/config`
5. **Set up intro skip**: Install the "Scheduled Task"
   plugin from Admin → Plugins → Catalog → Intro Skipper
6. **Enable hardware acceleration** exhaustively — test each
   codec you actually have in your library
7. **Disable or remove Plex** once satisfied

## Wrapping Up

Jellyfin is production-grade, actively maintained, and has
matured significantly over the past few years. The Docker
Compose setup takes under 15 minutes, hardware transcoding
just works on modern Intel and NVIDIA hardware, and the
arrs integration is seamless. With Plex's lifetime pass
effectively dead, there's never been a better time to switch.

The full media stack — Jellyfin, Sonarr, Radarr, Prowlarr,
qBittorrent — runs comfortably on a Proxmox LXC or VM with
4 vCPUs and 8 GB RAM, leaving hardware transcoding to the
iGPU. Your future self will thank you for the subscription-free
setup and the warm feeling of knowing your media server
belongs entirely to you.
