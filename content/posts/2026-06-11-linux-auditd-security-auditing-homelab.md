---
title: "Linux auditd Security Auditing — Monitor Proxmox and Docker Activity"
description: "Set up Linux auditd to monitor Docker container execution, Proxmox VM changes, and file access in your homelab. Covers audit rules, ausearch reporting, and integration with systemd-journald."
date: 2026-06-11T14:00:00-04:00
tags:
  - linux
  - homelab
  - security
  - monitoring
  - docker
keywords:
  - Linux auditd setup homelab security monitoring
  - auditd Docker container monitoring rules
  - Proxmox host audit daemon configuration file integrity
  - Linux auditd rules system calls file access monitoring
  - auditd ausearch aureport security auditing homelab
  - Docker daemon audit integration Linux security
  - auditd systemd-journald log aggregation homelab
summary: "Configure Linux auditd to watch container starts, file changes, and Proxmox host activity. Includes auditctl rules, ausearch queries, and Docker integration for comprehensive homelab security auditing."
canonical: "https://blog.gntech.me/posts/linux-auditd-security-auditing-homelab/"
---

Your Proxmox host runs a dozen Docker containers, a handful of LXCs, and has SSH exposed to the local network. You trust your users, but you have no record of who ran `docker exec --privileged` into that production container or when someone edited `/etc/pve/user.cfg`.

This is the security blind spot in most homelabs: the kernel can log everything, but nobody enables it.

Linux auditd is the built-in kernel-level auditing framework that captures syscalls, file access, process execution, and configuration changes. It costs no additional software, minimal CPU overhead, and produces structured logs you can query with familiar tools. This guide walks through a complete auditd deployment for a Docker and Proxmox homelab — from basic install to daily alert queries.

## What Is auditd? The Kernel Audit Framework

auditd is not a userland add-on. It sits at the kernel level, intercepting system calls through the Linux Audit subsystem and forwarding events to userspace via a netlink socket. The architecture has three layers:

1. **Kernel** — captures syscalls and file watches via the audit framework compiled into the kernel
2. **auditd daemon** — receives events from the kernel, writes them to disk, and optionally forwards them to remote log servers
3. **ausearch / aureport** — command-line tools for searching and summarizing audit logs

The systemd integration is minimal: `audit.socket` activates the daemon on demand, and `auditd.service` manages the full lifecycle. You explicitly enable it — it stays off by default on most distributions.

## Installing and Enabling auditd

Installation is a single package on Debian-based systems:

```bash
apt update
apt install -y auditd audispd-plugins
systemctl enable --now auditd
systemctl status auditd
```

Verify the kernel audit subsystem is active:

```bash
auditctl -s
```

Expected output shows `enabled 1` and a valid `pid` for the daemon.

The main configuration lives at `/etc/audit/auditd.conf`. Defaults are conservative for general-purpose systems, but for a homelab bump these values:

```
max_log_file = 128
max_log_file_action = rotate
space_left_action = email
admin_space_left_action = suspend
disk_full_action = suspend
```

`max_log_file_action = rotate` prevents the daemon from stopping when the log reaches the size limit. Set `space_left_action` to `email` if you have local mail configured, otherwise use `syslog` to forward to journald.

## Essential Audit Rules for Homelab Security

Rules are added with `auditctl` at runtime and persist through rule files. These three categories cover the critical homelab attack surface.

### Monitor Docker Daemon and Container Execution

The Docker binary and its data directory are the primary targets:

```bash
auditctl -w /usr/bin/docker -p x -k docker-execution
auditctl -w /usr/bin/containerd -p x -k containerd-exec
auditctl -w /var/lib/docker -p wa -k docker-data
auditctl -w /etc/docker/daemon.json -p wa -k docker-config
```

The first rule watches for any execution of `docker` — every `docker run`, `docker exec`, `docker ps` that hits disk triggers an event. The `-k` flag assigns a key for easy filtering with `ausearch`. The `-p x` flag watches execute permission; `-p wa` watches write and attribute changes for configuration and data paths.

### Monitor Proxmox Host Operations

Proxmox management tools — `qm` for VMs, `pct` for containers — are CLI binaries that should only run during planned maintenance:

```bash
auditctl -w /usr/sbin/qm -p x -k proxmox-qm
auditctl -w /usr/sbin/pct -p x -k proxmox-pct
auditctl -w /usr/sbin/pvesh -p x -k proxmox-api
auditctl -w /etc/pve -p wa -k proxmox-config
auditctl -w /var/log/pve -p wa -k proxmox-logs
```

