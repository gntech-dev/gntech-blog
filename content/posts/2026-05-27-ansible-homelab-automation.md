---
title: "Ansible Homelab Automation — Infrastructure as Code Guide"
description: "Practical Ansible homelab automation guide — install, inventory, playbook structure, roles, vault, and Proxmox integration for reproducible infrastructure as code."
date: 2026-05-27T07:00:00-04:00
tags:
  - ansible
  - automation
  - linux
  - devops
  - infrastructure
keywords:
  - Ansible homelab automation guide infrastructure as code
  - Ansible playbook structure roles directory layout homelab
  - Ansible inventory dynamic groups host variables best practices
  - Ansible vault secret management automation encrypted files
  - Ansible Proxmox module automation VM deployment
  - Ansible idempotent configuration management server setup
  - Ansible requirements.yml collections ansible-galaxy dependencies
summary: "Learn to automate your homelab with Ansible — inventory management, playbook layout, roles, vault secrets, and Proxmox integration for reproducible server deployments."
canonical: "https://gntech.dev/posts/ansible-homelab-automation/"
---

If you manage more than three Linux servers in your homelab, you
are already past the point where manual SSH-and-apt is sustainable.
A fresh OS install means hours of repeated work: adding users,
setting up SSH keys, installing Docker, configuring firewalls,
deploying monitoring agents. Then the next host comes, and you do
it all over again.

Ansible solves this. One playbook run turns a bare Debian install
into a fully configured homelab node — users, packages, config
files, running services, the whole stack. It is agentless (SSH
only), push-based, and idempotent: running it twice produces the
same result as running it once.

This guide covers a production-ready Ansible setup for homelab.
Inventory management, directory layout, role design, vault for
secrets, Proxmox module integration, and practical playbooks you
can adapt today. All examples work on Debian 12 / Ubuntu 24.04
and Ansible Core 2.17+.

---

## 1. Installation and Bootstrap

On your control machine — a laptop, a small LXC container, or a
VM — install Ansible:

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y ansible ansible-lint

# Verify
ansible --version
# ansible [core 2.17.6]
# config file = /etc/ansible/ansible.cfg
```

Or, for the absolute latest version via pip:

```bash
python3 -m venv ~/ansible-venv
source ~/ansible-venv/bin/activate
pip install ansible ansible-lint
```

**Why pip in a venv instead of apt:** The apt version on Debian
stable is frequently 6-12 months behind. Ansible moves fast —
collections, module deprecations, and Python compatibility
improvements land in pip first. Isolation in a venv avoids
conflicts with system Python site-packages.

### SSH Key Distribution

Ansible needs SSH access to all managed hosts. The most practical
approach for a homelab is key-based auth with an SSH agent:

```bash
# Generate a dedicated Ansible deployment key
ssh-keygen -t ed25519 -f ~/.ssh/ansible_deploy -C "ansible@homelab"

# Copy to a target host
ssh-copy-id -i ~/.ssh/ansible_deploy root@srv1.lab

# Or, if you use a non-root user with sudo:
ssh-copy-id -i ~/.ssh/ansible_deploy admin@srv1.lab

# Test
ssh -i ~/.ssh/ansible_deploy root@srv1.lab hostname
```

For repeatable bootstrapping of new hosts, automate key
distribution in your PXE/cloud-init config, or use a small shell
loop:

```bash
for host in srv1 srv2 srv3 nas; do
  ssh-copy-id -i ~/.ssh/ansible_deploy root@$host.lab
done
```

---

## 2. Directory Layout and Inventory

A consistent directory structure is the foundation of maintainable
automation. The standard pattern works well for homelabs:

```
ansible-homelab/
├── ansible.cfg
├── inventory/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   ├── staging/
│   │   └── hosts.yml
│   └── hosts.yml               # default inventory
├── group_vars/
│   └── all.yml
├── host_vars/
│   ├── srv1.yml
│   └── srv2.yml
├── roles/
│   ├── common/
│   ├── docker/
│   ├── prometheus-node/
│   ├── wireguard/
│   └── proxmox-node/
├── playbooks/
│   ├── bootstrap.yml
│   ├── deploy-monitoring.yml
│   └── update-all.yml
├── collections/
│   └── requirements.yml
└── vault-password.txt          # .gitignore this!
```

### ansible.cfg

```ini
[defaults]
inventory = inventory/hosts.yml
host_key_checking = False
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible-facts
fact_caching_timeout = 3600
stdout_callback = yaml
callback_whitelist = profile_tasks
ansible_managed = Ansible managed: {file} modified on %Y-%m-%d
interpreter_python = /usr/bin/python3
roles_path = roles
collections_paths = collections

