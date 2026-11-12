---
title: "Audit an Infrastructure Tutorial Before You Trust It"
description: "Check rendered links and assets, prove the checker can catch a broken link, and record what still needs a lab run."
date: 2026-11-12T00:00:00-04:00
draft: false
ShowToc: true
tags: [hugo, documentation, homelab, operations]
keywords: [infrastructure tutorial audit, Hugo content checks, reproducibility, restore evidence]
summary: "Use the GNTECH Infrastructure Series to see what a publishing check proves and how to record the remaining lab work."
cover:
  image: "/images/posts/infrastructure-tutorial-audit/featured.webp"
  alt: "An open notebook and pencil on a workbench in front of softly lit server racks."
  caption: "AI-generated editorial artwork."
  relative: false
---

A tutorial can render perfectly while a command assumes the wrong software version or an unavailable credential. An audit needs evidence at both levels. Start with what a reader can open, then check what they would need to reproduce the result.

The [GNTECH Infrastructure Series](/gntech-infrastructure-series/) has twelve written installments, from the architecture to the operations handoff. This follow-up uses the blog's existing publishing checks and the backup chapter as a worked example. You need a checkout of the GNTECH blog, Git, Bash, Python 3.11 or newer, and the Hugo Extended version pinned in the checkout's publishing workflow. Nothing in the publishing exercise connects to a hypervisor or backup server.

## 1. Build the same revision a reader will see

From the repository root, record the revision and Hugo version. Initialize the pinned theme submodule. Use fresh output directories so files from an earlier build cannot make a stale link appear valid.

```bash
git rev-parse HEAD
git submodule update --init --recursive &&
hugo version &&
audit_dir="$(mktemp -d /tmp/gntech-content-audit.XXXXXX)" &&
hugo --destination "$audit_dir/normal" --printPathWarnings &&
python3 tools/audit-content.py --site "$audit_dir/normal" &&
hugo --buildDrafts --destination "$audit_dir/drafts" --printPathWarnings &&
python3 tools/audit-content.py --site "$audit_dir/drafts"
```

Review duplicate output path warnings and confirm that the series hub and its linked installments render in the normal build. The draft build lets you audit unpublished drafts as well. If a link works only in that build, verify whether the target is intentionally unpublished before pointing readers at it.

Open the hub and sample the cover and the technical figures in the browser. The content audit checks internal article-body links, image targets, and anchors, and parses shell snippets without executing them. For a PR, also run the metadata, cover-file, unit, and diff checks listed in the repository's [publishing checklist](https://github.com/gntech-dev/gntech-blog/blob/master/docs/publishing-checks.md). Review vendor links separately against the documentation for the version named in the article.

## 2. Give the checker a link you know should fail

Use the same shell and repository root. This fixture creates only one HTML page under the temporary directory. Its link points to a deliberately missing page. The `post-content` class gives the checker the same article-body boundary it looks for in Hugo output.

```bash
fixture="$audit_dir/fixture"
mkdir -p "$fixture"
cat > "$fixture/index.html" <<'HTML'
<!doctype html>
<html lang="en">
<title>Audit fixture</title>
<div class="post-content">
  <a href="/missing-audit-page/">Broken example</a>
</div>
</html>
HTML

if python3 tools/audit-content.py --site "$fixture" > "$fixture/result.log" 2>&1; then
  printf 'Unexpected pass for the broken-link fixture\n' >&2
  false
else
  grep -F 'missing article target /missing-audit-page/' "$fixture/result.log"
fi
```

Look for the missing-target message. A generic failure, such as a missing Python dependency, does not demonstrate that the checker recognized the link. Keep the fixture separate from your Hugo build and discard the temporary directory once you have recorded the results.

## 3. Review the operation the page asks the reader to perform

Take one consequential step per installment and write down the prerequisite, the evidence that would count as success, and the fallback if the result differs. For example, [Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) asks the reader to recover a disposable VM from an off-site backup. Review the Proxmox documentation for the stated PVE and PBS versions and identify which evidence each step produces.

| Checkpoint | Evidence to record | Where it stops |
| --- | --- | --- |
| Off-site snapshot verification | Snapshot timestamp and verification result on the off-site datastore | Backup integrity check |
| Restore to an unused VM ID | Recovery-node task result and restored guest configuration | Restore task completion |
| Isolated boot and marker comparison | Console output and matching marker checksum | Evidence for this disposable guest |
| Production recovery | An application-level check and timing from an approved drill | Pending until that drill runs |

For a command that changes state, use a disposable guest or lab system first. Check what the command will act on, who can run it, and how the reader can undo it. Record the actual version and result in the audit notes. Keep raw logs private if they contain addresses, credentials, or identifiers. The [Part 12 handoff](/posts/2026-11-05-gntech-infrastructure-part-12-security-operations/) covers running and recording an operational acceptance test.

## 4. Close the audit with evidence

Keep the audit record short enough to read in a pull request. Include the revision, tool versions, and links to the relevant build or redacted lab logs. Use explicit statuses such as **rendered**, **syntax checked**, **lab verified**, or **pending**. If a vendor page moved, update the link only after confirming that the replacement still supports the command shown. If only a lab can settle the question, leave a concrete follow-up, such as testing whether the recovery operator can retrieve the encryption key without using the primary site's identity system.

## Official references

- [Hugo build options](https://gohugo.io/commands/hugo/)
- [Bash syntax checking with noexec](https://www.gnu.org/s/bash/manual/html_node/The-Set-Builtin.html)
- [Proxmox Backup Server verification](https://pbs.proxmox.com/docs/maintenance.html#verification)
- [Proxmox VE backup and restore](https://pve.proxmox.com/pve-docs/chapter-vzdump.html)
