---
title: "Deleted a Large Linux File but Disk Space Did Not Return?"
description: "Diagnose deleted-but-open files with df, du, and lsof, then reproduce the behavior in a small disposable Python lab."
date: 2026-11-08T00:00:00-04:00
draft: false
ShowToc: true
tags: [linux, storage, troubleshooting, operations, homelab]
keywords: [deleted open files, lsof L1, df du difference, Linux disk space]
summary: "Find the process still holding an unlinked file, distinguish filesystem usage from visible directory usage, and choose an application-aware recovery."
cover:
  image: "/images/posts/deleted-open-files/featured.webp"
  alt: "Compact server drive bays beside a laptop under cool blue and warm amber lighting."
  caption: "AI-generated editorial artwork."
  relative: false
---

You remove a large log, but the filesystem still reports the same usage. The filename has disappeared. A process may still hold the file open.

Linux removes a directory entry when a file is unlinked. When that was the final link, the storage can be released once the remaining open references are gone. Until then, directory scans can miss data that still occupies the filesystem.

This guide targets Debian or Ubuntu with GNU Coreutils, Python 3, and lsof. The lab creates a 16 MiB file in a temporary directory under your home directory. Confirm that filesystem has spare capacity before running it. The expected observations are a reference procedure, with no claim that this problem occurred on a live GNTECH host.

## 1. Compare the same filesystem

Start with the path where the file lived. Replace the example path with the relevant directory.

```bash
target=/var/log
findmnt -T "$target"
df -hT "$target"
df -i "$target"
sudo du -xsh -- "$target"
sudo lsof -nP +L1
```

The commands ask different questions. `df` reports filesystem-level usage. `du` walks reachable directory entries, and the last command lists open files whose link count is below one. A directory total for `/var/log` covers only that tree, while its filesystem may also hold other directories.

| Observation | What to investigate |
| --- | --- |
| Large deleted regular file in lsof | Identify its owning process and filesystem. |
| Many open descriptors with the same device and inode | Several references may point to the same file. Summing every row can overcount. |
| Inodes exhausted | Look for large numbers of small files. |
| No relevant deleted files | Check other directories, mount boundaries, snapshots, and filesystem accounting. |

Read the lsof warnings as well as its rows. Permissions, namespaces, and process visibility can limit collection. Match the device and inode to the affected filesystem before attributing a space problem to an entry.

## 2. Reproduce the behavior with a disposable file

Create a unique lab directory and a script. The script writes actual bytes, unlinks the file while keeping its descriptor open, and pauses so you can inspect it from another terminal. It prints its process ID and exact directory.

```bash
lab_dir="$(mktemp -d "$HOME/gntech-open-file.XXXXXX")"
cat > "$lab_dir/hold-open.py" <<'PY'
import os
import pathlib
import tempfile

directory = pathlib.Path(__file__).resolve().parent
with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
    path = pathlib.Path(handle.name)
    try:
        handle.write(b"x" * (16 * 1024 * 1024))
        handle.flush()
        os.fsync(handle.fileno())
        path.unlink()
        info = os.fstat(handle.fileno())
        print(f"PID={os.getpid()}", flush=True)
        print(f"Directory={directory}", flush=True)
        print(f"Inode={info.st_ino} Links={info.st_nlink}", flush=True)
        print(f"Logical bytes={info.st_size}", flush=True)
        input("Inspect from a second terminal, then press Enter to close: ")
    finally:
        path.unlink(missing_ok=True)
print("The file descriptor is closed.")
PY
python3 "$lab_dir/hold-open.py"
```

In a second terminal, set the values printed by the script. The numeric PID below is a placeholder. Use the live PID from your own run.

```bash
lab_pid=12345
lab_path="$HOME/gntech-open-file.REPLACE"
ps -p "$lab_pid" -o pid,user,comm,args
lsof -nP -a -p "$lab_pid" +L1
du -sh -- "$lab_path"
df -B1 "$lab_path"
```

Expect the lab file to have zero links while still appearing as an open descriptor. Its directory should mainly contain the small script. The filesystem still accounts for the file's allocated storage.

The 16 MiB logical size is deliberately small. Compression, deduplication, filesystem metadata, and concurrent activity can make the observed physical usage differ. Do not expect an exact 16 MiB movement on every filesystem.

## 3. Close the descriptor and check again

Return to the first terminal and press Enter. The context manager closes the file. Repeat the lsof and df commands promptly from the second terminal. Lsof can return a nonzero status when no matching files are found, and the Python process should have exited.

Once you have confirmed the process has ended, remove the known lab script and empty directory from the first terminal.

```bash
rm -- "$lab_dir/hold-open.py"
rmdir -- "$lab_dir"
```

A snapshot-capable filesystem may retain storage through other references even after the process closes its descriptor. On such systems, inspect the filesystem's own space and snapshot tools as the next step.

## 4. Resolve the real service carefully

For a production incident, record the process identity, device, inode, descriptor, and application before changing anything. A process can own many unrelated files. Map it to the service or container that manages its lifecycle.

Use the application's documented log-reopen or rotation mechanism when available. A reviewed service restart can release descriptors, but it also interrupts that service. Recheck client behavior, lsof, and filesystem usage after the action. If several processes hold the same file, all relevant references must close before its storage is eligible for release.

Avoid truncating an arbitrary descriptor under `/proc`. That changes the file data held by the application and can damage an active workload. Removing a filename also does not undo a deletion. Preserve required incident evidence before taking an action that closes its last reference.

## 5. Prevent the same failure

Use the logging system's supported retention and rotation controls. For systemd journal storage, follow the [persistent journal retention guide](/posts/2026-11-07-systemd-journal-persistence-retention/). Application logs and container logging drivers have separate policies.

Add filesystem capacity monitoring alongside service checks. An alert should identify the affected mount and lead to a runbook that starts with evidence collection. After recovery, record what held the storage, which action released it, and whether the retention configuration needs correction.

## Official references

- [GNU Coreutils FAQ on df and du differences](https://www.gnu.org/software/coreutils/faq/coreutils-faq.html)
- [GNU Coreutils disk usage commands](https://www.gnu.org/software/coreutils/manual/html_node/Disk-usage.html)
- [lsof upstream manual](https://github.com/lsof-org/lsof/blob/master/docs/manpage.md)
- [Linux unlink semantics](https://man7.org/linux/man-pages/man2/unlink.2.html)