[ssh_connection]
pipelining = True
control_path = /tmp/ansible-%%h-%%p-%%r
```

**Key settings:**
- `fact_caching = jsonfile` — caches host facts on disk between
  playbook runs, speeding up subsequent runs significantly
- `pipelining = True` — reduces SSH overhead by pipelining
  operations. Must have `requiretty` disabled in sudoers on
  managed hosts
- `stdout_callback = yaml` — human-readable output with task
  names and durations

### Inventory File

```yaml
# inventory/hosts.yml
all:
  children:
    proxmox:
      hosts:
        srv1:
          ansible_host: 10.0.20.30
      vars:
        ansible_user: root

    docker_hosts:
      hosts:
        srv1:
        srv2:
          ansible_host: 10.0.20.31
      vars:
        ansible_user: admin
        ansible_become: true

    monitoring_targets:
      hosts:
        srv1:
        srv2:
        nas:
          ansible_host: 10.0.20.50

    network:
      hosts:
        mikrotik-core:
          ansible_host: 10.0.20.1
          ansible_connection: community.network.routeros
          ansible_user: netadmin
          ansible_network_os: community.network.routeros
```

**Why separate groups:** Group membership controls which playbooks
and roles apply to which hosts. `docker_hosts` get Docker-related
roles, `proxmox` gets Proxmox-specific config, `network` uses the
RouterOS connection plugin instead of SSH.

### Group and Host Variables

```yaml
# group_vars/all.yml
---
ntp_servers:
  - 0.pool.ntp.org
  - 1.pool.ntp.org
dns_servers:
  - 10.0.20.1
  - 1.1.1.1
admin_users:
  - name: gntech
    key: "{{ vault_admin_ssh_key }}"
    shell: /bin/bash
    groups: [sudo, docker]
  - name: monitoring
    key: "{{ vault_monitoring_key }}"
    shell: /usr/sbin/nologin
    groups: []
```

```yaml
# host_vars/srv1.yml
---
host_role: homelab_main
docker_data_root: /docker/data
docker_compose_dir: /opt/docker-compose
backup_enabled: true
backup_target: "nfs://10.0.20.50/mnt/backups/srv1"
```

This separation keeps reusable defaults in `group_vars` and
hardware-specific overrides in `host_vars`.

---

## 3. Roles — Building Reusable Components

Roles are the building blocks. Each role configures one slice of
a system. Here are practical roles for a homelab.

### The Common Role (Every Host)

```yaml
# roles/common/tasks/main.yml
---
- name: Set hostname
  hostname:
    name: "{{ ansible_hostname }}"
  tags: hostname

- name: Install base packages
  apt:
    name:
      - htop
      - iotop
      - tmux
      - vim
      - git
      - curl
      - wget
      - jq
      - net-tools
      - lsof
      - tree
      - rsync
      - unattended-upgrades
      - fail2ban
    state: present
    update_cache: true
  tags: packages

- name: Configure timezone
  timezone:
    name: "{{ timezone | default('America/Santo_Domingo') }}"
  notify: restart cron
  tags: timezone

- name: Create admin users
  user:
    name: "{{ item.name }}"
    shell: "{{ item.shell | default('/bin/bash') }}"
    groups: "{{ item.groups | join(',') }}"
    append: true
    state: present
  loop: "{{ admin_users }}"
  tags: users

- name: Deploy SSH authorized keys
  authorized_key:
    user: "{{ item.name }}"
    key: "{{ item.key }}"
  loop: "{{ admin_users }}"
  tags: ssh,users

