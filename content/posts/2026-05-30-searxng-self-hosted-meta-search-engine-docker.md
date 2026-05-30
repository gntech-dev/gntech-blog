---
title: "SearXNG — Self-Hosted Private Meta Search Engine with Docker"
description: "Deploy SearXNG, a privacy-respecting self-hosted meta search engine, with Docker Compose, Traefik reverse proxy, and custom configuration for your homelab."
date: 2026-05-30T18:30:00-04:00
tags:
  - docker
  - selfhosting
  - privacy
  - search
  - homelab
keywords:
  - SearXNG self-hosted meta search engine Docker deployment
  - SearXNG Docker Compose homelab setup Traefik
  - SearXNG settings.yml configuration engine enable disable
  - SearXNG privacy self-hosted search engine alternative Google
  - SearXNG Docker reverse proxy Traefik homelab
  - SearXNG rate limit bot protection Valkey Redis configuration
  - SearXNG themes UI customization dark mode favicons
summary: "Deploy SearXNG with Docker Compose for a privacy-focused self-hosted meta search engine. Covers reverse proxy setup with Traefik, search engine configuration, rate limiting, and theme customization."
canonical: "https://blog.gntech.me/posts/searxng-self-hosted-meta-search-engine-docker/"
---

## Why Self-Host a Meta Search Engine

Every search query you type into Google, Bing, or DuckDuckGo sends your IP address, browser fingerprint, and search terms to servers you don't control. [SearXNG](https://docs.searxng.org/) solves this by acting as a privacy proxy between you and the search engines — your browser talks to your SearXNG instance, and SearXNG queries the upstream engines on your behalf without leaking your IP.

Running SearXNG in your homelab gives you:

- **Full visibility** into which engines handle each query
- **Engine selection** per category (general, files, images, maps, social media)
- **No rate limits** from shared public instances
- **Custom themes and dark mode** out of the box
- **Self-contained stack** — Docker Compose, no external dependencies

I run SearXNG at my homelab behind Traefik, and it replaced browser-based search entirely. On mobile, I set the instance as the default search engine in Firefox. One config file controls which engines are enabled, how queries are routed, and what data is stored.

## Prerequisites for SearXNG Docker Deployment

Before starting, make sure you have:

- **Docker and Docker Compose** installed on your Docker host (a Proxmox LXC or low-resource VM works fine — SearXNG runs on 512 MB RAM)
- **A domain name** pointing to your homelab (optional but recommended for Traefik)
- **Traefik** or another reverse proxy already running (this guide uses Traefik)

The SearXNG stack uses two containers: the SearXNG application itself and Valkey (the Redis-compatible key-value store) for caching and rate limiting.

### Directory Structure

Create a clean directory for the stack:

```bash
mkdir -p /opt/searxng
cd /opt/searxng
```

## SearXNG Docker Compose Setup

The official SearXNG compose template uses a `docker-compose.yml` and a `.env` file. Here is a version configured for homelab use with Traefik:

```yaml
# /opt/searxng/docker-compose.yml
services:
  core:
    image: searxng/searxng:latest
    container_name: searxng-core
    restart: unless-stopped
    volumes:
      - ./core-config:/etc/searxng:rw
      - ./data:/var/cache/searxng:rw
    environment:
      - SEARXNG_BASE_URL=https://search.yourdomain.com
      - SEARXNG_SECRET_KEY=${SEARXNG_SECRET_KEY:?err}
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
    networks:
      - proxy
      - internal
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.searxng.rule=Host(`search.yourdomain.com`)"
      - "traefik.http.routers.searxng.entrypoints=websecure"
      - "traefik.http.services.searxng.loadbalancer.server.port=8080"

  valkey:
    image: valkey/valkey:8-alpine
    container_name: searxng-valkey
    restart: unless-stopped
    volumes:
      - valkey-data:/data
    cap_drop:
      - ALL
    cap_add:
      - SETGID
      - SETUID
      - SETRLIMIT
    networks:
      - internal
    command: valkey-server --save 3600 1 --loglevel warning

volumes:
  valkey-data:

networks:
  proxy:
    external: true
    name: traefik-net
  internal:
    driver: bridge
```

