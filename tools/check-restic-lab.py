#!/usr/bin/env python3
"""Replay the Restic article and test recovery without the original repository."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

ARTICLE = Path(__file__).resolve().parents[1] / "content/posts/2026-05-19-restic-docker-backup-strategy.md"
IMAGE = "restic/restic:0.19.1"


def blocks(text):
    result = re.findall(r"^```bash\n(.*?)^```", text, re.M | re.S)
    if len(result) != 6:
        raise ValueError("Expected six Bash examples; review article changes")
    return result


def main():
    examples = blocks(ARTICLE.read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    env["COMPOSE_PROJECT_NAME"] = "gntech-restic-test-" + uuid.uuid4().hex[:12]
    env["RESTIC_IMAGE"] = IMAGE
    with tempfile.TemporaryDirectory(prefix="gntech-restic-test-") as directory:
        work = Path(directory)

        def run(script, *, input=None, check=True, capture=False):
            return subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=work, env=env, input=input, text=True,
                check=check, capture_output=capture, timeout=240,
            )

        compose = "docker compose -f compose.yaml -f compose.copy.yaml"
        try:
            run("docker version; docker compose version")
            setup = examples[0].replace(
                "restic_lab_dir=$(mktemp -d -t restic-file-lab.XXXXXX)",
                'restic_lab_dir="$PWD"',
            )
            if setup == examples[0]:
                raise ValueError("Article setup changed; review isolation")
            run(setup, input=IMAGE + "\n")
            run("docker image inspect " + IMAGE + " --format '{{json .RepoDigests}}'")
            expected = (work / "source/check.txt").read_bytes()
            run(examples[1])
            snapshots = json.loads(run("docker compose run --rm restic snapshots --json", capture=True).stdout)
            if len(snapshots) != 1:
                raise AssertionError("Expected one source snapshot")
            run(examples[2], input=snapshots[0]["id"] + "\n")
            run(examples[3])
            run(examples[4])
            copied = json.loads(run(compose + " run --rm recovery snapshots --json", capture=True).stdout)
            if len(copied) != 1:
                raise AssertionError("Expected one copied snapshot")
            failure = run(
                compose + " run --rm -e RESTIC_PASSWORD_FILE=/run/secrets/copy-password restic snapshots",
                check=False, capture=True,
            )
            if failure.returncode == 0:
                raise AssertionError("Original repository accepted destination password")
            if not any(message in failure.stderr.lower() for message in ("wrong password", "no key found")):
                raise AssertionError("Expected an authentication failure: " + failure.stderr)
            print("PASS: wrong-password access is rejected", flush=True)
            # Simulate original materials being unavailable before destination recovery.
            for name in ("source", "repository", "restic-password"):
                (work / name).rename(work / (name + "-unavailable"))
            run(examples[5], input=copied[0]["id"] + "\n")
            if (work / "recovered-copy/source/check.txt").read_bytes() != expected:
                raise AssertionError("Copied repository recovery differs from source")
            print("PASS: original restore, retention preview, copy, full data check, independent recovery", flush=True)
        finally:
            if (work / "compose.yaml").exists():
                run("docker compose down --remove-orphans", check=False)
            # Images may create root-owned repository files on the disposable runner.
            # TemporaryDirectory cannot remove those: container cleanup owns this path.
            if (work / "compose.copy.yaml").exists():
                run(compose + " run --rm --entrypoint /bin/sh recovery "
                    "-c 'rm -rf /repository/* /restore/*'", check=False)
            # Original repo was renamed; remove its contents via a narrow bind mount.
            for name in ("repository", "repository-unavailable", "restored"):
                path = work / name
                if path.exists():
                    run("docker run --rm --entrypoint /bin/sh "
                        "-v \"$PWD/" + name + ":/cleanup\" " + IMAGE +
                        " -c 'rm -rf /cleanup/*'", check=False)


if __name__ == "__main__":
    main()
