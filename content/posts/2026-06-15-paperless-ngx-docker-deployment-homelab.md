---
title: "Paperless-ngx Docker Deployment — AI-Powered Document Management"
description: "Deploy Paperless-ngx with Docker Compose for self-hosted AI-powered document management. OCR, ML auto-classification, consumption templates, and automated ingestion pipeline."
date: 2026-06-15T17:00:00-04:00
tags:
  - docker
  - selfhosted
  - homelab
  - storage
  - devops
keywords:
  - Paperless-ngx Docker Compose homelab deployment
  - Self-hosted document management OCR AI tagging
  - Paperless-ngx consumption templates automation
  - Docker Paperless-ngx PostgreSQL persistent storage
  - Paperless-ngx machine learning document classification
  - Self-hosted paperless document scanning workflow
  - Paperless-ngx reverse proxy Traefik Nginx setup
summary: "Deploy Paperless-ngx with Docker Compose in your homelab. Covers OCR processing, ML-based document classification, consumption templates, automated ingestion, and Traefik reverse proxy integration."
canonical: "https://blog.gntech.me/posts/paperless-ngx-docker-deployment-homelab/"
---

Your homelab generates paperwork — invoices, ISP contracts, device manuals, tax documents, warranty cards. Paperless-ngx turns that pile of PDFs and scans into a fully searchable, auto-tagged digital archive with OCR, machine learning classification, and multi-user access. Deploying it with Docker Compose keeps the stack isolated, reproducible, and easy to upgrade.

This guide walks through a production-ready Paperless-ngx deployment with PostgreSQL, Redis, Gotenberg, and Apache Tika, plus consumption templates, automated email ingestion, and Traefik reverse proxy configuration.

## Prerequisites

- **Docker** and **Docker Compose v2** installed on your host
- **PostgreSQL 16** — can run as a container within the same Compose file (this guide uses external for production reliability)
- **A reverse proxy** — Traefik, nginx, or Caddy for HTTPS access
- **Storage directories** — separate volumes for consumption (document import), media (archive), and database persistence

## Docker Compose Configuration for Paperless-ngx

The full Paperless-ngx stack consists of five services: the main application, PostgreSQL, Redis for the task queue, Gotenberg for document conversion, and Apache Tika for metadata extraction.

```yaml
# compose.yaml
services:
  paperless:
    image: ghcr.io/paperless-ngx/paperless-ngx:latest
    container_name: paperless
    restart: unless-stopped
    depends_on:
      - db
      - redis
      - gotenberg
      - tika
    volumes:
      - ./data:/usr/src/paperless/data
      - ./media:/usr/src/paperless/media
      - ./export:/usr/src/paperless/export
      - ./consume:/usr/src/paperless/consume
    environment:
      PAPERLESS_URL: https://docs.example.com
      PAPERLESS_SECRET_KEY: "${PAPERLESS_SECRET_KEY}"
      PAPERLESS_TIME_ZONE: America/Santo_Domingo
      PAPERLESS_OCR_LANGUAGE: eng+spa
      PAPERLESS_OCR_MODE: redo
      PAPERLESS_ENABLE_MATCHING_ALGORITHMS: auto
      PAPERLESS_REDIS: redis://redis:6379
      PAPERLESS_DBHOST: db
      PAPERLESS_DBUSER: paperless
      PAPERLESS_DBPASS: "${PAPERLESS_DB_PASSWORD}"
      PAPERLESS_DBNAME: paperless
      PAPERLESS_TIKA_ENABLED: 1
      PAPERLESS_TIKA_GOTENBERG_ENDPOINT: http://gotenberg:3000
      PAPERLESS_TIKA_ENDPOINT: http://tika:9998

  db:
    image: postgres:16-alpine
    container_name: paperless-db
    restart: unless-stopped
    volumes:
      - ./pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: paperless
      POSTGRES_USER: paperless
      POSTGRES_PASSWORD: "${PAPERLESS_DB_PASSWORD}"

  redis:
    image: redis:7-alpine
    container_name: paperless-redis
    restart: unless-stopped

  gotenberg:
    image: gotenberg/gotenberg:8
    container_name: paperless-gotenberg
    restart: unless-stopped
    command:
      - "gotenberg"
      - "--chromium-disable-javascript=true"
      - "--chromium-allow-list=file:///tmp/.*"

  tika:
    image: ghcr.io/paperless-ngx/tika:latest
    container_name: paperless-tika
    restart: unless-stopped
```

Create a `.env` file in the same directory to store secrets:

```
PAPERLESS_SECRET_KEY=<run: openssl rand -base64 48>
PAPERLESS_DB_PASSWORD=<run: openssl rand -base64 32>
```

## First-Run Setup

Create the required directory structure, generate the secret key, and start the stack:

```bash
mkdir -p data media consume export pgdata

# Generate secret if needed
openssl rand -base64 48

# Start all services
docker compose up -d

# Wait for database migration, then create admin user
docker compose exec paperless paperless-manage createsuperuser
```

