---
title: "Proxmox Cloud-Init VM Templates — Automated Virtual Machine Deployment"
description: "Create reusable Proxmox VM templates with cloud-init for automated OS configuration. Step-by-step guide with Ubuntu cloud images, user setup, SSH keys, and CI-driven cloning."
date: 2026-05-16T07:00:00-04:00
tags:
  - proxmox
  - automation
  - linux
  - devops
  - homelab
keywords:
  - Proxmox cloud-init VM template automation
  - Proxmox Ubuntu cloud image template
  - Proxmox automated VM deployment
  - cloud-init Proxmox user configuration
  - Proxmox VM template creation script
  - Proxmox qm cloud-init guide
  - Proxmox VM clone from template
summary: "Create reusable Proxmox VM templates with cloud-init to deploy Ubuntu and Debian VMs in under 60 seconds. Covers image preparation, cloud-init user/SSH/package config, template creation, and CLI cloning."
canonical: "https://gntech.dev/posts/proxmox-cloudinit-vm-templates/"
---

If you run Proxmox VE, you've spun up a VM from an ISO at least once.
Maybe dozens of times. Boot the ISO, click through the installer, set a
hostname, create a user, wait for updates, install QEMU Guest Agent,
shut down, convert to template — forty-five minutes per VM.

Forty-five minutes, and you get one VM. Clone ten VMs for a testing
environment and you've burned a full work day on installation.

Cloud-init eliminates this. You prepare one template image, define your
OS configuration in YAML, and Proxmox applies it automatically on first
boot. New VMs deploy in 30-60 seconds with SSH keys, users, packages,
and network config pre-configured.

This guide covers the exact process: downloading cloud images, creating
Proxmox templates, configuring cloud-init user data, and cloning VMs
from the CLI. The result is a repeatable pipeline that turns VM
deployment into a one-liner.

---

## What Cloud-Init Does in Proxmox

Cloud-init is the industry standard for initializing cloud instances. It
runs on first boot and applies configuration from a data source — in
Proxmox's case, a small CD-ROM with YAML files that Proxmox generates
from the VM's cloud-init settings.

Proxmox's cloud-init support covers:

- **User setup:** Username, password, SSH authorized keys
- **Hostname:** Set per-VM hostname automatically
- **Network:** Static IP, DHCP, VLAN, DNS, gateway
- **Packages:** Install packages on first boot
- **Commands:** Run arbitrary shell commands on first boot
- **DNS:** Custom nameservers and search domains

The advantage over traditional ISO installs: you never touch an
installer dialog. The OS boots, cloud-init reads the config from the
attached CD-ROM, and the VM is ready in 30 seconds.

---

## Step 1: Download a Cloud-Init Ready Image

Proxmox works best with official Ubuntu and Debian cloud images. These
are compact, optimized for first-boot initialization, and include
cloud-init pre-installed.

**Ubuntu 24.04 LTS (Noble) — recommended for most homelab VMs:**

```bash
# Download the official Ubuntu 24.04 cloud image
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img \
  -O /var/lib/vz/template/iso/ubuntu-24.04-cloudimg.img

# Debian 12 (Bookworm)
wget https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2 \
  -O /var/lib/vz/template/iso/debian-12-cloudimg.qcow2
```

These images are qcow2 format, 500-600 MB, and boot to a login prompt
with no configuration — that's where cloud-init takes over.

**Why cloud images instead of ISOs:**

| Aspect | Cloud Image | ISO Install |
|--------|------------|-------------|
| Size | ~500 MB | ~4 GB |
| First boot | 30-60 seconds | 15-45 minutes |
| Configuration | YAML (cloud-init) | Manual clicking |
| Repeatable | Yes | No |
| Clone-ready | Yes | No |

---

## Step 2: Create the Proxmox VM Template

With the cloud image downloaded, create a VM that doesn't boot yet,
import the disk, configure the cloud-init drive, and convert to a
template.

**Single script that does it all:**

