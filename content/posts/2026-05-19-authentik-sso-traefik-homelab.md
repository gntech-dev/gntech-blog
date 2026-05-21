---
title: "Authentik SSO With Traefik — Self-Hosted Identity Provider for Homelab"
description: "Deploy Authentik with Docker Compose and integrate it with Traefik as a forward-auth SSO provider. Centralize authentication, MFA, and access policies across all your homelab services."
date: 2026-05-19T11:00:00-04:00
tags:
  - docker
  - security
  - homelab
  - traefik
  - reverse-proxy
keywords:
  - Authentik Docker Compose deployment homelab
  - Authentik Traefik forward auth middleware
  - self-hosted SSO provider Docker
  - Authentik MFA TOTP WebAuthn setup
  - Authentik LDAP outpost integration
  - Authentik access policy groups
  - Authentik PostgreSQL Redis stack
summary: "Complete guide to deploying Authentik with Docker Compose and integrating it with Traefik as a forward-auth SSO provider for centralized authentication, MFA, and access policies across all homelab services."
canonical: "https://gntech.dev/posts/authentik-sso-traefik-homelab/"
---

As your homelab grows from a handful of containers to a dozen
services — Gitea, Grafana, Vaultwarden, Pi-hole admin, Portainer,
Proxmox — managing separate credentials for each becomes a
liability. Every service has its own login, its own password policy
(or lack thereof), and its own notion of multi-factor authentication.

Authentik solves this. It is an open-source Identity Provider (IdP)
that provides SSO, MFA, and centralized access policies. Deploy it
behind Traefik, and every service in your homelab can authenticate
through a single portal with TOTP or WebAuthn.

This guide covers deploying Authentik with Docker Compose,
configuring the Traefik forward-auth middleware, creating
applications and providers, setting up access policies, and
onboarding your homelab services one by one.

---

## Authentik vs the Alternatives

| Feature | Authentik | Authelia | Keycloak |
|---------|-----------|----------|----------|
| Deployment complexity | Moderate | Low | High |
| Built-in OIDC/OAuth2 | Yes | Yes (OIDC only) | Yes |
| LDAP outpost | Yes | No | Yes (external) |
| WebAuthn (passkeys) | Yes | Yes | Yes |
| Admin UI | Rich web UI | Minimal | Complex |
| User self-service portal | Yes | Limited | Yes |
| Traefik forward-auth | Native | Native | Requires extra config |
| Resource usage | ~1GB RAM | ~200MB RAM | ~2GB RAM |
| License | MIT | Apache 2.0 | Apache 2.0 |

**When to choose Authentik:** You have 8+ services, need a proper
admin UI for user management, want self-service enrollment with MFA,
and plan to integrate LDAP or SCIM. For 2-3 services with basic
auth-only needs, Authelia is lighter.

---

## Prerequisites

- Traefik already deployed (see the [Traefik reverse proxy guide](/posts/traefik-reverse-proxy-docker/))
- Docker and Docker Compose v2
- A domain pointed at your Traefik instance (e.g., `auth.example.com`)
- PostgreSQL knowledge (Authentik requires a Postgres database)
- At least 2GB RAM free on the Docker host

---

## Step 1 — Docker Compose Stack

Authentik consists of four components:

1. **Server** — The core IdP, handles login, MFA, user management
2. **Worker** — Background task processor (email, LDAP sync, event
   cleanup). Can scale horizontally.
3. **PostgreSQL** — Primary database
4. **Redis** — Cache, session storage, and task queue

