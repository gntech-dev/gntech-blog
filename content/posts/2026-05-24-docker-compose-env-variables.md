---
title: "Docker Compose Environment Variables — .env, Substitution, and Secrets"
description: "Complete guide to Docker Compose environment variables — .env file scoping rules, variable substitution syntax, env_file vs environment blocks, and when to use Docker secrets instead of env vars. With real compose.yml examples for homelab deployments."
date: 2026-05-24T10:00:00-04:00
tags:
  - docker
  - docker-compose
  - homelab
  - devops
  - containers
keywords:
  - Docker Compose .env file scoping and precedence
  - Docker Compose variable substitution syntax
  - Docker Compose env_file vs environment blocks
  - Docker Compose secrets management
  - Docker Compose extension field interpolation
  - Docker Compose multiple environment files
  - Docker Compose variable default error handling
summary: "Master Docker Compose environment variables — understand .env file scoping, variable substitution syntax with defaults and errors, env_file vs environment blocks, and when to use Docker secrets over env vars for sensitive data in homelab deployments."
canonical: "https://gntech.dev/posts/docker-compose-env-variables/"
---

Every Docker Compose user hits the wall eventually. You define
`POSTGRES_PASSWORD=mydbpass` in an `.env` file, but the container
reads an empty string. You try `${VAR:-default}` syntax and it
doesn't behave the way the documentation suggested. You switch
between environments and miss a variable, causing cryptic startup
failures.

The `.env` file in Docker Compose looks simple on the surface, but
the scoping rules, substitution behavior, and interaction with
`environment`, `env_file`, and Docker secrets have subtle traps
that trip up everyone — including experienced operators.

This guide covers everything you need to manage environment
variables in Docker Compose: how `.env` files work, when variables
are substituted and when they aren't, the difference between
`environment` and `env_file`, and the security boundaries between
env vars and Docker secrets. Every example uses real
`docker-compose.yml` snippets you can adapt to your homelab.

---

## How .env Files Work in Docker Compose

Docker Compose reads the `.env` file from the **project directory**
(the directory containing your `docker-compose.yml`). Variables
defined there are interpolated into the compose file before
services are built or started.

```bash
# Project structure
~/homelab/nginx/
├── docker-compose.yml
├── .env              # ← Compose reads this automatically
└── nginx.conf
```

```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:${NGINX_VERSION:-alpine}
    ports:
      - "${HTTP_PORT:-80}:80"
    environment:
      - NGINX_HOST=${DOMAIN:-localhost}
```

```bash
# .env
NGINX_VERSION=1.27-alpine
HTTP_PORT=8080
DOMAIN=web.gntech.dev
```

When you run `docker compose up -d`, Compose reads `.env`,
substitutes `${NGINX_VERSION}`, `${HTTP_PORT}`, and `${DOMAIN}`,
then creates the container with `nginx:1.27-alpine`, port 8080,
and `NGINX_HOST=web.gntech.dev`.

### Where Docker Compose Looks for .env

The `.env` file must be in the **same directory** as the compose
file or in the **project directory** (the parent of the compose
file if you use `-f`). Compose does **not** search parent
directories recursively.

```bash
# These all look for .env in /opt/homelab
cd /opt/homelab && docker compose up -d
docker compose -f /opt/homelab/docker-compose.yml up -d
```

```bash
# This does NOT load /opt/homelab/.env
docker compose -f /opt/homelab/services/web/compose.yml up -d
# .env must be at /opt/homelab/services/web/.env
```

### Shell Variables vs .env Precedence

When a variable exists in both the shell environment and the
`.env` file, the **shell environment wins**. This is by design —
it lets you override `.env` values without editing the file:

```bash
# .env has DB_NAME=mydb
# Override it for one-off commands
DB_NAME=testdb docker compose up -d
```

Variable resolution order (highest to lowest priority):

1. Shell environment variables
2. `.env` file variables
3. Compose file hardcoded values
4. Variable default (`:-`) or error (`:?`) fallback

