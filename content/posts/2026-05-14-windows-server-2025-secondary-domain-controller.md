---
title: "Windows Server 2025 Secondary Domain Controller — Add DC02 to Existing AD"
description: "Add a secondary Windows Server 2025 domain controller to an existing Active Directory domain with AD DS, DNS, Global Catalog, replication, client DNS failover, and full verification."
date: 2026-05-14T03:34:00-04:00
tags:
  - windows-server
  - active-directory
  - dns
  - homelab
  - security
keywords:
  - Windows Server 2025 secondary domain controller
  - add domain controller existing domain
  - additional domain controller AD DS
  - Active Directory replication verification
  - repadmin dcdiag secondary DC
  - DNS failover domain controller
summary: "Step-by-step guide to adding DC02 as a secondary Windows Server 2025 domain controller: preparation, AD DS promotion, DNS, Global Catalog, replication checks, SYSVOL validation, and client failover testing."
canonical: "https://blog.gntech.me/posts/windows-server-2025-secondary-domain-controller/"
cover:
  image: "/images/posts/windows-server-2025-secondary-domain-controller/secondary-dc-topology.svg"
  alt: "Windows Server 2025 secondary domain controller topology with DC01, DC02, replication, DNS, and client failover"
  caption: "Two-domain-controller Active Directory topology"
---

A single domain controller is fine for a lab, but it is still a single
point of failure. If `DC01` is down, clients lose AD DNS, Kerberos,
Group Policy, LDAP, and domain controller discovery. Adding a secondary
domain controller gives the domain redundancy and gives you a safer way
to patch, reboot, or recover the first DC.

This guide adds `DC02` as a Windows Server 2025 domain controller to an
existing domain. It assumes the first DC already exists and is healthy.
If you have not built the first DC yet, start with the primary domain
controller guide first.

![Windows Server 2025 secondary domain controller topology](/images/posts/windows-server-2025-secondary-domain-controller/secondary-dc-topology.svg)

> **Image placeholders to add later:**
>
> - Screenshot: `DC01` health checks before adding `DC02`
> - Screenshot: `DC02` static IP and DNS pointing to `DC01`
> - Screenshot: Server Manager role selection for AD DS on `DC02`
> - Screenshot: AD DS wizard **Add a domain controller to an existing domain**
> - Screenshot: Domain Controller Options with DNS and Global Catalog enabled
> - Screenshot: Replication source / Additional Options page
> - Screenshot: prerequisites check before promoting `DC02`
> - Screenshot: Active Directory Users and Computers showing both DCs
> - Screenshot: DNS Manager showing replicated zones on `DC02`
> - Screenshot: `repadmin`, `dcdiag`, SYSVOL/NETLOGON, and client failover validation

## GUI vs Server Core Path

This guide covers both install styles:

- **Desktop Experience / GUI:** use Server Manager, AD DS Configuration
  Wizard, DNS Manager, Active Directory Users and Computers, and Active
  Directory Sites and Services.
- **Server Core / automation:** use PowerShell commands for repeatable builds,
  remote administration, and clean documentation.

The GUI path is useful for screenshots and learning the workflow. The Server
Core path is better for real repeatable infrastructure.

## Target Design

Example values used here:

| Item | Value |
|------|-------|
| Existing DC | `DC01.gntech.me` |
| Existing DC IP | `10.0.20.10` |
| New DC | `DC02.gntech.me` |
| New DC IP | `10.0.20.11` |
| Domain | `gntech.me` |
| NetBIOS | `CORP` |
| Site | `Default-First-Site-Name` initially |
| Roles on DC02 | AD DS, DNS, Global Catalog |
| Client DNS | Preferred `10.0.20.10`, alternate `10.0.20.11` |

The secondary DC should be on the same reliable server VLAN as the first
DC, or in a separate site if you are testing AD Sites and Services. Do
not put a DC on unstable Wi-Fi, DHCP-only addressing, or storage you do
not trust.

## Pre-Checks on DC01

Do not add another domain controller to a broken domain. First, verify
`DC01` is healthy.

Run on `DC01`:

```powershell
dcdiag /test:dns /v /s:DC01
repadmin /replsummary
repadmin /showrepl DC01
net share | Select-String "SYSVOL|NETLOGON"
netdom query fsmo
```

Expected:

- DNS test passes or only shows non-critical forwarder warnings
- No replication failures
- `SYSVOL` and `NETLOGON` shares exist
- FSMO roles are known and reachable

Check AD and DNS service status:

```powershell
Get-Service NTDS,DNS,DFSR,Netlogon,KDC
Get-ADDomain
Get-ADForest
```

If any core service is stopped, fix that before promoting `DC02`.

## Prepare DC02

Start with a clean Windows Server 2025 install.

### 1. Patch Windows

