---
title: "NGINX Security Advisory Verification — Correction to the Poolslip Post"
description: "Correction of an unsupported nginx-poolslip advisory, with steps to verify official NGINX advisories, identify running versions, and validate an update."
date: 2026-05-22T12:00:00-04:00
tags:
  - nginx
  - security
  - docker
  - homelab
  - networking
keywords:
  - NGINX security advisory verification
  - NGINX version checks
  - NGINX container updates
summary: "Correction of an unsupported nginx-poolslip advisory, with steps to verify official NGINX advisories, identify running versions, and validate an update."
lastmod: 2026-10-30T12:00:00-04:00
---

> **Correction — October 30, 2026:** The original version of this post described an alleged “nginx-poolslip” zero-day as confirmed and unpatched. That claim was not supported by an identified vendor advisory. The current official NGINX advisory index does not list that name. This does not prove that no private report exists, but the original article did not justify its certainty. Its claimed exploit details, affected-version table, and workaround claims have been withdrawn.

Use the vendor's published advisories to decide whether your actual NGINX package needs an update. Do not treat this post's historical title or publication date as a current vulnerability notification.

## 1. Identify the Running Build

For a host installation:

```bash
nginx -v
nginx -V
```

For a container, replace `nginx` with its actual name:

```bash
docker exec nginx nginx -v
docker exec nginx nginx -V
docker inspect nginx --format '{{.Config.Image}}'
```

Record the package source, image digest where applicable, configured modules, and deployed version. Distribution packages may include backported fixes without adopting the upstream version number.

## 2. Match a Published Advisory

Read the [official NGINX security advisories](https://nginx.org/en/security_advisories.html) and the relevant distribution or image publisher's security notice.

For example, the vendor index identifies CVE-2026-42945 as a buffer overflow in `ngx_http_rewrite_module`, with upstream fixes in 1.31.0 and 1.30.1. The original article's characterization of 1.31.0 as a stable release was also incorrect: NGINX uses separate mainline and stable branches.

Check the advisory's affected versions and configuration prerequisites. Do not assume a WAF, rate limit, disabled `server_tokens`, or an image tag alone proves protection against a memory-safety issue.

## 3. Update Through Your Existing Deployment

Back up your configuration and verify your rollback plan before an update. Choose a publisher-supported version or digest that includes the required fixes. Avoid downgrading to an arbitrary older release as a generic mitigation.

For an existing Compose deployment, after reviewing its image reference, replace `nginx` below with the Compose **service name**:

```bash
docker compose config --quiet
docker compose pull nginx
docker compose run --rm --no-deps nginx nginx -t
docker compose up -d --no-deps nginx
docker compose exec nginx nginx -t
docker compose exec nginx nginx -v
docker compose logs --tail=100 nginx
```

The pre-deployment test uses the new image and the service's configured mounts. It may require running upstream services if the configuration resolves their names. Adapt the validation command for images with a custom entrypoint.

Afterward, test the externally used HTTPS URL and upstream application behavior. Confirm the running binary version and publisher advisory status. Keep a record of the applied image digest or package revision.

## References

- [NGINX security advisories](https://nginx.org/en/security_advisories.html)
- [NGINX release branches and downloads](https://nginx.org/en/download.html)
