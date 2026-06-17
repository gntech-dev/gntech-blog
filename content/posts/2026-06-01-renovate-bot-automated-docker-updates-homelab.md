---
title: "Renovate Bot Homelab — Automated Docker Dependency Updates with Git"
description: "Automate Docker Compose and Dockerfile dependency updates in your homelab with Renovate Bot. Self-hosted setup with Gitea for automated PR-based image version bumps and digest pinning."
date: 2026-06-01T09:00:00-04:00
tags:
  - docker
  - gitops
  - devops
  - automation
  - homelab
keywords:
  - Renovate Bot Docker homelab automated dependency updates
  - Self-hosted Renovate bot Gitea configuration example
  - Docker Compose image tag update automation Renovate
  - Renovate bot configuration JSON5 renovate.json5 presets
  - Automated Dockerfile FROM image version bumping
  - Docker digest pinning immutable builds Renovate
  - Homelab dependency management automated PR workflow
summary: "Automate Docker dependency updates in your homelab with Renovate Bot. Self-host or use the cloud bot to scan Docker Compose files and Dockerfiles, then open pull requests with version bumps, digest updates, and changelog summaries."
canonical: "https://blog.gntech.me/posts/renovate-bot-automated-docker-updates-homelab/"
---

## Why Automate Docker Dependency Updates in Your Homelab

You maintain a dozen Docker Compose stacks — databases, reverse proxies, media servers, monitoring tools. Each uses Docker images with version tags like `nginx:1.25-alpine`, `postgres:16-bookworm`, or `traefik:v3.1`. Over time these go stale. Security patches ship, bugs get fixed, and your compose files still reference the old tag.

Most homelabbers rely on **Watchtower** or **Diun** for runtime updates — pull the image, restart the container, done. That works for keeping running containers current, but it doesn't update your *source of truth*: the docker-compose.yml in your git repository.

**Renovate Bot** fills that gap. It scans your git repos for Dockerfile `FROM` lines, docker-compose image references, and even Kubernetes manifests. When a newer version exists, Renovate opens a pull request with the updated tag, optionally pins the digest, and includes release notes from the upstream registry.

The result is a full GitOps workflow: your compose definitions stay current in git, and you decide when to merge the update.

## How Renovate Differs from Watchtower

| Aspect | Watchtower | Renovate |
|--------|-----------|----------|
| What it updates | Running containers | Source definitions (git) |
| When it acts | On schedule + new image | On schedule per cron |
| Workflow | Pull + restart | Create PR |
| Rollback | Re-pull old tag | Revert commit in git |
| Auditing | Container logs | Git history + PR |

Both tools complement each other. Renovate keeps your git definitions accurate; Watchtower picks up merged changes and restarts containers.

## Self-Hosted vs Cloud Renovate

Renovate has two deployment models:

**Cloud bot** — GitHub and GitLab each have a Renovate app. Install it, add `renovate.json5` to your repos, and it runs on every push. Free for public repos, simple setup.

**Self-hosted** — Run the Renovate Docker image on your own schedule against any git forge: Gitea, Forgejo, GitLab CE, or Bitbucket. Full control over schedule, configuration, and which repos are scanned.

For a homelab with a self-hosted Gitea instance, self-hosted Renovate is the natural choice.

## Step-by-Step — Self-Hosted Renovate with Gitea

### 1. Shared Configuration Repository

Create a private repository called `renovate-config` to hold your default preset. This keeps per-repo configs minimal.

```json5
// renovate-config/default.json5
{
  $schema: "https://docs.renovatebot.com/renovate-schema.json",
  extends: [
    "config:recommended",
    "docker:pinDigests",
    "docker:enableMajor",
    ":maintainLockFilesMonthly",
  ],
  labels: ["dependencies", "docker"],
  schedule: ["before 6am on Monday"],
  packageRules: [
    {
      matchManagers: ["docker-compose", "dockerfile"],
      groupName: "Docker dependencies",
      groupSlug: "docker",
      automerge: false,
      labels: ["docker-update"],
    },
    {
      matchUpdateTypes: ["pin", "digest"],
      automerge: true,
      labels: ["docker-pin"],
    },
    {
      matchUpdateTypes: ["major"],
      labels: ["docker-major"],
      automerge: false,
      description: "Major version bumps require manual review",
    },
  ],
  docker: {
    pinDigests: true,
  },
}
```