- name: Harden SSH config
  lineinfile:
    path: /etc/ssh/sshd_config
    regexp: "{{ item.regexp }}"
    line: "{{ item.line }}"
    state: present
  loop:
    - { regexp: '^PermitRootLogin', line: 'PermitRootLogin prohibit-password' }
    - { regexp: '^PasswordAuthentication', line: 'PasswordAuthentication no' }
    - { regexp: '^PubkeyAuthentication', line: 'PubkeyAuthentication yes' }
    - { regexp: '^ChallengeResponseAuthentication', line: 'ChallengeResponseAuthentication no' }
    - { regexp: '^MaxAuthTries', line: 'MaxAuthTries 3' }
    - { regexp: '^ClientAliveInterval', line: 'ClientAliveInterval 300' }
    - { regexp: '^ClientAliveCountMax', line: 'ClientAliveCountMax 2' }
  notify: restart sshd
  tags: ssh

- name: Configure unattended-upgrades
  dpkg_selections:
    name: unattended-upgrades
    selection: install
  tags: updates

- name: Enable automatic security updates
  copy:
    content: |
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Download-Upgradeable-Packages "1";
      APT::Periodic::AutocleanInterval "7";
      APT::Periodic::Unattended-Upgrade "1";
      APT::Periodic::Verbose "0";
    dest: /etc/apt/apt.conf.d/20auto-upgrades
    mode: '0644'
  tags: updates

- name: Configure fail2ban for SSH
  template:
    src: fail2ban-jail.local.j2
    dest: /etc/fail2ban/jail.local
  notify: restart fail2ban
  tags: security

- name: Enable and start services
  service:
    name: "{{ item }}"
    state: started
    enabled: true
  loop:
    - fail2ban
    - cron
  tags: services
```

```yaml
# roles/common/handlers/main.yml
---
- name: restart sshd
  service:
    name: sshd
    state: restarted

- name: restart cron
  service:
    name: cron
    state: restarted

- name: restart fail2ban
  service:
    name: fail2ban
    state: restarted
```

### Docker Role

```yaml
# roles/docker/tasks/main.yml
---
- name: Remove old Docker packages
  apt:
    name:
      - docker.io
      - docker-doc
      - docker-compose
      - containerd
      - runc
    state: absent
  tags: docker

- name: Install dependencies
  apt:
    name:
      - ca-certificates
      - curl
      - gnupg
    state: present
  tags: docker

- name: Add Docker GPG key
  apt_key:
    url: https://download.docker.com/linux/debian/gpg
    state: present
  tags: docker

- name: Add Docker repository
  apt_repository:
    repo: "deb [arch=amd64] https://download.docker.com/linux/debian {{ ansible_distribution_release }} stable"
    state: present
  tags: docker

- name: Install Docker packages
  apt:
    name:
      - docker-ce
      - docker-ce-cli
      - containerd.io
      - docker-buildx-plugin
      - docker-compose-plugin
    state: present
    update_cache: true
  notify: restart docker
  tags: docker

- name: Configure Docker daemon
  copy:
    content: |
      {
        "data-root": "{{ docker_data_root | default('/var/lib/docker') }}",
        "log-driver": "json-file",
        "log-opts": {
          "max-size": "10m",
          "max-file": "3"
        },
        "storage-driver": "overlay2",
        "iptables": true,
        "live-restore": true,
        "max-concurrent-downloads": 10
      }
    dest: /etc/docker/daemon.json
    mode: '0644'
  notify: restart docker
  tags: docker

- name: Create docker-compose directory
  file:
    path: "{{ docker_compose_dir | default('/opt/docker-compose') }}"
    state: directory
    mode: '0755'
  tags: docker

- name: Ensure Docker is running
  service:
    name: docker
    state: started
    enabled: true
  tags: docker
```

```yaml
# roles/docker/handlers/main.yml
---
- name: restart docker
  service:
    name: docker
    state: restarted
```

---

## 4. Playbooks — Putting It Together

### Bootstrap Playbook

```yaml
# playbooks/bootstrap.yml
---
- name: Bootstrap new homelab host
  hosts: all
  gather_facts: true
  become: true

  pre_tasks:
    - name: Ensure Debian/Ubuntu
      fail:
        msg: "This playbook only supports Debian/Ubuntu"
      when: ansible_os_family != "Debian"

  roles:
    - common
    - docker
    - prometheus-node
