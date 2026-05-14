---
title: "Windows Server 2025 DNS Server Replication — AD-Integrated Zones"
description: "Configure Windows Server 2025 DNS servers with AD-integrated zone replication across DC01 and DC02, including GUI and Server Core steps, reverse zones, forwarders, and verification."
date: 2026-05-14T03:51:00-04:00
tags:
  - windows-server
  - dns
  - active-directory
  - homelab
  - networking
keywords:
  - Windows Server 2025 DNS replication
  - AD integrated DNS zones
  - DNS Server replication Active Directory
  - configure DNS Windows Server 2025
  - dcdiag DNS verification
  - DNS SRV records Active Directory
summary: "Step-by-step Windows Server 2025 DNS replication guide: AD-integrated zones, DNS role install, forward/reverse zones, forwarders, secure dynamic updates, GUI and Server Core paths, and verification."
canonical: "https://gntech.dev/posts/windows-server-2025-dns-replication/"
cover:
  image: "/images/posts/windows-server-2025-dns-replication/dns-replication-topology.svg"
  alt: "Windows Server 2025 DNS replication topology with DC01 and DC02 hosting AD-integrated DNS zones"
  caption: "AD-integrated DNS zone replication across two domain controllers"
---

DNS is not optional in Active Directory. Domain joins, Kerberos, LDAP,
Group Policy, Global Catalog discovery, and replication all depend on DNS
SRV records. If DNS is wrong, Active Directory looks broken even when the
DCs are healthy.

This guide configures Windows Server 2025 DNS with Active
Directory-integrated replication between `DC01` and `DC02`. It covers the
GUI path, the Server Core/PowerShell path, forward and reverse zones,
secure dynamic updates, DNS forwarders, client DNS settings, and real
verification.

![Windows Server 2025 DNS replication topology](/images/posts/windows-server-2025-dns-replication/dns-replication-topology.svg)

> **Image placeholders to add later:**
>
> - Screenshot: Server Manager DNS role installed on both DCs
> - Screenshot: DNS Manager showing `corp.gntech.local` on `DC01`
> - Screenshot: zone properties showing **Store the zone in Active Directory**
> - Screenshot: replication scope set to domain DNS servers
> - Screenshot: secure dynamic updates enabled
> - Screenshot: reverse lookup zone creation wizard
> - Screenshot: DNS forwarders tab
> - Screenshot: `_msdcs`, `_sites`, `_tcp`, and `_udp` SRV folders
> - Screenshot: `Resolve-DnsName`, `dcdiag /test:dns`, and `repadmin` success

## GUI vs Server Core Path

This guide covers both styles:

- **Desktop Experience / GUI:** DNS Manager, Server Manager, zone wizards, and
  properties dialogs.
- **Server Core / PowerShell:** `Install-WindowsFeature`, `Add-DnsServerPrimaryZone`,
  `Set-DnsServerPrimaryZone`, `Resolve-DnsName`, and `dcdiag`.

Use GUI when documenting screenshots. Use PowerShell when building repeatable
Windows infrastructure.

## Target Design

| Item | Value |
|------|-------|
| Domain | `corp.gntech.local` |
| DNS/DC 1 | `DC01` / `10.0.20.10` |
| DNS/DC 2 | `DC02` / `10.0.20.11` |
| Forward zone | `corp.gntech.local` |
| Reverse zone | `20.0.10.in-addr.arpa` |
| Replication type | AD-integrated |
| Replication scope | Domain DNS servers |
| Dynamic updates | Secure only |
| Client DNS | `10.0.20.10`, `10.0.20.11` |

For Active Directory, the cleanest DNS replication model is
AD-integrated DNS. The zone lives in AD DS and replicates through Active
Directory replication. Any domain controller running the DNS Server role
can answer the zone, and updates can be accepted securely.

## Pre-Checks

Before touching DNS, verify both domain controllers are healthy:

```powershell
Get-ADDomainController -Filter * |
  Select-Object HostName,IPv4Address,IsGlobalCatalog

repadmin /replsummary
dcdiag /test:dns /s:DC01
dcdiag /test:dns /s:DC02
```

Expected:

- `DC01` and `DC02` are listed
- replication has no failures
- DNS tests pass or only show non-critical external forwarder warnings

## Install DNS Server Role

If DNS was installed during DC promotion, this is already done. Verify first:

```powershell
Get-WindowsFeature DNS
```

### GUI: Server Manager

