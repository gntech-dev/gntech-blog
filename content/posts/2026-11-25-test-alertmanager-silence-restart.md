---
title: "Verify Alertmanager Silences Survive a Controlled Restart"
description: "Restart a disposable Alertmanager with the same storage directory, compare the restored silence, and verify its scope after alerts are resubmitted."
date: 2026-11-25T17:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, maintenance, recovery]
keywords: [Alertmanager silence persistence, storage.path, controlled restart, silence snapshot]
summary: "A local API drill separates persisted silence state from transient alerts and detects restarting against an empty storage directory."
cover:
  image: "/images/posts/alertmanager-silence-restart/featured.webp"
  alt: "An open metal archival box holding a notebook and small brass bell beside an external drive, laptop and homelab server at dusk."
  caption: "AI-generated conceptual editorial artwork; not a storage diagram or deployment screenshot."
  relative: false
---

A maintenance silence can be correctly scoped and still disappear operationally if a replacement process starts with the wrong storage directory. A successful readiness response only proves that Alertmanager is serving requests. It does not prove that the expected silence was loaded.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) creates one scoped silence, stops a disposable Alertmanager cleanly, and starts it again with the same storage path. The verifier compares the silence ID and fields, then resubmits synthetic alerts and checks the restored silence's scope through API status.

Preparation status: configuration validation and the controlled restart drill passed locally with checksum-verified Alertmanager/amtool 0.28.1. This is a historical isolated lab baseline, not a current production version recommendation. Repeat with the release used by the intended deployment. No production restart, external notification, backup restoration, upgrade, unclean crash or GNTECH rollout was exercised.

## 1. Separate silence state from alert state

Alertmanager persists silences and its notification log in local snapshot files. Alerts themselves are not persisted; producers such as Prometheus resend firing alerts. Keeping the configuration file alone is therefore not the same as preserving runtime state.

| Item | What this drill checks |
| --- | --- |
| Configuration | The same local file is supplied to both processes. |
| Silence snapshot | A nonempty `silences` file exists after the first clean stop. Its size and checksum are recorded. |
| Restored silence | The same ID, matchers, time bounds, creator and comment are returned after restart. |
| Alert list | Starts empty on the second process in this isolated pinned lab. |
| Resubmitted alerts | Worker A is silenced by the restored ID; worker B stays active without a silence. |

The receiver has no integrations, so this experiment checks state and suppression status without sending notifications. It does not validate the notification log or deduplication behavior merely because those files share a storage directory.

The pinned implementation loads silence state from the configured storage path and performs a final snapshot during orderly shutdown. This test sends SIGTERM, requires a clean exit and then verifies the loaded result. It makes no claim about SIGKILL, sudden power loss, disk failure or the durability of unsnapshotted changes.

## 2. Prepare an isolated lab

Use Linux x86-64, Python 3.11+, Bash, curl, tar and sha256sum. Reserve loopback port 19102. Use an ordinary account, a fresh directory and the disposable processes started by this script. Do not substitute an existing service's PID or data directory.

```bash
mkdir silence-restart-lab
cd silence-restart-lab
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

Continue only after checksum verification succeeds. The web listener binds to loopback and the clustering listener is disabled. A temporary storage directory is kept across the two child processes and removed only when the drill exits. No credentials or live receiver are required.

## 3. Use a receiver that cannot page anyone

Save as `alertmanager.yml`:

```yaml
route:
  receiver: lab-discard
