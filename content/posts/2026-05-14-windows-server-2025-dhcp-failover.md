---
title: "Windows Server 2025 DHCP Failover — Replicated Scopes and Verification"
description: "Configure Windows Server 2025 DHCP failover with replicated scopes across DHCP01 and DHCP02, covering GUI and Server Core setup, authorization, options, failover modes, replication, and client testing."
date: 2026-05-14T03:52:00-04:00
tags:
  - windows-server
  - dhcp
  - active-directory
  - networking
  - homelab
keywords:
  - Windows Server 2025 DHCP failover
  - DHCP replication Windows Server
  - configure DHCP failover PowerShell
  - DHCP load balance hot standby
  - DHCP scope replication
  - Windows DHCP verification
summary: "Step-by-step Windows Server 2025 DHCP failover guide: install DHCP, authorize servers in AD, create scopes, configure load-balance or hot-standby failover, replicate scopes, and verify leases."
canonical: "https://gntech.dev/posts/windows-server-2025-dhcp-failover/"
cover:
  image: "/images/posts/windows-server-2025-dhcp-failover/dhcp-failover-topology.svg"
  alt: "Windows Server 2025 DHCP failover topology with DHCP01 and DHCP02 replicating a shared IPv4 scope"
  caption: "DHCP failover relationship between two Windows Server 2025 DHCP servers"
---

DHCP looks simple until it is down. If your only DHCP server fails,
clients can keep their existing leases for a while, but new devices do
not get addresses, renewals eventually fail, and the network slowly gets
weird.

Windows Server DHCP failover solves that by pairing two DHCP servers.
They share scope configuration and lease state, then serve clients in
load-balance or hot-standby mode. This guide builds DHCP failover on
Windows Server 2025 with GUI and Server Core/PowerShell paths, including
replication and verification.

![Windows Server 2025 DHCP failover topology](/images/posts/windows-server-2025-dhcp-failover/dhcp-failover-topology.svg)

> **Image placeholders to add later:**
>
> - Screenshot: DHCP role install in Server Manager
> - Screenshot: DHCP post-install authorization wizard
> - Screenshot: DHCP console showing `DHCP01` and `DHCP02`
> - Screenshot: new IPv4 scope wizard
> - Screenshot: scope options with router, DNS servers, and DNS domain
> - Screenshot: Configure Failover wizard relationship page
> - Screenshot: load-balance or hot-standby mode selection
> - Screenshot: failover relationship status healthy
> - Screenshot: replicated scope visible on `DHCP02`
> - Screenshot: client lease and `ipconfig /all` verification

## GUI vs Server Core Path

This guide covers both styles:

- **Desktop Experience / GUI:** Server Manager, DHCP console, new scope wizard,
  DHCP authorization, and failover wizard.
- **Server Core / PowerShell:** `Install-WindowsFeature`, `Add-DhcpServerInDC`,
  `Add-DhcpServerv4Scope`, `Set-DhcpServerv4OptionValue`, and
  `Add-DhcpServerv4Failover`.

Use GUI for screenshots and learning the flow. Use PowerShell for repeatable
server builds and clean documentation.

## Target Design

| Item | Value |
|------|-------|
| DHCP server 1 | `DHCP01.corp.gntech.local` / `10.0.20.20` |
| DHCP server 2 | `DHCP02.corp.gntech.local` / `10.0.20.21` |
| Domain | `corp.gntech.local` |
| Scope | `10.0.20.0/24` |
| Lease range | `10.0.20.100` - `10.0.20.200` |
| Exclusions | `10.0.20.1` - `10.0.20.99`, `10.0.20.201` - `10.0.20.254` |
| Gateway option | `10.0.20.1` |
| DNS option | `10.0.20.10`, `10.0.20.11` |
| DNS suffix | `corp.gntech.local` |
| Failover mode | Load balance 50/50 for LAN, hot standby for remote site |

For a homelab LAN, load-balance mode is usually fine. For a branch or
remote site, hot-standby mode can be cleaner.

## DHCP Failover Modes

Windows DHCP failover supports two common designs.

### Load Balance

Both DHCP servers answer clients and split the scope workload.

```text
Use when: both DHCP servers are in the same site/VLAN and equally reachable.
Typical split: 50/50
```

### Hot Standby