```bash
#!/bin/bash
# create-proxmox-template.sh — run on Proxmox host
# Usage: ./create-proxmox-template.sh <vm-id> <vm-name> <image-path>

VM_ID=${1:-9000}
VM_NAME=${2:-ubuntu-2404-template}
IMAGE=${3:-/var/lib/vz/template/iso/ubuntu-24.04-cloudimg.img}
STORAGE=${4:-local-zfs}    # Change to match your storage name
BRIDGE=${5:-vmbr0}

# 1. Create VM with minimal hardware
qm create $VM_ID \
  --name $VM_NAME \
  --memory 2048 \
  --cores 2 \
  --cpu host \
  --net0 virtio,bridge=$BRIDGE \
  --agent enabled=1 \
  --ostype l26 \
  --serial0 socket \
  --vga serial0 \
  --boot order=scsi0 \
  --scsihw virtio-scsi-pci

# 2. Import the cloud image disk
qm importdisk $VM_ID $IMAGE $STORAGE

# 3. Attach the imported disk as scsi0
qm set $VM_ID \
  --scsi0 $STORAGE:vm-$VM_ID-disk-0,discard=on,ssd=1

# 4. Add cloud-init CD-ROM drive
qm set $VM_ID --ide2 $STORAGE:cloudinit

# 5. Resize disk to a useful size (default cloud images are ~2-4 GB)
qm resize $VM_ID scsi0 32G

# 6. Set first-boot DHCP for cloud-init
qm set $VM_ID --ipconfig0 ip=dhcp

# 7. Set default user and SSH key
qm set $VM_ID \
  --ciuser gntech \
  --sshkeys ~/.ssh/authorized_keys

# 8. Convert to template
qm template $VM_ID

echo "Template $VM_NAME (ID: $VM_ID) created successfully"
```

**What each step does:**

- `qm create` — Registers the VM with minimal hardware (2 cores, 2 GB
  RAM, virtio NIC, QEMU Agent, serial console)
- `qm importdisk` — Converts the qcow2 cloud image into a Proxmox
  volume on your chosen storage
- `qm resize` — Grows the disk from the tiny default (2-4 GB) to 32 GB
  (or whatever you need — 32 GB is enough for most Docker hosts)
- `--ide2 ...:cloudinit` — Adds a cloud-init config drive (Proxmox
  writes cloud-init YAML files here at clone time)
- `qm set --ciuser/--sshkeys` — Sets default user and SSH key
- `qm template` — Converts the VM into a read-only template

Run it:

```bash
chmod +x create-proxmox-template.sh
./create-proxmox-template.sh 9000 ubuntu-2404-template
```

After ~30 seconds, you have a template ready to clone.

**For a Debian 12 template:**

```bash
./create-proxmox-template.sh 9010 debian-12-template \
  /var/lib/vz/template/iso/debian-12-cloudimg.qcow2
```

---

## Step 3: Configure Cloud-Init Defaults

Before cloning, set sensible defaults that every VM gets unless you
override them. These are configured on the template itself and
inherited by all clones.

**Set these once on the template:**

```bash
# Set default user
qm set 9000 --ciuser gntech

# Set SSH public key (copy your host key)
qm set 9000 --sshkeys /root/.ssh/id_ed25519.pub

# Set DNS servers
qm set 9000 \
  --nameserver "10.0.20.1 1.1.1.1" \
  --searchdomain "homelab.internal"

# Set default IP configuration (DHCP)
qm set 9000 --ipconfig0 ip=dhcp

# Set a default password (optional — use SSH keys instead)
qm set 9000 --cipassword "changeme"    # Change on every clone!
```

**SSH keys are the better approach:** Set `--cipassword` to a temporary
password and rely on SSH keys for access. Remove the password entirely
after the first SSH login with:

```bash
sudo passwd -d gntech
```

---

## Step 4: Clone VMs from the Template

With the template ready, deploying a new VM is a single command:

**Basic clone with DHCP:**

```bash
# Deploy a new VM with hostname "docker-node-1"
qm clone 9000 100 --name docker-node-1 --full

# Assign cloud-init hostname
qm set 100 --ciuser gntech --sshkeys /root/.ssh/id_ed25519.pub

# Start the VM
qm start 100
```

**Clone with static IP and custom hostname:**

```bash
qm clone 9000 101 --name web-gateway --full

qm set 101 \
  --ciuser gntech \
  --sshkeys /root/.ssh/id_ed25519.pub \
  --ipconfig0 ip=10.0.20.50/24,gw=10.0.20.1 \
  --nameserver "10.0.20.1 1.1.1.1" \
  --searchdomain "homelab.internal"

qm start 101
```

**Clone with extra CPU/memory and a second network interface:**

```bash
qm clone 9000 102 --name database-node --full

qm set 102 \
  --memory 8192 \
  --cores 4 \
  --ciuser gntech \
  --sshkeys /root/.ssh/id_ed25519.pub \
  --ipconfig0 ip=10.0.20.60/24,gw=10.0.20.1 \
  --ipconfig1 ip=10.0.30.60/24,gw=10.0.30.1 \
  --net1 virtio,bridge=vmbr1

qm start 102
```

The `--full` flag creates a full clone (complete copy of the disk).
Linked clones (`--linked`) use the template as a backing store and save
disk space, but require the template to stay in place.

---

## Step 5: Advanced Cloud-Init User Data (Custom YAML)

