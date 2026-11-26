---
title: "Test Alertmanager Reload Rejection and Rollback"
description: "Reject an invalid receiver reference, verify the active route still delivers, then apply a valid correction and roll it back without restarting Alertmanager."
date: 2026-11-26T17:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, configuration, reliability]
keywords: [Alertmanager reload test, invalid configuration, rollback, active route verification]
summary: "A disposable local lab checks the configuration on disk, the loaded configuration and actual webhook delivery through rejection, correction and rollback."
cover:
  image: "/images/posts/alertmanager-reload/featured.webp"
  alt: "A dark-blue notebook and folded sheet with a red wax seal on a brass tray beside an open notebook, laptop and homelab server at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

A rejected configuration reload leaves an important distinction: the file on disk can be wrong while the process continues using its previous working configuration. Readiness alone cannot tell you which route is active. Neither can the contents of the file you just edited.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) tests that distinction on a disposable Alertmanager. It installs a known invalid receiver reference, requires reload rejection, and checks delivery through the prior route. It then applies a valid route change and restores the original route, verifying both with local webhook payloads without restarting the process.

Preparation status: the local runtime drill passed with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat with the release used by the intended deployment. No live monitoring configuration, production reload, real paging destination or GNTECH rollout was exercised.

## 1. Check three kinds of evidence

| Phase | File installed on disk | Required loaded route | Fresh probe destination |
| --- | --- | --- | --- |
| Before change | Original valid configuration | `local-old` | `/old` |
| After rejected reload | Undefined receiver `missing-lab` | Original configuration retained | `/old` |
| After valid correction | Root receiver changed to `local-new` | Corrected configuration | `/new` |
| After rollback | Original valid file restored | Original configuration restored | `/old` |

The invalid candidate is valid YAML but refers to a receiver that does not exist. Configuration validation should reject that reference. The lab deliberately bypasses that failed guard only to exercise rejection on its own disposable process; normal operations should validate and stop before installing a failed candidate.

Alertmanager supports reload through `POST /-/reload` or SIGHUP. This lab uses HTTP so the response can be recorded. On the pinned release, the tested invalid reference returns HTTP 500, while the valid correction and rollback return HTTP 200. Those status checks are version-specific observations, not a substitute for checking loaded state and delivery.

## 2. Prepare the isolated tools

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback ports 19105 for the webhook and 19106 for Alertmanager. Use an ordinary account and a fresh directory. The script must own the process and all files it changes.

```bash
mkdir reload-lab
cd reload-lab
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

Continue only after checksum verification succeeds. Both listeners bind to loopback, clustering is disabled, and storage is temporary. No receiver credential or external notification service is needed. Do not replace these paths or listeners with a live monitoring deployment.

## 3. Save the original configuration

Save as `alertmanager.yml`:

```yaml
route:
  receiver: local-old
  group_by: [alertname, instance]
  group_wait: 1s
  group_interval: 2s
  repeat_interval: 1h
receivers:
- name: local-old
  webhook_configs:
  - url: http://127.0.0.1:19105/old
    send_resolved: false
- name: local-new
  webhook_configs:
  - url: http://127.0.0.1:19105/new
    send_resolved: false
