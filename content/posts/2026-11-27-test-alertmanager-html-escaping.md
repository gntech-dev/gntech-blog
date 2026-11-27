---
title: "Test HTML Escaping in Alertmanager Email Templates"
description: "Render hostile annotation fixtures with amtool, inspect HTML structure and links, and catch unsafe safeHtml or text-mode changes before rollout."
date: 2026-11-27T17:00:00-04:00
draft: false
ShowToc: true
tags: [alertmanager, prometheus, monitoring, security, testing]
keywords: [Alertmanager HTML email template, amtool template render html, safeHtml, notification escaping]
summary: "An offline lab verifies literal annotation text, attribute boundaries, and filtered unsafe URLs in a custom HTML notification template."
cover:
  image: "/images/posts/alertmanager-html-escaping/featured.webp"
  alt: "A cream envelope inside an illuminated glass frame on a desk beside a home server and laptop, with abstract fragments outside the frame."
  caption: "AI-generated conceptual editorial artwork; not a deployment screenshot or technical diagram."
  relative: false
---

An alert summary is data, even when it contains angle brackets. If a service emits `<img ...>` in an error message, an email template should show those characters to the operator without turning them into an image element. A runbook URL containing a quote should also remain one attribute value.

This companion to [Infrastructure Series Part 11 — Monitoring and Observability](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) tests that boundary before enabling a custom email template. We render four synthetic notification fixtures in HTML mode, inspect the resulting elements and decoded text, and deliberately break the template to prove that the guard notices.

## Verification status

| Area | Evidence and limits |
|---|---|
| Preparation | Official Alertmanager and Go template documentation plus the pinned renderer implementation reviewed November 27, 2026. |
| Executed locally | Checksum-verified amtool 0.28.1 rendered four fixtures. HTML structure, literal text, and link expectations passed. Both the `safeHtml` mutation and the wrong rendering mode failed as intended. |
| Version assumption | 0.28.1 is a historical isolated lab baseline, not a current production recommendation. Repeat with the amtool release matching your deployed Alertmanager. |
| Not exercised | No Alertmanager server, reload, SMTP credentials, email delivery, browser execution, or email-client rendering. The Python parser checks these specific fixtures; it is not a general HTML sanitizer or complete browser parser. |

## 1. Separate template code from annotation data

