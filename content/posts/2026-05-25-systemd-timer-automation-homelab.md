---
title: "Systemd Timer Units — Replacing Cron for Homelab Automation"
description: "Replace cron with systemd timer units for homelab automation — real logging, dependency management, persistent schedules, and monotonic intervals with practical examples for backups, healthchecks, and maintenance."
date: 2026-05-25T10:00:00-04:00
tags:
  - linux
  - homelab
  - automation
  - systemd
  - devops
keywords:
  - systemd timer units homelab automation
  - replace cron with systemd timers Linux
  - systemd timer OnCalendar persistent monotonic
  - Linux automation systemd timers vs cron comparison
  - systemd backup timer ZFS snapshot schedule
  - systemd timer Docker container healthcheck
  - homelab task scheduling systemd service units
summary: "Replace cron with systemd timer units for reliable, observable homelab task scheduling — persistent schedules, real journald logging, monotonic intervals, and hardened service units with practical backup, maintenance, and healthcheck examples."
canonical: "https://gntech.dev/posts/systemd-timer-automation-homelab/"
---

Cron has been Linux's go-to scheduler for fifty years. It works. But
it also has blind spots: no logging beyond mail spool, no dependency
chaining, no catch-up for missed runs, and no integration with the
rest of the system's init machinery.

Systemd timers solve all of this natively. If your homelab runs
systemd — and any modern Linux distribution does — you already have
a better scheduler installed. This guide covers when and why to
replace cron with systemd timers, the exact unit file patterns you
need, and real-world homelab examples you can copy today.

---

## Why Systemd Timers Beat Cron in a Homelab

Cron is simple. A one-liner in a crontab and you are done. But in a
homelab with containers, ZFS datasets, Proxmox nodes, and MikroTik
backups, your tasks accumulate fast. The cracks start to show:

| Capability              | cron                      | systemd timer                   |
|-------------------------|---------------------------|---------------------------------|
| Logging                 | Mail spool or syslog      | `journalctl` with structured metadata |
| Missed-run catch-up     | Task is skipped           | `Persistent=true` fires on next boot |
| Random delay            | Manual sleep hack         | `RandomizedDelaySec=` built-in  |
| Dependencies            | None                      | `After=`, `Requires=`, `BindsTo=` |
| Sandboxing              | None                      | `ProtectHome=`, `PrivateTmp=`, etc. |
| Failed-run notification | Mail on stderr            | `OnFailure=` unit chaining     |
| Per-user scheduling     | `crontab -e` per user     | `--user` systemd instance       |
| Timezone-aware          | Requires `CRON_TZ=`       | Respects system timezone        |
| Verification           | Parse visually            | `systemd-analyze calendar`     |

For a homelab running 10-20 recurring tasks — container restarts,
zfs snapshot rotation, log cleanup, health pings, backup syncs —
systemd timers provide observability and reliability that cron
simply cannot match.

---

## Anatomy of a Systemd Timer

A timer always comes in a pair: a `.timer` unit defines when to run,
and a `.service` unit defines what to run. The timer activates the
service, the service does the work, and systemd tracks both.

### Service Unit

```ini
# /etc/systemd/system/docker-cleanup.service
[Unit]
Description=Clean up unused Docker images and volumes

[Service]
Type=oneshot
ExecStart=/usr/local/bin/docker-cleanup.sh
```

### Timer Unit

```ini
# /etc/systemd/system/docker-cleanup.timer
[Unit]
Description=Run Docker cleanup daily at 3 AM

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
```

### Enable and Start

```bash
systemctl daemon-reload
systemctl enable --now docker-cleanup.timer

# Verify
systemctl list-timers --all
```

Output:

```
NEXT                        LEFT          LAST                        PASSED  UNIT                  ACTIVATES
Mon 2026-05-26 03:00:00 EDT 13h left      Sun 2026-05-25 03:17:42 EDT 9h ago  docker-cleanup.timer   docker-cleanup.service
```

Compare that to `crontab -l` showing `0 3 * * * /usr/local/bin/docker-cleanup.sh`.
The timer output tells you the next run, last run, and how long ago
it ran — all without grepping logs.

---

## OnCalendar Syntax — The Replacement for Cron Expressions

Systemd's OnCalendar syntax is more readable than cron but follows
its own pattern: `DOW YYYY-MM-DD HH:MM:SS`. Missing components act
as wildcards.

### Common Patterns

