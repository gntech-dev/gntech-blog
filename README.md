# GnTech Blog ⚙️

Personal blog about homelab infrastructure, networking, automation, and all the rabbit holes in between.

Built with [Hugo](https://gohugo.io/) + [PaperMod](https://github.com/adityatelange/hugo-PaperMod). Deployed via [Cloudflare Pages](https://pages.cloudflare.com/).

## Quick Start

```bash
# Clone with submodules (includes theme)
git clone --recurse-submodules https://github.com/gntech-dev/gntech-blog.git
cd gntech-blog

# Development server with live reload
hugo server -D

# Build for production
hugo
```

Output goes to `public/`.

## Add a Post

Just drop a Markdown file in `content/posts/` with front matter:

```yaml
---
title: "My Post"
description: "What it's about"
date: 2026-05-08T00:00:00-04:00
draft: false
tags:
  - whatever
categories:
  - category
---
```

**⚠️ No Hugo shortcodes.** This theme (PaperMod) has no custom shortcodes like `alert`, `hint`, `notice`, `admonition`, etc. Plain Markdown only. Run `hugo` before pushing to verify.

## Posting and review workflow

1. Read related posts and choose a useful uncovered topic or a focused update.
2. Prepare the article on a topic branch and open a pull request without requesting a separate pre-PR approval.
3. Include relevant visuals, descriptive alt text, verification evidence and remaining limitations.
4. Review the GitHub checks and Cloudflare preview. Fix failures; do not describe pending checks as passed.
5. Notify the owner with the PR link and a concise summary of changes and validation.
6. The owner reviews and merges. Cloudflare Pages builds the merged publication-ready article.

The pull request is the review boundary. Do not merge or publish on the owner's behalf without authorization.

### Drafts and publication

Hugo's default archetype intentionally starts with `draft = true` for work in progress. Keep an unfinished GitHub PR in draft state while writing. Before marking a post PR ready for review, set the article to `draft: false` (YAML) or `draft = false` (TOML). Merging should publish the approved post without a second flag-change PR.

### Article standard

- Use plain Markdown; do not introduce unsupported Hugo shortcodes.
- Explain the problem, prerequisites, steps, expected results, troubleshooting and rollback where relevant.
- Give copy-paste file-creation commands such as quoted `cat` heredocs or scoped `sed` edits. Preserve existing configuration before replacement.
- Put a concise verification table near the beginning of procedural guides. Separate reported lab observations, syntax checks, application validation and runtime testing. See [verification guidance](docs/article-verification-status.md).
- Record known versions and meaningful limitations. Do not invent performance results, tested dates or successful deployments.
- Include a relevant cover for new posts and an instructional diagram when it helps explain the procedure. Prefer exact SVG diagrams for topology and generated illustrations for editorial imagery. Identify generated imagery; never present it as a real screenshot.
- Save assets under `static/images/`, add alt text and useful captions, and preserve generated-image provenance where applicable.
- Add a few relevant next-reading links with a reason for each.
- Pair English/Spanish editions with the same `translationKey`. Label condensed editions and links to a different language accurately.
- Preserve retired URLs when consolidating articles and update internal links to the maintained destination.

### Validation

The [publishing workflow](.github/workflows/content-checks.yml) builds production and draft-inclusive sites, runs the existing content audit, and checks changed publication metadata and cover assets. See [local instructions and limits](docs/publishing-checks.md).

These checks do not certify command behavior, hardware compatibility or external links. Report what actually ran and what remains unverified. Check the rendered page on desktop and mobile when a preview is available.

This describes the PR-based collaboration routine. Updating these instructions does not reconfigure any separate OpenClaw or Telegram scheduled job.

## Structure

```
.
├── content/          # Markdown posts and pages
│   ├── posts/        # Blog posts
│   └── about.md      # About page
├── themes/PaperMod   # Hugo PaperMod theme (submodule)
├── static/           # Static assets
├── hugo.toml         # Site configuration
└── public/           # Build output (gitignored)
```

## Deploy

Push to `master` — Cloudflare Pages auto-builds and deploys.

- **Build command:** `hugo` (output: `public/`)
- **Hugo version:** `0.147.0` (extended)
- **Framework preset:** Hugo

## License

Content and code are private unless otherwise noted.

## Content audit

After editing articles, build the site and check the rendered article links and source snippets:

```bash
hugo --destination public --printPathWarnings
python3 tools/audit-content.py --site public
git diff --check
```

The audit script needs Python 3.9+ and Bash. It parses shell examples without executing them. Technical procedures still need version-appropriate documentation review and lab validation. See [the October 2026 audit report](docs/content-audit-2026-10-30.md) for coverage and limitations.

## Article navigation

PaperMod's table of contents is enabled globally and collapsed on initial page
load. Readers can expand it to jump to a guide's sections. It uses the existing
Hugo table-of-contents renderer; no JavaScript dependency or custom shortcode is
introduced by this configuration change.

For a short page where an outline adds little value, set `ShowToc: false` in YAML
front matter (or `ShowToc = false` in TOML). An individual page can use
`TocOpen: true` if an expanded outline is useful. Keep descriptive headings so the
links make sense outside their surrounding text.

See the [PaperMod variables](https://github.com/adityatelange/hugo-PaperMod/wiki/Variables)
for the theme's supported overrides. Preview a long guide in English and Spanish
at desktop and mobile widths after changing navigation settings.
