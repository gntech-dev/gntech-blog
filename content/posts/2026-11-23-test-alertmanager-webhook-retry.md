---
title: "Test Alertmanager Retries After a Temporary Webhook Failure"
description: "Reject local webhook requests with HTTP 503, recover the receiver, and verify that the same alert is retried without resubmission or restart."
date: 2026-11-23T17:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, reliability]
keywords: [Alertmanager webhook retry, HTTP 503, notification recovery, local webhook test]
summary: "A disposable loopback drill records failed notification attempts and verifies successful delivery after receiver recovery."
cover:
  image: "/images/posts/alertmanager-webhook-retry/featured.webp"
  alt: "A brass desk bell and amber hourglass beside a laptop and compact homelab server overlooking a mountain lake at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot."
  relative: false
---

An alert can be firing while its notification destination is temporarily unavailable. A successful request to Alertmanager's alert API does not tell you whether the destination accepted a notification. To test recovery, make the destination reject delivery, then watch what Alertmanager does when it becomes available again.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) uses a disposable Alertmanager and a local Python webhook. It submits one synthetic alert, records repeated HTTP 503 responses, enables HTTP 204, and checks that the same alert and notification group arrive without restarting Alertmanager or resubmitting the alert.

Preparation status: the configuration check and runtime drill passed locally with checksum-verified Alertmanager/amtool 0.28.1. That release is a historical isolated lab baseline, not a current production version recommendation. Repeat the drill with your deployed release before relying on its behavior. No production receiver, real paging channel, Prometheus rule evaluation, or GNTECH deployment was exercised.

## 1. Separate the three acknowledgments

| Evidence | What it establishes |
| --- | --- |
| Alert API returns HTTP 200 | Alertmanager accepted the synthetic alert submission. |
| Local webhook returns HTTP 503 | The receiver was contacted but rejected the notification temporarily. |
| Local webhook later returns HTTP 204 | The receiver accepted a subsequent attempt. It does not prove that a person was paged or a downstream action completed. |

The pinned release's generic webhook implementation treats 2xx responses as success and 5xx responses as recoverable failures. Its default retry classifier does not classify HTTP 400 as retryable. These are integration-specific behaviors: do not infer another receiver's policy, or a special response such as 429, from this test.

The receiver records the payload on every attempt, including rejected ones. That makes repeated requests visible without applying any business effect. A real receiver must account for ambiguous outcomes: it might complete work and lose the response, causing a retry. This drill does not prove exactly-once delivery or durable deduplication.

## 2. Prepare an isolated directory

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback ports 19095 for the webhook and 19096 for Alertmanager. Run as an ordinary user in a fresh directory; the script starts its own services and must not be pointed at an existing monitoring instance.

```bash
mkdir webhook-retry-lab
cd webhook-retry-lab
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

Continue only after the checksum check succeeds. The clustering listener is disabled, the web listener is loopback-only, and Alertmanager storage lives in a temporary directory removed on exit. No account or credential is needed.

## 3. Keep notification retries separate from routine repeats

Save as `alertmanager.yml`:

```yaml
route:
  receiver: local-lab
  group_by: [alertname, instance]
  group_wait: 1s
  group_interval: 1m
  repeat_interval: 1h
receivers:
- name: local-lab
  webhook_configs:
  - url: http://127.0.0.1:19095/alerts
    send_resolved: false
    timeout: 2s
