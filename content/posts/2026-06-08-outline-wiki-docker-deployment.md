---
title: "Outline Wiki Deployment Guide — Self-Hosted Knowledge Base with Docker"
description: "Deploy Outline wiki with Docker Compose for a self-hosted knowledge base. OIDC auth via Authentik, PostgreSQL, Redis, Traefik reverse proxy, and S3 storage setup."
date: 2026-06-08T07:00:00-04:00
tags:
  - docker
  - selfhosting
  - documentation
  - homelab
keywords:
  - Outline Wiki Docker deployment homelab knowledge base
  - Outline Docker Compose OIDC authentication Authentik
  - Self-hosted collaborative documentation Outline PostgreSQL
  - Outline wiki S3 storage MinIO homelab setup
  - Traefik reverse proxy Outline Docker deployment
  - Outline Redis PostgreSQL Docker Compose configuration
  - Outline wiki OIDC SAML SSO homelab documentation
summary: "Deploy Outline wiki on your homelab with Docker Compose. Complete guide covering PostgreSQL, Redis, OIDC auth with Authentik, S3/MinIO storage, and Traefik reverse proxy."
canonical: "https://blog.gntech.me/posts/outline-wiki-docker-deployment/"
---

## What Is Outline and Why Self-Host It

Outline is an open-source knowledge base and wiki platform designed for team collaboration. Its clean, Notion-like interface supports real-time editing, Markdown formatting, nested collections, and a rich search experience powered by PostgreSQL full-text search.

Self-hosting Outline gives you full control over your documentation data — no per-user SaaS pricing, no data leaving your infrastructure, and no feature-gating behind expensive enterprise tiers. For homelab operators, Outline solves the recurring problem of keeping infrastructure docs, runbooks, and network diagrams in one searchable place instead of scattered across text files and chat messages.

Compared to other self-hosted documentation tools:

- **BookStack** — structured, book-and-shelf hierarchy, simpler auth (LDAP/SAML)
- **Docusaurus** — static site generator, great for public docs, requires builds
- **Outline** — real-time collaborative editor, Markdown-native, OIDC/SAML/SSO, Slack integration

Outline works best as an internal team wiki where multiple people contribute and edit collaboratively.

## Prerequisites and Architecture

Before deploying, you need:

- Docker Engine 24+ and Docker Compose v2 installed
- A domain name pointing to your homelab (e.g., `outline.yourlab.com`)
- An OIDC-compatible identity provider — this guide uses Authentik, but Google, Azure AD, Keycloak, or any OpenID Connect provider works
- Optional: S3-compatible object storage (MinIO) — Outline defaults to local disk for file uploads

Minimum hardware: 1 GB RAM, 2 vCPUs, 10 GB disk. At idle, the stack consumes about 500 MB of RAM.

The architecture is straightforward:

```
User → Traefik (SSL termination) → Outline (container)
                                      ├── PostgreSQL 16 (documents, users, metadata)
                                      ├── Redis 7 (session cache, rate limiting)
                                      └── MinIO (optional — file attachments)
```

## Environment and Directory Setup

Create the project directory and set up the environment file:

```bash
mkdir -p /opt/outline/data
cd /opt/outline
```

Generate secret keys for Outline:

```bash
# Generate a 64-character random secret key
openssl rand -hex 32

# Generate a separate utils secret
openssl rand -hex 32
```

Create `.env` in `/opt/outline`:

```bash
cat > .env << 'EOF'
# General
NODE_ENV=production
APP_NAME=GnTech Wiki
APP_URL=https://outline.yourlab.com
PORT=3000
FORCE_HTTPS=true

# Secrets (replace with your generated values)
SECRET_KEY=your-64-hex-char-secret
UTILS_SECRET=your-64-hex-char-utils-secret

# PostgreSQL
DATABASE_URL=postgres://outline_user:outline_password@postgres:5432/outline
PGSSLMODE=disable

# Redis
REDIS_URL=redis://redis:6379

# OIDC Authentication (Authentik)
OIDC_CLIENT_ID=your-authentik-client-id
OIDC_CLIENT_SECRET=your-authentik-client-secret
OIDC_AUTH_URI=https://auth.yourlab.com/application/o/authorize/
OIDC_TOKEN_URI=https://auth.yourlab.com/application/o/token/
OIDC_USERINFO_URI=https://auth.yourlab.com/application/o/userinfo/
OIDC_LOGOUT_URI=https://auth.yourlab.com/application/o/end-session/
OIDC_SCOPES=openid profile email

# File Storage (local disk — switch to S3 below if using MinIO)
FILE_STORAGE=local
MAXIMUM_IMPORT_SIZE=52428800

# Default access
DEFAULT_ACCESS=members
EOF
```

