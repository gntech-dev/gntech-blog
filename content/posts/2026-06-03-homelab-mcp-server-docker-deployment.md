---
title: "Homelab MCP Server — AI-Powered Infrastructure via Claude Desktop"
description: "Deploy the Homelab MCP server in Docker for AI-powered infrastructure management via Claude Desktop. Monitor containers, AI models, Pi-hole DNS, and network devices through natural language."
date: 2026-06-03T17:00:00-04:00
tags:
  - homelab
  - docker
  - automation
  - selfhosting
  - ai
keywords:
  - Homelab MCP server Docker deployment guide
  - Claude Desktop homelab infrastructure AI management
  - Docker MCP server container monitoring configuration
  - Ollama MCP server homelab AI model management
  - Pi-hole MCP DNS query monitoring Claude
  - Self-hosted AI infrastructure monitoring tool
  - Model Context Protocol homelab automation setup
summary: "Deploy the Homelab MCP server in Docker to manage your homelab infrastructure through Claude Desktop. Monitor Docker containers, Ollama AI models, Pi-hole DNS, and network devices using natural language commands."
canonical: "https://blog.gntech.me/posts/homelab-mcp-server-docker-deployment/"
---

## What Is MCP and Why Your Homelab Needs It

The Model Context Protocol (MCP) is an open protocol developed by Anthropic that standardizes how AI assistants connect to external tools and data sources. Think of it as a USB-C port for AI — one standard connection that lets Claude reach into your infrastructure instead of guessing or hallucinating.

Before MCP, asking Claude about your homelab meant pasting terminal output into a chat window. MCP flips that: Claude connects directly to your services via MCP servers and executes real queries against live data. You ask "What containers are running on my Docker host?" and Claude calls a Docker API endpoint, formats the response, and shows you the result.

