---
title: "Ansible for a Homelab — Inventory, First Playbook, and Safe Expansion"
description: "Start with a small local Ansible playbook, verify repeatability, then target one disposable Linux host before expanding to roles and services."
date: 2026-05-27T07:00:00-04:00
lastmod: 2026-10-31
draft: false
aliases:
  - /posts/2026-05-13-ansible-homelab-automation/
tags: [ansible, automation, linux, homelab]
summary: "A staged Ansible introduction with a complete file-management example, explicit target selection, check-mode limits, secrets guidance and rollback."
---

Ansible makes repeated configuration changes easier to describe and review. A useful first project manages one harmless file, rather than changing SSH, firewall rules, package repositories and Docker storage in a single run.

This guide consolidates the two earlier Ansible introductions. It replaces their overlapping bootstrap examples with a complete small exercise. It does not claim to restore an entire lab from Git or provide a tested production role collection.

## Verification status

| Scope | Evidence and limits |
| --- | --- |
| Environment | Linux control node with a supported Ansible installation; a disposable Linux target for the optional remote step. |
| Preparation | Bash syntax and generated YAML structure can be checked independently. |
| Runtime | The playbook has not been run against a host during this update. |
| Before relying on it | Validate with the installed Ansible version, run on a test target, inspect the result and repeat the run. |

## Install and record your tools

Use the [official installation guide](https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html) for your control node. Distribution packages and isolated Python environments have different release policies; an apt install is not automatically the latest upstream release or a PPA installation.

```bash
ansible --version
ansible-playbook --version
```

The example uses built-in modules. Remote Linux targets normally need SSH access and a compatible Python interpreter. RouterOS devices require their own supported connection and collection setup; do not put them in a Linux bootstrap play without separating those requirements.

## Create a small project

Use a new directory and run these commands as your normal user, not root:

```bash
mkdir -p "$HOME/ansible-first-lab/playbooks"
cd "$HOME/ansible-first-lab"
cat > ansible.cfg <<'EOF'
[defaults]
inventory = ./inventory.yml
host_key_checking = True
EOF
cat > inventory.yml <<'EOF'
all:
  children:
    control_local:
      hosts:
        localhost:
          ansible_connection: local
    linux_lab:
      hosts: {}
EOF
cat > playbooks/demo.yml <<'EOF'
---
- name: Manage a demonstration file
  hosts: "{{ target_group | default('control_local') }}"
  gather_facts: true
  become: false
  vars:
    demo_directory: "{{ ansible_env.HOME }}/ansible-first-lab-output"
  tasks:
    - name: Create demonstration directory
      ansible.builtin.file:
        path: "{{ demo_directory }}"
        state: directory
        mode: '0750'

    - name: Write demonstration file
      ansible.builtin.copy:
        dest: "{{ demo_directory }}/managed.txt"
        content: "Managed by Ansible for {{ inventory_hostname }}\n"
        mode: '0640'
EOF
```

This writes a dedicated demonstration directory under the execution account's home. It does not create users, change authentication, enable a firewall or restart services. Check that the output path is unused before applying it.

## Inspect the targets and validate syntax

```bash
ansible-inventory --graph
ansible-playbook playbooks/demo.yml --list-hosts
ansible-playbook playbooks/demo.yml --syntax-check
ansible control_local -m ansible.builtin.ping
```

The default play should select only localhost. Ansible's ping module tests module execution; it is not an ICMP network ping.

## Preview, apply, then repeat

```bash
ansible-playbook playbooks/demo.yml --check --diff
ansible-playbook playbooks/demo.yml
cat "$HOME/ansible-first-lab-output/managed.txt"
ansible-playbook playbooks/demo.yml
```

Check mode is a simulation, not proof that the apply will succeed. In this example the copy task may fail in the initial preview because the directory task only simulates creation. Inspect that dependency rather than treating it as permission to skip validation.

Some modules do not support check mode, and tasks explicitly configured with `check_mode: false` can still run normally. Diff output can reveal file contents, including secrets. Review the [check and diff documentation](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html) for the modules you use.

