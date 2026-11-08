---
title: "Linux Has Free Disk Space but Cannot Create Files? Check Inodes"
description: "Compare byte and inode capacity, locate small-file-heavy directories with GNU du, and practice scoped cleanup in a disposable lab."
date: 2026-11-08T12:00:00-04:00
draft: false
ShowToc: true
tags: [linux, storage, troubleshooting, operations, homelab]
keywords: [Linux inode capacity, df inodes, du inodes, small files]
summary: "Check the filesystem's file capacity alongside free bytes, locate directories with many entries, and recover through application-aware retention."
cover:
  image: "/images/posts/inode-capacity/featured.webp"
  alt: "Compact server drive bays with small amber lights and blue reflections beside a laptop."
  caption: "AI-generated editorial artwork."
  relative: false
---

A service reports that it cannot create a file, yet the filesystem still has free gigabytes. Check its inode statistics alongside byte capacity. A workload producing many small files can reach a different limit from a workload writing a few large files.

This guide uses GNU Coreutils and Python 3 on Debian or Ubuntu. The disposable lab creates 1,000 empty files under your home directory. It demonstrates accounting and scoped cleanup. It deliberately leaves the filesystem far from exhaustion.

## 1. Identify the affected filesystem

Use the directory where the failed write occurred. The example checks a log directory.

```bash
target=/var/log
findmnt -T "$target"
df -hT "$target"
df -i "$target"
```

Read the available byte and inode counts together with the application's exact error. Filesystem implementations account for inodes differently, so interpret the values using the filesystem type. Quotas, read-only mounts, permissions, and metadata capacity can also block writes.

| Observation | Next investigation |
| --- | --- |
| Bytes available, inode availability exhausted | Locate file-heavy trees and inspect their retention policy. |
| Bytes exhausted | Locate space usage and check deleted-but-open files. |
| Both appear available | Inspect quotas, mount state, permissions, and the exact application error. |
| Statistics unavailable or unusual | Use the filesystem's own administration tools and documentation. |

An inode identifies a filesystem object and stores its metadata. Directory entries name objects. Multiple hard links can refer to one inode, so a count of names is not always a count of distinct objects.

For the related case where deletion fails to release bytes, see the [deleted-but-open-file guide](/posts/2026-11-08-linux-deleted-open-files-disk-space/).

## 2. Find where the inode usage is concentrated

Start with a bounded directory on the affected filesystem. GNU du can count inode usage instead of storage blocks.

```bash
target=/var
sudo du --inodes -x --max-depth=1 -- "$target" | sort -n
```

Select a high-count child from the output and repeat at that path. The `-x` option keeps the walk within one filesystem. Keep permission errors visible. A deep scan on a busy tree can take time and consume I/O.

Review the owner and purpose of the concentrated data. Common candidates include application caches, spool directories, generated thumbnails, and abandoned job outputs. A large count can be legitimate. The recovery decision depends on the application and retention contract.

## 3. Practice counting in a disposable lab

Check that your home filesystem has enough byte and inode headroom first. Then create a unique directory and 1,000 empty files.

```bash
df -h "$HOME"
df -i "$HOME"
lab_dir="$(mktemp -d "$HOME/gntech-inodes.XXXXXX")"
python3 - "$lab_dir" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
files = root / "files"
files.mkdir()
for number in range(1000):
    (files / f"entry-{number:04d}").touch(exist_ok=False)
print(f"Created 1000 empty files in {files}")
PY

du -sh -- "$lab_dir"
du --inodes -s -- "$lab_dir"
find "$lab_dir/files" -maxdepth 1 -type f -printf '.\n' | wc -l
```

Expect the final command to count 1,000 regular files. GNU du's inode total also includes the directories it visits. Even empty files require metadata, and directories themselves can consume storage. Actual allocated bytes vary by filesystem.

The lab does not need a measurable change in the host-wide percentage to succeed. Its useful observations are the scoped file count and the inode count of that tree.

## 4. Delete only the files created by this lab

Keep using the same shell so `lab_dir` still refers to the unique directory. The cleanup checks that the child directory contains exactly the expected names and only regular files before unlinking them.

```bash
python3 - "$lab_dir" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
files = root / "files"
expected = {f"entry-{number:04d}" for number in range(1000)}
entries = list(files.iterdir())
if {path.name for path in entries} != expected:
    raise SystemExit("Unexpected contents; review before cleanup")
if any(path.is_symlink() or not path.is_file() for path in entries):
    raise SystemExit("Unexpected object type; review before cleanup")
for path in entries:
    path.unlink()
files.rmdir()
root.rmdir()
print("Removed the disposable lab tree")
PY
```

On a production tree, use the application's documented retention or cleanup operation. Coordinate with the owner and preserve necessary evidence before deleting records. Stop or pause a runaway producer through its supported controls when it would immediately refill the space.

Deleted data requires an appropriate backup for recovery. Preview the proposed cleanup scope and establish a recovery point before applying a retention change.

## 5. Verify recovery and prevent recurrence

After the approved cleanup, rerun both df commands against the affected path. Confirm that the application can create and use its required data, then watch its file growth over a representative period.

Record the filesystem, object count, producer, retention change, and application result. Monitor both byte capacity and file capacity where the filesystem exposes meaningful inode statistics. Choose thresholds that leave time to investigate and run cleanup.

Filesystem growth or migration can be appropriate when the object count is legitimate. Plan that work using filesystem-specific documentation, a tested backup, and the workload's expected file count. Deleting arbitrary directories or reformatting a volume is not a diagnostic step.

## Official references

- [GNU df inode statistics](https://www.gnu.org/software/coreutils/manual/html_node/df-invocation.html)
- [GNU du inode accounting](https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html)
- [Linux inode metadata](https://man7.org/linux/man-pages/man7/inode.7.html)
