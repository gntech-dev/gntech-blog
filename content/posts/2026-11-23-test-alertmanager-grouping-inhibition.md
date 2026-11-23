---
title: "Test Alertmanager Grouping and Inhibition Across Two Workers"
description: "Use a local webhook to prove that one worker's source alert inhibits only its own dependent alert and releases it after resolution."
date: 2026-11-23T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, reliability]
keywords: [Alertmanager inhibition test, grouping by instance, scoped inhibition, local webhook]
summary: "An isolated runtime drill checks per-worker notification groups, suppression scope and release after source resolution."
cover:
  image: "/images/posts/alertmanager-inhibition/featured.webp"
  alt: "Two brass desk bells on blue coasters, with one bell partly covered by a felt dome beside a homelab server."
  caption: "AI-generated conceptual editorial artwork; not an alert dashboard."
  relative: false
---

Grouping and inhibition solve different problems. Grouping decides which alerts share a notification. Inhibition suppresses a target alert's notification while a matching source alert is firing. An overly broad equality key can hide another worker's independent failure.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) checks both behaviors with a disposable Alertmanager and a local Python webhook. It injects three synthetic API alerts, inspects inhibition status and verifies the webhook payloads. It does not contact people, a database, or a production receiver.

Preparation status: configuration validation and the local runtime drill passed with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat the drill with the release you deploy. No GNTECH production rollout, Prometheus rule evaluation or external notification delivery was exercised.

## 1. Define the expected scope

All alerts share job `retry-lab`. The `instance` label separates the two synthetic workers.

| Alert | Initial expectation |
| --- | --- |
| worker-a / WorkerUnavailable | Delivered as the source alert. |
| worker-a / WorkerMetricMissing | Retained by Alertmanager but inhibited from notification. |
| worker-b / WorkerMetricMissing | Delivered because worker B has no matching source. |

After resolving worker A's source, its still-firing dependent alert should become eligible for delivery. The test deliberately creates overlapping alerts to exercise inhibition. It does not replace upstream rule guards that avoid reporting a metric-presence failure when its scrape is down.

## 2. Install the isolated lab tools

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback ports 19093 for the local webhook and 19094 for the disposable Alertmanager. Run from a fresh directory and do not point the script at a running monitoring service.

```bash
mkdir inhibition-lab
cd inhibition-lab
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
    "alertmanager-${version}.linux-amd64/alertmanager" \
    "alertmanager-${version}.linux-amd64/amtool"
  ./alertmanager --version
)
```

Continue after checksum verification succeeds. The script starts its own process on loopback, disables the clustering listener and uses temporary state. It never starts a public listener or loads your existing Alertmanager storage.

## 3. Group and inhibit by worker identity

Save as `alertmanager.yml`:

```yaml
route:
  receiver: local-lab
  group_by: [job, instance]
  group_wait: 2s
  group_interval: 2s
  repeat_interval: 1h
receivers:
- name: local-lab
  webhook_configs:
  - url: http://127.0.0.1:19093/
    send_resolved: true
inhibit_rules:
- source_matchers: ['alertname="WorkerUnavailable"']
  target_matchers: ['alertname="WorkerMetricMissing"']
  equal: [job, instance]
```

`group_by` keeps worker A and B in separate groups while allowing related alert names for one worker to share a notification. `equal` limits inhibition to the same job and instance. These settings are independent: grouping by instance does not repair an inhibition rule that only compares job.

Use disjoint source and target matchers so an alert cannot match both sides. Require meaningful identity labels from producers: a missing label and an empty label value compare equally for inhibition. In a multi-cluster system, include the additional labels needed to identify the same worker on both alerts.

The two-second timings are for a fast local drill. Production `group_wait`, `group_interval` and repeat policies need operational choices. A source that arrives after the first group notification cannot undo a notification already delivered.

## 4. Save the runtime verifier

Save as `drill.py`. It overwrites `events.jsonl` and `alertmanager.log` in this lab directory on each run. Retain copies before rerunning if you need previous evidence. The script checks port availability, starts both local services, posts all three alerts in one batch and waits for explicit conditions with bounded polling.

