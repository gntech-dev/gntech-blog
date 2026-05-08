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
tags:
  - whatever
categories:
  - category
---
```

**⚠️ No Hugo shortcodes.** This theme (PaperMod) has no custom shortcodes like `alert`, `hint`, `notice`, `admonition`, etc. Plain Markdown only. Run `hugo` before pushing to verify.

## Automated Blog Workflow

Posts are drafted daily at **07:00 AST** by an OpenClaw automation agent:

1. The agent reads existing posts and picks an uncovered topic
2. A draft is written and saved to `content/posts/`
3. `hugo` validates the build (must pass)
4. A Telegram notification with **inline buttons** (Approve / Skip) is sent to the owner
5. On approval, the agent commits, pushes, and Cloudflare Pages deploys automatically

### Rules enforced by the automation
- **No shortcodes** — only plain Markdown
- **Hugo build must pass** before any Telegram notification
- **No git operations** until approval is received

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
