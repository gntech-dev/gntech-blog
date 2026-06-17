---
title: "Docker Container Graceful Shutdown — Signals, Stop Grace Period, and Trap Handlers"
description: "Configure proper graceful shutdown for Docker containers in your homelab. Covers stop signals, stop_grace_period, init process management with tini/dumb-init, and SIGTERM trap handlers to prevent data corruption during restarts."
date: 2026-06-12T10:30:00-04:00
tags:
  - docker
  - docker-compose
  - containers
  - homelab
  - devops
keywords:
  - Docker container graceful shutdown stop signal SIGTERM trap handler
  - Docker Compose stop_grace_period configuration homelab
  - Docker StopSignal image directive container stop behavior
  - Docker container init process PID1 zombie reaping tini dumb-init
  - Docker compose restart policy stop timeout data corruption prevention
  - Docker container shutdown signal handling best practices production
  - docker-compose.yml graceful shutdown configuration examples
summary: "Configure proper graceful shutdown for Docker containers in your homelab. Covers stop signals, stop_grace_period, init process management with tini/dumb-init, and SIGTERM trap handlers to prevent data corruption during restarts."
canonical: "https://blog.gntech.me/posts/docker-container-graceful-shutdown-signals/"
---

You run `docker-compose down` and wait. The terminal hangs for ten seconds, then spits you back to your prompt. Next time you start the stack, your database logs show "database system was not properly shut down." Your application containers have stale PID files. An incomplete write has corrupted a config file you need to regenerate from scratch.

This is the default Docker shutdown behavior at work: SIGTERM, a ten-second grace period, then SIGKILL. For many containers that's fine. For databases, caches, and stateful services, those ten seconds are a roll of the dice and you will lose.

This guide covers how Docker container signals actually work, how to configure `stop_grace_period` and `StopSignal` properly, why PID1 handling matters, and how to implement SIGTERM trap handlers in your custom entrypoints. Every config and command here is copy-paste ready for your homelab.

## How Docker Container Stop Signals Actually Work

When you run `docker stop <container>`, Docker sends the SIGTERM signal (15) to PID1 inside the container. The kernel delivers the signal to the process running as PID1, which is the entrypoint or CMD of your image. Docker then waits for the `stop_grace_period` — defaulting to 10 seconds. If the container has not exited by then, Docker sends SIGKILL (signal 9), which the kernel handles directly and terminates the process immediately with no cleanup opportunity.

The full flow:

1. `docker stop` → SIGTERM to PID1
2. Container process decides whether to handle or ignore
3. If still running after grace period → SIGKILL (uncatchable)
4. Container exits with code 137 (128 + 9 = SIGKILL) or 143 (128 + 15 = SIGTERM)

You can observe this directly:

```bash
docker run -d --name test-stop alpine sleep 300
time docker stop test-stop
```

The `time` output shows how long the stop actually took. If it's close to 10 seconds, your container was killed, not gracefully stopped. Check the exit code:

```bash
docker inspect test-stop --format '{{.State.ExitCode}}'
# 137 → killed by SIGKILL
# 143 → received SIGTERM and exited on its own
```

The same signal flow applies to `docker-compose down`, `docker compose restart`, and `docker service update` in Swarm mode. Every one of these operations follows the signal → wait → kill pattern.

## Configuring StopSignal and stop_grace_period in Docker Compose

The two essential settings for controlling shutdown behavior are `stop_signal` and `stop_grace_period` in your compose file, and `STOPSIGNAL` in your Dockerfile.

### Docker Compose stop_grace_period

Set a per-service grace period that matches your application's shutdown requirements:

```yaml
services:
  postgres:
    image: postgres:17
    stop_grace_period: 120s
    stop_signal: SIGTERM

  redis:
    image: redis:7-alpine
    stop_grace_period: 30s

  nginx:
    image: nginx:alpine
    stop_signal: SIGQUIT
    stop_grace_period: 30s
```