```yaml
# /opt/authentik/docker-compose.yml
services:
  postgresql:
    image: docker.io/library/postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: authentik
      POSTGRES_USER: authentik
      POSTGRES_PASSWORD: ${PG_PASS:?Set PG_PASS in .env}
    volumes:
      - ./postgres:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -d authentik -U authentik"]
      interval: 30s
      timeout: 10s
      retries: 5

  redis:
    image: docker.io/library/redis:7-alpine
    restart: unless-stopped
    command: --save 60 1 --loglevel warning
    volumes:
      - ./redis:/data
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 10s
      retries: 5

  server:
    image: ghcr.io/goauthentik/server:latest
    restart: unless-stopped
    command: server
    environment:
      AUTHENTIK_REDIS__HOST: redis
      AUTHENTIK_POSTGRESQL__HOST: postgresql
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY:?Generate a 64-char key}
      AUTHENTIK_BOOTSTRAP_PASSWORD: ${AUTHENTIK_BOOTSTRAP_PASSWORD:?Set admin password}
      AUTHENTIK_BOOTSTRAP_EMAIL: ${AUTHENTIK_BOOTSTRAP_EMAIL:-admin@example.com}
    volumes:
      - ./media:/media
      - ./certs:/certs
      - ./custom-templates:/templates
    ports:
      - "127.0.0.1:9000:9000"  # Only localhost — Traefik proxies
      - "127.0.0.1:9443:9443"  # HTTPS port (not used behind Traefik)
    networks:
      - internal
      - traefik
    depends_on:
      postgresql:
        condition: service_healthy
      redis:
        condition: service_healthy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.authentik.rule=Host(`auth.example.com`)"
      - "traefik.http.routers.authentik.entrypoints=websecure"
      - "traefik.http.routers.authentik.tls=true"
      - "traefik.http.routers.authentik.tls.certresolver=letsencrypt"
      - "traefik.http.services.authentik.loadbalancer.server.port=9000"
      # Outpost forward-auth endpoint
      - "traefik.http.routers.authentik-outpost.rule=Host(`auth.example.com`) && PathPrefix(`/outpost.goauthentik.io/`)"
      - "traefik.http.routers.authentik-outpost.entrypoints=websecure"
      - "traefik.http.routers.authentik-outpost.tls=true"
      - "traefik.http.routers.authentik-outpost.priority=20"
      - "traefik.http.services.authentik-outpost.loadbalancer.server.port=9000"

  worker:
    image: ghcr.io/goauthentik/server:latest
    restart: unless-stopped
    command: worker
    environment:
      AUTHENTIK_REDIS__HOST: redis
      AUTHENTIK_POSTGRESQL__HOST: postgresql
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
    volumes:
      - ./media:/media
      - ./certs:/certs
      - ./custom-templates:/templates
    networks:
      - internal
    depends_on:
      postgresql:
        condition: service_healthy
      redis:
        condition: service_healthy

networks:
  internal:
    driver: bridge
    internal: true  # No external access
  traefik:
    external: true
```

### .env File

```bash
# /opt/authentik/.env
PG_PASS=$(openssl rand -base64 32)
AUTHENTIK_SECRET_KEY=$(openssl rand -base64 48)
AUTHENTIK_BOOTSTRAP_PASSWORD=changeme!
AUTHENTIK_BOOTSTRAP_EMAIL=admin@example.com
```

Generate real credentials:

```bash
cd /opt/authentik
echo "PG_PASS=$(openssl rand -base64 32)" >> .env
echo "AUTHENTIK_SECRET_KEY=$(openssl rand -base64 48)" >> .env
echo "AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -base64 16)" >> .env
echo "AUTHENTIK_BOOTSTRAP_EMAIL=admin@example.com" >> .env
```

Replace the email and domain before deploying.

### Deploy

```bash
cd /opt/authentik
docker compose pull
docker compose up -d
```

Watch the logs for the first-time setup:

```bash
docker compose logs -f server
```

After about 30 seconds, Authentik is reachable at
`https://auth.example.com`. Log in with the bootstrap credentials
from your `.env` file.

---

## Step 2 — Initial Configuration

After the first login, go through the initial setup wizard:

1. **Change the admin password** — Immediately set a strong password
2. **Configure system settings** — Under Admin Interface → System:
   - Set the **External host** to `https://auth.example.com`
   - Configure email if you need password reset flows
   - Set the default token length (leave at 60)
3. **Create a default flow** — Authentik uses "flows" for
   authentication, enrollment, and password reset. The default
   "default-authentication-flow" works for most setups.

### First Login Flow

Navigate to `https://auth.example.com` — you see the Authentik login
portal. Enter your admin credentials, and you're in the admin
interface.

The admin interface has two distinct areas:
- **Admin Interface** (`/if/admin/`) — Full configuration, users,
  providers, flows, outposts
- **User Interface** (`/if/user/`) — Self-service portal for users
  to manage their own profile, MFA devices, and applications

---

## Step 3 — Configure the Traefik Forward-Auth Middleware

Authentik uses an "outpost" — a lightweight component that proxies
authentication requests. When deployed via Docker alongside the
server, the outpost runs embedded within the server container. The
forward-auth endpoint lives at:

```
http://authentik:9000/outpost.goauthentik.io/auth/traefik
```

### Step 3a — Create a Proxy Provider in Authentik

1. Go to **Admin Interface** → **Applications** → **Providers**
2. Click **Create**, select **Proxy Provider**
3. Configure:
   - **Name:** `Traefik Forward Auth`
   - **Authentication flow:** `default-authentication-flow`
   - **Authorization flow:** `default-provider-authorization-implicit-consent`
   - **Mode:** `Forward Auth (Single Application)`
