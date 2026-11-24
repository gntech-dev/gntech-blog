---
title: "Test Alertmanager Routes Before Changing Team Notifications"
description: "Use amtool to verify ordered sibling routes, continue behavior and fallback selection against an explicit matrix of alert labels."
date: 2026-11-24T17:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, reliability]
keywords: [amtool route test, Alertmanager continue, routing fallback, team alert routing]
summary: "Seven offline routing checks catch missing destinations, unintended short circuits and incorrect fallback assumptions before a configuration change."
cover:
  image: "/images/posts/alertmanager-routing/featured.webp"
  alt: "Three brass sorting trays with blue and amber envelopes on a homelab desk beside a server and laptop at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or routing diagram."
  relative: false
---

A valid Alertmanager configuration can send an alert to the wrong team. A new route placed above an existing one may stop traversal early. Removing `continue: true` can silently drop a second destination. Neither mistake requires invalid YAML.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) turns a small routing policy into executable expectations. It uses `amtool config routes test` with a local file, so no Alertmanager server, receiver credential or paging destination is needed.

Preparation status: configuration validation, all seven routing checks and two deliberate regression checks passed with checksum-verified amtool 0.28.1. That is a historical offline lab baseline, not a current production version recommendation. Repeat the tests with the tool version matching the intended deployment. No live configuration reload, notification delivery or GNTECH rollout was exercised.

## 1. Write the policy before the route tree

For this synthetic policy, security alerts belong only to the security receiver. Platform alerts go to the platform receiver and also reach the critical receiver when their severity is critical. Other critical alerts go to critical. Everything else uses fallback.

These are example ownership decisions, not a universal escalation policy. In particular, the security rule deliberately prevents a matching critical alert from reaching the later critical receiver. Review that choice with the teams responsible for your real routes.

| Ordered child | Match | Receiver | Continue to later siblings? |
| --- | --- | --- | --- |
| 1 | `team="security"` | `security` | No, the default. |
| 2 | `team="platform"` | `platform` | Yes. |
| 3 | `severity="critical"` | `critical` | No, the default. |

Every alert enters the root route, which has no matchers. Children are evaluated in order. A matching child normally stops subsequent sibling matching; `continue: true` allows matching to continue with later siblings. It does not return to earlier siblings or force every later route to match.

The root receiver is a fallback when none of its children match. It is not automatically an extra destination for every alert passing through the root. This example has one level of children so that each expectation is easy to inspect.

## 2. Install the isolated test tool

Use Linux x86-64, Bash, curl, tar and sha256sum. Run as an ordinary user from a fresh directory.

```bash
mkdir route-lab
cd route-lab
mkdir bin
(
  set -euo pipefail
  cd bin
  version=0.28.1
  archive="alertmanager-${version}.linux-amd64.tar.gz"
  release="https://github.com/prometheus/alertmanager/releases/download/v${version}"
  curl --fail --location --retry 3 "$release/$archive" -o "$archive"
  curl --fail --location --retry 3 "$release/sha256sums.txt" -o sha256sums.txt
  awk -v file="$archive" '$2 == file { print; found = 1 } END { if (!found) exit 1 }' \
    sha256sums.txt > selected-checksum.txt
  sha256sum --check selected-checksum.txt
  tar -xzf "$archive" --strip-components=1 \
    "alertmanager-${version}.linux-amd64/amtool"
  ./amtool --version
)
```

Continue only after checksum verification succeeds. The routing commands below always specify `--config.file`; they inspect the local file rather than fetching a server's configuration. Downloading the release requires network access, but the routing tests do not need a running monitoring service.

## 3. Save the routing fixture

Save as `alertmanager.yml`:

```yaml
route:
  receiver: fallback
  group_by: [alertname, instance]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
  - receiver: security
    matchers: ['team="security"']
  - receiver: platform
    matchers: ['team="platform"']
    continue: true
  - receiver: critical
    matchers: ['severity="critical"']
receivers:
- name: fallback
- name: security
- name: platform
- name: critical
```

The four receivers intentionally have no integrations. They are names used to test selection; starting Alertmanager with this file would not page anyone. Do not replace a live file with this fixture.

Grouping timings are ordinary example values, not observations about delivery latency. The routing test does not wait for group timers or send a notification. Multiple integrations inside one receiver are a separate concern from selecting multiple receivers through sibling routes.

## 4. Define the label matrix

Each test adds `alertname=RoutingLab`. The remaining labels and expected destinations are:

| Case | Additional labels | Expected receiver names |
| --- | --- | --- |
| Platform critical | `team=platform severity=critical` | `platform,critical` |
| Platform warning | `team=platform severity=warning` | `platform` |
| Security critical | `team=security severity=critical` | `security` |
| Other critical | `team=other severity=critical` | `critical` |
| Other warning | `team=other severity=warning` | `fallback` |
| Missing team | `severity=critical` | `critical` |
| Missing team and severity | None | `fallback` |

The missing-label cases make a production assumption visible: an alert without a team can still reach critical or fallback. If that would be unacceptable, add an explicit ownership policy and test it rather than assuming every producer always supplies the label.

Save as `test-routes.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
config="${1:-alertmanager.yml}"
./bin/amtool check-config "$config"
check() {
  local expected="$1"
  shift
  ./bin/amtool config routes test --config.file="$config" \
    --verify.receivers="$expected" alertname=RoutingLab "$@"
}
check platform,critical team=platform severity=critical
check platform team=platform severity=warning
check security team=security severity=critical
check critical team=other severity=critical
check fallback team=other severity=warning
check critical severity=critical
check fallback
printf '%s\n' 'PASS: all seven route expectations matched'
```

Run it from this lab directory:

```bash
bash test-routes.sh
```

Require configuration validation, all seven receiver results and the final PASS line. The pinned command returns exit status 1 when `--verify.receivers` does not match the resolved receivers. With `set -e`, a mismatch stops the script before it can print success. Receiver names are supplied as a comma-separated list when more than one is expected.

This combines a structural check with behavioral expectations. `amtool check-config` can accept a routing tree whose ownership behavior is wrong; the matrix describes the policy the change must preserve.

## 5. Prove the checks detect a regression

Create a separate copy with continuation disabled:

```bash
sed 's/continue: true/continue: false/' alertmanager.yml > no-continue.yml
./bin/amtool check-config no-continue.yml
./bin/amtool config routes test --config.file=no-continue.yml \
  --verify.receivers=platform,critical \
  alertname=RoutingLab team=platform severity=critical
```

The syntax check should succeed, but the routing command should print `platform`, report an expected-receiver mismatch and exit with status 1. This is the intended negative result: critical was lost because the platform route stopped sibling traversal.

For a second check, copy the original file to `critical-first.yml` and move the entire critical child block above the security and platform child blocks. Keep the original block's default `continue: false`, and leave the rest of the file unchanged. Check syntax, then repeat the same expectation:

```bash
./bin/amtool check-config critical-first.yml
./bin/amtool config routes test --config.file=critical-first.yml \
  --verify.receivers=platform,critical \
  alertname=RoutingLab team=platform severity=critical
```

Expect `critical` and exit status 1. The broad severity route now matches first and stops traversal before platform is considered. A route reorder can change ownership even when every individual matcher stays the same.

These failures establish that the tests reject the two intended mistakes. Inspect the mismatch output; a missing file or malformed configuration is not evidence of the same regression. Preserve the original `alertmanager.yml` and run `bash test-routes.sh` again to confirm the reviewed policy still passes.

## 6. Use the matrix during a real change

Keep the routing expectations with the configuration in version control. Add representative label sets for each affected team, overlaps, unowned alerts and newly introduced labels. Before changing a route, write down which matrix rows should change and why. An unexpected destination change deserves review even when configuration validation succeeds.

For a larger tree, test the complete intended configuration with the matching tool version. Extend coverage for nested children, regular-expression matchers, inherited settings and time-based policies as they are introduced; this seven-row fixture does not validate those features. Treat time intervals, silences, inhibition, grouping and delivery as separate checks. A selected receiver name does not prove that a notification is allowed or delivered.

After offline checks, test a disposable alert through the intended running route and independently verify each real destination. That exercise must account for authentication, connectivity, suppression, timers and downstream acceptance. This article performs none of those live operations.

The lab makes no service or state changes. Keep the fixture and test results if useful, then remove the directory when finished. For a separately authorized production change, retain the preceding reviewed configuration and its passing matrix so your normal rollback restores both configuration and expected behavior.

## Official references

Reviewed November 24, 2026:

- [Alertmanager routing and continuation](https://prometheus.io/docs/alerting/latest/configuration/)
- [Pinned route configuration semantics](https://github.com/prometheus/alertmanager/blob/v0.28.1/docs/configuration.md)
- [Official amtool routing usage](https://github.com/prometheus/alertmanager/blob/v0.28.1/README.md)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
