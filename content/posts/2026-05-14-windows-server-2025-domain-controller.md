---
title: "Windows Server 2025 Domain Controller — AD DS Install and Verification"
description: "Install and configure a Windows Server 2025 domain controller with AD DS, DNS, static IP, PowerShell deployment, client join testing, and full dcdiag/repadmin verification."
date: 2026-05-14T03:20:00-04:00
tags:
  - windows-server
  - active-directory
  - dns
  - homelab
  - security
keywords:
  - Windows Server 2025 domain controller
  - install AD DS Windows Server 2025
  - Active Directory domain controller setup
  - configure DNS domain controller
  - dcdiag repadmin verification
  - homelab Active Directory setup
summary: "Step-by-step Windows Server 2025 domain controller deployment: static IP, AD DS installation, DNS configuration, domain promotion, OU/user setup, client join testing, and post-install verification."
canonical: "https://gntech.dev/posts/windows-server-2025-domain-controller/"
cover:
  image: "/images/posts/windows-server-2025-domain-controller/ad-ds-lab-topology.svg"
  alt: "Windows Server 2025 domain controller topology with AD DS, DNS, clients, and verification tools"
  caption: "Basic Windows Server 2025 AD DS lab topology"
---

A domain controller is still the center of a Windows network. Even in a
small homelab, Active Directory gives you centralized identity, DNS,
Group Policy, Kerberos authentication, device management, and a clean
place to test enterprise workflows without touching production.

This guide builds a fresh Windows Server 2025 domain controller from
zero: static IP, hostname, AD DS installation, DNS, forest creation,
first OU/user structure, client join, and verification. The focus is not
"click Next until it works". The focus is building it in a way you can
troubleshoot later.

![Windows Server 2025 AD DS lab topology](/images/posts/windows-server-2025-domain-controller/ad-ds-lab-topology.svg)

> **Image placeholders to add later:**
>
> - Screenshot: Server Manager dashboard before AD DS installation
> - Screenshot: static IP and DNS settings on `DC01`
> - Screenshot: Add Roles and Features wizard with **Active Directory Domain Services** selected
> - Screenshot: AD DS post-deployment warning / **Promote this server to a domain controller**
> - Screenshot: Deployment Configuration page for new forest `corp.gntech.local`
> - Screenshot: DNS Options / Additional Options pages during promotion
> - Screenshot: final prerequisites check before install
> - Screenshot: Active Directory Users and Computers showing created OUs
> - Screenshot: DNS Manager showing `_msdcs` and SRV records
> - Screenshot: successful `dcdiag`, `repadmin`, and client domain join verification

## GUI vs Server Core Path

This guide covers both install styles:

- **Desktop Experience / GUI:** use Server Manager, Settings, DNS Manager,
  Active Directory Users and Computers, and the AD DS configuration wizard.
- **Server Core / automation:** use PowerShell only. This is the cleaner path
  for repeatable homelab builds, unattended deployment, and documentation.

Use the GUI path when you want screenshots or you are learning the flow. Use
the PowerShell path when you want a build you can reproduce exactly.

## Target Lab Design

Example values used in this guide:

| Item | Value |
|------|-------|
| Server name | `DC01` |
| Server OS | Windows Server 2025 |
| Domain/FQDN | `corp.gntech.local` |
| NetBIOS name | `CORP` |
| DC IP | `10.0.20.10/24` |
| Gateway | `10.0.20.1` |
| DNS on DC | `127.0.0.1`, then `10.0.20.10` |
| DNS on clients | `10.0.20.10` |
| Site | `Default-First-Site-Name` initially |

Use a real internal domain that you own if this will become production.
For a lab, `.local` is common, but it can conflict with mDNS in mixed
Linux/macOS networks. A safer production-style pattern is a delegated
subdomain like `ad.example.com` or `corp.example.com`.

## Before You Install AD DS

Do these first. Most broken domain controllers come from skipping one of
these basics.

### 1. Patch the Server

Install Windows updates before promotion:

```powershell
Install-Module PSWindowsUpdate -Force
Get-WindowsUpdate
Install-WindowsUpdate -AcceptAll -AutoReboot
```

