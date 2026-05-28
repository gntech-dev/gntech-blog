---
title: "Docker Container Migration — Move Containers Between Hosts in Your Homelab"
description: "Complete guide to migrating Docker containers between homelab hosts — volume backup and restore, image export/import, Compose stack portability, and NFS-based zero-copy migration with minimal downtime."
date: 2026-05-28T07:00:00-04:00
tags:
  - docker
  - homelab
  - backup
  - storage
  - migration
keywords:
  - Docker container migration between hosts guide homelab
  - Docker volume backup and restore across hosts
  - Docker Compose stack migration new server
  - Docker image export import without registry
  - Docker persistent data migration rsync restic
  - Docker container migration minimal downtime homelab
  - migrate Docker environment to new host step by step
summary: "Migrate Docker containers between homelab hosts with minimal downtime. Covers volume backup and restore, image export/import, Compose stack portability, and rsync-based data transfer strategies."
canonical: "https://gntech.dev/posts/docker-container-migration-homelab/"
---

You've outgrown your first Docker host, you're rebuilding Proxmox nodes, or you just want to move a stack to a beefier server without starting from scratch. Migrating Docker containers between hosts is a task every homelab operator eventually faces, and doing it wrong means losing persistent data, breaking DNS, or forgetting critical .env files.

This guide covers three migration methods — volume-level, NFS-based zero-copy, and full-environment rsync — with real commands and a complete workflow example. By the end you'll know exactly how to move any container or Compose stack between hosts cleanly.

All commands target Debian 12 / Ubuntu 24.04 with Docker Engine 27+ and Docker Compose v2.

---

## 1. When and Why You Migrate

Migration scenarios in a homelab typically fall into one of three buckets:

- **Server upgrade** — replacing an older LXC or VM with a newer Proxmox host
- **Hardware failure** — a disk is failing, ZFS pool is degrading, move services off fast
- **Rebalancing** — spreading workloads across multiple hosts to avoid resource contention

The core challenge is always the same: containers are ephemeral, but the data they write — databases, uploaded files, configuration — is not. A well-planned migration treats the container as disposable and the data as precious.

---

## 2. Strategy Overview — Three Migration Methods

| Method | Downtime | Complexity | Best For |
|--------|----------|------------|----------|
| Volume backup/restore | Medium (minutes) | Low | Single containers, small stacks |
| NFS zero-copy | Low (seconds) | Medium | Services with shared storage |
| Full /var/lib/docker rsync | High (10-30 min) | Low | Full environment rebuilds |

Picking the right method depends on how much downtime you can tolerate and how much data you're moving.

---

## 3. Method A — Container-Level Migration with Volume Backup

This is the most portable approach. You back up each named volume as a compressed tarball, save the container image, and re-create the container on the new host.

### Backup Volumes

```bash
# List your named volumes
docker volume ls

# Backup a single volume (e.g., grafana_data)
docker run --rm \
  -v grafana_data:/data \
  -v /tmp/backup:/backup \
  alpine tar czf /backup/grafana_data.tar.gz -C /data .
```

For bind mounts, you can tar the host path directly:

```bash
tar czf /tmp/backup/prometheus_data.tar.gz -C /tank/monitoring/prometheus .
```

### Save and Compress Images

```bash
docker save grafana/grafana:latest | gzip > /tmp/backup/grafana-image.tar.gz
docker save prom/prometheus:latest | gzip > /tmp/backup/prometheus-image.tar.gz
```

If you have a local registry, push images instead for a faster transfer:

```bash
docker tag grafana/grafana:latest registry.gntech.dev/grafana:latest
docker push registry.gntech.dev/grafana:latest
```

### Transfer and Restore on the New Host