One server actively handles the scope; the partner waits and takes over
if the active server is unavailable.

```text
Use when: one server is primary for a site and the other is backup.
Typical split: 95/5 or standby role
```

For this guide, the PowerShell example uses load-balance mode.

## Pre-Checks

On both DHCP servers:

```powershell
hostname
Get-NetIPConfiguration
Resolve-DnsName corp.gntech.local
Test-ComputerSecureChannel -Verbose
```

Both servers should be domain joined, statically addressed, patched, and
able to resolve the domain.

Check domain DNS:

```powershell
Resolve-DnsName DC01.corp.gntech.local
Resolve-DnsName DC02.corp.gntech.local
```

## Install the DHCP Server Role

### GUI: Server Manager

On each DHCP server:

1. Open **Server Manager**.
2. Go to **Manage → Add Roles and Features**.
3. Select **DHCP Server**.
4. Accept management tools.
5. Install the role.
6. Click the post-install notification to complete DHCP configuration.

> **Image placeholder:** Add screenshot of the DHCP Server role selected in
> Server Manager.

### Server Core / PowerShell

Run on both `DHCP01` and `DHCP02`:

```powershell
Install-WindowsFeature DHCP -IncludeManagementTools
```

Verify:

```powershell
Get-WindowsFeature DHCP
Get-Service DHCPServer
```

Expected service:

```text
Running
```

## Authorize DHCP in Active Directory

Domain-joined Windows DHCP servers must be authorized in AD before they
serve leases.

### GUI: DHCP Console

1. Open **Server Manager → Tools → DHCP**.
2. Right-click the server.
3. Select **Authorize**.
4. Refresh until the server icon shows authorized.

> **Image placeholder:** Add screenshot of both DHCP servers authorized in the
> DHCP console.

### Server Core / PowerShell

Run from a domain admin session:

```powershell
Add-DhcpServerInDC \
  -DnsName "DHCP01.corp.gntech.local" \
  -IPAddress 10.0.20.20

Add-DhcpServerInDC \
  -DnsName "DHCP02.corp.gntech.local" \
  -IPAddress 10.0.20.21
```

Verify:

```powershell
Get-DhcpServerInDC
```

## Create the Scope on DHCP01

Create the scope on one server first. The failover relationship will
replicate it to the partner.

### GUI: DHCP Console

1. Expand `DHCP01`.
2. Right-click **IPv4** → **New Scope**.
3. Name it `LAB-10.0.20.0`.
4. Set range `10.0.20.100` to `10.0.20.200`.
5. Set subnet mask `255.255.255.0`.
6. Add exclusions if needed.
7. Set router `10.0.20.1`.
8. Set DNS servers `10.0.20.10` and `10.0.20.11`.
9. Set DNS domain `corp.gntech.local`.
10. Activate the scope.

> **Image placeholder:** Add screenshot of the New Scope Wizard with the
> address range configured.
>
> **Image placeholder:** Add screenshot of DHCP scope options showing router,
> DNS servers, and DNS suffix.

### Server Core / PowerShell

Run on `DHCP01`:

```powershell
Add-DhcpServerv4Scope \
  -ComputerName "DHCP01.corp.gntech.local" \
  -Name "LAB-10.0.20.0" \
  -StartRange 10.0.20.100 \
  -EndRange 10.0.20.200 \
  -SubnetMask 255.255.255.0 \
  -State Active
```

Set options:

```powershell
Set-DhcpServerv4OptionValue \
  -ComputerName "DHCP01.corp.gntech.local" \
  -ScopeId 10.0.20.0 \
  -Router 10.0.20.1 \
  -DnsServer 10.0.20.10,10.0.20.11 \
  -DnsDomain "corp.gntech.local"
```

Verify:

```powershell
Get-DhcpServerv4Scope -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4OptionValue -ComputerName "DHCP01.corp.gntech.local" -ScopeId 10.0.20.0
```

## Configure DHCP Failover

### GUI: DHCP Failover Wizard

1. In DHCP console, expand `DHCP01 → IPv4`.
2. Right-click the scope → **Configure Failover**.
3. Select the scope.
4. Add partner server `DHCP02.corp.gntech.local`.
5. Name the relationship `DHCP01-DHCP02-LAB`.
6. Choose **Load balance**.
7. Set load balance percentage to `50%`.
8. Set shared secret.
9. Finish the wizard.

