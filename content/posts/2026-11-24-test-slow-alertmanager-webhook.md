---
title: "Test a Slow Alertmanager Webhook Alongside a Healthy One"
description: "Hold one local webhook open past its timeout and verify that a second integration receives the same firing alert while the slow path retries."
date: 2026-11-24T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, reliability]
keywords: [Alertmanager slow webhook, webhook timeout, concurrent integrations, notification isolation]
summary: "A loopback-only runtime drill checks healthy delivery while a sibling webhook stalls, times out and retries."
cover:
  image: "/images/posts/alertmanager-slow-webhook/featured.webp"
  alt: "Two metal lanterns, one lit and one dark, beside an hourglass, laptop and homelab server overlooking a mountain lake."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

A receiver can accept a connection and then stop responding. That failure is different from returning an error immediately: the request occupies time until a timeout cancels it. When an alert has more than one destination, check whether the healthy destination still receives the current notification while another request is stalled.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) attaches two local webhook integrations to one named Alertmanager receiver. One handler deliberately sends no response. The other returns HTTP 204. A verifier submits one synthetic alert, checks healthy delivery, and requires evidence that the slow path timed out and retried for the same alert and group.

Preparation status: configuration validation and the runtime drill passed locally with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat the test with your deployed release. No production route, real paging channel, Prometheus rule evaluation or GNTECH rollout was exercised.

## 1. Define what success means

| Component | Required observation |
| --- | --- |
| Alert API | Accepts one synthetic firing alert. |
| Healthy webhook | Returns HTTP 204; Alertmanager logs success for its integration. |
| Slow webhook | Starts at least two requests while its handlers remain blocked. |
| Alertmanager log | Records the configured two-second webhook timeout. |
| Payload identity | Every observed request carries the same firing alert fingerprint and notification group key. |

Both webhook entries belong to receiver `local-lab`. They are integrations, not two child routes. No `continue: true` routing rule is needed to invoke both entries in that receiver.

The pinned implementation constructs a separate delivery pipeline for each integration and runs those pipelines concurrently. It also waits for them to finish before the overall fan-out stage returns. A healthy destination can therefore receive this notification while another integration is still working, without making the entire send operation successful.

This drill tests that first-delivery behavior. It does not establish resource isolation under heavy load, fairness across groups, indefinite progress of later notifications, or a production latency guarantee.

## 2. Install the disposable lab tools

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback port 19097 for the threaded capture server and 19098 for the disposable Alertmanager. Use an ordinary account and a fresh directory. Do not point the verifier at an existing monitoring service.

```bash
mkdir slow-webhook-lab
cd slow-webhook-lab
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

Continue only after checksum verification succeeds. Both listeners bind to loopback. Clustering is disabled and Alertmanager uses temporary state removed on exit. No credentials or external notification service are needed.

## 3. Configure two integrations with bounded requests

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
  - url: http://127.0.0.1:19097/slow
    timeout: 2s
    send_resolved: false
  - url: http://127.0.0.1:19097/healthy
    timeout: 2s
    send_resolved: false
```

The slow integration is listed first; list order is not a dependency that forces the healthy integration to wait for it. Each entry has a two-second webhook timeout. The one-minute group interval is longer than an individual request timeout and the verifier's twelve-second observation window. The one-hour repeat interval prevents a routine repeat from satisfying the check.

A webhook timeout bounds an individual invocation. It is not an end-to-end delivery deadline or a fixed retry schedule. The notification pipeline also has a context deadline associated with the group interval, so a very short group interval can cancel delivery work. Keep request and grouping policies distinct when adapting the lab.

## 4. Save the runtime verifier

Save as `drill.py`. It overwrites `events.jsonl` and `alertmanager.log` on each run; preserve previous evidence before rerunning. Use regular `python3`, without `-O`, because the payload checks use assertions.

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
from pathlib import Path

BASE = "http://127.0.0.1:19098"
release = threading.Event()
lock = threading.Lock()
events = []
started = time.monotonic()


def record(kind, payload):
    entry = {"elapsed": round(time.monotonic() - started, 3),
             "event": kind, "payload": payload}
    with lock:
        events.append(entry)
        with open("events.jsonl", "a", encoding="utf-8") as output:
            output.write(json.dumps(entry) + "\n")


def snapshot():
    with lock:
        return list(events)


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/slow":
            record("slow-start", payload)
            release.wait()  # No HTTP response; released only during cleanup.
            self.close_connection = True
            record("slow-cleanup", payload)
        elif self.path == "/healthy":
            self.send_response(204)
            self.end_headers()
            record("healthy-204", payload)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


