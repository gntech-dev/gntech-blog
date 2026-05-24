---
title: "Linux systemd Service Hardening — Sandboxing, Capabilities, and Security Auditing"
description: "Complete guide to hardening Linux systemd services — sandboxing with ProtectHome and ProtectSystem, capability reduction with CapabilityBoundingSet, NoNewPrivileges, PrivateTmp, systemd-analyze security scoring, and real hardened service files for homelab daemons."
date: 2026-05-24T17:00:00-04:00
tags:
  - linux
  - homelab
  - security
  - performance
  - devops
keywords:
  - Linux systemd service hardening sandboxing directives
  - systemd-analyze security audit service scoring
  - ProtectHome ProtectSystem PrivateTmp systemd sandboxing
  - CapabilityBoundingSet NoNewPrivileges systemd container
  - systemd service drop-in override security configuration
  - ReadWritePaths MemoryMax TasksMax systemd resource limits
  - harden systemd service root filesystem protection
summary: "Harden Linux systemd services with built-in sandboxing directives — ProtectHome, ProtectSystem, CapabilityBoundingSet, NoNewPrivileges, PrivateTmp, and systemd-analyze security scoring. Includes real hardened service files for common homelab daemons."
canonical: "https://gntech.dev/posts/systemd-service-hardening-linux/"
---

Many homelab administrators focus on network firewalls, container security, and kernel parameters — but overlook the sandboxing features built into systemd itself. Every service that runs on your Linux host can be locked down with zero code changes, using systemd's security directives.

The `systemd-analyze security` command exposes the current exposure level of every unit on your system, scoring each one on a scale from 0 (safe) to 10 (exposed). By default, most services score 9+. With the directives in this guide, you can push them to 3 or lower.

This guide covers the security directives that matter, how to audit your current services, how to apply hardening through drop-in overrides without touching vendor unit files, and real hardened configurations for common homelab daemons like Nginx, Prometheus, and Docker containers.

Every command and config works on systemd 250+ (Ubuntu 22.04+, Debian 12+, Fedora 38+) and most will work on systemd 240+ (Ubuntu 20.04+).

---

## systemd Security Directives — The Essential Set

systemd provide around 40 security-related directives for `[Service]` sections. Most fall into four categories: filesystem isolation, process isolation, capability reduction, and resource limits. These are the ones that give you the most security per line of config.

### Filesystem Sandboxing

```ini
[Service]
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
```

| Directive | What it does | Effect |
|---|---|---|
| `ProtectSystem=strict` | Makes `/usr` and `/etc` read-only. The service can only write to explicitly allowed paths. | Blocks malware from modifying system binaries or config. |
| `ProtectSystem=full` | Makes `/usr` read-only, `/etc` read-only, `/var` writable. | Good balance for services that need to write logs to `/var/log`. |
| `ProtectHome=true` | Makes `/home`, `/root`, `/run/user` inaccessible. The process sees empty directories. | Prevents reading SSH keys, user documents, and dotfiles. |
| `PrivateTmp=true` | Mounts a private `/tmp` and `/var/tmp` namespace. | Prevents /tmp race-condition exploits and temp file snooping. |
| `PrivateDevices=true` | Provides a minimal `/dev` with only null, zero, random, and urandom. | Blocks direct hardware access. |
| `ProtectKernelTunables=true` | Makes `/sys` and `/proc/sys` read-only. | Blocks kernel parameter changes from the service. |
| `ProtectKernelModules=true` | Blocks loading or listing kernel modules. | Prevents kernel module escalation. |
| `ProtectControlGroups=true` | Makes cgroup filesystems read-only. | Prevents escaping cgroup isolation. |

### Process Isolation

```ini
[Service]
NoNewPrivileges=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true
LockPersonality=true
```

| Directive | What it does |
|---|---|
| `NoNewPrivileges=true` | Blocks the process and its children from gaining new privileges via `setuid`, `setcap`, or `capability`-granting syscalls. This is the single most impactful hardening directive. It is essentially non-negotiable. |
| `MemoryDenyWriteExecute=true` | Blocks `mmap(PROT_EXEC)` on writable memory. Prevents JIT spray and shellcode injection. Breaks some JIT compilers (Python with JIT, V8). |
| `RestrictSUIDSGID=true` | Blocks `chmod` and `chown` on setuid/setgid bits. |
| `LockPersonality=true` | Prevents changing the execution domain via `personality()`. |

### Capability Reduction

```ini
[Service]
CapabilityBoundingSet=
AmbientCapabilities=
```

