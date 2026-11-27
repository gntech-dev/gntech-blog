---
title: "Test Alertmanager Notification Templates Before Rollout"
description: "Render Alertmanager templates against explicit JSON fixtures and catch missing per-alert summaries before changing a notification receiver."
date: 2026-11-27T05:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, monitoring, testing, homelab]
keywords: [amtool template render, Alertmanager notification templates, CommonAnnotations, notification fixture testing]
summary: "An offline amtool lab with four notification fixtures, exact output checks, and two intentional template regressions."
cover:
  image: "/images/posts/alertmanager-template-fixtures/featured.webp"
  alt: "A brass magnifying glass over notification cards beside a small home server and laptop on a warmly lit desk."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

A notification can arrive successfully and still leave the on-call person guessing. A group title may say **FIRING**, while one worker has already recovered. A summary that looked fine with one alert can disappear when a second alert joins the group.

This companion to [Infrastructure Series Part 11 — Monitoring and Observability](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) tests the message before changing a receiver. We render a named text template with `amtool`, compare the complete output against reviewed expectations, and deliberately introduce two defects to prove that the checks detect them.

## Verification status and boundaries

| Area | Evidence and limits |
|---|---|
| Preparation | Official template documentation and the pinned CLI/data implementation reviewed November 27, 2026. |
| Executed locally | Checksum-verified amtool 0.28.1 rendered all four fixtures with exact expected output. A shared-summary regression failed the output comparison; an unsupported field failed template execution. |
| Version assumption | 0.28.1 is a historical, isolated lab baseline, not a recommendation for a current production release. Repeat the checks with the amtool version matching your deployed Alertmanager and its supported fields/functions. |
| Not exercised | No Alertmanager server, Prometheus rule evaluation, reload, credentials, external service, or live notification delivery. Text rendering does not verify a provider's Markdown, length limits, HTML, or transport. |

## 1. Understand the data you are testing

Alertmanager's [template reference](https://prometheus.io/docs/alerting/latest/notifications/) distinguishes group data from each alert. The fixture must represent the **notification data object**, not the array you would submit to `/api/v2/alerts`.

| Template value | Meaning in this lab | Why it matters |
|---|---|---|
| `.Status` | `firing` when at least one group member is firing | A mixed group can contain recovered members. |
| `.Alerts` | All members supplied in this notification fixture | Print each member's own state and summary. |
| `.Alerts.Firing` / `.Alerts.Resolved` | Filtered members by state | Count both so the headline is honest. |
| `.CommonAnnotations` | Annotation values shared by every member | Different summaries are absent here. |
| `.Annotations` inside `range .Alerts` | One member's annotations | This is where its individual summary belongs. |

The renderer reads the JSON you supply. It does **not** recalculate group status or common annotations as a running Alertmanager would. Our fixture generator below explicitly sets those fields and computes the shared values. Its fixed timestamps describe synthetic cases; the renderer is not waiting for those times or evaluating an alert lifecycle.

## 2. Prepare a disposable workspace

Use Linux amd64 with Bash, Python 3, `curl`, `tar`, `awk`, and `sha256sum`. No root access or account credentials are needed. Run the commands in the same Bash session, in a new directory. Download the archive and checksum file from the official release, verify the exact archive entry, and only then extract the executable. A checksum obtained from the same release detects byte corruption; it is not an independent publisher signature.

```bash
set -euo pipefail
lab_dir="$(mktemp -d -t gntech-template-XXXXXX)"
cd "$lab_dir"
umask 077
version=0.28.1
archive="alertmanager-${version}.linux-amd64.tar.gz"
release="https://github.com/prometheus/alertmanager/releases/download/v${version}"
curl --fail --location --retry 3 "$release/$archive" -o "$archive"
curl --fail --location --retry 3 "$release/sha256sums.txt" -o sha256sums.txt
awk -v file="$archive" '$2 == file {print; found=1} END {if (!found) exit 1}'   sha256sums.txt > selected-checksum.txt
sha256sum --check selected-checksum.txt
tar -xzf "$archive" --strip-components=1   "alertmanager-${version}.linux-amd64/amtool"
./amtool --version
./amtool template render --help
```

Keep the version output and checksum result with your review evidence. If adapting to another release or architecture, select its archive and inspect that binary's help rather than assuming identical options.

## 3. Write a readable text template

This template includes group counts, then one line per alert and an optional runbook line. `with` provides a visible fallback for an absent or empty summary. A missing runbook simply omits its line. This fallback keeps the message understandable; it does not excuse missing required annotations in your own alert rules.

The `range` changes the current context (`.`) to one alert. Go template `$` retains the root context. Confusing those contexts is the regression we will test later.

```bash
cat > notification.tmpl <<'TMPL'
{{ define "gntech.text" -}}
{{ .Status | toUpper }} | {{ .Receiver }} | firing={{ len .Alerts.Firing }} resolved={{ len .Alerts.Resolved }}
{{ range .Alerts -}}
{{ .Status | toUpper }} {{ .Labels.instance }}: {{ with .Annotations.summary }}{{ . }}{{ else }}(summary missing){{ end }}
{{ with .Annotations.runbook_url }}runbook: {{ . }}
{{ end -}}
{{ end -}}
{{ end }}
TMPL
```

