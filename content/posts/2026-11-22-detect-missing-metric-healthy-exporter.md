---
title: "Detect a Missing Metric While the Exporter Is Still Up"
description: "Use per-target PromQL matching to detect an absent retry outcome counter without confusing zero values, failed scrapes or healthy peers."
date: 2026-11-22T18:00:00-04:00
draft: false
ShowToc: true
tags: [prometheus, monitoring, alerting, reliability]
keywords: [missing application metric, PromQL unless, exporter up metric missing, target matching]
summary: "A metric-presence rule with eight offline test groups, including two targets and deliberate matching regressions."
cover:
  image: "/images/posts/metric-presence/featured.webp"
  alt: "Two blue glass spheres and an empty central recess in a wooden tray beside a green beacon and homelab server."
  caption: "AI-generated conceptual editorial artwork; not a monitoring dashboard."
  relative: false
---

A successful scrape does not guarantee that every expected application metric is present. A worker can return HTTP successfully while an outcome counter disappears after a code change. If the remaining graphs show no failures, operators may mistake missing evidence for a healthy workload.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) adds a per-target metric-presence check. It focuses on a scrapeable exporter missing one expected series. Scrape failures, removed targets and retry exhaustion require their own checks.

Preparation status: one rule and all 11 alert assertions across eight groups passed with checksum-verified promtool 3.5.0. Two deliberate query regressions were rejected. That version is a historical offline test baseline, not a production server recommendation; rerun with your deployed Prometheus tool version before rollout. No live Prometheus, exporter rollout or notification route was exercised.

## 1. Define what must exist

The expected series is:

```promql
gntech_tx_requests_finished_total{job="retry-metrics-lab",outcome="exhausted"}
```

It counts logical requests that consumed their retry budget. Each target should export the exhausted outcome even when its value is zero. Initialize known outcome labels at startup instead of waiting for the first failure to create them.

| Observed target state | Meaning for this rule |
| --- | --- |
| `up = 1`, expected metric has value 0 | Present and quiet; no presence alert. |
| `up = 1`, expected metric absent | Presence alert becomes pending, then firing after its delay. |
| `up = 0` | Excluded; investigate the scrape-failure alert. |
| No current `up` series | Excluded; investigate expected-target inventory separately. |

The rule checks presence, not counter progress, freshness inside an exporter cache, valid numeric values or business success. A present but stuck counter needs a different signal. A surviving `committed` outcome does not satisfy the contract for the `exhausted` outcome.

## 2. Install an offline test tool

Use Linux x86-64 with Bash, curl, tar and sha256sum. Create a fresh directory; only `promtool` will be extracted and no server will start.

```bash
mkdir metric-presence-lab
cd metric-presence-lab
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

Continue after the checksum check succeeds. Preserve its output and the tool version with the test result.

## 3. Match the metric to its own target

Save as `alerts.yml`:

```yaml
groups:
- name: retry-metric-presence
  interval: 1m
  rules:
  - alert: RetryOutcomeMetricMissing
    expr: |
      (up{job="retry-metrics-lab"} == 1)
      unless on (job, instance)
      gntech_tx_requests_finished_total{job="retry-metrics-lab",outcome="exhausted"}
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: Expected retry outcome metric missing
```

Read the expression in two parts. First, `up == 1` filters the left side down to successfully scraped targets. Then `unless on (job, instance)` removes every left-side target with a matching expected metric. Targets left over are the ones missing that metric. Additional application labels on the metric do not prevent the target-level match.

Keep both `job` and `instance` in the matching key. If worker A exports the metric and worker B does not, matching on job alone allows A to hide B's missing series. In a federated or multi-cluster query layer, include the additional labels needed to identify the same target unambiguously on both sides.

Do not change the filter to `up == bool 1`. Boolean comparison keeps false results as zero-valued vector elements. `unless` operates on presence of matching elements, not whether their values are nonzero. An alert expression can therefore still return a zero-valued element for a down target and count as active.

The two-minute `for` is a lab delay. Choose a production delay that allows expected startup behavior without hiding persistent instrumentation failures. Detection also depends on scrape/evaluation intervals and series staleness; it is not a guaranteed two minutes from the underlying code defect.

## 4. Test zero, disappearance and a healthy peer

Save as `tests.yml`. The samples use one-minute intervals. `1+0x8` means an initial 1 followed by eight additional unchanged samples. `stale` ends current series presence explicitly; `_` supplies a missing sample.

```yaml
rule_files:
- alerts.yml
evaluation_interval: 1m
tests:
- name: zero is present
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 0+0x8
  alert_rule_test:
  - eval_time: 3m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
