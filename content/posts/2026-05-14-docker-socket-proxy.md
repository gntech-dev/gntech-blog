---
title: "Docker Socket Proxy — Restrict API Access and Verify the Policy"
description: "Configure documented socket-proxy endpoint controls, keep the proxy private, and test permitted and denied requests."
date: 2026-05-14T11:00:00-04:00
tags:
  - docker
  - security
  - homelab
  - containers
  - devops
keywords:
  - Docker socket proxy permissions
  - Tecnativa socket proxy
  - Docker API policy
summary: "Configure documented socket-proxy endpoint controls, keep the proxy private, and test permitted and denied requests."
lastmod: 2026-10-31
---

Access to a rootful Docker daemon can give control of the host. A socket proxy filters requests before they reach the daemon, but remains a privileged component. Its usefulness depends on the requests allowed and on which clients can reach it.

## Verification status

| Area | Evidence and limits |
|---|---|
| Source review | Tecnativa's documented environment variables reviewed on October 31, 2026. |
| Runtime | No proxy container or authorization test was executed in this audit. |
| Required test | Confirm an allowed request works and a denied request returns a rejection for the chosen image digest. |

## Configure a separate read-oriented endpoint

The example is for a discovery client such as Traefik, not a container-management tool. Select a reviewed `tecnativa/docker-socket-proxy` image tag or digest first. Use its documented variables such as `CONTAINERS` and `POST`; the earlier `ALLOW_CREATE`/`ALLOW_DELETE` examples did not describe Tecnativa's configuration interface.

```bash
read -r -p 'Reviewed socket-proxy image tag or digest: ' SOCKET_PROXY_IMAGE
export SOCKET_PROXY_IMAGE
cat > compose.yaml <<'EOF'
services:
  socket-proxy:
    image: ${SOCKET_PROXY_IMAGE:?Select a reviewed socket-proxy image}
    restart: unless-stopped
    environment:
      CONTAINERS: "1"
      EVENTS: "1"
      INFO: "1"
      NETWORKS: "1"
      VERSION: "1"
      PING: "1"
      POST: "0"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - discovery
networks:
  discovery:
    internal: true
EOF
docker compose config --quiet
docker compose up -d
```

There is deliberately no host port mapping. Attach only the intended client to this network and point its Docker endpoint at `tcp://socket-proxy:2375`. Give that client a separate network for its normal traffic where needed. A client also holding the raw Docker socket bypasses the proxy.

`CONTAINERS=1` enables a category of endpoints, not only a hand-picked container. Read access can disclose metadata and environment values. `POST=0` is a proxy policy control; it is **not** implemented by the socket's `:ro` mount. A read-only bind mount does not make Docker API calls read-only. The proxy can still communicate with the mounted socket, and compromise of the proxy itself remains significant.

See the [upstream permission list and security warnings](https://github.com/Tecnativa/docker-socket-proxy). Test the behavior of the exact release rather than assuming environment names carry across different proxy projects.

## Verify before attaching real clients

In a disposable lab, use a temporary HTTP client on the private network. Check a required GET endpoint, then a benign request to a disabled category such as `/volumes`; inspect the response code and proxy logs. Do not use create, delete, exec, or privileged-container operations as a production denial test. Confirm the policy independently of whether the application appears healthy.

Portainer and automatic updaters need write operations that this example intentionally denies. Do not enable broad write access on a shared proxy and then claim every connected client has separate permissions. Use separate proxy instances/networks and review the write API's effective host access. Network reachability controls who can call an endpoint; this proxy configuration does not provide per-user authentication or TLS for an exposed listener.

## Continue reading

- [Container security hardening](/posts/2026-05-15-docker-container-security-hardening/) — inspect capabilities, mounts, and the daemon trust boundary.
- [Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — keep deployment boundaries explicit.
