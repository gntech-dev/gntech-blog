---
title: "Systemd Service Hardening — Lock Down Linux Services in Your Homelab"
description: "Hardening systemd service units for homelab Linux servers: sandboxing directives, capability dropping, filesystem restrictions, resource limits, and secure service templates with real unit file examples."
date: 2026-05-15T17:00:00-04:00
tags:
  - linux
  - security
  - systemd
  - homelab
  - performance
keywords:
  - systemd service hardening homelab
  - systemd sandboxing directives
  - Linux service unit security
  - systemd ProtectSystem ReadWritePaths
  - systemd capability drop BoundingSet
  - systemd MemoryMax CPUQuota resource limits
  - systemd service template homelab
summary: "Hardening systemd service units in your homelab isn't just for production servers — it's how you prevent one compromised service from taking down your entire host. This guide covers sandboxing, capability drops, filesystem isolation, and resource limits with real unit files you can use today."
canonical: "https://gntech.dev/posts/systemd-service-hardening/"
---

Docker gets all the security attention, but most homelabs run plenty of
services directly on the host — Nginx, Prometheus, systemd-networkd,
fail2ban, cron jobs, custom scripts. Each one is a systemd unit, and
each one runs with default permissions that are far too permissive.

systemd's `[Service]` section supports dozens of sandboxing directives
that clamp down on what a process can see, touch, and do. Most homelab
servers don't use any of them.

This guide covers the exact directives you add to existing unit files
or new `.service` files to lock down services on Debian, Ubuntu, or any
systemd-based Linux distribution.

---

## Why Default systemd Permissions Are Dangerous

Without hardening, every service on your system runs with full access
to the filesystem, the process tree, the network, and kernel interfaces.

```bash
# Check what a typical service can see
systemd-run --user --wait --pty bash -c "ls /root"
# Works — a service running as root can read /root

systemd-run --user --wait --pty bash -c "cat /etc/shadow"
# Also works — the service has the same access as its user
```

A single vulnerable service — say, a custom API script that suffers
from path traversal — can read every file on the system, spawn
processes, and persist itself. systemd hardening limits the blast
radius.

**The approach:** start with the most restrictive settings, then relax
only what breaks. Like Docker capabilities, it's easier to add back
than to lock down after deployment.

---

## Hardening Level 1: Filesystem Sandboxing

systemd provides directives that restrict what parts of the filesystem
a service can access. These are your first line of defense.

**Read-only root filesystem — the biggest win:**

```ini
[Service]
ProtectSystem=strict
```

`ProtectSystem=strict` makes `/usr`, `/etc`, and `/lib` read-only for
the service. The process can still write to `/var`, `/home`, `/root`,
`/tmp`, and any explicitly permitted paths.

For even tighter lockdown:

```ini
[Service]
ProtectSystem=full
```

`ProtectSystem=full` makes `/usr`, `/etc`, `/lib`, and `/var` read-only.
Typical for stateless services that only need to write to specific
directories.

**Allow specific writable paths:**

```ini
[Service]
ProtectSystem=full
ReadWritePaths=/var/lib/my-service /var/log/my-service
```

The service can only write to those two directories. Everything else is
read-only.

**Hide /home, /root, and /run/user:**

```ini
[Service]
ProtectHome=true
```

`ProtectHome=true` makes `/home`, `/root`, and `/run/user`
inaccessible. The process inside the unit literally cannot see them.
Most services never need to read user home directories.

**Make /tmp and /var/tmp private:**

```ini
[Service]
PrivateTmp=true
```

Each service gets its own private `/tmp` and `/var/tmp` that no other
process can see. This prevents a service A from reading temporary files
created by service B — a common attack vector for race conditions and
symlink attacks.

---

## Hardening Level 2: Capability Dropping

Like Docker, systemd supports Linux capability management. You define
exactly which capabilities the service binary is allowed to use.

**Drop all capabilities, add back only what's needed:**

```ini
[Service]
CapabilityBoundingSet=~CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_NET_ADMIN
AmbientCapabilities=
```

The `~` prefix inverts the match: "drop these capabilities." For most
services, you can drop everything:

```ini
[Service]
CapabilityBoundingSet=
```

Empty `CapabilityBoundingSet` means **no capabilities** — the service
cannot:
- Change file permissions (`CAP_DAC_OVERRIDE`)
- Bind to privileged ports (`CAP_NET_BIND_SERVICE` — ports under 1024)
- Mount filesystems (`CAP_SYS_ADMIN`)
- Access kernel features (`CAP_SYS_MODULE`, `CAP_SYS_PTRACE`)