- name: missing from startup
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  alert_rule_test:
  - eval_time: 1m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
  - eval_time: 2m
    alertname: RetryOutcomeMetricMissing
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Expected retry outcome metric missing
- name: metric disappears then returns
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 0 stale _ _ 0+0x4
  alert_rule_test:
  - eval_time: 2m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
  - eval_time: 3m
    alertname: RetryOutcomeMetricMissing
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Expected retry outcome metric missing
  - eval_time: 4m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
- name: one healthy peer cannot hide the missing target
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9816"}
    values: 1+0x8
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted"}
    values: 0+0x8
  alert_rule_test:
  - eval_time: 2m
    alertname: RetryOutcomeMetricMissing
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9816
        severity: warning
      exp_annotations:
        summary: Expected retry outcome metric missing
- name: down target is handled elsewhere
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 0+0x8
  alert_rule_test:
  - eval_time: 3m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
- name: removed target is handled by inventory
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1 stale _x7
  alert_rule_test:
  - eval_time: 3m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
- name: another outcome is insufficient
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="committed"}
    values: 0+0x8
  alert_rule_test:
  - eval_time: 2m
    alertname: RetryOutcomeMetricMissing
    exp_alerts:
    - exp_labels:
        job: retry-metrics-lab
        instance: 127.0.0.1:9815
        severity: warning
      exp_annotations:
        summary: Expected retry outcome metric missing
- name: extra application labels still match the target
  interval: 1m
  input_series:
  - series: up{job="retry-metrics-lab",instance="127.0.0.1:9815"}
    values: 1+0x8
  - series: gntech_tx_requests_finished_total{job="retry-metrics-lab",instance="127.0.0.1:9815",outcome="exhausted",operation="write"}
    values: 0+0x8
  alert_rule_test:
  - eval_time: 3m
    alertname: RetryOutcomeMetricMissing
    exp_alerts: []
```

| Fixture | Expected result |
| --- | --- |
| Zero counter present | No presence alert. |
| Missing at startup | No firing at 1m; firing at 2m. |
| Metric disappears, then returns | Pending at 2m, firing at 3m, clear at 4m. |
| A present, B missing | Only B fires; A cannot satisfy B's contract. |
| Target down | No presence alert; scrape health is separate. |
| Target removed | No presence alert; expected-target inventory is separate. |
| Only another outcome exists | Alert still fires for the missing exhausted outcome. |
| Extra application label exists | Presence still matches by target. |

The `exp_alerts: []` checks mean no firing alert at that evaluation. The later positive checks distinguish a pending delay from a rule that never fires. Expected target labels and annotations are checked as well.

The explicit stale samples make disappearance timing deterministic. A live missing scrape or service-discovery removal may have different lookback/staleness timing. Do not interpret an isolated underscore as immediate proof that a series has vanished from all instant queries.

## 5. Run the suite and check its sensitivity

```bash
./bin/promtool check rules alerts.yml
./bin/promtool test rules tests.yml
```

Expect one validated rule and a successful test run. The suite has 11 alert assertions across eight groups. Synthetic timestamps let the tests run without waiting for the full evaluation durations in real time.

Back up `alerts.yml`, then try each deliberate regression separately:

1. Replace `on (job, instance)` with `on (job)`. The two-target case should fail because the missing target is hidden by its healthy peer.
2. Restore the file, then replace `== 1` with `== bool 1`. The down-target case should fail because a zero-valued left-side element remains eligible.

Restore the original rule and require a passing run again. Keep expected results tied to the intended contract; do not rewrite them merely to silence a regression.

## 6. Investigate a real firing alert

Check that the alert labels identify the intended target. Compare its current `up` series, the exporter response and the ingested application metric with the exact expected outcome label. Check whether a release changed the metric name or label values. A valid zero is a useful observation; an absent series is not equivalent to zero.

Retain known low-cardinality outcome labels in the exporter. In the Python client, calling a labeled counter's `.labels(outcome="exhausted")` creates that child at zero before a failure occurs. Keep request IDs and arbitrary error strings out of metric labels.

Before enabling notifications, validate the complete Prometheus configuration, load the reviewed rule in an isolated monitoring environment, and verify a controlled metric-loss/restoration transition through the intended notification route. The offline suite validates these expression semantics and fixtures; it does not validate the live scrape path or operator delivery.

Retain a preceding reviewed rule and fixture set for rollback. Restore that pair through your normal configuration process and revalidate before reload. This offline lab changes no running service; remove its directory after preserving the test report if it is no longer needed.

## References

Official documentation reviewed November 22, 2026:

- [PromQL set operators and vector matching](https://prometheus.io/docs/prometheus/latest/querying/operators/)
- [Avoiding missing metrics](https://prometheus.io/docs/practices/instrumentation/)
- [Alert expression elements and pending delays](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Rule unit-test samples and expectations](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
- [Series staleness and lookback](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Python client label initialization](https://prometheus.github.io/client_python/instrumenting/labels/)
