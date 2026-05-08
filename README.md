# GnTech Blog ⚙️

Personal blog about homelab infrastructure, networking, automation, and all the rabbit holes in between.

Built with [Hugo](https://gohugo.io/) + [PaperMod](https://github.com/adityatelange/hugo-PaperMod). Deployed via Cloudflare Pages.

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

```bash
hugo new content posts/my-post.md
```

Or just drop a Markdown file in `content/posts/` with front matter:

```yaml
---
title: "My Post"
description: "What it's about"
date: 2026-05-08T01:00:00-04:00
draft: false
tags:
  - whatever
categories:
  - category
---
```

## Structure

```
.
├── content/          # Markdown posts and pages
│   └── posts/        # Blog posts
├── themes/PaperMod   # Hugo PaperMod theme (submodule)
├── static/           # Static assets (images, files)
├── hugo.toml         # Site configuration
└── public/           # Build output (gitignored)
```

## Deploy

Push to `master` — Cloudflare Pages auto-builds and deploys.

Build command: `hugo` (output: `public/`, Hugo version `0.147.0`)

## License

Content and code are private unless otherwise noted.