Generate a strong secret key for the `.env` file:

```bash
openssl rand -hex 48
```

Then create `/opt/searxng/.env`:

```bash
SEARXNG_SECRET_KEY=<paste the 96-character hex string>
```

### What the Compose File Does

- **core** — The SearXNG application listening on port 8080 inside the container. The `SEARXNG_BASE_URL` tells SearXNG what external URL to use for link generation. The `SEARXNG_SECRET_KEY` encrypts session data and rate limiter state.
- **valkey** — In-memory cache used by SearXNG for rate limiting and temporary data. Because it replaces Redis, all SearXNG Redis configuration works against it with no changes. The `--save 3600 1` flag writes a snapshot every hour if at least one change occurred.
- **networks** — The proxy network is external (shared with Traefik). The internal network isolates Valkey from the outside.
- **cap_drop / cap_add** — Minimal Linux capabilities for container hardening.

## Configuring SearXNG Search Engines and Features

SearXNG generates a default `settings.yml` on first start. You can override it by placing a file in the mounted `./core-config` directory.

Create `/opt/searxng/core-config/settings.yml`:

```yaml
# /opt/searxng/core-config/settings.yml
use_default_settings: true

search:
  # Safe search: 0 = off, 1 = moderate, 2 = strict
  safe_search: 0
  # Language set in search results
  default_lang: "en"
  # Format autocomplete suggestions
  autocomplete: "google"
  # Output formats
  formats:
    - html
    - csv
    - json
    - rss

server:
  # Do not register this instance in the public instance list
  public_instance: false
  # Show the instance name in the UI
  instance_name: "GnTech Search"
  # Enable image proxy to hide Referer headers
  image_proxy: true
  # Enable method to limit requests
  limiter: true
  # Redis/Valkey URL for the limiter
  redis_url: "redis://valkey:6379/0"

ui:
  # Default theme: simple, oscar
  default_theme: simple
  # Dark mode: auto, dark, light
  default_theme_style: dark
  # Custom CSS (optional)
  # static_path: "/etc/searxng/static/themes/simple/css/custom.css"

# Engines — enable the ones you use, disable the rest
engines:
  # Google Web
  - name: google
    disabled: false

  # DuckDuckGo (no JS required)
  - name: duckduckgo
    disabled: false

  # Bing
  - name: bing
    disabled: false

  # Brave Search
  - name: brave
    disabled: false

  # Wikipedia
  - name: wikipedia
    disabled: false

  # GitHub
  - name: github
    disabled: false

  # StackOverflow
  - name: stackoverflow
    disabled: false

  # Reddit
  - name: reddit
    disabled: false

  # Docker Hub
  - name: docker_hub
    disabled: false

  # YouTube (Invidious instance)
  - name: invidious
    disabled: false
    instance_url: "https://inv.nadeko.net"

  # Pixabay images
  - name: pixabay
    disabled: false

  # DuckDuckGo definitions
  - name: duckduckgo_definitions
    disabled: false

  # Disable less useful defaults
  - name: 1x
    disabled: true
  - name: apk_mirror
    disabled: true
  - name: google_images
    disabled: true
  - name: google_news
    disabled: true
  - name: google_videos
    disabled: true
  - name: media.ccc.de
    disabled: true
  - name: mixcloud
    disabled: true
  - name: rumble
    disabled: true
  - name: soundcloud
    disabled: true
  - name: twitcher
    disabled: true
```

### Key Configuration Points

