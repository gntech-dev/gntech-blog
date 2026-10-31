---
title: "Proxmox Cloud-Init VM Templates — Automated Virtual Machine Deployment"
description: "Create an Ubuntu cloud-image template, clone it with an SSH public key, and verify first-boot configuration before adding custom user data."
date: 2026-05-16T07:00:00-04:00
lastmod: 2026-10-31
draft: false
tags: [proxmox, automation, linux, devops, homelab]
keywords: [Proxmox cloud-init template, Ubuntu cloud image, qm clone, cloud-init SSH keys]
summary: "Build an unbooted cloud-image template and verify a disposable clone before extending provisioning."
---

Cloud images let you prepare a reusable guest without repeating an ISO installation. Start with one disposable clone and working SSH access. Add packages and application provisioning after that baseline succeeds.

## Verification status

| Area | Evidence and limits |
|---|---|
| Technical review | Reviewed against the official references below on October 31, 2026. |
| Shell examples | Syntax checked with Bash; commands were not executed against PVE. |
| Runtime | Disk import, cloning, SSH access, and guest initialization remain untested for this revision. |
| Timing | No deployment-time guarantee is claimed. |

## 1. Prepare the inputs

Run PVE commands as root on the intended node. Choose two unused IDs; the example uses template 9100 and test clone 9101. Check the cluster inventory, including containers, before proceeding.

Choose storage that supports VM disks, confirm free capacity, and select a bridge connected to your test network with DHCP. The examples use `local-lvm` and `vmbr0`; change them to match your host.

Download an official Ubuntu 24.04 AMD64 cloud image from [Ubuntu cloud images](https://cloud-images.ubuntu.com/noble/current/). Verify it against the publisher's authenticated checksum information and retain its exact filename and checksum for reproducibility. Place the verified image at the path used below.

Copy only your administrator workstation's SSH **public** key to `/root/cloud-template-admin.pub` on PVE. Keep the private key on the workstation. Do not copy the host's entire `authorized_keys` file into every guest.

## 2. Create an unbooted template

The following block runs in a Bash subshell and stops on an error. It creates new resources; review the IDs, storage, bridge, and image path first.

```bash
(
set -euo pipefail
template_id=9100
disk_store=local-lvm
bridge=vmbr0
image=/var/lib/vz/template/iso/ubuntu-24.04-cloudimg.img

test -s "$image"
pvesm status --storage "$disk_store"
ip link show "$bridge"

# qm create refuses an existing guest ID.
qm create "$template_id" --name ubuntu-2404-template \
  --memory 2048 --cores 2 --ostype l26 \
  --net0 "virtio,bridge=$bridge" --scsihw virtio-scsi-pci
qm set "$template_id" --scsi0 "$disk_store:0,import-from=$image"
qm set "$template_id" --ide2 "$disk_store:cloudinit"
qm set "$template_id" --boot order=scsi0 --serial0 socket --vga serial0
qm resize "$template_id" scsi0 32G
qm set "$template_id" --ipconfig0 ip=dhcp
qm config "$template_id"
qm template "$template_id"
)
```

Import-and-attach avoids guessing the allocated volume name. The 32 GiB disk size is an example; select a size larger than the image's virtual disk. Guest filesystem expansion must be checked after boot.

Keep this base image unbooted. If a command fails, inspect the partial VM and task log before retrying. Do not run an automatic destroy-and-rebuild command against an ID that may already contain useful data.

See [PVE cloud-init support](https://github.com/proxmox/pve-docs/blob/master/qm-cloud-init.adoc) and [VM management](https://github.com/proxmox/pve-docs/blob/master/qm.adoc) for supported options on your release.

## 3. Configure a full clone before starting it

This block assumes the template above exists. It uses DHCP and the one public key prepared earlier. It intentionally does not start the clone until you inspect its generated configuration.

```bash
(
set -euo pipefail
template_id=9100
clone_id=9101
public_key=/root/cloud-template-admin.pub

test -s "$public_key"
ssh-keygen -lf "$public_key"
qm clone "$template_id" "$clone_id" --name cloudinit-test --full 1
qm set "$clone_id" --ciuser gnolasco --sshkeys "$public_key" \
  --ipconfig0 ip=dhcp
qm cloudinit dump "$clone_id" user
qm cloudinit dump "$clone_id" network
qm config "$clone_id"
)
```

Confirm the generated user and public key, the bridge, DHCP configuration, and boot disk. Then start the new guest:

```bash
qm start 9101
```

Find its address in DHCP leases or console output. Check its SSH host-key fingerprint through a trusted route before accepting it on the workstation. A serial console can show boot errors but does not provide a password login when no password was configured.

Full clones have independent disks; linked clones depend on their base. Choose deliberately using the installed release's storage and clone documentation.

## 4. Verify from inside the guest

Connect from your workstation using the matching private key and the guest's actual address. Run these commands **inside the guest**, not on PVE:

```bash
cloud-init status --wait
cloud-init status --long
whoami
id
lsblk
df -h /
sudo tail -n 80 /var/log/cloud-init-output.log
```

Confirm the intended user exists, initialization finished without unresolved errors, and disk/filesystem capacity is appropriate. Review [cloud-init debugging](https://docs.cloud-init.io/en/latest/howto/debugging.html) if access or configuration fails.

Enabling the PVE guest-agent option alone does not install the guest agent. If you need it, install and configure the guest package, enable the PVE option, and verify communication separately.

Do not set a shared template password or delete a user's password as an SSH-hardening shortcut. Inspect the generated configuration and test authentication on a disposable clone.

## 5. Add custom user data only after the baseline works

A `cicustom user=...` file **replaces** PVE's generated user data. It does not automatically merge package settings with the user and SSH key supplied by `--ciuser` and `--sshkeys`.

Use `qm cloudinit dump 9101 user` as a starting point. Preserve the intended account and public-key configuration when building a complete custom document. Validate it with the cloud-init version used by the image, then test a fresh disposable clone.

Snippet storage must support the snippets content type, and the file must be available on every node where the VM may start or migrate. Network and metadata overrides are separate choices. Rebooting an already initialized guest is not proof that a first-boot module will run again.

Keep provisioning small at first. Record package failures and confirm access before enabling firewalls or adding applications. For configuration beyond first boot, see the [Ansible homelab guide](/posts/2026-05-27-ansible-homelab-automation/).

## Recovery and maintenance

Keep the verified image and build inputs so you can create a new template under a new unused ID. Test its clone before retiring the previous template. Inspect dependencies before removing a base used by linked clones.

Record the PVE version, image checksum, template settings, generated cloud-init data, and clone verification results. Avoid filling the guest disk with zeroes or deleting existing templates as routine cleanup.

## Continue reading

- [Proxmox bridges and VLANs](/posts/2026-05-08-proxmox-networking-bridges-vlans/) — Check where the clone's network connects.
- [PBS setup and first restore](/posts/2026-05-08-proxmox-backup-server-setup/) — Test recovery alongside deployment.