`CapabilityBoundingSet` is a whitelist of Linux capabilities the service can ever use. Start with an empty set and add only what the service needs:

```ini
# Common minimal sets for different service types

# Static file server (Nginx serving static content)
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

# Reverse proxy that needs privilege ports but nothing else
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_NET_RAW

# Backup agent that binds sockets and forks
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SYS_PTRACE

# Docker daemon (broad capabilities required)
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_NET_ADMIN CAP_SYS_ADMIN CAP_SYS_PTRACE
```

To find out what capabilities a specific service needs, run it without `CapabilityBoundingSet`, then check the journal:

```bash
journalctl -u myservice.service -p err | grep -i capability
```

If the service logs something like "Operation not permitted" at startup, add the missing capability and retry.

### Network and Syscall Filtering

```ini
[Service]
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallFilter=@system-service
SystemCallArchitectures=native
IPAddressDeny=any
```

| Directive | What it does |
|---|---|
| `RestrictAddressFamilies` | Whitelist of socket address families. A service that only connects to localhost doesn't need `AF_INET` or `AF_INET6`. |
| `SystemCallFilter` | Whitelist or blacklist of syscalls. `@system-service` is a systemd-maintained set appropriate for most daemons. |
| `SystemCallArchitectures=native` | Only allow native syscalls. Blocks 32-bit syscalls on 64-bit systems, preventing some compatibility-layer exploits. |
| `IPAddressDeny=any` | Blocks all IPv4 and IPv6 traffic. Pair with `IPAddressAllow=` to whitelist specific addresses. |

### Resource Limits

```ini
[Service]
MemoryMax=512M
TasksMax=128
LimitNOFILE=4096
```

These prevent a single compromised service from DoSing the host by exhausting memory, processes, or file descriptors.

---

## Auditing with systemd-analyze security

Before hardening anything, establish a baseline. The `systemd-analyze security` command evaluates every active unit and assigns a numeric exposure level.

```bash
# Score every service, sorted by exposure (most exposed first)
systemd-analyze security --vulnerable | head -20
```

Example output for a default-service state:

```
  SERVICE NAME                                                          EXPOSURE
~ sshd.service                                                            9.6 SAFE
~ systemd-journald.service                                                4.6 SAFE
~ prometheus-node-exporter.service                                        9.3 SAFE
~ nginx.service                                                           9.0 SAFE
```

A score of 9.6 means the service has almost no sandboxing. With hardening, you can bring these down to 2–3.

To inspect a single unit in detail:

```bash
systemd-analyze security nginx.service
```

This shows exactly which security directives are set (or missing) and why the score is what it is:

```
  NAME                                                            DESCRIPTION                      EXPOSURE
✗ RootDirectoryOrRootImage=/…                                   Root directory is not changed        0.1
✗ User=/DynamicUser=…                                            Service runs as root user             0.2
✗ CapabilityBoundingSet=~CAP_SETUID CAP_SETGID …                 Service has no capability whitelist   0.1
  …
```

Use this output to identify the low-hanging fruit on each service.

---

## Applying Hardening with Drop-In Overrides

Never edit vendor unit files in `/lib/systemd/system/`. Package updates overwrite them. Instead, use drop-ins:

```bash
# Create a drop-in directory for any service
sudo mkdir -p /etc/systemd/system/nginx.service.d/

# Create a hardened override
sudo tee /etc/systemd/system/nginx.service.d/hardening.conf << 'EOF'
[Service]
# Filesystem sandboxing
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

# Process isolation
NoNewPrivileges=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true
LockPersonality=true

# Capabilities — Nginx only needs port binding
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_NET_RAW

# Syscall filtering
SystemCallFilter=@system-service
SystemCallArchitectures=native

# Network—Nginx needs full network access
# (omit RestrictAddressFamilies for reverse proxies)

# Resource limits
MemoryMax=256M
TasksMax=256
LimitNOFILE=16384
EOF
```

