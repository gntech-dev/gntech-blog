---
title: "Ansible Homelab Automation — Infrastructure as Code for Docker and Linux Servers"
description: "Practical Ansible homelab automation — infrastructure as code for Docker and Linux servers. Playbook structure, community.docker, ansible-vault, Jinja2 templates, and full project template."
date: 2026-05-13T16:30:00-04:00
tags:
  - automation
  - docker
  - linux
  - devops
  - homelab
keywords:
  - Ansible homelab automation
  - infrastructure as code homelab
  - Docker Ansible deployment
  - ansible-vault secrets
  - Linux server configuration automation
summary: "Practical Ansible homelab automation guide — playbook structure, Docker container deployment with community.docker, ansible-vault secrets, Jinja2 templates, Git workflow, and full project template."
canonical: "https://gntech.dev/posts/ansible-homelab-automation/"
---

If you manage more than two Linux servers in your homelab, you've
probably SSH'd into each one, run the same three commands, and thought
"there has to be a better way." There is — it's Ansible.

Ansible is agentless infrastructure-as-code. You write YAML playbooks
on your control machine, and it SSH's into your hosts to apply them.
No agents, no daemons, no persistent connections. Just SSH and Python
on the target.

This guide covers setting up Ansible for a homelab, writing playbooks
that manage Docker containers and system configuration, handling secrets
safely with ansible-vault, and structuring your project so it doesn't
turn into an unmaintainable mess. Real configs, real examples.

---

## Why Ansible and Not a Shell Script?

Shell scripts work until they don't. Here's what Ansible gives you that
a bash script doesn't:

- **Idempotence** — Run the playbook 100 times, same result each time.
  Shell scripts crash on the second run when the config file already exists.
- **Inventory** — Manage dozens of hosts from one control node without
  maintaining SSH configs everywhere.
- **Templating** — Jinja2 templates for config files with variables that
  differ per host.
- **Facts** — Ansible gathers system info (OS, IPs, disks, memory) and
  exposes it as variables you can use in playbooks.
- **Error handling** — Failed tasks stop the playbook instead of silently
  corrupting your config.

For a homelab with 3–20 VMs or LXCs, Ansible turns "SSH into each and
pray" into a single `ansible-playbook` command.

---

## Setting Up Ansible

### Control Node (Your Workstation or a Management LXC)

Ansible runs from any Linux machine. I run it inside a dedicated LXC
container on Proxmox with 1 core and 512 MB RAM — it doesn't need
much.

```bash
# Debian/Ubuntu — install from official PPA for latest version
sudo apt update
sudo apt install -y ansible ansible-lint

# Verify
ansible --version
# Should show ansible [core 2.18+] with python 3.x
```

For macOS or WSL: `brew install ansible` or `pip install ansible`.

### Target Host Requirements

Ansible only needs two things on each target:

1. **SSH server** running and reachable
2. **Python 3** — most Debian/Ubuntu installs have it. If not:

```bash
# Control node can install it via the raw module if needed
ansible all -m raw -a "apt install -y python3" -u root
```

That's it. No agents, no extra ports, no registration process.

---

## Project Structure

Don't throw everything into one `playbook.yml`. A maintainable structure
looks like this:

```
homelab-ansible/
├── ansible.cfg
├── inventory/
│   ├── production.yml
│   └── group_vars/
│       └── all.yml
├── playbooks/
│   ├── site.yml
│   ├── docker-hosts.yml
│   └── system-base.yml
├── roles/
│   ├── docker/
│   ├── common/
│   ├── traefik/
│   └── monitoring/
└── requirements.yml
```

### ansible.cfg

```ini
[defaults]
inventory = inventory/production.yml
host_key_checking = False
retry_files_enabled = False
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible-facts
stdout_callback = yaml

[ssh_connection]
pipelining = True
control_path = /tmp/ansible-%%h-%%p-%%r
```

Key settings:
- `pipelining = True` — reduces SSH connections per task. Huge speedup.
- `host_key_checking = False` — don't prompt for new host keys on first
  connect (safe in a homelab with known hardware).
- `stdout_callback = yaml` — prettier output.

### Inventory