This preset:
- Extends recommended rules and Docker digest pinning
- Groups all Docker updates into a single weekly PR (Monday morning)
- Auto-merges digest/pin updates (low risk)
- Flags major version bumps for manual review
- Applies labels for easy filtering in the PR list

### 2. Per-Repository renovate.json5

Each docker-compose repository includes a minimal config referencing the shared preset:

```json5
// homelab-infra/renovate.json5
{
  $schema: "https://docs.renovatebot.com/renovate-schema.json",
  extends: ["local>gitea.yourlab.internal/renovate-config:default.json5"],
}
```

The `local>` preset reference tells Renovate to fetch the config from the configured git forge. No need to duplicate rules across a dozen repos.

### 3. Deploy Renovate with Docker Compose

Create a compose file for the Renovate bot itself:

```yaml
services:
  renovate:
    image: renovate/renovate:39
    container_name: renovate
    restart: unless-stopped
    volumes:
      - ./config.js:/usr/src/app/config.js:ro
      - ./data:/usr/src/app/data
    environment:
      RENOVATE_TOKEN: ${RENOVATE_TOKEN}
      RENOVATE_ENDPOINT: "${GITEA_URL}/api/v1"
      RENOVATE_AUTODISCOVER: "true"
      RENOVATE_AUTODISCOVER_FILTER: "homelab-*,infra-*"
      RENOVATE_PLATFORM: "gitea"
      RENOVATE_BASE_DIR: "/usr/src/app/data"
      RENOVATE_CONFIG_FILE: "/usr/src/app/config.js"
      LOG_LEVEL: "info"
```

Start it with:

```bash
docker compose up -d
```

Renovate runs continuously in daemon mode, scanning on the schedule defined in your config.

For single-shot execution (useful for testing), run:

```bash
docker compose run --rm renovate
```

### 4. Gitea API Access Token

Generate a Gitea token with `read:repository`, `write:repository`, and `read:issue` scopes:

```bash
# Using Gitea CLI or API
gitea admin user generate-access-token \
  --username renovate \
  --scopes "read:repository,write:repository,read:issue"
```

Set the token as `RENOVATE_TOKEN` in your `.env` file:

```
RENOVATE_TOKEN=gitea_xxxxxxxxxxxx
GITEA_URL=https://gitea.yourlab.internal
```

### 5. First Run — Verification

Run Renovate in dry mode to verify everything works without creating PRs:

```bash
docker compose run --rm renovate --dry-run
```

Check the logs for "Found Dockerfile package files" and "PR created" entries. If Autodiscover filtered correctly, only the matching repos appear.

Once dry-run is clean, run for real:

```bash
docker compose run --rm renovate
```

Renovate scans each repo, checks current image tags against registries, and opens PRs for any updates found.

### 6. What a Renovate PR Looks Like

When Renovate detects an update, the PR title, body, and diff look like this:

```
Title: chore(deps): update docker.io/library/nginx:1.25-alpine to 1.26-alpine

Body:
- **Schedule**: Before 6 AM on Monday
- **Branch**: renovate/docker-nginx-1.x
- **Update type**: minor
- **Release notes**: https://github.com/nginx/nginx/releases/tag/release-1.26.0

![nginx-version](https://img.shields.io/badge/nginx-1.25%20→%201.26-blue)

Diff:
-    image: nginx:1.25-alpine
+    image: nginx:1.26-alpine@sha256:abc123def456...
```

If you enabled digest pinning, the PR includes the SHA256 digest for immutable builds.

## Configuration Deep Dive

### Presets Worth Using

- `config:recommended` — Sensible defaults for most projects
- `docker:pinDigests` — Replace tag-only references with tag+digest
- `docker:enableMajor` — Allow major version PRs (disabled by default for Docker)
- `:maintainLockFilesMonthly` — Monthly lock file refresh (mostly for npm, but applies generally)
- `:automergeMinor` — Auto-merge minor/patch updates (enable with caution — test your config first)

### Package Rules for Docker Groups

Group all Docker updates into one PR to reduce noise:

```json5
{
  packageRules: [
    {
      matchManagers: ["docker-compose", "dockerfile"],
      groupName: "Docker dependencies",
      labels: ["docker"],
    },
  ],
}
```

Without grouping, each outdated image gets its own PR — noisy for busy compose files with 10+ images.

### Custom Managers for Non-Standard Files

If you reference Docker images in shell scripts, Ansible variables, or Terraform, add a custom manager:

```json5
{
  customManagers: [
    {
      customType: "regex",
      fileMatch: ["\\.env$", "\\.bash$", "scripts/.*\\.sh$"],
      matchStrings: [
        "IMAGE_TAG=(?<currentValue>.*)\\n",
      ],
      datasourceTemplate: "docker",
      depNameTemplate: "library/nginx",
      versioningTemplate: "docker",
    },
  ],
}
```

This catches environment variable-driven image tags — useful when your compose file references an `$IMAGE_TAG` variable.

## Digest Pinning for Immutable Builds

Docker tags are mutable. `nginx:1.25-alpine` today might not be `nginx:1.25-alpine` tomorrow if the image is overwritten or a patch release gets re-tagged.

Digest pinning replaces the tag with an immutable content hash:

```yaml
# Without pinning — mutable
image: nginx:1.25-alpine

# With pinning — immutable
image: nginx:1.25-alpine@sha256:d4f9c3b9f5a7c8b9a1b2c3d4e5f6a7b8c9d0e1f2
```

Renovate automatically pins digests when `docker:pinDigests` is enabled. It also opens `digest`-type PRs when the underlying digest changes for the same tag. This prevents accidental supply-chain issues from retagged images.

**Trade-off**: More PRs to review (or auto-merge), but every build is reproducible.

## End-to-End Workflow

Here is the practical cycle once Renovate is deployed:

```
Monday 05:00  — Cron triggers Renovate in daemon mode
               Renovate scans 8 repos, finds 3 outdated Docker images
               Opens 1 grouped PR: "chore(deps): update Docker dependencies"

PR includes:
  - nginx:1.25 → nginx:1.26@sha256:abc
  - postgres:16 → postgres:16@sha256:def
  - redis:7-alpine → redis:7-alpine@sha256:ghi

Monday 09:00  — You review the PR in Gitea
               Merge it to main branch

Monday 09:01  — Gitea webhook triggers your CI pipeline
               (optional — you can also skip CI and just merge)

Monday 09:05  — Watchtower picks up new digest on the host
               Pulls updated images, restarts containers
               Or you run: docker compose pull && docker compose up -d
```

The same cycle runs weekly. No more logging into each host to check image versions.

## Auto-Merge Safe Updates

For low-risk updates (digest changes, patch bumps), enable auto-merge in your Renovate config:

```json5
{
  packageRules: [
    {
      matchUpdateTypes: ["pin", "digest"],
      automerge: true,
    },
    {
      matchManagers: ["docker-compose", "dockerfile"],
      matchUpdateTypes: ["patch"],
      automerge: true,
    },
  ],
}
```

Works best with branch protection rules that require CI checks to pass before merge. Otherwise auto-merge pushes directly to your main branch.

## Conclusion

Renovate Bot transforms how you manage Docker dependencies in a homelab. Instead of manually checking image versions or relying entirely on runtime updates, Renovate keeps your git-tracked definitions current with automated pull requests. Pair it with Watchtower for a complete pipeline:

1. **Renovate** updates the definition (git → PR → merge)
2. **Watchtower** applies the update (merge → pull → restart)

The self-hosted setup with Gitea runs on minimal hardware — a single Docker container with a cron schedule. Shared presets keep per-repo configs under ten lines. Digest pinning locks every image to an immutable content hash.

In my homelab, Renovate manages 12 repositories with 30+ Docker Compose stacks. Weekly grouped PRs replace the tedious "check every image tag" chore. That's time saved for actually building things.

### See Also

- [Gitea Docker CI/CD Pipeline for Homelab](/posts/gitea-docker-ci-cd-homelab/)
- [Docker Watchtower — Automated Container Image Updates](/posts/docker-watchtower-auto-updates/)
- [Docker Compose Production Patterns](/posts/docker-compose-production-patterns/)
- [GitOps Patterns for Homelab Infrastructure](/posts/ansible-homelab-automation/)
