# Article verification status

Put a short `## Verification status` section near the beginning of procedural guides, after the introduction. Use plain Markdown so it works without theme changes.

Use four rows:

- **Environment:** identify the hardware/software actually covered. Record exact versions only when known; do not infer them from the current date.
- **Previously reported lab observations:** state the concrete observation and its limits. A successful login on one host does not validate every setup step on another.
- **Preparation checks:** list checks that actually ran. Distinguish Markdown, YAML and shell parsing from application configuration validation and runtime testing. Never mark a command as tested merely because it parses.
- **Still to verify:** name the remaining checks a reader needs before relying on the procedure.

If no runtime evidence exists, say so. Do not add a 'last tested' date without a dated test record. `lastmod` records an editorial change, not proof of fresh runtime validation. Update the table when new evidence arrives and keep detailed limitations in the article.

Avoid claiming every blog post was lab-tested. CI build results, screenshots, generated illustrations, and historical observations each support different claims. None is a substitute for an end-to-end test of a procedure.