1. Open **Server Manager**.
2. Go to **Manage → Add Roles and Features**.
3. Select the local server.
4. Select **DNS Server**.
5. Accept management tools and install.

> **Image placeholder:** Add screenshot of the DNS Server role selected in
> Server Manager.

### Server Core / PowerShell

```powershell
Install-WindowsFeature DNS -IncludeManagementTools
```

Verify service status:

```powershell
Get-Service DNS
```

Expected:

```text
Running
```

## Create or Confirm the Forward Zone

If this domain was created with AD DS, the forward zone probably already
exists. Check it:

```powershell
Get-DnsServerZone -ComputerName DC01
Get-DnsServerZone -ComputerName DC02
```

Expected zone:

```text
corp.gntech.local
```

### GUI: DNS Manager

1. Open **Server Manager → Tools → DNS**.
2. Expand `DC01` → **Forward Lookup Zones**.
3. Confirm `corp.gntech.local` exists.
4. Right-click the zone → **Properties**.
5. Confirm **Type** is **Active Directory-Integrated**.
6. Confirm **Dynamic updates** is **Secure only**.
7. Click **Replication** and select the domain DNS replication scope.

> **Image placeholder:** Add screenshot of zone properties showing
> AD-integrated storage and secure dynamic updates.

### Server Core / PowerShell

If the zone does not exist, create it as AD-integrated:

```powershell
Add-DnsServerPrimaryZone \
  -Name "corp.gntech.local" \
  -ReplicationScope "Domain" \
  -DynamicUpdate "Secure"
```

If the zone exists, enforce secure dynamic updates:

```powershell
Set-DnsServerPrimaryZone \
  -Name "corp.gntech.local" \
  -DynamicUpdate "Secure"
```

Check the zone:

```powershell
Get-DnsServerZone -Name "corp.gntech.local" |
  Select-Object ZoneName,ZoneType,IsDsIntegrated,DynamicUpdate,ReplicationScope
```

## Create the Reverse Lookup Zone

Reverse DNS improves troubleshooting and logging. It is not required for
AD logons, but it is worth configuring.

### GUI: DNS Manager

1. Open **DNS Manager**.
2. Right-click **Reverse Lookup Zones** → **New Zone**.
3. Choose **Primary zone**.
4. Check **Store the zone in Active Directory**.
5. Choose replication to DNS servers in the domain.
6. Choose **IPv4 Reverse Lookup Zone**.
7. Enter network ID `10.0.20`.
8. Allow **Secure only** dynamic updates.

> **Image placeholder:** Add screenshot of reverse lookup zone creation for
> `10.0.20.0/24`.

### Server Core / PowerShell

```powershell
Add-DnsServerPrimaryZone \
  -NetworkId "10.0.20.0/24" \
  -ReplicationScope "Domain" \
  -DynamicUpdate "Secure"
```

Verify:

```powershell
Get-DnsServerZone | Where-Object ZoneName -like "*in-addr.arpa"
```

## Add Static Records for Infrastructure

Most domain members register dynamically. Infrastructure records should
be explicit.

```powershell
Add-DnsServerResourceRecordA \
  -ZoneName "corp.gntech.local" \
  -Name "router" \
  -IPv4Address "10.0.20.1" \
  -CreatePtr

Add-DnsServerResourceRecordA \
  -ZoneName "corp.gntech.local" \
  -Name "srv1" \
  -IPv4Address "10.0.20.30" \
  -CreatePtr
```

Verify:

```powershell
Resolve-DnsName router.corp.gntech.local -Server 10.0.20.10
Resolve-DnsName router.corp.gntech.local -Server 10.0.20.11
Resolve-DnsName 10.0.20.1 -Server 10.0.20.10
```

## Configure Forwarders

Clients should ask AD DNS. AD DNS should forward internet queries.

### GUI: DNS Manager

1. Right-click the DNS server → **Properties**.
2. Open **Forwarders**.
3. Add upstream resolvers, for example `1.1.1.1` and `9.9.9.9`.
4. Repeat on both DCs, or configure through PowerShell.

> **Image placeholder:** Add screenshot of DNS forwarders configured on `DC01`
> and `DC02`.

### Server Core / PowerShell

```powershell
Set-DnsServerForwarder \
  -ComputerName DC01 \
  -IPAddress 1.1.1.1,9.9.9.9

Set-DnsServerForwarder \
  -ComputerName DC02 \
  -IPAddress 1.1.1.1,9.9.9.9
```

Verify:

```powershell
Get-DnsServerForwarder -ComputerName DC01
Get-DnsServerForwarder -ComputerName DC02
```

