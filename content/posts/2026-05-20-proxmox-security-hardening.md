---
title: "Proxmox VE Security Hardening — Firewall, 2FA, and Fail2ban"
description: "Harden your Proxmox VE host with the Proxmox firewall, TOTP two-factor authentication, Fail2ban, SSH lockdown, AppArmor, and automatic security updates — step-by-step for homelab and production."
date: 2026-05-20T16:00:00-04:00
tags:
  - proxmox
  - security
  - firewall
  - linux
keywords:
  - Proxmox VE security hardening guide homelab
  - Proxmox firewall datacenter security groups
  - two-factor authentication Proxmox TOTP setup
  - Fail2ban Proxmox VE API brute force protection
  - SSH hardening Proxmox host key-based authentication
  - AppArmor Proxmox confinement profiles
  - automatic security updates Proxmox unattended-upgrades
summary: "A comprehensive Proxmox VE hardening guide covering firewall rules, TOTP 2FA, Fail2ban, SSH lockdown, AppArmor, and unattended upgrades — secure your hypervisor beyond default settings."
canonical: "https://blog.gntech.me/posts/proxmox-security-hardening/"
---

Every week someone posts on r/Proxmox asking about security best
practices — and with good reason. The default Proxmox VE
installation is functional but not hardened. On a fresh install,
the web UI listens on port 8006 without rate limiting, SSH
accepts password authentication, and the built-in firewall is
disabled.

If your hypervisor gets compromised, every VM and container on
it is compromised too. Proxmox runs as root, so a breach means
full host access.

This guide covers seven concrete hardening steps that apply to
Proxmox VE 8.x — the same measures used in production
environments, adapted for homelab budgets:

1. Enable and configure the Proxmox firewall
2. Set up TOTP two-factor authentication
3. Install and configure Fail2ban for the web UI
4. Harden SSH access
5. Confine services with AppArmor
6. Enable automatic security updates
7. Audit and verify the configuration

---

## Step 1 — Enable and Configure the Proxmox Firewall

Proxmox ships with a three-layer firewall model: datacenter,
node, and VM/CT. The datacenter layer sets the default policy
for all nodes, and each node can override. This is your first
and most important layer.

### Enable the Datacenter Firewall

```bash
# SSH into your Proxmox host
ssh root@pve-host

# Enable the firewall at the datacenter level
pve-firewall set --enable 1

# Or through the config file directly
echo "1" > /etc/pve/firewall/dc.fw
```

Verify it is active:

```bash
pve-firewall status
```

Expected output: `Status: enabled/running`

### Define Datacenter Default Rules

Edit `/etc/pve/firewall/dc.fw`:

```ini
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: ACCEPT

[RULES]
# Allow established connections
IN ACCEPT -state ESTABLISHED,RELATED
# Allow ICMP (ping)
IN ACCEPT -icmp-type echo-request -p icmp -log nolog
# Allow web UI access from management subnet
IN ACCEPT -source 10.0.20.0/24 -dest +pveproxy -log nolog
# Allow SSH from management subnet
IN ACCEPT -source 10.0.20.0/24 -dport 22 -p tcp -log nolog
# Allow VNC console access
IN ACCEPT -source 10.0.20.0/24 -dport 5900-5999 -p tcp -log nolog
# Cluster communication (if clustered)
IN ACCEPT -source 10.0.20.0/24 -dport 5405:5412 -p udp -log nolog
# SPICE console
IN ACCEPT -source 10.0.20.0/24 -dport 3128 -p tcp -log nolog
# Allow HTTP redirect to HTTPS
IN ACCEPT -source 10.0.20.0/24 -dport 80 -p tcp -log nolog
# Drop everything else
IN DROP -log nolog
```

Replace `10.0.20.0/24` with your management subnet. The
`+pveproxy` macro expands to the default Proxmox web UI ports
(8006 for HTTPS, 8007 for PBS). Important notes:

- **Do not set `policy_in: DROP` until you have tested** your
  rules. Start with `ACCEPT`, add your allow rules, then switch
  to `DROP`.
- **Always keep SSH access open** from at least one IP range.
  If you lock yourself out, you will need IPMI or physical
  console access.
- **The firewall processes rules top-down.** Place the
  `ESTABLISHED,RELATED` accept rule first.

### Apply Firewall Rules per Node

Each node inherits the datacenter policy but can add
node-specific rules. Create `/etc/pve/nodes/srv1/host.fw`:

```ini
[OPTIONS]
enable: 1

[RULES]
# Allow Proxmox Backup Server traffic to backup host
IN ACCEPT -source 10.0.20.30 -dport 8007 -p tcp -log nolog
# Allow corosync cluster traffic
IN ACCEPT -p udp -dport 5405 -log nolog
```

Apply the rules without rebooting:

```bash
pve-firewall restart
```

### Verify Firewall Rules

```bash
# List all active rules
pve-firewall rules

# Check the log for dropped packets
tail -f /var/log/pve-firewall.log
```

---

## Step 2 — Enable TOTP Two-Factor Authentication

Password-only access to the Proxmox web UI is a single point of
failure. Proxmox VE 8.x supports TOTP (Time-based One-Time
Password) natively — no third-party module needed.

### Enable TOTP for root

```bash
# Install the OTP tools if not already present
apt update && apt install -y oathtool

# Generate a TOTP secret for root
pveum user modify root@pam --otp-type totp
```

This command generates a QR code in the terminal and outputs the
TOTP secret (base32). Scan the QR code with your authenticator
app (Authy, Google Authenticator, Bitwarden, 2FAS).

If the QR code does not render cleanly, you can get the raw
secret:

```bash
pveum user otp-secret root@pam
```

Copy the base32 secret and add it manually to your authenticator
app.

### Verify TOTP Works

Log out of the web UI and log back in as `root@pam`. You should
see a second field for the TOTP code after entering your
password.

Test from the CLI:

```bash
pvesh get /access/ticket --username root@pam --password
```

This prompts for your password, then the TOTP code.

### Enable TOTP for Regular Users

Do not log in as `root` for daily administration. Create
individual users and enforce 2FA on those too:

```bash
# Create a user
pveum user add admin@pve --comment "Admin user"
pveum acl modify / --user admin@pve --role Administrator

# Set a password
pveum user password admin@pve

# Enable TOTP
pveum user modify admin@pve --otp-type totp
```

### Create a Backup Code

TOTP recovery is not built into Proxmox. Protect yourself by
creating a backup authentication method:

```bash
# Add a second TOTP entry with a different secret
pveum user modify root@pam --otp-type totp
```

Scan the new QR code with a second device or save the secret
offline. Alternatively, use the Proxmox Datacenter Manager to
maintain a secondary access path.

**⚠️ Warning:** If you lose access to your TOTP device and
have no backup, you will need console access to disable TOTP:

```bash
pveum user modify root@pam --otp-type none
```

---

## Step 3 — Install and Configure Fail2ban

The Proxmox web UI and API have no built-in rate limiting. A bot
can hammer the login endpoint indefinitely. Fail2ban fills this
gap by monitoring the Proxmox auth log and temporarily banning
IPs after repeated failures.

### Install Fail2ban

```bash
apt update && apt install -y fail2ban
```

### Create the Proxmox Jail

Create `/etc/fail2ban/jail.d/proxmox.conf`:

```ini
[proxmox]
enabled  = true
port     = http,https,8006
filter   = proxmox
logpath  = /var/log/pveproxd.log
maxretry = 3
bantime  = 3600
findtime = 600
```

This configuration bans an IP for 1 hour after 3 failed login
attempts within 10 minutes. Adjust `bantime` and `maxretry` to
your tolerance — 3600 seconds (1 hour) is reasonable for a
homelab. Production environments often use 24 hours.

### Create the Filter Definition

Create `/etc/fail2ban/filter.d/proxmox.conf`:

```ini
[Definition]
failregex = ^.*authentication failure;.*rhost=<HOST>.*$
            ^.*pveproxy.*failed authentication.*from: <HOST>.*$
ignoreregex =
```

This matches the two most common failure patterns in
`/var/log/pveproxd.log`. Test it:

```bash
fail2ban-regex /var/log/pveproxd.log /etc/fail2ban/filter.d/proxmox.conf
```

You should see a match count. If it shows zero, check the log
format with:

```bash
grep "authentication failure" /var/log/pveproxd.log | head -5
```

### Add an SSH Jail (Optional but Recommended)

Create `/etc/fail2ban/jail.d/sshd.conf`:

```ini
[sshd]
enabled  = true
port     = ssh
logpath  = %(sshd_log)s
maxretry = 5
bantime  = 3600
findtime = 600
```

### Start and Enable Fail2ban

```bash
systemctl enable --now fail2ban
fail2ban-client status
```

You should see both `proxmox` and `sshd` jails listed. Check the
Proxmox jail specifically:

```bash
fail2ban-client status proxmox
```

---

## Step 4 — Harden SSH Access

SSH is the most common attack vector on any Linux server.
Proxmox nodes are no exception.

### Disable Password Authentication

Edit `/etc/ssh/sshd_config.d/hardening.conf`:

```ini
# Disable password auth — keys only
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no

# Use only modern key types
PubkeyAcceptedAlgorithms ssh-ed25519,rsa-sha2-512
HostKeyAlgorithms ssh-ed25519,rsa-sha2-512

# Restrict login to specific users
AllowUsers root admin

# Timeouts
ClientAliveInterval 300
ClientAliveCountMax 2

# Disable root login with password (already covered above, be explicit)
PermitRootLogin prohibit-password

# Use only SSH protocol 2
Protocol 2

# Disable X11 forwarding unless needed
X11Forwarding no

# Limit max auth attempts
MaxAuthTries 3
MaxSessions 10
```

Apply the changes:

```bash
systemctl restart sshd
```

**Before you close your current SSH session**, open a second
terminal and test that key-based authentication still works:

```bash
ssh -o PasswordAuthentication=no root@pve-host
```

Keep the first session open until you have confirmed the new
session works.

### Change the SSH Port (Optional)

Changing the SSH port from 22 reduces automated attack noise:

```ini
Port 2222
```

Update your firewall rules and Fail2ban jail to match, then
restart SSH. This is security through obscurity — it stops bots
but not targeted attacks. Pair it with key-only auth for real
security.

### Generate and Deploy Ed25519 Keys

If you are still using RSA 2048-bit keys, upgrade today:

```bash
ssh-keygen -t ed25519 -a 100 -f ~/.ssh/id_ed25519 -C "homelab-$(date +%Y-%m-%d)"
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@pve-host
```

Ed25519 keys are faster, smaller, and more secure than RSA.
The `-a 100` flag runs 100 KDF rounds on the key for extra
protection of the private key at rest.

---

## Step 5 — Confine Services with AppArmor

Proxmox ships with AppArmor profiles for key services, but they
are not always enforced by default on all installations.

### Check AppArmor Status

```bash
aa-status
```

Look for these Proxmox-related profiles:

- `lxc-container-default`
- `lxc-container-default-with-nesting`
- `pve-firewall`
- `pveproxy`

### Enable AppArmor Enforcement

If a profile is in complain mode instead of enforce:

```bash
# Set LXC profiles to enforce
aa-enforce /etc/apparmor.d/lxc-container-default
aa-enforce /etc/apparmor.d/lxc-container-default-with-nesting

# Reload AppArmor
systemctl reload apparmor
```

Verify:

```bash
aa-status | grep -E "(lxc|pve)"
```

All profiles should show "enforce" mode, not "complain."

### Audit AppArmor Denials

AppArmor denials log to the kernel ring buffer:

```bash
dmesg | grep -i apparmor | grep -i denied | tail -10
```

Or check syslog:

```bash
grep "apparmor.*DENIED" /var/log/syslog | tail -10
```

If a legitimate service triggers denials, update the profile
or add a local override in
`/etc/apparmor.d/local/`. Do not disable AppArmor.

---

## Step 6 — Enable Automatic Security Updates

Proxmox does not install security updates automatically by
default. In a homelab where you do not log in daily, this means
known CVEs can sit unpatched for weeks.

### Install Unattended-Upgrades

```bash
apt update && apt install -y unattended-upgrades apt-listchanges
```

### Configure for Proxmox

Edit `/etc/apt/apt.conf.d/50unattended-upgrades`:

```ini
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
    "Proxmox:${distro_codename}-pve-no-subscription";
    "Proxmox:${distro_codename}-pbs-no-subscription";
};

Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
```

Key points for Proxmox:

- **Include `pve-no-subscription`** in the allowed origins.
  Without it, Proxmox-specific packages (pve-kernel, qemu-server)
  will never be auto-updated.
- **Set `Automatic-Reboot` to `false`** — a kernel update should
  never reboot your hypervisor silently. Reboot manually during
  your maintenance window.
- **Enable `Remove-Unused-Kernel-Packages`** to keep `/boot`
  from filling up with old kernels.

### Configure Automatic Download

Edit `/etc/apt/apt.conf.d/20auto-upgrades`:

```ini
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
```

### Test the Configuration

```bash
# Dry run
unattended-upgrades --dry-run --verbose

# Check the log
cat /var/log/unattended-upgrades/unattended-upgrades.log
```

---

## Step 7 — Audit and Verify

Run a quick audit to confirm everything is in place:

```bash
#!/bin/bash
# proxmox-audit.sh — Run as root

echo "=== Firewall Status ==="
pve-firewall status 2>/dev/null || echo "FAIL"

echo ""
echo "=== TOTP for root ==="
pveum user list --output-format yaml | grep -A2 "root@pam" | grep otp
echo "(empty = no TOTP configured)"

echo ""
echo "=== Fail2ban Status ==="
fail2ban-client status proxmox 2>/dev/null | grep -E "Status|Banned" || echo "FAIL or not installed"

echo ""
echo "=== SSH Config ==="
grep -E "^(PasswordAuthentication|PermitRootLogin|Port)" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -v "no$"

echo ""
echo "=== AppArmor ==="
aa-status 2>/dev/null | grep -E "profiles are in enforce" || echo "AppArmor not active"

echo ""
echo "=== Unattended Upgrades ==="
systemctl is-active unattended-upgrades 2>/dev/null || echo "FAIL"
```

Save this as `/root/proxmox-audit.sh` and run it monthly:

```bash
bash /root/proxmox-audit.sh
```

---

## Summary

A hardened Proxmox host is not difficult to achieve, but it
requires deliberate configuration of layers that Proxmox leaves
open by default:

| Layer | Default | Hardened |
|-------|---------|----------|
| Firewall | Disabled | Datacenter DROP policy, management-subnet-only |
| Authentication | Password only | TOTP two-factor |
| Rate limiting | None | Fail2ban, 3 attempts → 1h ban |
| SSH | Password + root login | Key-only, restricted users, ed25519 |
| Service confinement | Complain (some) | Enforce mode |
| Updates | Manual | Daily security, manual reboot |
| Audit | None | Monthly audit script |

Each step builds on the others. The firewall limits who can
reach the services. 2FA protects against credential theft.
Fail2ban blocks brute-force attempts at the network level.
SSH hardening eliminates password guessing entirely. AppArmor
contains any service compromise. And automatic updates ensure
known vulnerabilities are patched before they are exploited.

Start with the firewall and SSH hardening — those two steps
alone eliminate 90% of common attack vectors. Add 2FA and
Fail2ban next. Then schedule automatic updates and run a
monthly audit.

Your hypervisor is the foundation of your entire homelab.
Hardening it is not optional — it is the single most impactful
security improvement you can make.
