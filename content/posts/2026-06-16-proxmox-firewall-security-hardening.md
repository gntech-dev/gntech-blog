---
title: "Proxmox Firewall Security Hardening — IPSets, Rules, Cluster Firewall"
description: "Harden Proxmox VE with datacenter-level firewall rules, dynamic IPSets for trusted management networks, fail2ban protection, and cluster-wide security policies."
date: 2026-06-16T17:00:00-04:00
tags:
  - proxmox
  - security
  - networking
  - linux
  - homelab
keywords:
  - Proxmox firewall security hardening homelab
  - Proxmox datacenter firewall rule IPSet configuration
  - Proxmox cluster firewall synchronization default-deny
  - Proxmox fail2ban HTTP API brute-force protection
  - Proxmox NFS firewall rules smb management access
  - Proxmox host firewall logging network segmentation
  - Proxmox VE firewall IPSet management best practices
summary: "Harden Proxmox VE with datacenter firewalls, dynamic IPSets for trusted management networks, cluster-wide security, fail2ban for web UI brute-force protection, and firewall log auditing."
canonical: "https://blog.gntech.me/posts/proxmox-firewall-security-hardening/"
---

The built-in Proxmox VE firewall is one of the most effective security layers you can enable, yet it's frequently overlooked in homelab deployments. A default Proxmox installation leaves the web UI (port 8006) and SSH accessible to every device on the LAN — and worse, if your host has a public IP or a forwarded port, accessible from the entire internet.

Proxmox's firewall operates at four levels: **datacenter** (cluster-wide), **node** (per-host), **VM/CT**, and **SDN**. Policy inherits downward — a datacenter-level deny applies to every node and VM unless explicitly overridden. With nftables as the backend since Proxmox VE 8.x, the firewall is fast, modern, and fully manageable via CLI or API.

This guide walks through a production-ready harden: default-deny datacenter policy, IPsets for trusted management networks, host-level segmentation, fail2ban for brute-force prevention, and audit logging.

## Firewall Architecture and Enabling the Firewall

The Proxmox firewall is an nftables wrapper managed through `pve-firewall` and `pveproxy`. Each node runs its own nftables ruleset, but the datacenter scope allows you to push consistent rules across your entire cluster.

To confirm the service status:

```bash
systemctl status pve-firewall
```

If it's not running or disabled, enable it system-wide:

```bash
systemctl enable --now pve-firewall
```

Or enable it through the API. Start with the datacenter level:

```bash
pvesh set /cluster/firewall/options -enable 1
```

Repeat for each node if needed, but the datacenter enable flag triggers firewall activation on all cluster nodes.

## Datacenter-Level Default-Deny Policy

The single most impactful change: switch the datacenter firewall from default-allow to default-deny.

```bash
pvesh set /cluster/firewall/options -policy_in DROP
pvesh set /cluster/firewall/options -policy_out DROP
```

Once applied, **no inbound traffic reaches any node** unless an explicit rule permits it. Your Proxmox web UI will become unreachable immediately — don't panic. You need to add allow rules first.

### Allow Management Access via Datacenter Rules

Add rules for SSH and the Proxmox web UI, scoped to your management network. Using a CIDR directly:

```bash
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --dport 22 --proto tcp --type in
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --dport 8006 --proto tcp --type in
```

Allow ICMP (ping) for network troubleshooting:

```bash
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --proto icmp --type in
```

### Allow Cluster and Storage Traffic

If you run a Proxmox cluster, the nodes need to communicate on specific ports. Add rules for corosync (multicast), SSH replication, and NFS/CIFS storage:

```bash
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --dport 5404,5405,5406 --proto udp --type in
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --dport 111,2049 --proto tcp --type in
pvesh create /cluster/firewall/rules --action ACCEPT --source 10.0.20.0/24 --dport 445 --proto tcp --type in
```

## IPSet Management for Trusted Networks

Hardcoding CIDR ranges in every rule is brittle. If your management IP range changes or you add a VPN subnet, you'd need to update every rule. **IPSets solve this** — a named set of CIDRs that rules reference by name. Update the set, and all referencing rules automatically use the new members.

