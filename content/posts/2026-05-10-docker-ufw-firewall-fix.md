---
title: "Docker Bypasses UFW — How to Fix Firewall Rules Properly"
description: "Why Docker punches holes in your UFW firewall, the three real solutions in order of preference, and the one approach that actually fixes it without breaking container networking."
date: 2026-05-10T11:00:00-04:00
tags:
  - docker
  - networking
  - firewall
  - ufw
  - security
lastmod: 2026-10-30T12:00:00-04:00
---

Publishing a Docker port can make it reachable even when UFW says incoming traffic is denied. Docker routes published bridge-network traffic through NAT and forwarding rules; UFW's host `INPUT` policy does not provide the access control you might expect.

This guide separates two jobs: limiting where a port is published, and filtering which clients can reach it. Binding to a LAN address reduces exposure, but does **not** make UFW's host-input rules control forwarded container traffic.

## 1. Check the Existing Rules

Run on the Docker host with administrator access:

```bash
docker version
docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ufw status verbose
sudo iptables -S DOCKER-USER
sudo iptables -t nat -S DOCKER
```

The rules below apply to Docker's **iptables backend**, including iptables-nft compatibility mode. If Docker uses its native nftables backend, use the [nftables guide](/posts/2026-06-06-docker-nftables-firewall-backend-homelab/) instead. Do not create a fake `DOCKER-USER` chain to hide a backend mismatch.

## 2. Avoid Publishing Ports You Do Not Need

Services on the same Compose network can communicate by service name without `ports`. A database used only by an application normally needs no host-published port:

```yaml
services:
  database:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/database_password
    secrets:
      - database_password
    volumes:
      - database_data:/var/lib/postgresql/data

secrets:
  database_password:
    file: ./database_password.txt

volumes:
  database_data:
```

Create the password file securely before starting this example. Keep it out of Git. Do not replace an existing database deployment with this sample or change its PostgreSQL major version without a migration plan.

For a service used only by software on the host, bind to loopback:

```yaml
ports:
  - "127.0.0.1:8080:80"
```

For LAN clients, bind to an address actually assigned to the host:

```yaml
ports:
  - "10.0.20.50:8080:80"
```

A LAN binding is **not a source allowlist**. Routed clients may still reach it. Apply a forwarding policy when source restrictions are required, and check IPv6 exposure separately. Docker releases before 28.0.0 also have a documented localhost-publishing caveat for peers on the same layer-2 segment; update older installations.

## 3. Filter One Published Port with DOCKER-USER

This example protects **TCP port 8080 published on 10.0.20.50**, allowing new connections only from `10.0.10.0/24` arriving on `ens18`. Replace all three values before running it.

Use the incoming physical interface, **not** `docker0`. At this hook, destination NAT has already happened, so `--ctorigdst` and `--ctorigdstport` match the original host address and published port.

First save the existing IPv4 rules:

```bash
sudo sh -c 'iptables-save > /root/iptables-before-blog-filter.rules'
```

Add a dedicated chain without flushing any existing policy:

```bash
sudo iptables -N GNTECH-WEB8080
sudo iptables -A GNTECH-WEB8080 -s 10.0.10.0/24 -j RETURN
sudo iptables -A GNTECH-WEB8080 -j DROP
sudo iptables -I DOCKER-USER 1 -i ens18 -p tcp \
  -m conntrack --ctstate NEW \
  --ctorigdst 10.0.20.50 --ctorigdstport 8080 \
  -j GNTECH-WEB8080
```

Run this setup once. If the chain exists, inspect it instead of running the commands again. The jump only handles new connections to this one published endpoint; other forwarding rules remain in force. Existing connections are unaffected.

This example covers IPv4 only. If the service is reachable through IPv6, configure and test an equivalent IPv6 policy or remove its IPv6 publication. Conntrack matching can have a performance cost.

## 4. Verify from Allowed and Blocked Clients

On the host:

```bash
sudo iptables -nvL DOCKER-USER --line-numbers
sudo iptables -nvL GNTECH-WEB8080 --line-numbers
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

From an allowed client and then a client outside the permitted subnet:

```bash
curl --connect-timeout 5 http://10.0.20.50:8080/
```

The allowed request should reach the application; the blocked request should time out. Use a **new connection** for each check. Verify container DNS, outbound access, and application health too. A host-local curl or an `ss` listing alone does not prove that external access is blocked.

## 5. Persistence and Rollback

The commands above are runtime rules. Integrate them into your existing firewall manager so they load after Docker creates `DOCKER-USER`, without duplicating rules. Verify again after reboot and after a Docker restart. Avoid blindly saving and replaying all of Docker's dynamically generated rules.

To remove only this example:

```bash
sudo iptables -D DOCKER-USER -i ens18 -p tcp \
  -m conntrack --ctstate NEW \
  --ctorigdst 10.0.20.50 --ctorigdstport 8080 \
  -j GNTECH-WEB8080
sudo iptables -F GNTECH-WEB8080
sudo iptables -X GNTECH-WEB8080
```

Do not disable Docker's `iptables` or `ip6tables` options as a UFW fix. Those options disable rules Docker needs for networking; they do not transfer container access control to UFW automatically.

## References

- [Docker: packet filtering, firewalls, and UFW](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Docker: iptables chains and original-destination matching](https://docs.docker.com/engine/network/firewall-iptables/)
- [Docker: port publishing and localhost caveat](https://docs.docker.com/engine/network/port-publishing/)