receivers:
- name: lab-discard
```

This is a synthetic discard route. Both alerts enter Alertmanager, but the receiver has no notification integrations. Do not promote this fixture as a production routing configuration.

The silence will require both `alertname="RestartLab"` and `instance="worker-a"`. Its five-minute duration leaves time for the short controlled restart; both synthetic alerts have three-minute end times. The test must finish while those time bounds remain valid.

## 4. Save the restart verifier

Save as `drill.py`. It replaces the prior JSON evidence and overwrites `alertmanager.log` on each run, so preserve evidence you need before rerunning. Use regular `python3`, without `-O`, because assertions perform part of the checks.

```python
import datetime as dt
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:19102"


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
            raise RuntimeError("Alertmanager exited; inspect alertmanager.log")
        try:
            with urllib.request.urlopen(BASE + "/-/ready", timeout=1) as r:
                return r.status == 200
        except urllib.error.URLError:
            return False
    wait_for(check, "Alertmanager readiness")


def start(state, log):
    return subprocess.Popen([
        "./bin/alertmanager", "--config.file=alertmanager.yml",
        "--storage.path=" + str(state),
        "--web.listen-address=127.0.0.1:19102", "--cluster.listen-address=",
    ], stdout=log, stderr=subprocess.STDOUT)


def stop(process):
    process.terminate()  # SIGTERM on Linux; require a clean exit for the test.
    try:
        code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise RuntimeError("Graceful stop timed out; test failed")
    assert code == 0, code


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def alerts():
    return {a["labels"]["instance"]: a for a in request("/api/v2/alerts")}


def scope(silence_id):
    current = alerts()
    a, b = current.get("worker-a", {}), current.get("worker-b", {})
    return (silence_id in a.get("status", {}).get("silencedBy", [])
            and b.get("status", {}).get("state") == "active"
            and not b["status"]["silencedBy"])


def save(name, value):
    Path(name).write_text(json.dumps(value, indent=2) + "\n")


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 19102))
for name in ("before.json", "snapshot.json", "after.json"):
    Path(name).unlink(missing_ok=True)