This means you can chain overrides safely. The compose file
defines the structure, `.env` stores the defaults for your
environment, and shell vars handle temporary overrides.

---

## Variable Substitution Syntax

Docker Compose supports the full set of shell-like variable
substitution expressions. These work in **any string value**
in `docker-compose.yml` — image tags, port numbers, volume paths,
environment values, labels, and extension fields.

### Basic Substitution

```yaml
services:
  app:
    image: myapp:${TAG}
```

If `TAG` is undefined, Compose raises an error and refuses to
start. Always provide a default or explicitly handle missing
variables.

### Default Values with `:-`

```yaml
services:
  app:
    image: myapp:${TAG:-latest}
    ports:
      - "${PORT:-3000}:3000"
```

If `TAG` is not set, Compose substitutes `latest`. If `PORT` is
not set, it substitutes `3000`. This is the safest pattern for
optional configuration.

### Mandatory Variables with `:?`

```yaml
services:
  postgres:
    image: postgres:${PG_VERSION:-16-alpine}
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD:?Database password is required}
      POSTGRES_DB: ${DB_NAME:?Database name is required}
```

When `:?` is used and the variable is unset or empty, Compose
prints the error message and exits **before** creating any
containers. This catches missing configuration at the parsing
stage instead of at container runtime.

### Alternate Value with `:+`

```yaml
services:
  app:
    environment:
      - LOG_LEVEL=${VERBOSE:+debug}
```

If `VERBOSE` is set (to any non-empty value), `LOG_LEVEL` becomes
`debug`. If `VERBOSE` is unset, `LOG_LEVEL` is an empty string.
Use this for toggle-style configuration.

### Escape `$` for Literal Dollar Signs

Docker Compose interprets `$` as the start of a variable. To
use a literal `$` in a value, double it:

```yaml
services:
  app:
    environment:
      - SHELL_CHAR=$$
      - CURRENCY=\$50
```

The `$$` produces a single `$` at runtime. The backslash-escape
`\$` is recognized by Docker Compose 2.x as an alternative.

---

## `environment` vs `env_file` — When to Use Each

Docker Compose provides two ways to pass variables into a
container. They look similar but behave differently.

### The `environment` Block

Variables in `environment` are **always passed** to the
container, regardless of how they're defined:

```yaml
services:
  app:
    environment:
      # Hardcoded value
      - MODE=production
      # From compose interpolation (reads .env or shell)
      - DB_HOST=${DB_HOST:-postgres}
      # Pairs syntax (equivalent to above)
      DB_PORT: ${DB_PORT:-5432}
```

The `environment` block is **interpolated at compose parsing
time** — `${DB_HOST}` is resolved before the container starts.
If `DB_HOST` is not set anywhere, the default `postgres` is used.

### The `env_file` Directive

```yaml
services:
  app:
    env_file:
      - ./app.env
      - ./app.override.env  # later files override earlier ones
```

```bash
# app.env
DB_HOST=postgres
DB_PORT=5432
DB_NAME=myapp
```

Variables from `env_file` are **not interpolated by Compose**.
They are passed verbatim to the container. If `app.env` contains
`DB_HOST=${DB_HOST:-postgres}`, the container sees the literal
string `${DB_HOST:-postgres}`, not the resolved value.

**This is the most common source of confusion.** Use `env_file`
for static key-value pairs that don't need interpolation. Use
`environment` when you need variable substitution.

### Which One to Use

Situation                               | Use
----------------------------------------|---------------------
Static config that never changes        | `environment` (hardcoded)
Values that differ per environment      | `.env` + `environment` (interpolation)
Long lists of variables (10+)           | `env_file`
Secrets or credentials                  | Docker secrets (see below)
Third-party config (Terraform output)   | `env_file` generated by script

A practical hybrid approach for a homelab stack:

```yaml
# docker-compose.yml
services:
  app:
    env_file:
      - ./app.env           # static config
    environment:
      - DB_HOST=${DB_HOST}  # from .env or shell
      - DB_PORT=${DB_PORT}
```