```powershell
Install-Module PSWindowsUpdate -Force
Get-WindowsUpdate
Install-WindowsUpdate -AcceptAll -AutoReboot
```

Reboot until updates are complete.

### 2. Rename the Server

```powershell
Rename-Computer -NewName "DC02" -Restart
```

After reboot:

```powershell
hostname
```

Expected:

```text
DC02
```

### 3. Configure Static IP

```powershell
New-NetIPAddress \
  -InterfaceAlias "Ethernet" \
  -IPAddress 10.0.20.11 \
  -PrefixLength 24 \
  -DefaultGateway 10.0.20.1
```

For DNS, point `DC02` to the existing domain controller first. This is
important because `DC02` must find the existing AD domain before it can
join or promote.

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10
```

Verify network and DNS:

```powershell
Test-Connection 10.0.20.10 -Count 4
Resolve-DnsName gntech.me
Resolve-DnsName _ldap._tcp.dc._msdcs.gntech.me -Type SRV
```

If SRV lookup fails, stop. Domain promotion depends on AD DNS.

### 4. Check Time Sync

```powershell
w32tm /query /status
w32tm /stripchart /computer:DC01 /samples:5 /dataonly
```

Kerberos requires time to be close. Fix time skew before joining the
domain.

## Join DC02 to the Existing Domain

You can promote a workgroup server directly, but joining first makes
basic DNS, credential, and secure channel problems obvious before AD DS
promotion.

```powershell
Add-Computer \
  -DomainName "gntech.me" \
  -Credential "CORP\Administrator" \
  -Restart
```

After reboot, log in as a domain admin:

```text
CORP\Administrator
```

Verify the secure channel:

```powershell
Test-ComputerSecureChannel -Verbose
whoami /fqdn
```

Expected:

```text
True
```

## Install AD DS on DC02

### GUI: Install the Role with Server Manager

On Windows Server 2025 Desktop Experience:

1. Open **Server Manager**.
2. Go to **Manage → Add Roles and Features**.
3. Choose **Role-based or feature-based installation**.
4. Select `DC02`.
5. Select **Active Directory Domain Services**.
6. Accept the required management tools.
7. Click **Install**.

> **Image placeholder:** Add screenshot of AD DS role selection on `DC02`.

### Server Core / PowerShell: Install the Role

Install the AD DS role and tools:

```powershell
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools
```

Verify:

```powershell
Get-WindowsFeature AD-Domain-Services
```

Expected:

```text
[X] Active Directory Domain Services
```

## Promote DC02 as an Additional Domain Controller

### GUI: Promote with the AD DS Wizard

After the AD DS role installs, Server Manager shows a notification flag.

1. Click the notification flag.
2. Select **Promote this server to a domain controller**.
3. Choose **Add a domain controller to an existing domain**.
4. Enter `gntech.me` and provide domain admin credentials.
5. Keep **Domain Name System (DNS) server** checked.
6. Keep **Global Catalog (GC)** checked.
7. Set the Directory Services Restore Mode password for `DC02`.
8. Pick a replication source or leave it automatic.
9. Review paths and run the prerequisites check.
10. Click **Install** and let `DC02` reboot.

> **Image placeholder:** Add screenshot of the Deployment Configuration page
> showing **Add a domain controller to an existing domain**.
>
> **Image placeholder:** Add screenshot of Domain Controller Options with DNS
> and Global Catalog checked.
>
> **Image placeholder:** Add screenshot of the prerequisites check before
> installation.

### Server Core / PowerShell: Promote with `Install-ADDSDomainController`

Use `Install-ADDSDomainController`. This adds a domain controller to an
existing domain, instead of creating a new forest.

```powershell
$Credential = Get-Credential "CORP\Administrator"
$SafeModePassword = Read-Host \
  -Prompt "Enter Directory Services Restore Mode password for DC02" \
  -AsSecureString

Install-ADDSDomainController \
  -DomainName "gntech.me" \
  -Credential $Credential \
  -InstallDns \
  -NoGlobalCatalog:$false \
  -SafeModeAdministratorPassword $SafeModePassword \
  -NoRebootOnCompletion:$false \
  -Force
```

The server reboots after promotion.

Notes:

- `-InstallDns` installs DNS on `DC02`.
- `-NoGlobalCatalog:$false` makes `DC02` a Global Catalog server.
- The DSRM password is local to this domain controller.
- Do not use `Install-ADDSForest`; that creates a new forest and is the
  wrong command for a secondary DC.

## Set DNS Client Order After Promotion

After `DC02` is promoted and DNS is installed, update DNS client settings
on both DCs.

On `DC01`:

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10,10.0.20.11
```