```yaml
# inventory/production.yml
all:
  children:
    proxmox_hosts:
      hosts:
        srv1:
          ansible_host: 10.0.20.30
          ansible_user: root
    docker_hosts:
      hosts:
        docker-01:
          ansible_host: 10.0.20.31
          ansible_user: gntech
          ansible_become: yes
        docker-02:
          ansible_host: 10.0.20.32
          ansible_user: gntech
          ansible_become: yes
    routers:
      hosts:
        router-01:
          ansible_host: 10.0.20.1
          ansible_user: admin
          ansible_network_os: routeros
```

Ansible pulls facts about each host on first run — OS, IPs, interfaces,
disk, memory — and makes them available as variables like
`ansible_os_family`, `ansible_default_ipv4.address`, etc.

---

## First Playbook: System Baseline

Apply this to every new host. It ensures you can reach it, it has sane
defaults, and Docker is ready.

```yaml
# playbooks/system-base.yml
---
- name: System baseline for all Linux hosts
  hosts: all
  become: yes
  vars:
    timezone: America/Santo_Domingo
    admin_user: gntech
    ssh_key: "{{ lookup('file', '~/.ssh/id_ed25519.pub') }}"

  tasks:
    - name: Set timezone
      community.general.timezone:
        name: "{{ timezone }}"

    - name: Install essential packages
      apt:
        name:
          - htop
          - iotop
          - curl
          - wget
          - git
          - ufw
          - fail2ban
          - unattended-upgrades
        state: present
        update_cache: yes

    - name: Create admin user
      user:
        name: "{{ admin_user }}"
        groups: sudo,docker
        shell: /bin/bash
        append: yes
        state: present

    - name: Deploy SSH key
      authorized_key:
        user: "{{ admin_user }}"
        key: "{{ ssh_key }}"
        state: present

    - name: Harden SSH
      lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "{{ item.regexp }}"
        line: "{{ item.line }}"
        state: present
        validate: 'sshd -t -f %s'
      notify: restart sshd
      loop:
        - { regexp: '^PermitRootLogin', line: 'PermitRootLogin prohibit-password' }
        - { regexp: '^PasswordAuthentication', line: 'PasswordAuthentication no' }
        - { regexp: '^PubkeyAuthentication', line: 'PubkeyAuthentication yes' }

    - name: Configure UFW defaults
      ufw:
        direction: "{{ item.dir }}"
        policy: "{{ item.policy }}"
      loop:
        - { dir: incoming, policy: deny }
        - { dir: outgoing, policy: allow }

    - name: Allow SSH through UFW
      ufw:
        rule: allow
        port: '22'
        proto: tcp

    - name: Enable UFW
      ufw:
        state: enabled

  handlers:
    - name: restart sshd
      service:
        name: sshd
        state: restarted
```

Run it:

```bash
ansible-playbook playbooks/system-base.yml --limit docker_hosts
```

First run on a raw Debian install takes about 30 seconds. Subsequent
runs finish in under 2 seconds because everything is already in the
desired state — that's idempotence in action.

---

## Managing Docker Containers with Ansible

The `community.docker` collection lets you define containers, images,
networks, and volumes as Ansible state. This is more powerful than
Docker Compose for multi-host setups because Ansible handles ordering,
secrets, and host-specific variables.

### Install the Collection

```bash
ansible-galaxy collection install community.docker
```

Add it to `requirements.yml` so your project is reproducible:

```yaml
# requirements.yml
collections:
  - name: community.docker
```

Then install with:

```bash
ansible-galaxy collection install -r requirements.yml
```

### Docker Host Playbook

```yaml
# playbooks/docker-services.yml
---
- name: Deploy Docker containers across hosts
  hosts: docker_hosts
  become: yes
  vars_files:
    - vars/containers.yml
    - vault/secrets.yml

  tasks:
    - name: Ensure Docker is installed
      apt:
        name: docker-ce
        state: present
      tags: [docker, never]

    - name: Create required Docker networks
      community.docker.docker_network:
        name: "{{ item.name }}"
        driver: "{{ item.driver | default('bridge') }}"
        ipam_config: "{{ item.ipam | default(omit) }}"
        state: present
      loop: "{{ docker_networks }}"
      tags: [networks]

    - name: Create persistent volumes
      community.docker.docker_volume:
        name: "{{ item }}"
        state: present
      loop: "{{ docker_volumes }}"
      tags: [volumes]

    - name: Deploy containers
      community.docker.docker_container:
        name: "{{ item.name }}"
        image: "{{ item.image }}"
        state: started
        restart_policy: unless-stopped
        networks: "{{ item.networks | default(omit) }}"
        ports: "{{ item.ports | default(omit) }}"
        volumes: "{{ item.volumes | default(omit) }}"
        env: "{{ item.env | default(omit) }}"
        labels: "{{ item.labels | default(omit) }}"
        memory: "{{ item.memory | default('512m') }}"
        cpus: "{{ item.cpus | default(1.0) }}"
        restart: "{{ item.force_restart | default(false) }}"
      loop: "{{ docker_containers }}"
      tags: [containers]
```