Then apply and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx.service
sudo systemd-analyze security nginx.service
```

The score should drop from ~9.0 to ~2.5 on a clean configuration.

**Common breakage points and fixes:**

- If Nginx fails to start with `socket()` errors: add `CAP_NET_RAW`
- If Nginx can't read SSL certificates from a custom path: add `ReadWritePaths=/etc/ssl/private`
- If the service can't write logs: change `ProtectSystem=full` (not `strict`) or add `ReadWritePaths=/var/log/nginx`
- If `MemoryDenyWriteExecute=true` breaks a JIT-based tool (Python, Lua, some Node.js addons): remove that line or set it to `false`

### ReadWritePaths for selective writes

When `ProtectSystem=strict` is too restrictive, use `ReadWritePaths` to punch holes in the read-only filesystem:

```ini
[Service]
ProtectSystem=strict
ReadWritePaths=/var/lib/prometheus
ReadWritePaths=/var/log/prometheus
ReadWritePaths=/etc/prometheus
```

This keeps everything else read-only while allowing the service to write to exactly the directories it needs.

---

## Real-World Hardened Configurations

### Prometheus Node Exporter (Minimal Score Target: 1.5)

Node exporter needs to read `/proc`, `/sys`, and `/host` filesystem paths. It does not need network access to arbitrary hosts, kernel modules, or user home directories.

```ini
# /etc/systemd/system/prometheus-node-exporter.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

NoNewPrivileges=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true

CapabilityBoundingSet=

RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallFilter=@system-service
SystemCallArchitectures=native

MemoryMax=128M
TasksMax=32
```

Node exporter needs zero capabilities and only the standard syscall set. Its exposure drops to ~1.5.

### Docker Daemon (As Locked As Possible)

Docker requires broad capabilities by nature — it manages namespaces, mounts, networking, and cgroups. But you can still clamp down:

```ini
# /etc/systemd/system/docker.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true

NoNewPrivileges=true

CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_NET_ADMIN CAP_NET_RAW CAP_SYS_ADMIN CAP_SYS_PTRACE CAP_SYS_RESOURCE CAP_DAC_OVERRIDE CAP_CHOWN CAP_FOWNER CAP_SETUID CAP_SETGIP
```

Note: `ProtectKernelModules=true` and `MemoryDenyWriteExecute=true` may break Docker's overlay2 storage driver. Test thoroughly.

### PostgreSQL

```ini
# /etc/systemd/system/postgresql.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

NoNewPrivileges=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true

CapabilityBoundingSet=

RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
SystemCallFilter=@system-service
SystemCallArchitectures=native

MemoryMax=4G
TasksMax=500
LimitNOFILE=65536
```

---

## First Steps for Every Homelab

If you want the most impact with the least effort, apply these three directives to every service:

```ini
[Service]
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
```

These three alone drop most services from ~9.5 to ~3.8. They are safe for essentially every daemon — I have yet to find a common service that breaks with only these three.

From there, audit each service with `systemd-analyze security` and add directives incrementally:

1. Run `systemd-analyze security <service>` and note the issues.
2. Add `ProtectSystem=full` → test → if it works, move to `strict`.
3. Add `CapabilityBoundingSet=` (empty) → test → if it fails, add back capabilities one at a time from the journal errors.
4. Add `SystemCallFilter=@system-service` → test.
5. Add `MemoryDenyWriteExecute=true` → test (most likely to break JIT).

---

## Scripted Hardening

For homelabs with tens of services, hardening each one manually is tedious. This one-liner generates drop-in files for every service on the system with the minimum safe directives:

```bash
for unit in $(systemctl list-units --type=service --no-legend | awk '{print $1}'); do
  dir="/etc/systemd/system/${unit}.d"
  sudo mkdir -p "$dir"
  sudo tee "$dir/hardening.conf" > /dev/null << 'EOF'
[Service]
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
EOF
done
sudo systemctl daemon-reload
```

This is a starting point. After applying it, identify the services that break (and they will — some daemons legitimately need root access across the filesystem) and remove the offending directives from their individual drop-ins.

---

## Verification

After hardening, confirm everything is working:

```bash
# Check the new exposure levels
systemd-analyze security --vulnerable | head -20

# Verify specific services are still running
systemctl is-active nginx.service prometheus-node-exporter.service

# Check for capability-related errors
journalctl -p err -g "capability\|permission\|denied" --since "5 minutes ago"

# Confirm NoNewPrivileges is effective (should print nothing)
for pid in $(systemctl show -p MainPID nginx.service | cut -d= -f2); do
  grep -l NoNewPrivs /proc/$pid/status
done
```

With proper hardening, your systemd services run with the minimum filesystem access, the minimum capabilities, and the minimum syscall surface needed to do their jobs. No root access to your home directory, no writable system binaries, no privilege escalation vectors. And nothing depends on custom tooling — it is all built into the init system that already manages every service on your Linux host.

Apply these changes incrementally, test each one, and within an afternoon you can drop your average service exposure from 9 to 3 without touching a single line of application code.