## Docker Compose Configuration

Create `docker-compose.yml`:

```yaml
services:
  outline:
    image: outlinewiki/outline:latest
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - ./data:/var/lib/outline/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/_health"]
      interval: 30s
      timeout: 10s
      retries: 3
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    networks:
      - outline-net
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: outline_user
      POSTGRES_PASSWORD: outline_password
      POSTGRES_DB: outline
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U outline_user -d outline"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - outline-net
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.5"

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks:
      - outline-net
    deploy:
      resources:
        limits:
          memory: 128M
          cpus: "0.25"

networks:
  outline-net:
    external: true
    name: traefik-net

volumes:
  postgres-data:
  redis-data:
```

Expose Outline only on localhost port 3000 — Traefik handles external access. The `traefik-net` network must exist before deploying; create it if needed:

```bash
docker network create traefik-net
```

## OIDC Authentication with Authentik

Outline does not include a built-in user database — it requires an external OIDC, SAML, or Slack/Google OAuth provider. Authentik works well for this in a homelab.

### Creating the OIDC Provider in Authentik

1. Navigate to **Applications → Providers → Create Provider**
2. Select **OAuth2/OpenID Provider** and configure:
   - Name: `Outline`
   - Client Type: `Confidential`
   - Redirect URIs: `https://outline.yourlab.com/auth/oidc.callback`
   - Signing Key: Select a key or create one
3. Navigate to **Applications → Applications → Create Application**
   - Name: `Outline`
   - Slug: `outline`
   - Provider: select the Outline provider just created
4. From the provider details page, copy the **Client ID** and **Client Secret**

Place these values in the `.env` file as `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. Update the URIs to match your Authentik domain.

### Understanding the OIDC Flow

1. User visits `outline.yourlab.com`
2. Outline redirects to Authentik's authorize endpoint
3. User authenticates (password, WebAuthn, TOTP — Authentik-enforced MFA works transparently)
4. Authentik redirects back to Outline with an authorization code
5. Outline exchanges the code for tokens and creates/logs in the user

No user provisioning is needed — Outline auto-creates accounts on first login via OIDC. The first user to log in becomes the admin by default when `DEFAULT_ACCESS=members`.

## S3 Storage with MinIO (Optional)

For production use, switch from local disk to S3-compatible object storage. Deploy MinIO alongside Outline:

```yaml
services:
  minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadminpassword
    volumes:
      - minio-data:/data
    ports:
      - "127.0.0.1:9000:9000"
    networks:
      - outline-net

volumes:
  minio-data:
```

Access the MinIO console at port 9001, create a bucket named `outline-attachments`, and create an access key. Then update `FILE_STORAGE` in `.env`:

```bash
FILE_STORAGE=s3
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-minio-access-key
AWS_SECRET_ACCESS_KEY=your-minio-secret-key
AWS_S3_UPLOAD_BUCKET_URL=http://minio:9000
AWS_S3_UPLOAD_BUCKET_NAME=outline-attachments
AWS_S3_ACCELERATE_URL=
AWS_S3_FORCE_PATH_STYLE=true
```

`AWS_S3_FORCE_PATH_STYLE=true` is required for MinIO. If using AWS S3, set it to `false` and use a proper region.

## Traefik Reverse Proxy Configuration

If you already run Traefik, add a new router and service for Outline. With dynamic config file (or Docker labels):

```yaml
# docker-compose.yml labels (add to outline service)
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.outline.rule=Host(`outline.yourlab.com`)"
  - "traefik.http.routers.outline.entrypoints=websecure"
  - "traefik.http.routers.outline.tls=true"
  - "traefik.http.routers.outline.tls.certresolver=letsencrypt"
  - "traefik.http.services.outline.loadbalancer.server.port=3000"
  - "traefik.http.middlewares.outline-ratelimit.ratelimit.average=100"
  - "traefik.http.middlewares.outline-ratelimit.ratelimit.burst=50"
  - "traefik.http.routers.outline.middlewares=outline-ratelimit"