After a real successful apply, an unchanged second run of this example should report no changes. Inspect the recap and file; do not assume every playbook is idempotent simply because it uses Ansible. A later preview should also be easier to interpret now that the directory exists.

## Move to one disposable remote host

Establish working SSH access first and verify the host's fingerprint through a trusted path. Keep host-key checking enabled. Do not treat an unverified key scan as proof of identity.

Replace the empty lab group with one test host. This example address is documentation-only; replace it and the username before connecting:

```bash
cp -a inventory.yml inventory.yml.before-remote
cat > inventory.yml <<'EOF'
all:
  children:
    control_local:
      hosts:
        localhost:
          ansible_connection: local
    linux_lab:
      hosts:
        lab01:
          ansible_host: 192.0.2.10
          ansible_user: YOUR_LINUX_USER
EOF
ansible-playbook playbooks/demo.yml -e target_group=linux_lab --limit lab01 --list-hosts
ansible linux_lab --limit lab01 -m ansible.builtin.ping
ansible-playbook playbooks/demo.yml -e target_group=linux_lab --limit lab01 --check --diff
```

Only after reviewing those results, apply to that host and repeat:

```bash
ansible-playbook playbooks/demo.yml -e target_group=linux_lab --limit lab01
ansible-playbook playbooks/demo.yml -e target_group=linux_lab --limit lab01
```

Inspect the output file on the remote account, not on the control node. Keep the `--limit` until you deliberately expand the inventory. Privilege escalation and its credentials are unnecessary for this user-owned-file exercise.

## Expand with roles and collections

Once the small workflow works, split configuration into reusable roles and keep a play's `hosts` scoped to the appropriate group. An imported playbook must exist; referencing an unspecified monitoring role does not create it.

Record collection versions in a requirements file and check their current module documentation. Docker deployment requires an installed compatible engine and the collection's prerequisites. Proxmox API provisioning is separate from running Linux modules over SSH on a guest. RouterOS command modules can use a different transport from API modules.

Introduce one service at a time. Validate templates before restarting services, keep handlers scoped, and back up existing configuration. Avoid combining daemon data-root changes, package removal and a service restart into an untested generic Docker role.

## Handle secrets deliberately

Ansible Vault encrypts stored data, not every place it might appear during execution. Prefer an interactive vault password or an approved password-manager integration, rather than putting a literal password in shell history or committing a password file.

Load encrypted variables through an explicit file or a correctly placed inventory variable directory. A filename containing `vault` does not alone guarantee that Ansible loads it. Tasks handling credentials may need `no_log: true` and `diff: false`; avoid debugging those values into logs.

Create ignore rules before the first Git commit. Review staged changes for credentials and generated output. Git preserves configuration history; it does not replace backups of databases, volumes, keys or other application data.

## Roll back the demonstration

The local exercise creates only the dedicated directory and file. Inspect them before removal:

```bash
ls -la "$HOME/ansible-first-lab-output"
rm -i "$HOME/ansible-first-lab-output/managed.txt"
rmdir "$HOME/ansible-first-lab-output"
```

Run those commands on the test target if you applied the remote exercise. `rmdir` refuses to remove a nonempty directory; investigate additional files instead of switching to recursive deletion. Restore the saved inventory if you want to return to the local-only setup.

## Continue reading

- [Docker Compose patterns](/posts/2026-05-08-docker-compose-patterns/) — understand the service definitions before automating deployments.
- [Monitoring foundations](/posts/2026-05-17-homelab-monitoring-stack/) — verify a small application stack before turning it into a role.
- [Ansible Vault documentation](https://docs.ansible.com/projects/ansible/latest/vault_guide/index.html) — review encryption and secret-handling behavior.

This consolidation removes the older disabled-host-verification recommendation, missing-role bootstrap examples and fixed completion-time claims. No remote execution or application-level syntax validation is claimed for this update; use the validation steps above with the versions you install.
