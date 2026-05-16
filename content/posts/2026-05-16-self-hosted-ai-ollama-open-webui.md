---
title: "Self-Hosted AI — Deploy Ollama and Open WebUI in Your Homelab"
description: "Run local LLMs with Ollama and Open WebUI on your own hardware. Full Docker Compose setup, GPU passthrough, model management, and practical AI for the privacy-conscious homelab."
date: 2026-05-16T12:00:00-04:00
tags:
  - docker
  - homelab
  - linux
  - security
  - automation
keywords:
  - Ollama homelab setup
  - Open WebUI Docker Compose
  - self-hosted LLM inference
  - local AI privacy homelab
  - Ollama GPU passthrough Docker
  - self-hosted AI model management
  - Ollama Docker deployment
summary: "Deploy Ollama and Open WebUI on your homelab hardware for private, self-hosted AI inference. Covers Docker Compose setup, GPU acceleration, model management, remote access, and production hardening tips."
canonical: "https://gntech.dev/posts/self-hosted-ai-ollama-open-webui/"
---

Running large language models locally in your homelab isn't just a
novelty anymore — it's becoming a practical alternative to API-dependent
workflows. You get full data privacy, no rate limits, no API costs, and
complete control over which models run and when.

Ollama handles model inference with a simple API, and Open WebUI gives
you a ChatGPT-like interface with RAG, document uploads, and multi-model
support. Together, they form the backbone of a self-hosted AI stack that
runs entirely on your hardware.

This guide walks through deploying Ollama and Open WebUI with Docker
Compose on a Proxmox VM or bare-metal Linux host, with GPU acceleration,
model management, backup strategies, and remote access via Cloudflare
Tunnel or Tailscale.

---

## Why Self-Host AI in the Homelab?

Three reasons make local inference compelling for the homelab in 2026:

**Privacy** — Your prompts, files, and conversation history never leave
your network. No data is shipped to third-party API endpoints. For
services handling sensitive queries or document analysis, this is the
only option.

**Cost** — A mid-range consumer GPU (used RTX 3090 24GB at around
$700-900) runs most open models at usable speeds. Compare that to
continuous API bills for a power user running AI daily. The GPU pays
for itself in months if you'd otherwise rely on paid tiers.

**Latency and reliability** — No API downtime. No rate limiting. No
sudden deprecation of the model you depend on. Local inference has
predictable latency — around 30-50 tokens/second on a 24GB card for
7B-13B parameter models.

The trade-off is hardware cost and the 1-3 hour setup time. After that,
it's self-sustaining.

---

## Docker Compose — Ollama and Open WebUI

The cleanest deployment uses two containers on the same Docker network.
Ollama exposes its API on port 11434, and Open WebUI connects to it
internally.

```yaml
version: "3.8"

services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    volumes:
      - ollama-data:/root/.ollama
    ports:
      - "11434:11434"
    environment:
      - OLLAMA_KEEP_ALIVE=5m
      - OLLAMA_NUM_PARALLEL=1
      - OLLAMA_MAX_LOADED_MODELS=1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    networks:
      - ai-net

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped
    depends_on:
      - ollama
    ports:
      - "3000:8080"
    volumes:
      - open-webui-data:/app/backend/data
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - WEBUI_SECRET_KEY=your-secure-generated-key-here
      - WEBUI_NAME=GnTech AI
      - ENABLE_SIGNUP=false
    networks:
      - ai-net

volumes:
  ollama-data:
  open-webui-data:

networks:
  ai-net:
    driver: bridge
```

**Key configuration notes:**

- `OLLAMA_KEEP_ALIVE=5m` — keeps the model loaded in GPU memory for 5
  minutes after the last request. Set higher (30m) for frequent use or
  lower (30s) to free VRAM faster.
- `OLLAMA_NUM_PARALLEL=1` — processes one request at a time. Increase
  to 2-4 on high-VRAM cards if you expect concurrent users.
- `OLLAMA_MAX_LOADED_MODELS=1` — keeps only one model in GPU memory.
  Increase if you switch models frequently and have VRAM to spare.
- `WEBUI_SECRET_KEY` — generate a random key with `openssl rand -base64
  42`. This secures session tokens.
- `ENABLE_SIGNUP=false` — disable public signup after creating your
  admin account. You enable it temporarily, create your user, then
  disable it.

Deploy with:

```bash
docker compose -f docker-compose.yml up -d
```

---

## GPU Passthrough for Containers

Ollama won't use your GPU without the NVIDIA container toolkit
installed on the Docker host. On a Proxmox VM, this means:

**1. Passthrough the GPU to the VM** — in the Proxmox UI or via CLI:

```bash
# Identify the GPU
lspci | grep -i nvidia

# Attach to VM (replace 101 with your VM ID)
qm set 101 -hostpci0 01:00.0,pcie=1
```