The `/etc/pve` directory is a PMXA filesystem (FUSE) shared across cluster nodes. Watching it captures changes to VM configs, storage definitions, and user permissions through the Proxmox web interface or CLI. The `/var/log/pve` watch catches task log writes — who started, stopped, or migrated a VM.

### Monitor Critical System Paths

User database, SSH configuration, and cron are common privilege escalation vectors:

```bash
auditctl -w /etc/passwd -p wa -k user-db
auditctl -w /etc/shadow -p wa -k user-db
auditctl -w /etc/group -p wa -k user-db
auditctl -w /etc/ssh/sshd_config -p wa -k ssh-config
auditctl -w /etc/ssh/sshd_config.d/ -p wa -k ssh-config
auditctl -w /root/.ssh -p wa -k ssh-keys
auditctl -w /etc/crontab -p wa -k cron-config
auditctl -w /etc/cron.d/ -p wa -k cron-config
```

### Monitor Sensitive System Calls

File-watch rules only cover specific paths. Syscall rules catch actions anywhere in the filesystem and on kernel objects:

```bash
auditctl -a always,exit -S execve -F key=process-exec
auditctl -a always,exit -S execveat -F key=process-exec
auditctl -a always,exit -S mount -S umount2 -k mount-changes
auditctl -a always,exit -S sethostname -S setdomainname -k hostname-changes
auditctl -a always,exit -S unlink -S unlinkat -S rmdir -k file-deletion
```

The `execve` syscall rule generates an event for every binary execution on the system — including scripts launched by interpreters like Python and Bash. This is your catch-all for discovering unauthorized processes. Combine it with the docker-execution rules to correlate: was this `docker exec` an authorized deployment or a compromise?

## Making Audit Rules Persistent

Runtime rules with `auditctl` do not survive a reboot. For persistence, write rule files to `/etc/audit/rules.d/` and load them with `augenrules`:

```bash
cat > /etc/audit/rules.d/docker.rules << 'EOF'
-w /usr/bin/docker -p x -k docker-execution
-w /usr/bin/containerd -p x -k containerd-exec
-w /var/lib/docker -p wa -k docker-data
-w /etc/docker/daemon.json -p wa -k docker-config
EOF
```

Repeat for Proxmox, system paths, and syscall rules:

```bash
cat > /etc/audit/rules.d/proxmox.rules << 'EOF'
-w /usr/sbin/qm -p x -k proxmox-qm
-w /usr/sbin/pct -p x -k proxmox-pct
-w /usr/sbin/pvesh -p x -k proxmox-api
-w /etc/pve -p wa -k proxmox-config
-w /var/log/pve -p wa -k proxmox-logs
EOF
```

```bash
cat > /etc/audit/rules.d/system.rules << 'EOF'
-w /etc/passwd -p wa -k user-db
-w /etc/shadow -p wa -k user-db
-w /etc/group -p wa -k user-db
-w /etc/ssh/sshd_config -p wa -k ssh-config
-w /etc/ssh/sshd_config.d/ -p wa -k ssh-config
-w /root/.ssh -p wa -k ssh-keys
-w /etc/crontab -p wa -k cron-config
-w /etc/cron.d/ -p wa -k cron-config
EOF
```

```bash
cat > /etc/audit/rules.d/syscall.rules << 'EOF'
-a always,exit -S execve -S execveat -F key=process-exec
-a always,exit -S mount -S umount2 -k mount-changes
-a always,exit -S sethostname -S setdomainname -k hostname-changes
-a always,exit -S unlink -S unlinkat -S rmdir -k file-deletion
EOF
```

Load and verify:

```bash
augenrules --load
auditctl -l
```

## Querying Audit Logs with ausearch and aureport

Once rules are active and events are flowing, the real value comes from querying the log. These commands are your daily audit interface.

### Search by Rule Key

```bash
# All Docker executions today
ausearch -k docker-execution --start today --interpret

# All file access on /etc/pve this hour
ausearch -k proxmox-config --start recent --interpret

# Failed file access (permission denied)
ausearch -f /etc/shadow --failed --start today
```

### Generate Summary Reports

```bash
# Top executed binaries
aureport -x --summary

# File access summary by count
aureport -f

# Login events
aureport -l

# User activity summary
aureport -u --failed
```

### Watch Live Events

