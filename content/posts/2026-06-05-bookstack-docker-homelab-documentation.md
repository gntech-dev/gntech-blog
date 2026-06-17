---
title: "BookStack Docker Deployment — Self-Hosted Wiki for Homelab Documentation"
description: "Deploy BookStack with Docker Compose for self-hosted homelab documentation. Full setup with MariaDB, Traefik reverse proxy, LDAP SSO, and backup automation."
date: 2026-06-05T07:00:00-04:00
tags:
  - selfhosting
  - docker
  - homelab
  - documentation
  - docker-compose
keywords:
  - BookStack Docker homelab deployment configuration
  - Self-hosted wiki knowledge base Docker Compose
  - BookStack MariaDB Docker setup guide
  - BookStack Traefik reverse proxy configuration
  - Homelab documentation wiki BookStack best practices
  - BookStack LDAP SSO authentication setup
  - Self-hosted documentation wiki backup automation
summary: "Deploy BookStack with Docker Compose for a self-hosted homelab documentation wiki. Real configs for MariaDB, Traefik, LDAP, and automated backups."
canonical: "https://blog.gntech.me/posts/bookstack-docker-homelab-documentation/"
---

## Why Your Homelab Needs a Documentation Wiki

Every homelab accumulates complexity. VLAN assignments, firewall rules, Docker compose stacks, ZFS pool layouts, backup schedules, Proxmox bridge configurations — you remember them today, but will you remember them six months from now after a RouterOS update? Your homelab documentation should live somewhere searchable, editable, and organized, not scattered across sticky notes and SSH history.

BookStack is a free and open-source wiki platform built on PHP and Laravel. It organizes content in a clean hierarchy: **Shelf → Book → Chapter → Page**. That maps naturally to how homelab knowledge is structured — group related documentation on shelves, create a book per project or subsystem, write detailed pages per configuration.

This guide covers everything you need to run BookStack in Docker Compose on your homelab: MariaDB backend, Traefik reverse proxy with automatic HTTPS, LDAP authentication for team access, and a practical backup strategy.

## Why BookStack Over Other Documentation Tools

BookStack is not the only documentation tool in the self-hosted space. Here is how it compares:

- **BookStack**: Hierarchical out of the box, WYSIWYG + Markdown editor, built-in search, role-based permissions, LDAP/OAuth/SAML authentication, PDF export, no build step
- **Wiki.js**: Modular and extensible, Git-backed storage, but requires a Node.js runtime and client-side rendering that can feel sluggish on lower-end hardware
- **Docusaurus**: Static site generator — excellent for developer docs but requires a build step and Git-based workflow; covered in a [previous post](/posts/docusaurus-documentation-site-homelab/)
- **Outline**: Modern UI and real-time editing, but requires MinIO/S3 object storage and a Redis instance, adding operational overhead

For a homelab, BookStack wins because it has no external dependencies beyond a database. The linuxserver.io Docker image keeps maintenance near zero, the WYSIWYG editor means you do not need Markdown fluency to contribute, and the hierarchical shelf/book/chapter/page model mirrors real infrastructure organization.

## Prerequisites

- Docker and Docker Compose v2 installed on a Linux host
- A working reverse proxy (Traefik or Nginx) for HTTPS termination
- Port 80 and 443 or internal reverse proxy network access

## Deploying BookStack with Docker Compose

The standard setup uses two containers: MariaDB for database storage and the linuxserver.io BookStack image.

Create a directory and the compose file:

```bash
mkdir -p /opt/bookstack
cd /opt/bookstack
nano docker-compose.yml
```