The [Homelab MCP](https://github.com/bjeans/homelab-mcp) project bundles seven specialized MCP servers into a single Docker container. Deploy it once, configure Claude Desktop, and you have natural language access to Docker containers, Ollama AI models, Pi-hole DNS stats, Unifi network devices, UPS power status, Ansible inventory, and ICMP connectivity checks.

**Prerequisites:** Docker Engine, Claude Desktop (free tier works), and at least one homelab service you want to monitor.

## What the Homelab MCP Server Does

The unified container runs all seven MCP servers in a single process. Each server exposes namespaced tools so Claude knows which service to query:

| Server | Tools | What You Can Ask |
|--------|-------|-------------------|
| Docker/Podman | `docker_get_containers`, `docker_inspect` | "List all running containers" |
| Ollama | `ollama_list_models`, `ollama_ps` | "What models are loaded?" |
| Pi-hole | `pihole_get_stats`, `pihole_get_query_types` | "Top DNS queries in the last hour" |
| Unifi | `unifi_list_devices`, `unifi_list_clients` | "Show me all connected clients" |
| UPS/NUT | `nut_get_status`, `nut_get_battery` | "What is the UPS battery level?" |
| Ansible | `ansible_list_hosts`, `ansible_get_groups` | "Show my Ansible inventory summary" |
| Ping | `ping_ping_host` | "Ping my Proxmox host" |

The unified mode uses namespaced tool names (e.g., `docker_get_containers`) so there is no collision between servers. This is the recommended mode and the only one supported for Docker deployments.

## Docker Deployment

Pull the image and set up a compose file. The container is available on Docker Hub:

```bash
docker pull bjeans/homelab-mcp:latest
```

### Docker Compose Configuration

Create `docker-compose.yml` in a dedicated directory:

```yaml
services:
  homelab-mcp:
    image: bjeans/homelab-mcp:latest
    container_name: homelab-mcp
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./ansible_hosts.yml:/app/ansible_hosts.yml:ro
    networks:
      - homelab-mcp
    # No ports exposed — Claude Desktop connects via
    # Docker's internal networking or host-mode transport

networks:
  homelab-mcp:
    name: homelab-mcp
    internal: true
```

The `internal: true` network ensures the MCP server cannot be reached from outside the host. Claude Desktop communicates with the container through Docker's STDIO transport or a bind-mount socket — not over the network.

If your Docker host has a Unix socket for Docker (the default), mount it read-only. The container uses this to query container status without needing elevated permissions on the host.

### Starting the Container

```bash
docker compose up -d
docker compose logs -f  # Verify it started cleanly
```

A successful start logs:

```
[INFO] Homelab MCP Unified Server v3.0.0 starting...
[INFO] Registered 7 server modules: docker, ollama, pihole, unifi, nut, ansible, ping
[INFO] Using stdio transport
[INFO] Server initialized and ready
```

## Environment Configuration

The `.env` file is the single configuration point. Copy the template from the repository and fill in your service endpoints:

```bash
# Required — Docker socket path (inside container)
DOCKER_SOCKET=/var/run/docker.sock

# Optional — Ollama
OLLAMA_HOST=http://10.0.20.30:11434

# Optional — Pi-hole
PIHOLE_HOST=http://10.0.20.40
PIHOLE_API_KEY=your-pihole-api-key-here

# Optional — Unifi controller
UNIFI_HOST=https://10.0.20.50:8443
UNIFI_USER=homelab-monitor
UNIFI_PASS=readonly-api-user-password

# Optional — NUT UPS server
NUT_HOST=10.0.20.60
NUT_PORT=3493
NUT_UPS_NAME=ups

# Optional — Ansible inventory (mounted volume)
ANSIBLE_INVENTORY=/app/ansible_hosts.yml
```

Only `DOCKER_SOCKET` is required. Each service you leave out simply means Claude won't have that tool available. Start with Docker and Pi-hole, then add the rest.

Generate a fresh Pi-hole API key from the Pi-hole admin interface under **Settings > API > Show API Token**. For Unifi, create a dedicated read-only local user on the controller.

### Ansible Inventory (Optional but Useful)

If you use Ansible to manage your homelab, mount your inventory file. The MCP server reads it to provide Claude with host names, IP addresses, groups, and variables:

```yaml
# ansible_hosts.yml
all:
  hosts:
    srv1-proxmox:
      ansible_host: 10.0.20.30
    srv2-docker:
      ansible_host: 10.0.20.31
    mikrotik-gw:
      ansible_host: 10.0.20.1
  children:
    proxmox:
      hosts:
        srv1-proxmox:
    docker:
      hosts:
        srv2-docker:
    network:
      hosts:
        mikrotik-gw:
```

Claude can now answer "What hosts are in my Proxmox group?" or "What is the IP of my Docker host?"

## Claude Desktop Integration

Configure Claude Desktop to connect to the MCP server. Open Claude Desktop settings and edit the MCP configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

For the Docker deployment, Claude connects via Docker exec:

```json
{
  "mcpServers": {
    "homelab": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "homelab-mcp",
        "python",
        "/app/homelab_unified_mcp.py"
      ]
    }
  }
}
```

This tells Claude to start the MCP server inside the running container. The `-i` flag keeps STDIN open for the MCP protocol transport. No network ports, no firewall rules — the communication happens through the Docker CLI.

Restart Claude Desktop after adding the configuration. You should see a hammer icon appear in the chat input area, indicating MCP tools are available.

### Testing the Connection

Type "What tools do you have available?" in Claude Desktop. If the connection is working, Claude lists all registered tools:

```
I have access to these tools:
- docker_get_containers — List Docker containers
- docker_inspect — Inspect a specific container
- ollama_list_models — List loaded Ollama models
- pihole_get_stats — Get Pi-hole statistics
- nut_get_status — Get UPS status
- ping_ping_host — Ping a host
```

## Real-World Usage Examples

Once connected, Claude can run live queries against your infrastructure. Here are practical commands to try:

**Container management:**
```
Show me all Docker containers, their status, and resource usage.
```

Claude calls `docker_get_containers` and returns a formatted table with container names, images, status, ports, and uptime.

**DNS health check:**
```
What are the top DNS queries on Pi-hole right now? Any blocked domains spiking?
```

Claude calls `pihole_get_stats` and `pihole_get_query_types` to show query volume, blocked percentage, and top domains.

**AI model status:**
```
Check if Ollama is running and list which models are loaded.
```

Claude runs `ollama_ps` to show loaded models and their sizes.

**Network diagnostics:**
```
Ping my Proxmox host and my MikroTik gateway. Are they reachable?
```

Claude calls `ping_ping_host` sequentially for each target and reports latency.

**Infrastructure overview:**
```
Show me a summary of my Ansible inventory with groups and host IPs.
```

Claude queries the Ansible server and returns your infrastructure map.

**UPS monitoring:**
```
What is the battery level on my UPS? How much runtime is left?
```

Claude calls `nut_get_status` and `nut_get_battery` for real-time power data.

## Security Considerations

The Homelab MCP server has access to your Docker socket, which is effectively root access to the host. Treat this deployment with the same care as any privileged container:

- **Never expose the Docker socket to the network.** The mount is read-only (`:ro`), but even read-only socket access reveals container details. Keep it local.
- **Use a read-only API key for Pi-hole and Unifi.** Do not use admin credentials. Homelab MCP only queries data — it does not modify configurations.
- **Keep `.env` out of version control.** Add it to `.gitignore`. It contains API keys and credentials for your infrastructure.
- **Run on a management VLAN.** Place the Docker host in a dedicated management VLAN (VLAN 99 or similar) with strict ACLs limiting which services the MCP container can reach.
- **Audit the Docker socket.** The container runs `docker_get_containers` against your entire local Docker API. Consider running a [Docker Socket Proxy](https://gntech.dev/posts/docker-socket-proxy/) for granular access control instead of mounting `/var/run/docker.sock` directly.
- **Monitor access logs.** Claude Desktop conversations run locally, but if you use Claude Pro or Teams, your queries transit Anthropic's servers. Do not include secrets in prompts.

## Troubleshooting

**Claude Desktop shows no MCP tools available.** Verify the container is running: `docker ps | grep homelab-mcp`. Check logs: `docker compose logs`. Ensure the `claude_desktop_config.json` path is correct and the JSON is valid.

**"Permission denied" on Docker socket.** The user running Docker must have access. Run `sudo usermod -aG docker $USER` and log out/in. Or run Claude Desktop with the user that has Docker access.

**Container exits immediately.** Missing or incorrect `.env` variables. The container validates required configs on startup. Run `docker compose logs` — missing `DOCKER_SOCKET` is the most common cause.

**Pi-hole returns empty data.** Check that `PIHOLE_API_KEY` is correct and the Pi-hole API is reachable from the Docker container. The container runs on the internal network — if Pi-hole is on a different Docker network, they may not connect. Use `docker compose exec homelab-mcp curl http://pihole-ip/admin/api.php` to test.

**Claude says "I don't have access to that yet."** You asked for a tool from a server not configured. Only tools from services with valid `.env` entries are registered. Check your `.env` and restart the container.

## What This Changes About Homelab Management

Before MCP, homelab monitoring meant dashboards. Grafana panels, Prometheus alerts, Uptime Kuma status pages — all visual, all pull-based. You stare at charts and wait for something red.

MCP inverts the model. You ask a question in natural language and Claude goes to the source, queries the live data, and returns an answer. No dashboard navigation, no SQL queries, no `docker ps | grep` chains. It is querying your infrastructure the same way you query a database — but the database is your entire homelab.

The Homelab MCP project is actively maintained and the server count grows with each release. Start with Docker and Pi-hole, add Unifi and Ansible as you get comfortable, and before long you will find yourself reaching for Claude instead of SSH to check on your homelab.

**Full stack summary:**

- **Homelab MCP** — unified Docker container with 7 MCP servers
- **Claude Desktop** — natural language interface for infrastructure queries
- **Docker** — runtime for the MCP container with read-only socket access
- **Optional:** Pi-hole, Ollama, Unifi, NUT, Ansible — each adds more tools

Deploy it tonight. Tomorrow morning ask Claude "Did anything interesting happen in my homelab while I was asleep?" and watch it query Pi-hole, check Docker containers, ping your hosts, and report back. That is the future of homelab management — it asks you less and answers you more.
