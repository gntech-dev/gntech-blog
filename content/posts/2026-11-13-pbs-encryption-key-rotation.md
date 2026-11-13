---
title: "Rotate a Proxmox Backup Encryption Key and Verify Both Restores"
description: "Rehearse a PBS encryption-key rotation using two snapshot generations and restore each with its matching key."
date: 2026-11-13T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, disaster-recovery, homelab]
keywords: [Proxmox Backup Server key rotation, PBS encryption keys, encrypted snapshot restore]
summary: "Record which encryption key belongs to each backup generation and test both restores before relying on the rotation."
cover:
  image: "/images/posts/pbs-key-rotation/featured.webp"
  alt: "Brass and brushed steel USB drives on a lit workbench beside a backup appliance."
  caption: "AI-generated editorial artwork."
  relative: false
---

After an encryption-key rotation, the latest backup can restore successfully while an older recovery point is already out of reach. The old snapshot still needs its original key. This drill makes two encrypted snapshots and tests a restore on each side of the cutover.

This is a file-level companion to the [off-site recovery exercise in Part 10](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/). It uses the PBS 4.2 command-line client, a lab namespace and disposable files. The results are expectations for your lab.

![The pre-rotation snapshot needs key A and the post-rotation snapshot needs key B. The recovery kit keeps both keys.](/images/posts/pbs-key-rotation/key-generations.svg)

## 1. Decide what changes at cutover

A new client-side key protects future snapshots written with it. Older snapshots keep their original encryption. Changing the password on a key file with `key change-passphrase` changes how that file is unlocked while retaining the underlying backup key.

PBS includes the encryption key when computing encrypted chunk digests. Identical content encrypted under two different keys therefore has different chunk IDs. Allow capacity and upload time for the first backup with the new key, including any off-site replication. See the [PBS technical overview](https://pbs.proxmox.com/docs/technical-overview.html#encrypted-chunks).

For this rehearsal, use a separate backup group for each generation. That makes the boundary visible and avoids relying on reuse from the previous snapshot in the original group. The group names in this example belong to the standalone client. For scheduled Proxmox VE jobs, review the [PBS storage configuration](https://pve.proxmox.com/pve-docs/chapter-pvesm.html#storage_pbs) and rehearse the change with a test guest and a separate target namespace or storage entry.

## 2. Write and identify both generations

Install the PBS client on a Linux lab host. Create a disposable namespace called `rotation-drill` on a lab PBS datastore. Use a writer with `DatastoreBackup` and a separate restore user with `DatastoreReader` on that namespace. Use a trusted TLS certificate or configure the client with a fingerprint verified independently. The repository below is a placeholder and the client can prompt for the account password and key passphrases.

```bash
set -e
umask 077
work="$(mktemp -d)"
writer='lab-writer@pbs@pbs-lab.example:lab-store'
ns='rotation-drill'
run_id="rotate-$(date -u +%Y%m%dT%H%M%SZ)"

for generation in a b; do
  mkdir "$work/input-$generation"
  printf '%s\n' "Rotation fixture $run_id generation $generation" \
    > "$work/input-$generation/marker.txt"
  (cd "$work/input-$generation" && sha256sum marker.txt) \
    > "$work/$generation.sha256"

  proxmox-backup-client key create "$work/key-$generation.json"
  proxmox-backup-client key show "$work/key-$generation.json"
  proxmox-backup-client backup "fixture.pxar:$work/input-$generation" \
    --backup-type host --backup-id "$run_id-$generation" \
    --repository "$writer" --ns "$ns" \
    --keyfile "$work/key-$generation.json" --crypt-mode encrypt \
    --change-detection-mode legacy
  proxmox-backup-client snapshot list "host/$run_id-$generation" \
    --repository "$writer" --ns "$ns"
done
```

For each generation, record the complete snapshot path, key fingerprint from `key show`, fixture checksum and location of the key in the recovery kit. Confirm the fingerprints differ. Store both password-protected key files and make sure the operator can retrieve their passphrases. Keep key material out of the inventory and terminal transcripts.

## 3. Restore each generation from the recovery copy

Use a fresh recovery host and the reader account. If the lab uses sync, wait for both groups to arrive and enter the destination repository and namespace. Use the exact snapshot paths from that copy. Create a private working directory on disposable encrypted storage, then copy the two key files and checksum files into it from the recovery materials.

```bash
set -e
umask 077
recovery="$(mktemp -d)"
printf 'Copy key-a.json, key-b.json, a.sha256 and b.sha256 into %s\n' "$recovery"
```

After copying the files, run the following in the same shell. Confirm the displayed key fingerprints against the inventory before starting either restore.

```bash
read -r -p 'Recovery repository (reader account): ' reader
read -r -p 'Recovery namespace: ' ns
read -r -p 'Snapshot path before rotation: ' before
read -r -p 'Snapshot path after rotation: ' after

chmod 600 "$recovery/key-a.json" "$recovery/key-b.json"
proxmox-backup-client key show "$recovery/key-a.json"
proxmox-backup-client key show "$recovery/key-b.json"
read -r -p 'Type YES after matching both fingerprints: ' confirmed
test "$confirmed" = YES

proxmox-backup-client restore "$before" fixture.pxar "$recovery/restored-a" \
  --repository "$reader" --ns "$ns" --keyfile "$recovery/key-a.json"
(cd "$recovery/restored-a" && sha256sum -c "$recovery/a.sha256")

proxmox-backup-client restore "$after" fixture.pxar "$recovery/restored-b" \
  --repository "$reader" --ns "$ns" --keyfile "$recovery/key-b.json"
(cd "$recovery/restored-b" && sha256sum -c "$recovery/b.sha256")
```

Expect `marker.txt: OK` twice. Record both results with the destination and exact snapshot paths. If a snapshot is missing, check the sync filters and destination namespace. If the client rejects a key, verify the inventory entry and distinguish a passphrase failure from a key mismatch. If a checksum fails, stop and check that the expected checksum came from the source generation.

## 4. Keep the old generation recoverable

Treat the first successful backup with key B as the beginning of the overlap. Keep key A and its recovery instructions until every retained snapshot that depends on it is gone, including off-site, tape or exported copies. Review retention and sync filters for both groups, and check available datastore capacity after the first new-key backup.

If the cutover fails, pause the new lab job and preserve both generations. Where the old key remains trusted, you can resume the previous configuration while diagnosing the new target. Keep any snapshots already made with the new key and retain that key as well. If the old key may have been exposed, handle its retention and access as part of the incident rather than returning it to routine use.

Return the key media to custody after the drill. Dispose of the recovery workspace according to your lab storage policy and let the lab owner remove the two test groups under the lab retention policy.

## References

- [Proxmox Backup Client usage and encryption](https://pbs.proxmox.com/docs/backup-client.html#encryption)
- [Proxmox Backup Client command reference](https://pbs.proxmox.com/docs/proxmox-backup-client/man1.html)
- [Proxmox Backup Server user management and roles](https://pbs.proxmox.com/docs/user-management.html)
