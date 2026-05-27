---
title: "Proxmox GitOps — Terraform IaC for LXC and VM Automation"
description: "Automate Proxmox LXC and VM provisioning with Terraform/OpenTofu and GitOps — declarative config, remote state, and CI/CD pipelines for homelab infrastructure."
date: 2026-05-27T14:30:00-04:00
tags:
  - proxmox
  - terraform
  - devops
  - automation
  - homelab
keywords:
  - Proxmox Terraform OpenTofu IaC automation homelab
  - Proxmox GitOps pipeline LXC VM provisioning
  - Terraform Proxmox provider LXC container deployment
  - OpenTofu GitLab CI/CD infrastructure as code
  - Proxmox VM template creation GitOps workflow
  - Terraform remote state Proxmox infrastructure
  - declarative infrastructure management Proxmox homelab
summary: "Automate Proxmox LXC and VM provisioning using Terraform or OpenTofu with a GitOps pipeline — declarative infrastructure, remote state, and CI/CD from Git pushes."
canonical: "https://gntech.dev/posts/proxmox-terraform-gitops-iac/"
---

Manually creating LXC containers and VMs through the Proxmox web UI
works for a handful of servers, but once you cross twenty containers
across multiple VLANs, you need something repeatable. That is where
GitOps comes in: your infrastructure definition lives in Git, and
every push triggers an automated pipeline that applies the changes.

This guide covers the full stack: Proxmox API token creation,
Terraform/OpenTofu provider setup, LXC and VM resource definitions,
remote state management, and a CI/CD pipeline that turns git push
into deployed infrastructure.

All examples target Proxmox VE 8.x with Terraform 1.6+ or OpenTofu
1.6+. I recommend OpenTofu for homelabs — it is the fully open-source
fork with no licence changes to worry about.

---

## 1. Proxmox API Token for Terraform

Terraform needs API access to your Proxmox host or cluster. Create a
dedicated user and token so you can revoke access without touching
your root credentials.

```bash
pveum user add terraform@pve --comment "Terraform IaC"
pveum acl modify / -user terraform@pve -role Administrator
pveum user token add terraform@pve terraform-token --privsep false
```

The last command prints a token ID and secret. Save the secret
immediately — Proxmox will not show it again. Store it in your
password manager or encrypted vault.

For a more restricted setup, create a custom role with only the
permissions Terraform needs (VM.Allocate, Datastore.AllocateSpace,
Sys.Audit) instead of full Administrator.

---

## 2. Provider and Backend Configuration

The community provider `bpg/proxmox` is the most actively maintained
option and supports both LXC and QEMU resources.

Create `providers.tf`:

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.70"
    }
  }
}

provider "proxmox" {
  endpoint  = var.pm_api_url
  api_token = var.pm_api_token
  ssh {
    agent    = true
    node {
      name    = var.pm_node
      address = var.pm_node_ip
    }
  }
}
```

Create `terraform.tfvars` with your actual values (add to
`.gitignore`):

```hcl
pm_api_url      = "https://10.0.20.30:8006/api2/json"
pm_api_token    = "terraform@pve!terraform-token=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
pm_node         = "srv1"
pm_node_ip      = "10.0.20.30"
```

---

## 3. LXC Container with Declarative Config

Define an LXC container in `containers/web01/main.tf`:

```hcl
resource "proxmox_virtual_environment_container" "web01" {
  node_name = var.pm_node
  vm_id     = 210

  template {
    file_id = "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
  }

  startup  = true
  start_on_boot = true
  unprivileged  = true

  cpu {
    cores = 2
  }

  memory {
    dedicated = 1024
    swap      = 512
  }

  disk {
    datastore_id = "local-zfs"
    size         = 8
  }

  network {
    name   = "eth0"
    bridge = "vmbr0"
    ip     = "dhcp"
  }

  features {
    nesting = true
  }
}
```

For multiple similar containers, use a module:

```hcl
module "app_containers" {
  source = "./modules/lxc/"

  for_each = var.app_containers

