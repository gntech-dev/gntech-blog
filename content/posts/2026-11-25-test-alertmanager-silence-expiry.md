---
title: "Test a Scoped Alertmanager Silence Through Natural Expiration"
description: "Create a short-lived silence for one worker, verify that a peer still notifies, and confirm delivery resumes after the silence expires."
date: 2026-11-25T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, maintenance]
keywords: [Alertmanager silence expiry, scoped silence test, silencedBy, maintenance notifications]
summary: "A disposable loopback lab checks silence scope, unaffected peer delivery and notification eligibility after natural expiration."
cover:
  image: "/images/posts/alertmanager-silence-expiry/featured.webp"
  alt: "A brass bell partly covered by a felt dome beside an unlabeled timer, laptop and compact homelab server at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

A maintenance silence should mute the alerts you intended, for the time you intended. A silence that matches only an alert name can hide a second worker's unrelated failure. An expired silence also does not mean that the underlying fault recovered; a still-firing alert can become eligible for notification again.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) creates a twenty-second silence for one synthetic worker. It checks that a peer notifies during that window, waits for natural expiration, and verifies that the still-firing silenced worker subsequently reaches a local webhook. It never expires the silence manually or resubmits the alerts to trigger recovery.

Preparation status: configuration validation and the local runtime drill passed with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat with the release used by the intended deployment. No real maintenance window, production silence, Prometheus rule evaluation, paging channel or GNTECH rollout was exercised.

## 1. Define the scope and the evidence

Both alerts use `alertname="SilenceLab"`. Their `instance` labels distinguish worker A from worker B. The silence requires both that alert name and `instance="worker-a"`; its equality matchers must all match.

| Phase | Worker A | Worker B |
| --- | --- | --- |
| Silence active | Alert remains known; its status includes the created silence ID. No firing webhook should arrive. | Active without a silence; firing webhook must arrive. |
| Silence expired | Still-firing alert is active without a silence and reaches the webhook. | Its earlier successful delivery remains evidence that the peer was unaffected. |

A silence is a time-bounded matcher-based suppression rule. It does not repair an application or change the alert's source condition. This test checks actual captured notifications alongside API status: a `silencedBy` field alone does not prove that the unaffected peer received anything.

Use meaningful identity labels when designing a real maintenance scope. Include the cluster, environment or service labels needed to distinguish otherwise identical workers. Review the complete matcher set, start time and end time before applying a silence outside a disposable lab.

## 2. Prepare the isolated tools

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback ports 19099 for the webhook and 19101 for the disposable Alertmanager. Run as an ordinary user in a fresh directory. Do not point the script at an existing monitoring service.

```bash
mkdir silence-lab
cd silence-lab
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

Continue only after checksum verification succeeds. The script owns both loopback services, disables the clustering listener and gives Alertmanager temporary storage. It needs no receiver credentials and contacts no external notification destination.

## 3. Configure a local capture route

Save as `alertmanager.yml`:

```yaml
route:
  receiver: local-lab
  group_by: [alertname, instance]
  group_wait: 1s
  group_interval: 2s
  repeat_interval: 1h
receivers:
- name: local-lab
  webhook_configs:
  - url: http://127.0.0.1:19099/alerts
    send_resolved: false