The first startup runs database migrations automatically. Watch the logs with `docker compose logs -f paperless` to confirm completion before creating the superuser.

## OCR and Machine Learning Configuration

Paperless-ngx runs OCR on every ingested document using Tesseract. The configuration above uses English and Spanish language packs (`eng+spa`) — add more languages by separating with `+` (e.g., `deu+eng+fra+spa`).

The `PAPERLESS_OCR_MODE: redo` setting forces re-OCR on every document, which is useful when documents come from various sources with inconsistent quality. For production use where you control the scanner quality, switch to `skip` to avoid unnecessary processing.

Machine learning classification is enabled with:

```
PAPERLESS_ENABLE_MATCHING_ALGORITHMS: auto
```

This activates Paperless-ngx's built-in ML model that learns from manual document corrections. Over time, it automatically assigns correspondents, document types, and tags based on your patterns. Heuristics like exact-match and fuzzy-match supplement the ML algorithm for reliable results from day one.

## Consumption Templates for Automatic Processing

Consumption templates let you define rules that automatically classify incoming documents based on content, filename, or correspondent. Create a YAML file in the `consume` directory:

```yaml
# consume/templates.yaml
- match: invoice|invoice|factura|receipt
  match_algorithm: content
  document_type: Invoice
  tags:
    - Finance
  storage_path: Finance/Invoices/{created_year}

- match: contract|agreement|terms
  match_algorithm: content
  document_type: Contract
  storage_path: Documents/Contracts

- match: manual|guide|datasheet
  match_algorithm: filename
  document_type: Manual
  tags:
    - Hardware
  storage_path: Reference/Manuals
```

Document types, correspondents, and tags must exist in Paperless-ngx before the template can reference them. Create them through the web UI first, then templates apply automatically on document ingestion.

## Automated Ingestion Pipeline

Paperless-ngx watches the `consume/` directory for new files. Drop a PDF in there and it gets OCR'd, classified, and archived within seconds. Set up automated ingestion sources:

**Email ingestion** — Paperless can pull documents from email accounts:

```bash
# Add to paperless environment
PAPERLESS_CONSUME_MAIL_ENABLED: true
PAPERLESS_CONSUME_MAIL_HOST: imap.example.com
PAPERLESS_CONSUME_MAIL_USER: scans@example.com
PAPERLESS_CONSUME_MAIL_PASS: "${MAIL_PASSWORD}"
PAPERLESS_CONSUME_MAIL_INBOX: INBOX
```

**Scanner integration** — Point your SANE network scanner to write to the `consume/` directory via an SMB or NFS share mounted at `/consume`. Many MFPs support scan-to-folder or scan-to-email. Configure scan-to-email for the most reliable pipeline.

**Mobile app upload** — The Paperless-ngx mobile app (Android/iOS) supports direct document upload through the API. Enable this in Settings → Mobile → App Authentication. You can also configure the share-to-Paperless shortcut on iOS.

## Reverse Proxy Integration with Traefik

Expose Paperless-ngx through your reverse proxy for HTTPS access. Traefik labels for the Paperless service:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.paperless.rule=Host(`docs.example.com`)"
  - "traefik.http.routers.paperless.entrypoints=websecure"
  - "traefik.http.routers.paperless.tls.certresolver=letsencrypt"
  - "traefik.http.services.paperless.loadbalancer.server.port=8000"
```

For nginx proxy:

```nginx
server {
    listen 443 ssl;
    server_name docs.example.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://10.0.20.50:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Set `PAPERLESS_URL` to match your public or internal URL (e.g., `https://docs.example.com`). Without this, Paperless generates incorrect links in emails and API responses.

## Backup Strategy

Two components must be backed up: the **media directory** containing archived documents and the **PostgreSQL database** for metadata and tags.

```bash
#!/bin/bash
# backup-paperless.sh
BACKUP_DIR="/backup/paperless"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"

# Database dump
docker compose exec -T db pg_dump -U paperless paperless | \
  gzip > "$BACKUP_DIR/paperless-db-$TIMESTAMP.sql.gz"

# Media archive
tar czf "$BACKUP_DIR/paperless-media-$TIMESTAMP.tar.gz" \
  -C "$(pwd)" media consume

# Keep last 30 days, remove older
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete
```

Run this daily via cron or a systemd timer. For off-site protection, pipe the backups to restic or borg against a remote repository.

## Conclusion

Paperless-ngx transforms document management in the homelab from a mess of random PDFs into a structured, searchable, and automated archive. Docker Compose makes the full stack — OCR, ML classification, document conversion, and metadata extraction — deployable with a single `docker compose up -d`. Start with the consumption directory workflow, add email ingestion, and let the machine learning model learn your document patterns over time.

For more details, visit the [Paperless-ngx documentation](https://docs.paperless-ngx.com/) and the [GitHub repository](https://github.com/paperless-ngx/paperless-ngx).