with tempfile.TemporaryDirectory(prefix="am-restart-") as directory:
    state = Path(directory)
    process = None
    with open("alertmanager.log", "w") as log:
        try:
            process = start(state, log)
            ready(process)
            now = dt.datetime.now(dt.timezone.utc)
            matchers = [{"name": name, "value": value,
                         "isRegex": False, "isEqual": True}
                        for name, value in [("alertname", "RestartLab"),
                                            ("instance", "worker-a")]]
            silence_id = request("/api/v2/silences", {
                "matchers": matchers, "startsAt": stamp(now),
                "endsAt": stamp(now + dt.timedelta(minutes=5)),
                "createdBy": "restart-lab", "comment": "Disposable restart drill",
            })["silenceID"]
            path = "/api/v2/silence/" + silence_id
            before = request(path)
            assert before["status"]["state"] == "active"
            payload = [{"labels": {"alertname": "RestartLab", "instance": instance},
                        "startsAt": stamp(now - dt.timedelta(seconds=1)),
                        "endsAt": stamp(now + dt.timedelta(minutes=3))}
                       for instance in ("worker-a", "worker-b")]
            request("/api/v2/alerts", payload)
            wait_for(lambda: scope(silence_id), "scope before restart")
            save("before.json", {"silence": before, "alerts": alerts()})

            stop(process)
            snapshot = state / "silences"
            raw = snapshot.read_bytes()
            assert raw
            save("snapshot.json", {"storage_path": str(state), "file": "silences",
                                   "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            restart_state = state
            process = start(restart_state, log)
            ready(process)
            after = request(path)  # No new silence is created after restart.
            for key in ("id", "matchers", "startsAt", "endsAt", "createdBy", "comment"):
                assert after[key] == before[key], key
            assert after["status"]["state"] == "active"
            assert request("/api/v2/alerts") == []
            print("PASS: same silence ID and fields loaded; alert list starts empty")

            request("/api/v2/alerts", payload)  # Producer resends firing alerts.
            wait_for(lambda: scope(silence_id), "scope after resubmission")
            save("after.json", {"silence": after, "alerts": alerts()})
            stop(process)
            print("PASS: restored silence suppresses A; B stays active after resubmission")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
```

The second process uses `restart_state = state`: the same temporary directory, not another directory with the same configuration. The only silence creation happens before the first stop. If the silence is missing after restart, the GET by its original ID fails rather than silently recreating it.

The script deliberately submits the alert payload twice, once before and once after restart. That second submission represents a producer sending firing alerts again. It is not evidence that the alert list survived the restart. The same silence ID must suppress worker A in both phases, while worker B remains outside its scope.

## 5. Run and inspect the evidence

```bash
./bin/amtool check-config alertmanager.yml
python3 drill.py
```

Require configuration validation and both PASS lines. A timeout, assertion or HTTP error is a failed drill. If the controlled stop needs a forced kill, the test fails even though cleanup still prevents an orphaned process.

Inspect the evidence independently:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path
before = json.loads(Path("before.json").read_text())
after = json.loads(Path("after.json").read_text())
snapshot = json.loads(Path("snapshot.json").read_text())
print("IDs:", before["silence"]["id"], after["silence"]["id"])
print("snapshot evidence:", snapshot)
print("before:", {k: v["status"] for k, v in before["alerts"].items()})
print("after:", {k: v["status"] for k, v in after["alerts"].items()})
PYCODE
```

Expect identical silence IDs, active silence state and the same matcher/time fields. In both alert snapshots, A should include that ID in `silencedBy`, while B should be active without a silence. Keep `alertmanager.log` with the JSON files if any check fails.

`snapshot.json` records the file measured after the first stop. Its checksum identifies that observed snapshot; it is not a saved backup and does not validate another host's storage. The temporary path recorded there no longer exists after cleanup. A real backup-and-restore exercise needs a separate retained artifact and independent restoration checks.

## 6. Prove an empty storage path is detected

As a controlled negative check, back up the script and change only this assignment:

```python
restart_state = state / "empty-state"
```

Run the drill again. The replacement process can become ready with its new empty directory, but the GET for the original silence should return HTTP 404 and fail the test. A successful startup is insufficient evidence of restored state. Inspect the actual error; a bind failure or malformed file is not the same negative result.

Restore `restart_state = state` and require another passing run. Do not simulate state loss by deleting a real monitoring directory. This experiment uses a second disposable directory and leaves the first process's snapshot intact until normal lab cleanup.

## 7. Apply the check to an operational restart

Before a separately authorized real restart, record the intended storage path or volume mapping, ownership and permissions, and the silence IDs and time windows that must remain. Keep the previous reviewed configuration. After the process returns, check representative silence IDs and fields and verify how the real alert producer repopulates alerts; do not equate readiness with state recovery.

If the expected silence is absent, investigate storage mapping, access errors and startup logs before treating the instance as recovered. Preserve the original state and follow your recovery procedure. Avoid creating a replacement silence as a shortcut to claiming that persistence succeeded.

This lab does not test replicas or gossip, upgrades, notification deduplication, unclean shutdown, backup restoration, or delivery through a real receiver. It also does not establish that a production filesystem or volume will survive host failure. Those boundaries need their own evidence.

The verifier terminates only its own child processes and removes its temporary storage on exit. Keep the JSON evidence and log as needed, then remove the lab directory. No live service needs rollback because none was changed.

## Official references

Reviewed November 25, 2026:

- [Alertmanager state persistence and alert resending](https://prometheus.io/docs/alerting/latest/high_availability/)
- [Alert API client expectations](https://prometheus.io/docs/alerting/latest/alerts_api/)
- [Pinned storage path and shutdown wiring](https://github.com/prometheus/alertmanager/blob/v0.28.1/cmd/alertmanager/main.go)
- [Pinned silence snapshot maintenance](https://github.com/prometheus/alertmanager/blob/v0.28.1/silence/silence.go)
- [Pinned API v2 schema](https://github.com/prometheus/alertmanager/blob/v0.28.1/api/v2/openapi.yaml)
- [Alertmanager 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1)
