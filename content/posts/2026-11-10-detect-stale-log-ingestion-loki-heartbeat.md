---
title: "Detect Stalled Log Ingestion With a Loki Heartbeat"
description: "Send a timestamped event through Grafana Alloy, query its absence in Loki, and verify that the signal clears when delivery resumes."
date: 2026-11-10T12:00:00-04:00
draft: false
ShowToc: true
tags: [linux, logging, grafana-alloy, loki, observability]
keywords: [Loki heartbeat, LogQL absent_over_time, Alloy log timestamp, stale ingestion]
summary: "Use a periodic file event to check the log path from producer through collection to the Loki query layer."
cover:
  image: "/images/posts/loki-log-heartbeat/featured.webp"
  alt: "Green status light on a small network appliance with blue cables leading toward a server rack."
  caption: "AI-generated editorial artwork."
  relative: false
---

A quiet service and a broken log pipeline can look identical in a dashboard. A synthetic heartbeat gives you one event that should arrive on a known schedule, even when the application has nothing to report.

This lab assumes a Linux test host with Grafana Alloy, Bash, curl, Python 3, and an existing single-tenant Loki test endpoint on loopback port 3100. The Alloy instance uses a separate configuration and state directory. It listens for its own diagnostics only on loopback port 12346. Check that this port is free before starting. Use a test destination you administer. This example uses unauthenticated HTTP on loopback and does not change Loki's listener or authentication settings.

| Signal | What it verifies |
| --- | --- |
| Heartbeat lines in the source file | The emitter is writing. |
| Recent heartbeat in Loki | The dedicated file path is working through collection, ingestion, and query. |
| Alert delivered to the test receiver | The rule and notification route are working. |

For a basic collection setup, see the [Grafana Alloy log collection guide](/posts/2026-05-14-grafana-alloy-log-collection/). The exercise below adds a continuing signal and a deliberate stop-and-resume test.

## 1. Configure a separate collector

In the first terminal, create the lab and record the directory printed by `pwd`. The exact file target avoids collecting unrelated logs. The processing stage uses the timestamp written by the emitter so old queued events keep their original age when delivered.

```bash
alloy --version
curl --fail --silent --show-error http://127.0.0.1:3100/ready
ss -ltn 'sport = :12346'
```

Continue once Loki is ready and the diagnostics port is free.

```bash
lab="$(mktemp -d /tmp/gntech-loki-heartbeat.XXXXXX)"
cd "$lab" || exit 1
touch heartbeat.jsonl
pwd

cat > heartbeat.alloy <<ALLOY
loki.source.file "heartbeat" {
  targets = [{"__path__" = "$lab/heartbeat.jsonl", "job" = "gntech_heartbeat", "probe" = "file_lab"}]
  forward_to = [loki.process.heartbeat.receiver]
}

loki.process "heartbeat" {
  forward_to = [loki.write.lab.receiver]

  stage.json {
    expressions = {"emitted_at" = "emitted_at"}
  }

  stage.timestamp {
    source = "emitted_at"
    format = "RFC3339"
    action_on_failure = "skip"
  }
}

loki.write "lab" {
  endpoint {
    url = "http://127.0.0.1:3100/loki/api/v1/push"
  }
}
ALLOY

alloy validate heartbeat.alloy &&
alloy run --server.http.listen-addr=127.0.0.1:12346 \
  --storage.path="$lab/state" heartbeat.alloy
```

Use valid UTC timestamps and synchronize clocks on different hosts. With `action_on_failure = "skip"`, Alloy keeps the existing entry timestamp when parsing fails. The lab emitter writes valid timestamps. For a production heartbeat, verify that timestamps parse correctly and reject malformed probes if freshness depends on the producer's clock.

## 2. Emit and query the heartbeat

In a second terminal, replace the placeholder with the lab path. The foreground loop writes one event every 30 seconds. Leave it running for the baseline check.

```bash
cd /tmp/gntech-loki-heartbeat.REPLACE || exit 1
while true; do
  printf '{"event":"GNTECH_LOG_HEARTBEAT","emitted_at":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> heartbeat.jsonl
  sleep 30
done
```

In a third terminal, query the count and the absence signal. Run the queries after Alloy has sent the first line.

```bash
loki=http://127.0.0.1:3100
query_loki() {
  curl --fail --silent --show-error --get "$loki/loki/api/v1/query" \
    --data-urlencode "query=$1" | python3 -m json.tool
}
query_loki 'count_over_time({job="gntech_heartbeat",probe="file_lab"} |= "GNTECH_LOG_HEARTBEAT" [3m])'
query_loki 'absent_over_time({job="gntech_heartbeat",probe="file_lab"} |= "GNTECH_LOG_HEARTBEAT" [3m])'
```

A healthy count query has a positive sample. The absence query should return an empty result while a heartbeat is within the window. When none is present, it returns a sample with value `1`. An HTTP or query error is a separate state. It gives no information about whether the stream contains a recent heartbeat.

If repeating against the same Loki instance, wait for the previous run's events to age out or choose a new probe label and use it consistently in both queries and the rule. In production, keep labels stable and bounded. Use one rule or an explicit inventory for each expected probe. A single selector that matches several hosts can remain healthy when just one host stops reporting.

## 3. Test the missing and recovered states

Stop only the emitter with Ctrl+C in the second terminal. Leave Alloy and Loki running. Wait until the last event is older than three minutes, then rerun the absence query. Record the returned sample. Restart the emitter with the same loop and check that the count becomes positive and the absence result becomes empty again.

To exercise alert delivery on a Loki installation with its ruler and Alertmanager already configured, load the following as a Loki-managed rule group using your existing provisioning method. It uses a 30-second evaluation interval and requires the absence condition to persist for one minute. Account for the three-minute query window, the pending period, and notification timing before expecting delivery.

```yaml
groups:
  - name: gntech-log-heartbeat-lab
    interval: 30s
    rules:
      - alert: LabLogHeartbeatMissing
        expr: absent_over_time({job="gntech_heartbeat",probe="file_lab"} |= "GNTECH_LOG_HEARTBEAT" [3m])
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "No recent file heartbeat in Loki"
```

Repeat the stop-and-resume test and verify the firing and resolved states at the ruler. If your test receiver is configured to send resolved notifications, verify those too. This is a Loki-managed rule. If you implement the same check with Grafana-managed alerting, explicitly test its handling of the empty healthy result and of query errors.

## 4. Interpret the result and clean up

| Observation | First check |
| --- | --- |
| No line in the source file | Check the emitter and write permissions. |
| File advances but Loki sees nothing | Check Alloy's target, diagnostics, endpoint responses, and timestamps. |
| Loki query errors | Check Loki readiness, permissions, and the query independently of the heartbeat. |
| Rule fires but nothing arrives | Check Alertmanager routing, silences, and receiver delivery. |

This test covers the route and parser used by the synthetic file. It cannot establish that every application, label, or tenant is collecting correctly. Place production probes on representative paths, choose a window that allows normal collection and query delay, and monitor the query and notification layers separately.

Remove the test rule from its provisioning source, then stop the emitter and Alloy with Ctrl+C. Keep the configuration and query results if needed for review. Loki retains ingested test events according to its configured retention.

## Official references

- [Alloy file source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/)
- [Alloy log processing and timestamps](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/)
- [Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/)
- [LogQL metric queries](https://grafana.com/docs/loki/latest/query/metric_queries/)
- [Loki alerting rules](https://grafana.com/docs/loki/latest/alert/)