```bash
# app.env (static, never changes per environment)
TZ=America/Santo_Domingo
LANG=en_US.UTF-8
```

```bash
# .env (per-environment config)
DB_HOST=pg1.gntech.dev
DB_PORT=5432
```

---

## Multiple .env Files and Override Chains

Compose 2.x supports loading **multiple `.env` files** with the
`--env-file` flag:

```bash
# Load base.env first, then override with production.env
docker compose --env-file ./base.env --env-file ./production.env up -d
```

Later files take precedence. Variables from the shell
environment always win over any `.env` file.

### Environment-Specific Compose Files

For more complex setups, combine `.env` with multiple compose
files and the `-f` flag:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  --env-file .env.prod \
  up -d
```

```yaml
# docker-compose.prod.yml — overrides development defaults
services:
  app:
    deploy:
      resources:
        limits:
          memory: 512M
    restart: always
```

The production override file adds restart policies and resource
limits without modifying the base compose file. The `.env.prod`
file supplies production-specific variables (database URLs, API
keys, domain names).

### Project-Level .env with Multiple Stacks

If you run multiple compose stacks in subdirectories, create a
`.env` in each project directory:

```text
/opt/homelab/
├── .env                # Top-level (NOT automatically loaded)
├── web/
│   ├── docker-compose.yml
│   └── .env            # Auto-loaded for web stack
├── monitoring/
│   ├── docker-compose.yml
│   └── .env            # Auto-loaded for monitoring stack
└── database/
    ├── docker-compose.yml
    └── .env            # Auto-loaded for database stack
```

If you want a shared `.env` at the top level, load it explicitly:

```bash
cd /opt/homelab/web
docker compose --env-file ../.env up -d
```

---

## Extension Fields for Dry Variable Reuse

Compose extension fields (`x-*`) let you define reusable
variable blocks and interpolate them across services:

```yaml
# docker-compose.yml
x-logging: &logging
  driver: "json-file"
  options:
    max-size: "${LOG_MAX_SIZE:-10m}"
    max-file: "${LOG_MAX_FILES:-3}"

x-deploy: &deploy
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: ${MEM_LIMIT:-256M}

services:
  app:
    image: myapp:${TAG:-latest}
    ports:
      - "${APP_PORT:-3000}:3000"
    environment:
      - NODE_ENV=${NODE_ENV:-production}
    <<: [*logging, *deploy]

  worker:
    image: myapp:${TAG:-latest}
    command: worker
    environment:
      - NODE_ENV=${NODE_ENV:-production}
    <<: [*logging, *deploy]
```

All services inherit the same logging config and restart policy
from the extension fields. Change `LOG_MAX_SIZE` or `MEM_LIMIT`
in `.env` and all services pick it up.

---

## Environment Variables vs Docker Secrets

**Environment variables are not secrets.** Any process that can
run `docker inspect` on a container can read its environment
variables. Any process inside the container can read
`/proc/1/environ`. Compose files (and their `.env` files) are
often committed to version control.

Docker secrets are the correct mechanism for sensitive data:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

Secrets are mounted as tmpfs files at `/run/secrets/<name>`
inside the container. They never appear in `docker inspect`
output, command lines, or environment dumps.

### When to Use Each

Use **environment variables** for:
- Service names and ports
- Runtime mode (development vs production)
- Feature flags and toggles
- Log levels and debug settings
- Database names, usernames (but not passwords)

Use **Docker secrets** for:
- Database passwords and API tokens
- TLS private keys and certificates
- Any value that would cause damage if leaked
- Credentials for external services (S3, SMTP, Cloudflare)

### Hybrid Pattern for Legacy Images

Some Docker images only accept credentials through environment
variables (e.g., `POSTGRES_PASSWORD`). For these, use the
`_FILE` convention:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
```