```bash
tail -f /var/log/audit/audit.log | ausearch --interpret --input -
```

### JSON Output for Log Aggregation

```bash
ausearch -k docker-execution --start today --format json
```

This is directly ingestible by Loki, Elasticsearch, or any JSON log pipeline. If you run the Grafana Loki stack in your homelab, pipe auditd events there for dashboards.

## Integrating auditd with systemd-journald

auditd events appear in systemd-journald via the `audispd` syslog plugin. Enable it:

```bash
systemctl enable --now auditd
```

View audit events in journald:

```bash
journalctl -t auditd --since today
journalctl _TRANSPORT=audit --since today | tail -50
```

For structured log aggregation, set up the `audisp-remote` plugin to forward to a central syslog server or use the built-in syslog forwarding in `/etc/audit/audisp-remote.conf`:

```
remote_server = 10.0.20.50
port = 601
transport = tcp
```

## Docker-Specific Auditing: Containers and the Docker Socket

auditd complements Docker's built-in event system. Docker events tell you containers started and stopped; auditd tells you who executed the `docker` command and which user on the host triggered it.

Watch the Docker socket for API access:

```bash
auditctl -w /var/run/docker.sock -p rwa -k docker-socket
```

This catches any process reading from or writing to the Docker socket — useful for detecting unauthorized containers or tooling that accesses Docker without going through the CLI.

To catch `docker exec` and `docker attach` sessions, the execve syscall rule combined with the docker binary watch gives you the full picture: which user ran `docker exec -it nginx sh` and at what time.

```bash
ausearch -k docker-execution --start today --interpret | grep "docker exec"
```

## Preventing Audit Log Tampering

Audit logs are only useful if they survive an attack. Once all rules are loaded, lock the audit configuration so that no one — including root — can disable or modify rules without a reboot:

```bash
auditctl -e 2
```

Set this as the last rule in one of your rule files to apply it automatically:

```bash
echo "-e 2" >> /etc/audit/rules.d/syscall.rules
augenrules --load
```

After this, `auditctl -e 0` returns permission denied. Only a reboot clears it, and during boot the rules reload before network services start.

For additional protection, forward logs off-host. The `audisp-remote` plugin sends events to a central syslog or a dedicated logging VM. Set it up:

```bash
cat > /etc/audit/audisp-remote.conf << 'EOF'
remote_server = 10.0.20.50
port = 601
transport = tcp
EOF
```

On the remote server, run a syslog listener:

```bash
nc -lk -p 601 > /var/log/remote-audit.log
```

## Storage Management and Log Rotation

auditd logs to `/var/log/audit/audit.log` by default. With active rules on a busy homelab host, expect 10-50 MB per day depending on workload. Set adequate limits:

```
# /etc/audit/auditd.conf
max_log_file = 128
max_log_file_action = rotate
num_logs = 5
```

This keeps 5 rotated files of 128 MB each — roughly 640 MB of history. Adjust based on your storage budget. If you forward to remote logging, you can reduce it further.

The system logrotate configuration at `/etc/logrotate.d/auditd` handles rotation via signal. Verify it exists and reload if needed:

```bash
logrotate -f /etc/logrotate.d/auditd
```

## Verification and Testing

After deploying, run a quick smoke test:

```bash
# List loaded rules (should show 15-25 rules depending on your config)
auditctl -l | wc -l

# Trigger a Docker event
docker run --rm alpine echo "test audit"

# Query for it
ausearch -k docker-execution --start today --interpret | tail -10

# Check audit status
auditctl -s

# Verify immutable mode (if set)
auditctl -e 2 || echo "NOT immutable — set -e 2"
```

Expected output from `auditctl -s` shows `enabled 1`, `pid` of the running daemon, `rate_limit` (default 0 = unlimited), and `backlog_limit` (default 64).

## Conclusion

auditd is one of the most underused security tools in homelabs. It ships with every Linux kernel, costs almost nothing in overhead, and produces forensic-grade logs of everything happening on your host. With the rules in this guide, you cover Docker execution, Proxmox VM management, critical file changes, and system-call-level process monitoring — all with a one-time setup.

Once auditd is running, it works silently in the background. The logs accumulate in `/var/log/audit/audit.log`, ready to answer the question no homelab owner wants to face: What happened, when, and who did it?

Deploy auditd alongside CrowdSec or Fail2ban for a complete host security posture. Set up remote log forwarding if you have a second host. Configure it once, and forget about it — until the day you need it.