- `use_default_settings: true` — Loads the built-in defaults first, then your overrides apply on top. This keeps the file small and maintainable.
- `image_proxy: true` — Images served through SearXNG, not directly from the source, preventing referrer leakage.
- `limiter: true` — Enables rate limiting using Valkey. Without this, any bot can hammer your upstream search engines and get your IP rate-limited.
- `redis_url: "redis://valkey:6379/0"` — Points to the Valkey container in the internal Docker network. The `redis://` protocol prefix works because Valkey is Redis-protocol compatible.
- `public_instance: false` — Prevents your instance from appearing in the public [SearXNG instance list](https://searx.space/). Keep your instance private.
- `default_theme_style: dark` — Dark mode by default, with the simple theme.

## Exposing SearXNG with Traefik Reverse Proxy

If you already run Traefik as a Docker reverse proxy, the compose file labels above handle the routing. Make sure you have:

1. A DNS A record for `search.yourdomain.com` pointing to your homelab
2. The `traefik-net` Docker network available (adjust the name to match your setup)
3. Traefik's ACME (Let's Encrypt) configuration active for TLS

Create or verify the Docker network:

```bash
docker network create traefik-net
```

The Traefik labels in the compose file:

- `traefik.http.routers.searxng.rule=Host(\`search.yourdomain.com\`)` — Routes traffic for that hostname to SearXNG
- `traefik.http.routers.searxng.entrypoints=websecure` — Uses the HTTPS entrypoint
- `traefik.http.services.searxng.loadbalancer.server.port=8080` — Points to the container's internal port 8080

If you use Nginx Proxy Manager or Caddy instead, the setup is similar — just proxy pass to `http://searxng-core:8080` from the reverse proxy container.

## Starting SearXNG and Verifying the Deployment

Start the stack:

```bash
cd /opt/searxng
docker compose up -d
```

Check the logs to confirm startup:

```bash
docker compose logs -f core
```

Look for the line:

```
[INFO] starting server on 0.0.0.0:8080
```

Visit your instance at `https://search.yourdomain.com`. You should see the SearXNG search interface with your configured `instance_name`.

### Testing Searches

Type a query and verify:
1. Results load from multiple engines
2. The "Categories" dropdown shows enabled categories
3. The preferences page (`/preferences`) lists your configured settings
4. Dark mode renders correctly

### Common Issues

**"Invalid base_url" error in logs** — The `SEARXNG_BASE_URL` in `docker-compose.yml` must match the actual URL you are accessing. If you are testing locally, use `http://localhost:8080`.

**Search returns no results** — Some engines require JavaScript and may not work with all themes. Try the `simple` theme if results fail with `oscar`. Check `docker compose logs core` for engine-specific error messages.

**Rate limiter errors** — If you see `429 Too Many Requests` for upstream engines, SearXNG respects upstream rate limits. Reduce query frequency or add a delay in settings.yml:

```yaml
search:
  safe_search: 0
  # Add delay in ms between queries to avoid rate limiting
  request_delay: 1.0
```

## Maintaining Your SearXNG Instance

### Updating Containers

Pull the latest images and restart:

```bash
cd /opt/searxng
docker compose down
docker compose pull
docker compose up -d
```

Always check the [SearXNG release notes](https://github.com/searxng/searxng/releases) before updating, as configuration keys occasionally change.

### Backup

Back up two directories — everything else is disposable:

```bash
tar czf searxng-backup-$(date +%F).tar.gz ./core-config/ ./data/
```

Store the backup off-server (Proxmox Backup Server, remote storage).

### Monitoring

Add a health check to the SearXNG service in `docker-compose.yml`:

```yaml
services:
  core:
    # ... existing config
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
```

SearXNG exposes a `/health` endpoint that returns a 200 status when the application is running and engines are responsive.

## Conclusion

SearXNG replaces public search engines with a self-hosted, privacy-respecting alternative that gives you full control over which engines process your queries, what data is cached, and how rate limiting works. The Docker Compose stack runs on minimal hardware, integrates with any reverse proxy, and costs nothing beyond your homelab's electricity.

Set up search categories — images through Pixabay, code through GitHub and StackOverflow, general queries through DuckDuckGo and Brave. Disable the engines you never use. Drop the default search engine into your browser settings and never expose your IP to a search engine again.

### See Also

- [SearXNG Official Documentation](https://docs.searxng.org/)
- [Docker Compose Production Patterns](/posts/docker-compose-production-patterns/)
- [Traefik Middleware Security Hardening](/posts/traefik-middleware-security-hardening/)
