---
title: "Valkey 9.1 Docker Deployment — High-Performance Cache for Your Homelab"
description: "Deploy Valkey 9.1 with Docker Compose for a high-performance, Redis-compatible cache in your homelab. Covers configuration, ACL security, performance tuning, and the new 9.1 features."
date: 2026-05-20T07:00:00-04:00
tags:
  - docker
  - cache
  - homelab
  - performance
  - security
keywords:
  - Valkey 9.1 Docker deployment homelab
  - Redis alternative Valkey Docker Compose
  - Valkey Docker configuration persistence
  - Valkey database level ACL security
  - Valkey JSON logging observability
  - Valkey performance tuning maxmemory
  - Valkey Docker Compose Dockerfile configuration
summary: "Complete guide to deploying Valkey 9.1 with Docker Compose — the high-performance Redis fork with new security, observability, and performance features. Covers config, ACL hardening, and connecting your homelab services."
canonical: "https://blog.gntech.me/posts/valkey-docker-deployment-homelab/"
---

If your homelab runs WordPress, Nextcloud, Grafana, GitLab, or
any session-backed web application, you are almost certainly
running Redis somewhere. Since Redis shifted to a non-OSI license
in 2024, the community has rallied behind **Valkey** — a fully
open-source (BSD-3-Clause), Redis-compatible fork backed by the
Linux Foundation.

Valkey 9.1 dropped on May 19, 2026, and it is a significant
release: 2.1 million requests per second with 512-byte payloads,
database-level access control, JSON logging, and a modular Lua
engine. This guide walks through deploying Valkey 9.1 with Docker
Compose, configuring it for production use, hardening it with
ACLs, and connecting your homelab services.

---

## Why Valkey Over Redis

It is worth understanding the landscape. Redis was the king of
in-memory key-value stores for over a decade. In 2024, Redis Ltd.
switched to a Server Side Public License (SSPL), meaning you
cannot offer Redis as a managed service without a commercial
agreement. Valkey forked from Redis 7.2.4 under the original
BSD-3-Clause license and is governed by the Linux Foundation with
contributions from AWS, Google, Oracle, and Ericsson.

| Aspect | Redis | Valkey |
|--------|-------|--------|
| License | SSPL (restrictive) | BSD-3-Clause |
| Governance | Single vendor | Linux Foundation |
| Latest stable | 7.4.x | 9.1.0 |
| Performance | Baseline | +15-25% (9.1 I/O threading) |
| DB-level ACLs | No | Yes (9.1) |
| JSON logging | No | Yes (9.1) |
| Drop-in compatible | — | Yes, same protocol and commands |

For a homelab, the practical difference is zero today — Valkey
speaks the Redis protocol, so any app that connects to Redis
connects to Valkey unchanged. The long-term difference is that
Valkey is evolving faster and is fully open-source.

---

## Step 1 — Docker Compose Deployment

Create a project directory and a basic `docker-compose.yml`:

```yaml
# /opt/valkey/docker-compose.yml
services:
  valkey:
    image: valkey/valkey:9.1-alpine
    restart: unless-stopped
    container_name: valkey
    command: ["valkey-server", "/etc/valkey/valkey.conf"]
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - ./valkey.conf:/etc/valkey/valkey.conf:ro
      - ./data:/data
      - ./tls:/etc/valkey/tls:ro
    environment:
      - TZ=America/Santo_Domingo
    cap_drop:
      - ALL
    cap_add:
      - SETGID
      - SETUID
      - NET_BIND_SERVICE
    networks:
      - valkey-net
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: 3

networks:
  valkey-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
```

Key points:

- **Bind to 127.0.0.1:** Valkey should never be exposed directly to
  your LAN. Only containers on the same Docker network or the host
  should reach it.
- **Read-only config mount:** Prevents runtime modification to the
  configuration file.
- **Capability drop:** Strips all kernel capabilities except the
  minimum needed (SETGID, SETUID, NET_BIND_SERVICE).
- **Healthcheck:** Every 10 seconds, Valkey-CLI pings the server.
- **Separate network:** Gives Valkey a predictable subnet for
  service discovery.

---

## Step 2 — Valkey Configuration for Homelab

Create `valkey.conf` in the same directory:

```conf
# /opt/valkey/valkey.conf — Valkey 9.1 Homelab Configuration

# Bind to loopback and Docker network
bind 127.0.0.1 172.20.0.2
protected-mode yes
port 6379

# Persistence — snapshot every 5 min if at least 1 key changed
save 300 1
save 60 100
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb

# Append-only file for durability (recommended for production)
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Memory management — cap at 512MB for homelab
maxmemory 512mb
maxmemory-policy allkeys-lru

# Logging — JSON for log aggregation
logfile ""
loglevel notice
log-format json

# Lua — restrict to read-only
lua-time-limit 5000

# Performance — I/O threading (new in 9.1)
io-threads 4
io-threads-do-reads yes

# Slow log
slowlog-log-slower-than 10000
slowlog-max-len 128

# ACL — require a password
requirepass ${VALKEY_PASSWORD}
aclfile /etc/valkey/users.acl

# TLS paths (set to empty to disable)
tls-cert-file ""
tls-key-file ""
tls-ca-cert-file ""
```

### Understanding the Memory Policy

`maxmemory-policy allkeys-lru` is the right choice for a homelab
caching layer. It evicts the least-recently-used key when memory
fills up. For session storage specifically, `volatile-lru` (evict
only keys with an expiry set) is also valid — but `allkeys-lru`
handles apps that forget to set TTLs.

Set `maxmemory` to a value that leaves enough headroom for the OS.
On a 8GB Proxmox host running several containers, 512MB is safe.
If Valkey lives on a dedicated 2GB VM, set it to 1.5GB.

---

## Step 3 — Securing Valkey with ACLs

Valkey 9.1 introduces **number database-level access control**,
which lets you restrict users to specific databases. This is
invaluable when multiple apps share a single Valkey instance.

Create `users.acl`:

```acl
# /opt/valkey/users.acl

# Admin user with full access
user default on >${VALKEY_PASSWORD} ~* &* +@all

# Application users — scoped to specific databases
# WordPress — database 0
user wordpress on >wp-secure-pass ~* +@all -@dangerous db=0

# Grafana — database 1, read-mostly
user grafana on >graf-secure-pass ~* +@read +@write -@admin db=1

# Rate limiter — database 2, minimal permissions
user ratelimit on >rate-secure-pass ~* +GET +SET +EXPIRE +TTL db=2
```

The `+@dangerous` category includes `FLUSHALL`, `FLUSHDB`, `DEBUG`,
`CONFIG`, `SHUTDOWN`, and `SLAVEOF`. Removing it from application
users prevents accidental or malicious data destruction.

Load the ACL file by pointing config at it:

```conf
aclfile /etc/valkey/users.acl
```

Then apply it at runtime without restart:

```bash
docker exec valkey valkey-cli ACL LOAD
```

You can test access restrictions:

```bash
# Authenticate as the wordpress user
docker exec valkey valkey-cli -a wp-secure-pass

# Works — database 0
> SELECT 0
OK

# Blocked — database 3
> SELECT 3
(error) NOPERM No permissions to access database
```

---

## Step 4 — Connecting Homelab Services

### WordPress + Valkey Object Cache

Add a `object-cache.php` drop-in and configure `wp-config.php`:

```php
define('WP_REDIS_HOST', 'valkey');
define('WP_REDIS_PORT', 6379);
define('WP_REDIS_PASSWORD', 'wp-secure-pass');
define('WP_REDIS_DATABASE', 0);
define('WP_CACHE', true);
```

### Nextcloud + Valkey

Nextcloud uses Valkey for file locking, caching, and MFA rate
limiting. In `config/config.php`:

```php
'memcache.local' => '\\OC\\Memcache\\APCu',
'memcache.distributed' => '\\OC\\Memcache\\Redis',
'memcache.locking' => '\\OC\\Memcache\\Redis',
'redis' => [
  'host' => 'valkey',
  'port' => 6379,
  'password' => 'wp-secure-pass',
  'timeout' => 1.5,
],
```

### Grafana + Valkey

Grafana can use Valkey for session storage and query caching. In
`grafana.ini`:

```ini
[session]
provider = redis
provider_config = addr=valkey:6379,password=graf-secure-pass,db=1

[caching]
enabled = true
cache_type = redis
cache_options = addr=valkey:6379,password=graf-secure-pass,db=1
```