Alertmanager uses Go templates, and its [notification reference](https://prometheus.io/docs/alerting/latest/notifications/) distinguishes fields evaluated as text from those evaluated as HTML. HTML mode applies context-sensitive escaping: a value in a paragraph needs different handling from a value in a URL attribute.

The template itself must be trusted. Go's [HTML template documentation](https://pkg.go.dev/html/template) assumes trusted template authors and untrusted data. Escaping does not make a malicious template safe.

| Input or operation | What this lab requires |
|---|---|
| Label inserted in a heading | Original characters survive as text; no new element appears. |
| Summary inserted in a paragraph | `<`, `>`, `&`, and quotes remain readable after entity decoding. |
| HTTPS URL with quotes | One `href` attribute; quotes cannot create an event handler. |
| `javascript:` URL | The pinned renderer substitutes `#ZgotmplZ`. |
| Annotation piped through `safeHtml` | Regression guard fails when annotation markup becomes an element. |

`safeHtml` marks content as trusted HTML. It does **not** sanitize it. Do not use it to make untrusted summaries look formatted. If a value contains markup that should be displayed literally, keep the ordinary template action and let HTML mode escape it.

URL escaping is also different from destination approval. An arbitrary HTTPS host can still be inappropriate or misleading. In a real alert contract, use curated runbook URLs or an explicit destination policy. The filtering test below does not establish a host allowlist.

## 2. Install the reproducible lab tool

Use Linux amd64, Bash, Python 3, `curl`, `tar`, `awk`, and `sha256sum`. Run the blocks in one Bash session. No root access or account credentials are needed. The commands create a new temporary directory and leave running services alone.

Download from the official release and verify the archive before extracting it. This checks byte integrity against the release checksum file; it is not an independent publisher signature.

```bash
set -euo pipefail
lab_dir="$(mktemp -d -t gntech-html-template-XXXXXX)"
cd "$lab_dir"
umask 077
version=0.28.1
archive="alertmanager-${version}.linux-amd64.tar.gz"
release="https://github.com/prometheus/alertmanager/releases/download/v${version}"
curl --fail --location --retry 3 "$release/$archive" -o "$archive"
curl --fail --location --retry 3 "$release/sha256sums.txt" -o sha256sums.txt
awk -v file="$archive" '$2 == file {print; found=1} END {if(!found)exit 1}' \
  sha256sums.txt > selected-checksum.txt
sha256sum --check selected-checksum.txt
tar -xzf "$archive" --strip-components=1 \
  "alertmanager-${version}.linux-amd64/amtool"
./amtool --version
./amtool template render --help
```

Record the version and checksum result. Use an approved current release for production; the fixed historical binary here only makes the offline behavior reproducible. New releases can change escaping details, so review any changed expectation instead of copying it blindly.

## 3. Write the HTML template

The structure is intentionally small: one heading and one section per alert. The data actions sit in text positions or a quoted `href`. There are no scripts, styles, external images, or trusted-HTML conversions.

```bash
cat > email.tmpl <<'TMPL'
{{ define "gntech.email" -}}
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Alert detail</title></head>
<body>
<h1>{{ .Status | toUpper }}</h1>
{{ range .Alerts }}
<section>
<h2>{{ .Labels.instance }}</h2>
<p>{{ .Annotations.summary }}</p>
{{ with .Annotations.runbook_url }}<a href="{{ . }}">Open runbook</a>{{ end }}
</section>
{{ end }}
</body>
</html>
{{ end }}
TMPL
```

The definition is named `gntech.email`; the renderer must invoke that exact name with the notification object as its context. This is an HTML body example, not a subject-line template or a complete mail configuration.

## 4. Create the hostile fixtures

These are notification `Data` objects, not the array accepted by `/api/v2/alerts`. Each contains one firing alert, so its common labels and annotations equal that alert's values. The fixed timestamps and fingerprints are synthetic; this command does not evaluate an alert lifecycle.

| Fixture | What it probes |
|---|---|
| `ordinary` | Comparisons, ampersands, quotes, Unicode, and a query-string separator. |
| `markup` | A label containing `<b>` and a summary containing an image/event-handler string. |
| `unsafe-url` | A JavaScript-scheme runbook value. |
| `quoted-url` | A quote and event-handler-shaped string inside an HTTPS query value. |

The hostile strings are inert test data here. Do not open outputs from intentionally unsafe mutations in a browser or mail client.

```bash
cat > fixtures.py <<'PY'
import json
from pathlib import Path

out = Path("fixtures")
out.mkdir(exist_ok=True)
cases = {
    "ordinary": ("worker-a", 'Load < 5 & queue > 0; café "ready"',
                 "https://example.com/runbooks/worker?team=ops&view=full"),
    "markup": ("worker-<b>east</b>", '<img src=x onerror="alert(1)">',
               "https://example.com/runbooks/worker"),
    "unsafe-url": ("worker-b", "Runbook came from an untrusted label",
                   "javascript:alert(1)"),
    "quoted-url": ("worker-c", "Check a quote inside an HTTPS query",
                   'https://example.com/runbooks/worker?q=" onmouseover="alert(1)'),
}
for name, (instance, summary, url) in cases.items():
    data = {
        "receiver": "fixture-email", "status": "firing",
        "groupLabels": {"alertname": "WorkerUnavailable"},
        "commonLabels": {"alertname": "WorkerUnavailable", "instance": instance},
        "commonAnnotations": {"summary": summary, "runbook_url": url},
        "externalURL": "https://alertmanager.example.com",
        "alerts": [{
            "status": "firing",
            "labels": {"alertname": "WorkerUnavailable", "instance": instance},
            "annotations": {"summary": summary, "runbook_url": url},
            "startsAt": "2026-01-01T00:00:00Z",
            "endsAt": "2026-01-01T01:00:00Z",
            "generatorURL": "https://prometheus.example.com/graph",
            "fingerprint": name,
        }],
    }
    (out / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
print("Wrote four synthetic notification fixtures")
PY
```

```bash
python3 fixtures.py
python3 -m json.tool fixtures/markup.json
```

## 5. Check structure, literal text, and URL boundaries

A successful command exit only means rendering completed. The verifier below parses each output and checks a deliberately narrow contract:

- Exactly the expected start-element sequence and attribute sets.
- Heading, paragraph, and link text that round-trip through HTML entities without changing the original value.
- One link with the reviewed decoded `href`, including the filtered marker for the unsafe scheme and percent-encoded quotes for the quoted URL.

This is not a universal safety test. It covers one template shape and four examples. Extend it when changing the layout or adding new contexts such as CSS, JavaScript, or additional attributes; preferably keep those contexts out of notification templates.

```bash
cat > verify.py <<'PY'
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

class Message(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = {"h1": [], "h2": [], "p": [], "a": []}
        self.active = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        allowed = {
            "html": [("lang", "en")], "head": [],
            "meta": [("charset", "utf-8")], "title": [],
            "body": [], "h1": [], "section": [], "h2": [], "p": [],
        }
        if tag == "a":
            if len(attrs) != 1 or attrs[0][0] != "href":
                raise ValueError(f"unexpected link attributes: {attrs!r}")
            self.links.append(attrs[0][1])
        elif tag not in allowed or attrs != allowed[tag]:
            raise ValueError(f"unexpected element or attributes: {tag} {attrs!r}")
        self.tags.append(tag)
        if tag in self.text:
            self.active = tag

    def handle_endtag(self, tag):
        if tag == self.active:
            self.active = None

    def handle_data(self, data):
        if self.active:
            self.text[self.active].append(data)

template = sys.argv[1] if len(sys.argv) > 1 else "email.tmpl"
mode = sys.argv[2] if len(sys.argv) > 2 else "html"
results = Path("results")
results.mkdir(exist_ok=True)
expected_tags = ["html", "head", "meta", "title", "body", "h1",
                 "section", "h2", "p", "a"]
for name in ("ordinary", "markup", "unsafe-url", "quoted-url"):
    fixture = Path(f"fixtures/{name}.json")
    data = json.loads(fixture.read_text())
    run = subprocess.run([
        "./amtool", "template", "render", f"--template.glob={template}",
        '--template.text={{ template "gntech.email" . }}',
        f"--template.type={mode}", f"--template.data={fixture}",
    ], text=True, capture_output=True, check=True)
    (results / f"{name}.html").write_text(run.stdout)
    try:
        message = Message()
        message.feed(run.stdout)
        message.close()
        if message.tags != expected_tags:
            raise ValueError(f"unexpected element sequence: {message.tags!r}")
        alert = data["alerts"][0]
        expected_text = {
            "h1": "FIRING", "h2": alert["labels"]["instance"],
            "p": alert["annotations"]["summary"], "a": "Open runbook",
        }
        if {k: "".join(v) for k, v in message.text.items()} != expected_text:
            raise ValueError("visible text did not round-trip through HTML entities")
        expected_link = {
            "ordinary": "https://example.com/runbooks/worker?team=ops&view=full",
            "markup": "https://example.com/runbooks/worker",
            "unsafe-url": "#ZgotmplZ",
            "quoted-url": "https://example.com/runbooks/worker?q=%22%20onmouseover=%22alert%281%29",
        }[name]
        if message.links != [expected_link]:
            raise ValueError(f"unexpected href: {message.links!r}")
    except ValueError as error:
        raise SystemExit(f"FAIL {name}: {error}") from error
    print(f"PASS {name}")
PY
```

```bash
python3 verify.py
cat results/markup.html
cat results/unsafe-url.html
```

Expect four PASS lines. The markup fixture includes these serialized lines:

```html
<h2>worker-&lt;b&gt;east&lt;/b&gt;</h2>
<p>&lt;img src=x onerror=&#34;alert(1)&#34;&gt;</p>
```

The parser reads the heading as `worker-<b>east</b>` and the paragraph as the original image-shaped string. Neither `b` nor `img` is a generated element. The ordinary fixture preserves `café` and the query's `&` after entity decoding.

The unsafe URL fixture instead contains:

```html
<a href="#ZgotmplZ">Open runbook</a>
```

That marker is evidence of filtering, **not a working runbook link**. It is expected only in this adversarial test. If it appears in a normal notification, fix the source URL or omit the link according to your reviewed contract. Do not bypass filtering to remove the marker.

The verifier writes each render to `results` before checking it, so failures retain evidence. It deliberately fixes the quoted URL's serialized normalization for this binary; a future version may normalize it differently and require a reviewed update.

## 6. Prove two unsafe changes are detected

The first mutation adds `safeHtml` to the summary. That accepts the markup fixture as trusted HTML, so an `img` element appears and the parser rejects it. The second uses the original template in text mode. Its label markup becomes a `b` element when interpreted as HTML, and the same guard rejects it.

Both render operations can succeed while producing the wrong HTML boundary. These controls distinguish that problem from a template syntax error. They create separate files and do not modify the original template.

```bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
source = Path("email.tmpl").read_text()
Path("unsafe-email.tmpl").write_text(source.replace(
    "{{ .Annotations.summary }}", "{{ .Annotations.summary | safeHtml }}"))
PY
if python3 verify.py unsafe-email.tmpl html > unsafe-email.log 2>&1; then
  echo 'FAIL: safeHtml bypass escaped detection' >&2
  exit 1
fi
grep -F 'FAIL markup: unexpected element or attributes: img' unsafe-email.log
if python3 verify.py email.tmpl text > wrong-mode.log 2>&1; then
  echo 'FAIL: text mode escaped detection' >&2
  exit 1
fi
grep -F 'FAIL markup: unexpected element or attributes: b' wrong-mode.log
python3 verify.py
```

You should see the two expected `FAIL markup:` messages followed by four PASS lines for the original HTML-mode template. Read `unsafe-email.log` and `wrong-mode.log`; do not treat a random download, parsing, or command failure as a successful negative control. The exact `grep` checks above require the intended element errors.

The final successful run restores `results/*.html` after the negative runs. Review those baseline files rather than the unsafe mutation outputs.

## 7. Carry the checks into a controlled rollout

Keep the reviewed template, sanitized fixtures, and verifier together. When integrating it with an actual email receiver:

1. Use the matching amtool version and test every invoked template name. Render the HTML body in HTML mode; test plain-text and subject fields separately according to the integration's documented behavior.
2. Add cases reflecting your real alert contract: missing fields, mixed firing/resolved groups, long values, and approved runbook destinations. Never commit captured secrets or private identifiers as fixture data.
3. Load the named template through the configuration's `templates` paths and reference it from the email integration's documented `html` field. The [official examples](https://prometheus.io/docs/alerting/latest/notification_examples/) show that wiring. This article supplies no SMTP credentials or production configuration.
4. Preserve the previous configuration **and template files**, validate the complete candidate, and use your controlled reload procedure. Offline rendering alone does not prove which receiver is selected or which live file is loaded.
5. Send synthetic firing and resolved notifications to an isolated mailbox. Inspect the raw MIME body and the supported email clients, including link destinations and formatting. Clients can rewrite or strip HTML; a parser test cannot establish their behavior.
6. If acceptance fails, restore both configuration references and template files through the same validated change process, reload, and verify a new synthetic notification at that isolated destination.

No production changes are needed to run this lab, so local rollback simply means returning to `email.tmpl` and HTML mode.

## Troubleshooting and cleanup

| Symptom | Investigate |
|---|---|
| Annotation markup creates a new element | Check rendering mode and remove trusted-HTML conversions from untrusted values. |
| `#ZgotmplZ` appears in a normal link | Review the URL scheme/value and your runbook policy; do not mark it trusted to hide the symptom. |
| Exact URL expectation differs on another release | Compare the normalized URL and attribute structure; review the change before updating the baseline. |
| Local fixtures pass but received mail differs | Check deployed version, template path/name, actual notification data, MIME body, and client rewriting. |

Keep the workspace while reviewing evidence. To remove it afterward, inspect the exact path first:

```bash
printf 'Lab directory: %s\n' "$lab_dir"
cd ..
# Review the printed path before deleting the disposable directory.
rm -r -- "$lab_dir"
```

## Official references

Reviewed November 27, 2026. Current documentation may contain features newer than this historical baseline; the pinned source establishes the renderer and helper used here.

- [Alertmanager notification template reference](https://prometheus.io/docs/alerting/latest/notifications/).
- [Official HTML email and named-template examples](https://prometheus.io/docs/alerting/latest/notification_examples/).
- [Go HTML templates: contexts, trust model, and filtered URLs](https://pkg.go.dev/html/template).
- [amtool 0.28.1 renderer: text versus HTML selection and JSON data](https://github.com/prometheus/alertmanager/blob/v0.28.1/cli/template_render.go).
- [Alertmanager 0.28.1 template execution and safeHtml implementation](https://github.com/prometheus/alertmanager/blob/v0.28.1/template/template.go).
- [Official 0.28.1 release assets](https://github.com/prometheus/alertmanager/releases/tag/v0.28.1).

Next planned topic: test Alertmanager notification scheduling across a time-interval boundary.