### Create IPsets

```bash
pvesh create /cluster/firewall/ipset mgmt_net
pvesh create /cluster/firewall/ipset/mgmt_net/cidr --cidr 10.0.20.0/24 --comment "Primary management LAN"
pvesh create /cluster/firewall/ipset/mgmt_net/cidr --cidr 10.0.30.0/24 --comment "VPN pool"
```

Create a separate set for backup traffic:

```bash
pvesh create /cluster/firewall/ipset backup_net
pvesh create /cluster/firewall/ipset/backup_net/cidr --cidr 10.0.40.0/24 --comment "Backup server network"
pvesh create /cluster/firewall/ipset/backup_net/cidr --cidr 10.0.20.50/32 --comment "PBS server"
```

### Reference IPsets in Firewall Rules

The IPset name goes in the `--source` field. Proxmox resolves it at apply time:

```bash
pvesh create /cluster/firewall/rules --action ACCEPT --source mgmt_net --dport 22 --proto tcp --type in --comment "SSH from Mgmt network"
pvesh create /cluster/firewall/rules --action ACCEPT --source mgmt_net --dport 8006 --proto tcp --type in --comment "Web UI from Mgmt network"
pvesh create /cluster/firewall/rules --action ACCEPT --source backup_net --dport 8007 --proto tcp --type in --comment "PBS port from backup net"
```

List all IPsets and their members:

```bash
pvesh get /cluster/firewall/ipset
pvesh get /cluster/firewall/ipset/mgmt_net
```

### Remove an IPset Entry

```bash
pvesh delete /cluster/firewall/ipset/mgmt_net/cidr/10.0.20.0%2F24
```

The CIDR is URL-encoded in the path — `%2F` for `/`. This is the standard Proxmox API behavior.

## Host-Level Firewall Rules

Datacenter rules apply everywhere. Host-level rules apply to a single node. Use them for node-specific services that shouldn't be cluster-wide.

```bash
pvesh create /nodes/srv1/firewall/rules --action ACCEPT --source mgmt_net --dport 5900:5999 --proto tcp --type in --comment "VNC/SPICE console ports"
pvesh create /nodes/srv1/firewall/rules --action ACCEPT --source mgmt_net --dport 3128 --proto tcp --type in --comment "Proxmox VE SPICE proxy"
```

Block everything else explicitly (already covered by datacenter default-deny, but explicit documentation helps):

```bash
pvesh create /nodes/srv1/firewall/rules --action DROP --source 0.0.0.0/0 --proto tcp --type in --enable 0 --comment "Default drop logged"
```

The `--enable 0` flag creates the rule in a disabled state — useful for staging before enforcement.

Apply firewall changes on the node:

```bash
pve-firewall restart
```

Check the ruleset:

```bash
nft list ruleset | grep -A5 "pve-firewall"
```

## VM and Container Firewall Policies

Enabling the firewall on a VM or container interface gives you east-west traffic control — preventing a compromised container from probing other hosts.

First, enable the firewall on the VM network interface in the Proxmox web GUI (check the **Firewall** checkbox in the NIC settings), or via CLI:

```bash
pvesh set /nodes/srv1/qemu/100/firewall/options -enable 1
```

### Security Groups

Security groups let you define a reusable set of rules and assign them to multiple VMs:

```bash
pvesh create /cluster/firewall/groups --group webservers
pvesh create /cluster/firewall/groups/webservers/rule --action ACCEPT --proto tcp --dport 80,443 --type in
pvesh create /cluster/firewall/groups/webservers/rule --action ACCEPT --proto tcp --dport 22 --type in --source mgmt_net
pvesh create /cluster/firewall/groups/webservers/rule --action DROP --proto tcp --type in --enable 0 --comment "Drop all other inbound"
```

Then apply the group to a VM:

```bash
pvesh set /nodes/srv1/qemu/100/options -firewall_group webservers
```

Groups compose well with IPsets — use `--source mgmt_net` inside a group rule to restrict SSH access to your management IPset.

