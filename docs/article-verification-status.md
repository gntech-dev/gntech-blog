# Article verification status

Put a short `## Verification status` section near the beginning of procedural guides, after the introduction. Use plain Markdown so it works without theme changes.

Use the following four evidence categories; add rows when a dated runtime record needs its own scope:

- **Environment:** identify the hardware/software actually covered. Record exact versions only when known; do not infer them from the current date.
- **Previously reported lab observations:** state the concrete observation and its limits. A successful login on one host does not validate every setup step on another.
- **Preparation checks:** list checks that actually ran. Distinguish Markdown, YAML and shell parsing from application configuration validation and runtime testing. Never mark a command as tested merely because it parses.
- **Still to verify:** name the remaining checks a reader needs before relying on the procedure.

If no runtime evidence exists, say so. Do not add a 'last tested' date without a dated test record. `lastmod` records an editorial change, not proof of fresh runtime validation. Update the table when new evidence arrives and keep detailed limitations in the article.

Avoid claiming every blog post was lab-tested. CI build results, screenshots, generated illustrations, and historical observations each support different claims. None is a substitute for an end-to-end test of a procedure.

## Recorded runtime labs as of October 31, 2026

| Guide | Evidence | What remains outside that evidence |
|---|---|---|
| PostgreSQL dumps and scheduling | [Integrated database lab](https://github.com/gntech-dev/gntech-blog/actions/runs/41247821482): dump/restore, service/timer execution, failure propagation, Restic copy, and a new database restore. | Production data, real remote storage, missed-run monitoring, external notifications, hardware loss. |
| Restic file recovery | [Restic lab](https://github.com/gntech-dev/gntech-blog/actions/runs/41245705581): file restore, separately encrypted copy, authentication rejection, full data check, and recovery without original materials. | A remote backend, application consistency, and site-loss durability. |
| Other revised procedures | Source review and syntax/render checks, as stated in each guide and the [consolidated audit](content-audit-consolidated-2026-10-31.md). | Runtime behavior is not established by a parser or by another article's lab. |

The [Start Here recovery path](../content/start-here.md#backup-and-recovery) distinguishes guest backups, database-native recovery, and encrypted file copies. Avoid maintaining competing executable backup scripts in deployment guides; link to the workflow with the clearest evidence and adapt it explicitly.
