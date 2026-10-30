# Blog content audit — October 30, 2026

Base commit: `38d57c52f2c413920b931839ebfc58ece4cc5f8e`.

## Coverage

All 177 posts received automated source checks. The full site was built with the README's Hugo Extended 0.147.0 and the repository's pinned PaperMod submodule. Rendered article-body links, image paths, and fragment targets were checked against the generated site. Shell-tagged examples were parsed with `bash -n` without execution.

Technical review concentrated on the posts and snippets where the scan exposed concrete errors, especially firewall configuration, RouterOS, Windows PowerShell, storage/retention, health metrics, and security advisories. This is not a certification of every command or factual statement across all 177 posts.

## Corrections

- Removed 160 unused `canonical` fields. The pinned PaperMod theme reads `canonicalURL`; the discarded values frequently used the wrong domain or nonexistent undated paths. The theme now continues to derive canonicals from the actual permalinks. Existing article URLs were preserved.
- Repaired 44 internal article references in the initial source pass, including wrong-domain references. Where an undated name matched multiple articles, selected the most recent article available at the referring article's publication date.
- Separated the English and Spanish content mounts. The original build reported duplicate Spanish output paths; the corrected build no longer does.
- Fixed 139 Bash-style line continuations in PowerShell examples across four Windows Server articles and removed 20 unfinished screenshot-note blocks.
- Modernized six legacy Compose command occurrences without renaming Compose files, tags, package names, or URLs.
- Fixed nested Markdown fences, mislabeled RouterOS/configuration/transcript blocks, and unquoted angle-bracket command placeholders. Placeholder arguments still require readers to supply their own values.
- Rewrote the Docker/UFW procedure: corrected forwarding behavior, original-destination matching, ingress interface selection, IPv4 scope, persistence limits, and rollback. Removed the nonexistent firewall chain and claims that LAN bindings make UFW INPUT rules filter Docker forwarding.
- Rewrote the Docker native nftables procedure using Docker's documented tables, separate custom-table ownership, forwarding prerequisites, Swarm limitation, and enabled firewall-rule creation.
- Replaced the general nftables article's incomplete Docker firewall replacement and blanket ruleset flushing with a scoped host-input example and backend-specific Docker references.
- Reworked the 10GbE guide to correct RouterOS syntax, access-port PVIDs, management VLAN access, offload verification, MTU sequencing, and unsupported universal tuning/performance claims.
- Added a transparent correction to the NGINX poolslip article. Its asserted zero-day details were not supported by an identified vendor advisory; removed the unsupported exploit and mitigation claims and supplied a vendor-advisory verification workflow.
- Corrected CVE-2026-31431's classification as a Linux kernel issue, removed universal container-escape assertions, and replaced inadequate exposure checks with vendor package and running-kernel verification.
- Removed an unsupported security-incident claim from the supply-chain article's introduction.
- Removed destructive manual Loki chunk deletion. Corrected a health-exporter case statement that matched `unhealthy` as `healthy`, and placed metric metadata into the generated textfile.
- Corrected four-hour and six-hour systemd schedules that actually ran every four/six minutes, corrected the initial daily cleanup schedule, fixed broken ZFS shell syntax and unbounded midnight retention, and removed automatic volume pruning from the weekly cleanup example.
- Removed disk-allocation commands presented as changes to existing Proxmox boot disks, an incomplete IOThread command, and raw duplicate-device QEMU arguments. Existing-disk edits now preserve the recorded volume and options.
- Corrected the rootful Caddy example's mixed shell/config block and container-localhost upstream assumption.
- Replaced NFS soft mounts for application storage, corrected locking guidance, and made the consolidated exports example write an actual configuration file.
- Corrected RouterOS NTP/logging/graphing examples and removed scripts that claimed to upload backups without doing so. Replaced the faulty address-list hosts-file parser with native DNS-adlist guidance.
- Clarified the historical Frigate example's device-access requirements, storage sizing, exposed ports, and missing notifier implementation.
- Probed 142 unique external Markdown URL strings in the initial set. Seven returned 404: removed unsupported repository/exporter/dashboard claims, removed an obsolete resource link, or replaced the documentation destination. Corrected a non-ASCII badge URL. A Paperless documentation endpoint returned 403; a private/example Grafana dashboard returned 530. Those responses do not establish that the corresponding products or examples are invalid.

## Validation

From the repository root:

```bash
hugo --destination public --printPathWarnings
python3 tools/audit-content.py --site public
git diff --check
```

The audit tool uses Python's standard library and the installed Bash parser. It checks Markdown fences, known metadata/placeholder issues, PowerShell continuation mistakes, Bash syntax, and rendered internal article links/images/anchors. It does not run any documented infrastructure command or crawl external sites.

The four-hour and six-hour calendar expressions were additionally checked with `systemd-analyze calendar`. Health-status mapping was checked with healthy, unhealthy, and unclassified sample inputs.

## Limits and follow-up

- RouterOS, Windows, Proxmox, NFS, ZFS, Docker firewall, and kernel-remediation procedures were not executed against live systems. Hardware-specific behavior and version compatibility still require lab validation.
- Most posts retain their historical versions and context. Unrelated release, pricing, performance, and availability statements were not comprehensively refreshed.
- A successful external HTTP response establishes reachability, not technical accuracy or suitability. Protected endpoints can reject automated probes.
- Destructive examples that remain in the collection require case-by-case review in a disposable lab. Shell syntax checks do not establish their safety.
- No changes were merged to `master` or deployed as part of this audit.
