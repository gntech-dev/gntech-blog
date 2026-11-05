---
title: "GNTECH Infrastructure Part 12: Validate the Boundaries and Hand Over Operations"
description: "Turn the hybrid infrastructure series into a repeatable acceptance review with allowed and denied paths, recovery evidence, change gates, and an operations handoff."
date: 2026-11-05T18:00:00-04:00
draft: false
ShowToc: true
tags: [gntech-infrastructure, security, operations, homelab, runbooks]
keywords: [hybrid infrastructure acceptance, security validation, operational handoff, change control]
summary: "Build an evidence-based acceptance matrix for network isolation, authenticated administration, restore readiness, and alert delivery."
cover:
  image: "/images/posts/gntech-infrastructure-part-12/featured.webp"
  alt: "Open operations binder and laptop beside a compact server rack under blue and amber lighting."
  caption: "AI-generated editorial artwork."
  relative: false
---

**Series** · [GNTECH Infrastructure Deployment Series](/gntech-infrastructure-series/) · **Part 12 of 12** · [Previous: Part 11 — Monitoring](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/)

The earlier installments describe individual building blocks. Operating them together requires a second view. Which clients may reach management? What happens when identity is unavailable? Can someone restore a guest using only the recovery kit? Who receives the alert?

This final installment is an acceptance procedure for a reference environment. The tables begin untested. Fill them with observations from your own system. Publishing the series does not establish that a live GNTECH deployment has passed these checks.

## 1. Freeze the scope before testing

Write down the configuration revision, software versions, test source networks, intended destinations, and approved test window. Use a disposable application and an isolated restored guest for disruptive checks. Keep console or another independent recovery path available before changing routing or authentication.

Assign one person to own each test and another to review its evidence where possible. For a single-person homelab, make the review a separate pass after the test. Record a result as pass, fail, or untested. Record an intentional exception with an owner, reason, compensating control, and expiry.

| Boundary | Required observation | Evidence to preserve |
| --- | --- | --- |
| Authorized admin to management | Intended service works through the chosen route and identity control | Client context, destination, time, and application result |
| Household or IoT client to management | Prohibited application connection fails for the expected policy reason | Source network, exact destination/port, relevant firewall log or counter |
| Unauthenticated browser to admin app | Access authentication is required before reaching application content | Fresh browser session and Access decision |
| Authenticated but unauthorized identity | Application content remains inaccessible | Identity category and Access decision, with personal details redacted |
| Recovery host to off-site backup | Selected snapshot restores and boots in isolation | Snapshot time, task IDs, marker comparison, elapsed time |
| Failed or stale monitored service | Alert fires and reaches the designated receiver | Trigger, rule state, receiver arrival, resolution |

A timeout by itself does not prove segmentation. A powered-off target, DNS error, or wrong route can produce the same symptom. Pair a denied test with a permitted test against a known-working target and examine the enforcing device.

## 2. Capture one network test from each side

Use the hostname and port of a disposable HTTPS application you control. The sample hostname is a placeholder. Run the same probe from the authorized management client and the restricted client, then compare the results with the policy you intended.

```bash
target=admin.example.com
date -u +%FT%TZ
getent ahosts "$target"
curl --connect-timeout 5 --max-time 15 --silent --show-error \
  --output /dev/null --write-out 'HTTP=%{http_code} remote=%{remote_ip}\n' \
  "https://$target/"
```

Record the command's exit status immediately with `echo $?`. Keep TLS verification enabled and install your organization's CA certificate where needed. An HTTP redirect to an identity login page is evidence that the authentication edge is reachable. Continue with a browser to verify authorization and application behavior.

If split DNS is in use, confirm whether each client resolves the same destination. Test the intended private origin path separately from the public Access hostname. Otherwise, a restricted client reaching the identity edge could be mistaken for direct management access. Validate both IPv4 and IPv6 when both protocols are enabled.

Revisit [Part 04's isolation model](/posts/2026-11-01-gntech-infrastructure-part-04-proxmox-firewall-isolation/) and [Part 05's scoped routes](/posts/2026-11-02-gntech-infrastructure-part-05-home-to-hetzner-connectivity/) when a probe uses an unexpected path.

