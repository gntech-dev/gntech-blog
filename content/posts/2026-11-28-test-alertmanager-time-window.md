---
title: "Test an Alertmanager Notification Time Window"
description: "Run an isolated Alertmanager drill across a one-minute UTC active interval and verify scheduled delivery against an always-active control route."
date: 2026-11-28T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, monitoring, testing, homelab]
keywords: [Alertmanager active_time_intervals, notification schedule test, Alertmanager time window, UTC alert routing]
summary: "A loopback-only runtime drill checks notifications before, inside, and after an active time interval without changing the host clock."
cover:
  image: "/images/posts/alertmanager-time-window/featured.webp"
  alt: "A brass hourglass and notification envelope on a warmly lit desk beside a small home server, overlooking a mountain lake at dusk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

A receiver can work perfectly during office hours and appear broken when its active interval closes. The useful question is whether Alertmanager is withholding the scheduled notification or the delivery path has failed.

This companion to [Infrastructure Series Part 11 — Monitoring and Observability](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) answers that question in an isolated lab. We cross a real one-minute UTC window, keep an independent control route active, and inspect captured webhook timestamps. The host clock stays unchanged.

## Verification status

| Area | Evidence and limits |
|---|---|
| Preparation | Official configuration and management documentation, including the pinned configuration reference, reviewed November 28, 2026. |
| Executed locally | Checksum-verified Alertmanager/amtool 0.28.1 passed configuration validation and the before/inside/after runtime drill. Removing the active-interval reference produced the intended early-notification failure. |
| Version assumption | 0.28.1 is a historical isolated lab baseline, not a current production recommendation. Rerun with the release you intend to deploy. |
| Not exercised | No production schedule, external paging service, Prometheus rule evaluation, reload, replicas, daylight-saving transition, or long-term recurrence. This is bounded loopback delivery evidence. |

## 1. Understand what an active interval changes