### Container Definitions

```yaml
# vars/containers.yml
docker_networks:
  - name: web
    driver: bridge
    ipam:
      - subnet: "172.20.0.0/24"
  - name: internal
    driver: bridge
    ipam:
      - subnet: "172.20.1.0/24"

docker_volumes:
  - nginx_data
  - postgres_data
  - prometheus_data
  - grafana_data

docker_containers:
  - name: nginx
    image: nginx:stable-alpine
    networks:
      - name: web
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "nginx_data:/etc/nginx/conf.d"
    labels:
      traefik.enable: "true"

  - name: postgres
    image: postgres:16-alpine
    networks:
      - name: internal
    volumes:
      - "postgres_data:/var/lib/postgresql/data"
    env:
      POSTGRES_PASSWORD: "{{ vault_postgres_password }}"
      POSTGRES_DB: homelab
    memory: 1g
    cpus: 2.0

  - name: prometheus
    image: prom/prometheus:latest
    networks:
      - name: internal
      - name: web
    volumes:
      - "prometheus_data:/prometheus"
    memory: 1g
    cpus: 1.0
```

Run it:

```bash
ansible-playbook playbooks/docker-services.yml -l docker-01
```

One command deploys the entire service stack to any Docker host. If you
add a new host to the inventory, run the same playbook against it.

---

## Secrets with Ansible Vault

Hardcoding passwords in your playbooks is bad, and committing them to
Git is worse. Ansible Vault encrypts sensitive variables at rest.

### Create an Encrypted Vault File

```bash
ansible-vault create vault/secrets.yml
```

You'll be prompted for a vault password. Inside, add your secrets:

```yaml
vault_postgres_password: "S3cur3P@ssw0rd!"
vault_traefik_email: "admin@example.com"
vault_cloudflare_token: "abc123def456..."
vault_wireguard_private_key: "..."
```

Save and exit. The file is encrypted with AES-256.

### Use Secrets in Playbooks

Reference the vault file in your playbook:

```yaml
vars_files:
  - vault/secrets.yml
```

Then use variables like `{{ vault_postgres_password }}` in your
container configs or templates.

### Run with Vault Password

```bash
ansible-playbook playbooks/docker-services.yml --ask-vault-pass
```

Or use a vault password file (never commit this!):

```bash
echo "my-vault-password" > ~/.ansible-vault-pass
chmod 600 ~/.ansible-vault-pass
ansible-playbook playbooks/docker-services.yml --vault-password-file ~/.ansible-vault-pass
```

### Edit or Rotate the Vault

```bash
ansible-vault edit vault/secrets.yml
ansible-vault rekey vault/secrets.yml  # change password
```

---

## Templates: Dynamic Config Files

Ansible's `template` module processes Jinja2 templates with host
variables. This is invaluable for service configs that differ per host.

### Example: Prometheus Target Config

```jinja
# roles/prometheus/templates/prometheus.yml.j2
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets:
{% for host in groups['docker_hosts'] %}
        - '{{ hostvars[host].ansible_default_ipv4.address }}:9100'
{% endfor %}

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

### Task to Deploy Template

```yaml
- name: Deploy Prometheus config
  template:
    src: prometheus.yml.j2
    dest: /opt/prometheus/prometheus.yml
    owner: nobody
    group: nogroup
    mode: '0644'
  notify: restart prometheus
```

Ansible replaces `{{ groups['docker_hosts'] }}` with the actual IPs
from your inventory at runtime. Add a new host to the inventory, run
the playbook, and Prometheus discovers it automatically.

---

## Running Playbooks: Common Workflows

```bash
# Ping all hosts without applying changes (test connectivity)
ansible all -m ping