| Schedule                  | OnCalendar value               | Equivalent cron              |
|---------------------------|--------------------------------|------------------------------|
| Every day at 2:30 AM      | `*-*-* 02:30:00`               | `30 2 * * *`                 |
| Every 15 minutes          | `*:0/15`                       | `*/15 * * * *`               |
| Every hour                | `hourly` or `*:0`              | `0 * * * *`                  |
| Daily                     | `daily` or `*-*-* 00:00:00`   | `0 0 * * *`                  |
| Weekly (Monday midnight)  | `Mon *-*-* 00:00:00`           | `0 0 * * 1`                  |
| First day of month 6 AM   | `*-*-1 06:00:00`               | `0 6 1 * *`                  |
| Every 30 minutes          | `*:0/30`                       | `*/30 * * * *`               |
| Weekdays at 8 PM          | `Mon..Fri 20:00:00`            | `0 20 * * 1-5`               |

### Validate Before Deploying

```bash
systemd-analyze calendar "Mon..Fri 20:00:00"
```

Output:

```
  Original form: Mon..Fri 20:00:00
Normalized form: Mon..Fri 20:00:00
    Next elapse: Mon 2026-05-25 20:00:00 EDT
       (in UTC): Mon 2026-05-25 20:00:00 EDT
       From now: 6h left
```

Always run `systemd-analyze calendar` before deploying a new timer.
A typo in the DOW portion does not error — it silently produces an
empty schedule and the job never runs.

---

## Monotonic Timers — Run Relative to Boot or Last Run

Not every task needs a wall-clock schedule. Some tasks should run
relative to system state:

```ini
# /etc/systemd/system/healthcheck.timer
[Timer]
# Run 5 minutes after boot
OnBootSec=5min

# Then every 30 minutes after the last run
OnUnitActiveSec=30min
```

This is perfect for:
- **Health pings** to a monitoring service after the machine boots
- **Temp file cleanup** that should run periodically but has no
  specific preferred wall time
- **Docker container restart policies** that need retry logic
  outside Docker's built-in restart

Monotonic timers do not accept `OnCalendar` — the two families are
mutually exclusive in a single timer unit. Use monotonic when the
exact wall clock is irrelevant; use OnCalendar when it matters.

---

## Persistent Timers — Catch Up on Missed Runs

The `Persistent=true` flag is the biggest practical advantage over
cron for homelab machines that may not run 24/7.

```ini
[Timer]
OnCalendar=daily
Persistent=true
```

With cron, if your machine was off at 3 AM, that day's backup
simply never runs. With a persistent systemd timer, the service
fires immediately on the next boot — even if the machine was off
for three days, it catches up on the first boot after the outage.

Pair `Persistent=true` with `RandomizedDelaySec` to avoid hammering
resources when multiple persistent timers trigger simultaneously
after a reboot:

```ini
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m
```

---

## Real-World Homelab Examples

### 1. ZFS Snapshot Rotation

```ini
# /etc/systemd/system/zfs-snapshots.service
[Unit]
Description=Rotate ZFS snapshots

[Service]
Type=oneshot
ExecStart=/usr/local/bin/zfs-snapshot-rotate.sh
```

```ini
# /etc/systemd/system/zfs-snapshots.timer
[Unit]
Description=Run ZFS snapshot rotation every 4 hours

[Timer]
OnCalendar=*:0/4
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
```

The script (`/usr/local/bin/zfs-snapshot-rotate.sh`):

```bash
#!/bin/bash
# ZFS snapshot rotation — keep hourly for 24h, daily for 7d, weekly for 4w
POOL="tank"

# Create hourly snapshot
zfs snapshot -r "${POOL}@auto-$(date +%Y%m%d-%H%M)"

# Prune snapshots older than 24 hours if they are not daily patterns
zfs list -H -o name -t snapshot -r "${POOL}" | grep auto- | while read snap; do
    ts=$(echo "$snap" | grep -oP '\d{8}-\d{4}')
    if [[ $(date -d "${ts:0:8} ${ts:9:2}:${ts:11:2}" +%s) -lt $(date -d '24 hours ago' +%s) ]]; then
        # Keep if it matches daily midnight pattern
        [[ "$snap" =~-[0-9]{8}-0000$ ]] && continue
        zfs destroy "$snap"
    fi
done
```

### 2. Docker Prune with Health Notification

```ini
# /etc/systemd/system/docker-prune.service
[Unit]
Description=Prune unused Docker resources
Wants=docker.service

[Service]
Type=oneshot
ExecStart=docker system prune -af --volumes
ExecStartPost=/usr/local/bin/notify-health.sh "Docker prune completed"

# Sandboxing — Docker needs the socket but nothing else
ProtectSystem=strict
PrivateTmp=true
NoNewPrivileges=true
```