The [official configuration reference](https://prometheus.io/docs/alerting/latest/configuration/) defines `active_time_intervals` on a route. A nonempty list restricts when that route may send notifications. An empty or omitted list leaves it always active. Named definitions live under `time_intervals`; the root route cannot have active times.

An inactive route still participates in route matching. It does not automatically fall through to another receiver when the clock leaves its window. Keep `continue` and the complete route tree under separate review when designing a day/night handoff.

| Route in this lab | Matcher | Time restriction | Destination |
|---|---|---|---|
| Scheduled child | `scope="scheduled"` | One generated UTC minute | Local `/scheduled` webhook |
| Control child | `scope="control"` | None | Local `/control` webhook |
| Root fallback | Any unmatched alert | None | Receiver with no integrations |

Both webhook paths are served by the same disposable local process, so successful control delivery is a useful comparison. It does not prove the availability of a different real-world destination.

The documented interval start is inclusive and its end exclusive. Delivery itself is checked at notification processing opportunities, with grouping and transport delay. This lab samples just outside and inside the window; it does not measure exact subsecond boundary behavior or promise delivery at the opening instant.

## 2. Prepare the isolated lab

Use Linux amd64, Python 3, Bash, `curl`, `tar`, `awk`, and `sha256sum`. Allow roughly two to three minutes for the positive run, sometimes longer near midnight. Keep the host clock synchronized and stable. The script uses the actual UTC clock; do not adjust it to accelerate the test.

Run the blocks in one Bash session. No root access, account credentials, containers, or production configuration are needed. The binaries bind only to `127.0.0.1`; cluster listening is disabled. The Python webhook chooses a free port and the Alertmanager port is selected locally. If another process takes that port before startup, the readiness check fails and the log identifies the problem.

```bash
set -euo pipefail
lab_dir="$(mktemp -d -t gntech-time-window-XXXXXX)"
cd "$lab_dir"
umask 077
version=0.28.1
archive="alertmanager-${version}.linux-amd64.tar.gz"
release="https://github.com/prometheus/alertmanager/releases/download/v${version}"
curl --fail --location --retry 3 "$release/$archive" -o "$archive"
curl --fail --location --retry 3 "$release/sha256sums.txt" -o sha256sums.txt
awk -v file="$archive" '$2 == file {print; found=1} END {if(!found)exit 1}' \
  sha256sums.txt > selected-checksum.txt
sha256sum --check selected-checksum.txt
tar -xzf "$archive" --strip-components=1 \
  "alertmanager-${version}.linux-amd64/amtool" \
  "alertmanager-${version}.linux-amd64/alertmanager"
./alertmanager --version
./amtool --version
```

The checksum verifies the downloaded bytes against the official release file; it is not an independent publisher signature. Keep the checksum and version output with your review evidence.

## 3. Create the boundary drill

The script generates a complete configuration with `group_wait: 1s`, `group_interval: 2s`, and `repeat_interval: 10m`. Those short grouping times are lab settings. Alerts are grouped by `scope` and `phase`, so each fresh phase forms a distinct group. Their explicit end times keep them firing throughout the drill; no repeated submissions are needed to keep the earlier group alive.

It chooses an upcoming minute with startup margin, sets `location: UTC`, and constrains the interval to its UTC day, month, and year. Near midnight it avoids a time range that wraps through `00:00`. It records the full opening/closing timestamps before starting the process.

The three stages are:

1. **Before:** submit scheduled and control alerts. Require control delivery and a quiet scheduled route over the short observation window.
2. **Inside:** submit a fresh pair after opening. Require both scheduled groups—the earlier still-firing one and the new one—to reach the webhook, plus the control group. Check their receive timestamps are inside the active window.
3. **After:** submit another fresh pair after closing. Require control delivery and no scheduled notification for that new group during the bounded observation window.

The evidence directory must not already exist. That protects earlier results and ensures each run has clean history and fresh process storage. Use a new workspace for every rerun.

```bash
cat > drill.py <<'PYTHON'
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen

UTC = timezone.utc
evidence = Path("evidence")
evidence.mkdir()  # Refuse to overwrite a previous run.
lock = threading.Lock()
events = []

def now():
    return datetime.now(UTC)

def stamp(value):
    return value.isoformat().replace("+00:00", "Z")

class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        event = {"at": stamp(now()), "path": self.path, "body": body}
        with lock:
            events.append(event)
            with (evidence / "notifications.jsonl").open("a") as output:
                output.write(json.dumps(event) + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass

hook = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
threading.Thread(target=hook.serve_forever, daemon=True).start()
with socket.socket() as reservation:
    reservation.bind(("127.0.0.1", 0))
    api_port = reservation.getsockname()[1]
api = f"http://127.0.0.1:{api_port}"
start = now().replace(second=0, microsecond=0) + timedelta(minutes=1)
if (start - now()).total_seconds() < 20:
    start += timedelta(minutes=1)
# Keep the minute window within one UTC date, even near midnight.
if start.hour == 23 and start.minute == 59:
    start += timedelta(minutes=1)
end = start + timedelta(minutes=1)
window = {"start": stamp(start), "end": stamp(end), "api": api}
(evidence / "window.json").write_text(json.dumps(window, indent=2) + "\n")
config = f'''route:
  receiver: discard
  group_by: [scope, phase]
  group_wait: 1s
  group_interval: 2s
  repeat_interval: 10m
  routes:
  - receiver: scheduled
    matchers: ['scope="scheduled"']
    active_time_intervals: [lab-window]
  - receiver: control
    matchers: ['scope="control"']
receivers:
- name: discard
- name: scheduled
  webhook_configs:
  - url: 'http://127.0.0.1:{hook.server_port}/scheduled'
    send_resolved: false
- name: control
  webhook_configs:
  - url: 'http://127.0.0.1:{hook.server_port}/control'
    send_resolved: false
time_intervals:
- name: lab-window
  time_intervals:
  - times:
    - start_time: '{start:%H:%M}'
      end_time: '{end:%H:%M}'
    days_of_month: ['{start.day}']
    months: ['{start.month}']
    years: ['{start.year}']
    location: UTC
'''
if "--without-window" in sys.argv:
    config = config.replace("    active_time_intervals: [lab-window]\n", "")
Path("alertmanager.yml").write_text(config)
subprocess.run(["./amtool", "check-config", "alertmanager.yml"], check=True)
log = (evidence / "alertmanager.log").open("w")
process = None

def wait_for(test, seconds, description):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Alertmanager exited; inspect evidence/alertmanager.log")
        if test():
            return
        time.sleep(0.2)
    raise RuntimeError(f"Timeout: {description}")

def ready():
    try:
        with urlopen(api + "/-/ready", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False

def seen(scope, phase):
    with lock:
        return [event for event in events if event["path"] == "/" + scope
                and event["body"]["groupLabels"].get("phase") == phase]

def send(phase):
    alerts = [{
        "labels": {"alertname": "WindowProbe", "scope": scope, "phase": phase},
        "annotations": {"summary": f"Synthetic {scope} {phase} probe"},
        "startsAt": stamp(now() - timedelta(seconds=1)),
        "endsAt": stamp(end + timedelta(minutes=2)),
    } for scope in ("scheduled", "control")]
    with urlopen(Request(api + "/api/v2/alerts", data=json.dumps(alerts).encode(),
                         headers={"Content-Type": "application/json"}), timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected alert submission status: {response.status}")

def pause_until(target):
    while now() < target:
        if process.poll() is not None:
            raise RuntimeError("Alertmanager exited during boundary wait")
        time.sleep(min(0.2, max(0, (target - now()).total_seconds())))

try:
    process = subprocess.Popen([
        "./alertmanager", "--config.file=alertmanager.yml",
        "--storage.path=state", f"--web.listen-address=127.0.0.1:{api_port}",
        "--cluster.listen-address=", "--log.level=debug",
    ], stdout=log, stderr=subprocess.STDOUT)
    wait_for(ready, 8, "readiness")
    if (start - now()).total_seconds() < 10:
        raise RuntimeError("Insufficient pre-window margin; rerun in a new directory")
    print("UTC window:", stamp(start), "to", stamp(end), flush=True)
    send("before")
    wait_for(lambda: seen("control", "before"), 5, "before control delivery")
    time.sleep(4)
    if now() >= start or seen("scheduled", "before"):
        raise RuntimeError("FAIL before: scheduled notification arrived outside active window")
    print("PASS before: control delivered; scheduled route quiet", flush=True)
    pause_until(start + timedelta(seconds=1))
    send("inside")
    wait_for(lambda: seen("scheduled", "before") and seen("scheduled", "inside")
             and seen("control", "inside"), 12, "inside deliveries")
    for phase in ("before", "inside"):
        for event in seen("scheduled", phase):
            if not start <= datetime.fromisoformat(event["at"].replace("Z", "+00:00")) < end:
                raise RuntimeError("Scheduled delivery timestamp outside window")
    print("PASS inside: earlier alert and fresh alert delivered", flush=True)
    pause_until(end + timedelta(seconds=1))
    send("after")
    wait_for(lambda: seen("control", "after"), 5, "after control delivery")
    time.sleep(6)
    if seen("scheduled", "after"):
        raise RuntimeError("FAIL after: scheduled route notified after window closed")
    print("PASS after: control delivered; fresh scheduled group quiet", flush=True)
    (evidence / "result.txt").write_text("PASS before / inside / after\n")
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    hook.shutdown()
    hook.server_close()
    log.close()
PYTHON
python3 drill.py
```

A successful run reports:

```text
PASS before: control delivered; scheduled route quiet
PASS inside: earlier alert and fresh alert delivered
PASS after: control delivered; fresh scheduled group quiet
```

It then writes `evidence/result.txt`. A timeout, early process exit, or failed assertion prevents that success marker. The `finally` block stops the owned Alertmanager process and closes the webhook server on normal completion or a handled exception. If you forcibly kill the Python process, inspect and stop any remaining lab child process before cleanup.

The earlier group's delivery shows reevaluation in this particular run, not a durable message queue or a promise to replay every notification suppressed during a closed interval. The test stops well before the next daily occurrence and makes no claim about tomorrow's state.

## 4. Inspect actual evidence

The configuration contains the generated date and minute, so read it rather than copying a stale example window into a real schedule. The receiver paths and phase labels let you distinguish every observation.

```bash
cat alertmanager.yml
cat evidence/window.json
cat evidence/result.txt
python3 - <<'PYTHON'
import json
from pathlib import Path
for line in Path("evidence/notifications.jsonl").read_text().splitlines():
    event = json.loads(line)
    print(event["at"], event["path"], event["body"]["groupLabels"])
PYTHON
```

Expect control entries for all three phases, scheduled entries for `before` and `inside` received during the window, and no scheduled `after` entry in this run. The `before` phase label describes when that alert was submitted; its scheduled notification should arrive **after opening**. Receive timestamps are measured at the local webhook, not provider delivery timestamps.

The script also retains `evidence/alertmanager.log`. Read it on failures. A green `/-/ready` alone establishes readiness to serve traffic, not notification delivery; that is why the webhook checks are separate.

## 5. Prove the guard rejects a missing restriction

A configuration can pass syntax validation while scheduling the wrong hours. The optional lab-only switch removes the scheduled route's `active_time_intervals` reference. That leaves the route always active. Run it in another directory so the first run's state and evidence remain untouched:

```bash
mkdir negative-control
cp drill.py amtool alertmanager negative-control/
(
  cd negative-control
  if python3 drill.py --without-window > regression.log 2>&1; then
    echo 'FAIL: removed window escaped detection' >&2
    exit 1
  fi
  grep -F 'RuntimeError: FAIL before: scheduled notification arrived outside active window' \
    regression.log
)
```

The candidate still passes `amtool check-config`, but the scheduled `before` alert now reaches its webhook too early. The final `grep` requires that exact regression error; an unrelated startup or network failure is not accepted as proof. Inspect `negative-control/evidence/notifications.jsonl` and its log to confirm the observation.

The original script and positive evidence are unchanged. To repeat the correct test, create a new directory, copy the original script and both binaries there, and run without the switch.

## 6. Adapt the result to a real notification policy

Start with the intended schedule and receiver ownership, not this artificial one-minute range. Record the IANA time zone explicitly. A UTC interval does not exercise daylight-saving gaps or repeated local times; test those separately for a region that observes them.

Preserve the existing configuration, validate a candidate with the matching amtool release, and review route order, `continue`, grouping timers, repeat intervals, and named interval references together. Use a separate isolated receiver for a real schedule test. Verify notifications on both sides of the change before routing production traffic through it.

If the new policy fails acceptance, restore the previous configuration through your normal validated reload process and verify a fresh synthetic notification at the isolated destination. This lab does not perform a reload or provide a production handoff policy. Do not remove an intentional restriction from a live receiver merely to make a test pass.

| Symptom | Investigate |
|---|---|
| Control and scheduled notifications both disappear | Readiness, process log, local ports, webhook process, and route matchers. |
| Scheduled notification arrives before opening | Missing or wrong active-interval reference, time zone, or generated date. |
| Control works but the interval never opens | Clock stability, date constraints, named interval, and sufficient runtime. |
| Earlier group arrives shortly after opening | Compare grouping cadence and captured timestamps; opening is not a precise send deadline. |
| A real day/night route has no fallback | Review matching and `continue`; inactive routes still participate in routing. |

The after-window quiet check is finite evidence for the fresh `after` group, not a guarantee of indefinite suppression or cancellation of all in-flight deliveries.

## Cleanup

No production service or configuration was changed. Retain the workspace if you need its evidence. Otherwise inspect the path before deleting the disposable files:

```bash
printf 'Lab directory: %s\n' "$lab_dir"
cd ..
# Review the printed path before deletion.
rm -r -- "$lab_dir"
```

## Official references

Reviewed November 28, 2026. Current documentation may include features newer than the historical lab release; the pinned reference establishes the fields used here.

- [Alertmanager route restrictions, grouping, and time intervals](https://prometheus.io/docs/alerting/latest/configuration/).
- [Alertmanager 0.28.1 configuration reference](https://github.com/prometheus/alertmanager/blob/v0.28.1/docs/configuration.md).
- [Alertmanager management API and readiness](https://prometheus.io/docs/alerting/latest/management_api/).
- [Pinned Alertmanager v2 API schema](https://github.com/prometheus/alertmanager/blob/v0.28.1/api/v2/openapi.yaml).
- [Official 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1).

Next planned topic: verify a day/night Alertmanager receiver handoff without a routing gap.
