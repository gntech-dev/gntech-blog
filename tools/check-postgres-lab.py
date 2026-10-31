#!/usr/bin/env python3
"""Run the backup article's Bash examples in a disposable Compose project."""
import os
import json
import fcntl
import time
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

ARTICLE = Path(__file__).resolve().parents[1] / "content/posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md"


def blocks(text):
    examples = re.findall(r"^```bash\n(.*?)^```", text, re.M | re.S)
    if len(examples) != 12:
        raise ValueError("Expected twelve Bash examples; review the lab harness after article edits")
    return examples


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo on a disposable systemd/Docker host")
    examples = blocks(ARTICLE.read_text())
    env = os.environ.copy()
    # Never inherit a production Compose project or alternative compose file.
    for key in list(env):
        if key.startswith("COMPOSE_"):
            del env[key]
    env["COMPOSE_PROJECT_NAME"] = "gntech-pg-test-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="gntech-pg-test-") as directory:
        work = Path(directory)

        def run(script, *, input=None, check=True, capture=False):
            return subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=work, env=env, input=input, text=True, check=check, capture_output=capture, timeout=240,
            )

        unit = env["COMPOSE_PROJECT_NAME"] + "-backup"

        def service_result(expected):
            result = subprocess.check_output(
                ["systemctl", "show", unit + ".service", "-p", "Result", "--value"], text=True
            ).strip()
            status = subprocess.check_output(
                ["systemctl", "show", unit + ".service", "-p", "ExecMainStatus", "--value"], text=True
            ).strip()
            if result != expected or (status == "0") != (expected == "success"):
                raise AssertionError(f"Unexpected service result: {result}, status {status}")

        try:
            run("docker version; docker compose version; systemctl --version")
            # Keep the guide's setup intact, placing it in our managed directory.
            setup = examples[0].replace(
                "db_lab_dir=$(mktemp -d -t postgres-backup-lab.XXXXXX)",
                'db_lab_dir="$PWD"',
            )
            if setup == examples[0]:
                raise ValueError("Article setup changed; review isolation before running")
            run(setup)
            run("docker image inspect postgres:16-alpine --format '{{json .RepoDigests}}'")
            run("docker compose exec -T source postgres --version")
            run(examples[1])
            run(examples[2])
            archives = list((work / "backups").glob("*.dump"))
            if len(archives) != 1:
                raise AssertionError("Expected exactly one published archive")
            archive = archives[0]
            if archive.stat().st_mode & 0o077:
                raise AssertionError("Archive permissions allow group/other access")
            before = archive.read_bytes()
            run(examples[3], input=str(archive.relative_to(work)) + "\n")
            run(examples[4])
            print("PASS: article dump, isolated restore, and marker assertion", flush=True)

            # Repeat restore must fail rather than silently accepting duplicate data.
            if run(examples[3], input=str(archive.relative_to(work)) + "\n", check=False).returncode == 0:
                raise AssertionError("Repeated restore unexpectedly succeeded")
            print("PASS: restore errors propagate", flush=True)

            # Execute the article's actual unit-generation block under a unique name.
            run(examples[5].replace("gntech-postgres-backup", unit))
            run("systemctl start " + unit + ".service")
            service_result("success")
            if len(list((work / "backups").glob("*.dump"))) != 2:
                raise AssertionError("Manual service did not publish a dump")

            # Force a near-term timer event instead of waiting until 02:00.
            override = Path("/etc/systemd/system") / (unit + ".timer.d")
            override.mkdir()
            (override / "test.conf").write_text(
                "[Timer]\nOnCalendar=\nOnActiveSec=2s\nRandomizedDelaySec=0\nAccuracySec=1us\n"
            )
            run("systemctl daemon-reload; systemctl start " + unit + ".timer")
            deadline = time.monotonic() + 45
            while len(list((work / "backups").glob("*.dump"))) < 3:
                if time.monotonic() > deadline:
                    raise AssertionError("Timer did not publish an archive within 45 seconds")
                time.sleep(0.25)
            # Wait for systemd to observe the oneshot's successful completion.
            while subprocess.check_output(
                ["systemctl", "show", unit + ".service", "-p", "ActiveState", "--value"], text=True
            ).strip() == "activating":
                if time.monotonic() > deadline:
                    raise AssertionError("Timer service failed to complete")
                time.sleep(0.1)
            run("systemctl stop " + unit + ".timer")
            service_result("success")
            print("PASS: real systemd service and accelerated timer publish archives", flush=True)

            with (work / "backup.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if run("systemctl start " + unit + ".service", check=False).returncode == 0:
                    raise AssertionError("Service ignored backup lock contention")
                service_result("exit-code")
            run("systemctl reset-failed " + unit + ".service")
            archives = list((work / "backups").glob("*.dump"))
            published = {a.name: a.read_bytes() for a in archives}
            run("docker compose stop source")
            if run("systemctl start " + unit + ".service", check=False).returncode == 0:
                raise AssertionError("Scheduled service ignored stopped source")
            service_result("exit-code")
            journal = subprocess.check_output(
                ["journalctl", "-u", unit + ".service", "--no-pager"], text=True
            )
            if "Backup already running" not in journal or 'service "source" is not running' not in journal:
                raise AssertionError("Expected failure details missing from journal")
            print("PASS: lock and source failures reach service status and journal", flush=True)
            if run("./backup.sh", check=False).returncode == 0:
                raise AssertionError("Backup unexpectedly succeeded with source stopped")
            if list((work / "backups").glob("*.partial")):
                raise AssertionError("Failed backup left a partial file")
            if list((work / "backups").glob("*.dump")) != archives or {a.name: a.read_bytes() for a in archives} != published:
                raise AssertionError("Failed backup changed published archives")
            print("PASS: failed dump publishes nothing and preserves prior archive", flush=True)
            # Rehearse recovery of the published SQL dumps from an encrypted copy.
            (work / "backups/ignored.partial").write_text("must never enter a snapshot")
            run(examples[8])
            chain = "docker compose -f compose.yaml -f compose.chain.yaml"
            run(chain + " run --rm --interactive=false archive version")
            run("docker image inspect restic/restic:0.19.1 --format '{{json .RepoDigests}}'")
            copied = json.loads(run(
                chain + " run --rm --interactive=false recover_archive snapshots --json",
                capture=True,
            ).stdout)
            if len(copied) != 1:
                raise AssertionError("Expected exactly one copied dump snapshot")
            run("docker compose stop restore_test")
            # Only the copied repository remains available to the recovery procedure.
            for name in ("backups", "chain-repository", "chain-password", "db-password"):
                (work / name).rename(work / (name + "-unavailable"))
            run(examples[9], input=copied[0]["id"] + "\n" + archive.name + "\n")
            run(examples[10])
            restored = work / "chain-restored/dumps"
            recovered = {a.name: a.read_bytes() for a in restored.glob("*.dump")}
            if recovered != published:
                raise AssertionError("Recovered dumps differ from published archives")
            if list(restored.glob("*.partial")):
                raise AssertionError("Restic included a partial dump")
            print("PASS: PostgreSQL dump -> encrypted repository copy -> fresh database recovery", flush=True)
            print("PASS: restored dump bytes match and partial files are excluded", flush=True)
        finally:
            run("systemctl stop " + unit + ".timer " + unit + ".service", check=False)
            run("systemctl reset-failed " + unit + ".service", check=False)
            root = Path("/etc/systemd/system")
            for suffix in (".service", ".timer"):
                (root / (unit + suffix)).unlink(missing_ok=True)
            override = root / (unit + ".timer.d")
            if override.exists():
                (override / "test.conf").unlink(missing_ok=True)
                override.rmdir()
            run("systemctl daemon-reload")
            if (work / "compose.yaml").exists():
                run("docker compose logs --no-color --tail 60", check=False)
                # Only our randomly named, disposable project's volumes are removed.
                if (work / "compose.chain.yaml").exists():
                    run("docker compose -f compose.yaml -f compose.chain.yaml down --volumes --remove-orphans")
                else:
                    run("docker compose down --volumes --remove-orphans")


if __name__ == "__main__":
    main()