**If your service needs to bind to port 80 or 443:**

```ini
[Service]
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
```

The `AmbientCapabilities` is required for the capability to survive
`exec()` calls. Without it, the cap is set in the bounding set but
not inherited by the child process.

**Set NoNewPrivileges — the single most important flag:**

```ini
[Service]
NoNewPrivileges=true
```

This prevents the service from gaining new privileges via suid binaries
or `capset` syscalls. Even if an attacker gets code execution, they
cannot escalate. This is the equivalent of Docker's
`security_opt: no-new-privileges:true`.

---

## Hardening Level 3: Process and Network Isolation

systemd can hide the rest of the system from the service entirely.

**Hide everything except the service's own process tree:**

```ini
[Service]
ProtectProc=invisible
ProcSubset=pid
```

`ProtectProc=invisible` means `/proc` only shows the service's own
processes — no other processes on the system are visible.

`ProcSubset=pid` restricts `/proc` to only process directories. All
the kernel tuning files in `/proc/sys`, `/proc/net`, and `/proc/fs` are
hidden.

**Deny all network access:**

```ini
[Service]
PrivateNetwork=true
```

The service gets a loopback-only network with `127.0.0.1`. No external
connections in or out. Use this for services that don't need the
network at all (local cron tasks, maintenance scripts, log processors).

**Restrict to specific network namespaces or sockets —**
systemd v250+ supports socket-activation with network namespace
isolation via `NetworkNamespacePath=`, but for most homelabs,
`PrivateNetwork=true` is the practical option.

**Hide other runtime information:**

```ini
[Service]
PrivateDevices=true
```

Hides all physical devices from the service. Only `null`, `zero`,
`full`, `random`, `urandom` are available. The service cannot access
disk devices, USB devices, or GPU devices.

```ini
[Service]
ProtectKernelTunables=true
```

Prevents the service from modifying kernel parameters via
`/proc/sys` or `/sys`.

```ini
[Service]
ProtectKernelModules=true
```

Blocks `insmod` and `modprobe` — the service cannot load kernel
modules.

```ini
[Service]
ProtectKernelLogs=true
```

Prevents the service from reading kernel log messages via `dmesg` or
`/proc/kmsg`.

```ini
[Service]
ProtectClock=true
```

Blocks changes to the system clock. Critical for services that sync
time or use timestamps — an attacker can't corrupt your logs by
changing the clock.

---

## Hardening Level 4: Resource Limits

A compromised service shouldn't be able to DoS the rest of the host.
systemd supports cgroups v2 resource control natively.

**CPU and memory limits:**

```ini
[Service]
MemoryMax=512M
MemoryHigh=384M
MemorySwapMax=0
CPUQuota=50%
TasksMax=100
IOReadBandwidthMax=/dev/sda 50M
IOWriteBandwidthMax=/dev/sda 50M
```

- `MemoryMax`: hard memory limit (OOM kill if exceeded)
- `MemoryHigh`: soft throttle limit (starts reclaiming above this)
- `MemorySwapMax=0`: no swap usage — on low-memory homelab servers,
  prevents the service from pushing the system into swap
- `CPUQuota=50%`: limit to 50% of one CPU core
- `TasksMax=100`: max number of tasks (processes + threads) —
  prevents fork bombs

**Restart and failure handling:**

```ini
[Service]
Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=60
StartLimitBurst=3
```

The service restarts after a crash, but only three times in 60 seconds.
After that, systemd gives up and marks the unit as failed — prevents
a crash loop from burning CPU cycles forever.

**OOM killer adjustment:**

```ini
[Service]
OOMPolicy=continue
```

