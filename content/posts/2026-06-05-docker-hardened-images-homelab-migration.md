---
title: "Docker Hardened Images — Verify Compatibility Before Migration"
description: "Compare exact image digests, inspect migration requirements, and test application recovery before adopting a hardened image."
date: 2026-06-05T16:00:00-04:00
tags:
  - docker
  - security
  - devops
  - homelab
  - containers
keywords:
  - Docker Hardened Images migration
  - image digest scanning
  - application compatibility
summary: "Compare exact image digests, inspect migration requirements, and test application recovery before adopting a hardened image."
lastmod: 2026-10-31
---

A hardened image can reduce included components and improve supply-chain evidence. It still needs to meet the application's runtime, storage, and recovery requirements. Treat migration as an application change rather than a search-and-replace of registry names.

## Verification status

| Area | Evidence and limits |
|---|---|
| Source review | Docker's migration documentation reviewed on October 31, 2026. |
| Measurements | No digest-pinned CVE comparison or application migration was executed in this audit. |
| Correction | Earlier fixed vulnerability counts, percentage reductions, guessed image paths, and universal drop-in/non-root claims are removed. |

## Select an image from the current catalog

Start with [Docker's migration documentation](https://docs.docker.com/dhi/migration/) and follow the catalog and access instructions for the image you need. Record its exact registry, repository, tag, digest, architecture, edition, and license/access requirements. Do not infer an image path by prepending `dockerhardened/` to a Docker Official Image name.

Check the image-specific guide for its user ID, ports, filesystem permissions, entrypoint, environment variables, data directory, and available tools. A non-root container is not necessarily using a rootless Docker daemon. A distroless variant may omit the shell or utilities used by your existing health check and maintenance commands.

## Compare evidence for exact digests

Use your selected scanner's documented installation method. Scan the deployed digest and the candidate digest with the same scanner version, vulnerability database, architecture, and severity policy. Save the timestamp, SBOM, package findings, and any vendor vulnerability statements.

A CVE count changes as images and vulnerability databases change. It is not evidence that every finding is exploitable or that an image with fewer findings is risk-free. Check the applicability and remediation of individual findings. Provenance and signatures support checks of origin and build evidence; they do not prove application correctness or absence of vulnerabilities.

## Rehearse the application migration

1. Export the current Compose configuration and record image digests, required secrets, persistent data, and a rollback target.
2. Make an application-consistent backup. For PostgreSQL, follow the [tested dump and isolated recovery lab](/posts/2026-06-01-docker-database-backup-automation-pgdump-cron/).
3. Restore into an isolated test deployment with fresh volumes and the candidate image. Review ownership and permissions before changing them; do not apply guessed recursive `chown` operations to the original data.
4. Adapt health checks to tools the image actually supplies. Test login, writes, reads, migrations, extensions, integrations, and recovery.
5. Plan a maintenance window and a tested rollback. Database migrations may prevent an older application image from using newly upgraded data.

Keep the original image and recovery materials until the new deployment and rollback exercise have passed. An automatic image updater is not a substitute for this validation.

## Record a useful result

Publish the exact versions/digests, configuration changes, observed behavior, and remaining limits. Do not publish a generic “95% fewer CVEs” result without the scan evidence and scope needed to reproduce it.

Continue with [image security and distroless design](/posts/2026-06-05-docker-image-security-hardening-distroless/) and [container security hardening](/posts/2026-05-15-docker-container-security-hardening/).