## 3. Test identity decisions and recovery independently

Use fresh browser sessions for an authorized identity and an authenticated identity outside the allowed group. Verify the actual application content each can reach. Cloudflare's policy tester helps review existing identities using their most recent Access login context. Follow it with an actual application test for the browser and device state you intend to support.

Record how an operator reaches the console or recovery network if the primary identity provider or tunnel cannot be used. Exercise that independent path during an approved test window. Keep recovery credentials in a controlled location accessible without the service being recovered. Review access to that location as part of the handoff.

Use [Part 08](/posts/2026-11-03-gntech-infrastructure-part-08-cloudflare-zero-trust/) for the tunnel and Access checks. Use [Part 10's off-site restore procedure](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) for restore evidence. Successful authentication does not establish restore readiness, and a successful restore does not establish the correct access policy.

## 4. Rehearse a change with a stop condition

Pick one reversible change to the disposable application's Compose configuration. Save its known-good files and exact image references before editing. In its project directory, validate the proposed configuration before applying it.

```bash
docker compose config --quiet
docker compose ps
```

Review any override files using the same ordered `-f` arguments that deployment will use. Configuration validation checks the resolved model. Application startup, data compatibility, and client behavior still need their own tests.

Apply the reviewed change with `docker compose up -d`, check the service state, and repeat its HTTPS and data checks. If the acceptance checks fail, restore the known-good files and image references, apply them, and repeat those checks. Plan a compatible data restore if the change migrates a data format. Restarting a container does not apply edited Compose settings.

| Change gate | Record before proceeding |
| --- | --- |
| Before change | Owner, revision, affected service, expected behavior, recovery point, rollback steps |
| After deployment | Service state, client result, data check, error logs |
| Stop condition | Exact failed check or maximum permitted interruption |
| After rollback | Restored revision and repeated client/data checks |

Keep full rendered Compose configuration private because interpolation can include secrets. For a public write-up, publish a sanitized excerpt and describe what was redacted.

## 5. Verify alert delivery and hand over the evidence

Repeat the controlled stale-data and exporter-outage tests from [Part 11](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/). Record the alert entering firing state, arrival at the designated receiver, and resolution after recovery. When testing a notification route, use an approved receiver and tell the person handling it that the alert is a drill.

Create an operations worksheet in your private documentation. Each row should have a named owner, a review date, and a link to the latest evidence.

| Runbook | Minimum contents |
| --- | --- |
| Access recovery | Console path, local authentication, credential retrieval, revocation process |
| Network recovery | Bridge/VLAN inventory, route ownership, saved configuration, recovery access |
| Backup recovery | Datastore/namespace, trusted TLS identity, key location, tested restore sequence |
| Monitoring | Expected jobs, freshness thresholds, notification receiver, silence expiry |
| Updates | Version inventory, release review, maintenance window, rollback and data restore |
| Incident handoff | Observed impact, timeline, current revision, actions taken, next owner |

Preserve task logs and screenshots with timestamps. Remove session tokens, credentials, public addresses that identify your environment, and personal information before sharing excerpts. Keep the unredacted evidence under appropriate access controls.

## 6. Decide whether the environment is ready

Review the matrix against the frozen scope. Failed required checks need a corrective action and a retest. Untested checks remain open. When accepting an exception, record who accepted it and when it must be reviewed.

The handoff is complete when the next operator can find the current configuration, reach recovery access, identify the latest usable backup, and follow an alert to an actionable runbook. Re-run the affected checks after changes to routing, identity, storage, or notification delivery.

This closes the twelve-part publication sequence. The next follow-up will audit the series links, assumptions, and validation gaps across all twelve installments.

## Official references

- [Cloudflare Access policy testing](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/policy-management/)
- [Docker Compose configuration validation](https://docs.docker.com/reference/cli/docker/compose/config/)
- [Docker Compose production changes](https://docs.docker.com/compose/how-tos/production/)
- [Docker Compose restart behavior](https://docs.docker.com/reference/cli/docker/compose/restart/)
- [Proxmox VE backup and restore](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