**2. Install the NVIDIA container toolkit inside the VM:**

```bash
# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit

# Configure Docker to use the NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**3. Verify GPU access from a container:**

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If you see GPU info output, you're ready. The Ollama container will
automatically use the GPU when available.

**For AMD GPUs (ROCm):**

```yaml
# In the ollama service, replace the device reservation with:
    devices:
      - /dev/kfd
      - /dev/dri
```

AMD support is improving but NVIDIA remains the most reliable option for
Ollama inference. If possible, use an NVIDIA card for less friction.

---

## Model Management — Pull, Run, and Switch

Ollama makes model management straightforward. The CLI operates inside
the container or through the API.

**Pull your first models:**

```bash
# Enter the container
docker exec -it ollama bash

# Pull models by parameter count and variant
ollama pull llama3.2:3b          # Fast, lightweight (~2GB VRAM)
ollama pull mistral:7b           # General purpose (~4.5GB VRAM)
ollama pull qwen2.5-coder:7b     # Code generation
ollama pull llama3.2:8b-instruct # Conversational
ollama pull deepseek-r1:14b      # Reasoned output (~10GB VRAM)
ollama pull qwen2.5:32b          # Heavy lifting (~20GB VRAM)
```

**Model sizing guide by VRAM:**

| VRAM | Sweet Spot Models | Use Case |
|------|-------------------|----------|
| 6-8 GB | 3B-7B (llama3.2:3b, mistral:7b) | Chat, summarization, light coding |
| 12 GB | 7B-13B (llama3.2:8b, qwen2.5-coder:14b) | Heavy coding, RAG pipelines |
| 24 GB | 14B-32B (deepseek-r1:14b, qwen2.5:32b) | Reasoning, document analysis |
| 48+ GB | 70B quantized (llama3.3:70b-Q4) | Enterprise-level inference |

**List and remove models:**

```bash
docker exec ollama ollama list
docker exec ollama ollama rm llama3.2:3b
```

**Via the API:**

```bash
# List models
curl http://10.0.20.50:11434/api/tags

# Pull a model
curl -X POST http://10.0.20.50:11434/api/pull \
  -d '{"name": "mistral:7b"}'

# Chat completion
curl -X POST http://10.0.20.50:11434/api/chat \
  -d '{
    "model": "mistral:7b",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

---

## Open WebUI Configuration for Power Users

After the first login (create your admin account via the signup flow),
configure Open WebUI for homelab use.

**RAG pipeline — enable document-aware chat:**

1. Navigate to Admin Panel → Documents
2. Upload PDFs, Word docs, or text files
3. Open WebUI chunks and embeds them into Qdrant (MinIO or local
   storage)
4. In any chat, toggle "Use RAG" — the model answers from your
   documents

This turns your AI into a personal knowledge base that knows your
infrastructure, configs, and documentation.

**Web search integration with SearXNG:**

If you run SearXNG (search at http://10.0.20.30:8888 as in this
homelab), point Open WebUI to it:

```yaml
# Add to open-webui environment section
    environment:
      - ENABLE_WEB_SEARCH=true
      - WEB_SEARCH_URL=http://10.0.20.30:8888/search
      - WEB_SEARCH_RESULT_COUNT=5
```

The AI can now search the web for real-time information and incorporate
results into answers — no API key required.

**Multi-user isolation:**

Enable workspace separation in Open WebUI settings:

1. Settings → Users → Enable User Workspaces
2. Each user gets their own chat history, RAG document pool, and model
   preferences
3. Admins can assign specific models to specific users

---

## Securing and Exposing Your AI Stack

Open WebUI listens on port 3000. For LAN access, that's fine. For remote
access, you have two homelab-standard options.

**Option 1: Cloudflare Tunnel (no open ports)**

```yaml
# cloudflared docker-compose service
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared-ai
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=your-tunnel-token
    networks:
      - ai-net
```

Create the tunnel in Cloudflare Zero Trust Dashboard, point it at
`http://open-webui:8080`, and you're accessible at
`https://ai.yourdomain.com` with Cloudflare's WAF in front.

**Option 2: Tailscale (private mesh)**

```yaml
# Sidecar approach
  tailscale:
    image: tailscale/tailscale:latest
    container_name: tailscale-ai
    restart: unless-stopped
    environment:
      - TS_AUTH_KEY=tskey-your-auth-key
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_HOSTNAME=ollama-ai
      - TS_SERVE_PORT=8080
    volumes:
      - tailscale-state:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - NET_ADMIN
      - NET_RAW
    networks:
      - ai-net

volumes:
  tailscale-state:
```

With Tailscale Serve, `https://ollama-ai.tailnet-name.ts.net` resolves
to your Open WebUI without any firewall rule changes.