## 4. Create four explicit fixtures

The generator writes JSON and separate expected text files. Expectations are literal strings for a reviewer to read; they are not generated by the template under test. The example hostnames use `example.com`, and the worker names and fingerprints are synthetic identifiers.

| Fixture | Input | Expected behavior |
|---|---|---|
| `single` | One firing worker with summary and runbook | Both annotation values appear. |
| `mixed` | One firing and one resolved worker, with different summaries | Group remains FIRING; each member keeps its own status and summary. |
| `missing` | One firing worker without annotations | Explicit summary fallback; no empty runbook line. |
| `resolved` | Both workers resolved | RESOLVED headline with zero firing and two resolved members. |

```bash
cat > fixtures.py <<'PY'
import copy
import json
from pathlib import Path

out = Path("fixtures")
out.mkdir(exist_ok=True)

def alert(instance, status, annotations):
    return {
        "status": status,
        "labels": {"alertname": "WorkerUnavailable", "instance": instance},
        "annotations": annotations,
        "startsAt": "2026-01-01T00:00:00Z",
        "endsAt": ("2026-01-01T00:05:00Z" if status == "resolved"
                   else "2026-01-01T01:00:00Z"),
        "generatorURL": "https://prometheus.example.com/graph",
        "fingerprint": instance,
    }

a = alert("worker-a", "firing", {
    "summary": "Worker A stopped", "runbook_url": "https://example.com/runbooks/worker"
})
b = alert("worker-b", "resolved", {"summary": "Worker B recovered"})
resolved_a = copy.deepcopy(a)
resolved_a.update(status="resolved", endsAt="2026-01-01T00:05:00Z")
missing = alert("worker-c", "firing", {})

cases = {
    "single": ([a], [
        "FIRING | fixture-team | firing=1 resolved=0",
        "FIRING worker-a: Worker A stopped",
        "runbook: https://example.com/runbooks/worker",
    ]),
    "mixed": ([a, b], [
        "FIRING | fixture-team | firing=1 resolved=1",
        "FIRING worker-a: Worker A stopped",
        "runbook: https://example.com/runbooks/worker",
        "RESOLVED worker-b: Worker B recovered",
    ]),
    "missing": ([missing], [
        "FIRING | fixture-team | firing=1 resolved=0",
        "FIRING worker-c: (summary missing)",
    ]),
    "resolved": ([resolved_a, b], [
        "RESOLVED | fixture-team | firing=0 resolved=2",
        "RESOLVED worker-a: Worker A stopped",
        "runbook: https://example.com/runbooks/worker",
        "RESOLVED worker-b: Worker B recovered",
    ]),
}

for name, (alerts, expected) in cases.items():
    # Build a notification Data object, not an array for POST /api/v2/alerts.
    def common(field):
        return {k: v for k, v in alerts[0][field].items()
                if all(item[field].get(k) == v for item in alerts)}
    data = {
        "receiver": "fixture-team",
        "status": "firing" if any(x["status"] == "firing" for x in alerts) else "resolved",
        "alerts": alerts,
        "groupLabels": {"alertname": "WorkerUnavailable"},
        "commonLabels": common("labels"),
        "commonAnnotations": common("annotations"),
        "externalURL": "https://alertmanager.example.com",
    }
    (out / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    (out / f"{name}.expected").write_text("\n".join(expected) + "\n")
print("Wrote four notification fixtures and their expected output")
PY
```

```bash
python3 fixtures.py
python3 -m json.tool fixtures/mixed.json
```

In `mixed.json`, `commonAnnotations` is empty even though both alerts have a summary. Their summary **values differ**, so neither summary is common to the whole notification.

## 5. Render and compare the whole message

Use an explicit `--template.data` for every case. Omitting it uses amtool's built-in demonstration data, which does not test your alert contract. `--template.type=text` makes the intended rendering mode explicit. An email HTML field needs separate HTML-mode checks and browser/email-client review; a passing text comparison does not establish correct HTML escaping.

```bash
cat > verify.py <<'PY'
import difflib
from pathlib import Path
import subprocess
import sys

template = sys.argv[1] if len(sys.argv) > 1 else "notification.tmpl"
results = Path("results")
results.mkdir(exist_ok=True)
for name in ("single", "mixed", "missing", "resolved"):
    run = subprocess.run([
        "./amtool", "template", "render",
        f"--template.glob={template}",
        '--template.text={{ template "gntech.text" . }}',
        "--template.type=text", f"--template.data=fixtures/{name}.json",
    ], text=True, capture_output=True, check=True)
    (results / f"{name}.txt").write_text(run.stdout)
    expected = Path(f"fixtures/{name}.expected").read_text()
    if run.stdout != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(True), run.stdout.splitlines(True),
            fromfile="expected", tofile="rendered"))
        raise SystemExit(f"FAIL {name}: rendered text differs\n{diff}")
    print(f"PASS {name}")
PY
```

```bash
python3 verify.py
cat results/mixed.txt
```