```

Both named receivers exist from the start. The root initially selects `local-old`; the valid correction changes only that selection. The two paths share one local capture server, which records both the URL path and the receiver name in each webhook.

Each phase uses a fresh `instance` label so it creates a distinct group. Older synthetic alerts can also be routed again after a configuration change. The verifier therefore filters for the current phase's alert rather than assuming an exact total notification count or arrival order.

## 4. Save the runtime verifier

Save as `drill.py`. It generates `invalid.yml` and `corrected.yml`, replaces the active lab file during the test, and restores the original file during cleanup. It overwrites its evidence and log files; retain any earlier evidence before rerunning. Use regular `python3`, without `-O`, because assertions perform part of the verification.

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

BASE = "http://127.0.0.1:19106"
config = Path("alertmanager.yml")
original = config.read_text()
assert original.count("receiver: local-old") == 1
corrected = original.replace("receiver: local-old", "receiver: local-new", 1)
invalid = original.replace("receiver: local-old", "receiver: missing-lab", 1)
events = []
lock = threading.Lock()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path not in ("/old", "/new"):
            self.send_error(404)
            return
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        with lock:
            entry = {"receivedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "path": self.path, "payload": payload}
            events.append(entry)
            with open("events.jsonl", "a", encoding="utf-8") as output:
                output.write(json.dumps(entry) + "\n")

    def log_message(self, *args):
        pass


def http(path, payload=None, method=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def api(path, payload=None):
    code, body = http(path, payload)
    assert code == 200, (path, code, body)
    return json.loads(body) if body else None


def wait_for(check, label):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def install(text):
    candidate = Path("candidate.tmp")
    candidate.write_text(text)
    candidate.replace(config)


def loaded():
    return api("/api/v2/status")["config"]["original"]


def send_and_check(phase, path, receiver):
    now = dt.datetime.now(dt.timezone.utc)
    api("/api/v2/alerts", [{
        "labels": {"alertname": "ReloadLab", "instance": phase},
        "startsAt": (now - dt.timedelta(seconds=1)).isoformat(),
        "endsAt": (now + dt.timedelta(minutes=3)).isoformat(),
    }])
    def delivered():
        with lock:
            return any(e["path"] == path and e["payload"]["receiver"] == receiver
                       and any(a["labels"]["instance"] == phase and a["status"] == "firing"
                               for a in e["payload"]["alerts"])
                       for e in events)
    wait_for(delivered, phase + " delivery")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19106))
Path("events.jsonl").write_text("")
Path("summary.json").unlink(missing_ok=True)
Path("invalid.yml").write_text(invalid)
Path("corrected.yml").write_text(corrected)
subprocess.run(["./bin/amtool", "check-config", "alertmanager.yml"], check=True)
subprocess.run(["./bin/amtool", "check-config", "corrected.yml"], check=True)
bad_check = subprocess.run(["./bin/amtool", "check-config", "invalid.yml"],
                           capture_output=True, text=True)
Path("invalid-check.txt").write_text(bad_check.stdout + bad_check.stderr)
assert bad_check.returncode != 0
server = ThreadingHTTPServer(("127.0.0.1", 19105), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
process = None
try:
    with tempfile.TemporaryDirectory(prefix="am-reload-") as state:
        with open("alertmanager.log", "w") as log:
            process = subprocess.Popen([
                "./bin/alertmanager", "--config.file=alertmanager.yml",
                "--storage.path=" + state, "--web.listen-address=127.0.0.1:19106",
                "--cluster.listen-address=",
            ], stdout=log, stderr=subprocess.STDOUT)
            def ready():
                if process.poll() is not None:
                    raise RuntimeError("Alertmanager exited; inspect alertmanager.log")
                try:
                    return http("/-/ready")[0] == 200
                except urllib.error.URLError:
                    return False
            wait_for(ready, "readiness")
            baseline = loaded()
            send_and_check("before", "/old", "local-old")

            install(invalid)
            rejected_code, rejected_body = http("/-/reload", method="POST")
            Path("rejected-reload.txt").write_bytes(rejected_body)
            assert rejected_code == 500, rejected_code
            assert loaded() == baseline
            send_and_check("after-invalid", "/old", "local-old")
            assert process.poll() is None
            print("PASS: invalid reload rejected; prior config and delivery retained")

            install(corrected)
            corrected_code, _ = http("/-/reload", method="POST")
            assert corrected_code == 200, corrected_code
            expected = baseline.replace("receiver: local-old", "receiver: local-new", 1)
            assert expected != baseline and loaded() == expected
            send_and_check("after-correction", "/new", "local-new")

            install(original)
            rollback_code, _ = http("/-/reload", method="POST")
            assert rollback_code == 200, rollback_code
            assert loaded() == baseline
            send_and_check("after-rollback", "/old", "local-old")
            assert process.poll() is None
            Path("summary.json").write_text(json.dumps({
                "pid": process.pid, "rejected_code": rejected_code,
                "corrected_code": corrected_code, "rollback_code": rollback_code,
                "baseline_config_sha256": digest(baseline),
                "rollback_config_sha256": digest(loaded()),
                "phases": {"before": "/old", "after-invalid": "/old",
                           "after-correction": "/new", "after-rollback": "/old"},
            }, indent=2) + "\n")
            print("PASS: valid correction and rollback delivered without process restart")
finally:
    install(original)
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

The file replacement uses a sibling temporary file followed by a rename. That avoids intentionally exposing a partially written file in this lab. It does not establish production filesystem durability or validate every deployment tool's file replacement behavior.

After rejection, the verifier compares the API's loaded configuration string with its baseline and sends a new alert to the expected old destination. For the correction, it compares against the expected change in the same API representation and checks `/new`. The API representation may differ from the source file's formatting; the test compares loaded representations rather than assuming byte identity with the YAML file.

The rollback restores both the file and the loaded route, then requires delivery through `/old` again. One subprocess serves all four phases. The script has no replacement-process or restart step.

## 5. Run and inspect the result

```bash
python3 drill.py
```

The script validates the original and corrected candidates with amtool. It also requires the invalid candidate to fail validation, then performs the intentional invalid reload against its own process. Require both PASS lines; a timeout, unexpected HTTP status or traceback is failure.

Inspect the evidence independently:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
print(Path("summary.json").read_text())
print(Path("invalid-check.txt").read_text())
print(Path("rejected-reload.txt").read_text())
for line in Path("events.jsonl").read_text().splitlines():
    e = json.loads(line)
    print(e["path"], e["payload"]["receiver"],
          [a["labels"]["instance"] for a in e["payload"]["alerts"]])
PYCODE
```