```ini
# /etc/systemd/system/docker-prune.timer
[Timer]
OnCalendar=Sun 03:00:00
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
```

The `Wants=docker.service` dependency ensures the Docker daemon is
running before the prune fires. Without this, the exec would fail
silently.

### 3. Proxmox PBS Garbage Collection

For Proxmox Backup Server, garbage collection reclaims space from
pruned backup chunks. A weekly GC keeps your datastore healthy:

```ini
# /etc/systemd/system/pbs-gc.service
[Unit]
Description=Proxmox Backup Server garbage collection
After=proxmox-backup.service

[Service]
Type=oneshot
ExecStart=proxmox-backup-manager garbage-collection --output-format text
StandardOutput=journal
```

```ini
# /etc/systemd/system/pbs-gc.timer
[Timer]
OnCalendar=Sun 04:00:00
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
```

### 4. Homelab Health Ping

```ini
# /etc/systemd/system/homelab-healthcheck.service
[Unit]
Description=Ping Uptime Kuma or similar health endpoint

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -sf -o /dev/null \
  https://health.gntech.dev/ping/homelab-srv1

# Sandbox the curl call
ProtectSystem=strict
PrivateTmp=true
ProtectHome=true
NoNewPrivileges=true
CapabilityBoundingSet=
SystemCallFilter=@basic-io
```

```ini
# /etc/systemd/system/homelab-healthcheck.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

This runs 2 minutes after boot, then every 5 minutes. Uptime Kuma
(or your monitoring tool of choice) alerts you if the ping stops —
dead simple, zero agent overhead.

### 5. Off-Site Backup Sync

```ini
# /etc/systemd/system/offsite-backup.service
[Unit]
Description=Sync backups to off-site storage
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/restic-backup.sh

# Security: read-only filesystem except where needed
ProtectSystem=full
ReadWritePaths=/mnt/backup-cache
PrivateTmp=true
ProtectHome=true
NoNewPrivileges=true
```

```ini
# /etc/systemd/system/offsite-backup.timer
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=20m

