# GNTECH Blog — Visual Publishing Standard

Adopted as a proposed editorial standard for review with GNTECH Infrastructure Series Parts 01–03.

## Two separate image jobs

**Featured artwork** is for visual discovery on post cards, social previews, and article headers. Prefer an original cinematic, visually engaging depiction of the article's subject (datacenter, hardware, cloud infrastructure, routing or security). Use a consistent 1200×630, 1.90:1 landscape composition with readable typography, high contrast, strong subject focus, and a distinguishable per-post color/accent. Conceptual artwork is not a screenshot of a working deployment; never add invented telemetry or a purported live dashboard.

**Technical diagrams** live inside the article close to the explanation. Prioritize accuracy and legibility over dramatic effects: actual example topology, bridge ownership, zones, expected network paths, scope, and meaningful alt text. Diagrams may remain SVG and should not be reused as the featured cover merely because they already exist.

## Implementation in Parts 01–03

| Part | New featured cover | Original technical diagram retained |
| --- | --- | --- |
| 01 | `static/images/posts/gntech-infrastructure-part-01/featured.svg` | `static/images/posts/gntech-infrastructure-part-01/architecture.svg` |
| 02 | `static/images/posts/gntech-infrastructure-part-02/featured.svg` | `static/images/posts/gntech-infrastructure-part-02/cover.svg` |
| 03 | `static/images/posts/hetzner-proxmox-dual-chr/featured.svg` | `static/images/posts/hetzner-proxmox-dual-chr/cover.svg` |

The new covers are original layered **vector editorial artwork with an isometric cinematic treatment**, not photorealistic raster output. This is a practical repository-compatible first implementation of the requested aesthetic. Editorial review can replace the cover assets with photographic/generated raster covers later while preserving the filenames and frontmatter contract after adapting file extensions. Do not describe these SVG files as photographs.

## Article checklist

- [ ] One article-specific featured visual; avoid identical template scenes for every post.
- [ ] Technical diagram included when networking, security, deployment or routing would benefit from one.
- [ ] Cover and in-article diagram have different roles and separate paths.
- [ ] Cover alt text describes actual artwork; diagram alt text explains technical meaning.
- [ ] Do not invent production states, numerical dashboards, provider branding endorsements, or deployment facts.
- [ ] Maintain a consistent landscape aspect ratio, check small-screen crops, inspect dark and light themes.
- [ ] Verify local asset paths, SVG XML syntax, Hugo build, and link checks in CI.
- [ ] No external hotlinked stock image needed for article rendering.