def wait_for(check, label, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19098))
Path("events.jsonl").write_text("")
server = ThreadingHTTPServer(("127.0.0.1", 19097), Receiver)
server.daemon_threads = True
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix="am-slow-webhook-") as state:
        with open("alertmanager.log", "w") as log:
            process = subprocess.Popen([
                "./bin/alertmanager", "--config.file=alertmanager.yml",
                "--storage.path=" + state,
                "--web.listen-address=127.0.0.1:19098",
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
                wait_for(ready, "Alertmanager readiness", 10)
                now = dt.datetime.now(dt.timezone.utc)
                labels = {"alertname": "SlowWebhookLab", "instance": "worker-a"}
                alert = {"labels": labels,
                         "annotations": {"summary": "Synthetic isolation drill"},
                         "startsAt": stamp(now - dt.timedelta(seconds=1)),
                         "endsAt": stamp(now + dt.timedelta(minutes=3))}
                request = urllib.request.Request(
                    BASE + "/api/v2/alerts", data=json.dumps([alert]).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert response.status == 200

                def isolated():
                    current = snapshot()
                    text = Path("alertmanager.log").read_text()
                    success = any('msg="Notify success"' in line
                                  and 'integration=webhook[1]' in line
                                  for line in text.splitlines())
                    return (sum(e["event"] == "slow-start" for e in current) >= 2
                            and any(e["event"] == "healthy-204" for e in current)
                            and "configured webhook timeout reached (2s)" in text
                            and success)
                wait_for(isolated, "healthy success alongside slow timeout/retry", 12)
                observed = snapshot()
                assert not release.is_set()
                assert not any(e["event"] == "slow-cleanup" for e in observed)
                groups, fingerprints = set(), set()
                for entry in observed:
                    payload = entry["payload"]
                    assert payload["receiver"] == "local-lab"
                    assert payload["status"] == "firing"
                    assert len(payload["alerts"]) == 1
                    item = payload["alerts"][0]
                    assert item["labels"] == labels and item["status"] == "firing"
                    groups.add(payload["groupKey"])
                    fingerprints.add(item["fingerprint"])
                assert len(groups) == len(fingerprints) == 1
                assert next(iter(groups)) and next(iter(fingerprints))
                assert process.poll() is None
                print("PASS: healthy webhook succeeded while slow handlers stayed blocked")
                print("PASS: slow integration timed out and retried for the same alert/group")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
finally:
    release.set()
    server.shutdown()
    server.server_close()
    thread.join()
```

The capture server is threaded deliberately. A single-threaded HTTP server would hold the healthy request behind the sleeping handler and introduce a shared bottleneck unrelated to Alertmanager's integration scheduling.

The slow handler does not send HTTP headers, an error status or a body. Its event is released only during cleanup, after the verifier has made its assertions. A second slow request plus the timeout log demonstrates a retry after a stalled invocation. The healthy handler sends its HTTP response before recording its event, and the verifier separately requires Alertmanager's success log for `webhook[1]`.

The log strings and zero-based integration index match the pinned release and this configuration. If you change versions, ordering or logging, review those checks. A changed log format is a reason to inspect the evidence, not to declare either healthy delivery or notification failure without further work.

## 5. Run and review both paths

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Require configuration validation and both PASS lines. A timeout or traceback means the drill failed. The verifier submits the alert once, starts no replacement process and never releases the slow handler before checking healthy success. It compares payload identities instead of assuming an exact request count or arrival order.

Inspect the evidence independently:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
for line in Path("events.jsonl").read_text().splitlines():
    e = json.loads(line)
    p = e["payload"]
    print(e["elapsed"], e["event"], p["receiver"],
          p["alerts"][0]["fingerprint"])
PYCODE
```

Expect a `healthy-204` event and at least two `slow-start` events for the same fingerprint. `slow-cleanup` events appear after the assertions when blocked handlers are released; they are not successful slow notifications. Inspect `alertmanager.log` for the healthy integration's success and the slow integration's timeout. Cancellation messages during intentional process shutdown do not prove that the slow destination recovered.

The twelve-second observation bound keeps this a short failure test. Actual elapsed values and retry counts may vary. A local HTTP 204 only establishes acceptance by the capture endpoint; no person was paged and no downstream business action was tested.

For a controlled negative check, back up the configuration, remove the complete `/healthy` webhook entry, and rerun. The verifier should time out because healthy delivery is required, even though the remaining slow integration can time out and retry. Restore both entries and require another passing run. Keep that mutation in the disposable directory.

## 6. Apply the finding with its limits

A working destination does not make the route healthy as a whole. Track each intended integration, inspect notification errors and test the independent channel you rely on during an incident. Do not use a single successful webhook as evidence that all destinations accepted an alert.

Before changing a production configuration, validate the complete file with the matching amtool and test a disposable route on the intended release. Exercise representative payload sizes, proxies, TLS, authentication, load and downstream processing separately. Check later alert updates as well as the first notification; the fan-out stage still waits for unfinished work, and the overall pipeline can expire.

The Python server is an in-memory test fixture. It is not a production receiver or durable queue. This lab does not test long outages, multiple Alertmanager replicas, restart persistence, receiver recovery, or duplicate business effects after an ambiguous response.

On exit, the verifier terminates its own Alertmanager, releases the blocked handlers, stops the capture server and removes temporary Alertmanager state. Keep the evidence files as needed, then remove the lab directory. No live configuration was edited. If you separately deploy a change, retain the preceding reviewed configuration for your normal rollback process.

## Official references

Reviewed November 24, 2026:

- [Alertmanager route timing and webhook configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Pinned per-integration pipelines and concurrent fan-out](https://github.com/prometheus/alertmanager/blob/v0.28.1/notify/notify.go)
- [Pinned webhook timeout configuration](https://github.com/prometheus/alertmanager/blob/v0.28.1/docs/configuration.md)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
- [Python threaded HTTP server](https://docs.python.org/3/library/http.server.html)