On `DC02`:

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.11,10.0.20.10
```

This keeps each DC using itself first, with the other DC as backup. Some
admins prefer the partner DC first to avoid DNS island scenarios during
boot. In small homelabs, either pattern can work if both DCs are healthy;
be consistent and test failover.

For clients, set DHCP DNS options to both DCs:

```text
DNS Server 1: 10.0.20.10
DNS Server 2: 10.0.20.11
```

Do not hand out public DNS servers to domain-joined clients. Public DNS
cannot answer AD SRV records.

## Verify DC02 Promotion

Run these checks after the reboot.

### 1. Confirm DC Discovery

From `DC02`:

```powershell
nltest /dsgetdc:gntech.me
nltest /dclist:gntech.me
```

Expected: both `DC01` and `DC02` appear in the domain controller list.

### 2. Verify Domain Controller Object

```powershell
Get-ADDomainController -Filter * |
  Select-Object HostName,IPv4Address,Site,IsGlobalCatalog,OperationMasterRoles
```

Expected:

- `DC01` appears
- `DC02` appears
- `DC02` has `IsGlobalCatalog` set to `True`

### 3. Run DCDIAG on Both DCs

```powershell
dcdiag /v /c /d /e > C:\dcdiag-all-dcs.txt
notepad C:\dcdiag-all-dcs.txt
```

Then run targeted DNS tests:

```powershell
dcdiag /test:dns /v /s:DC01
dcdiag /test:dns /v /s:DC02
```

Focus on:

```text
Advertising
Connectivity
DFSREvent
SysVolCheck
KccEvent
MachineAccount
NetLogons
Services
SystemLog
DNS
```

Short-lived replication warnings immediately after promotion can happen.
Wait a few minutes, force replication, and retest before treating them as
real failures.

### 4. Verify Replication

```powershell
repadmin /replsummary
repadmin /showrepl DC01
repadmin /showrepl DC02
```

A healthy result has no failed replication attempts.

Force synchronization:

```powershell
repadmin /syncall /AdeP
```

Then check again:

```powershell
repadmin /replsummary
```

### 5. Verify SYSVOL and NETLOGON on DC02

```powershell
net view \\DC02
net share
```

Expected shares on `DC02`:

```text
NETLOGON
SYSVOL
```

Check paths:

```powershell
Test-Path C:\Windows\SYSVOL\sysvol
Test-Path C:\Windows\SYSVOL\domain\scripts
```

Both should return `True`.

If `SYSVOL` or `NETLOGON` is missing, check DFS Replication:

```powershell
Get-Service DFSR
Get-WinEvent -LogName "DFS Replication" -MaxEvents 30
```

Do not continue until SYSVOL is healthy.

### 6. Verify DNS Zones Replicated

```powershell
Get-DnsServerZone
Resolve-DnsName gntech.me -Server 10.0.20.10
Resolve-DnsName gntech.me -Server 10.0.20.11
Resolve-DnsName _ldap._tcp.dc._msdcs.gntech.me -Type SRV -Server 10.0.20.11
```

Expected: both DCs answer the zone and SRV records.

Check host records:

```powershell
Resolve-DnsName DC01.gntech.me -Server 10.0.20.11
Resolve-DnsName DC02.gntech.me -Server 10.0.20.10
```

### 7. Verify Global Catalog

```powershell
Get-ADDomainController DC02 | Select-Object HostName,IsGlobalCatalog
```

Expected:

```text
IsGlobalCatalog : True
```

You can also verify the GC port:

```powershell
Test-NetConnection DC02 -Port 3268
```

### 8. Verify FSMO Roles Stayed Put

Adding a secondary DC should not move FSMO roles automatically.

```powershell
netdom query fsmo
```

Expected: roles are still on `DC01` unless you intentionally moved them.
For a two-DC homelab, leaving FSMO roles on `DC01` is fine. If you want
`DC02` to become the maintenance target later, move roles intentionally
and document it.

## Client Failover Test

Pick a domain-joined Windows client.

Set DNS to both DCs:

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10,10.0.20.11
```

Verify domain discovery:

```powershell
nltest /dsgetdc:gntech.me
Resolve-DnsName _kerberos._tcp.gntech.me -Type SRV
Test-ComputerSecureChannel -Verbose
gpupdate /force
```

Now simulate `DC01` being unavailable. For a lab, the cleanest test is to
stop DNS registration use by pointing the client only to `DC02`, not by
hard powering off a DC during replication.

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.11

ipconfig /flushdns
nltest /dsgetdc:gntech.me
gpupdate /force
```

Expected: the client discovers `DC02`, resolves AD SRV records, and
applies Group Policy.

Restore normal DNS order afterward:

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10,10.0.20.11
```

## AD Sites and Services Cleanup

### GUI: Active Directory Sites and Services

Open Active Directory Sites and Services:

```powershell
dssite.msc
```

