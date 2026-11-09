---
title: "Rotate NGINX Logs and Verify the Workers Reopened Them"
description: "Use an isolated NGINX and logrotate lab to show why a renamed log can keep growing and how to verify that requests reach the replacement file."
date: 2026-11-09T00:00:00-04:00
draft: false
ShowToc: true
tags: [linux, nginx, logging, operations, homelab]
keywords: [nginx logrotate, nginx reopen, USR1, log rotation verification]
summary: "Rotate a disposable access log, ask NGINX to reopen it, and trace a unique request into the new file."
cover:
  image: "/images/posts/nginx-log-reopen/featured.webp"
  alt: "Laptop with amber light traces in front of a cobalt-lit server rack."
  caption: "AI-generated editorial artwork."
  relative: false
---

Rotating a log changes the filenames on disk. The application must also switch where it writes. On Linux, a process with an open descriptor can keep writing to the same file after a rename. If that file is later removed while still open, its storage can remain allocated.

This reference lab targets Debian or Ubuntu with packaged NGINX, logrotate, Bash, curl, and GNU Coreutils on Linux. Run it as an ordinary user with those tools installed. It uses a unique temporary directory, a private PID file, and loopback port 18082. The existing NGINX service and system logrotate configuration are outside the lab.

| Stage | Current pathname | Where NGINX writes |
| --- | --- | --- |
| Before rotation | access.log | Original file |
| After rename and creation | access.log.1 and a new access.log | Original file until reopen |
| After successful reopen | access.log.1 and a new access.log | New access.log |

## 1. Start a disposable NGINX instance

Check that port 18082 is available before continuing. Keep the following commands in the same shell.

```bash
command -v nginx
command -v logrotate
ss -ltn 'sport = :18082'

lab="$(mktemp -d /tmp/gntech-logrotate.XXXXXX)"
mkdir "$lab/logs"
nginx_bin="$(command -v nginx)"

cat > "$lab/nginx.conf" <<'NGINX'
pid logs/nginx.pid;
error_log logs/error.log notice;
events {}
http {
    access_log logs/access.log;
    client_body_temp_path logs/client-body;
    proxy_temp_path logs/proxy;
    fastcgi_temp_path logs/fastcgi;
    uwsgi_temp_path logs/uwsgi;
    scgi_temp_path logs/scgi;
    server {
        listen 127.0.0.1:18082;
        location / {
            return 200 "log rotation lab\n";
        }
    }
}
NGINX

"$nginx_bin" -p "$lab/" -e "$lab/logs/error.log" -c nginx.conf -t &&
"$nginx_bin" -p "$lab/" -e "$lab/logs/error.log" -c nginx.conf
```

Stop if either NGINX command fails. With a successful start, confirm that an HTTP request appears in the initial access log.

```bash
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18082/before
grep -F -- 'GET /before ' "$lab/logs/access.log"
stat -c '%i %s %n' "$lab/logs/access.log"
```

## 2. Configure rotation with a reopen hook

NGINX documents `USR1` as its log-reopen signal. The `nginx -s reopen` command uses this behavior and reads the PID from the configuration supplied here. Use the exact same prefix and configuration as the lab start.

```bash
cat > "$lab/logrotate.conf" <<CONF
"$lab/logs/access.log" {
    size 1k
    rotate 2
    create 0640
    postrotate
        "$nginx_bin" -p "$lab/" -e "$lab/logs/error.log" -c nginx.conf -s reopen
    endscript
}
CONF

logrotate --debug --force --state "$lab/logrotate.state" "$lab/logrotate.conf"
```

Debug mode shows what the forced lab run would do without updating logs or state. Review the paths before performing the rotation. The lab has its own state file, so the command does not reuse the host scheduler's state.

```bash
logrotate --verbose --force --state "$lab/logrotate.state" "$lab/logrotate.conf"
stat -c '%i %s %n' "$lab/logs/access.log" "$lab/logs/access.log.1"
```

Expect two different inode numbers, with the original inode now at `access.log.1`. That confirms the rename and creation steps. Signal delivery and log routing still need their own check.

## 3. Verify where a fresh request was written

Signal handling can be asynchronous. Give the workers a bounded interval to reopen, then inspect both logs.

```bash
found=0
for attempt in {1..10}; do
    marker="/after-$attempt-$(date +%s%N)"
    curl --fail --silent --show-error --max-time 3 \
        "http://127.0.0.1:18082$marker" >/dev/null || break
    if grep -F -- "GET $marker " "$lab/logs/access.log"; then
        found=1
        break
    fi
    sleep 1
done
test "$found" -eq 1 &&
grep -F -- 'GET /before ' "$lab/logs/access.log.1"
```

The expected result is the fresh marker in the current log and the initial request in the archive. A request sent during the transition may still land in the archive. If new requests keep landing there, inspect the lab error log, the PID file, and permissions on the replacement file and its parent directory.

## 4. Adapt the approach to an existing service

Inspect the distribution's existing logrotate rule and service unit first. A packaged NGINX instance may already have a reopen hook. Add a second rule only for a distinct log path. Duplicate rules for the same path can break rotation.

Use the service's documented reopen method and a scoped process identity. Avoid broad signals such as killing or signaling every process with the same name. Match the replacement file's ownership and mode to the service. Test one rotation and a fresh client request before enabling compression or changing retention.

For an application without a reopen mechanism, logrotate's `copytruncate` copies and then truncates the original file. The same descriptor can continue to work, but writes between copy and truncate can be lost. Evaluate that tradeoff against the application's own logging options and evidence requirements.

If storage remains allocated after log deletion, use the [deleted-but-open-file guide](/posts/2026-11-08-linux-deleted-open-files-disk-space/). For systemd journal files, use [journald's own retention controls](/posts/2026-11-07-systemd-journal-persistence-retention/).

## 5. Stop and remove the lab

Send a graceful stop to the lab instance. Wait for the process to exit before removing its directory. Retain the logs until you have recorded the results.

```bash
"$nginx_bin" -p "$lab/" -e "$lab/logs/error.log" -c nginx.conf -s quit
```

Once the lab process has exited, confirm that `lab` still points to the directory created by this article before removing it. For a production rollback, restore the prior rotation rule and verify that a fresh request reaches the current log. Keep rotated files available for investigation.

## Official references

- [NGINX signal handling and log reopening](https://nginx.org/en/docs/control.html#logs)
- [Logrotate upstream manual](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in)
