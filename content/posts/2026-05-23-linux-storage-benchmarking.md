---
title: "Linux Storage Benchmarking — A Bounded fio Filesystem Baseline"
description: "Select the intended filesystem, prepare a unique test file, save separate fio JSON results, and interpret cache and workload limits before tuning storage."
date: 2026-05-23T12:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [linux, storage, homelab, performance]
keywords: [fio filesystem benchmark, Linux storage baseline, fio JSON results, cache-aware storage testing]
summary: "A small file-based baseline with explicit target selection and machine-readable results."
---

Storage benchmarks answer a specific workload question. A cached read result, a queue-depth-32 random test, and a database commit latency are different measurements.

Start with a modest file test on the intended filesystem. Record conditions before changing hardware or tuning properties.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | fio, Docker and OpenZFS references reviewed on October 31, 2026. |
| Static checks | Bash syntax and result-path structure checked. |
| Runtime | No fio workload, storage modification, NFS test or container benchmark executed for this revision. |
| Scope | Proposed buffered, single-job filesystem baseline; not a raw-device or durable-transaction benchmark. |

## 1. Identify the path and workload

On Debian or Ubuntu:

```bash
sudo apt update
sudo apt install fio sysstat python3
fio --version
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,FSTYPE,MODEL
```

Confirm this is the Flexible I/O Tester, not another executable with the same name. Choose an existing writable test directory on the desired mount, with free space and no production data that the test should touch.

Avoid a default /tmp target: it might be memory-backed or on a different disk. For external mounts, verify the expected source is actually mounted before creating test files. Run during an agreed maintenance window; even a file-based workload competes with other users.

Write down the question: sequential file transfer, random reads, application commits, or concurrent clients. The small demo below measures only the first two under buffered conditions.

## 2. Create a bounded baseline script

The script requires an explicit directory. It writes a 256 MiB preparation file in a newly created subdirectory, then reads that file. It never accepts a raw block-device target.

```bash
cat > filesystem-baseline.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

target=${1:?Usage: filesystem-baseline.sh EXISTING_TEST_DIRECTORY}
test -d "$target"
test -w "$target"
target=$(realpath -- "$target")
findmnt -T "$target"
df -h "$target"

run_dir=$(mktemp -d "$target/fio-baseline.XXXXXX")
printf 'Run directory: %s\n' "$run_dir"
{
  date -u
  uname -r
  fio --version
  findmnt -T "$target"
  df -h "$target"
} > "$run_dir/context.txt"

fio --name=prepare --ioengine=psync --direct=0 --iodepth=1 \
  --rw=write --bs=1M --size=256M --numjobs=1 \
  --refill_buffers=1 --end_fsync=1 \
  --filename="$run_dir/test.bin" \
  --output-format=json --output="$run_dir/prepare.json"

fio --name=sequential-read --ioengine=psync --direct=0 --iodepth=1 \
  --rw=read --bs=128k --size=256M --numjobs=1 \
  --readonly --allow_file_create=0 --invalidate=0 \
  --filename="$run_dir/test.bin" \
  --output-format=json --output="$run_dir/sequential-read.json"

fio --name=random-read --ioengine=psync --direct=0 --iodepth=1 \
  --rw=randread --bs=4k --size=256M --numjobs=1 \
  --runtime=15 --time_based --readonly --allow_file_create=0 --invalidate=0 \
  --filename="$run_dir/test.bin" \
  --output-format=json --output="$run_dir/random-read.json"

python3 - "$run_dir" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ("prepare", "sequential-read", "random-read"):
    data = json.loads((root / (name + ".json")).read_text())
    jobs = data["jobs"]
    if not jobs or any(job["error"] != 0 for job in jobs):
        raise SystemExit("fio job error: " + name)
print("All result files parsed and report zero job errors.")
PY
printf 'Retained test file and results in %s\n' "$run_dir"
SCRIPT

chmod 700 filesystem-baseline.sh
read -r -p 'Existing test directory on the intended filesystem: ' benchmark_dir
./filesystem-baseline.sh "$benchmark_dir"
```

Review free space before running; the script does not enforce a capacity threshold. The 15-second read phase is bounded in time, while preparation and flush duration depend on storage. Stop and investigate errors rather than disabling durability or changing production properties to obtain a number.

The preparation write uses fresh buffers rather than a zero-filled dd stream. The read jobs cannot create missing test files. Each result is one JSON document; context text stays separate.

The synchronous engine runs one request at a time here. Raising iodepth with this engine would not create the same concurrency as an asynchronous engine. See the [fio reference](https://fio.readthedocs.io/en/latest/fio_doc.html) for option semantics.

## 3. Read results without inventing expectations

This is deliberately buffered and cache-aware: the preparation may warm caches, and the read working set is small. Read throughput may therefore describe memory or filesystem cache behavior rather than physical disk speed. It is not a cold-cache hardware comparison.

Inspect the saved JSON and verify units. Bandwidth, operation rate, and completion latency describe different aspects of the test. Percentiles are nested in the latency structure produced by the installed fio version; do not assume invented p50/p99 top-level keys.

Record errors and variability alongside headline throughput. Compare repeated runs with the same file size, cache policy, engine, block size, concurrency and background load. Keep preparation results separate from steady-state claims.

Do not convert one random-I/O rate directly into application INSERT latency or promise a universal throughput target for media streams. Validate representative application behavior too.

## 4. Adapt by storage type

| Path | Additional evidence to record |
|---|---|
| Local filesystem | Device, filesystem, mount options, free space and competing workloads |
| ZFS | Pool layout, properties, ARC behavior, dataset versus zvol, and installed OpenZFS version |
| NFS | Actual mount source/options, client and server load, network path and server cache |
| Docker bind mount or volume | Backing filesystem, mount type, cgroup limits, image and tools used |

Direct I/O support and behavior depend on the filesystem and version. Do not assume direct=1 bypasses every cache, especially across ZFS or network storage. Keep buffered and supported direct-I/O tests as separately labelled experiments.

For ZFS, inspect properties before tuning. Do not change sync, recordsize or compression on a live production dataset as a benchmark step. The sync property defaults to standard, not always. See [OpenZFS properties](https://openzfs.github.io/openzfs-docs/man/master/7/zfsprops.7.html).

Docker named volumes and bind mounts are distinct from the container writable layer; they do not inherently traverse overlay2. Use a new disposable volume for a container comparison, not a running database's storage. Compare equivalent backing storage and conditions. See [Docker volumes](https://docs.docker.com/engine/storage/volumes/).

## 5. Diagnose before buying or tuning

Watch host and storage activity during a separate run, for example with iostat, and correlate it with application latency and errors. Investigate mount selection, thermal behavior, queueing and competing jobs before blaming the disk model.

Benchmarking is not disk-health validation or a backup test. Review the [disk-health guide](/posts/2026-06-05-linux-disk-health-monitoring-smartmontools-scrutiny/) and protect recoverable data before stressing suspect storage.

Retain JSON results and context for comparison. When finished, remove only the exact disposable run directory printed by the script after inspecting its contents. No raw-device write, global cache drop, pool-property change or automatic deletion is included.

## Continue reading

- [ZFS snapshots and recovery](/posts/2026-05-08-zfs-snapshot-strategies/) — Understand dataset and guest-storage boundaries.
- [Docker Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — Document mounts and resource constraints.
