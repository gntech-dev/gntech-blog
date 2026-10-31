---
title: "Vaultwarden Docker Deployment — Self-Hosted Password Manager Guide"
description: "Deploy a small Vaultwarden instance behind a private HTTPS proxy, close registration after bootstrap, and verify recovery of the complete data directory."
date: 2026-05-17T07:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [docker, security, homelab, linux]
summary: "A staged Vaultwarden setup with explicit HTTPS, signup and recovery boundaries."
---

Vaultwarden is an independent implementation of the Bitwarden client API. Review client compatibility and release notes rather than assuming full feature parity or a fixed memory footprint.

This guide does not rely on the earlier unsupported claims about Bitwarden ending its free tier or a specific security incident.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Upstream deployment, admin, WebSocket and backup documentation reviewed on October 31, 2026. |
| Preparation checks | Compose structure and Bash syntax checked. |
| Runtime | No vault, proxy, SMTP, client-sync or restore operation executed for this revision. |
| Scope | Proposed private bootstrap; use disposable test credentials until recovery is verified. |

## 1. Prepare HTTPS and a new project

Use a supported Docker host, a reviewed Vaultwarden image tag or digest, and an HTTPS reverse proxy with a valid certificate. Keep the proxy reachable only by the intended test clients during bootstrap.

In this example the proxy runs on the same host and forwards to 127.0.0.1:18082. A proxy container's localhost is different: use a deliberately shared network for that design. Follow the [upstream deployment examples](https://github.com/dani-garcia/vaultwarden/wiki/Deployment-examples).

```bash
vault_lab_dir=$(mktemp -d -t vaultwarden-lab.XXXXXX)
cd "$vault_lab_dir" || exit 1
umask 077
mkdir data
read -r -p 'Reviewed vaultwarden/server image tag or digest: ' VAULTWARDEN_IMAGE
read -r -p 'Private HTTPS vault URL: ' VAULTWARDEN_DOMAIN
printf 'VAULTWARDEN_IMAGE=%s\nVAULTWARDEN_DOMAIN=%s\nSIGNUPS_ALLOWED=true\n' \
  "$VAULTWARDEN_IMAGE" "$VAULTWARDEN_DOMAIN" > .env

cat > compose.yaml <<'EOF'
services:
  vaultwarden:
    image: ${VAULTWARDEN_IMAGE:?Set the reviewed image}
    environment:
      DOMAIN: ${VAULTWARDEN_DOMAIN:?Set the HTTPS vault URL}
      SIGNUPS_ALLOWED: ${SIGNUPS_ALLOWED:?Set the signup policy}
      INVITATIONS_ALLOWED: "false"
    volumes:
      - ./data:/data
    ports:
      - "127.0.0.1:18082:80"
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"
EOF

docker compose config --quiet
docker compose up -d
docker compose logs --tail=60 vaultwarden
```

This deliberately leaves registration open only for the private bootstrap window. No admin token, SMTP or public exposure is configured.

## 2. Create one test account and close registration

Open the private HTTPS URL, confirm the certificate, and create a disposable test account. Close registration before expanding access:

```bash
sed -i 's/^SIGNUPS_ALLOWED=true$/SIGNUPS_ALLOWED=false/' .env
docker compose up -d
docker compose logs --tail=30 vaultwarden
```

Verify a second uninvited registration is rejected. Configure a supported client for the HTTPS URL, create a test item, and verify a second client can synchronize it.

Current WebSocket notifications use the main HTTP service; the old separate-port/WEBSOCKET_ENABLED recipe is obsolete for current releases. Verify your proxy's WebSocket handling against the [upstream notification guidance](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-WebSocket-notifications).

## 3. Enable administration only if needed

The admin endpoint is not configured in this example. If required, follow [upstream admin-page guidance](https://github.com/dani-garcia/vaultwarden/wiki/Enabling-admin-page), use the supported hashed-token format, and protect admin access separately.

Preserve dollar signs correctly when transporting a hash through Compose or an environment file. Do not assume a token controls user vault passwords or resets an encrypted vault's master password.

Settings saved through administration may override environment settings. Inspect the effective configuration after changes. Test SMTP delivery before relying on invitation or recovery workflows.

A Cloudflare Tunnel is a transport path, not proof that a site is private. Confirm access policy and Bitwarden-client compatibility before placing an identity gateway in front of the vault.

## 4. Back up the complete recovery set

Follow [Backing up your vault](https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault). A SQLite copy alone omits attachments, sends and other required state.

For a simple offline backup, stop Vaultwarden cleanly, archive the complete data directory with its permissions, and restart it. For online backups, use a supported consistent SQLite procedure and coordinate the other files. Do not copy only db.sqlite3 from a running WAL-mode database or discard WAL files blindly.

Keep Compose settings, secrets and the exact image reference with the recovery materials. Encrypt off-site copies and preserve credentials outside the Docker host. Separate volumes on the same host are not independent off-site protection.

## 5. Prove recovery without overwriting the live vault

Restore into a new data directory and separate test instance. Preserve the original and use an isolated address. Check the account, a test item, attachments, organization state if applicable, and client synchronization.

Confirm ownership against the selected image; do not hard-code chown 1000:1000 without evidence. Record the restore result before scheduling retention or deleting old archives.

Do not automate updates and then assume an older image can read a migrated database. Preserve a matching pre-update backup, review release notes, and test rollback on a separate instance.

## Stop the test

```bash
docker compose down
```

The bind-mounted data remains. Do not put real passwords into the instance until access controls, account security, backup and recovery have been verified.

## Continue reading

- [Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — Understand mounts, environment and proxy boundaries.
- [Restic recovery](/posts/2026-05-19-restic-docker-backup-strategy/) — Protect prepared recovery files.
