---
title: "Test Alertmanager Notification Deduplication After a Restart"
description: "Preserve the notification log across a clean restart, check for an immediate duplicate, and prove a changed alert group still delivers."
date: 2026-11-26T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, alerting, recovery]
keywords: [Alertmanager nflog, notification deduplication, controlled restart, repeat interval]
summary: "A local webhook drill distinguishes retained delivery history from a quiet or broken notification path."
cover:
  image: "/images/posts/alertmanager-dedup-restart/featured.webp"
  alt: "A blue envelope in a brass tray beside a leather ledger, seal and external drive on a homelab desk at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or exact system diagram."
  relative: false
---

A clean restart should not be treated as evidence that notification history was preserved. Alertmanager can become ready with an empty storage directory, accept the same firing alert again, and notify a receiver that already accepted it before the restart.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) tests a narrow claim: retaining local notification state avoids an immediate repeat of an unchanged group during a short observation window. It then adds an alert to that same group and requires delivery, so silence alone cannot pass as evidence of a healthy path.

Preparation status: configuration validation and the controlled local drill passed with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat on the intended release. No production restart, real paging channel, HA cluster, crash recovery or GNTECH rollout was exercised.

## 1. Separate deduplication from permanent suppression

Alertmanager stores notification history in its `nflog` snapshot. The pinned deduplication stage consults that history for the receiver and group, considers changes in firing/resolved alerts, and considers the repeat interval. An unchanged firing group can remain quiet before its repeat interval without being silenced.

| Phase | Required local observation |
| --- | --- |
| Initial send | Webhook accepts one firing notification containing the base alert. |
| Clean stop | A nonempty `nflog` snapshot exists in the chosen storage directory. |
| Restart and resubmit | No extra notification arrives during a six-second window; the second process logs multiple group flushes. |
| Add another alert to the same group | A new notification contains both base and probe alerts. |

The base alert intentionally appears again in the final updated group notification. That is a group update, not the unexpected immediate duplicate checked in the preceding phase. The test counts notifications and inspects their contents rather than assuming an alert fingerprint may only ever appear once.

This does not prove exactly-once delivery. Other failure modes, including ambiguous acknowledgments, replicas and partitions, can produce duplicates. A real receiver must handle its downstream effects accordingly. The test's six-second quiet period is bounded evidence, not a promise of silence forever.

## 2. Install the disposable lab tools

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback ports 19103 for the capture webhook and 19104 for Alertmanager. Use an ordinary account and a fresh directory. Do not substitute a live service's PID or storage directory.

```bash
mkdir dedup-restart-lab
cd dedup-restart-lab
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

Continue only after checksum verification succeeds. Both listeners bind to loopback. Clustering is disabled, and temporary state is retained across the two child processes before being removed at the end. No receiver credential or external paging service is needed.

## 3. Keep the group identity and receiver unchanged

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
  - url: http://127.0.0.1:19103/alerts
    send_resolved: false
```

Both synthetic alerts will share `alertname="DedupLab"` and `instance="worker-a"`. They differ in `kind`, which is deliberately excluded from `group_by`. Adding `kind="probe"` therefore changes the alert set in the existing notification group rather than creating a new group.

The two-second group interval allows several checks during the observation window. The one-hour repeat interval is much longer than the drill, so a routine repeat is not expected to satisfy the positive delivery check. These are lab timings, not production recommendations. The drill does not test delivery after the full repeat interval.

Keep the configuration, receiver/integration identity and grouping unchanged across this restart. Changes to those identities or policies need separate expectations; this experiment is specifically about keeping state for the same route and group.

## 4. Save the runtime verifier

Save as `drill.py`. It replaces previous evidence and overwrites both phase logs on each run; preserve files you need before rerunning. Use regular `python3`, without `-O`, because assertions perform part of the verification.

