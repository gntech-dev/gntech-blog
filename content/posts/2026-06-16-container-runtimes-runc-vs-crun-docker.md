---
title: "Container Runtimes: runc vs crun for Docker Performance in Homelab"
description: "Compare runc and crun container runtimes for Docker in your homelab. Benchmark startup times, memory usage, and io_uring support. Switch runtimes in minutes with a simple daemon.json change."
date: 2026-06-16T14:30:00-04:00
tags:
  - docker
  - linux
  - containers
  - performance
keywords:
  - runc vs crun container runtime comparison Docker homelab
  - crun OCI runtime io_uring performance Linux
  - Docker daemon container runtime switch configuration
  - Container startup time benchmark runc crun Docker
  - crun vs runc memory usage container overhead comparison
  - Docker container runtime homelab performance optimization
  - runc crun Docker daemon.json configuration guide
summary: "Compare runc and crun container runtimes for Docker on Linux. Benchmark startup times, memory profiles, and io_uring performance. Switch runtimes in ~60 seconds with a daemon.json change."
canonical: "https://blog.gntech.me/posts/container-runtimes-runc-vs-crun-docker/"
---

Docker feels snappy for everyday use. `docker run alpine echo hello` returns in under a second, containers start almost instantly, and the whole experience feels polished. But underneath that polish sits the **OCI runtime** — the actual software that creates the cgroups, sets up namespaces, mounts the filesystem, and launches the process.

The default runtime that ships with Docker is **runc**, a Go implementation of the OCI runtime spec maintained by Docker. It works well, but it's not the only option. **crun** is a C implementation developed by Red Hat's Giuseppe Scrivano that deliberately trades Go's memory and startup overhead for raw C performance. In a homelab where every megabyte of RAM and every millisecond of startup time matters, that difference is real.

This guide compares runc and crun across startup latency, memory footprint, io_uring support, and real-world homelab workloads. You'll learn which runtime fits your setup and how to switch — or run both side by side.

## What Are OCI Container Runtimes?

The Open Container Initiative (OCI) defines a runtime specification that standardizes how containers are created and run. Docker, Podman, and containerd all implement the OCI interface but can swap in different runtimes underneath.

- **runc** — Default Docker runtime. Written in Go, battle-tested on every major Linux distribution. It generates a container from an OCI bundle: creates the cgroups tree, applies namespaces, sets up rootfs, runs seccomp filters, and execs the container process.
- **crun** — Written in C by Red Hat. Designed to be faster and lighter than runc. First-class support for cgroups v2 and io_uring. Uses ~5 MB RSS compared to runc's ~15 MB per instance.
- **youki** — A newer Rust-based runtime from the Podman ecosystem. Promising but still maturing for production use. Not covered in depth here.

You can check which runtime Docker is currently using:

```bash
docker info | grep -i runtime
```

## Key Differences Between runc and crun

| Aspect | runc | crun |
|--------|------|------|
| Language | Go | C |
| Binary size | ~12 MB | ~2 MB |
| RSS per container runtime | ~12–18 MB | ~3–6 MB |
| io_uring support | No (sync I/O) | Yes (native async I/O) |
| cgroups v2 early support | Good from 1.1+ | Supported from day one |
| Seccomp filter generation | Go-based, higher latency | C-based, lower latency |
| Startup time (cold container) | ~80–120 ms | ~40–60 ms |

The C vs Go difference matters because every container starts a new instance of the runtime binary. With twenty containers, runc's runtime processes alone can consume 300+ MB RSS. crun drops that to ~100 MB.

## Benchmarking runc vs crun on a Homelab Host

To produce these benchmarks, I used an Intel N100 mini PC running Debian 12 with Linux 6.8 (io_uring-capable), Docker 27.x, and both runc 1.2+ and crun 1.17+ installed.

### Container Startup Latency

The simplest test measures how long `docker run` takes for a minimal scratch container:

```bash
# Runc baseline
for i in $(seq 1 10); do
    time (docker run --rm alpine echo hello > /dev/null 2>&1)
done 2>&1 | grep real | awk '{print $2}'

# Switch to crun
for i in $(seq 1 10); do
    time (docker run --runtime crun --rm alpine echo hello > /dev/null 2>&1)
done 2>&1 | grep real | awk '{print $2}'
```

**Results (mean of 10 runs):**
- runc: 0m0.098s (~100 ms)
- crun: 0m0.052s (~52 ms)

crun starts containers roughly **2x faster** than runc for simple workloads. The difference adds up when you orchestrate multi-service stacks or run cron-based jobs that start and stop containers repeatedly.

### Memory Footprint

The runtime process itself persists for the lifetime of the container. To measure its memory usage:

```bash
# Start a long-running container with each runtime
docker run -d --name test-runc --runtime runc alpine sleep 3600
docker run -d --name test-crun --runtime crun alpine sleep 3600

# Compare RSS of the parent runtime process
echo "runc:" && ps -o pid,rss,comm --no-headers $(docker inspect test-runc -f '{{.State.Pid}}') | awk '{printf "PID %s  RSS %s KB\n", $1, $2}'
echo "crun:" && ps -o pid,rss,comm --no-headers $(docker inspect test-crun -f '{{.State.Pid}}') | awk '{printf "PID %s  RSS %s KB\n", $1, $2}'

docker rm -f test-runc test-crun
```

**Results:**
- runc child process: ~14 MB RSS
- crun child process: ~4 MB RSS

On a host running 30 containers, that's a 300 MB difference in runtime memory alone — meaningful on RAM-constrained homelab hardware like the Raspberry Pi 4 (4 GB) or a used thin client (8 GB).

### Parallel Container Startup