Expect the undefined-receiver diagnostic in the validation and reload evidence, response codes 500/200/200, and matching baseline/rollback hashes in the summary. For the named phase probes, require `/old`, `/old`, `/new`, then `/old`. Keep `alertmanager.log` with the JSONL capture when investigating a failure.

A successful HTTP 200 alone does not prove that a route reaches its destination. Likewise, a failed reload response alone does not prove that the previous configuration is still delivering. The verifier requires those observations separately.

## 6. Keep rejection and rollback distinct

Rejection retains the prior active configuration for this tested validation failure. It does not repair the invalid file on disk. Leaving that file in place can make a later restart fail even though the current process is still serving. Restore or correct the candidate through the reviewed change process before treating the operation as complete.

Rollback after a successful change is different: the corrected route really became active, so returning to the original requires installing and loading the original configuration again. This lab verifies that second transition rather than just putting an old file back on disk.

For a separately authorized deployment, validate the complete candidate with the matching amtool, preserve the reviewed previous file, and record the expected route behavior before reloading. Check the response, loaded representation, logs and representative destination delivery. Keep the management interface within your existing access controls; this loopback fixture does not configure production authentication or TLS.

The drill covers one undefined-receiver rejection and one simple route change. It does not establish atomic rollback for every template, integration or runtime failure. It also does not test replicas, remote proxies, credentials, real paging channels, concurrent edits or a process restart while the on-disk file is invalid.

On exit, the verifier restores the original lab file, terminates only its own Alertmanager, stops the capture server and removes temporary storage. The successful path also verifies a live rollback before cleanup. Preserve the evidence as needed, then remove the lab directory. No live service needs rollback because none was changed.

## Official references

Reviewed November 26, 2026:

- [Alertmanager configuration validation and reload behavior](https://prometheus.io/docs/alerting/latest/configuration/)
- [Reload and readiness management endpoints](https://prometheus.io/docs/alerting/latest/management_api/)
- [Pinned status API schema and loaded configuration field](https://github.com/prometheus/alertmanager/blob/v0.28.1/api/v2/openapi.yaml)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