> **Image placeholder:** Add screenshot of the Configure Failover wizard with
> `DHCP02` selected as the partner.
>
> **Image placeholder:** Add screenshot of load-balance mode and shared secret
> configuration.

### Server Core / PowerShell

Use a strong shared secret. Store it securely.

```powershell
$Secret = Read-Host "DHCP failover shared secret" -AsSecureString
$PlainSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
)

Add-DhcpServerv4Failover \
  -ComputerName "DHCP01.corp.gntech.local" \
  -Name "DHCP01-DHCP02-LAB" \
  -PartnerServer "DHCP02.corp.gntech.local" \
  -ScopeId 10.0.20.0 \
  -SharedSecret $PlainSecret \
  -LoadBalancePercent 50 \
  -AutoStateTransition $true \
  -StateSwitchInterval 01:00:00
```

Clear the plaintext variable when done:

```powershell
Remove-Variable PlainSecret
```

Verify the relationship:

```powershell
Get-DhcpServerv4Failover -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4Failover -ComputerName "DHCP02.corp.gntech.local"
```

## Replicate Scope Configuration

Failover replicates leases automatically, but when you change scope
options, reservations, policies, or exclusions, force replication.

### GUI: Replicate Scope

1. Open DHCP console.
2. Right-click the scope or IPv4 node.
3. Select **Replicate Scope** or **Replicate Failover Scopes**.
4. Confirm replication to the partner.

> **Image placeholder:** Add screenshot of the DHCP replicate scope action.

### Server Core / PowerShell

Replicate a specific scope:

```powershell
Invoke-DhcpServerv4FailoverReplication \
  -ComputerName "DHCP01.corp.gntech.local" \
  -ScopeId 10.0.20.0 \
  -Force
```

Or replicate by relationship name:

```powershell
Invoke-DhcpServerv4FailoverReplication \
  -ComputerName "DHCP01.corp.gntech.local" \
  -Name "DHCP01-DHCP02-LAB" \
  -Force
```

Verify the scope exists on both servers:

```powershell
Get-DhcpServerv4Scope -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4Scope -ComputerName "DHCP02.corp.gntech.local"
```

## Router / VLAN DHCP Relay

If clients are not on the same L2 segment as the DHCP servers, configure
DHCP relay/IP helper on the router or L3 switch.

For a VLAN 20 client network, relay to both DHCP servers:

```text
DHCP relay target 1: 10.0.20.20
DHCP relay target 2: 10.0.20.21
```

On MikroTik, this is usually DHCP Relay on the VLAN interface. On Cisco,
it is usually `ip helper-address` under the SVI. The important part is
that both DHCP servers receive requests.

## Verification Checklist

### 1. DHCP Server Authorization

```powershell
Get-DhcpServerInDC
```

Expected: both `DHCP01` and `DHCP02` listed with correct IPs.

### 2. Scope Exists on Both Servers

```powershell
Get-DhcpServerv4Scope -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4Scope -ComputerName "DHCP02.corp.gntech.local"
```

### 3. Options Are Correct

```powershell
Get-DhcpServerv4OptionValue \
  -ComputerName "DHCP01.corp.gntech.local" \
  -ScopeId 10.0.20.0

Get-DhcpServerv4OptionValue \
  -ComputerName "DHCP02.corp.gntech.local" \
  -ScopeId 10.0.20.0
```

Expected:

```text
003 Router: 10.0.20.1
006 DNS Servers: 10.0.20.10, 10.0.20.11
015 DNS Domain Name: corp.gntech.local
```

### 4. Failover Relationship Is Healthy

```powershell
Get-DhcpServerv4Failover \
  -ComputerName "DHCP01.corp.gntech.local" \
  -Name "DHCP01-DHCP02-LAB" |
  Format-List *
```

Look for normal state on both partners.

### 5. Client Lease Test

On a Windows client:

```powershell
ipconfig /release
ipconfig /renew
ipconfig /all
```

Verify:

- IPv4 address is inside `10.0.20.100-200`
- gateway is `10.0.20.1`
- DNS servers are `10.0.20.10` and `10.0.20.11`
- DNS suffix is `corp.gntech.local`

### 6. Lease Visibility