For more complex provisioning, define a custom cloud-init YAML snippet.
Proxmox writes this to the cloud-init CD-ROM on clone.

**Custom cloud-init config with package installation:**

```yaml
# Save as /var/lib/vz/snippets/docker-host.yaml
#cloud-config
package_update: true
package_upgrade: true
packages:
  - docker.io
  - docker-compose-v2
  - qemu-guest-agent
  - htop
  - tree
  - ufw
  - fail2ban

runcmd:
  - systemctl enable --now docker
  - systemctl enable --now qemu-guest-agent
  - usermod -aG docker gntech
  - ufw allow OpenSSH
  - ufw --force enable
  - echo "Provisioning complete" > /etc/motd

final_message: "Cloud-init finished in $UPTIME seconds"
```

Apply it to a clone:

```bash
qm clone 9000 120 --name docker-worker-1 --full

# Point to the custom cloud-init snippet
qm set 120 \
  --ciuser gntech \
  --sshkeys /root/.ssh/id_ed25519.pub \
  --cicustom "user=local:snippets/docker-host.yaml"

qm start 120
```

The `--cicustom` flag overrides the default cloud-init user data with
your custom YAML. Proxmox reads it from the local storage snippet path.

**Another example — a web server template:**

```yaml
# Save as /var/lib/vz/snippets/webserver.yaml
#cloud-config
package_update: true
packages:
  - nginx
  - certbot
  - python3-certbot-nginx
  - qemu-guest-agent

write_files:
  - path: /etc/nginx/sites-available/default
    content: |
      server {
          listen 80 default_server;
          server_name _;
          return 301 https://$host$request_uri;
      }

runcmd:
  - systemctl enable --now nginx
  - systemctl enable --now qemu-guest-agent
  - nginx -t && systemctl restart nginx
```

Deploy a web server in one command:

```bash
qm clone 9000 130 --name webserver-1 --full
qm set 130 \
  --ciuser gntech \
  --sshkeys /root/.ssh/id_ed25519.pub \
  --cicustom "user=local:snippets/webserver.yaml" \
  --ipconfig0 ip=10.0.20.70/24,gw=10.0.20.1
qm start 130
```

---

## Step 6: Verification — Confirm Cloud-Init Worked

After the VM boots, SSH in with your key and verify cloud-init
completed successfully:

```bash
# Wait for cloud-init to finish
ssh gntech@10.0.20.50 "cloud-init status --wait"

# Check the cloud-init output log
ssh gntech@10.0.20.50 "sudo cat /var/log/cloud-init-output.log"

# Verify packages were installed
ssh gntech@10.0.20.50 "docker --version"

# Verify the user and SSH key work
ssh gntech@10.0.20.50 "whoami && id"

# Check disk layout
ssh gntech@10.0.20.50 "lsblk"

# Verify QEMU Agent is running (check from Proxmox host)
qm agent 100 ping
```

If cloud-init fails, check these logs on the VM:

```bash
/var/log/cloud-init.log       # Cloud-init module execution log
/var/log/cloud-init-output.log  # Full output of all cloud-init stages
```

**Common failures and fixes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| VM boots to login prompt but SSH fails | Cloud-init generated SSH host keys but didn't apply user config | Check `cloud-init status --wait`. Reboot and retry |
| Packages not installed | No network at boot time | Set `--nameserver` correctly. Use `package_update: true` in custom config |
| Static IP not applied | Cloud-init networking conflicts with Netplan | Use Proxmox `--ipconfig0` — don't also configure Netplan in cloud-init |
| "No cloud-init data source found" | Missing cloud-init drive | Verify `qm set VM_ID --ide2 STORAGE:cloudinit` on the template |

---

## Step 7: Automation — A Deployment Script

For daily use, wrap the clone-and-configure steps into a script:

```bash
#!/bin/bash
# deploy-vm.sh — clone a template and configure cloud-init
# Usage: ./deploy-vm.sh <template-id> <new-vm-id> <hostname> <ip/cidr> <gateway>

TEMPLATE_ID=${1:-9000}
VM_ID=${2:-200}
HOSTNAME=${3:-test-vm}
IP=${4:-dhcp}
GATEWAY=${5:-}

echo "Cloning template $TEMPLATE_ID to VM $VM_ID ($HOSTNAME)..."
qm clone $TEMPLATE_ID $VM_ID --name $HOSTNAME --full

if [ "$IP" = "dhcp" ]; then
  qm set $VM_ID \
    --ciuser gntech \
    --sshkeys /root/.ssh/authorized_keys \
    --ipconfig0 ip=dhcp
else
  qm set $VM_ID \
    --ciuser gntech \
    --sshkeys /root/.ssh/authorized_keys \
    --ipconfig0 ip=${IP},gw=${GATEWAY}
fi

qm start $VM_ID
echo "VM $HOSTNAME (ID: $VM_ID) started. Waiting for cloud-init..."

# Wait for the VM to get an IP and cloud-init to finish
sleep 15

# Get VM IP from Proxmox
VM_IP=$(qm guest exec $VM_ID -- hostname -I 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
if [ -n "$VM_IP" ]; then
  echo "VM IP: $VM_IP"
  echo "SSH: ssh gntech@$VM_IP"
else
  echo "VM started. Get IP from Proxmox web UI or DHCP leases."
fi
```