4. Save. Note the **Client ID** — you'll need it for the provider.

### Step 3b — Create an Application

1. Go to **Applications** → **Applications**
2. Click **Create**:
   - **Name:** `Traefik Auth`
   - **Slug:** `traefik-auth`
   - **Provider:** Select the provider you just created
3. Save.

### Step 3c — Define the Traefik Middleware

The forward-auth middleware lives in your Traefik dynamic
configuration. Add it to your `middlewares.yml`:

```yaml
# /opt/traefik/dynamic/middlewares.yml
http:
  middlewares:
    # Existing middlewares...

    authentik:
      forwardAuth:
        address: http://authentik:9000/outpost.goauthentik.io/auth/traefik
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-entitlements
          - X-authentik-email
          - X-authentik-name
          - X-authentik-uid
          - X-authentik-jwt
          - X-authentik-meta-outpost
          - X-authentik-meta-provider
          - X-authentik-meta-app
          - X-authentik-meta-version
```

**Important:** The `address` uses `http://authentik:9000` — this
assumes Authentik is on the same Docker network as Traefik. If
Authentik is on a separate network, use the container's IP:

```bash
docker inspect authentik-server-1 | jq -r '.[0].NetworkSettings.Networks.traefik.IPAddress'
10.0.20.30  # Example — use the actual IP
```

Then set `address: http://10.0.20.30:9000/outpost.goauthentik.io/auth/traefik`.

### Step 3d — Add the Outpost Router Bypass

The forward-auth endpoint must NOT go through authentication itself
(that would create a loop). The outpost router we defined in the
docker-compose handles this — it routes
`/outpost.goauthentik.io/*` directly to Authentik without the
middleware:

```yaml
# Already in your compos as labels on the server container:
- "traefik.http.routers.authentik-outpost.rule=Host(`auth.example.com`) && PathPrefix(`/outpost.goauthentik.io/`)"
- "traefik.http.routers.authentik-outpost.priority=20"
```

This router has `priority: 20` (higher than the default 0), so
requests to `auth.example.com/outpost.goauthentik.io/*` match this
route first and bypass the middleware.

---

## Step 4 — Protect Services with Authentik

Now the fun part: add Authentik authentication to every service.

### Grafana Example

```yaml
# /opt/grafana/docker-compose.yml
services:
  grafana:
    image: grafana/grafana:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`grafana.example.com`)"
      - "traefik.http.routers.grafana.entrypoints=websecure"
      - "traefik.http.routers.grafana.tls=true"
      - "traefik.http.routers.grafana.middlewares=authentik@file"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"
```

Once added, visiting `https://grafana.example.com` redirects to
Authentik's login portal. After successful login, you land on
Grafana. Repeat for every service.

### Services That Need Exceptions

Some services have endpoints that must not go through Authentik:

**Portainer** — WebSocket connections for the terminal:
```yaml
labels:
  - "traefik.http.routers.portainer.rule=Host(`portainer.example.com`)"
  - "traefik.http.routers.portainer.middlewares=authentik@file"
  - "traefik.http.routers.portainer-ws.rule=Host(`portainer.example.com`) && PathPrefix(`/api/websocket/`)"
  - "traefik.http.routers.portainer-ws.middlewares="
  - "traefik.http.routers.portainer-ws.priority=20"
```

**Grafana public dashboards:**
```yaml
labels:
  - "traefik.http.routers.grafana-public.rule=Host(`grafana.example.com`) && PathPrefix(`/public`)"
  - "traefik.http.routers.grafana-public.middlewares="
  - "traefik.http.routers.grafana-public.priority=20"
  - "traefik.http.routers.grafana.rule=Host(`grafana.example.com`)"
  - "traefik.http.routers.grafana.middlewares=authentik@file"
```

---

## Step 5 — Access Policies and Groups

Authentik's policy engine is how you control who gets access to what.

### Create Groups

1. Go to **Admin Interface** → **Directory** → **Groups**
2. Create:
   - **admins** — Full access to admin services
   - **users** — Standard user access
   - **readonly** — View-only access to monitoring

### Assign Users to Groups

1. Go to **Directory** → **Users**
2. Click a user → **Groups** tab → Join groups

### Create Bindings Between Groups and Applications

Applications use "bindings" to control access. Each application can
have policies that check group membership, user attributes, or time
of day.

1. Go to **Applications** → **Applications** → select your app
2. Click the **Policies / Bindings** tab
3. Click **Create** → select **Group Binding**
4. Choose the group (e.g., `admins`) and set access mode to
   `grant_allow`