**Production hardening:**

```bash
# Never expose Ollama API port 11434 to the internet
# Bind it to localhost only, or use an internal Docker network
# Bad:   ports: "11434:11434" 
# Good:  no ports — only internal network access

# Run Open WebUI behind Traefik with Let's Encrypt for real TLS
# Block direct port access with UFW
ufw deny 3000
ufw deny 11434
```

---

## Backup and Migration Strategy

Your Ollama models are large files (4-40 GB each) stored under
`/root/.ollama/models/`. Open WebUI data (chats, settings, RAG
documents) lives separately. Back them up differently.

**Backup script for AI data:**

```bash
#!/bin/bash
# ai-backup.sh — backs up Ollama models + Open WebUI data

BACKUP_PATH="/backups/ai-stack"
DATE=$(date +%Y%m%d)
OLLAMA_VOLUME="gntech_ollama-data"
WEBUI_VOLUME="gntech_open-webui-data"

mkdir -p "$BACKUP_PATH/$DATE"

# Backup Ollama models (can be re-pulled, but saves bandwidth)
docker run --rm \
  -v ${OLLAMA_VOLUME}:/data \
  -v ${BACKUP_PATH}/${DATE}:/backup \
  alpine:latest \
  tar czf /backup/ollama-models.tar.gz -C /data .

# Backup Open WebUI data (chats, settings, RAG index)
docker run --rm \
  -v ${WEBUI_VOLUME}:/data \
  -v ${BACKUP_PATH}/${DATE}:/backup \
  alpine:latest \
  tar czf /backup/open-webui-data.tar.gz -C /data .

echo "AI stack backed up to ${BACKUP_PATH}/${DATE}"
```

**Restoring:**

```bash
# Restore Ollama
docker run --rm \
  -v ${OLLAMA_VOLUME}:/data \
  -v ${BACKUP_PATH}/20260516:/backup \
  alpine:latest \
  tar xzf /backup/ollama-models.tar.gz -C /data

# Restore Open WebUI
docker run --rm \
  -v ${WEBUI_VOLUME}:/data \
  -v ${BACKUP_PATH}/20260516:/backup \
  alpine:latest \
  tar xzf /backup/open-webui-data.tar.gz -C /data
```

Schedule with a systemd timer (same pattern as the volume backup timer
in the Docker volume management guide).

---

## Practical Homelab AI Use Cases

Once the stack is running, here's what it actually does:

**Infrastructure assistant** — Feed it your Ansible playbooks, Docker
Compose files, and Proxmox configs as RAG documents. Ask "how do I
restore my PBS backup?" or "what's the VLAN config for my IoT network?"
and get answers based on your own configs.

**Code generation** — Qwen2.5-Coder or DeepSeek-Coder for writing
scripts, Dockerfiles, and configuration snippets. Run it alongside your
terminal as a coding companion.

**Document analysis** — Drop PDFs (technical manuals, vendor docs) into
Open WebUI and ask questions. The RAG pipeline retrieves relevant
sections from 50+ page documents in seconds.

**API integration** — Ollama's OpenAI-compatible API means any tool that
works with OpenAI (LangChain, n8n, custom scripts) works with your local
instance by changing the base URL. Point OpenClaw or other automation to
`http://10.0.20.50:11434/v1` and use local models for tool calls.

---

## Summary

```bash
# Quick reference — essential commands

# Deploy the stack
docker compose up -d

# Pull a model
docker exec ollama ollama pull mistral:7b

# Check GPU usage
docker exec ollama nvidia-smi

# View logs
docker compose logs -f ollama
docker compose logs -f open-webui

# Update containers
docker compose pull
docker compose up -d

# Test the API
curl http://localhost:11434/api/generate \
  -d '{"model": "mistral:7b", "prompt": "Hello!"}'
```

**Key takeaways:**

1. **Start with a 24GB GPU** — an RTX 3090 runs 7B-32B models and costs
   less than six months of GPT-4 API usage.
2. **Don't expose Ollama directly** — only Open WebUI needs external
   access. The API port stays internal.
3. **Model selection matters** — match model size to your VRAM and use
   case. A 7B model tuned for your task outperforms a 70B model run at a
   quantized 4-bit.
4. **Back up the WebUI data, not the models** — models can be re-pulled.
   Your chat history and RAG documents are the valuable part.
5. **Integrate with your stack** — SearXNG for web search, Traefik for
   TLS, Tailscale or Cloudflare for remote access. The AI stack fits
   into your existing homelab infrastructure like any other service.

Running AI locally isn't a science experiment anymore. It's a
production-grade service that belongs in every homelab alongside DNS,
monitoring, and media servers. Your data stays yours, the API is always
available, and the models keep getting better.
