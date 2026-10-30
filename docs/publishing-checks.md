# Blog publishing checks

The `Blog publishing checks` workflow validates pull requests, pushes to master,
and manual runs. It uses Hugo extended 0.147.0 to match the documented production
build, and verifies the downloaded release archive against its release checksums.
Keep that version in sync with Cloudflare Pages when upgrading Hugo.

For changed articles under either language's `posts` directory it checks:

- Parseable YAML or TOML front matter and a nonempty title.
- A boolean `draft` field, if supplied.
- No `draft: true` articles in a PR marked ready for review or on master.
- Local cover files exist, and supplied cover images have descriptive alt text.

A draft GitHub PR can retain Hugo draft articles. Marking the PR ready for review
reruns the guard. For this blog's review workflow, prepare articles with
`draft: false`; the unmerged PR is the review boundary and merging publishes them.
Omitting `draft` uses Hugo's normal false default.

The existing content audit checks source fences, Bash syntax without executing
examples, and internal body links, images and anchors in rendered HTML. The
workflow audits both a normal build and a build including drafts. Cover existence
is checked separately because theme covers sit outside the article body.

External URLs are not fetched by these checks. They do not validate command
behavior, Windows PowerShell syntax, hardware compatibility, security claims, or
the visual quality of a page. Review and lab testing remain separate.

Run locally from the repository root with Python 3.11+, Bash and the matching Hugo
extended release installed:

```bash
python3 -m pip install PyYAML==6.0.3
python3 -m unittest discover -s tools -p test_publication.py -v
python3 tools/check-publication.py --base origin/master
hugo --destination public --printPathWarnings
python3 tools/audit-content.py --site public
hugo --buildDrafts --destination public-drafts --printPathWarnings
python3 tools/audit-content.py --site public-drafts
git diff --check origin/master HEAD
```

Add `--allow-drafts` to the metadata check when working on an intentional draft.
Use a Python virtual environment for local dependencies if needed.

The workflow reports a check; it does not change repository protection settings.
After its first successful run, the owner can make `Build and audit blog` a
required check in the master branch rules. Until that is configured, a failed
check does not itself prevent someone with merge permission from merging.
