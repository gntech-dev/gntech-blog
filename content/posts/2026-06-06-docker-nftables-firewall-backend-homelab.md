---
title: "Docker nftables Firewall Backend — Native Firewall for Containers"
description: "Migrate Docker from iptables to nftables with the native firewall backend. Configure, verify, and troubleshoot Docker nftables support on Debian 13 and Ubuntu 24.04 homelab hosts."
date: 2026-06-06T21:00:00+00:00
tags:
  - docker
  - firewall
  - networking
  - linux
  - security
keywords:
  - Docker nftables firewall backend configuration homelab guide
  - Migrate Docker iptables to nftables native Debian 13
  - Docker Engine 29 nftables experimental firewall setup
  - Docker nftables port publishing NAT rules troubleshooting
  - Linux nftables firewall Docker container isolation best practices
  - Docker daemon.json nftables backend configuration file
  - Debian 13 iptables-nft compatibility Docker networking fix
summary: "Migrate Docker from iptables to the native nftables firewall backend. Configure docker daemon.json for nftables on Debian 13, test port publishing, and troubleshoot common migration issues."
lastmod: 2026-10-30T12:00:00-04:00
---

Docker Engine 29.0.0 introduced an experimental native nftables firewall backend. It is different from using Docker's iptables backend through the `iptables-nft` compatibility tools.

The important differences: Docker creates `ip docker-bridges` and `ip6 docker-bridges` tables, there is **no native nftables DOCKER-USER chain**, and Docker does not enable IP forwarding for you. The backend cannot be enabled while Docker is running in Swarm mode.

Check the documentation for your installed Engine release before migrating. Experimental behavior may change.

## 1. Record the Current State

Use a maintenance window and console access. Restarting Docker can interrupt containers and published services.

```bash
docker version
docker info
sudo nft list ruleset
sudo iptables -S FORWARD
sudo iptables -S DOCKER-USER
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
```

Check `Swarm` in `docker info`. Do not continue on a Swarm host. `iptables --version` reporting `nf_tables` identifies a compatibility frontend, not Docker's selected backend.

Save backups before modifying anything:

```bash
sudo mkdir -p /root/docker-firewall-backup
sudo sh -c 'nft list ruleset > /root/docker-firewall-backup/nftables.rules'
sudo sh -c 'iptables-save > /root/docker-firewall-backup/iptables.rules'
sudo sh -c 'ip6tables-save > /root/docker-firewall-backup/ip6tables.rules'
if sudo test -f /etc/docker/daemon.json; then
  sudo cp -a /etc/docker/daemon.json /root/docker-firewall-backup/daemon.json
fi
```

These snapshots are for review and recovery planning. Do not blindly replay a whole ruleset over a running Docker daemon.

## 2. Prepare Forwarding and Existing Policy

Docker's native nftables backend needs forwarding enabled before it starts bridge networks. On a host with several interfaces, first ensure your firewall blocks unintended forwarding between physical networks.

For IPv4 bridge networking, create a dedicated sysctl file:

```bash
sudo tee /etc/sysctl.d/90-docker-forwarding.conf >/dev/null <<'EOF'
net.ipv4.ip_forward = 1
EOF
sudo sysctl -p /etc/sysctl.d/90-docker-forwarding.conf
```

If you enable Docker IPv6 networking, also plan and configure IPv6 forwarding and routing. Enabling IPv6 forwarding can affect router-advertisement acceptance; do not switch it on blindly on an RA-dependent host.

Review existing `DOCKER-USER` rules and translate required restrictions into your own nftables table. A leftover iptables `FORWARD` policy of `DROP` can still block packets that nftables accepts. Reconcile that policy with your complete host firewall; changing it to `ACCEPT` without replacement restrictions can expose unrelated forwarding.

## 3. Merge the Docker Configuration

Keep Docker firewall-rule creation enabled. Setting `iptables` or `ip6tables` to `false` disables rule creation for **both** backends.

This script preserves existing JSON options and explicitly enables those rule settings. Stop here if their current `false` values support an intentionally managed firewall; migrate that design before changing them.

```bash
sudo mkdir -p /etc/docker
sudo python3 - <<'PYCODE'
import json
from pathlib import Path
path = Path('/etc/docker/daemon.json')
config = json.loads(path.read_text()) if path.exists() else {}
if config.get('iptables') is False or config.get('ip6tables') is False:
    raise SystemExit('Existing firewall-rule disabling detected; review the firewall design first.')
config['firewall-backend'] = 'nftables'
config['iptables'] = True
config['ip6tables'] = True
path.write_text(json.dumps(config, indent=2) + '\n')
PYCODE
sudo dockerd --validate --config-file=/etc/docker/daemon.json
```

A successful validation checks daemon configuration syntax. It does not prove that the host firewall or forwarding policy is correct. Also check for conflicting options supplied through the systemd service command line.

## 4. Restart and Inspect the Actual Tables

```bash
sudo systemctl restart docker
sudo systemctl --no-pager --full status docker
sudo journalctl -u docker -n 80 --no-pager
sudo nft list table ip docker-bridges
sudo nft list table ip6 docker-bridges
```

Inspect Docker's tables, but do not modify them. Their internal chains can change between releases and Docker owns their contents.

## 5. Add Restrictions in a Separate Table

This optional example allows new IPv4 TCP connections to host address `10.0.20.50`, published port `8080`, only from `10.0.10.0/24` through `ens18`. Replace these values. It handles one published endpoint, not your entire firewall.

```bash
sudo tee /root/docker-web8080.nft >/dev/null <<'EOF'
table ip gntech_docker_web8080 {
    chain forward {
        type filter hook forward priority -1; policy accept;
        iifname "ens18" ct state new meta l4proto tcp ct original ip daddr 10.0.20.50 ct original proto-dst 8080 ip saddr != 10.0.10.0/24 counter drop
    }
}
EOF
sudo nft -c -f /root/docker-web8080.nft
sudo nft -f /root/docker-web8080.nft
```

Run once on a host without an existing table of this name. Persist it through your existing nftables management process. Do not add `flush ruleset` to a reload script while Docker is running.

An nftables `accept` verdict in one base chain does not override a `drop` in another base chain. This policy only adds a restriction. Configure IPv6 restrictions separately if the service is published through IPv6.

Rollback of this example alone:

```bash
sudo nft delete table ip gntech_docker_web8080
```

## 6. Test End to End

Start a temporary loopback-only web service on a free port:

```bash
docker run -d --name gntech-nft-test -p 127.0.0.1:18080:80 nginx:alpine
curl --fail --connect-timeout 5 http://127.0.0.1:18080/
docker rm -f gntech-nft-test
```

Then test your actual published services from allowed and blocked remote clients. Verify DNS and outbound access inside an existing application network, and verify inter-container communication. Loopback testing alone does not validate the forwarding filter.

Repeat those checks after a reboot. A successful Docker restart is not enough: forwarding settings and firewall rules must survive boot.

## Roll Back the Backend

Restore the exact previous `daemon.json` backup if one existed. If it did not, remove only the keys added by this guide from the new file. Validate the configuration and restart Docker. Restore your previous custom forwarding policy through its original firewall manager, then verify connectivity and exposure again.

Keep the forwarding sysctl file only if your previous network design needs it. Removing a sysctl file does not immediately reset the running value.

## References

- [Docker: native nftables backend and migration](https://docs.docker.com/engine/network/firewall-nftables/)
- [Docker: packet filtering and firewall-rule disabling](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
