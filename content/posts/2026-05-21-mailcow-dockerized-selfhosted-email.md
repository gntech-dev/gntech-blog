---
title: "Mailcow Dockerized — Self-Hosted Email Server in Your Homelab"
description: "Deploy Mailcow in Docker for a full self-hosted email server with Postfix, Dovecot, Rspamd, and SOGo — includes DNS records, Traefik reverse proxy, and security hardening."
date: 2026-05-21T12:00:00-04:00
tags:
  - docker
  - homelab
  - linux
  - security
  - devops
keywords:
  - Mailcow Dockerized self-hosted email server homelab
  - deploy Mailcow email server Docker Compose
  - Mailcow Traefik reverse proxy integration
  - SPF DKIM DMARC DNS configuration mailcow
  - Postfix Dovecot Rspamd Docker deployment
  - Mailcow SSL Let's Encrypt certificate
  - self-hosted email server security hardening
summary: "Full guide to deploying Mailcow Dockerized in your homelab — from Docker Compose setup and DNS records to Traefik reverse proxy, DKIM signing, and email deliverability tuning."
canonical: "https://blog.gntech.me/posts/2026-05-21-mailcow-dockerized-selfhosted-email/"
---

Running your own email server is one of the most rewarding homelab
projects. You get full control over your data, no privacy-invading
scanning from big providers, unlimited mailboxes, and deep insight
into deliverability. But it is also one of the most complex services
to get right — DNS records, reverse DNS, SPF, DKIM, DMARC, spam
filtering, and security hardening all need to work together.

Mailcow Dockerized solves most of this complexity. It bundles
Postfix (MTA), Dovecot (IMAP/POP3), Rspamd (spam filtering),
SOGo (webmail/CalDAV/CardDAV), and all the supporting services
into a single Docker Compose stack with sensible defaults. You
still need to handle DNS and firewall, but Mailcow eliminates the
pain of manual integration between components.

This guide covers deploying Mailcow on a single Docker host behind
Traefik, configuring all required DNS records, tuning for good
deliverability, and securing the stack.

---

## Requirements

Before starting, make sure you have:

- A Docker host (Debian 12 or Ubuntu 24.04 recommended)
- Docker Engine 24+ and Docker Compose plugin
- A domain you control (e.g., `example.com`)
- Ability to modify DNS records (preferably with API access)
- Ports 25, 465, 587, 993, and 995 open on your firewall
- **Reverse DNS (PTR) record** from your ISP (mandatory for good
  deliverability to Gmail and Outlook)
- Traefik or another reverse proxy (optional but recommended for
  webmail)

### Port Requirements

| Port | Protocol | Service         |
|------|----------|-----------------|
| 25   | SMTP     | Inbound mail    |
| 465  | SMTPS    | Submission (SSL)|
| 587  | SMTP     | Submission (TLS)|
| 993  | IMAPS    | IMAP over SSL   |
| 995  | POP3S    | POP3 over SSL   |
| 80   | HTTP     | Let's Encrypt   |
| 443  | HTTPS    | Webmail         |

Port 25 must be open globally. This is non-negotiable for an email
server — other mail servers need to reach you on port 25. Check
that your ISP does not block inbound port 25 (most residential
ISPs do; business plans usually allow it).

---

## Step 1 — Deploy Mailcow

Clone the repository and run the setup:

```bash
cd /opt
git clone https://github.com/mailcow/mailcow-dockerized
cd mailcow-dockerized
```

Generate the configuration:

```bash
./generate_config.sh
```

This script asks for:

- **Mail server hostname** (FQDN) — e.g., `mail.example.com`
- **Timezone** — use your local timezone (e.g., `America/Santo_Domingo`)
- **HTTP bind** — leave as `0.0.0.0` if Traefik handles termination
- **Skip Let's Encrypt** — set to `n` if Traefik handles TLS externally

If Traefik handles TLS, edit `mailcow.conf` after generation:

```bash
SKIP_LETS_ENCRYPT=y
HTTP_BIND=127.0.0.1
HTTP_PORT=8080
```