## Fail2ban for Proxmox Web UI Brute-Force Protection

Proxmox's web UI (pveproxy) logs authentication failures to `/var/log/pveproxy/access.log`. Hook fail2ban into those logs to ban IPs that hit auth endpoints repeatedly.

### Create the fail2ban Filter

```bash
cat > /etc/fail2ban/filter.d/pveproxy.conf << 'EOF'
[Definition]
failregex = ^<HOST> - .* "(GET|POST) /api2/.*(login|auth|ticket).* HTTP/1\.[01]" 401 .*$
ignoreregex =
EOF
```

### Create the Jail

```bash
cat > /etc/fail2ban/jail.d/pveproxy.conf << 'EOF'
[pveproxy]
enabled = true
port = 8006,https
filter = pveproxy
logpath = /var/log/pveproxy/access.log
maxretry = 5
findtime = 600
bantime = 3600
banaction = nftables-allports
chain = input

[proxmox-ssh]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
findtime = 300
bantime = 86400
banaction = nftables-allports
EOF
```

### Reload and Test

```bash
systemctl restart fail2ban
fail2ban-client status pveproxy
fail2ban-client status proxmox-ssh
```

Test the filter by triggering a failed login:

```bash
curl -k -u "baduser:badpass" https://10.0.20.30:8006/api2/json/access/ticket
```

Then check:

```bash
tail -5 /var/log/pveproxy/access.log
fail2ban-client status pveproxy
```

If fail2ban picks it up, you'll see the failed count increment.

## Firewall Logging and Audit

Every dropped or accepted packet can be logged. Set log level on a per-rule basis:

```bash
pvesh create /cluster/firewall/rules --action LOG --log_level info --type in --comment "Log all inbound INFO"
```

View the firewall log stream:

```bash
journalctl -u pve-firewall -f
```

Or read the log file directly:

```bash
tail -f /var/log/pve-firewall.log
```

A typical log line looks like this:

```
Jun 16 10:23:45 srv1 pve-firewall[1234]: DROP IN=vmbr0 OUT= MAC=... SRC=203.0.113.5 DST=10.0.20.30 LEN=40 TOS=0x00 PREC=0x00 TTL=118 ID=54321 PROTO=TCP SPT=40001 DPT=8006 WINDOW=65535
```

Forward these logs to your monitoring stack. On a Grafana Loki setup:

```bash
# Scrape pve-firewall log via promtail
cat > /etc/promtail/config.yml << 'EOF'
scrape_configs:
  - job_name: pve-firewall
    static_configs:
      - targets: [localhost]
        labels:
          job: pve-firewall
          __path__: /var/log/pve-firewall.log
EOF
```

## Rule Ordering and Best Practices

The Proxmox firewall processes rules first-match. Order matters:

1. Put **explicit allow rules** for trusted sources early
2. Place **log rules** before blocking rules so you see what's denied
3. End with a **catch-all deny** (the default-deny policy covers this at datacenter level)

### Best Practices Checklist

- **Always use IPsets** — never hardcode CIDRs in individual rules
- **Comment every rule** — `--comment "SSH from mgmt VLAN"` saves future-you hours
- **Stage rules with --enable 0** — test before enforcing
- **Document IPset CIDR entries** — use `--comment` on the CIDR add command
- **Check the ruleset periodically:**

```bash
pve-firewall status
nft list ruleset | grep "pve-firewall" | head -30
```

- **Test connectivity after each change** — have a management session open before applying host-level deny rules
- **Enable VM-level firewalls** on any VM exposed to the internet (web servers, game servers)

## Conclusion

The Proxmox VE firewall is a powerful, nftables-based security layer that many homelabs leave disabled. With a datacenter default-deny policy, dynamic IPsets for management networks, host-level segmentation, security groups for VMs, and fail2ban guarding the web UI, you build a defense-in-depth posture that stops automated scanners, limits lateral movement, and keeps your hypervisor accessible only from trusted networks.

Start small: enable the firewall, deploy a `mgmt_net` IPset with your admin LAN and VPN pool, and switch inbound policy to DROP. Everything else builds on that foundation.
