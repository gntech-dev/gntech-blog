---
title: "Did Your Log Shipper Keep Reading After Rotation?"
description: "Use Vector and a local JSON Lines sink to check for missing or duplicated events across a log rename and a clean collector restart."
date: 2026-11-09T12:00:00-04:00
draft: false
ShowToc: true
tags: [linux, logging, vector, observability, operations]
keywords: [Vector file source, log rotation, log checkpoints, missing log events]
summary: "Follow a short sequence of numbered log events across a renamed file, its replacement, and a collector restart."
cover:
  image: "/images/posts/log-shipper-rotation/featured.webp"
  alt: "Two compact servers connected by blue Ethernet cables on a dark lab bench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A new request in the replacement access log confirms that the application reopened its file. The collector has a separate job. It needs to finish reading the old file and discover the new one. A running process or a recent dashboard entry tells you little about the events in between.

This lab uses Vector's file source and a local JSON Lines sink. Install a supported Vector release from the official distribution instructions and have Python 3 and Bash available. Run the lab as an ordinary user in a fresh directory. It uses synthetic events, opens no listener, and needs no log backend or credentials. The expected results describe the test contract.

| Stage | Source of the numbered events | What it tests |
| --- | --- | --- |
| 001–003 | Original active file | Initial discovery and collection |
| 004–005 | Renamed file through the original open descriptor | Reading late writes to the old file |
| 006–008 | Replacement active file | Discovery after rotation |
| 009–010 | Active file while Vector is stopped | Catch-up after a clean restart with the same checkpoint directory |

For the writer side, see the [NGINX reopen test](/posts/2026-11-09-nginx-logrotate-reopen-verification/). Here a shell descriptor stands in for an application that keeps writing briefly after the rename.

## 1. Configure a private pipeline

In the first terminal, create the lab and start Vector in the foreground. Note the directory printed by `pwd`.

```bash
vector --version
lab="$(mktemp -d /tmp/gntech-vector-rotation.XXXXXX)"
cd "$lab" || exit 1
mkdir data input output
printf 'GNTECH-001\nGNTECH-002\nGNTECH-003\n' > input/app.log
pwd

cat > vector.toml <<TOML
data_dir = "$lab/data"

[sources.lab]
type = "file"
include = ["$lab/input/app.log", "$lab/input/app.log.1"]
read_from = "beginning"
fingerprint.strategy = "checksum"
fingerprint.lines = 1

[sinks.capture]
type = "file"
inputs = ["lab"]
path = "$lab/output/received.jsonl"
encoding.codec = "json"
framing.method = "newline_delimited"
TOML

vector validate vector.toml && vector --config vector.toml
```

The first line in each source file is distinct, so the checksum strategy can distinguish them. Keep the rotated file in the include list and leave it uncompressed for the lab. The configuration records the lab directory as an absolute path. Reuse the same directory, source name, and state when restarting.

## 2. Rename the file while the writer still holds it open

In a second terminal, enter the directory printed earlier. Replace the placeholder with your lab path. Wait until the capture includes the baseline marker before rotating.

```bash
cd /tmp/gntech-vector-rotation.REPLACE || exit 1
grep -F 'GNTECH-003' output/received.jsonl
```

Open the original file for append, rename it, append two more lines through the existing descriptor, and then close that descriptor. Write three different lines to the replacement.

```bash
exec 3>> input/app.log
mv -- input/app.log input/app.log.1
printf 'GNTECH-004\nGNTECH-005\n' >&3
exec 3>&-
printf 'GNTECH-006\nGNTECH-007\nGNTECH-008\n' > input/app.log
```

Expect the capture to include both sets of markers after discovery and collection. Events can interleave across the two files. Count event IDs rather than treating global ordering as the success condition.

## 3. Stop cleanly and test catch-up

Wait until the capture includes all eight IDs before moving on. For a quick inspection:

```bash
grep -oE 'GNTECH-[0-9]{3}' output/received.jsonl | sort | uniq -c
```

Press Ctrl+C in the first terminal and wait for Vector to exit. In the second terminal, append the last two lines while it is stopped.

```bash
printf 'GNTECH-009\nGNTECH-010\n' >> input/app.log
```

In the first terminal, start Vector again from the same directory with `vector --config vector.toml`. Wait for the last marker to appear. Use this check in the second terminal to detect both gaps and replay:

```bash
python3 - <<'PY'
from collections import Counter
import json
from pathlib import Path

capture = Path("output/received.jsonl")
with capture.open() as lines:
    observed = Counter(json.loads(line)["message"] for line in lines)
expected = Counter(f"GNTECH-{i:03d}" for i in range(1, 11))
missing = expected - observed
unexpected = observed - expected
print("Missing:", dict(missing))
print("Unexpected or repeated:", dict(unexpected))
raise SystemExit(bool(missing or unexpected))
PY
```

Both dictionaries should be empty. If the sink is still writing, wait briefly and rerun the check. A passing run covers this rename and clean restart. It provides no guarantee about crashes, a remote sink outage, or exactly-once delivery.

## 4. Diagnose gaps before changing production

| Symptom | First check |
| --- | --- |
| Baseline missing | Verify the working directory, file glob, permissions, and Vector diagnostics. |
| Old-file markers missing | Check rotated-file visibility, retention, and whether the writer flushed those lines. |
| Replacement markers missing | Check discovery and whether its first line collides with the original fingerprint. |
| Old markers repeat after restart | Check the data directory, source name, checkpoint continuity, and capture scope. |

Keep checkpoints when investigating. Deleting them changes where the collector may resume and can introduce replay. In a production test, use unique markers and query the actual destination. Keep rotated files available for the expected collector outage and separately test compression, buffering, and recovery behavior for your deployment.

Stop the lab collector with Ctrl+C before removing the temporary directory. Keep the captured output if it is needed as evidence. For a new test, start with a fresh directory so prior output and checkpoints cannot affect the comparison.

## Official references

- [Vector installation](https://vector.dev/docs/setup/installation/)
- [Vector file source and rotation behavior](https://vector.dev/docs/reference/configuration/sources/file/)
- [Vector file sink](https://vector.dev/docs/reference/configuration/sinks/file/)
- [Vector configuration validation](https://vector.dev/docs/administration/validating/)