```python
import datetime as dt
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "http://127.0.0.1:19104"
events = []
lock = threading.Lock()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        with lock:
            entry = {"receivedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "payload": payload}
            events.append(entry)
            with open("events.jsonl", "a", encoding="utf-8") as output:
                output.write(json.dumps(entry) + "\n")

    def log_message(self, *args):
        pass


def captured():
    with lock:
        return list(events)


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2) as response:
        body = response.read()
        return json.loads(body) if body else None


def wait_for(check, label):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def ready(process):
    def check():
        if process.poll() is not None:
            raise RuntimeError("Alertmanager exited; inspect phase logs")
        try:
            with urllib.request.urlopen(BASE + "/-/ready", timeout=1) as r:
                return r.status == 200
        except urllib.error.URLError:
            return False
    wait_for(check, "Alertmanager readiness")


def start(state, log):
    return subprocess.Popen([
        "./bin/alertmanager", "--config.file=alertmanager.yml",
        "--storage.path=" + str(state), "--web.listen-address=127.0.0.1:19104",
        "--cluster.listen-address=", "--log.level=debug",
    ], stdout=log, stderr=subprocess.STDOUT)


def stop(process):
    process.terminate()
    try:
        code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("Graceful stop timed out; test failed")
    assert code == 0, code


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19104))
Path("events.jsonl").write_text("")
Path("summary.json").unlink(missing_ok=True)
server = ThreadingHTTPServer(("127.0.0.1", 19103), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
process = None
try:
    with tempfile.TemporaryDirectory(prefix="am-nflog-") as directory:
        state = Path(directory)
        with open("phase1.log", "w") as log1, open("phase2.log", "w") as log2:
            process = start(state, log1)
            ready(process)
            now = dt.datetime.now(dt.timezone.utc)
            base = {"labels": {"alertname": "DedupLab", "instance": "worker-a", "kind": "base"},
                    "startsAt": (now - dt.timedelta(seconds=1)).isoformat(),
                    "endsAt": (now + dt.timedelta(minutes=3)).isoformat()}
            request("/api/v2/alerts", [base])
            wait_for(lambda: len(captured()) == 1, "initial notification")
            wait_for(lambda: 'msg="Notify success"' in Path("phase1.log").read_text(),
                     "initial sender success")
            first = captured()[0]["payload"]
            assert first["status"] == "firing" and len(first["alerts"]) == 1
            assert first["alerts"][0]["labels"] == base["labels"]
            stop(process)
            raw = (state / "nflog").read_bytes()
            assert raw
            restart_state = state
            process = start(restart_state, log2)
            ready(process)
            assert request("/api/v2/alerts") == []
            request("/api/v2/alerts", [base])
            wait_for(lambda: len(request("/api/v2/alerts")) == 1, "resubmitted alert")
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                assert len(captured()) == 1, "Unexpected duplicate in restart observation window"
                assert process.poll() is None
                time.sleep(0.1)
            assert len(captured()) == 1
            flushes = Path("phase2.log").read_text().count("msg=flushing")
            assert flushes >= 2, "Expected multiple group flushes on the pinned release"
            print("PASS: no duplicate during six-second restart observation window")

            added = dict(base)
            added["labels"] = dict(base["labels"], kind="probe")
            request("/api/v2/alerts", [added])
            wait_for(lambda: len(captured()) >= 2, "changed group notification")
            latest = captured()[-1]["payload"]
            assert len(captured()) == 2
            assert latest["status"] == "firing"
            assert latest["groupKey"] == first["groupKey"]
            assert {a["labels"]["kind"] for a in latest["alerts"]} == {"base", "probe"}
            original = next(a for a in latest["alerts"] if a["labels"]["kind"] == "base")
            assert original["fingerprint"] == first["alerts"][0]["fingerprint"]
            Path("summary.json").write_text(json.dumps({
                "nflog_bytes": len(raw), "nflog_sha256": hashlib.sha256(raw).hexdigest(),
                "observation_seconds": 6, "phase2_flushes": flushes,
                "notifications_before_change": 1, "notifications_after_change": len(captured()),
            }, indent=2) + "\n")
            stop(process)
            print("PASS: changed group delivered base and probe after restart")
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    server.shutdown()
    server.server_close()
    thread.join()
```