```powershell
Get-DhcpServerv4Lease \
  -ComputerName "DHCP01.corp.gntech.local" \
  -ScopeId 10.0.20.0

Get-DhcpServerv4Lease \
  -ComputerName "DHCP02.corp.gntech.local" \
  -ScopeId 10.0.20.0
```

Leases should replicate between partners.

## Failover Test

Do not hard power off servers during early testing. First do a controlled
service test.

On `DHCP01`:

```powershell
Stop-Service DHCPServer
```

On a client:

```powershell
ipconfig /release
ipconfig /renew
ipconfig /all
```

Expected: the client still receives a valid lease from `DHCP02`.

Restart `DHCP01`:

```powershell
Start-Service DHCPServer
```

Check failover state:

```powershell
Get-DhcpServerv4Failover -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4Failover -ComputerName "DHCP02.corp.gntech.local"
```

## Common Problems

### DHCP Server Not Leasing Addresses

Check authorization:

```powershell
Get-DhcpServerInDC
Get-Service DHCPServer
```

If unauthorized, authorize it in AD.

### Client Gets APIPA Address

APIPA means the client did not receive DHCP.

Check the client and the DHCP server-side counters:

```powershell
ipconfig /all
Get-DhcpServerv4Statistics -ComputerName "DHCP01.corp.gntech.local"
Get-DhcpServerv4Statistics -ComputerName "DHCP02.corp.gntech.local"
Get-DhcpServerv4Lease -ComputerName "DHCP01.corp.gntech.local" -ScopeId 10.0.20.0
Get-DhcpServerv4Lease -ComputerName "DHCP02.corp.gntech.local" -ScopeId 10.0.20.0
```

Do not use `Test-NetConnection -Port 67` as a DHCP test. DHCP uses UDP
broadcast/relay behavior, so a TCP port probe does not prove DHCP works.
Also verify DHCP relay/IP helper on routed VLANs.

### Scope Changes Did Not Appear on Partner

Force replication:

```powershell
Invoke-DhcpServerv4FailoverReplication \
  -ComputerName "DHCP01.corp.gntech.local" \
  -Name "DHCP01-DHCP02-LAB" \
  -Force
```

### DNS Updates Not Working

If DHCP is registering DNS records for clients, configure DHCP credentials
and check DNS dynamic update settings.

```powershell
Get-DhcpServerDnsCredential
Get-DhcpServerv4DnsSetting
```

For AD environments, DNS zones should allow secure dynamic updates.

## Final Verification Script

```powershell
$ScopeId = "10.0.20.0"
$Relationship = "DHCP01-DHCP02-LAB"
$Servers = "DHCP01.corp.gntech.local", "DHCP02.corp.gntech.local"

Write-Host "== Authorized DHCP Servers ==" -ForegroundColor Cyan
Get-DhcpServerInDC

foreach ($Server in $Servers) {
  Write-Host "== $Server Service ==" -ForegroundColor Cyan
  Get-Service DHCPServer -ComputerName $Server

  Write-Host "== $Server Scopes ==" -ForegroundColor Cyan
  Get-DhcpServerv4Scope -ComputerName $Server

  Write-Host "== $Server Options ==" -ForegroundColor Cyan
  Get-DhcpServerv4OptionValue -ComputerName $Server -ScopeId $ScopeId

  Write-Host "== $Server Leases ==" -ForegroundColor Cyan
  Get-DhcpServerv4Lease -ComputerName $Server -ScopeId $ScopeId |
    Select-Object -First 10

  Write-Host "== $Server Failover ==" -ForegroundColor Cyan
  Get-DhcpServerv4Failover -ComputerName $Server -Name $Relationship
}
```

## Summary

The reliable DHCP failover path is:

1. Build two domain-joined Windows Server 2025 DHCP servers
2. Install DHCP role and management tools
3. Authorize both servers in Active Directory
4. Create the scope on the first server
5. Set router, DNS server, and DNS suffix options
6. Create a DHCP failover relationship
7. Replicate scope configuration after changes
8. Configure router/VLAN DHCP relay to both servers
9. Verify leases, options, failover state, and client renewal

DHCP failover is not just a checkbox. Treat it like a replicated service:
verify both partners, force replication after changes, and test client
renewal before you trust it.