PostgreSQL needs time to flush its WAL (write-ahead log), close active connections, and sync dirty buffers to disk. A 10-second default is dangerously short. Setting `stop_grace_period: 120s` gives Postgres room to shut down cleanly even under load.

Redis is fast but needs a few seconds to dump its RDB snapshot if persistence is enabled and `save` directives are configured. 30 seconds is safe.

Nginx can use `SIGQUIT` as the stop signal — this tells Nginx to finish serving all in-flight HTTP requests before exiting, unlike SIGTERM which drops them immediately.

### Docker StopSignal in Dockerfile

You can bake the signal into your image using the `STOPSIGNAL` instruction:

```dockerfile
FROM nginx:alpine
STOPSIGNAL SIGQUIT
```

This means any container launched from this image will receive SIGQUIT by default on `docker stop`, regardless of what the compose file says.

### Docker run equivalents

The same settings work on the command line:

```bash
docker run -d \
  --stop-signal SIGTERM \
  --stop-timeout 120 \
  --name postgres \
  postgres:17
```

`--stop-timeout` sets the grace period in seconds. `--stop-signal` sets the initial signal sent to PID1.

## The init Process Problem: PID1 and Zombie Reaping

There is a subtle but critical issue with how Linux process management works inside containers. In Linux, PID1 is special. It does not receive default signal handlers: if your PID1 process has not explicitly registered a handler for SIGTERM, the signal is silently ignored. This is kernel behavior, not Docker behavior.

What this means in practice: if your container's entrypoint is a shell script or a binary that does not explicitly trap SIGTERM, `docker stop` sends SIGTERM, the process ignores it, and the container keeps running until the 10-second timeout expires and Docker delivers SIGKILL. Your application never got a chance to shut down cleanly.

The second problem is zombie reaping. When a process inside the container forks children and those children exit, they become zombie processes until their parent calls `wait()`. If the parent dies without reaping them, they remain zombies. PID1 is responsible for reaping orphaned zombies. If your container's entrypoint does not implement this, zombie processes accumulate.

### The Simple Fix: docker --init