The capture server stays running while Alertmanager is stopped and started, so the notification count spans both processes. The script waits for initial receiver acceptance and sender success before the first clean stop. It then requires a nonempty notification-log snapshot and reuses the same storage directory.

Alerts themselves are not persisted. The script checks the empty alert list on the new process and resubmits the unchanged base payload, representing a producer sending its firing alert again. It does not delete the first notification from the capture history.

During the six-second observation window, every poll requires the count to stay at one. The log check additionally requires at least two group flushes from the second process. That debug-log string matches the pinned release; review it if the deployed release changes logging. A missing log observation is a failed test requiring investigation, not automatic proof of a delivery defect.

## 5. Run and inspect both negative and positive observations

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Require configuration validation and both PASS lines. A timeout or traceback is failure. The script requires clean SIGTERM exits; a forced kill needed during the controlled stop fails the drill even though cleanup still prevents an orphaned process.

After the quiet window, the verifier submits only the probe alert. The base remains firing with a future end time. The next captured notification must have the same group key, include both kinds, and preserve the base fingerprint. This positive observation checks delivery for the original group rather than treating absence of traffic as enough evidence.

Inspect the summary and captured messages:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
print(Path("summary.json").read_text())
for line in Path("events.jsonl").read_text().splitlines():
    e = json.loads(line)
    p = e["payload"]
    print(e["receivedAt"], p["status"],
          sorted(a["labels"]["kind"] for a in p["alerts"]))
PYCODE
```

Expect two messages in total: the initial base notification and the changed-group notification containing base and probe. The summary records a six-second window, multiple second-process group flushes, and the snapshot's measured size and checksum. Actual flush counts and timestamps can vary. Keep `phase1.log` and `phase2.log` with the capture when diagnosing failures.

The checksum identifies the observed snapshot; it is not a saved backup. Temporary state is removed after the drill, and this test does not validate storage durability or recovery on another host. The capture's HTTP 204 means local endpoint acceptance, not a human page or a completed business action.

## 6. Prove that losing history is detected

Back up the script and change only this assignment for a controlled negative check:

```python
restart_state = state / "empty-state"
```

Run it again. The replacement process should become ready with its separate empty directory, but the resubmitted base alert should produce another notification and fail the quiet-window assertion. Inspect the actual error: a missing binary or a bind failure is not the intended regression.

Restore `restart_state = state` and require another passing run. Do not simulate loss of history by deleting a real monitoring directory. This experiment uses a second disposable directory and leaves the original snapshot intact until normal cleanup.

## 7. Apply the result within its boundaries

For a separately authorized restart, verify the intended storage mapping and permissions, retain the reviewed configuration, and choose representative groups whose recent deliveries can be checked independently. Do not infer notification-history recovery merely because the web endpoint is ready or a silence ID is present.

Preserving local state is one part of the behavior. A changed group, elapsed repeat interval, different receiver identity or another failure scenario needs its own expected outcome. Receivers should tolerate duplicates, and a production check should include downstream processing and the real producer's resend behavior.

This lab covers one instance, one integration, unchanged configuration, successful local acknowledgments and an orderly restart. It does not validate HA gossip, partitions, crashes, upgrades, resolved notifications, retention expiry, long outages or exactly-once effects.

The verifier terminates only its own processes, stops its capture server and removes temporary Alertmanager storage on exit. Keep the evidence as needed, then remove the lab directory. No live configuration or receiver needs rollback because none was changed.

## Official references

Reviewed November 26, 2026:

- [Alertmanager notification history and persistence](https://prometheus.io/docs/alerting/latest/high_availability/)
- [Route grouping and repeat intervals](https://prometheus.io/docs/alerting/latest/configuration/)
- [Pinned deduplication and notification pipeline](https://github.com/prometheus/alertmanager/blob/v0.28.1/notify/notify.go)
- [Alertmanager API client expectations](https://prometheus.io/docs/alerting/latest/alerts_api/)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