The ordering matters — first-match wins. Place deny rules before
grant rules.

### Expression Policies

For advanced controls, use expression policies:

```python
# Example: Allow access only during business hours
from datetime import datetime
from django.utils import timezone

now = timezone.localtime(timezone.now())
return 9 <= now.hour < 18
```

```python
# Example: Require MFA for external access
return request.user.ak_is_superuser or request.context.get("is_mfa", False)
```

Add these via **Admin Interface** → **Policies** → **Expression
Policy**, then bind them to your applications.

---

## Step 6 — Enabling MFA

Authentik supports TOTP (Google Authenticator, Authy), WebAuthn
(passkeys, YubiKey), and Duo.

### Default MFA Enrollment

1. Go to **Flows** → **Default Authentication Flow**
2. Add a **Stage** of type `authenticator_validate` after the
   password stage:
   - **Device classes:** `totp`, `webauthn`
   - **Not configured action:** `configure`
   - **Last validation threshold:** `days=30`
3. Users are prompted to set up MFA on their next login

### Require MFA for Specific Services

Create a binding that checks for MFA:

1. **Applications** → select your app → **Policies / Bindings**
2. **Create** → **Expression Policy**:
   ```python
   # Must have at least one MFA device configured
   devices = request.user.authentik_events_user.get(
       pk=request.user.pk
   ).akstage_set.filter(
       stage_type="authenticator"
   )
   return devices.exists()
   ```
3. Set mode to `grant_allow` and order it before other bindings

### MFA Without User Intervention

Users enrolled once via the user portal (`/if/user/` →
**Authenticator Devices**) don't need to re-enroll. The
`last_validation_threshold` in the flow stage determines how often
they need to re-verify their MFA token.

---

## Step 7 — User Self-Service Portal

Authentik's user interface at `/if/user/` lets users:

- Change their password
- Enroll MFA devices (TOTP, WebAuthn)
- View their active sessions
- Access granted applications
- Update their profile

Forward the user portal through Traefik (same router as the admin
interface, since they live under different paths).

### Customizing the Login Page

Authentik supports custom branding:

1. Go to **Admin Interface** → **System** → **Branding**
2. Set:
   - **Title:** Your homelab name
   - **Logo:** URL to your logo (256x256 recommended)
   - **Favicon:** URL to favicon
   - **Footer links:** GitHub, status page, etc.

For deeper customization, place custom HTML/CSS/JS in the
`custom-templates` directory mounted in the Docker compose:

```bash
mkdir -p /opt/authentik/custom-templates
```

Templates use the Django template language. Override files in:

```
custom-templates/
├── login/
│   └── password.html     # Password field template
├── flow/
│   └── loader.html       # Flow loader screen
└── themes/
    └── ...               # CSS overrides
```

---

## Step 8 — LDAP Outpost (Optional)

Authentik can act as an LDAP server for services that only support
LDAP authentication (Proxmox, NAS devices, network appliances).

### Enable the LDAP Outpost

1. Go to **Admin Interface** → **Applications** → **Outposts**
2. Click **Create**:
   - **Name:** `LDAP Outpost`
   - **Type:** `LDAP`
   - **Integrate with embedded outpost:** Yes
3. Bind users and groups to the outpost

### Add LDAP Port to the Server Container

Edit your docker-compose to expose LDAP ports:

```yaml
services:
  server:
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:3389:3389"  # LDAP (StartTLS)
      - "127.0.0.1:6363:6363"  # LDAPS
```

### Configure Service LDAP Binding

```text
Server: auth.example.com
Port: 3389 (StartTLS) or 6363 (LDAPS)
Base DN: DC=ldap,DC=goauthentik,DC=io
Bind DN: cn=admin,DC=ldap,DC=goauthentik,DC=io
Password: [outpost token from Authentik]
```

The bind credentials come from the **Outpost** settings page in the
admin interface.

---

## Step 9 — Backup Strategy

Authentik stores everything in PostgreSQL. Back up the database:

```bash
#!/bin/bash
# /opt/authentik/backup.sh
BACKUP_DIR="/backups/authentik"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="authentik"
DB_USER="authentik"
DB_PASS=$(grep PG_PASS /opt/authentik/.env | cut -d= -f2)

mkdir -p "$BACKUP_DIR"

docker compose exec -T postgresql pg_dump \
  -U "$DB_USER" "$DB_NAME" \
  | gzip > "$BACKUP_DIR/authentik_$TIMESTAMP.sql.gz"

# Keep 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -type f -mtime +30 -delete

echo "Backup complete: $BACKUP_DIR/authentik_$TIMESTAMP.sql.gz"
```