```

Run it:

```bash
cd ~/ansible-homelab
ansible-playbook playbooks/bootstrap.yml -l srv2
```

The `-l srv2` flag limits execution to hosts matching `srv2` in
the inventory. First run takes 2-5 minutes depending on package
downloads. Subsequent runs complete in under 30 seconds thanks to
idempotency and fact caching.

### Update All Playbook

```yaml
# playbooks/update-all.yml
---
- name: Apply updates across all hosts
  hosts: all
  gather_facts: false
  become: true
  serial: 3        # update 3 hosts at a time to avoid flooding

  tasks:
    - name: Update apt cache
      apt:
        update_cache: true
      changed_when: false

    - name: Show upgradable packages
      shell: apt list --upgradable 2>/dev/null | tail -n +2
      register: upgradable
      changed_when: false

    - name: Print pending updates
      debug:
        msg: "{{ upgradable.stdout_lines | default([]) }}"

    - name: Upgrade all packages
      apt:
        upgrade: dist
        autoremove: true
        autoclean: true

    - name: Check if reboot is required
      stat:
        path: /var/run/reboot-required
      register: reboot_required

    - name: Reboot if required
      reboot:
        reboot_timeout: 300
        pre_reboot_delay: 30
      when: reboot_required.stat.exists

    - name: Clean up old kernels
      apt:
        autoremove: true
        purge: true
```

Run with a dry-run first:

```bash
ansible-playbook playbooks/update-all.yml --check
ansible-playbook playbooks/update-all.yml
```

Schedule it via systemd timer or cron on the control host:

```bash
# crontab on control host
0 2 * * 0 cd ~/ansible-homelab && ansible-playbook playbooks/update-all.yml >> /var/log/ansible-updates.log 2>&1
```

---

## 5. Ansible Vault — Managing Secrets

Hardcoding passwords, API keys, and SSH private keys in
playbooks is a bad practice — especially if you version-control
your automation. Ansible Vault encrypts sensitive data at rest.

### Setup

```bash
# Create a password file (DO NOT commit this)
echo "your-vault-password-here" > ~/ansible-homelab/.vault_pass
chmod 600 ~/.vault_pass

# Update ansible.cfg to use it
echo "vault_password_file = .vault_pass" >> ansible.cfg
```

### Encrypt Variables

```yaml
# group_vars/all/vault.yml
---
# ansible-vault encrypt group_vars/all/vault.yml
vault_admin_ssh_key: "ssh-ed25519 AAAAC3... user@control"
vault_monitoring_key: "ssh-ed25519 AAAAC3... user@monitoring"
vault_wireguard_private_key: "gN3rT..."
vault_cloudflare_api_token: "cfsd_..."
```

Create and encrypt:

```bash
touch group_vars/all/vault.yml
ansible-vault encrypt group_vars/all/vault.yml
# Edit:
ansible-vault edit group_vars/all/vault.yml
# View:
ansible-vault view group_vars/all/vault.yml
```

Ansible automatically merges `vault.yml` files with regular
`vars.yml` files in the same directory. Reference vault variables
in playbooks exactly like regular variables:

```yaml
- name: Deploy WireGuard config
  template:
    src: wg0.conf.j2
    dest: /etc/wireguard/wg0.conf
  vars:
    private_key: "{{ vault_wireguard_private_key }}"
```

**Pro tip for homelab:** Store the vault password in a
password manager (Bitwarden, 1Password, or even a KDE
Wallet/KeePassXC) rather than on disk. On the control machine,
wrap `ansible-playbook` in a script that fetches the password:

```bash
#!/bin/bash
# ~/ansible-homelab/run-playbook.sh
PASS=$(pass ansible/vault 2>/dev/null || echo "")
if [ -z "$PASS" ]; then
  echo "Vault password not found. Run: pass insert ansible/vault"
  exit 1
fi
echo "$PASS" | ansible-playbook "$@" --vault-password-file=<(cat)
```

---

## 6. Proxmox Integration with Ansible

The `community.general.proxmox` and `community.general.proxmox_kvm`
modules let you manage Proxmox VMs and LXCs from Ansible
playbooks — creating, cloning, resizing, and starting containers
without touching the web UI.

### Install the Collection

```yaml
# collections/requirements.yml
---
collections:
  - name: community.general
  - name: community.docker
  - name: ansible.posix
  - name: community.crypto