If you do not use `PSWindowsUpdate`, run updates from Settings or Windows
Admin Center. Reboot until there are no pending updates.

### 2. Rename the Server

Do not promote a server named `WIN-ABC123XYZ`.

```powershell
Rename-Computer -NewName "DC01" -Restart
```

After reboot:

```powershell
hostname
```

Expected:

```text
DC01
```

### 3. Configure a Static IP

Find the interface name:

```powershell
Get-NetAdapter
```

Set the address:

```powershell
New-NetIPAddress \
  -InterfaceAlias "Ethernet" \
  -IPAddress 10.0.20.10 \
  -PrefixLength 24 \
  -DefaultGateway 10.0.20.1
```

Set temporary DNS to itself. Before AD DS is installed this looks odd,
but the DNS role will be installed during domain controller promotion.

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 127.0.0.1
```

Verify:

```powershell
Get-NetIPConfiguration
Get-DnsClientServerAddress -InterfaceAlias "Ethernet"
```

### 4. Check Time Sync

Kerberos is time-sensitive. A five-minute clock skew can break logons.

```powershell
w32tm /query /status
```

For a single lab DC, sync the host/VM from a reliable source. For a
production domain, configure the PDC Emulator to use external NTP and
let domain members sync from the domain hierarchy.

## Install AD DS and DNS

### GUI: Install the Role with Server Manager

On Windows Server 2025 Desktop Experience:

1. Open **Server Manager**.
2. Go to **Manage → Add Roles and Features**.
3. Choose **Role-based or feature-based installation**.
4. Select the local server `DC01`.
5. Select **Active Directory Domain Services**.
6. Accept the required management tools.
7. Continue through the wizard and click **Install**.

> **Image placeholder:** Add screenshot of Server Manager role selection with
> **Active Directory Domain Services** checked.

The role install does not make the server a domain controller yet. It only
installs the AD DS binaries and management tools.

### Server Core / PowerShell: Install the Role

Install the AD DS role with management tools:

```powershell
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools
```

Verify the role is present:

```powershell
Get-WindowsFeature AD-Domain-Services
```

Expected result:

```text
[X] Active Directory Domain Services
```

The server is not a domain controller yet. The role only installs the
binaries. Promotion creates the forest/domain and configures DNS,
SYSVOL, NTDS, Kerberos, and the first domain controller objects.

## Promote the Server to a New Forest

### GUI: Promote with the AD DS Wizard

After role installation, Server Manager shows a notification flag.

1. Click the notification flag.
2. Select **Promote this server to a domain controller**.
3. Choose **Add a new forest**.
4. Enter the root domain name: `corp.gntech.local`.
5. Keep **Domain Name System (DNS) server** checked.
6. Set the Directory Services Restore Mode password.
7. Confirm the NetBIOS name: `CORP`.
8. Review paths for database, logs, and SYSVOL.
9. Run the prerequisites check.
10. Click **Install** and let the server reboot.

> **Image placeholder:** Add screenshot of the Deployment Configuration page
> showing **Add a new forest** and `corp.gntech.local`.
>
> **Image placeholder:** Add screenshot of the prerequisites check passing
> before clicking **Install**.

### Server Core / PowerShell: Promote with `Install-ADDSForest`

For a new lab forest:

```powershell
$SafeModePassword = Read-Host \
  -Prompt "Enter Directory Services Restore Mode password" \
  -AsSecureString

Install-ADDSForest \
  -DomainName "corp.gntech.local" \
  -DomainNetbiosName "CORP" \
  -InstallDns \
  -SafeModeAdministratorPassword $SafeModePassword \
  -NoRebootOnCompletion:$false \
  -Force
```

The server reboots automatically.

Do not force a functional level unless you know exactly why. For a clean
Windows Server 2025-only lab, the default selected by Server Manager or
PowerShell is fine. In a real environment, check compatibility before
raising forest or domain functional levels.

After reboot, log in as:

```text
CORP\Administrator
```

or:

```text
corp.gntech.local\Administrator
```

## Post-Promotion DNS Cleanup

After promotion, set the server NIC DNS to the DC IP. Avoid leaving only
`127.0.0.1` on the NIC because it makes later troubleshooting less clear.

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10
```