### Generic Docker Compose Service

For any other container on the same Docker network, reference
Valkey by service name:

```yaml
services:
  myapp:
    image: myapp:latest
    networks:
      - valkey-net

networks:
  valkey-net:
    external: true
```

Then create the network once:

```bash
docker network create valkey-net
```

---

## Step 5 — Verifying Performance

Valkey 9.1's new I/O threading model and hardware-clock-based
timestamps deliver measurable gains. Run the built-in benchmark:

```bash
docker exec valkey valkey-benchmark -h 127.0.0.1 \
  -p 6379 -n 100000 -c 50 -P 16 -t get,set
```

Expect output like:

```
====== SET ======
  100000 requests completed in 0.85 seconds
  50 parallel clients
  16 bytes payload
  keep alive: 1
  host configuration "save": 300 1
  host configuration "appendonly": yes
  117647.05 requests per second

====== GET ======
  100000 requests completed in 0.73 seconds
  50 parallel clients
  16 bytes payload
  keep alive: 1
  host configuration "save": 300 1
  host configuration "appendonly": yes
  136986.30 requests per second
```

On a moderate homelab server (Ryzen 5, NVMe SSD), Valkey 9.1
easily hits 100k+ ops/sec. The I/O threading improvement
matters most when multiple pipelines run concurrently —
WordPress + Nextcloud + Grafana hitting the same instance.

Check real-time I/O thread usage:

```bash
docker exec valkey valkey-cli INFO STATS | grep -E
  "(io_thread|instantaneous)"
```

---

## Step 6 — Monitoring with JSON Logging

New in 9.1: Valkey can emit logs in JSON format, making them
natively parseable by Loki, OpenSearch, or any JSON-aware log
shipper.

With `log-format json` enabled, logs look like:

```json
{
  "timestamp": "2026-05-19T14:22:33.508Z",
  "role": "master",
  "pid": 14082,
  "message": "* Valkey is starting",
  "version": "255.255.255",
  "bits": 64
}
```

If you have Grafana Alloy or Promtail collecting Docker logs,
they will pick up the JSON format automatically with zero
parsing configuration — no regex-based log scraping needed.

---

## Step 7 — Backups and Maintenance

Valkey persists to both RDB snapshots and AOF logs. Back them up:

```bash
#!/bin/bash
# /opt/valkey/backup.sh
docker exec valkey valkey-cli SAVE
cp -r /opt/valkey/data/ /backup/valkey-$(date +%F)/
```

Or trigger `BGSAVE` and copy the file zero-downtime:

```bash
docker exec valkey valkey-cli BGSAVE
# Wait for background save to complete
while [ "$(docker exec valkey valkey-cli INFO persistence | \
  grep 'rdb_bgsave_in_progress:1')" ]; do sleep 1; done
cp /opt/valkey/data/dump.rdb /backup/
```

For zero-data-loss scenarios, enable AOF with `appendfsync
everysec`. You lose at most one second of writes on a crash.

---

## When to Skip Valkey

Valkey is not always the right tool:

- **Ephemeral caching only:** If you never need the data across
  restarts, run Valkey with `save ""` and `appendonly no`. It
  becomes a pure cache with no disk writes.
- **Single-app homelab:** If you have one small app, a SQLite file
  or a Docker volume-mounted JSON file is simpler.
- **High memory pressure:** Valkey stores everything in RAM. If
  your homelab runs on a 4GB NUC with existing services, add
  memory before reaching for Valkey.

For everything else — session storage, API rate limiting, job
queues, real-time dashboards, object caching — Valkey 9.1 is the
best open-source option available today.

---

## Summary

Valkey 9.1 brings database-level ACLs, JSON logging, I/O
threading, and significant performance improvements to the
Redis-compatible ecosystem. Switching from Redis to Valkey is a
drop-in replacement — export your RDB, change the image tag, and
restart. No code changes.

Beyond the migration story, the new security and observability
features make Valkey 9.1 a genuinely better choice for any
homelab running multiple applications. Database-scoped users mean
you can safely share one Valkey instance across WordPress,
Grafana, Nextcloud, and a custom rate-limiter without worrying
about cross-tenant data access.

Deploy it today, set up ACLs, point your apps at it, and forget
about it. That is the Valkey way.