This tells Mailcow to bind web services to localhost on port 8080,
so Traefik can proxy to it without exposing HTTP directly.

Pull images and start the stack:

```bash
docker compose pull
docker compose up -d
```

Wait a minute, then verify all containers are running:

```bash
docker compose ps
```

You should see containers for: postfix, dovecot, rspamd, nginx,
sogo, mysql (MariaDB), redis, clamav, unbound (DNS), olefy,
and watchdog. Mailcow is a full stack.

---

## Step 2 — DNS Records

This is the most critical part. Missing or misconfigured DNS
records mean your emails will go to spam — or get rejected entirely.

### A / AAAA Records

```dns
mail.example.com.  IN A     203.0.113.50
mail.example.com.  IN AAAA  2001:db8:1234::50
```

### MX Record

Point the MX to your mail server hostname:

```dns
example.com.  IN MX  10  mail.example.com.
```

Priority 10 is standard for a single server. The trailing dot on
`mail.example.com.` is required by the DNS standard.

### PTR Record (Reverse DNS)

Contact your ISP or use their control panel to set:

```
50.113.0.203.in-addr.arpa.  IN PTR  mail.example.com.
```

Most ISPs with a control panel have a "Reverse DNS" or "PTR"
setting on the IP address page. Without a matching PTR record,
Gmail and Outlook flag your mail as suspicious.

### SPF Record

SPF (Sender Policy Framework) tells receiving servers which IPs
are authorized to send mail for your domain:

```dns
example.com.  IN TXT  "v=spf1 mx ~all"
```

This allows the IPs listed in your MX records to send mail, and
soft-fail everything else. If you send through a third-party
service (Mailgun, SendGrid), include their SPF include too:

```dns
example.com.  IN TXT  "v=spf1 mx include:mailgun.org ~all"
```

### DKIM Record

Mailcow generates DKIM keys automatically. Retrieve them from
the web admin UI or directly:

```bash
docker exec -it $(docker compose ps -q postfix-mailcow) \
  cat /etc/opendkim/keys/example.com/mail.txt
```

Output looks like:

```
mail._domainkey IN TXT "v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA..."
```

Add this exact TXT record to your DNS:

```dns
mail._domainkey.example.com.  IN TXT  "v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA..."
```

### DMARC Record

DMARC tells receivers how to handle mail that fails SPF or DKIM
verification:

```dns
_dmarc.example.com.  IN TXT  "v=DMARC1; p=quarantine; rua=mailto:postmaster@example.com; pct=100"
```

- **`p=quarantine`** — move failing mail to spam (start here)
- **`p=reject`** — reject failing mail outright (after monitoring)
- **`p=none`** — monitor only, no action
- **`rua`** — where aggregate reports are sent

Start with `p=none`, monitor reports for a week, then tighten to
`p=quarantine`. Move to `p=reject` only after you are confident
all legitimate mail is authenticated.

### Verify DNS

```bash
# MX lookup
dig +short MX example.com

# SPF lookup
dig +short TXT example.com

# DKIM lookup
dig +short TXT mail._domainkey.example.com

# DMARC lookup
dig +short TXT _dmarc.example.com
```

All records should resolve before you send a single test email.

---

## Step 3 — Traefik Reverse Proxy Integration