```bash
# Transfer backups
rsync -avz /tmp/backup/ root@10.0.20.31:/tmp/backup/

# On the new host — load images
gunzip -c /tmp/backup/grafana-image.tar.gz | docker load
gunzip -c /tmp/backup/prometheus-image.tar.gz | docker load

# Restore volumes
docker run --rm \
  -v grafana_data:/data \
  -v /tmp/backup:/backup \
  alpine tar xzf /backup/grafana_data.tar.gz -C /data

docker run --rm \
  -v prometheus_data:/data \
  -v /tmp/backup:/backup \
  alpine tar xzf /backup/prometheus_data.tar.gz -C /data
```

### Deploy the Container

Keep your `docker-compose.yml` in version control so it's already on the new host:

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped

volumes:
  grafana_data:
    external: true
```

```bash
docker compose up -d
```

---

## 4. Method B — NFS-Based Zero-Copy Migration

If your homelab already uses NFS (see our [NFS storage homelab guide](https://gntech.dev/posts/nfs-storage-homelab-proxmox-docker/)), you can migrate without copying a single byte of application data. The idea is simple: mount the same NFS export on both hosts, and all you move is the container runtime.

### NFS Volume in a Compose File

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - prometheus_data:/prometheus

volumes:
  prometheus_data:
    driver_opts:
      type: nfs
      o: addr=10.0.20.10,nolock,soft,rw
      device: :/tank/monitoring/prometheus
```

### Migration Sequence

```bash
# On the source host — stop the stack
cd /opt/stacks/monitoring
docker compose down

# On the target host — deploy the exact same compose file
cd /opt/stacks/monitoring
git pull  # or rsync the compose file
docker compose up -d
```

The data stays mounted on the NFS share the entire time. Downtime is only the time it takes for `docker compose down` and `docker compose up -d` — typically under 10 seconds. This works best for stateless or NFS-friendly services like Prometheus, Loki, Grafana, and Pi-hole.

**Caveat:** Databases (PostgreSQL, MariaDB) should not use NFS as their primary data store without proper sync/fsync tuning. For those, use Method A with a proper dump.

---

## 5. Method C — Full Docker Environment Migration

When you're replacing a host entirely or the old host is failing, you can rsync the entire Docker data directory. This is brute-force but works.

```bash
# On the source host
systemctl stop docker

# On the target host — rsync the entire data directory
rsync -avz --progress \
  root@10.0.20.30:/var/lib/docker/ \
  /var/lib/docker/

# Start Docker on the target
systemctl start docker
```

**Optimisation tip:** Exclude the `overlay2` directory (container layers) if you plan to pull fresh images on the target. This saves gigabytes of transfer time:

```bash
rsync -avz --progress --exclude='overlay2/' \
  root@10.0.20.30:/var/lib/docker/ \
  /var/lib/docker/
```

After rsync, run `docker image ls` and `docker volume ls` on the target to verify everything arrived. Start containers with `docker start $(docker ps -aq)` or your Compose stack.

---

## 6. Database Migration Considerations

Databases are the most sensitive part of any migration. Use application-aware dumps:

**PostgreSQL:**
```bash
docker exec postgres pg_dump -U appdb -d myapp \
  --clean --if-exists > /backup/myapp.sql

# Restore
cat /backup/myapp.sql | docker exec -i postgres psql -U appdb -d myapp
```

**MariaDB / MySQL:**
```bash
docker exec mariadb mysqldump --all-databases \
  --single-transaction > /backup/mariadb.sql

# Restore
cat /backup/mariadb.sql | docker exec -i mariadb mysql
```

**SQLite:**
```bash
# Container must be stopped
docker stop vaultwarden
cp /opt/vaultwarden/data/db.sqlite3 /backup/
```

**Redis:**
```bash
docker exec redis redis-cli SAVE
# Then copy /data/dump.rdb from the volume
```

Never raw-copy a database volume without stopping the container first — you risk silent corruption from in-flight writes.

---

## 7. Network Identity After Migration

Containers that rely on static IPs (macvlan, ipvlan) lose their network identity when they move.

### Macvlan / Static IPs

