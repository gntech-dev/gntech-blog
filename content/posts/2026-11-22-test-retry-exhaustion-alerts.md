---
title: "Test Retry Exhaustion Alerts Before Trusting Them"
description: "Use promtool fixtures to test pending delays, counter resets, failed scrapes and a missing expected worker target."
date: 2026-11-22T06:00:00-04:00
draft: false
ShowToc: true
tags: [prometheus, alerting, testing, reliability]
keywords: [promtool alert tests, retry exhaustion alert, counter reset, missing target]
summary: "Three alert rules and six synthetic test groups distinguish request failures from monitoring gaps."
cover:
  image: "/images/posts/retry-alert-tests/featured.webp"
  alt: "A brass laboratory balance holding a blue glass bead and an amber bell on a warmly lit homelab desk."
  caption: "AI-generated conceptual editorial artwork; not an alert dashboard."
  relative: false
---

An exhaustion counter can produce the right-looking graph while its alert still fires too early, confuses a restart with a failure, or goes silent when a target disappears. Test those cases with synthetic samples before loading the rules into a monitoring service.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) uses offline `promtool` tests. It does not run a worker, scrape a database or send notifications. The lab pins promtool 3.5.0 as a reproducible historical test baseline; it is not a production server version recommendation. Before rollout, rerun the suite with the tool version matching your deployed Prometheus release.

Preparation status: the checksum-verified tool passed three-rule validation and all 19 alert assertions across six groups. A deliberate pending-delay regression was rejected by the suite. No live Prometheus/Alertmanager route or GNTECH deployment was exercised.

## 1. Define the three different failures

| Alert | Meaning |
| --- | --- |
| `RetryExhausted` | A worker reported a positive increase in exhausted logical requests within five minutes. |
| `RetryTargetDown` | Prometheus still has the target, but its scrape reports `up = 0`. |
| `RetryTargetMissing` | The exact target expected by this lab has no current `up` series. |

The counter is `gntech_tx_requests_finished_total{outcome="exhausted"}`. It counts logical requests that consumed their retry budget, not every failed attempt. Initialize this outcome series to zero in the exporter so a never-used label can still be observed.

The sample inventory contains one expected target: job `retry-metrics-lab`, instance `127.0.0.1:9815`. Change both the rules and test expectations when changing that inventory. A job-wide `absent(up{job="..."})` cannot identify one missing instance while another instance remains present.

## 2. Install the pinned offline tool

Use Linux x86-64 with Bash, curl, tar and sha256sum. Create a fresh working directory. The download includes Prometheus, but only `promtool` is extracted; no server is started.

```bash
mkdir retry-alert-lab
cd retry-alert-lab
mkdir bin
(
  set -euo pipefail
  cd bin
  version=3.5.0
  archive="prometheus-${version}.linux-amd64.tar.gz"
  release="https://github.com/prometheus/prometheus/releases/download/v${version}"
  curl --fail --location --retry 3 "$release/$archive" -o "$archive"
  curl --fail --location --retry 3 "$release/sha256sums.txt" -o sha256sums.txt
  awk -v file="$archive" '$2 == file { print; found = 1 } END { if (!found) exit 1 }' \
    sha256sums.txt > selected-checksum.txt
  sha256sum --check selected-checksum.txt
  tar -xzf "$archive" --strip-components=1 "prometheus-${version}.linux-amd64/promtool"
  ./promtool --version
)
```

Continue only after checksum verification succeeds. Keep the version and check output with the test report.

## 3. Save the rules

Save as `alerts.yml` in the working directory, beside the future test file.

```yaml
groups:
- name: retry-worker
  interval: 1m
  rules:
  - alert: RetryExhausted
    expr: sum by (job, instance) (increase(gntech_tx_requests_finished_total{job="retry-metrics-lab",outcome="exhausted"}[5m])) > 0
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: Retry budget exhausted
  - alert: RetryTargetDown
    expr: up{job="retry-metrics-lab"} == 0
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: Retry worker scrape failed
  - alert: RetryTargetMissing
    expr: absent(up{job="retry-metrics-lab",instance="127.0.0.1:9815"})
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: Expected retry worker target missing
```

The exhaustion rule uses `increase` on each counter series before aggregation, retaining `job` and `instance`. Counter decreases are treated as resets. A reset to zero alone should not invent a new exhaustion. An increase after that reset must still be detected.

The `for` clause requires a condition to remain active across evaluations before firing. Here the exhaustion and scrape-failure alerts wait one minute; the missing-target alert waits two. These are lab timings, not universal paging thresholds. The missing-target rule explicitly encodes one expected target and derives its labels from the exact selectors.

## 4. Save synthetic inputs and expected alerts

Save as `tests.yml`. Values start at time zero and advance at one-minute intervals. For example, `1+0x12` means an initial 1 followed by twelve additional unchanged samples. `_` represents a missing sample; `stale` explicitly ends a series' current presence.

