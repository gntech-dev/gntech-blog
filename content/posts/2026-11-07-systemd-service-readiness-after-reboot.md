---
title: "Is Your Linux Service Ready After Reboot? Check More Than Active"
description: "Use a disposable systemd HTTP lab to distinguish enablement, process state, and application readiness, then repeat the checks after reboot."
date: 2026-11-07T12:00:00-04:00
draft: false
ShowToc: true
tags: [linux, systemd, operations, troubleshooting, homelab]
keywords: [systemd readiness, service after reboot, is-active, Type exec]
summary: "Build a loopback-only HTTP service, check the response body, and prove that an active unit can still fail an application readiness check."
cover:
  image: "/images/posts/systemd-readiness/featured.webp"
  alt: "Compact server rack with a green status light beside a laptop in a blue and amber workspace."
  caption: "AI-generated editorial artwork."
  relative: false
---

A service can be enabled for boot and still fail to start. It can also be active while returning the wrong response. When checking a server after maintenance, collect evidence for each layer.

This reference lab targets Debian 12/13 or Ubuntu 24.04 with systemd, Python 3, curl, and sudo. It creates a disposable HTTP service on loopback port 18081. Use a test guest and an approved reboot window for the final check. The expected results below are a procedure to verify, with no claim of execution on a GNTECH host.

## 1. Separate the three questions

| Check | What it establishes |
| --- | --- |
| systemctl is-enabled | Whether the unit has an enablement state such as enabled, disabled, or static. |
| systemctl is-active | Whether systemd currently considers the unit active. |
| Application request | Whether the endpoint returns the status and data your client needs. |

For this lab, readiness means HTTP 200 with a body containing exactly `ready`. A production readiness endpoint might also check a required database operation. Define that contract before designing the probe.

`Type=exec` waits for execution of the service program to succeed before treating startup as successful. It does not wait for HTTP initialization. An application that implements systemd's notification protocol can use `Type=notify` and send its own readiness notification. Select the type supported by the program.

## 2. Create a small disposable service

First check for port conflicts and existing lab resources. Stop if the paths already belong to another workload.

```bash
command -v python3
command -v curl
sudo ss -ltnp 'sport = :18081'
sudo test ! -e /etc/systemd/system/gntech-ready-lab.service &&
sudo test ! -e /var/lib/gntech-ready-lab &&
echo 'Lab paths are available'
```

Continue only if the paths are available and port 18081 is free. The server runs as an unprivileged account and binds only to loopback.

```bash
sudo install -d -m 0755 /var/lib/gntech-ready-lab
printf 'ready\n' | sudo tee /var/lib/gntech-ready-lab/ready.txt >/dev/null

sudo sh -c 'set -C; cat > /etc/systemd/system/gntech-ready-lab.service' <<'UNIT'
[Unit]
Description=Disposable GNTECH readiness lab

[Service]
Type=exec
User=nobody
Group=nogroup
WorkingDirectory=/var/lib/gntech-ready-lab
ExecStart=/usr/bin/python3 -m http.server 18081 --bind 127.0.0.1
Restart=on-failure
RestartSec=2s
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT

sudo systemd-analyze verify /etc/systemd/system/gntech-ready-lab.service
sudo systemctl daemon-reload
sudo systemctl enable --now gntech-ready-lab.service
```

Inspect the loaded service and its current boot log. If validation or startup fails, investigate before proceeding.

```bash
systemctl is-enabled gntech-ready-lab.service
systemctl is-active gntech-ready-lab.service
systemctl show gntech-ready-lab.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts
sudo journalctl -b -u gntech-ready-lab.service --no-pager
```

The Python HTTP server serves static lab content. Keep this instance on loopback and remove it when the exercise is complete.

## 3. Check the application response with a bounded probe

Create a probe in your own home directory. Each request has a connection timeout and a total timeout. The loop retries briefly while the server starts, then exits unsuccessfully if the expected status and body never arrive.

```bash
cat > "$HOME/gntech-ready-probe.sh" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
for attempt in {1..10}; do
  if body="$(curl --fail --silent --show-error \
      --connect-timeout 1 --max-time 2 \
      http://127.0.0.1:18081/ready.txt)" &&
      [[ "$body" == ready ]]; then
    printf 'Ready on attempt %s\n' "$attempt"
    exit 0
  fi
  sleep 1
done
printf 'Readiness failed after 10 attempts\n' >&2
exit 1
BASH
chmod +x "$HOME/gntech-ready-probe.sh"
bash "$HOME/gntech-ready-probe.sh"
```

The successful branch checks the body as well as curl's success status. A web server returning HTTP 200 for an error page would fail this contract if the body differed.

## 4. Prove that process state and readiness can diverge

Rename the marker file while leaving the Python server running. Run these commands individually and inspect their exit status.

```bash
sudo mv /var/lib/gntech-ready-lab/ready.txt \
  /var/lib/gntech-ready-lab/ready.disabled
systemctl is-active gntech-ready-lab.service
bash "$HOME/gntech-ready-probe.sh"
```

The unit should remain active while the probe reports failure because the file request returns 404. Restore the file and repeat the probe.

```bash
sudo mv /var/lib/gntech-ready-lab/ready.disabled \
  /var/lib/gntech-ready-lab/ready.txt
bash "$HOME/gntech-ready-probe.sh"
```

This is a controlled failure in a disposable service. An ongoing production probe needs a monitored result, a clear alert owner, and a recovery procedure. Restart policies react to process failures according to their configuration. A failing external HTTP probe does not itself tell systemd to restart a service.

## 5. Repeat after a planned reboot

Record the boot ID and a baseline result before rebooting.

```bash
cat /proc/sys/kernel/random/boot_id
systemctl is-enabled gntech-ready-lab.service
bash "$HOME/gntech-ready-probe.sh"
```

Reboot normally during the agreed window. After reconnecting, compare the new boot ID, inspect the unit, and rerun the same probe.

```bash
cat /proc/sys/kernel/random/boot_id
systemctl is-active gntech-ready-lab.service
sudo journalctl -b -u gntech-ready-lab.service --no-pager
bash "$HOME/gntech-ready-probe.sh"
```

Record the boot ID, unit result, and probe result together. For applications accessed through a proxy or tunnel, also test from the intended client network. A local success covers the local path only.

Avoid adding a fixed startup sleep as the first response to a failure. Inspect missing mounts, credentials, permissions, dependencies, and the application log. Use `network-online.target` only for workloads that need its boot-time synchronization and the appropriate wait-online implementation. It does not monitor ongoing connectivity or prove that a remote database is accepting requests.

For persistent previous-boot evidence, use the [journal storage and retention guide](/posts/2026-11-07-systemd-journal-persistence-retention/).

## 6. Remove the lab

After saving the results, remove only the resources created here.

```bash
sudo systemctl disable --now gntech-ready-lab.service
sudo rm -- /etc/systemd/system/gntech-ready-lab.service
sudo systemctl daemon-reload
sudo rm -f -- /var/lib/gntech-ready-lab/ready.txt \
  /var/lib/gntech-ready-lab/ready.disabled
sudo rmdir -- /var/lib/gntech-ready-lab
rm -- "$HOME/gntech-ready-probe.sh"
```

The next maintenance report should carry three separate observations for each critical application. Record boot enablement, current unit state, and the client-visible readiness result, with the time each was checked.

## Official references

- [systemd service types and restart behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemctl state and enablement commands](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html)
- [systemd network target semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.special.html)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)