If your container uses a macvlan network for LAN access, the IP must be available on the target host's network. Update your DHCP reservation or adjust the Compose config:

```yaml
networks:
  my_macvlan:
    driver: macvlan
    driver_opts:
      parent: eth0
    ipam:
      config:
        - subnet: "10.0.30.0/24"
          gateway: "10.0.30.1"
          ip_range: "10.0.30.200/28"

services:
  nginx:
    networks:
      my_macvlan:
        ipv4_address: "10.0.30.201"
```

### DNS and Traefik

Most homelab stacks front services through Traefik or Nginx. Since Traefik routers are configured in Compose labels, they travel with the stack. The only DNS change is updating your domain's A record or internal DNS to point to the new host IP.

---

## 8. Migration Checklist

Before you start pulling the plug, run through this checklist:

- [ ] Backup all named volumes to compressed tar files
- [ ] Export container images or push to a private registry
- [ ] Copy `.env` files and any secrets referenced in Compose
- [ ] Verify volume mount paths exist on the target host
- [ ] Update DNS records or reverse proxy rules for the new IP
- [ ] Test a single non-critical service first
- [ ] Keep the old host running for a 24-hour rollback window

---

## 9. Real-World Example: Migrate Traefik + Grafana + Prometheus

Here's a complete migration of a monitoring stack from a source LXC (10.0.20.30) to a new host (10.0.20.31):

```bash
# ==== On source host (10.0.20.30) ====

cd /opt/stacks/monitoring

# 1. Backup data volumes
docker run --rm -v grafana_data:/data -v $(pwd)/backup:/backup \
  alpine tar czf /backup/grafana_data.tar.gz -C /data .
docker run --rm -v prometheus_data:/data -v $(pwd)/backup:/backup \
  alpine tar czf /backup/prometheus_data.tar.gz -C /data .

# 2. Save images
docker save grafana/grafana:latest | gzip > backup/grafana-image.tar.gz
docker save prom/prometheus:latest | gzip > backup/prometheus-image.tar.gz
docker save traefik:v3.3 | gzip > backup/traefik-image.tar.gz
docker save grafana/loki:latest | gzip > backup/loki-image.tar.gz

# 3. Transfer everything to the new host
rsync -avz backup/ root@10.0.20.31:/tmp/migration/
rsync -avz docker-compose.yml root@10.0.20.31:/opt/stacks/monitoring/
rsync -avz .env root@10.0.20.31:/opt/stacks/monitoring/

# 4. Stop the stack
docker compose down


# ==== On target host (10.0.20.31) ====

cd /opt/stacks/monitoring

# 5. Load images
for f in /tmp/migration/*.tar.gz; do
  gunzip -c "$f" | docker load
done

# 6. Create and restore volumes
docker volume create grafana_data
docker volume create prometheus_data

docker run --rm -v grafana_data:/data -v /tmp/migration:/backup \
  alpine tar xzf /backup/grafana_data.tar.gz -C /data

docker run --rm -v prometheus_data:/data -v /tmp/migration:/backup \
  alpine tar xzf /backup/prometheus_data.tar.gz -C /data

# 7. Bring it up
docker compose up -d
```

Total downtime: approximately 3-5 minutes. Rollback is just reversing the process on the old host.

---

## 10. Summary

Docker container migration doesn't have to be stressful. Pick the method that fits your stack:

- **Volume backup/restore** for most single-container and small-stack moves
- **NFS zero-copy** for large data sets and minimal downtime
- **Full rsync** for whole-environment migrations

The most important rule: test your restore process on a throwaway host before doing it for real. Practise the migration with a non-critical service first, then scale up. Keep old hosts around for at least 24 hours post-migration, and version-control your Compose files so you're never hunting for configs after the move.

For automated volume backups, check out our [restic Docker backup guide](https://gntech.dev/posts/restic-docker-backup-strategy/) — it pairs perfectly with the migration and restore workflows covered here.
