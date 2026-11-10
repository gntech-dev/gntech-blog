---
title: "Test What Happens to Your Logs During a Destination Outage"
description: "Make a local receiver return HTTP 503, let Vector retry, and measure which numbered events reach the destination after recovery."
date: 2026-11-10T00:00:00-04:00
draft: false
ShowToc: true
tags: [linux, logging, vector, observability, operations]
keywords: [Vector HTTP sink, log delivery outage, disk buffer, backpressure]
summary: "Use a temporary HTTP receiver and numbered events to measure delivery gaps, replay, and recovery time."
cover:
  image: "/images/posts/vector-destination-outage/featured.webp"
  alt: "Two servers on a dim workbench with blue and amber status lights."
  caption: "AI-generated editorial artwork."
  relative: false
---

The collector can stay up while its destination rejects every request. To see what readers of your logs actually get, count events at the destination after it recovers. Keep track of how long the backlog takes to drain.

This lab runs Vector and a small Python HTTP receiver on one Linux host. It simulates a destination that is reachable but temporarily responds with HTTP 503. It needs Bash, Python 3, and a supported Vector release. Run it as an ordinary user. The receiver binds only to loopback, takes synthetic data, and uses no credentials. Confirm that port 18083 is free and that the temporary filesystem has room for the lab's 300 MiB disk-buffer limit plus overhead.

## 1. Start a receiver you can switch offline

In the first terminal, create a fresh directory and record its absolute path. The receiver rejects requests while the `unavailable` marker exists. Accepted events get a receiver timestamp so you can measure the drain after recovery.

```bash
lab="$(mktemp -d /tmp/gntech-vector-outage.XXXXXX)"
cd "$lab" || exit 1
mkdir data
printf 'GNTECH-001\n' > app.log
pwd

cat > receiver.py <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time

class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/logs":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            self.send_error(400)
            return
        body = self.rfile.read(length)
        if Path("unavailable").exists():
            self.send_error(503)
            return
        try:
            events = [json.loads(line) for line in body.splitlines()]
            rows = [{"id": event["message"], "received_ns": time.time_ns()}
                    for event in events]
        except (KeyError, TypeError, ValueError):
            self.send_error(400)
            return
        with Path("received.jsonl").open("a", encoding="utf-8") as capture:
            for row in rows:
                capture.write(json.dumps(row) + "\n")
        self.send_response(204)
        self.end_headers()

HTTPServer(("127.0.0.1", 18083), Receiver).serve_forever()
PY

python3 receiver.py
```

The receiver is disposable. It acknowledges after closing the capture file. That is adequate for this exercise, but it does not model a production service's durability or authentication.

## 2. Configure the collector

In the second terminal, replace the placeholder with the path printed in step 1. The sink sends one event per batch to make its request and retry behavior easier to observe. The health check is disabled because this minimal receiver only implements the ingestion endpoint.

```bash
cd /tmp/gntech-vector-outage.REPLACE || exit 1
lab="$PWD"
cat > vector.toml <<TOML
data_dir = "$lab/data"

[sources.lab]
type = "file"
include = ["$lab/app.log"]
read_from = "beginning"

[sinks.receiver]
type = "http"
inputs = ["lab"]
uri = "http://127.0.0.1:18083/logs"
method = "post"
encoding.codec = "json"
framing.method = "newline_delimited"
healthcheck.enabled = false
batch.max_events = 1
buffer.type = "disk"
buffer.max_size = 314572800
buffer.when_full = "block"
TOML
vector validate vector.toml && vector --config vector.toml
```

Vector retries eligible HTTP failures, including 503. A full buffer configured to block applies backpressure. It does not extend upstream file retention, and application logs can still rotate away while the collector is behind. The file source must be able to read any backlog you expect it to recover.

## 3. Inject the failure and restore the destination

In a third terminal, enter the same directory. Wait until the first marker is captured before continuing.

```bash
cd /tmp/gntech-vector-outage.REPLACE || exit 1
grep -F GNTECH-001 received.jsonl
touch unavailable
printf 'GNTECH-%03d\n' {2..10} >> app.log
```

Confirm that the receiver logs at least one 503 and that no outage marker has reached the capture. Record collector errors and disk usage if you need evidence of the backlog. Leave Vector running and restore acceptance:

```bash
python3 -c 'import time; print(time.time_ns())' > recovery-ns
rm -- unavailable
```

Wait for delivery. Retry backoff can delay the first successful request after the receiver is ready. Check for all ten IDs, then stop Vector cleanly before taking the final count.

## 4. Compare the expected IDs with the capture

```bash
python3 - <<'PY'
from collections import Counter
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("received.jsonl").read_text().splitlines()]
expected = Counter(f"GNTECH-{i:03d}" for i in range(1, 11))
observed = Counter(row["id"] for row in rows)
missing = expected - observed
extra = observed - expected
print("Missing:", dict(missing))
print("Unexpected or repeated:", dict(extra))
recovered = [row["received_ns"] for row in rows
             if row["id"] in expected and row["id"] != "GNTECH-001"]
if recovered:
    restored = int(Path("recovery-ns").read_text())
    print(f"Last observed outage event after recovery: {(max(recovered)-restored)/1e9:.2f}s")
raise SystemExit(bool(missing or extra))
PY
```

A passing run captures each expected ID once in this experiment. The time is measured from just before the receiver starts accepting requests again. Interpret it as a backlog drain measurement only when all outage IDs arrived.

| Observation | First check |
| --- | --- |
| 503 responses continue | Check whether the marker file was removed in the receiver's actual working directory. |
| The capture stays empty after recovery | Check Vector's retry diagnostics and verify the URI, request format, and receiver status. |
| IDs are missing | Check source retention, retry limits, buffer policy, and whether the sink finished draining. |
| IDs repeat | Check retry and acknowledgement boundaries. A sender may retry after the receiver accepted data if the response was lost. |

The lab does not simulate power loss, process crashes, disk exhaustion, or a lost acknowledgement. For production sizing, start with measured ingress bytes per second and the outage interval you need to absorb. Add headroom for buffer overhead and continued ingress during recovery, then measure whether the destination drains faster than new events arrive. Keep retry limits, source retention, and the response behavior of your actual destination in the test plan.

Stop the receiver with Ctrl+C. Preserve the capture and configuration if you want to compare runs. Use a fresh temporary directory for a repeat so old checkpoints, disk-buffer files, and output cannot affect the results. For a separate writer-side check, see the [NGINX log reopen guide](/posts/2026-11-09-nginx-logrotate-reopen-verification/).

## Official references

- [Vector HTTP sink and retry behavior](https://vector.dev/docs/reference/configuration/sinks/http/)
- [Vector buffering model](https://vector.dev/docs/architecture/buffering-model/)
- [Vector file source](https://vector.dev/docs/reference/configuration/sources/file/)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)