```yaml
services:
  mariadb:
    image: mariadb:11
    container_name: bookstack-db
    restart: unless-stopped
    environment:
      - MYSQL_ROOT_PASSWORD=change-this-root-password
      - MYSQL_DATABASE=bookstack
      - MYSQL_USER=bookstack
      - MYSQL_PASSWORD=change-this-db-password
    volumes:
      - mariadb_data:/var/lib/mysql
    networks:
      - bookstack
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 15s
      timeout: 5s
      retries: 5

  bookstack:
    image: lscr.io/linuxserver/bookstack:latest
    container_name: bookstack
    restart: unless-stopped
    depends_on:
      mariadb:
        condition: service_healthy
    environment:
      - APP_URL=https://docs.gntech.me
      - DB_HOST=mariadb
      - DB_PORT=3306
      - DB_DATABASE=bookstack
      - DB_USERNAME=bookstack
      - DB_PASSWORD=change-this-db-password
      - APP_LANG=en
    volumes:
      - bookstack_data:/config
    networks:
      - bookstack
      - traefik
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.bookstack.rule=Host(`docs.gntech.me`)"
      - "traefik.http.routers.bookstack.entrypoints=websecure"
      - "traefik.http.routers.bookstack.tls.certresolver=letsencrypt"
      - "traefik.http.services.bookstack.loadbalancer.server.port=80"

volumes:
  mariadb_data:
  bookstack_data:

networks:
  bookstack:
    name: bookstack
    driver: bridge
  traefik:
    external: true
```

Replace `change-this-root-password` and `change-this-db-password` with strong random values:

```bash
openssl rand -base64 32 | tee /dev/stderr  # generate and show a password
```

For production, consider using Docker secrets or an `.env` file excluded from version control instead of hardcoding passwords in the compose file.

Start the stack:

```bash
docker compose up -d
docker compose logs -f bookstack
```

Wait for the health check to pass and the BookStack container to initialize the database schema. The first startup takes 30--60 seconds.

## Traefik Reverse Proxy Configuration

The compose file above assumes Traefik runs on an external `traefik` network. If you use a different reverse proxy, adjust the network and labels accordingly.

For Nginx Proxy Manager or plain Nginx, add an upstream block:

```nginx
server {
    listen 443 ssl;
    server_name docs.gntech.me;

    location / {
        proxy_pass http://127.0.0.1:6875;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Note that BookStack serves on port 80 inside the container. If you need to bind to a host port instead of using a reverse proxy network, add `ports: - "6875:80"` to the bookstack service.

## Initial Setup and Configuration

Access your BookStack instance at the configured domain. Navigate to `/register` to create the first admin account.

Once logged in, go to **Settings → Features** to configure:

- **Site name**: "GnTech Homelab Docs" or whatever fits your lab
- **Allow registration**: Disable after creating accounts for team members
- **Default language**: Set per user or globally

### Configuring LDAP Authentication

If you run a directory service (Active Directory, OpenLDAP, or Authentik), BookStack supports LDAP SSO out of the box. Add these environment variables to the `bookstack` service:

```yaml
environment:
  - APP_URL=https://docs.gntech.me
  - LDAP_ENABLED=true
  - LDAP_SERVER=ldap://10.0.20.10:389
  - LDAP_BASE_DN=dc=gntech,dc=me
  - LDAP_DN=cn=binduser,dc=gntech,dc=me
  - LDAP_PASS=your-bind-password
  - LDAP_USER_FILTER=(&(objectClass=user)(sAMAccountName=${user}))
  - LDAP_VERSION=3
  - LDAP_FOLLOW_REFERRALS=false
  - LDAP_ID_ATTRIBUTE=sAMAccountName
  - LDAP_DISPLAY_NAME_ATTRIBUTE=displayName
  - LDAP_EMAIL_ATTRIBUTE=mail
```

Restart the stack after adding LDAP config:

```bash
docker compose up -d
```

Users authenticate with their domain credentials. BookStack maps their LDAP group memberships to roles automatically.

### Configuring SMTP for Email Notifications

BookStack can send password reset emails and page notifications. Configure SMTP under **Settings → Mail**, or inject via environment variables:

```yaml
environment:
  - MAIL_DRIVER=smtp
  - MAIL_HOST=10.0.20.30
  - MAIL_PORT=25
  - MAIL_FROM=docs@gntech.me
  - MAIL_FROM_NAME=GnTech Docs