Postgres detects `POSTGRES_PASSWORD_FILE` and reads the secret
file instead of the environment variable. Many official images
support this pattern (`*_FILE`). Check the image documentation.

---

## Putting It All Together — Real Homelab Compose

Here is a complete example combining every pattern from this
post:

```bash
# .env
TAG=2026.05
LOG_MAX_SIZE=10m
LOG_MAX_FILES=3
MEM_LIMIT=512M

APP_DOMAIN=app.gntech.dev
APP_PORT=3000

DB_HOST=postgres
DB_PORT=5432
DB_NAME=myapp

POSTGRES_DB=myapp
```

```yaml
# docker-compose.yml
x-logging: &logging
  driver: "json-file"
  options:
    max-size: "${LOG_MAX_SIZE}"
    max-file: "${LOG_MAX_FILES}"

x-healthcheck: &healthcheck
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s

services:
  traefik:
    image: traefik:${TAG:-latest}
    secrets:
      - cf_api_token
    environment:
      - CF_DNS_API_TOKEN_FILE=/run/secrets/cf_api_token
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    <<: [*logging, *healthcheck]
    restart: unless-stopped

  app:
    image: myapp:${TAG:-latest}
    env_file:
      - ./app.env
    environment:
      DB_HOST: ${DB_HOST:?Database host is required}
      DB_PORT: ${DB_PORT:-5432}
      DB_NAME: ${DB_NAME:?Database name is required}
      NODE_ENV: ${NODE_ENV:-production}
    secrets:
      - db_password
    <<: [*logging, *healthcheck]
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      POSTGRES_DB: ${POSTGRES_DB:?Database name required}
      POSTGRES_USER: ${POSTGRES_USER:-app}
    volumes:
      - pgdata:/var/lib/postgresql/data
    <<: [*logging, *healthcheck]
    restart: unless-stopped

volumes:
  pgdata:

secrets:
  cf_api_token:
    file: ./secrets/cf_api_token.txt
  db_password:
    file: ./secrets/db_password.txt
```

```bash
# secrets/db_password.txt
# Not in version control! Add to .gitignore
# chmod 600 secrets/db_password.txt
V3ryS3cur3P4ssw0rd!
```

This stack uses every pattern:
- **`.env`** for environment-specific values
- **Extension fields** for shared logging and healthcheck config
- **`:?`** mandatory variable validation for database config
- **`:-`** defaults for ports, log sizes, and tags
- **Docker secrets** for database password and Cloudflare API
  token
- **`*_FILE` convention** for images that only accept env vars
- **`env_file`** for large static config blocks

---

## Debugging Variable Substitution

When variables don't resolve the way you expect:

```bash
# Print the final compose config after interpolation
docker compose config

# This shows every service definition with all variables
# resolved to their final values
```

```bash
# Check which variables are set in the shell
echo ${TAG:-unset}
echo ${DB_HOST:-unset}

# View .env file content (excluding secrets)
grep -v -f .gitignore .env
```

Use `docker compose config` as your primary debugging tool. If
it shows the wrong value, trace the resolution chain: shell
env → `.env` → compose file defaults.

---

## Summary

Docker Compose variable management has clear rules once you know
them:

1. **`.env` is auto-loaded** from the compose file directory;
   shell vars override it
2. **`:-` provides defaults**, `:?` enforces required variables,
   `:+` enables toggle patterns
3. **`environment` is interpolated** at parse time; **`env_file`
   is passed verbatim** to the container
4. **Use `--env-file`** for loading `.env` from custom paths or
   chaining multiple files
5. **Extension fields** (`x-*`) let you define reusable
   variable-driven config blocks
6. **Docker secrets** for credentials; `_FILE` convention for
   images that only support env vars
7. **`docker compose config`** shows the fully resolved config
   for debugging

Start every new compose stack with a `.env` file for
environment-specific values, `:?` for mandatory variables,
Docker secrets for credentials, and extension fields for shared
config. Your future self — and anyone else deploying your stack —
will thank you.