  vm_id       = each.value.vm_id
  hostname    = each.key
  cores       = each.value.cores
  memory      = each.value.memory
  disk_size   = each.value.disk_size
  bridge      = each.value.bridge
  ip_address  = each.value.ip_address
  gateway     = each.value.gateway
}
```

---

## 4. VM Deployment from Template

For full VMs, first build a template with Packer, then clone it with
Terraform. This separates the image build (Packer) from the
deployment (Terraform).

Packer template snippet `proxmox-debian.pkr.hcl`:

```hcl
source "proxmox-iso" "debian" {
  proxmox_url              = var.pm_api_url
  username                 = var.pm_api_token_id
  token                    = var.pm_api_token_secret
  node                     = var.pm_node
  vm_name                  = "debian-13-template"
  template_description     = "Debian 13, generated {{ isotime \"2006-01-02\" }}"
  memory                   = 2048
  cores                    = 2
  cloud_init               = true
}
```

Terraform VM resource cloning the template:

```hcl
resource "proxmox_virtual_environment_vm" "app01" {
  node_name = var.pm_node
  vm_id     = 301
  name      = "app01"
  template  = "debian-13-template"

  cpu {
    cores  = 4
    type   = "host"
  }

  memory {
    dedicated = 4096
  }

  disk {
    datastore_id = "local-zfs"
    size         = 40
    file_format  = "raw"
  }

  network {
    bridge  = "vmbr0"
    model   = "virtio"
    vlan    = 20
  }

  agent {
    enabled = true
  }
}
```

---

## 5. Remote State — Required for GitOps

Local `terraform.tfstate` does not work in a GitOps pipeline because
every CI runner starts fresh. You need a remote backend.

Option A — S3-compatible (MinIO, garage):

```hcl
terraform {
  backend "s3" {
    bucket                      = "terraform-state"
    key                         = "proxmox/terraform.tfstate"
    region                      = "us-east-1"
    endpoint                    = "https://minio.gntech.dev"
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    use_path_style              = true
  }
}
```

Option B — HTTP backend (Gitea or GitLab):

```hcl
terraform {
  backend "http" {
    address        = "https://git.gntech.dev/api/packages/iac/terraform-state/proxmox"
    lock_address   = "https://git.gntech.dev/api/packages/iac/terraform-state/proxmox/lock"
    unlock_address = "https://git.gntech.dev/api/packages/iac/terraform-state/proxmox/lock"
  }
}
```

---

## 6. Repository Layout

```
iac/
├── environments/
│   ├── prod/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── terraform.tfvars       # gitignored
│   │   └── terraform.tfvars.example
│   └── staging/
│       ├── main.tf
│       ├── variables.tf
│       └── terraform.tfvars
├── modules/
│   ├── lxc/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── vm/
│       ├── main.tf
│       └── variables.tf
├── .github/workflows/  (or .gitea/workflows/)
├── providers.tf
└── README.md
```

Each environment has its own `.tfvars` with VLAN IDs, IP ranges, and
datastore paths specific to that environment.

---

## 7. Gitea Actions CI/CD Pipeline

A Gitea Actions workflow that validates, plans, and applies on push
to the `main` branch:

```yaml
name: Terraform Proxmox
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.0
      - name: Init and Validate
        run: |
          cd environments/prod
          terraform init -backend-config="address=${{ secrets.TF_HTTP_ADDRESS }}"
          terraform fmt --check
          terraform validate

  plan:
    needs: validate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Plan
        run: |
          cd environments/prod
          terraform init -backend-config="address=${{ secrets.TF_HTTP_ADDRESS }}"
          terraform plan -no-color
        env:
          TF_VAR_pm_api_url: ${{ secrets.PM_API_URL }}
          TF_VAR_pm_api_token: ${{ secrets.PM_API_TOKEN }}

  apply:
    if: github.ref == 'refs/heads/main'
    needs: plan
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Apply
        run: |
          cd environments/prod
          terraform init -backend-config="address=${{ secrets.TF_HTTP_ADDRESS }}"
          terraform apply -auto-approve
        env:
          TF_VAR_pm_api_url: ${{ secrets.PM_API_URL }}
          TF_VAR_pm_api_token: ${{ secrets.PM_API_TOKEN }}
```

The `environment: production` step adds a manual approval gate in
Gitea/GitHub before Terraform applies changes. Pull requests run only
validate and plan — you see exactly what will change before merging.

---

## 8. Full Workflow in Action

Here is what happens when you update a container's CPU allocation:

1. Edit `environments/prod/main.tf` — change `cores = 2` to `cores = 4`
2. Commit and push to a feature branch
3. The CI pipeline runs `terraform fmt --check`, `validate`, and `plan`
4. The plan shows: *"proxmox_virtual_environment_container.web01 will be updated"*
5. Open a pull request, review the plan output
6. Merge to `main`
7. The apply job runs with manual approval
8. Terraform updates the container — CPU limit changed, zero downtime

Adding a new LXC is just adding a new resource block to the
configuration:

```hcl
resource "proxmox_virtual_environment_container" "cache" {
  node_name = var.pm_node
  vm_id     = 211

  template { file_id = "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst" }
  cpu    { cores = 1 }
  memory { dedicated = 512 }
  disk   { datastore_id = "local-zfs" size = 4 }
  network { name = "eth0" bridge = "vmbr0" ip = "dhcp" }
}
```

Commit, push, approve — the cache container appears on your Proxmox
host. The same workflow works for VM resource changes, network
updates, or datastore reconfigurations.

---

## 9. Proxmox GitOps Benefits

| Manual workflow | GitOps workflow |
|----------------|-----------------|
| Click through web UI | Edit YAML/HCL in Git |
| No change history | Full git log of every change |
| Easy to skip steps | CI enforces validation |
| Human error risk | Idempotent applies |
| No rollback plan | `git revert` restores state |

---

## Conclusion

A Proxmox GitOps workflow with Terraform or OpenTofu eliminates the
guesswork from infrastructure management. Every LXC and VM is defined
declaratively, tracked in Git, and deployed through a repeatable
CI/CD pipeline that validates before applying.

Start small: create an API token, define one LXC container with the
`bpg/proxmox` provider, and set up remote state in MinIO. Once that
works, add the CI pipeline and expand to VMs. The infrastructure
drift that plagues manual setups disappears when commits drive
changes.

For the next step, pair this with Ansible for post-deployment
configuration management — Terraform provisions the hardware, Ansible
configures the software inside it.