```

`group_wait: 1s` allows the initial notification to start promptly. The one-minute group interval and one-hour repeat interval are longer than the verifier's shared 30-second delivery window. A successful repeat an hour later cannot satisfy the test. The two-second webhook timeout bounds each request; it does not define the complete retry schedule or total delivery guarantee.

These timings serve this isolated experiment. Production grouping, timeout and repeat policies need their own operational choices. The verifier does not assert exact backoff intervals or an exact request count.

## 4. Save the runtime verifier

Save as `drill.py`. It overwrites `attempts.jsonl` and `alertmanager.log` in the current directory on every run; copy evidence you want to keep before rerunning. The script fails if the local ports cannot be bound, Alertmanager exits, a required observation times out, or payload identities change.

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

BASE = "http://127.0.0.1:19096"
recovered = threading.Event()
lock = threading.Lock()
attempts = []
started = time.monotonic()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        code = 204 if recovered.is_set() else 503
        entry = {"elapsed": round(time.monotonic() - started, 3),
                 "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "response": code, "payload": payload}
        with lock:
            attempts.append(entry)
            with open("attempts.jsonl", "a", encoding="utf-8") as output:
                output.write(json.dumps(entry) + "\n")
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):
        pass


def snapshot():
    with lock:
        return list(attempts)


def wait_for(check, label, deadline):
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19096))
open("attempts.jsonl", "w").close()
server = ThreadingHTTPServer(("127.0.0.1", 19095), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix="am-webhook-retry-") as state:
        with open("alertmanager.log", "w") as log:
            process = subprocess.Popen([
                "./bin/alertmanager", "--config.file=alertmanager.yml",
                "--storage.path=" + state,
                "--web.listen-address=127.0.0.1:19096",
                "--cluster.listen-address=", "--log.level=debug",
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
                wait_for(ready, "Alertmanager readiness", time.monotonic() + 10)
                now = dt.datetime.now(dt.timezone.utc)
                labels = {"alertname": "WebhookRetryLab", "instance": "worker-a"}
                alert = {"labels": labels,
                         "annotations": {"summary": "Synthetic retry drill"},
                         "startsAt": stamp(now - dt.timedelta(seconds=1)),
                         "endsAt": stamp(now + dt.timedelta(minutes=3))}
                request = urllib.request.Request(
                    BASE + "/api/v2/alerts", data=json.dumps([alert]).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert response.status == 200
                # This is the only alert submission. Do not resend it on recovery.
                deadline = time.monotonic() + 30
                wait_for(lambda: len(snapshot()) >= 2,
                         "two rejected webhook attempts", deadline)
                before = snapshot()
                assert all(e["response"] == 503 for e in before)
                print("PASS: receiver rejected at least two attempts with HTTP 503")
                recovered.set()
                wait_for(lambda: any(e["response"] == 204 for e in snapshot()),
                         "successful retry after receiver recovery", deadline)
                observed = snapshot()
                fingerprints = set()
                groups = set()
                for entry in observed:
                    payload = entry["payload"]
                    assert payload["receiver"] == "local-lab"
                    assert payload["status"] == "firing"
                    assert len(payload["alerts"]) == 1
                    item = payload["alerts"][0]
                    assert item["labels"] == labels
                    assert item["status"] == "firing"
                    fingerprints.add(item["fingerprint"])
                    groups.add(payload["groupKey"])
                assert len(fingerprints) == len(groups) == 1
                assert next(iter(fingerprints)) and next(iter(groups))
                assert process.poll() is None
                print("PASS: same alert/group reached HTTP 204 without resubmission or restart")
                print("Evidence: attempts.jsonl and alertmanager.log")
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

The only alert submission is the POST to `/api/v2/alerts`. Recovery changes an in-process flag in the local receiver; it does not reload Alertmanager, restart either service, or send a second alert. Each webhook attempt must carry one firing alert with the same labels, fingerprint and group key.

The 30-second deadline is a bounded lab assertion, not a production service-level promise. The alert's three-minute expiry keeps it firing throughout the test while providing a fallback end time. No resolution notification is requested in this drill.

## 5. Run and inspect the evidence

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Require configuration validation and both PASS lines. A timeout or traceback is a failed drill, even if the initial alert API call succeeded. The script terminates its child process, shuts down the webhook and removes temporary Alertmanager state in its cleanup blocks.

Inspect the attempt history separately:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
for line in Path("attempts.jsonl").read_text().splitlines():
    entry = json.loads(line)
    payload = entry["payload"]
    print(entry["elapsed"], entry["response"], payload["receiver"],
          payload["status"], payload["alerts"][0]["fingerprint"])
PYCODE
```

Expected evidence is at least two 503 attempts followed by a 204, all for the same firing alert and group. Actual elapsed values can vary. The verifier checks identity and response history rather than treating a fixed delay as proof of delivery. Keep `alertmanager.log` with the JSONL record to investigate any failure.

As a controlled negative check in this isolated directory, back up `drill.py`, change `else 503` to `else 400`, and run again. On the pinned release, the verifier should time out waiting for two attempts within the delivery window. This demonstrates why a permanent request error is different from the temporary receiver failure tested here. It does not prove that HTTP 400 can never appear again in a later notification cycle. Restore the original script and require a passing run before keeping the result as your baseline.

## 6. Translate the result into a receiver runbook

| Observation in a real route | Next investigation |
| --- | --- |
| No request reaches the receiver | Confirm matching routes, suppression and connectivity before investigating receiver recovery. |
| Repeated 5xx responses | Inspect receiver availability, its dependencies and delivery-error logs. |
| A 4xx response | Check the exact integration's retry policy, request format, authentication and authorization. |
| Receiver returns 2xx but no downstream result appears | Inspect the receiver's queue, durable acceptance policy and downstream processing. |

Run the same failure-and-recovery test against a disposable route on the intended release. Test representative alerts, payload sizes, authentication and network boundaries separately. A responding local webhook does not validate TLS, a proxy, an email provider or a human notification channel.

Long outages, Alertmanager restarts, multiple replicas, notification retention, timeouts after completed work and durable receiver deduplication remain separate validation tasks. Do not assume this short in-memory receiver is a production queue. Keep normal monitoring of the notification path alongside application alerts.

After preserving any useful evidence, remove the lab directory when finished. The script never edits a live configuration. If you separately promote a change, retain the preceding reviewed configuration and use your normal deployment and rollback process.

## Official references

Reviewed November 23, 2026:

- [Alertmanager configuration and webhook payload](https://prometheus.io/docs/alerting/latest/configuration/)
- [Pinned webhook notifier implementation](https://github.com/prometheus/alertmanager/blob/v0.28.1/notify/webhook/webhook.go)
- [Pinned HTTP retry classifier](https://github.com/prometheus/alertmanager/blob/v0.28.1/notify/util.go)
- [Pinned webhook configuration and timing](https://github.com/prometheus/alertmanager/blob/v0.28.1/docs/configuration.md)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
- [Python HTTP server documentation](https://docs.python.org/3/library/http.server.html)