If you run Traefik (as covered in
[this blog's Traefik guide](/posts/2026-05-09-traefik-reverse-proxy-docker/)),
add a Compose override for the webmail interface.

Create `docker-compose.override.yml` in your mailcow directory:

```yaml
services:
  nginx-mailcow:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.mailcow.rule=Host(`mail.example.com`)"
      - "traefik.http.routers.mailcow.entrypoints=websecure"
      - "traefik.http.routers.mailcow.tls.certresolver=letsencrypt"
      - "traefik.http.services.mailcow.loadbalancer.server.port=8080"
    networks:
      - proxy
    depends_on:
      - traefik

networks:
  proxy:
    external: true
```

Restart the stack:

```bash
docker compose up -d
```

This routes `https://mail.example.com` through Traefik with
automatic Let's Encrypt. Mailcow's internal nginx does not
terminate TLS — Traefik handles it at the edge.

**Important:** Disable Mailcow's built-in ACME when using Traefik.
Set `SKIP_LETS_ENCRYPT=y` and `HTTP_BIND=127.0.0.1` in
`mailcow.conf` to prevent port conflicts.

---

## Step 4 — Initial Configuration and Security

### Access the Admin UI

Open `https://mail.example.com` in a browser. The default admin
login is:

- **Username:** `admin`
- **Password:** `moohoo`

Change this immediately in the admin panel under
Configuration → Access → Edit admin.

### Create Mailboxes

Go to Mailboxes → Add mailbox. Enter a full email address
(`user@example.com`) and password. Mailcow automatically creates
the mailbox, IMAP folder structure, and aliases.

### Disable Weak Ciphers

Mailcow's Postfix defaults are reasonable, but you can tighten
them. Edit `data/conf/postfix/extra.cf`:

```
smtpd_tls_protocols = !SSLv2 !SSLv3 !TLSv1 !TLSv1.1
smtpd_tls_mandatory_protocols = !SSLv2 !SSLv3 !TLSv1 !TLSv1.1
smtpd_tls_mandatory_ciphers = high
smtpd_tls_eecdh_grade = ultra
```

Apply changes:

```bash
docker compose restart postfix-mailcow
```

### Rspamd Tuning

Mailcow bundles Rspamd with good defaults. For better spam
filtering, enable additional modules in the Rspamd UI
(`https://mail.example.com/rspamd/`):

- **DMARC Reports** under Configuration → DMARC
- **Surbl / Spamhaus DBL** — already configured
- **Greylisting** — enabled by default; tune the timeout if
  needed (most legitimate mail resends within minutes)

### Set Up Fail2ban (Optional)

Mailcow includes its own fail2ban or you can install it on the
host:

```bash
docker exec -it $(docker compose ps -q watchdog-mailcow) \
  fail2ban-client status
```

The watchdog container monitors SSH, Postfix SASL, and Dovecot
login failures and auto-bans IPs.

---

## Step 5 — Firewall Rules

Open only the ports your mail server needs. A minimal
iptables/nftables ruleset:

```bash
# Inbound SMTP, submission, IMAPS
iptables -A INPUT -p tcp --dport 25 -j ACCEPT
iptables -A INPUT -p tcp --dport 465 -j ACCEPT
iptables -A INPUT -p tcp --dport 587 -j ACCEPT
iptables -A INPUT -p tcp --dport 993 -j ACCEPT
iptables -A INPUT -p tcp --dport 995 -j ACCEPT

# HTTP/HTTPS for webmail
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

**Do not restrict port 25 source IPs.** SMTP servers connect
from anywhere. Rate-limit it instead if you see abuse:

```bash
iptables -A INPUT -p tcp --dport 25 -m state --state NEW \
  -m recent --set --name SMTP
iptables -A INPUT -p tcp --dport 25 -m state --state NEW \
  -m recent --update --seconds 60 --hitcount 20 --name SMTP -j DROP
```

If you have an IPv6 address on your mail server, add equivalent
`ip6tables` rules for all ports.

---

## Step 6 — Testing Deliverability

### SMTP Port Scan

From an external machine, verify your mail server responds on the
expected ports:

```bash
nc -zv mail.example.com 25
nc -zv mail.example.com 587
nc -zv mail.example.com 465
nc -zv mail.example.com 993
```

### Send a Test Email

Use the admin UI to send a test. Then check Mailcow's logs:

```bash
docker compose logs postfix-mailcow | tail -50
```

Look for lines confirming successful delivery:

```
status=sent (250 2.0.0 Ok: queued as ABC123)
```

### Check Rspamd History

In the Rspamd UI (`/rspamd/`), check the History tab. Every
scanned email shows a score, symbols matched, and whether it was
classified as spam or ham.

### Use Mail-Tester

Send a test email to `check@mail-tester.com` from your new
mailbox. It returns a score out of 10 points with detailed
feedback on:

- SPF alignment
- DKIM signature validity
- Reverse DNS match
- SMTP configuration
- Blacklist status

A score above 9/10 is achievable with all DNS records configured
correctly.

### Blacklist Monitoring

Check your IP against common DNSBLs:

```bash
# Check Spamhaus
dig +short 50.113.0.203.zen.spamhaus.org

# Check Barracuda
dig +short 50.113.0.203.b.barracudacentral.org
```

An empty response means you are not listed. If you are listed on
Spamhaus or another blocklist, check your server for open relay
or compromised mailboxes.

---

## Step 7 — Backups

Mailcow stores everything in `./mailcow-dockerized/`. Back up
the entire directory, plus the MariaDB database regularly.

Mailcow includes a built-in backup script:

```bash
cd /opt/mailcow-dockerized
./helper-scripts/backup_and_restore.sh backup all
```

This dumps the SQL database and archives mail data. Schedule it
daily via cron:

```cron
0 3 * * * cd /opt/mailcow-dockerized && ./helper-scripts/backup_and_restore.sh backup all --delete-days 30
```

The `--delete-days 30` flag keeps 30 days of backups automatically.

For off-site protection, sync the backup directory to a remote
server using `rsync` or `rclone`:

```bash
rclone sync /opt/mailcow-dockerized/ backup:mailcow/ --progress
```

---

## Step 8 — Monitoring and Maintenance

### Check Queue Depth

A healthy outbound queue should be near zero:

```bash
docker exec -it $(docker compose ps -q postfix-mailcow) \
  mailq | grep "^[0-9A-F]" | wc -l
```

If the queue grows beyond 100, investigate — you may have a
compromised mailbox sending spam, or a remote server rejecting
your mail.

### Watch Logs

Monitor in real time:

```bash
docker compose logs -f --tail=100
```

### Update Mailcow

Mailcow updates are handled via git:

```bash
cd /opt/mailcow-dockerized
git pull
docker compose pull
docker compose up -d
```

Always check the [Mailcow changelog](https://github.com/mailcow/mailcow-dockerized/releases)
before updating a production deployment.

---

## Troubleshooting

### Port 25 is blocked by ISP

You cannot run a Mailcow inbound server on a residential
connection that blocks port 25. Options:

- **Business ISP plan** — most business fiber includes port 25
- **Relay through a VPS** — relay outgoing mail via a cheap VPS
  using Postfix transport maps
- **Tunnel** — use an SSH tunnel or WireGuard to forward port 25
  through a VPS

### Emails going to spam

Top causes:

1. **Missing reverse DNS** — fix with your ISP
2. **Missing or broken DKIM** — verify with `dig`
3. **SPF too permissive** (`+all` instead of `~all`) — tighten it
4. **IP on a blocklist** — check and delist
5. **Sending from a residential IP range** — much harder to fix;
   consider a relay

### Cannot authenticate to SMTP submission

Ensure your mail client uses:

- **Port 587** with STARTTLS (not port 25)
- **PLAIN or LOGIN** authentication
- **Full email address** as the username (`user@example.com`,
  not just `user`)

---

## Summary

Mailcow Dockerized turns the complexity of running a full email
server into a `git clone` + `docker compose up -d` workflow. The
stack handles Postfix, Dovecot, Rspamd, and webmail integration
out of the box, leaving you with just DNS configuration and
firewall rules to get right.

The essential checklist for a production-ready mail server:

1. Clone Mailcow and generate config with `SKIP_LETS_ENCRYPT=y`
2. Configure A, MX, PTR, SPF, DKIM, and DMARC DNS records
3. Integrate with Traefik for TLS termination on webmail
4. Secure Postfix ciphers and enable Rspamd greylisting
5. Set up daily backups and off-site sync
6. Test deliverability with mail-tester.com

A proper mail server in your homelab means no more depending on
third-party providers for your domain's email. It is not the
simplest project, but it is one of the most empowering.