# Gather facts without running tasks
ansible all -m setup

# Run system baseline on everything
ansible-playbook playbooks/system-base.yml

# Deploy Docker services to one host only
ansible-playbook playbooks/docker-services.yml -l docker-01

# Deploy with secrets
ansible-playbook playbooks/site.yml --ask-vault-pass

# Check mode — see what would change without applying
ansible-playbook playbooks/site.yml --check --diff

# Limit to specific tags
ansible-playbook playbooks/docker-services.yml --tags networks,volumes

# See playbook with step-by-step confirmation
ansible-playbook playbooks/site.yml --step
```

The `--check --diff` combination is incredibly useful. It shows exactly
which files would change and how, without touching anything. Run this
before any production change.

---

## Full Site Playbook

Tie everything together with a master playbook:

```yaml
# playbooks/site.yml
---
- name: Apply system baseline to all hosts
  import_playbook: system-base.yml

- name: Deploy Docker on designated hosts
  import_playbook: docker-services.yml
  when: inventory_hostname in groups['docker_hosts']

- name: Configure monitoring
  import_playbook: monitoring.yml
  when: inventory_hostname in groups['monitoring_hosts']
```

Now a single command manages your entire homelab:

```bash
ansible-playbook playbooks/site.yml
```

A fresh Proxmox LXC goes from a bare Debian install to running
Postgres, Prometheus, Grafana, and Nginx in about 90 seconds with
Ansible. No manual SSH, no copy-pasting, no "I forgot to install
that package."

---

## Git Workflow for Playbooks

Your Ansible project belongs in Git. The structure is simple:

```bash
cd ~/homelab-ansible
git init
git add .
git commit -m "Initial Ansible homelab project"

# .gitignore
echo "vault-password-file" >> .gitignore
echo "*.retry" >> .gitignore

git add .gitignore
git commit -m "Add gitignore"
```

Commit the encrypted `vault/secrets.yml` — it's safe because it's
encrypted. Only share the vault password with trusted operators via a
secure channel (or store it in your password manager).

When you need to rebuild a host after a disk failure or migrate to new
hardware:

```bash
git clone git@github.com:you/homelab-ansible.git
cd homelab-ansible
ansible-playbook playbooks/site.yml --ask-vault-pass
```

That's it. Your entire infrastructure, restored from a single `git
clone`.

---

## Pro Tips

**Use `--diff` liberally.** Always run `ansible-playbook --check --diff`
before applying changes to production services. It catches mistakes.

**Start small.** Don't write a 200-line playbook on day one. Write a
playbook that sets the hostname and installs htop. Then add Docker.
Then add one container. Build incrementally.

**Leverage `gather_facts: no` for speed.** If a playbook doesn't need
system facts (e.g., it just deploys containers by name), disable fact
gathering to save ~5 seconds per host.

**Use tags on everything.** Tags let you run specific parts of a
playbook without the full 10-minute run. Tag `docker`, `ufw`,
`monitoring`, etc.

**Ansible pull for unattended hosts.** If a host reboots but isn't
reachable by your control node, run `ansible-pull` from cron on the
target. It checks out your Git repo and applies the playbook locally.

```bash
# Target host's crontab — check and apply every 30 minutes
*/30 * * * * /usr/bin/ansible-pull -U https://github.com/you/homelab-ansible.git playbooks/site.yml --vault-password-file ~/.vault-pass
```

**Fragile hosts get `any_errors_fatal: true`.** If a misconfigured
host crashes during the playbook, stop immediately instead of
continuing to wreck other hosts.

---

## What's Next

You now have a project skeleton, a Docker deployment playbook, secret
management with ansible-vault, and Jinja2 templating for dynamic configs.
The next step is building out roles — reusable task bundles for common
services like Traefik, Prometheus/Grafana, Postgres, and WireGuard.

In a follow-up post, I'll cover writing reusable Ansible roles,
handling RouterOS via the community.routeros collection, and using
Semaphore or AWX for a web UI over your playbooks.

For now: clone your inventory, write a system baseline playbook, and
run it against your least-critical host. You'll be automating your
entire homelab inside an afternoon.