```python
import datetime as dt
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "http://127.0.0.1:19094"
messages = []
lock = threading.Lock()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with lock:
            messages.append(body)
            with open("events.jsonl", "a") as output:
                output.write(json.dumps(body) + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2) as response:
        body = response.read()
        return json.loads(body) if body else None


def wait_for(check, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise RuntimeError("Timed out: " + label)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def alerts():
    return {(a["labels"]["instance"], a["labels"]["alertname"]): a
            for a in request("/api/v2/alerts")}


def firing_pairs():
    with lock:
        return {(a["labels"]["instance"], a["labels"]["alertname"])
                for m in messages for a in m["alerts"]
                if a["status"] == "firing"}


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19094))
open("events.jsonl", "w").close()
server = ThreadingHTTPServer(("127.0.0.1", 19093), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix="am-inhibition-") as state:
        with open("alertmanager.log", "w") as log:
            process = subprocess.Popen([
                "./bin/alertmanager", "--config.file=alertmanager.yml",
                "--storage.path=" + state,
                "--web.listen-address=127.0.0.1:19094",
                "--cluster.listen-address=",
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                def ready():
                    if process.poll() is not None:
                        raise RuntimeError("Alertmanager exited; inspect alertmanager.log")
                    try:
                        with urllib.request.urlopen(BASE + "/-/ready", timeout=1) as r:
                            return r.status == 200
                    except urllib.error.URLError:
                        return False
                wait_for(ready, "Alertmanager readiness")
                now = dt.datetime.now(dt.timezone.utc)
                def alert(instance, name):
                    return {"labels": {"job": "retry-lab", "instance": instance,
                                       "alertname": name},
                            "annotations": {"summary": "Synthetic lab alert"},
                            "startsAt": stamp(now - dt.timedelta(seconds=1)),
                            "endsAt": stamp(now + dt.timedelta(minutes=3))}
                source = alert("worker-a", "WorkerUnavailable")
                request("/api/v2/alerts", [source,
                        alert("worker-a", "WorkerMetricMissing"),
                        alert("worker-b", "WorkerMetricMissing")])

                def scoped():
                    current = alerts()
                    a = current.get(("worker-a", "WorkerMetricMissing"), {})
                    b = current.get(("worker-b", "WorkerMetricMissing"), {})
                    return (bool(a.get("status", {}).get("inhibitedBy"))
                            and b.get("status", {}).get("state") == "active"
                            and not b["status"]["inhibitedBy"])
                wait_for(scoped, "A inhibited while B stays active")
                wait_for(lambda: {("worker-a", "WorkerUnavailable"),
                                 ("worker-b", "WorkerMetricMissing")} <= firing_pairs(),
                         "initial local notifications")
                assert ("worker-a", "WorkerMetricMissing") not in firing_pairs()
                with lock:
                    for message in messages:
                        assert set(message["groupLabels"]) == {"job", "instance"}
                        assert {a["labels"]["instance"] for a in message["alerts"]} == {
                            message["groupLabels"]["instance"]}
                print("PASS: per-worker groups; A inhibited; B delivered")

                source["endsAt"] = stamp(dt.datetime.now(dt.timezone.utc))
                request("/api/v2/alerts", [source])
                wait_for(lambda: ("worker-a", "WorkerMetricMissing") in firing_pairs(),
                         "A dependent notification after source resolution")
                assert not alerts()[("worker-a", "WorkerMetricMissing")]["status"]["inhibitedBy"]
                print("PASS: resolving A source released A dependent notification")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
```

The alert API's `inhibitedBy` field confirms that the dependent alert remains known but suppressed. The local webhook confirms what was actually sent. These are separate observations; an inhibited status by itself does not prove that worker B's notification was delivered.

## 5. Validate configuration and run the drill

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Expect configuration validation to succeed and the script to print both PASS lines. It requires these observations:

- A's dependent alert has an inhibitor while B's dependent alert is active without one.
- Initial local notifications include A's source and B's dependent, but omit A's dependent.
- Every checked initial payload groups by job and instance, with no mixed worker instances.
- Resolving A's source allows A's dependent to reach the local webhook.

Inspect `events.jsonl` for payloads and `alertmanager.log` for runtime errors. Do not assert an exact notification count: grouping timers and resolved alerts can produce additional updates. The script checks alert identities and status rather than relying on one particular delivery order.

If the drill times out or an assertion fails, it failed. Preserve the logs and inspect the actual labels, API status and webhook payloads. A configuration syntax check does not validate the scope of an inhibition rule.

As a controlled regression check, back up the configuration, change `equal: [job, instance]` to `equal: [job]`, and rerun. The scope check should fail because worker A's source also inhibits worker B's dependent alert. Restore the reviewed configuration and require a passing run again. Keep this mutation confined to the isolated lab.

## 6. Apply the behavior deliberately

Keep a passing copy of the configuration, verifier and evidence together. Test the same release and routing tree used by the intended deployment. Add the rule through your normal configuration process, validate the complete file, and test the real delivery route separately before relying on it.

Inhibition is not a substitute for good source rules or expected-target inventory. Use it for dependencies that operators agree should suppress notifications, with explicit identity labels and a recovery condition. A suppressed alert still needs to be understandable during incident review.

The verifier terminates its disposable Alertmanager, stops its webhook and removes temporary state on exit. Keep the evidence files as needed, then remove the lab directory. No live configuration needs rollback unless you separately promoted a change; retain the preceding reviewed configuration for that deployment's normal rollback process.

## References

Official documentation reviewed November 23, 2026:

- [Alertmanager grouping and inhibition concepts](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Route timing and inhibition equality](https://prometheus.io/docs/alerting/latest/configuration/)
- [Alertmanager API v2 schema](https://github.com/prometheus/alertmanager/blob/v0.28.1/api/v2/openapi.yaml)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
