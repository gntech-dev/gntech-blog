---
title: "Test Proxmox Backup Key Recovery Without Primary SSO"
description: "Use a clean recovery host, a scoped local PBS login, and an offline key kit to restore and verify an encrypted test file."
date: 2026-11-12T00:00:00-04:00
draft: false
ShowToc: true
tags: [proxmox, backup, disaster-recovery, homelab]
keywords: [Proxmox Backup Server encryption key recovery, PBS restore drill, offline recovery kit]
summary: "Prove that a recovery operator can reach an encrypted snapshot and decrypt it when the primary identity service is unavailable."
cover:
  image: "/images/posts/pbs-offline-key-recovery/featured.webp"
  alt: "An operator reaches for a USB drive in an open lockbox beside a backup appliance."
  caption: "AI-generated editorial artwork."
  relative: false
---

You can have a healthy off-site backup and still be unable to restore it. The operator might need a directory login to reach the server, or the password manager holding the encryption passphrase might require the same unavailable SSO. This drill tests those dependencies with a one-file archive and a fresh recovery host.

[Part 10 of the GNTECH Infrastructure Series](/posts/2026-11-04-gntech-infrastructure-part-10-backup-disaster-recovery/) covers restoring and booting a VM from an off-site copy. Here the finish line is narrower: an operator retrieves the original encryption key through an independent path and restores bytes that match a known checksum. The procedure targets the PBS 4.2 client and a disposable namespace. Results below are expected observations for the reader to verify.

![The recovery host reads an encrypted snapshot from off-site PBS using a local credential and decrypts it using the matching key and passphrase from an offline kit.](/images/posts/pbs-offline-key-recovery/recovery-paths.svg)

## 1. Prepare the two paths

Use two disposable Linux VMs with `proxmox-backup-client` installed, one for backup and one for recovery. On the PBS instance that represents your surviving off-site server, create a lab datastore or namespace. This lab writes its test snapshot directly to that server. If your recovery plan uses PBS sync, repeat the recovery half against the actual synced copy once it arrives.

| Dependency | Prepare for the drill |
| --- | --- |
| Snapshot access | Grant the backup account `DatastoreBackup` and a separate local PBS realm account `DatastoreReader`, scoped to the lab namespace. Check that the reader can read a snapshot owned by the writer. |
| Server identity | Have the trusted CA or independently recorded PBS TLS fingerprint available on the recovery host. Record the host, port, datastore and namespace in the recovery notes. |
| Key custody | Assign someone to retrieve the encrypted key file and its passphrase through the approved recovery process. Check that access to the kit, including any second custodian, works without primary SSO. |
| Network and console | Use a fresh recovery VM with local console access and a path to PBS. Keep the primary identity provider and ordinary SSO-dependent vault unavailable from this VM. Include DNS, VPN and certificate trust in that dependency check. |

Leave production identity services running. Apply the isolation only to the recovery VM. Use a fresh local user on it with no default PBS encryption key, no prior PBS session and no mounted source disk.

## 2. Create a disposable encrypted snapshot

On the backup VM, use the account with write permission. The hostname, datastore and namespace below are placeholders. Use normal CA validation or set `PBS_FINGERPRINT` in the shell to the independently verified value for a self-signed server before connecting.

```bash
set -e
umask 077
work="$(mktemp -d)"
repo='lab-writer@pbs@pbs-recovery.example:lab-store'
namespace='key-drill'
backup_id="key-drill-$(date -u +%Y%m%dT%H%M%SZ)"

mkdir "$work/input"
printf '%s\n' "PBS recovery fixture for $backup_id" > "$work/input/fixture.txt"
(cd "$work/input" && sha256sum fixture.txt) > "$work/fixture.sha256"

proxmox-backup-client key create "$work/original.json"
proxmox-backup-client backup "drill.pxar:$work/input" \
  --backup-type host --backup-id "$backup_id" \
  --repository "$repo" --ns "$namespace" \
  --keyfile "$work/original.json" --crypt-mode encrypt

proxmox-backup-client snapshot list "host/$backup_id" \
  --repository "$repo" --ns "$namespace"
```

Choose a lab passphrase at the key creation prompt. Record the exact `host/<id>/<timestamp>` snapshot path from the listing and copy `fixture.sha256` to the drill notes. Put a copy of `original.json` in the offline kit. Store the passphrase according to your recovery policy and exercise the actual retrieval process. The snapshot path and fixture checksum can be passed separately from the secrets. For this drill, leave the original VM and its copy of the key inaccessible to the recovery operator.

## 3. Prove that the correct key matters

On the clean recovery VM, start the clock before retrieving anything. Enter the local reader's password at the client prompt. Enter your real lab repository and snapshot values when prompted below, and use the same CA or verified fingerprint procedure as on the writer.

```bash
set -e
umask 077
recovery="$(mktemp -d)"
read -r -p 'PBS repository (lab reader): ' repo
read -r -p 'PBS namespace: ' namespace
read -r -p 'Snapshot path (host/id/timestamp): ' snapshot

proxmox-backup-client snapshot files "$snapshot" \
  --repository "$repo" --ns "$namespace"

proxmox-backup-client key create "$recovery/wrong.json"
if proxmox-backup-client restore "$snapshot" drill.pxar "$recovery/wrong" \
  --repository "$repo" --ns "$namespace" --keyfile "$recovery/wrong.json"; then
  printf '%s\n' 'Unexpected success with the wrong key. Stop and inspect the archive.' >&2
  exit 1
fi
```

Check that the listing shows `drill.pxar` as encrypted. For the negative control, enter the correct passphrase for the newly generated **wrong** key. Record the actual restore error. An authentication, TLS or connectivity error makes the negative control inconclusive. Fix access and repeat before proceeding. If the first restore leaves an output directory behind, leave it separate from the positive test.

## 4. Recover the key and verify the file

Retrieve `original.json` and its passphrase through the offline process. Copy the file to `$recovery/original.json` with owner-only permissions, and put the trusted fixture checksum in `$recovery/fixture.sha256`. Run the restore into a new path.

```bash
chmod 600 "$recovery/original.json"
proxmox-backup-client restore "$snapshot" drill.pxar "$recovery/restored" \
  --repository "$repo" --ns "$namespace" --keyfile "$recovery/original.json"

(cd "$recovery/restored" && sha256sum -c "$recovery/fixture.sha256")
```

Expect `fixture.txt: OK`. Record the snapshot, client version, wrong-key error, checksum result and elapsed time from the start of retrieval. Record where the operator got stuck without including any secret values. If the restore fails with the recovered key, compare the snapshot and kit identifiers first. Check for an older snapshot that predates a key rotation and for a passphrase that belongs to a different key file.

After the drill, return the media to custody and dispose of the test VMs or remove their temporary files according to the lab's storage policy. Ordinary deletion can leave copies in VM snapshots and backups, so use disposable encrypted storage for the recovery workspace and exclude it from routine backups. Ask the lab datastore owner to remove the disposable snapshot under the lab retention policy. Repeat the drill after changes to keys, custodians, TLS trust or access routes.

## References

- [Proxmox Backup Client usage and client-side encryption](https://pbs.proxmox.com/docs/backup-client.html)
- [Proxmox Backup Client command reference](https://pbs.proxmox.com/docs/proxmox-backup-client/man1.html)
- [PBS authentication realms and datastore roles](https://pbs.proxmox.com/docs/user-management.html)
- [PBS namespace permissions](https://pbs.proxmox.com/docs/storage.html#namespace-permissions)