Verify:

```powershell
Get-DnsClientServerAddress -InterfaceAlias "Ethernet"
Resolve-DnsName corp.gntech.local
Resolve-DnsName dc01.corp.gntech.local
```

Expected: both names resolve to the domain/DC records, with `DC01`
resolving to `10.0.20.10`.

## Configure DNS Forwarders

Clients should use the DC for DNS. The DC can forward unknown internet
queries to upstream resolvers.

### GUI: DNS Manager

1. Open **Server Manager → Tools → DNS**.
2. Right-click `DC01` → **Properties**.
3. Open the **Forwarders** tab.
4. Add `1.1.1.1` and `9.9.9.9`, or your internal resolver.

> **Image placeholder:** Add screenshot of DNS Manager forwarders configured on
> `DC01`.

### Server Core / PowerShell

```powershell
Add-DnsServerForwarder -IPAddress 1.1.1.1,9.9.9.9 -PassThru
Get-DnsServerForwarder
```

If your firewall/router provides internal DNS for other VLANs, you can
forward to that instead. The rule is simple: clients ask AD DNS first;
AD DNS either answers internal records or forwards external queries.

## Create a Basic OU Structure

### GUI: Create OUs in Active Directory Users and Computers

On Desktop Experience:

1. Open **Server Manager → Tools → Active Directory Users and Computers**.
2. Expand `corp.gntech.local`.
3. Right-click the domain → **New → Organizational Unit**.
4. Create `Servers`, `Workstations`, `Users`, `Groups`, and `Service Accounts`.
5. Right-click `Users` → **New → User** to create `test.user`.

> **Image placeholder:** Add screenshot of Active Directory Users and Computers
> showing the OU layout after creation.

### Server Core / PowerShell: Create OUs and Users

Install the AD PowerShell module if it is not loaded automatically:

```powershell
Import-Module ActiveDirectory
```

Create a clean structure:

```powershell
$BaseDN = "DC=corp,DC=gntech,DC=local"

New-ADOrganizationalUnit -Name "Servers" -Path $BaseDN
New-ADOrganizationalUnit -Name "Workstations" -Path $BaseDN
New-ADOrganizationalUnit -Name "Users" -Path $BaseDN
New-ADOrganizationalUnit -Name "Groups" -Path $BaseDN
New-ADOrganizationalUnit -Name "Service Accounts" -Path $BaseDN
```

Create a test user:

```powershell
$Password = Read-Host "Password for test.user" -AsSecureString

New-ADUser \
  -Name "Test User" \
  -GivenName "Test" \
  -Surname "User" \
  -SamAccountName "test.user" \
  -UserPrincipalName "test.user@corp.gntech.local" \
  -Path "OU=Users,$BaseDN" \
  -AccountPassword $Password \
  -Enabled $true \
  -ChangePasswordAtLogon $true
```

Verify:

```powershell
Get-ADOrganizationalUnit -Filter * | Select-Object Name,DistinguishedName
Get-ADUser test.user -Properties Enabled,UserPrincipalName
```

## Configure the Reverse Lookup Zone

Reverse DNS is not mandatory for every lab, but it helps with clean
logging and diagnostics.

```powershell
Add-DnsServerPrimaryZone \
  -NetworkId "10.0.20.0/24" \
  -ReplicationScope "Domain"
```

Create or verify the PTR record for the DC:

```powershell
Add-DnsServerResourceRecordPtr \
  -Name "10" \
  -ZoneName "20.0.10.in-addr.arpa" \
  -PtrDomainName "dc01.corp.gntech.local"
```

Check it:

```powershell
Resolve-DnsName 10.0.20.10
```

If the PTR already exists, the add command will fail. That is fine —
verify the existing record instead of duplicating it.

## Join a Windows Client to the Domain

On a Windows 11/Windows Server client, set DNS to the DC:

```powershell
Set-DnsClientServerAddress \
  -InterfaceAlias "Ethernet" \
  -ServerAddresses 10.0.20.10
```

Verify DNS before joining:

```powershell
Resolve-DnsName corp.gntech.local
Resolve-DnsName _ldap._tcp.dc._msdcs.corp.gntech.local -Type SRV
```

Join the domain:

```powershell
Add-Computer \
  -DomainName "corp.gntech.local" \
  -Credential "CORP\Administrator" \
  -Restart
```

After reboot, log in as:

```text
CORP\test.user
```

Move the computer object into the correct OU:

```powershell
Get-ADComputer -Filter 'Name -eq "CLIENT01"' |
  Move-ADObject -TargetPath "OU=Workstations,DC=corp,DC=gntech,DC=local"
```

## Verification Checklist

This is the important part. A DC that installs without errors can still
have DNS, SYSVOL, replication, or secure channel problems.

### 1. Confirm Domain Controller Discovery

Run from the DC:

```powershell
nltest /dsgetdc:corp.gntech.local
```

Expected indicators:

```text
DC: \\DC01
Address: \\10.0.20.10
Dom Guid: ...
Dom Name: corp.gntech.local
Forest Name: corp.gntech.local
The command completed successfully
```

### 2. Run DCDIAG

```powershell
dcdiag /v /c /d /e /s:DC01 > C:\dcdiag-DC01.txt
notepad C:\dcdiag-DC01.txt
```

For a single-DC lab, focus on:

```text
Connectivity
Advertising
FrsEvent or DFSREvent
SysVolCheck
KccEvent
MachineAccount
NetLogons
Services
SystemLog
DNS
```

A clean result should show tests passed. DNS warnings are common if
forwarders or internet access are not configured yet, but internal SRV
records must work.

Quick DNS-only test:

```powershell
dcdiag /test:dns /v /s:DC01
```

### 3. Verify SYSVOL and NETLOGON Shares

```powershell
net share
```

Expected shares:

```text
NETLOGON
SYSVOL
```

Check paths:

```powershell
Test-Path C:\Windows\SYSVOL\sysvol
Test-Path C:\Windows\SYSVOL\domain\scripts
```

Both should return:

```text
True
```

### 4. Verify Replication Health

Even with one DC, use the replication tools now so the commands are
normal before you add a second DC.

```powershell
repadmin /replsummary
repadmin /showrepl DC01
```

For a single DC, there may be little to replicate, but there should be
no replication failures.

### 5. Verify FSMO Roles

```powershell
netdom query fsmo
```

Expected: all five FSMO roles are held by `DC01` in a single-DC forest.

```text
Schema master               DC01.corp.gntech.local
Domain naming master        DC01.corp.gntech.local
PDC                         DC01.corp.gntech.local
RID pool manager            DC01.corp.gntech.local
Infrastructure master       DC01.corp.gntech.local
```

### 6. Verify DNS SRV Records

```powershell
Resolve-DnsName _ldap._tcp.dc._msdcs.corp.gntech.local -Type SRV
Resolve-DnsName _kerberos._tcp.corp.gntech.local -Type SRV
Resolve-DnsName gc._msdcs.corp.gntech.local -Type A
```

If these fail, clients will not reliably find domain controllers.

### 7. Verify AD Web Services

PowerShell AD cmdlets depend on AD Web Services.

```powershell
Get-Service ADWS
Get-ADDomain
Get-ADForest
```

Expected service status:

```text
Running
```

### 8. Verify Client Secure Channel

On a domain-joined client:

```powershell
Test-ComputerSecureChannel -Verbose
whoami /fqdn
gpupdate /force
gpresult /r
```

Expected:

- `Test-ComputerSecureChannel` returns `True`
- `whoami /fqdn` returns the user's AD distinguished name
- `gpupdate` completes without DC discovery errors
- `gpresult /r` shows domain policy information

## Basic Hardening After Install

Do these before building more services around the domain.

### Disable Unneeded Local Administrator Use

Create named admin accounts and keep the built-in Administrator for
break-glass use.