Docker provides a built-in init process based on [tini](https://github.com/krallin/tini) that handles both signal forwarding and zombie reaping:

```bash
docker run -d --init --name myapp myapp:latest
```

In Docker Compose:

```yaml
services:
  app:
    image: myapp:latest
    init: true
    stop_grace_period: 30s
```

Verify that init is enabled:

```bash
docker inspect app --format '{{.HostConfig.Init}}'
# true
```

The `--init` flag causes Docker to use its bundled `tini` as PID1. Tini spawns your application as a child, forwards signals to it, and reaps zombies. It is the single most impactful thing you can do for container signal handling.

### Manual Tini Integration in Dockerfile

If you want the init process baked into your image rather than relying on the `docker run --init` flag (useful for images you distribute), add tini directly:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y tini \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

### Dumb-init as an Alternative

[dumb-init](https://github.com/Yelp/dumb-init) is a similar tool with a slightly different approach. Unlike tini which uses `wait()` and signal forwarding, dumb-init runs as PID1 and creates a new process session for your app:

```dockerfile
FROM alpine:3.20

RUN apk add --no-cache dumb-init

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/usr/local/bin/myapp"]
```

Both tools solve the same problems. Tini is lighter and ships with Docker. Dumb-init provides a `--rewrite` feature for remapping signals. For most homelab use cases, `init: true` in your compose file is sufficient.

## Implementing SIGTERM Trap Handlers for Custom Container Entrypoints

When you build custom Docker images with shell-based entrypoints, you need explicit signal handling. A plain shell script started as PID1 in a container will ignore SIGTERM unless you trap it.

Here is a production-ready entrypoint script that handles the signal correctly:

```bash
#!/bin/sh
set -e

cleanup() {
    echo "Received SIGTERM, shutting down gracefully..."
    # Run any pre-stop hooks (e.g., drain connections, flush caches)
    if [ -f /usr/local/bin/pre-stop.sh ]; then
        /usr/local/bin/pre-stop.sh
    fi
    # Forward signal to main process
    kill -TERM "$child" 2>/dev/null
    # Wait for main process to finish cleanly
    wait "$child"
    echo "Shutdown complete."
    exit 0
}

trap cleanup TERM

# Start main application in background
/usr/local/bin/main-app &
child=$!

# Wait for child process
wait "$child"
```

Key points about this pattern:

- The main process runs in the background with `&` so the shell can receive signals
- `child=$!` captures its PID
- The `trap cleanup TERM` registers the handler
- The final `wait "$child"` blocks until the child exits, preserving the exit code
- The cleanup function forwards SIGTERM to the child and waits for it

A Dockerfile using this:

```dockerfile
FROM alpine:3.20

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY main-app /usr/local/bin/main-app

ENTRYPOINT ["/entrypoint.sh"]
```

### Custom Stop Signals for Advanced Use

Some applications use SIGUSR1 or SIGUSR2 for log rotation or configuration reload. If your application ties SIGTERM to log rotation rather than shutdown, you can change the stop signal:

```yaml
services:
  app:
    image: myapp:latest
    stop_signal: SIGUSR2
    stop_grace_period: 60s
```

The container receives SIGUSR2 instead of SIGTERM when `docker stop` is called. This is useful when your application uses SIGTERM for non-fatal actions and you need a different signal to trigger shutdown.

## Application-Specific Graceful Shutdown Patterns

Different applications need different shutdown strategies. Here are the patterns for the most common homelab services.

### PostgreSQL

PostgreSQL handles SIGTERM natively by entering "fast shutdown" mode. It disallows new connections, terminates existing connections, flushes the WAL to disk, and syncs data files. It just needs enough time.

```yaml
services:
  postgres:
    image: postgres:17
    stop_grace_period: 120s
    volumes:
      - pgdata:/var/lib/postgresql/data
```

When Postgres shuts down cleanly, you see these log entries:

```
LOG:  received fast shutdown request
LOG:  aborting any active transactions
LOG:  database system is shut down
```

If you see "database system was not properly shut down" on the next start, your grace period is too short.

### Nginx

Nginx responds to two signals differently:

- **SIGTERM**: Shuts down immediately, dropping all active connections
- **SIGQUIT**: Gracefully shuts down, finishing in-flight requests before exiting

For production services, always use SIGQUIT:

```yaml
services:
  nginx:
    image: nginx:alpine
    stop_signal: SIGQUIT
    stop_grace_period: 30s
```

You can verify in the logs that Nginx completed its graceful shutdown:

```
2026/06/12 10:30:00 [notice] 1#1: signal 3 (SIGQUIT) received, shutting down
2026/06/12 10:30:05 [notice] 21#21: gracefully shutting down
2026/06/12 10:30:05 [notice] 21#21: exiting
```

### Node.js Applications

Node.js does not handle SIGTERM by default. Your application code must register a handler:

```javascript
const server = require('http').createServer((req, res) => {
  res.end('ok');
});

function gracefulShutdown() {
  console.log('Received SIGTERM, shutting down gracefully...');
  server.close(() => {
    console.log('HTTP server closed');
    // Close database connections, flush logs, etc.
    process.exit(0);
  });
  // Force shutdown after 30 seconds
  setTimeout(() => {
    console.error('Forced shutdown after timeout');
    process.exit(1);
  }, 30000);
}

process.on('SIGTERM', gracefulShutdown);

server.listen(3000, () => console.log('Server listening on port 3000'));
```

Combine this with `init: true` in your compose file:

```yaml
services:
  node-app:
    build: .
    init: true
    stop_grace_period: 60s
```

### Python Applications

Python applications need explicit signal registration as well:

```python
import signal
import sys
import time

running = True

def handle_sigterm(signum, frame):
    global running
    print("Received SIGTERM, shutting down gracefully...")
    running = False

signal.signal(signal.SIGTERM, handle_sigterm)

try:
    while running:
        # Main application loop
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    print("Cleaning up resources...")
    # Close database connections, flush buffers, write state files
    sys.exit(0)
```

## Docker Compose Restart Policy and Shutdown Interaction

The `restart` policy in Docker Compose interacts with shutdown signals in a way that matters during updates and maintenance.

When you run `docker compose up -d` after changing a service definition, Docker Compose stops the old container (using the signal flow above) and starts the new one. If the old container exits with code 137 (SIGKILL), the restart policy does not trigger because Docker distinguishes between manual stops and crashed exits. A real crash — where the process exits unexpectedly — would trigger the restart policy, but a `docker stop` followed by SIGKILL is treated as intentional.

```yaml
services:
  app:
    image: myapp:latest
    init: true
    stop_grace_period: 60s
    stop_signal: SIGTERM
    healthcheck:
      test: ["CMD", "wget", "-q", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
```

The `restart: unless-stopped` policy ensures the container starts on boot and after crashes, while the `stop_grace_period` and `init: true` ensure that manual restarts do not cause data loss. The healthcheck ensures the new container is actually serving traffic before Compose considers the update complete when using `--wait`.

To update a stack safely:

```bash
docker compose pull
docker compose up -d --wait --remove-orphans
```

The `--wait` flag tells Compose to wait until all services pass their health checks before returning. Combined with proper `stop_grace_period` values, this gives you zero-downtime updates for most services.

## Monitoring and Troubleshooting Shutdown Issues

When containers are not shutting down gracefully, the evidence is in the exit codes and logs.

### Check Exit Codes

Exit code 137 means the container was killed by SIGKILL. Exit code 143 means it received SIGTERM and exited on its own.

```bash
docker ps -a --filter "status=exited" \
  --format "table {{.Names}}\t{{.ExitCode}}\t{{.Status}}"
```

List only containers killed by SIGKILL:

```bash
docker ps -a --filter "status=exited" \
  --format "{{.Names}}" \
  | xargs -I {} sh -c ' \
    code=$(docker inspect {} --format "{{.State.ExitCode}}"); \
    [ "$code" = "137" ] && echo "{}: KILLED (exit $code)"'
```

### Watch Docker Events in Real Time

```bash
docker events --filter 'event=die' --filter 'event=kill'
```

This shows each container die event with the exit code. When you see exit code 137 regularly, that service needs a longer `stop_grace_period` or proper signal handling.

### Interpret Log Output

Check container logs for shutdown-related messages:

```bash
docker logs postgres | grep -i "shutdown"
docker logs nginx | grep -i "signal"
```

If Nginx logs show "signal 3 (SIGQUIT)" the graceful signal is working. If Postgres logs show no shutdown messages at all, the container was killed before Postgres could write its shutdown entry.

### Increase Grace Periods Conservatively

Start with these values and adjust based on observation:

| Service    | stop_grace_period | Notes                                    |
|------------|-------------------|------------------------------------------|
| PostgreSQL | 120s              | Needs time to flush WAL and sync data    |
| MariaDB    | 120s              | Same as Postgres for InnoDB flush        |
| Redis      | 30s               | Quick if RDB persistence is minimal      |
| Nginx      | 30s               | SIGQUIT drains connections in seconds    |
| Node.js    | 60s               | Depends on in-flight request volume      |
| Python     | 30s               | Usually fast unless long-running tasks   |

## Summary

Docker container graceful shutdown follows a simple flow: SIGTERM, wait, then SIGKILL. The defaults work for stateless services but cause data corruption in stateful ones. Fix it in three steps:

1. **Set `stop_grace_period`** in your docker-compose.yml — 120s for databases, 30-60s for application servers
2. **Enable `init: true`** — Docker's built-in tini handles signal forwarding and zombie reaping
3. **Use the right signal** — SIGQUIT for Nginx, SIGTERM for most other services; implement trap handlers in custom entrypoints

Check your exit codes. If any container exits with code 137, your grace period is too short or your signal handling is broken. Fix it before the next `docker-compose down` saves your data, not destroys it.