```

Grouping by instance keeps the workers' notification groups separate. The short grouping values support a fast experiment; they are not production timing recommendations. Silence expiration changes eligibility, while routing, grouping, suppression and delivery conditions still determine when a notification is actually sent.

The alert payloads have a three-minute end time, longer than the twenty-second silence. That difference is deliberate: the silence must end while worker A's synthetic alert is still firing. Alert expiration and silence expiration are separate events.

## 4. Save the runtime verifier

Save as `drill.py`. Each run clears the previous JSON evidence and overwrites the runtime log; preserve evidence you need before rerunning. Use regular `python3`, without `-O`, because assertions perform part of the verification.

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

BASE = "http://127.0.0.1:19101"
messages = []
lock = threading.Lock()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        entry = {"receivedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "payload": payload}
        self.send_response(204)
        self.end_headers()
        with lock:
            messages.append(entry)
            with open("events.jsonl", "a", encoding="utf-8") as output:
                output.write(json.dumps(entry) + "\n")

    def log_message(self, *args):
        pass


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2) as response:
        body = response.read()
        return json.loads(body) if body else None


def wait_for(check, label, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def alerts():
    return {a["labels"]["instance"]: a for a in request("/api/v2/alerts")}


def delivered(instance):
    with lock:
        return any(a["labels"]["instance"] == instance and a["status"] == "firing"
                   for m in messages for a in m["payload"]["alerts"])


def save(name, data):
    Path(name).write_text(json.dumps(data, indent=2) + "\n")


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19101))
for name in ("silence.json", "before.json", "after.json"):
    Path(name).unlink(missing_ok=True)
Path("events.jsonl").write_text("")
server = ThreadingHTTPServer(("127.0.0.1", 19099), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix="am-silence-") as state:
        with open("alertmanager.log", "w") as log:
            process = subprocess.Popen([
                "./bin/alertmanager", "--config.file=alertmanager.yml",
                "--storage.path=" + state,
                "--web.listen-address=127.0.0.1:19101",
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
                wait_for(ready, "Alertmanager readiness", 10)
                now = dt.datetime.now(dt.timezone.utc)
                silence_until = now + dt.timedelta(seconds=20)
                matchers = [{"name": name, "value": value,
                             "isRegex": False, "isEqual": True}
                            for name, value in [("alertname", "SilenceLab"),
                                                ("instance", "worker-a")]]
                silence_id = request("/api/v2/silences", {
                    "matchers": matchers, "startsAt": stamp(now),
                    "endsAt": stamp(silence_until), "createdBy": "silence-lab",
                    "comment": "Disposable worker-a silence expiry test",
                })["silenceID"]
                silence_path = "/api/v2/silence/" + silence_id
                save("silence.json", request(silence_path))

                def alert(instance):
                    return {"labels": {"alertname": "SilenceLab", "instance": instance},
                            "startsAt": stamp(now - dt.timedelta(seconds=1)),
                            "endsAt": stamp(now + dt.timedelta(minutes=3))}
                request("/api/v2/alerts", [alert("worker-a"), alert("worker-b")])

                def scoped():
                    current = alerts()
                    a, b = current.get("worker-a", {}), current.get("worker-b", {})
                    return (silence_id in a.get("status", {}).get("silencedBy", [])
                            and b.get("status", {}).get("state") == "active"
                            and not b["status"]["silencedBy"])
                wait_for(scoped, "A silenced while B stays active", 5)
                wait_for(lambda: delivered("worker-b"), "B notification", 5)
                assert request(silence_path)["status"]["state"] == "active"
                assert not delivered("worker-a")
                save("before.json", alerts())
                print("PASS: A silenced; B delivered during the active silence")

                wait_for(lambda: request(silence_path)["status"]["state"] == "expired",
                         "natural silence expiration", 35)
                wait_for(lambda: delivered("worker-a"), "A notification after expiry", 10)
                current = alerts()
                assert current["worker-a"]["status"]["state"] == "active"
                assert not current["worker-a"]["status"]["silencedBy"]
                with lock:
                    for entry in messages:
                        for item in entry["payload"]["alerts"]:
                            if item["labels"]["instance"] == "worker-a":
                                assert dt.datetime.fromisoformat(entry["receivedAt"]) >= silence_until
                save("after.json", {"silence": request(silence_path), "alerts": current})
                print("PASS: silence expired naturally; still-firing A reached the webhook")
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

The silence is created before either alert is submitted. The script requires worker B's delivery while the silence still reports active, rather than treating a notification arriving after expiration as proof of correct scope. It also checks every captured worker-A timestamp against the silence's end time, so an early notification cannot satisfy the final assertion.

All generated timestamps use UTC on the same lab host. The waits are bounded observations, not service-level guarantees. A clock adjustment, busy host or changed release behavior can fail the test and needs investigation. Do not replace an explicit status or payload check with a fixed sleep and an assumption.

## 5. Run and inspect the lifecycle

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Require configuration validation and both PASS lines. A timeout or traceback means failure. The test should take roughly the silence duration plus setup and grouping time, but its result depends on the required observations, not a specific elapsed value.

Inspect the saved API evidence:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
silence = json.loads(Path("silence.json").read_text())
before = json.loads(Path("before.json").read_text())
after = json.loads(Path("after.json").read_text())
print("silence:", silence["id"], silence["startsAt"], silence["endsAt"])
print("initial:", {k: v["status"] for k, v in before.items()})
print("final silence:", after["silence"]["status"])
print("final alerts:", {k: v["status"] for k, v in after["alerts"].items()})
PYCODE
```

Expected evidence is worker A initially suppressed by the created silence ID, worker B active without a silence, and a final silence state of `expired`. Worker A should then be active without `silencedBy` entries. `events.jsonl` records each notification's receive time and payload; `alertmanager.log` provides runtime context. Keep both alongside the JSON snapshots when reviewing a failure.

As a controlled negative check, back up the verifier and remove the `("instance", "worker-a")` pair from the matchers list. Leave the alert-name matcher and both alert payloads unchanged. The initial scope check should time out because the broad silence also suppresses worker B. Restore the two-matcher version and require another passing run. Keep this mutation confined to the disposable lab.

## 6. Use silences with a clear end condition

For a real maintenance operation, record the reason, responsible operator, target label set and reviewed time window. Preview the affected alerts and verify that a representative out-of-scope alert remains unaffected. Inspect both the silence and alert states when maintenance ends; a quiet destination can also mean a delivery failure or another suppression rule.

This lab covers an immediately active silence with natural expiration. Scheduled pending silences, overlapping silences, manual early expiration, multiple replicas, restarts and persisted state need separate tests. It does not establish instantaneous delivery at the expiration boundary, delivery through real integrations, or recovery of the underlying service.

The verifier terminates its disposable Alertmanager, shuts down the webhook and removes temporary state on exit. The short silence therefore never persists on a live monitoring service. Preserve the evidence you need, then remove the lab directory. If you separately create a real silence, keep its ID and review its scope before editing or expiring it; do not delete unrelated silences as a rollback shortcut.

## Official references

Reviewed November 25, 2026:

- [Alertmanager silence semantics](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Pinned API v2 silence and alert-status schema](https://github.com/prometheus/alertmanager/blob/v0.28.1/api/v2/openapi.yaml)
- [Alertmanager routing and grouping configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
- [Python threaded HTTP server](https://docs.python.org/3/library/http.server.html)