```

Or via a Traefik dynamic configuration file:

```yaml
# /opt/traefik/config/outline.yml
http:
  routers:
    outline:
      rule: "Host(`outline.yourlab.com`)"
      entryPoints: ["websecure"]
      tls:
        certResolver: letsencrypt
      service: outline
      middlewares:
        - outline-ratelimit

  services:
    outline:
      loadBalancer:
        servers:
          - url: "http://outline:3000"

  middlewares:
    outline-ratelimit:
      rateLimit:
        average: 100
        burst: 50
```

If Outline is on a different host than Traefik, replace the `url` in the service definition with the actual Docker host IP.

## First Launch and Validation

Start the stack:

```bash
docker compose up -d
docker compose logs -f outline
```

Wait for the health check to pass:

```bash
docker compose ps
```

You should see all three services in `Up (healthy)` status.

### Migration and Initial Setup

Outline runs database migrations automatically on startup. Watch the logs for:

```
Migrations up to date
Listening on port 3000
```

Visit `https://outline.yourlab.com`. You will be redirected to Authentik for login. On first successful login, Outline creates your account. The first user gets admin privileges by default when `DEFAULT_ACCESS=members`.

### Verification Checklist

- [ ] Login via OIDC redirects back to Outline without errors
- [ ] Collections page loads with `Getting Started` collection
- [ ] Create a document with Markdown formatting
- [ ] Upload an image attachment
- [ ] Search returns results from document titles and content

### Troubleshooting

| Issue | Likely Cause | Fix |
|-------|-------------|-----|
| OIDC redirect loop | Redirect URI mismatch | Verify Authentik redirect URI exactly matches `https://outline.yourlab.com/auth/oidc.callback` |
| File uploads fail (local) | Volume permissions | `chown -R 1000:1000 /opt/outline/data` |
| 502 Bad Gateway (Traefik) | Network mismatch | Ensure Outline is on `traefik-net` network |
| Database connection refused | PostgreSQL not ready | Check `depends_on` healthcheck: `docker compose logs postgres` |
| Blank page after login | CORS or URL mismatch | Verify `APP_URL` in .env matches the access URL exactly |

## Backup and Maintenance

Automate daily PostgreSQL backups with a systemd timer:

```bash
cat > /opt/outline/backup.sh << 'SCRIPT'
#!/bin/bash
BACKUP_DIR=/opt/outline/backups
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p $BACKUP_DIR
docker exec $(docker compose ps -q postgres) pg_dump -U outline_user outline \
  | gzip > $BACKUP_DIR/outline-$TIMESTAMP.sql.gz
find $BACKUP_DIR -name "outline-*.sql.gz" -mtime +30 -delete
SCRIPT
chmod +x /opt/outline/backup.sh
```

Create the systemd service and timer:

```bash
cat > /etc/systemd/system/outline-backup.service << 'EOF'
[Unit]
Description=Outline database backup
After=docker.service

[Service]
Type=oneshot
ExecStart=/opt/outline/backup.sh
WorkingDirectory=/opt/outline
User=root
EOF

cat > /etc/systemd/system/outline-backup.timer << 'EOF'
[Unit]
Description=Daily Outline database backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now outline-backup.timer
```

For Docker image updates, add Outline to your Watchtower setup:

```bash
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --interval 86400 \
  --cleanup \
  outline
```

## Conclusion

Outline fills the gap for homelab documentation that is collaborative, real-time, and always searchable. With OIDC authentication via Authentik, you get SSO with MFA enforcement across all your self-hosted services in one identity layer. The Docker Compose setup runs comfortably alongside other services on a single homelab host.

Start populating your Outline wiki with infrastructure documentation, network diagrams, service runbooks, and configuration references. Over time it becomes the single source of truth for your homelab operations.

For full configuration options, see the [Outline self-hosting documentation](https://www.getoutline.com/self-hosting).