```yaml
rule_files:
- alerts.yml
evaluation_interval: 1m
tests:
- name: healthy worker
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x12
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 0+0x12
  alert_rule_test:
  - eval_time: 4m
    alertname: RetryExhausted
    exp_alerts: []
  - eval_time: 4m
    alertname: RetryTargetDown
    exp_alerts: []
  - eval_time: 4m
    alertname: RetryTargetMissing
    exp_alerts: []
- name: exhaustion pending firing then clears
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x12
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 0 1+0x11
  alert_rule_test:
  - eval_time: 1m
    alertname: RetryExhausted
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryExhausted
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Retry budget exhausted
  - eval_time: 10m
    alertname: RetryExhausted
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryTargetDown
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryTargetMissing
    exp_alerts: []
- name: reset without a new exhaustion
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x12
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 10 10 0+0x10
  alert_rule_test:
  - eval_time: 4m
    alertname: RetryExhausted
    exp_alerts: []
- name: new exhaustion after reset
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x12
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 10 10 0 1+0x9
  alert_rule_test:
  - eval_time: 3m
    alertname: RetryExhausted
    exp_alerts: []
  - eval_time: 4m
    alertname: RetryExhausted
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Retry budget exhausted
- name: scrape fails but target still exists
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1 0+0x11
  alert_rule_test:
  - eval_time: 1m
    alertname: RetryTargetDown
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryTargetDown
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Retry worker scrape failed
  - eval_time: 2m
    alertname: RetryTargetMissing
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryExhausted
    exp_alerts: []
- name: target disappears with a stale marker
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1 stale _x10
  alert_rule_test:
  - eval_time: 2m
    alertname: RetryTargetMissing
    exp_alerts: []
  - eval_time: 3m
    alertname: RetryTargetMissing
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Expected retry worker target missing
  - eval_time: 3m
    alertname: RetryTargetDown
    exp_alerts: []
  - eval_time: 3m
    alertname: RetryExhausted
    exp_alerts: []
```

| Group | Regression it catches |
| --- | --- |
| Healthy worker | Unexpected firing when the counter is zero and scrapes succeed. |
| Exhaustion, then quiet | Firing during the pending minute, failure to fire after it, or failure to clear after the increase leaves the window. |
| Reset without a new exhaustion | Treating a process restart as a new request failure. |
| Exhaustion after reset | Suppressing a real increment because the counter recently restarted. |
| Failed scrape | Confusing an existing target with a removed target. |
| Stale target | Assuming `up == 0` also covers a target with no current series. |

`exp_alerts: []` asserts no **firing** alerts for that name at that time. It does not by itself prove the alert is absent rather than pending. That is why the fixture pairs a no-firing check with a later expected firing check. Expected labels and annotations are part of the contract too.

The stale marker gives the test an explicit disappearance time. A live service-discovery removal and missing scrape samples have their own staleness/lookback behavior; a single missed sample does not necessarily remove an instant-vector series immediately. This test does not simulate every discovery implementation.

## 5. Run the checks and prove a failure is visible

```bash
./bin/promtool check rules alerts.yml
./bin/promtool test rules tests.yml
```

Expect rule validation to find three rules and the test command to report success. The suite contains 19 firing/non-firing assertions. It runs on synthetic timestamps, so it does not wait ten wall-clock minutes for a ten-minute evaluation.

As a controlled regression exercise, back up `alerts.yml`, change only `RetryExhausted` from `for: 1m` to `for: 0m`, then rerun the tests. The no-firing assertions at 1m and 3m in the two exhaustion groups should fail. Restore the original file and require a passing run again. Do not change expectations merely to make a changed rule pass; first decide whether the behavior change is intended.

An empty exhaustion result is not proof of health. Both the failed-scrape and stale-target cases deliberately have no exhaustion counter input, so a separate target alert must explain the monitoring gap. These three rules still do not detect a missing application counter while `up` remains 1; that needs a separate metric-presence rule and test.

## 6. Promote the tested rules deliberately

Keep the rule file and test file together in version control. Run the tests with the deployed tool version in CI, and inspect any changed labels, pending timings or range windows as reviewable behavior. These rules use a one-minute group interval; production scrape and evaluation intervals affect when evidence becomes available.

Before enabling notifications, validate the complete Prometheus configuration, load the reviewed rules in an isolated environment, confirm the actual target labels, and test an alert through the intended Alertmanager route. Offline success validates expression evaluation against these fixtures. It does not validate service discovery, credentials, notification delivery or operator response.

For rollback, retain the preceding reviewed rule file and its passing fixture set, restore that version through your normal configuration process, and revalidate before reload. This offline lab changes no running monitoring service; its files can be removed when the test report has been retained.

## References

Official documentation reviewed November 22, 2026:

- [Rule unit-test file format](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
- [Alert rule pending and firing behavior](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Counter increases and absent series](https://prometheus.io/docs/prometheus/latest/querying/functions/)
- [Staleness and instant-vector lookback](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Prometheus 3.5.0 release assets](https://github.com/prometheus/prometheus/releases/tag/v3.5.0)