```

## Organizing Your Homelab Documentation

A well-structured wiki is easier to maintain. Here is a suggested hierarchy for homelab documentation:

```
📚 Networking              (Shelf)
  ├── VLAN Layout          (Book)
  │   ├── VLAN IDs and Purposes      (Page)
  │   ├── Firewall Rules             (Page)
  │   └── DHCP Scopes                (Page)
  ├── MikroTik Config     (Book)
  │   ├── RouterOS 7 Setup           (Page)
  │   ├── BGP Peering               (Page)
  │   └── WireGuard VPN              (Page)
  └── DNS Records          (Book)
      ├── Internal Zones             (Page)
      └── Pi-hole / Unbound          (Page)

📚 Proxmox                 (Shelf)
  ├── Host Configuration   (Book)
  ├── VM Templates         (Book)
  └── Backup Strategy      (Book)
      ├── PBS Setup                  (Page)
      └── Offsite Replication        (Page)

📚 Docker                  (Shelf)
  ├── Compose Stacks       (Book)
  ├── Networking           (Book)
  └── Security             (Book)
```

BookStack supports code blocks with syntax highlighting for configs, inline image uploads for network diagrams, and file attachments for PDF documentation. The search bar indexes all page content including code blocks, so you can find that one firewall rule or compose override file in seconds.

## Backup and Maintenance

BookStack stores content in MariaDB and file uploads in the `/config` volume. A complete backup requires both.

### Automated Database Backup

Create a systemd timer or cron job to dump the database daily:

```bash
#!/bin/bash
# /opt/bookstack/backup.sh
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/tank/backups/bookstack

mkdir -p "$BACKUP_DIR"

docker exec bookstack-db mariadb-dump \
  --single-transaction \
  --user=bookstack \
  --password="change-this-db-password" \
  bookstack | gzip > "$BACKUP_DIR/bookstack-db-$TIMESTAMP.sql.gz"

# Backup volume data
docker run --rm -v bookstack_data:/source -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/bookstack-files-$TIMESTAMP.tar.gz" -C /source .
```

Make it executable and set up a cron entry:

```bash
chmod +x /opt/bookstack/backup.sh
echo "0 3 * * * /opt/bookstack/backup.sh" | crontab -
```

### Restore Procedure

```bash
# Restore database
gunzip -c bookstack-db-20260605-030000.sql.gz | \
  docker exec -i bookstack-db mariadb -u bookstack -p"change-this-db-password" bookstack

# Restore files
docker run --rm -v bookstack_data:/target -v "$PWD":/restore \
  alpine tar xzf "/restore/bookstack-files-20260605-030000.tar.gz" -C /target
```

### Updating BookStack

Since we use the linuxserver.io image, updating is straightforward:

```bash
docker compose pull
docker compose up -d
```

The image auto-runs database migrations on startup, so the schema stays current. Check the [BookStack release notes](https://github.com/BookStackApp/BookStack/releases) before major version bumps.

## Conclusion

BookStack turns the chore of documentation into a habit. With Docker Compose, you go from zero to a fully functional homelab wiki in under ten minutes. Traefik handles TLS, LDAP handles authentication, and a five-line backup script protects your data.

Start by documenting your VLAN layout and firewall rules — the things you most frequently reference. Then expand into Proxmox configs, Docker compose stacks, and recovery procedures. Your future self will thank you.

**Related reading:**
- [BookStack Installation Docs](https://www.bookstackapp.com/docs/admin/installation/)
- [linuxserver/bookstack Docker Image](https://hub.docker.com/r/linuxserver/bookstack)
- [Docusaurus Documentation Site for Homelab](/posts/docusaurus-documentation-site-homelab/)