One-command deployment:

```bash
./deploy-vm.sh 9000 200 docker-node-1 dhcp
./deploy-vm.sh 9000 201 web-server-1 "10.0.20.71/24" "10.0.20.1"
./deploy-vm.sh 9000 202 database-1 "10.0.20.72/24" "10.0.20.1"
```

Three VMs deployed in under 2 minutes. Compare that to three ISO
installs at 45 minutes each.

---

## Step 8: Terraform Integration (Optional)

For the full infrastructure-as-code experience, manage templates with
Terraform and the Proxmox provider:

```hcl
# main.tf
provider "proxmox" {
  pm_api_url = "https://10.0.20.30:8006/api2/json"
  pm_user    = "root@pam"
}

resource "proxmox_vm_qemu" "docker_node" {
  name        = "docker-node-${count.index + 1}"
  target_node = "srv1"
  clone       = "ubuntu-2404-template"
  full_clone  = true
  count       = 3

  cores   = 4
  memory  = 8192
  agent   = 1

  disk {
    size    = "64G"
    type    = "scsi"
    storage = "local-zfs"
  }

  network {
    model  = "virtio"
    bridge = "vmbr0"
  }

  # Cloud-init settings
  ciuser      = "gntech"
  sshkeys     = file("~/.ssh/id_ed25519.pub")
  ipconfig0   = "ip=10.0.20.${80 + count.index}/24,gw=10.0.20.1"
  nameserver  = "10.0.20.1"
  searchdomain = "homelab.internal"
}
```

Apply:

```bash
terraform init
terraform apply -auto-approve
# Creates 3 Docker nodes in ~90 seconds
```

---

## Performance Tips for Proxmox Templates

**Disk format considerations:**

- **Full clones** — Independent copy. Slower to create, no dependency
  on template. Best for production VMs.
- **Linked clones** — COW (copy-on-write) on ZFS. Instant creation,
  saves disk space. Template must stay on the same storage.

Choose linked clones when you're spinning up ephemeral test
environments. Use full clones for production services.

**Template location:**

Store templates on fast storage (NVMe or SSD ZFS pool). Cloning from
spinning disks is significantly slower.

```bash
# Move template to fast storage
qm move_disk 9000 scsi0 local-nvme --delete
```

**Minimize template disk size:**

Cloud images include a swap partition and some bloat. Create a lean
template:

```bash
# Inside the template before converting:
# Remove cloud-init artifacts
sudo cloud-init clean

# Remove machine ID (will be regenerated on clone)
sudo rm -f /etc/machine-id
sudo truncate -s 0 /etc/machine-id

# Clean package cache
sudo apt clean
sudo apt autoremove --purge

# Zero free space for better compression
sudo dd if=/dev/zero of=/zerofile bs=1M || true
sudo rm -f /zerofile
```

After cleanup, consider a fresh template:

```bash
# Delete old template and rebuild
qm destroy 9000
./create-proxmox-template.sh 9000 ubuntu-2404-template
```

---

## Summary: The Cloud-Init Template Workflow

```
Download cloud image → Create VM → Import disk → Configure
cloud-init → Convert to template

Then on demand:
Clone template → Set IP/hostname → Power on → SSH in (60 seconds)
```

**Key takeaways:**

1. **One template, unlimited VMs** — Download once, clone endlessly. No
   more ISO installs.
2. **Cloud-init handles first-boot config** — Users, SSH keys, packages,
   network, hostname — all automated.
3. **Custom snippets for role-specific setup** — Docker hosts, web
   servers, databases — define once in a YAML snippet, apply to any
   clone.
4. **Full CLI automation** — Script the entire workflow. `deploy-vm.sh`
   turns VM creation into a single command.
5. **Terraform-ready** — Cloud-init + Proxmox provider gives you
   infrastructure-as-code for your homelab.

Every homelab running Proxmox should have at least one cloud-init
template. Deploying a new VM should take seconds, not the time it takes
to watch an installer progress bar.

The template creation script and deploy script from this guide will be
on the GnTech GitHub repo — grab them, customize the user and SSH key,
and you're deploying VMs in under a minute.