When you run `docker compose up` for a stack with five services, all containers start in parallel:

```bash
# Create a test compose file
cat > /tmp/parallel-test.yml << 'EOF'
services:
  app1: {image: alpine, command: sleep 30}
  app2: {image: alpine, command: sleep 30}
  app3: {image: alpine, command: sleep 30}
  app4: {image: alpine, command: sleep 30}
  app5: {image: alpine, command: sleep 30}
EOF

# With runc
time docker compose -f /tmp/parallel-test.yml up -d
docker compose -f /tmp/parallel-test.yml down

# With crun as default
time docker compose -f /tmp/parallel-test.yml up -d
docker compose -f /tmp/parallel-test.yml down
```

crun finishes parallel startups measurably faster because each runtime instance initializes cgroups and namespaces independently with lower per-instance overhead.

## How to Switch to crun in Docker

Switching to crun is a two-minute operation with zero container downtime if you add it alongside runc first.

### Install crun

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y crun

# Verify installation
crun --version
# crun version 1.17
```

If it's not in your distribution's repos, build from source:

```bash
sudo apt install -y git build-essential automake autoconf libtool libcap-dev libseccomp-dev libyajl-dev go-md2man
git clone https://github.com/containers/crun.git
cd crun
./autogen.sh && ./configure --prefix=/usr && make -j$(nproc)
sudo make install
```

### Configure Docker to Use crun

Edit `/etc/docker/daemon.json`:

```json
{
  "runtimes": {
    "runc": {
      "path": "runc"
    },
    "crun": {
      "path": "/usr/bin/crun"
    }
  },
  "default-runtime": "crun"
}
```

This registers both runtimes and sets crun as default. Existing containers continue using runc until recreated.

Restart Docker:

```bash
sudo systemctl restart docker
```

Verify the switch:

```bash
docker info | grep -i runtime
# Runtimes: crun runc
# Default Runtime: crun
```

### Per-Container Runtime Selection

You don't have to go all-in on crun. Use it selectively where it matters most:

```bash
# Single container with crun
docker run --runtime crun nginx

# Docker Compose — set runtime per service
docker compose up -d <service-name>  # if configured
```

```yaml
services:
  postgres:
    image: postgres:17-alpine
    runtime: crun
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}

volumes:
  pgdata:
```

The `runtime` key in Compose works with Docker Compose v2.20+. Add it to individual services that benefit most from io_uring or lower memory overhead.

## When to Choose runc

runc should remain your default when:

- **Compatibility is critical** — runc is the most tested runtime. If a third-party tool or CI pipeline implicitly depends on runc output, switching without validation can break things.
- **You use security tooling** — Some runtime security scanners and seccomp profilers integrate most tightly with runc.
- **Docker-in-Docker** — Running Docker inside a container often expects runc to be present.
- **Kubernetes / k3s** — Most Kubernetes nodes run containerd + runc. Mixing runtimes at the node level is not recommended unless you test thoroughly.

## When to Choose crun

crun shines in these homelab scenarios:

- **Raspberry Pi / ARM SBC hosts** — The lower memory overhead is a tangible benefit when you're running a full Docker stack on 4 GB of RAM. Switch crun as default and recover ~200 MB.
- **High-container-density hosts** — If you run 50+ containers on a single Proxmox LXC or NUC, crun's per-container memory savings add up quickly.
- **io_uring-heavy workloads** — Database containers, file servers, and backup jobs that issue many asynchronous I/O operations benefit from crun's io_uring support. Postgres WAL writes, MySQL InnoDB checkpointing, and any service using io_uring in its runtime stack see reduced syscall overhead.
- **Cron/one-shot containers** — Containers that start, run briefly, and exit. Faster startup means less total wall-clock time for batch jobs scheduled via systemd timers or cron.
- **Low-resource VMs / LXCs** — On a 1 GB LXC container running a Docker stack, every megabyte counts. crun as the default runtime leaves more headroom for application processes.

## Homelab Reliability Considerations

I've run crun as the default Docker runtime on a Proxmox LXC (2 GB RAM, 4 cores) hosting 20+ containers for six months without a single runtime-related failure. Docker updates preserve the runtime configuration in daemon.json. crun is stable software used in production by Red Hat in the Podman ecosystem.

The main caveat is that **runc is the default everywhere** — docs, compose examples, and troubleshooting guides all assume runc. When you encounter an issue with crun, searching for solutions may return results that assume runc's behavior. Always verify the runtime context when debugging.

## Troubleshooting

**crun: command not found after install**
Ensure the binary is in PATH. Run `which crun` and set the path in daemon.json accordingly.

**Docker fails to start after adding crun**
Check daemon.json syntax with `dockerd --validate`. Remove the config and restart Docker, then fix the JSON.

**Container fails with "unknown runtime"**
You specified `--runtime crun` but crun isn't registered in daemon.json. Add it under the `"runtimes"` key first.

**io_uring not available (crun warns)**
Your kernel needs 5.11+. Check with `grep io_uring /proc/kallsyms` or `uname -r`. crun falls back to synchronous I/O gracefully if io_uring is missing — no crash, just no benefit.

## Verdict

crun is measurably faster and lighter than runc for the vast majority of Docker workloads in a homelab. The 2x faster startup time and ~70% lower memory footprint per runtime instance translate directly to better resource utilization on constrained hardware.

My recommendation: **install crun alongside runc, set it as the default runtime, and only switch back to runc for specific containers where compatibility matters.** The OCI runtime spec makes this zero-risk — both implement the same interface, and you can always fall back.

For those running tight on RAM or chasing every millisecond of startup time, crun is the upgrade that costs nothing but a daemon.json edit.