## Client DNS Configuration

Domain-joined clients must use AD DNS first. Configure DHCP option 6 or
static client DNS with both DCs:

```text
Preferred DNS: 10.0.20.10
Alternate DNS: 10.0.20.11
```

Do not hand out public DNS servers directly to Windows clients in an AD
domain. Public DNS cannot resolve `_ldap._tcp.dc._msdcs.corp.gntech.local`.

## Verify DNS Replication

Create a test record on `DC01`:

```powershell
Add-DnsServerResourceRecordA \
  -ComputerName DC01 \
  -ZoneName "corp.gntech.local" \
  -Name "dnsrep-test" \
  -IPv4Address "10.0.20.250"
```

Force AD replication:

```powershell
repadmin /syncall /AdeP
```

Query both DNS servers:

```powershell
Resolve-DnsName dnsrep-test.corp.gntech.local -Server 10.0.20.10
Resolve-DnsName dnsrep-test.corp.gntech.local -Server 10.0.20.11
```

Remove the test record:

```powershell
Remove-DnsServerResourceRecord \
  -ComputerName DC01 \
  -ZoneName "corp.gntech.local" \
  -RRType A \
  -Name "dnsrep-test" \
  -Force
```

Force replication again and verify it disappears from both servers.

## Verify AD SRV Records

These records are what domain clients actually use:

```powershell
Resolve-DnsName _ldap._tcp.dc._msdcs.corp.gntech.local -Type SRV -Server 10.0.20.10
Resolve-DnsName _ldap._tcp.dc._msdcs.corp.gntech.local -Type SRV -Server 10.0.20.11
Resolve-DnsName _kerberos._tcp.corp.gntech.local -Type SRV -Server 10.0.20.10
Resolve-DnsName _gc._tcp.corp.gntech.local -Type SRV -Server 10.0.20.11
```

Expected: records for both domain controllers where appropriate.

## Run DCDIAG DNS Tests

```powershell
dcdiag /test:dns /v /s:DC01
dcdiag /test:dns /v /s:DC02
```

A healthy result validates delegation, dynamic updates, SRV records, and
basic DNS service health.

## Verify Replication Layer

Because AD-integrated DNS rides AD replication, check AD replication too:

```powershell
repadmin /replsummary
repadmin /showrepl DC01
repadmin /showrepl DC02
```

No DNS replication design is healthy if AD replication is failing.

## Standard Secondary Zones vs AD-Integrated Zones

For domain DNS, use AD-integrated zones. Standard primary/secondary DNS
zones still exist, but they replicate by DNS zone transfer, not AD
replication.

Use standard secondary zones only for non-AD DNS designs, DMZ DNS, or
special cases where a non-domain DNS server needs a read-only copy.

For AD domain controllers:

```text
Recommended: AD-integrated DNS zone
Avoid: manual standard primary/secondary zone transfer between DCs
```

## Final Verification Script

```powershell
$Zone = "corp.gntech.local"
$Servers = "10.0.20.10", "10.0.20.11"

Write-Host "== Zones ==" -ForegroundColor Cyan
Get-DnsServerZone | Select-Object ZoneName,ZoneType,IsDsIntegrated,DynamicUpdate

Write-Host "== Forwarders ==" -ForegroundColor Cyan
Get-DnsServerForwarder -ComputerName DC01
Get-DnsServerForwarder -ComputerName DC02

foreach ($Server in $Servers) {
  Write-Host "== Querying $Server ==" -ForegroundColor Cyan
  Resolve-DnsName $Zone -Server $Server
  Resolve-DnsName "_ldap._tcp.dc._msdcs.$Zone" -Type SRV -Server $Server
  Resolve-DnsName "_kerberos._tcp.$Zone" -Type SRV -Server $Server
}

Write-Host "== DCDIAG DNS ==" -ForegroundColor Cyan
dcdiag /test:dns /s:DC01
dcdiag /test:dns /s:DC02

Write-Host "== AD Replication ==" -ForegroundColor Cyan
repadmin /replsummary
```

## Summary

For Windows Server 2025 domain DNS:

1. Run DNS on at least two domain controllers
2. Use AD-integrated zones
3. Use secure dynamic updates
4. Replicate zones to DNS servers in the domain
5. Configure reverse lookup zones
6. Point clients to both AD DNS servers
7. Verify SRV records, `dcdiag /test:dns`, and AD replication

DNS replication is not just a DNS feature in Active Directory. It is AD
replication plus DNS Server health. Validate both.