Also back up the `.env` file and the mounted `media` and `certs`
directories.

### Restore Procedure

```bash
# Stop the server and worker
docker compose stop server worker

# Drop and recreate (in production, create a new DB and recreate)
docker compose exec -T postgresql psql -U authentik -d postgres \
  -c "DROP DATABASE IF EXISTS authentik;"
docker compose exec -T postgresql psql -U authentik -d postgres \
  -c "CREATE DATABASE authentik;"

# Restore
gunzip -c authentik_20260519_120000.sql.gz | \
  docker compose exec -T postgresql psql -U authentik -d authentik

# Restart
docker compose up -d
```

---

## Troubleshooting

### "Too many redirects" when visiting a protected service

The forward-auth endpoint is looping. Check:
- The outpost router has `PathPrefix(/outpost.goauthentik.io/)`
  with `priority: 20` (higher than the auth router's default 0)
- The `address` in the forward-auth middleware points to the
  correct container hostname/port
- Authentik's **External host** setting matches the domain

### "401 Unauthorized" after login

The Token is invalid or expired. In Authentik admin:
1. **Applications** → **Providers** → edit your proxy provider
2. Re-generate the token
3. Update the outpost if needed

### WebSocket connections failing

Portainer terminal, Grafana live updates, and similar features use
WebSockets. Authentik's forward-auth does not support WebSocket
upgrade natively. Create a bypass router:

```yaml
- "traefik.http.routers.portainer-ws.rule=Host(`portainer.example.com`) && Headers(`Upgrade`,`websocket`)"
- "traefik.http.routers.portainer-ws.middlewares="
- "traefik.http.routers.portainer-ws.priority=30"
```

### LDAP connection refused

If you enabled the LDAP outpost and can't connect:
1. Verify the LDAP ports are exposed in docker-compose
2. Check `docker compose logs server` for LDAP errors
3. The outpost must have bindings to users/groups

### Lost admin password

Reset it via the CLI:

```bash
docker compose exec server \
  /bin/bash -c "echo 'from authentik.core.models import User; u = User.objects.get(username=\"akadmin\"); u.set_password(\"newpassword\"); u.save()' | python3 manage.py shell"
```

The admin username is `akadmin` by default.

---

## Putting It All Together — Reference Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Internet / Cloudflare Tunnel                             │
│       ↓                                                  │
│  Traefik → Authenticates via forward-auth middleware     │
│       ↓                                                  │
│  Authentik Outpost endpoint at auth.example.com          │
│       ↓                                                  │
│  Authentik validates → redirects to service              │
│       ↓                                                  │
│  Service receives user info via headers                  │
│       ↓                                                  │
│  User lands on protected service, already authenticated  │
└──────────────────────────────────────────────────────────┘
```

**Request flow breakdown:**

1. User visits `https://grafana.example.com`
2. Traefik's `authentik` forward-auth middleware intercepts the
   request
3. Traefik sends the request to
   `http://authentik:9000/outpost.goauthentik.io/auth/traefik`
4. Authentik sees no session cookie → redirects to
   `auth.example.com` login page
5. User logs in with credentials + MFA
6. Authentik sets the `authentik_session` cookie and redirects back
   to Traefik
7. Traefik retries the forward-auth check — this time Authentik
   returns 200 with user info headers
8. Traefik forwards the original request with `X-authentik-*`
   headers to Grafana
9. Grafana receives the authenticated user info in request headers

---

## Summary

Authentik transforms a collection of independently-authenticated
services into a unified, secure ecosystem. The key takeaways:

- **Deploy** with Docker Compose using PostgreSQL and Redis —
  allocate at least 2GB RAM and expose only port 9000 behind Traefik
- **Configure** the Traefik forward-auth middleware with the
  embedded outpost endpoint — one middleware file protects every
  service
- **Protect** services by adding `authentik@file` to their Traefik
  router middlewares — bypass WebSocket routes with a higher-priority
  router rule
- **Enforce MFA** via flow stages — TOTP and WebAuthn with a
  `last_validation_threshold` of 30 days
- **Control access** with group bindings — create admins, users,
  and readonly groups, then bind them to applications
- **Extend** with LDAP outpost for services that don't support
  OIDC/OAuth2 — Proxmox, NAS appliances, and network gear

The investment in setting up Authentik pays off immediately. Instead
of managing a dozen password databases and hoping users pick strong
ones, you get a single identity source with MFA that every service
inherits. For a homelab running 10+ web services, it's not nice to
have — it's a security necessity.