```

```bash
ansible-galaxy collection install -r collections/requirements.yml
```

### Automated LXC Deployment

```yaml
# playbooks/deploy-lxc.yml
---
- name: Deploy LXC containers on Proxmox
  hosts: proxmox
  gather_facts: false
  tasks:
    - name: Create LXC container
      community.general.proxmox:
        api_user: "{{ proxmox_api_user | default('root@pam') }}"
        api_password: "{{ vault_proxmox_password }}"
        api_host: "{{ inventory_hostname }}"
        vmid: "{{ item.vmid }}"
        node: "{{ item.node | default('srv1') }}"
        hostname: "{{ item.hostname }}"
        ostemplate: "{{ item.template | default('local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst') }}"
        storage: "{{ item.storage | default('local-zfs') }}"
        cores: "{{ item.cores | default(2) }}"
        memory: "{{ item.memory | default(2048) }}"
        swap: "{{ item.swap | default(512) }}"
        netif: '{"net0":"name=eth0,bridge=vmbr0,ip=dhcp"}'
        onboot: true
        unprivileged: true
        features:
          - keyctl=1
          - nesting=1
        state: started
      loop: "{{ proxmox_containers }}"
      when: item.state | default('present') == 'present'
```

With `host_vars/srv1.yml`:

```yaml
proxmox_containers:
  - vmid: 201
    hostname: ansible-ctrl
    cores: 2
    memory: 2048
    storage: local-zfs
  - vmid: 202
    hostname: docker-host-1
    cores: 4
    memory: 8192
    storage: local-zfs
  - vmid: 203
    hostname: monitoring-stack
    cores: 2
    memory: 4096
    storage: local-zfs
```

Run it:

```bash
ansible-playbook playbooks/deploy-lxc.yml --ask-vault-pass
```

### Clone from Template

For VMs, cloning from a prepared template is faster than
creating from scratch:

```yaml
- name: Clone Proxmox VM from template
  community.general.proxmox_kvm:
    api_user: root@pam
    api_password: "{{ vault_proxmox_password }}"
    api_host: "{{ inventory_hostname }}"
    name: "{{ item.hostname }}"
    node: srv1
    clone: debian-12-template
    storage: local-zfs
    format: qcow2
    full: true
    cores: "{{ item.cores }}"
    memory: "{{ item.memory }}"
    net:
      net0: "virtio,bridge=vmbr0"
    state: started
  loop: "{{ proxmox_vms }}"
```

---

## 7. Ansible for MikroTik Configuration

Ansible manages more than just Linux. The `community.network.routeros`
connection plugin lets you apply configs to RouterOS devices:

```yaml
# playbooks/configure-mikrotik.yml
---
- name: Configure MikroTik router
  hosts: network
  gather_facts: false
  tasks:
    - name: Set router identity
      community.network.routeros_command:
        commands:
          - /system identity set name={{ inventory_hostname }}

    - name: Apply firewall filter rules
      community.network.routeros_command:
        commands:
          - /ip firewall filter add chain=input connection-state=established,related action=accept
          - /ip firewall filter add chain=input protocol=icmp action=accept
          - /ip firewall filter add chain=input connection-state=invalid action=drop

    - name: Update DNS over HTTPS settings
      community.network.routeros_command:
        commands:
          - /ip dns set servers=1.1.1.1,8.8.8.8 use-doh-server=https://cloudflare-dns.com/dns-query
```

Note: RouterOS modules use the RouterOS API, not SSH. Ensure the
API service is enabled and restricted to your Ansible host's IP:

```bash
/ip service set api-ssl address=10.0.20.20
```

---

## 8. Role Design Strategies

### Conditionals by Host Role

A single bootstrap playbook can behave differently depending on
host_vars, keeping your automation DRY:

```yaml
- name: Configure monitoring agents
  include_role:
    name: prometheus-node
  when: "'monitoring_targets' in group_names"

- name: Configure Docker
  include_role:
    name: docker
  when: "'docker_hosts' in group_names"
```

### Tags for Targeted Runs

Tag everything. It lets you run only the parts you need:

```bash
# Only run user management tasks on all hosts
ansible-playbook playbooks/bootstrap.yml --tags users

# Run everything except hostname changes
ansible-playbook playbooks/bootstrap.yml --skip-tags hostname

# Run Docker install on all docker hosts
ansible-playbook playbooks/bootstrap.yml -l docker_hosts --tags docker
```

### Jinja2 Templates for Config Files

Templates keep config generation clean. Example:
`roles/common/templates/fail2ban-jail.local.j2`:

```ini
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
ignoreip = {{ dns_servers | join(' ') }} {{ ansible_default_ipv4.address }}