A successful run reports `PASS single`, `PASS mixed`, `PASS missing`, and `PASS resolved`. The mixed message is exactly:

```text
FIRING | fixture-team | firing=1 resolved=1
FIRING worker-a: Worker A stopped
runbook: https://example.com/runbooks/worker
RESOLVED worker-b: Worker B recovered
```

The verifier saves each render before comparing it. It fails on command errors or any output difference, including a missing line or unintended blank line. Alert order here is fixture order; this example does not promise sorting for real notifications. Keep the expected files under review when intentionally changing wording, rather than automatically replacing them with whatever the renderer emits.

## 6. Prove the guard catches bad changes

The first mutation incorrectly reads every member's summary from the root `.CommonAnnotations`. It still renders successfully, and the single-alert case still passes. The mixed case must fail because it loses both individual summaries.

The second mutation misspells a struct field as `.Receivr`. That is a rendering error, a different failure from valid text with incorrect content. The following block requires both failures and then verifies the unchanged original template again. It writes only lab copies.

```bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
source = Path("notification.tmpl").read_text()
Path("common-summary.tmpl").write_text(source.replace(
    ".Annotations.summary", "$.CommonAnnotations.summary"))
Path("bad-field.tmpl").write_text(source.replace(".Receiver", ".Receivr"))
PY
if python3 verify.py common-summary.tmpl > common-summary.log 2>&1; then
  echo 'FAIL: the shared-summary regression escaped detection' >&2
  exit 1
fi
grep -F 'FAIL mixed: rendered text differs' common-summary.log
if ./amtool template render --template.glob=bad-field.tmpl \
  --template.text='{{ template "gntech.text" . }}' \
  --template.type=text --template.data=fixtures/single.json \
  > bad-field.txt 2> bad-field.log; then
  echo 'FAIL: unsupported field rendered successfully' >&2
  exit 1
fi
grep -F "can't evaluate field Receivr" bad-field.log
python3 verify.py
```

Inspect `common-summary.log` to see the two summaries replaced with `(summary missing)`. Inspect `bad-field.log` for the field error. The last four PASS lines show the original template is intact. Negative runs can overwrite some files under `results`; the final successful run restores the original evidence there.

## 7. Apply the result through your normal review process

This lab leaves every running service untouched. To adapt it:

1. Copy the actual named template and its invocation into a separate review workspace. Test every entry point used by the intended integration, including subject/title fields where applicable.
2. Build sanitized fixtures from your real label/annotation contract. Include heterogeneous groups, missing optional fields, all-resolved notifications, long values, and provider-specific markup cases. Treat captured payloads as potentially sensitive; remove secrets and private identifiers before committing them.
3. Render with the matching release and the correct text or HTML mode. Keep both successful output and intentional failure evidence with the change.
4. Wire the named definition through the integration's documented templated field and the configuration's `templates` paths. See the [official examples](https://prometheus.io/docs/alerting/latest/notification_examples/). This article does not install a receiver or imply that arbitrary integration fields support templating.
5. Validate the complete candidate configuration in the target environment, preserve the previous configuration **and template files**, and follow your controlled reload procedure. A syntax check alone cannot prove the resulting message is useful.
6. Send a synthetic firing and resolved notification to an isolated destination. Check the received message, escaping, length, links, and delivery before production cutover. Revert both configuration references and template files through the same reviewed process if acceptance fails.

The offline check proves that selected fixture inputs produce the reviewed text. It does not prove that routing will select the receiver, that suppression allows delivery, or that an external provider accepts the result.

## Troubleshooting and cleanup

| Symptom | Check |
|---|---|
| Single case passes, mixed case loses summaries | Read each alert's annotations inside the loop; inspect the fixture's common annotation map. |
| `can't evaluate field` | Check spelling and whether the current context is the group, one alert, or a string inside `with`. |
| CLI succeeds but comparison fails | Read the unified diff and saved render; do not accept a changed baseline without reviewing its meaning. |
| Fixture results disagree with live output | Check release, actual notification data, named template invocation, integration rendering mode, and destination formatting. |

Keep the lab directory if you need its evidence. Otherwise leave it and delete the exact directory printed by the setup step:

```bash
printf 'Lab directory: %s\n' "$lab_dir"
cd ..
# Review the printed path before running this command.
rm -r -- "$lab_dir"
```

## Official references

Reviewed November 27, 2026. Current documentation can describe features newer than this historical lab baseline; pinned implementation links establish the behavior used here.

- [Notification data, alert fields, filtering, and rendering modes](https://prometheus.io/docs/alerting/latest/notifications/).
- [Official named-template and integration examples](https://prometheus.io/docs/alerting/latest/notification_examples/).
- [amtool 0.28.1 renderer: explicit JSON data and text/HTML selection](https://github.com/prometheus/alertmanager/blob/v0.28.1/cli/template_render.go).
- [Alertmanager 0.28.1 template Data schema and common-value construction](https://github.com/prometheus/alertmanager/blob/v0.28.1/template/template.go).
- [Official 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1).

Next planned topic: test HTML notification escaping with hostile annotation values before enabling a custom email template.
