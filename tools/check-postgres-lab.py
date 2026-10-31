#!/usr/bin/env python3
"""Run the backup article's Bash examples in a disposable Compose project."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

ARTICLE = Path(__file__).resolve().parents[1] / "content/posts/2026-06-01-docker-database-backup-automation-pgdump-cron.md"


def blocks(text):
    examples = re.findall(r"^```bash\n(.*?)^```", text, re.M | re.S)
    if len(examples) != 6:
        raise ValueError("Expected six Bash examples; review the lab harness after article edits")
    return examples


def main():
    examples = blocks(ARTICLE.read_text())
    env = os.environ.copy()
    # Never inherit a production Compose project or alternative compose file.
    for key in list(env):
        if key.startswith("COMPOSE_"):
            del env[key]
    env["COMPOSE_PROJECT_NAME"] = "gntech-pg-test-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="gntech-pg-test-") as directory:
        work = Path(directory)

        def run(script, *, input=None, check=True):
            return subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=work, env=env, input=input, text=True, check=check, timeout=240,
            )

        try:
            run("docker version; docker compose version")
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

            run("docker compose stop source")
            if run("./backup.sh", check=False).returncode == 0:
                raise AssertionError("Backup unexpectedly succeeded with source stopped")
            if list((work / "backups").glob("*.partial")):
                raise AssertionError("Failed backup left a partial file")
            if list((work / "backups").glob("*.dump")) != archives or archive.read_bytes() != before:
                raise AssertionError("Failed backup changed published archives")
            print("PASS: failed dump publishes nothing and preserves prior archive", flush=True)
        finally:
            if (work / "compose.yaml").exists():
                run("docker compose logs --no-color --tail 60", check=False)
                # Only our randomly named, disposable project's volumes are removed.
                run("docker compose down --volumes --remove-orphans")


if __name__ == "__main__":
    main()