> **Image placeholder:** Add screenshot of Active Directory Sites and Services
> showing `DC01` and `DC02` under the correct site.

Check:

- `DC01` and `DC02` are under the correct site
- Subnets are defined if you have multiple VLANs/sites
- NTDS Settings exists under each DC
- Replication connections were generated by KCC

For a single site, the default is usually fine. For routed homelabs with
multiple VLANs or remote sites, define subnets so clients prefer the
nearest DC.

PowerShell example:

```powershell
New-ADReplicationSubnet \
  -Name "10.0.20.0/24" \
  -Site "Default-First-Site-Name"
```

## Monitoring Checks to Keep

Add these to your maintenance routine:

```powershell
repadmin /replsummary
dcdiag /test:dns /s:DC01
dcdiag /test:dns /s:DC02
Get-ADDomainController -Filter * | Select HostName,IPv4Address,IsGlobalCatalog
```

Event logs worth watching:

```powershell
Get-WinEvent -LogName "Directory Service" -MaxEvents 20
Get-WinEvent -LogName "DNS Server" -MaxEvents 20
Get-WinEvent -LogName "DFS Replication" -MaxEvents 20
Get-WinEvent -LogName "System" -MaxEvents 20
```

## Common Problems

### Promotion Fails: Cannot Contact Domain

Check DNS on `DC02` before promotion:

```powershell
Get-DnsClientServerAddress
Resolve-DnsName _ldap._tcp.dc._msdcs.gntech.me -Type SRV
Test-NetConnection DC01 -Port 389
Test-NetConnection DC01 -Port 53
```

Fix: point `DC02` DNS to `DC01` before promotion.

### Replication Shows 1908 or 1726 Right After Promotion

Immediately after promotion, transient replication errors can appear
while services finish registering. Wait a few minutes, then run:

```powershell
repadmin /syncall /AdeP
repadmin /replsummary
```

If errors persist, check firewall, DNS, time sync, and Directory Service
events.

### DC02 Missing SYSVOL or NETLOGON

Check DFSR logs:

```powershell
Get-WinEvent -LogName "DFS Replication" -MaxEvents 50
```

Also verify the DFSR service:

```powershell
Get-Service DFSR
```

Do not point clients to `DC02` until SYSVOL and NETLOGON are present.

### Clients Still Only Use DC01

Check Sites and Services and DNS SRV records:

```powershell
nltest /dsgetdc:gntech.me /force
Resolve-DnsName _ldap._tcp.dc._msdcs.gntech.me -Type SRV
```

If clients have static DNS pointing only to `DC01`, update DHCP option 6
or the client NIC configuration.

## Final Verification Script

Run from an elevated PowerShell session on either DC:

```powershell
$Domain = "gntech.me"
$DCs = "DC01", "DC02"

Write-Host "== Domain Controllers ==" -ForegroundColor Cyan
Get-ADDomainController -Filter * |
  Select-Object HostName,IPv4Address,Site,IsGlobalCatalog,OperationMasterRoles

Write-Host "== DC Discovery ==" -ForegroundColor Cyan
nltest /dclist:$Domain

Write-Host "== DNS SRV Records ==" -ForegroundColor Cyan
Resolve-DnsName "_ldap._tcp.dc._msdcs.$Domain" -Type SRV
Resolve-DnsName "_kerberos._tcp.$Domain" -Type SRV

Write-Host "== Replication Summary ==" -ForegroundColor Cyan
repadmin /replsummary

foreach ($DC in $DCs) {
  Write-Host "== $DC DNS Test ==" -ForegroundColor Cyan
  dcdiag /test:dns /s:$DC

  Write-Host "== $DC Shares ==" -ForegroundColor Cyan
  net view \\$DC | Select-String "SYSVOL|NETLOGON"

  Write-Host "== $DC GC Port ==" -ForegroundColor Cyan
  Test-NetConnection $DC -Port 3268
}

Write-Host "== FSMO Roles ==" -ForegroundColor Cyan
netdom query fsmo
```

## Summary

The safe path to a secondary domain controller is:

1. Verify `DC01` is healthy first
2. Patch and rename `DC02`
3. Set static IP and point DNS to `DC01`
4. Join `DC02` to the domain
5. Install AD DS
6. Promote with `Install-ADDSDomainController`
7. Install DNS and enable Global Catalog
8. Verify replication, DNS, SYSVOL, NETLOGON, GC, and FSMO roles
9. Update client/DHCP DNS to include both DCs
10. Test client failover to `DC02`

Do not treat promotion as the finish line. The finish line is a clean
`dcdiag`, healthy `repadmin`, valid DNS SRV records, present
`SYSVOL/NETLOGON`, and a client that can still log in and apply Group
Policy when using the secondary DC.