[sshd]
enabled = true
port = {{ ssh_port | default(22) }}
logpath = %(sshd_log)s
backend = %(sshd_backend)s
```

---

## 9. Testing and Validation

### Syntax and Lint Checks

Always validate before applying to production hosts:

```bash
# Check YAML syntax
ansible-playbook playbooks/bootstrap.yml --syntax-check

# Lint the playbook
ansible-lint playbooks/bootstrap.yml

# Dry run (idempotency check)
ansible-playbook playbooks/bootstrap.yml --check --diff

# Lint all roles
ansible-lint roles/*/tasks/*.yml
```

### Idempotency Testing

A true idempotent playbook produces zero changes on the second
run (assuming nothing changed on the host externally). If the
second run reports changes, you have a non-idempotent task:

```bash
# Run twice — first applies, second verifies
ansible-playbook playbooks/bootstrap.yml
ansible-playbook playbooks/bootstrap.yml
# Second run should show "changed=0"
```

Common sources of non-idempotence: `command`/`shell` modules
without `creates` or `when` guards, `lineinfile` without
`regexp`, and `copy` without explicit content comparison.

---

## 10. Recommended Workflow

### Git for Version Control

```bash
cd ~/ansible-homelab
git init
git add .
git commit -m "Initial homelab Ansible automation"
```

Add a `.gitignore`:

```gitignore
.vault_pass
collections/
*.retry
__pycache__/
*.pyc
/tmp/
inventory/production/hosts.yml
```

Commit the inventory structure and examples, but keep actual IPs
and vault passwords out of the repository. Use
`inventory/hosts.yml.example` as a reference:

```yaml
# inventory/hosts.yml.example
---
all:
  children:
    docker_hosts:
      hosts:
        my-server-1:
    proxmox:
      hosts:
        my-proxmox:
```

### Daily Operations

```bash
# Bootstrap a new host
ansible-playbook playbooks/bootstrap.yml -l new-host

# Run updates on all servers
ansible-playbook playbooks/update-all.yml

# Deploy a new LXC
ansible-playbook playbooks/deploy-lxc.yml

# Check config compliance
ansible-playbook playbooks/bootstrap.yml --check

# Ad-hoc: reboot a host
ansible docker_hosts -a "reboot" -b

# Ad-hoc: check disk space
ansible all -a "df -h" -b

# Ad-hoc: list Docker containers
ansible docker_hosts -a "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

### Scaling to Multiple Sites

If you have multiple homelab locations (home, colo, VPS), use
separate inventories:

```bash
ansible-playbook -i inventory/production playbooks/update-all.yml
ansible-playbook -i inventory/staging   playbooks/bootstrap.yml
```

Or separate inventory groups with host prefix conventions:

```yaml
# inventory/hosts.yml
home:
  hosts:
    home-pve01: { ansible_host: 10.0.20.30 }
    home-nas:   { ansible_host: 10.0.20.50 }

colo:
  hosts:
    colo-pve01: { ansible_host: 198.51.100.10 }
    colo-db01:  { ansible_host: 198.51.100.11 }
```

---

## Summary

Ansible turns homelab server management from a manual chore into
a repeatable, documented, one-command operation. The investment
in writing playbooks pays off the first time you rebuild a failed
host and are back online in under 10 minutes.

Key takeaways from this guide:

1. **Directory structure matters** — organize your inventory,
   roles, and playbooks consistently from day one.
2. **Roles over playbook tasks** — roles are reusable across
   projects and composable in different playbooks.
3. **Vault for secrets** — never commit plaintext passwords or
   keys. Encrypt them with `ansible-vault` and store the
   password in a manager.
4. **Proxmox automation** — the `community.general.proxmox*`
   modules let you deploy VMs and LXCs from the same tool you
   use to configure them.
5. **Test idempotency** — second runs should produce zero
   changes. If they don't, your automation has a bug.
6. **Tag aggressively** — tags let you run targeted slices of
   your automation without executing the full playbook.

The complete structure at
[github.com/gntech/ansible-homelab](https://github.com/gntech/ansible-homelab)
is a usable starting point — adapt the roles, swap in your own
variable values, and start automating today.