```powershell
New-ADGroup -Name "GG-Server-Admins" -GroupScope Global -GroupCategory Security -Path "OU=Groups,DC=corp,DC=gntech,DC=local"
```

### Enable the Recycle Bin

```powershell
Enable-ADOptionalFeature \
  -Identity 'Recycle Bin Feature' \
  -Scope ForestOrConfigurationSet \
  -Target 'corp.gntech.local'
```

Verify:

```powershell
Get-ADOptionalFeature -Filter 'Name -like "Recycle Bin Feature"' |
  Select-Object Name,EnabledScopes
```

### Configure Backups

At minimum, back up System State:

```powershell
Install-WindowsFeature Windows-Server-Backup
wbadmin start systemstatebackup -backupTarget:E: -quiet
```

For a VM, also keep hypervisor-level backups, but do not treat VM
snapshots as your only AD backup strategy. AD has replication and USN
rollback considerations once you have more than one DC.

### Keep DNS Simple

Recommended client DNS:

```text
Client DNS server: 10.0.20.10
```

Not recommended:

```text
Client DNS server: 1.1.1.1
Client DNS server: 8.8.8.8
```

Clients must ask AD DNS first. If they ask public DNS first, domain join,
Group Policy, Kerberos, and SRV record discovery will randomly fail.

## Common Problems and Fixes

### Domain Join Fails: Domain Not Found

Check DNS on the client:

```powershell
Get-DnsClientServerAddress
Resolve-DnsName _ldap._tcp.dc._msdcs.corp.gntech.local -Type SRV
```

Fix: point client DNS to the DC, not the router or public resolvers.

### DCDIAG DNS Test Fails

Check the DNS service:

```powershell
Get-Service DNS
Get-DnsServerZone
Get-DnsServerForwarder
```

Then restart Netlogon to re-register SRV records:

```powershell
Restart-Service Netlogon
ipconfig /registerdns
```

### SYSVOL or NETLOGON Missing

Check DFSR:

```powershell
Get-Service DFSR
Get-WinEvent -LogName "DFS Replication" -MaxEvents 20
```

Do not ignore missing SYSVOL/NETLOGON. Group Policy and logon scripts
will not work correctly until SYSVOL is healthy.

### Time/Kerberos Errors

```powershell
w32tm /query /status
w32tm /resync
```

On clients:

```powershell
w32tm /query /source
klist purge
```

If time is wrong, Kerberos tickets fail and logons get weird fast.

## Final Verification Script

Run this after the DC is built:

```powershell
$Domain = "corp.gntech.local"
$DC = "DC01"

Write-Host "== DNS ==" -ForegroundColor Cyan
Resolve-DnsName $Domain
Resolve-DnsName "_ldap._tcp.dc._msdcs.$Domain" -Type SRV

Write-Host "== DC Discovery ==" -ForegroundColor Cyan
nltest /dsgetdc:$Domain

Write-Host "== Shares ==" -ForegroundColor Cyan
net share | Select-String "SYSVOL|NETLOGON"

Write-Host "== FSMO ==" -ForegroundColor Cyan
netdom query fsmo

Write-Host "== Replication ==" -ForegroundColor Cyan
repadmin /replsummary

Write-Host "== DCDIAG DNS ==" -ForegroundColor Cyan
dcdiag /test:dns /s:$DC

Write-Host "== AD Cmdlets ==" -ForegroundColor Cyan
Get-ADDomain
Get-ADForest
```

If DNS, SYSVOL, FSMO, AD cmdlets, and client join all pass, you have a
working Windows Server 2025 domain controller.

## Summary

The reliable path is straightforward:

1. Patch Windows Server 2025
2. Rename the server
3. Assign a static IP
4. Install AD DS with management tools
5. Promote to a new forest with DNS
6. Point clients to AD DNS
7. Create OUs/users/groups
8. Join a test client
9. Verify with `dcdiag`, `repadmin`, `nltest`, DNS SRV lookups, SYSVOL,
   and client secure channel tests

The install wizard is the easy part. Verification is what tells you the
domain is actually usable.