When the kernel's OOM killer fires, `continue` means the service keeps
running (systemd won't kill it). Use `stop` if you want systemd to
stop the unit on OOM (cleaner than the kernel blindly killing the
process).

---

## Hardening Level 5: User and Group Separation

Never run services as root. systemd makes user separation trivial.

**Run as a dedicated system user:**

```ini
[Service]
User=my-service
Group=my-service
DynamicUser=true
```

`DynamicUser=true` is a killer feature — systemd creates a transient
user and group with no login shell, no home directory, and deletes
them when the service stops. No `/etc/passwd` pollution.

**With DynamicUser, StateDirectory and friends:**

```ini
[Service]
DynamicUser=true
StateDirectory=my-service
CacheDirectory=my-service
LogsDirectory=my-service
RuntimeDirectory=my-service
RuntimeDirectoryPreserve=yes
```

systemd creates the directories under `/var/lib/`,
`/var/cache/`, `/var/log/`, and `/run/` respectively, sets the right
ownership (to the dynamic user), and cleans them up if configured.

**For services that need a persistent user:**

```ini
[Service]
User=myservice
Group=myservice
```

Create the user manually:

```bash
sudo useradd -r -s /usr/sbin/nologin -M myservice
```

The `-r` makes it a system user (UID < 1000), `-s /usr/sbin/nologin`
disables login, and `-M` skips creating a home directory.

**Supplementary groups only when needed:**

```ini
[Service]
SupplementaryGroups=docker
```

For services that need socket access (e.g., a monitoring script that
reads the Docker socket), add only the specific group instead of
running as root.

---

## The Complete Hardened Service Template

Combining every directive into a single production-ready template:

```ini
[Unit]
Description=My Hardened Service
Documentation=https://example.com/docs
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/my-service
Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=60
StartLimitBurst=3
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM

# === User ===
User=my-service
Group=my-service
DynamicUser=true
SupplementaryGroups=
NoNewPrivileges=true

# === Filesystem Isolation ===
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/my-service /var/log/my-service
StateDirectory=my-service
CacheDirectory=my-service
LogsDirectory=my-service
RuntimeDirectory=my-service
RuntimeDirectoryPreserve=yes

# === Capabilities ===
CapabilityBoundingSet=
AmbientCapabilities=

# === Kernel Isolation ===
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectClock=true
ProtectHostname=true
ProtectControlGroups=true

# === Process Isolation ===
ProtectProc=invisible
ProcSubset=pid

# === Network Isolation ===
PrivateNetwork=true

# === Resource Limits (cgroups v2) ===
MemoryMax=256M
MemoryHigh=192M
MemorySwapMax=0
CPUQuota=50%
TasksMax=50
IOReadBandwidthMax=/dev/sda 10M
IOWriteBandwidthMax=/dev/sda 10M
OOMPolicy=continue

# === Sandboxing ===
KeyringMode=private
UMask=0077
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictRealtime=true
RemoveIPC=true

[Install]
WantedBy=multi-user.target
```

This template assumes the service doesn't need the network
(`PrivateNetwork=true`), doesn't need capabilities, and doesn't need
to write to most of the filesystem. Adjust for your service's actual
requirements — most services will need some of these relaxed.

---

## Applying Hardening to Existing Services

Don't modify the base unit file for packaged services — use drop-in
overrides.

**Create an override for Nginx:**

```bash
sudo systemctl edit nginx.service
```

This opens `/etc/systemd/system/nginx.service.d/override.conf`. Add:

```ini
[Service]
# Nginx needs to bind to port 80/443
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Nginx needs access to ssl certs and configs
ProtectSystem=full
ReadWritePaths=

# Use a non-root user
User=nginx
Group=nginx
NoNewPrivileges=true

# Hide home directories
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

# No kernel access needed
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectClock=true

# Resource limits
MemoryMax=1G
MemoryHigh=768M
CPUQuota=200%
TasksMax=512

# System call filter (Nginx doesn't need exotic syscalls)
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
```

Apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx
sudo systemctl status nginx
```

**Check if hardening broke anything:**

```bash
sudo journalctl -u nginx --since "5 minutes ago" | grep -i "denied\|permission\|error"
```

If Nginx can't read SSL certificates, add the cert path to ReadWritePaths
or verify the cert directory permissions.

---

## Creating a Fully Isolated Service: Example

Let's build a hardened service for a custom health check script
(like the homelab health receipt that was trending on Reddit).

**The script** — `/usr/local/bin/health-report.sh`:

```bash
#!/bin/bash
# Generates a daily homelab health report
set -euo pipefail
OUTPUT="/var/lib/health-report/report.json"

curl -sf http://localhost:9090/api/v1/query?query=up > /dev/null \
  && echo '{"health":"ok","timestamp":"'$(date -Iseconds)'"}' \
  || echo '{"health":"degraded","timestamp":"'$(date -Iseconds)'"}' \
  > "$OUTPUT"
```

**The hardened unit — `/etc/systemd/system/health-report.service`:**

```ini
[Unit]
Description=Daily Homelab Health Report
Documentation=https://gntech.dev/posts/systemd-service-hardening/
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/health-report.sh

# === User ===
DynamicUser=true
NoNewPrivileges=true

# === Filesystem Isolation ===
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
StateDirectory=health-report

# === Capabilities ===
CapabilityBoundingSet=
AmbientCapabilities=

# === Kernel Isolation ===
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true

# === Process Isolation ===
ProtectProc=invisible

# === Network (needs to reach Prometheus on localhost) ===
# PrivateNetwork=true  ← Not set — needs loopback for local Prometheus
RestrictAddressFamilies=AF_INET AF_UNIX

# === Resource Limits ===
MemoryMax=64M
CPUQuota=25%
TasksMax=5

[Install]
WantedBy=timers.target
```

**The timer — `/etc/systemd/system/health-report.timer`:**

```ini
[Unit]
Description=Daily Health Report Timer

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
```

Enable both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now health-report.timer
```

The report script runs once daily as a dynamic user, with no root
access, no home directory visibility, no kernel access, and a strict
64MB memory cap. If an attacker exploits the script, they're trapped
in a sandbox with no capabilities and no network access beyond
localhost.

---

## Verifying Your Hardening

After applying changes, verify each directive is active:

```bash
# Load and display all active systemd hardening
systemd-analyze security my-service
```

This outputs a security score (`EXPOSURE` level from 1-10) and a table
of every sandboxing directive with checkmarks. Aim for `SAFE` or
`EXPOSURE=1-2` for services that don't need network or device access.

```bash
# Check specific directives on a running service
systemctl show my-service -p ProtectSystem
systemctl show my-service -p ProtectHome
systemctl show my-service -p CapabilityBoundingSet
systemctl show my-service -p MemoryMax
systemctl show my-service -p NoNewPrivileges
systemctl show my-service -p PrivateTmp
systemctl show my-service -p PrivateNetwork
systemctl show my-service -p SystemCallFilter
systemctl show my-service -p RestrictAddressFamilies
```

```bash
# Check the effective cgroup limits
systemd-cgls -u my-service
cat /sys/fs/cgroup/system.slice/my-service/memory.max
cat /sys/fs/cgroup/system.slice/my-service/cpu.max
```

```bash
# Test user isolation
systemd-run --unit=test-workdir -p DynamicUser=yes -p ProtectSystem=strict \
  -p CapabilityBoundingSet= -p PrivateTmp=true -p NoNewPrivileges=true \
  --wait --pty touch /test-write
# Should fail: Read-only file system
```

---

## Common Issues and Fixes

**"Permission denied" on startup:** Your service needs to write to a
directory you didn't allow. Use `ReadWritePaths=` to whitelist it, or
use `StateDirectory=` which systemd creates with correct ownership.

**"Can't bind to port 80":** The service needs `CAP_NET_BIND_SERVICE`.
Add `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` and
`AmbientCapabilities=CAP_NET_BIND_SERVICE`. Or run on a port >1024
and set up a reverse proxy.

**"Can't connect to database on another host":** `PrivateNetwork=true`
blocks all network. Remove it (the default is false). For tighter
security, use `RestrictAddressFamilies=AF_INET AF_INET6` instead.

**Service starts as the right user but can't read config:**
Filesystem permissions matter. Store configs in a directory owned by
the service user, or use `LoadCredential=` to pass secrets securely:

```ini
[Service]
LoadCredential=db-password:/etc/secrets/db-password
```

**SystemCallFilter breaks the service:**
Some apps (Java, Node.js running native modules, Chrome/Puppeteer) use
uncommon syscalls. Check what's being blocked:

```bash
journalctl -u my-service | grep -i "syscall\|seccomp"
```

Use `-1-SystemCallFilter=` (drop specific syscalls) instead of
`+1@system-service` (allow a preset). Or drop `SystemCallFilter`
entirely if the service legitimately needs exotic syscalls.

---

## Summary: The Minimal Hardening Checklist

These eight directives cover 95% of the improvement with minimal
breakage. Apply them to every unit you create:

```ini
[Service]
# 1. Isolate the filesystem
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

# 2. Isolate the kernel
PrivateDevices=true
ProtectKernelTunables=true

# 3. Drop privileges
NoNewPrivileges=true
CapabilityBoundingSet=

# 4. Limit resources
MemoryMax=512M
CPUQuota=50%
```

Run `systemd-analyze security my-service` after every change to see
your exposure score drop. When a service scores `SAFE` on all
directives, you've done your job.

systemd hardening is the equivalent of Docker's security options —
it's built into the init system, it costs zero additional tooling,
and it relies on the same kernel primitives (cgroups, namespaces,
seccomp, capabilities). Use it.