[Install]
WantedBy=timers.target
```

The `After=network-online.target` ensures the network is actually
up before the backup starts — something cron users typically hack
with a `sleep 30` in the script.

---

## Hardening Timer Service Units

Since every timer pair includes a service unit, you get systemd's
full sandboxing arsenal for free. These are the most useful options
for homelab timer services:

| Option                       | Effect                                   |
|------------------------------|------------------------------------------|
| `ProtectSystem=strict`      | Read-only /usr, /etc (except whitelisted)|
| `ProtectHome=true`          | /root, /home are inaccessible            |
| `PrivateTmp=true`           | Isolated /tmp per invocation             |
| `NoNewPrivileges=true`      | Prevents privilege escalation            |
| `CapabilityBoundingSet=`    | Drops all kernel capabilities            |
| `SystemCallFilter=@system-service` | Restricts allowed syscalls       |
| `MemoryMax=256M`            | Limits memory usage                      |
| `TasksMax=32`               | Limits number of tasks/processes         |
| `ReadWritePaths=`           | Explicit writable paths, everything else read-only |

Example for a script that only needs to write to one backup directory:

```ini
[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
ProtectSystem=strict
ReadWritePaths=/mnt/backup
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
CapabilityBoundingSet=
MemoryMax=512M
TasksMax=16
```

---

## User Timers — Per-User Scheduling

Not all homelab automation runs as root. Systemd supports per-user
timers that run under your user's systemd instance:

```bash
# Create user unit directory
mkdir -p ~/.config/systemd/user/

# Create the service
cat > ~/.config/systemd/user/update-hosts.service << 'EOF'
[Unit]
Description=Update local hosts file from Pi-hole

[Service]
Type=oneshot
ExecStart=/home/gntech/bin/update-hosts.sh
EOF

# Create the timer
cat > ~/.config/systemd/user/update-hosts.timer << 'EOF'
[Unit]
Description=Update hosts file every 6 hours

[Timer]
OnCalendar=*:0/6
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Enable for the user session
systemctl --user daemon-reload
systemctl --user enable --now update-hosts.timer

# Verify
systemctl --user list-timers
```

Enable lingering so user timers survive logout:

```bash
loginctl enable-linger $(whoami)
```

User timers are ideal for:
- User-level backups (restic repos, git repos)
- Updating personal dotfiles or hosts files
- Emailing reports or syncing calendars
- Any automation that should not run as root

---

## Monitoring and Debugging

### List All Active Timers

```bash
systemctl list-timers --all

# Filter for a specific timer
systemctl list-timers --all | grep backup
```

### Check Timer Status

```bash
systemctl status docker-cleanup.timer
systemctl status docker-cleanup.service  # Shows last run result
```

### Journal Logs for the Last Run

```bash
# Last 50 lines from the service's most recent run
journalctl -u docker-cleanup.service -n 50 --no-pager

# Follow logs in real time
journalctl -u docker-cleanup.service -f

# Show all runs from today
journalctl -u docker-cleanup.service --since today
```

### Force a Run (Manual Trigger)

```bash
systemctl start docker-cleanup.service
```

Running the service unit directly bypasses the timer schedule but
still logs through journald — useful for testing.

### Test the Timer Schedule

```bash
systemd-analyze verify /etc/systemd/system/docker-cleanup.timer
systemd-analyze calendar "*-*-* 02:30:00"
```

### Check for Failures

```bash
# Show failed units from the last 24 hours
systemctl list-units --state=failed

# Show timer units that missed their schedule
journalctl -u docker-cleanup.timer --since "24 hours ago" | grep -i "missed\|skipped\|failed"
```

---

## Converting Existing Cron Jobs

Migration script to convert crontab entries to systemd timer units
is straightforward for simple cases:

```bash
#!/bin/bash
# /usr/local/bin/cron2systemd.sh
# Usage: cron2systemd.sh "30 2 * * * /usr/local/bin/backup.sh" "backup"

EXPR="$1"
NAME="$2"
CRON_REGEX='([0-9*,/-]+) ([0-9*,/-]+) ([0-9*,/-]+) ([0-9*,/-]+) ([0-9*,/-]+) (.*)'

if [[ "$EXPR" =~ $CRON_REGEX ]]; then
    MINUTE="${BASH_REMATCH[1]}"
    HOUR="${BASH_REMATCH[2]}"
    DAY="${BASH_REMATCH[3]}"
    MONTH="${BASH_REMATCH[4]}"
    DOW="${BASH_REMATCH[5]}"
    COMMAND="${BASH_REMATCH[6]}"

    cat > "/etc/systemd/system/${NAME}.service" << EOF
[Unit]
Description=${NAME} (converted from cron)

[Service]
Type=oneshot
ExecStart=${COMMAND}
EOF

    cat > "/etc/systemd/system/${NAME}.timer" << EOF
[Unit]
Description=${NAME} timer (converted from cron)

[Timer]
OnCalendar=${DOW} *-*-${DAY} ${HOUR}:${MINUTE}:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

    echo "Created ${NAME}.service and ${NAME}.timer"
    echo "Run: systemctl daemon-reload && systemctl enable --now ${NAME}.timer"
fi
```

This handles the common case. For complex schedules with step values
(`*/15`), you will need to adjust the OnCalendar expression manually.

---

## When to Still Use Cron

Systemd timers are not a universal replacement. Keep cron for:

1. **Minimal containers** — Alpine-based Docker images do not run
   systemd. Use the container's own cron or supervisord.

2. **Legacy systems** — Older distributions with sysvinit or
   systemd < v236 lack timer features like `RandomizedDelaySec`.

3. **Simple one-off scripts** — If you need literally one line and
   will never need logging, cron's `@reboot` and one-liner syntax
   is faster to type.

4. **Non-systemd environments** — WSL1, some embedded Linux, or
   systems with systemd masked.

For everything else in a modern homelab — backups, pruning,
healthchecks, sync jobs, snapshot rotation — systemd timers provide
better observability, reliability, and security with no external
dependencies.

---

## Summary

Systemd timers replace cron with a first-class scheduling system that
integrates with the rest of your Linux stack:

1. **Each timer needs two files**: a `.timer` for the schedule and a
   `.service` for the command — enable both with `systemctl enable --now`.
2. **Use `OnCalendar` for wall-clock schedules** and `OnBootSec` /
   `OnUnitActiveSec` for monotonic intervals.
3. **Always add `Persistent=true`** for tasks that should catch up
   after downtime (backups, pruning).
4. **Add `RandomizedDelaySec`** to prevent multiple timers from
   hammering resources simultaneously after boot.
5. **Sandbox service units** with `ProtectSystem`, `PrivateTmp`, and
   `NoNewPrivileges` — these apply to any systemd unit, not just timers.
6. **Use `journalctl -u servicename.service`** for structured logging
   — no more grepping mail spool or syslog files.
7. **Validate schedules with `systemd-analyze calendar`** before
   deploying — catch typos before they cause silent failures.

A homelab running a dozen timer-managed tasks — ZFS snapshots,
Docker pruning, PBS garbage collection, health pings, and off-site
backups — runs more reliably and observably than the same tasks
managed by cron, with no additional software to install.
