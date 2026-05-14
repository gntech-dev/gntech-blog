---
title: "Windows Server 2025 Group Policy Management — GPMC, WUfB, and Central Store"
description: "Complete guide to Group Policy management on Windows Server 2025: installing GPMC on Server Core and GUI, creating and linking GPOs, security/WMI filtering, ADMX Central Store, backup/restore, HTML reporting, and Windows Update for Business (WUfB) via Group Policy."
date: 2026-05-14T12:00:00-04:00
tags:
  - windows-server
  - group-policy
  - active-directory
  - gpo
  - wufb
  - windows-update
  - homelab
keywords:
  - Windows Server 2025 Group Policy
  - GPMC install Server Core PowerShell
  - Group Policy ADMX Central Store
  - GPO security filtering WMI filtering
  - Windows Update for Business GPO
  - GPO backup restore PowerShell
  - Resultant Set of Policy modeling
summary: "Step-by-step Group Policy management on Windows Server 2025: GPMC install, GPO creation/linking, security and WMI filtering, ADMX templates, backup/restore, and Windows Update for Business deployment rings."
canonical: "https://blog.gntech.me/posts/windows-server-2025-group-policy-management/"
cover:
  image: "https://upload.wikimedia.org/wikipedia/commons/2/26/Windows_Server_logo.svg"
  alt: "Windows Server logo"
  caption: "Windows Server logo — © Microsoft Corporation (public domain as simple geometric logo)"
---

Group Policy is the backbone of configuration management in Active
Directory. Without it, every server and workstation must be configured
manually. Security baselines, update policies, drive maps, printer
deployments, and user restrictions all flow through Group Policy
Objects (GPOs) linked to sites, domains, and OUs.

This guide covers Group Policy on Windows Server 2025 from first
principles. The first half is pure GPO management: install GPMC, create
and link GPOs, apply security and WMI filtering, manage ADMX templates
via the Central Store, backup and restore GPOs, and use Resultant Set
of Policy for troubleshooting. The second half applies all of that to
one practical scenario: replacing WSUS with **Windows Update for
Business (WUfB)** configured entirely through Group Policy.

> **Screenshots and images to add later:**
>
> - GPMC console with forest, domains, and GPOs
> - New GPO dialog
> - GPO Editor showing Administrative Templates
> - Security Filtering tab with Authenticated Users removed
> - WMI Filter dialog
> - Central Store folder structure in SYSVOL
> - Group Policy Results wizard
> - Group Policy Modeling wizard
> - Windows Update deferral policy settings
> - Delivery Optimization GPO settings

## Prerequisites

- A working Active Directory domain (`gntech.me` in this guide)
- Domain Controller running Windows Server 2025 (or 2022)
- At least one member server or client joined to the domain for testing
- Domain Administrator credentials
- Windows Server 2025 ADMX templates (download from Microsoft)

## GPMC on Server Core vs GUI

Windows Server 2025 ships with both Desktop Experience (GUI) and Server
Core installation options. The approach differs:

| Environment | Install GPMC | Management |
|---|---|---|
| Server Core | `Install-WindowsFeature GPMC` (PowerShell) | Manage remotely via RSAT from a Windows 11 workstation, or use PowerShell cmdlets locally |
| Desktop Experience | `Install-WindowsFeature GPMC` or Add Roles and Features Wizard | Full GPMC snap-in locally |
| Windows 11 (any) | Install RSAT optional feature | Full GPMC via `gpmc.msc`, manage any domain |

For a homelab, running GPMC on a Windows 11 management workstation via
RSAT is the most practical approach. Server Core installs GPMC but
gives you only the PowerShell module — there is no MMC console on
Server Core.

## Installing GPMC

### On Server Core via PowerShell

```powershell
# Must be run as Administrator on the domain controller
Install-WindowsFeature -Name GPMC -IncludeManagementTools
```

The output confirms success or failure. No reboot is required.

### On Desktop Experience (GUI) via PowerShell

```powershell
Install-WindowsFeature -Name GPMC
```

Or use Server Manager:

1. Open **Server Manager** → **Manage** → **Add Roles and Features**
2. Click **Next** through the wizard until **Features**
3. Scroll to **Group Policy Management**
4. Check the box, click **Install**

### On Windows 11 (RSAT)

Windows 11 manages GPMC through the RSAT optional features system:

**GUI path:**

1. Open **Settings** → **System** → **Optional Features**
2. Click **View features**
3. Search for **RSAT: Group Policy Management Tools**
4. Check the box and click **Next** → **Install**

**PowerShell path:**

```powershell
# Confirm the feature name
Get-WindowsCapability -Online | Where-Object Name -like "Rsat.GroupPolicy*"

# Install it
Add-WindowsCapability -Online -Name "Rsat.GroupPolicy.Management.Tools~~~~0.0.1.0"
```

Once installed, launch GPMC by running `gpmc.msc` or searching **Group
Policy Management** in the Start menu.

## GPMC Overview

When GPMC opens, the console tree shows:

```
Group Policy Management
├── Forest: gntech.me
│   ├── Sites
│   │   └── Default-First-Site-Name
│   ├── Domains
│   │   └── gntech.me
│   │       ├── Default Domain Policy
│   │       ├── Domain Controllers (OU)
│   │       │   └── Default Domain Controllers Policy
│   │       ├── [user-created OUs]
│   │       └── Group Policy Objects
│   │       └── WMI Filters
│   │       └── Starter GPOs
│   └── Group Policy Modeling
│   └── Group Policy Results
```

Key sections:

- **Group Policy Objects** — stores all GPOs regardless of link location
- **WMI Filters** — reusable WMI queries to scope GPOs by OS version, RAM, disk, etc.
- **Starter GPOs** — templates for common policy configurations
- **Group Policy Modeling** — RSoP simulation ("what-if")
- **Group Policy Results** — actual RSoP of a real client ("what-is")

### Default GPOs

Every domain has two mandatory GPOs after AD DS installation:

| GPO | Linked to | Purpose |
|---|---|---|
| Default Domain Policy | Domain root | Password policy, account lockout, Kerberos policy |
| Default Domain Controllers Policy | Domain Controllers OU | User rights assignments, audit policy, security options for DCs |

**Rule:** Never delete these. Do not modify the Domain Controllers
Policy unless you know exactly what you are doing. Add custom settings
into new GPOs, not into the defaults.

## ADMX Central Store

Administrative Templates (.admx / .adml) define the registry-based
policy settings visible in the GPO Editor. By default, each server or
workstation running GPMC uses its local `C:\Windows\PolicyDefinitions`
folder. In a mixed-OS environment (Server 2025 managing Windows 11
25H2 settings), this means missing templates on older machines.

The **Central Store** solves this by hosting ADMX files in SYSVOL,
making them available to all domain administrators regardless of their
management workstation OS.

### Creating the Central Store

```powershell
# Create the Central Store folder on a domain controller
$sysvol = "\\gntech.me\SYSVOL\gntech.me\Policies\PolicyDefinitions"
New-Item -Path $sysvol -ItemType Directory -Force

# Create language subfolder (en-US in this case)
New-Item -Path "$sysvol\en-US" -ItemType Directory -Force
```

### Populating ADMX Files

Download the latest ADMX templates:

- [Administrative Templates (.admx) for Windows 11 2025 Update (25H2)](https://www.microsoft.com/en-us/download/details.aspx?id=108394)
- [Administrative Templates (.admx) for Windows Server 2025 (October 2025 release)](https://www.microsoft.com/en-us/download/details.aspx?id=108430)

Extract the downloaded MSI/MSP and copy the files:

```powershell
# Example: after extracting to C:\ADMX\Win11_25H2
Copy-Item -Path "C:\ADMX\Win11_25H2\*.admx" -Destination $sysvol -Recurse
Copy-Item -Path "C:\ADMX\Win11_25H2\en-US\*.adml" -Destination "$sysvol\en-US" -Recurse

# Repeat for Server 2025 ADMX
Copy-Item -Path "C:\ADMX\Svr2025\*.admx" -Destination $sysvol -Recurse
Copy-Item -Path "C:\ADMX\Svr2025\en-US\*.adml" -Destination "$sysvol\en-US" -Recurse
```

GPMC automatically detects the Central Store and uses it in preference
to local PolicyDefinitions. Newer ADMX files override older ones with
the same name.

**Best practice:** Populate the Central Store with the latest Windows
client ADMX (e.g., Windows 11 25H2) plus the Server 2025 ADMX. This
covers both client and server policy settings from one location.

## Creating a GPO

### Via GPMC (GUI)

1. Right-click the target OU (or domain) → **Create a GPO in this domain and Link it here**
2. Enter a descriptive name like **Windows Update - Ring 1 (Pilot)**
3. Click **OK**
4. Right-click the new GPO → **Edit** to open the Group Policy Management Editor

### Via PowerShell

```powershell
# Create an unlinked GPO
New-GPO -Name "Windows Update - Ring 1 (Pilot)" -Comment "Pilot ring - 0 day deferral"

# Create and link in one step
New-GPO -Name "Windows Update - Ring 2 (Fast)" | New-GPLink -Target "OU=Workstations,OU=Computers,DC=gntech,DC=me"
```

### Linking an Existing GPO

```powershell
# Link to an OU
New-GPLink -Name "Windows Update - Ring 1 (Pilot)" -Target "OU=Pilot,OU=Workstations,OU=Computers,DC=gntech,DC=me"

# Link to domain
New-GPLink -Name "Windows Update - Base Policy" -Target "DC=gntech,DC=me"

# Set link order and enable/disable
Set-GPLink -Name "Windows Update - Ring 1 (Pilot)" -Target "OU=Pilot,OU=Workstations,OU=Computers,DC=gntech,DC=me" -Order 1 -Enabled Yes
```

Link order matters — lower numbers have higher precedence. The last
applied GPO wins in case of conflict.

## GPO Inheritance and Processing Order

Policy applies in this order:

1. **Local** (stored on the machine)
2. **Site** — linked to the AD site the computer belongs to
3. **Domain** — linked at the domain root
4. **OU** — linked to the OU and its parent OUs (parent first, child last)

When multiple GPOs apply at the same level, the one with the lowest
link order wins. You can override this with:

- **Enforced** (No Override) — forces the GPO to apply regardless of
  lower-level settings. Use sparingly.
- **Block Inheritance** — stops higher-level GPOs from applying to an
  OU. Use rarely; it makes troubleshooting harder.

```powershell
# Enforce a GPO link (No Override)
Set-GPLink -Name "Security Baseline" -Target "DC=gntech,DC=me" -Enforced Yes

# Block inheritance on an OU
Set-GPInheritance -Target "OU=RestrictedWorkstations,OU=Computers,DC=gntech,DC=me" -IsBlocked Yes
```

## Security Filtering

By default, a new GPO applies to **Authenticated Users** — everyone in
the domain. In production, you almost never want that.

### Applying GPOs to Specific Security Groups

1. In GPMC, select the GPO
2. In the **Scope** tab, under **Security Filtering**, select
   **Authenticated Users** and click **Remove**
3. Click **Add**, type the security group name (e.g.,
   `WS-Pilot-Ring`), and click **OK**
4. The GPO now applies only to members of that group

**Important:** The computer account itself needs **Read** and **Apply**
permissions to process a Computer Configuration GPO. When you add a
security group of computers, computer members inherit those
permissions automatically.

```powershell
# Add security filtering via PowerShell
$gpo = Get-GPO -Name "Windows Update - Ring 1 (Pilot)"
Set-GPPermissions -Name "Windows Update - Ring 1 (Pilot)" -TargetName "WS-Pilot-Ring" -TargetType Group -PermissionLevel GpoApply

# Remove Authenticated Users
Set-GPPermissions -Name "Windows Update - Ring 1 (Pilot)" -TargetName "Authenticated Users" -TargetType Group -PermissionLevel None
```

### Delegation (Non-Admin GPO Editing)

To let a helpdesk team edit a specific GPO without giving them Domain
Admin:

```powershell
Set-GPPermissions -Name "Windows Update - Ring 1 (Pilot)" -TargetName "GPO-Editors" -TargetType Group -PermissionLevel GpoEditDeleteModifySecurity
```

Available permission levels: `GpoRead`, `GpoApply`, `GpoEdit`,
`GpoEditDeleteModifySecurity`, `GpoCustom`.

## WMI Filtering

WMI filters scope GPOs based on system attributes — OS version, RAM,
disk space, installed software. Only computers matching the WMI query
process the GPO.

### Creating a WMI Filter

**Example — apply only to Windows 11 workstations:**

```wmi
SELECT * FROM Win32_OperatingSystem WHERE Version LIKE "10.0.2%" AND ProductType = "1"
```

- `Version LIKE "10.0.2%"` — Windows 11 family (5 = Server 2022,
  10.0.20348; Server 2025 is 10.0.26100)
- `ProductType = "1"` — workstation only (not server)

**Example — apply only to Windows Server 2025:**

```wmi
SELECT * FROM Win32_OperatingSystem WHERE Version = "10.0.26100" AND ProductType <> "1"
```

**To create via GPMC:**

1. Right-click **WMI Filters** → **New**
2. Name the filter, add the query, click **Save**
3. Select a GPO → **Scope** tab → in **WMI Filtering**, select the filter

**To create via PowerShell:**

```powershell
$query = "SELECT * FROM Win32_OperatingSystem WHERE Version LIKE '10.0.2%' AND ProductType = '1'"
New-GPWmiFilter -Name "Windows 11 Workstations" -Description "Applies only to Windows 11 client devices" -Content $query
```

WMI filters can hurt performance if the query is slow or if many GPOs
are filtered. Keep queries simple and avoid uncapped `WHERE` clauses.

## GPO Backup and Restore

Backups are critical. A misconfigured GPO can break an entire
organization.

### Backup via PowerShell

```powershell
# Backup a single GPO to a timestamped folder
$backupPath = "C:\GPOBackups\$(Get-Date -Format 'yyyy-MM-dd')"
Backup-GPO -Name "Windows Update - Ring 1 (Pilot)" -Path $backupPath -Comment "Pre-WUfB configuration"

# Backup all GPOs in the domain
Backup-GPO -All -Path $backupPath -Comment "Domain-wide GPO backup $(Get-Date -Format 'yyyy-MM-dd')"
```

### Backup via GPMC GUI

1. Right-click **Group Policy Objects** → **Back Up All**
2. Choose a path and click **Back Up**

### Restore via PowerShell

```powershell
# Find backups
Get-GPOBackup -Path $backupPath -All

# Restore a specific GPO from its most recent backup
Restore-GPO -Name "Windows Update - Ring 1 (Pilot)" -Path $backupPath
```

### Export/Import (Cross-Domain)

GPMC supports migration tables for cross-domain GPO copy, remapping
security principals and UNC paths:

```powershell
# Export
$gpo = Get-GPO -Name "Security Baseline"
$gpo.GenerateReport -ReportType Xml | Out-File C:\GPExport\SecBaseline.xml

# Create migration table
New-GPMigrationTable -Path C:\GPExport\migration-table.migtable -Mapping @{
    "gntech\Domain Admins" = "targetdom\Domain Admins"
}
```

## HTML Reporting and RSoP

GPMC can generate HTML reports of GPO settings without opening the
editor.

### GPO Settings Report

```powershell
Get-GPOReport -Name "Windows Update - Ring 1 (Pilot)" -ReportType Html -Path "C:\Reports\WURing1.html"
```

### Resultant Set of Policy (RSoP)

**Group Policy Results** — what is actually applied (reactive):

In GPMC, right-click **Group Policy Results** → **Group Policy Results
Wizard** → specify a remote computer and user. The HTML output shows
all GPOs applied, denied GPOs with reasons, and the final setting
values.

```powershell
# PowerShell equivalent
Get-GPResultantSetOfPolicy -Computer "WS-Client01" -User "gntech\administrator" -ReportType Html -Path "C:\Reports\RSoP-WS-Client01.html"
```

**Group Policy Modeling** — what would apply (simulation):

In GPMC, right-click **Group Policy Modeling** and configure OU,
security groups, and WMI filters. This is invaluable before deploying
a new GPO.

## Windows Update for Business via GPO

With WSUS deprecated by Microsoft in September 2024, the recommended
replacement for on-premises update management is **Windows Update for
Business (WUfB)** configured through Group Policy. WUfB directs clients
to Microsoft's Windows Update service, not to a local WSUS server.

> **Note:** WUfB was formerly called "Windows Update for Business" and
> is now referred to in documentation as "Windows Update client
> policies." The GPO category is still labeled **Windows Update for
> Business**.

### Deployment Ring Strategy

We create three security groups in AD and corresponding GPOs:

| Ring | Group | Deferral | Purpose |
|---|---|---|---|
| Pilot | `WS-WU-Pilot` | 0 days quality, 0 days feature | IT/admin workstations, test VMs |
| Fast | `WS-WU-Fast` | 5 days quality, 30 days feature | Early adopters, dev machines |
| Slow | `WS-WU-Slow` | 10 days quality, 120 days feature | Production, critical systems |

### Step 1 — Create Security Groups

In **Active Directory Users and Computers** or via PowerShell:

```powershell
$groups = @("WS-WU-Pilot", "WS-WU-Fast", "WS-WU-Slow")
foreach ($group in $groups) {
    New-ADGroup -Name $group -GroupScope Global -GroupCategory Security -Path "OU=Groups,DC=gntech,DC=me"
}
```

Add computer accounts to the appropriate group.

### Step 2 — Create GPOs for Each Ring

From a management workstation with GPMC:

```powershell
# Create base Windows Update policy GPO
New-GPO -Name "Windows Update - Base Policy" -Comment "Base WUfB settings shared across all rings"
New-GPLink -Name "Windows Update - Base Policy" -Target "DC=gntech,DC=me"

# Create ring-specific GPOs
New-GPO -Name "Windows Update - Pilot Ring" -Comment "0 day quality deferral, no feature deferral"
New-GPO -Name "Windows Update - Fast Ring" -Comment "5 day quality deferral, 30 day feature deferral"
New-GPO -Name "Windows Update - Slow Ring" -Comment "10 day quality deferral, 120 day feature deferral"

# Link ring GPOs to the domain root (filtered by security groups)
New-GPLink -Name "Windows Update - Pilot Ring" -Target "DC=gntech,DC=me"
New-GPLink -Name "Windows Update - Fast Ring" -Target "DC=gntech,DC=me"
New-GPLink -Name "Windows Update - Slow Ring" -Target "DC=gntech,DC=me"
```

### Step 3 — Configure the Base Policy

Edit **Windows Update - Base Policy** in GPMC and navigate to:

```
Computer Configuration
  └─ Policies
      └─ Administrative Templates
          └─ Windows Components
              └─ Windows Update
```

Configure these settings:

| Setting | Value | Path |
|---|---|---|
| **Configure Automatic Updates** | Enabled → **2 - Notify for download and auto install** | `Windows Update` |
| **Configure Automatic Updates → Install updates for other Microsoft products** | Enabled | `Windows Update` |
| **Do not include drivers with Windows Updates** | Disabled (default — let drivers update) | `Windows Update` |
| **Turn on Software Notifications** | Enabled | `Windows Update` |
| **Specify intranet Microsoft update service location** | Not configured (we use WUfB, not WSUS) | `Windows Update` |

### Step 4 — Configure Deferral Policies

Under the same path, go deeper to:

```
Computer Configuration
  └─ Policies
      └─ Administrative Templates
          └─ Windows Components
              └─ Windows Update
                  └─ Windows Update for Business
```

Edit each ring GPO:

**Pilot Ring:**

| Setting | Value |
|---|---|
| **Select when Preview Builds and Feature Updates are received** | Enabled → **Deferral (0 days)**, **Pause (Disabled)** |
| **Select when Quality Updates are received** | Enabled → **Deferral (0 days)**, **Pause (Disabled)** |

**Fast Ring:**

| Setting | Value |
|---|---|
| **Select when Preview Builds and Feature Updates are received** | Enabled → **Deferral (30 days)**, **Pause (Disabled)** |
| **Select when Quality Updates are received** | Enabled → **Deferral (5 days)**, **Pause (Disabled)** |

**Slow Ring:**

| Setting | Value |
|---|---|
| **Select when Preview Builds and Feature Updates are received** | Enabled → **Deferral (120 days)**, **Pause (Disabled)** |
| **Select when Quality Updates are received** | Enabled → **Deferral (10 days)**, **Pause (Disabled)** |

The maximum deferral periods are:
- **Feature updates:** 365 days
- **Quality updates:** 30 days

### Step 5 — Apply Security Filtering

For each ring GPO, remove `Authenticated Users` and add the
corresponding security group:

```powershell
# Remove Authenticated Users from all ring GPOs
$ringGpos = @("Windows Update - Pilot Ring", "Windows Update - Fast Ring", "Windows Update - Slow Ring")
foreach ($gpoName in $ringGpos) {
    Set-GPPermissions -Name $gpoName -TargetName "Authenticated Users" -TargetType Group -PermissionLevel None
}

# Add security groups
Set-GPPermissions -Name "Windows Update - Pilot Ring" -TargetName "WS-WU-Pilot" -TargetType Group -PermissionLevel GpoApply
Set-GPPermissions -Name "Windows Update - Fast Ring" -TargetName "WS-WU-Fast" -TargetType Group -PermissionLevel GpoApply
Set-GPPermissions -Name "Windows Update - Slow Ring" -TargetName "WS-WU-Slow" -TargetType Group -PermissionLevel GpoApply
```

### Step 6 — Configure Delivery Optimization

Delivery Optimization (DO) is Windows' peer-to-peer update distribution
system. In a homelab with limited bandwidth, DO can help, but for a
small number of machines it is often unnecessary.

Navigate to:

```
Computer Configuration
  └─ Policies
      └─ Administrative Templates
          └─ Windows Components
              └─ Delivery Optimization
```

Recommended settings for a homelab:

| Setting | Value |
|---|---|
| **Download mode** | **1 (HTTP + Peering on same NAT)** — LAN-only peering; or **0 (HTTP only)** to disable P2P entirely |
| **Absolute max cache size** | **Enabled** → **4096** (4 GB cache) |
| **Maximum upload bandwidth** | Not configured |

```powershell
# Verify Delivery Optimization settings on a client
Get-DeliveryOptimizationStatus
```

### Step 7 — Verify Application

From a domain-joined client in the Pilot ring, run:

```powershell
# Force Group Policy refresh
gpupdate /force

# View applied GPOs
gpresult /r

# View WUfB configuration
$updateSettings = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
$updateSettings | Format-List

# Check deferral configuration
reg query "HKLM\SOFTWARE\Microsoft\WindowsUpdate\UpdatePolicy\PolicyStates" /s
```

Expected output from `gpresult /r` should show the base and ring GPOs
applied. If they do not appear, check:

1. Is the computer in the correct security group?
2. Does the GPO link apply to the computer's OU?
3. Is `Authenticated Users` still in security filtering? (It should be
   removed.)
4. Run `rsop.msc` on the client for a GUI RSoP view.

### Pausing Updates

If a bad update is deployed, pause it for up to 35 days via one GPO:

```
Computer Configuration
  └─ Policies
      └─ Administrative Templates
          └─ Windows Components
              └─ Windows Update
                  └─ Windows Update for Business
                      └─ Select when Quality Updates are received
                          → Check "Pause quality updates"
```

```powershell
# Alternatively, pause via PowerShell on the client
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings" -Name "PauseQualityUpdatesStartTime" -Value (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
```

## Common GPO Troubleshooting

### GPO Not Applying

1. **Replication delay:** Check SYSVOL and AD replication across DCs
   ```powershell
   repadmin /replsummary
   dcdiag /test:replications
   ```
2. **Security filtering mismatch:** Ensure the computer or user account
   is a member of the security group and that the group has `Apply
   Group Policy` permission
3. **WMI filter failure:** Run the WMI query directly on the client
   ```powershell
   Get-WmiObject -Query "SELECT * FROM Win32_OperatingSystem WHERE Version LIKE '10.0.2%'"
   ```
4. **Inheritance blocked:** Check if Block Inheritance is set on the OU
5. **Slow Link Detection:** By default, GPO does not apply over slow
   links for certain settings. Override with:
   ```
   Computer Configuration → Administrative Templates → System → Group Policy
   → Group Policy slow link detection → Disabled
   ```

### GPO Conflict

If two GPOs set the same policy, the one with the highest precedence
(lowest link order) wins. Check the precedence chain using `gpresult /h
C:\report.html` and review the **Winning GPO** and **Filtered GPOs**
sections.

## What We Built

| Component | Purpose |
|---|---|
| GPMC installed (Server Core via PowerShell, DCs via GUI, Windows 11 via RSAT) | Management platform |
| ADMX Central Store | Single source of truth for policy templates |
| 3 deployment ring GPOs | Phased Windows Update rollout |
| Security filtering | Ring membership via AD security groups |
| WMI filtering (optional) | OS-specific GPO targeting |
| GPO modeling | Pre-deployment validation |
| GPO backup | Disaster recovery |
| Delivery Optimization | Peer-to-peer update distribution |

## Next in the Series

With GPO management in place, the next post covers hybrid identity
sync — installing Microsoft Entra Connect to synchronize on-premises
users and groups to the cloud, setting the stage for Entra ID hybrid
join, Windows Hello for Business, and cloud file access.

> **Post 2: Microsoft Entra Connect — On-Premises to Cloud Identity
> Sync**

## References

- [Group Policy overview for Windows Server](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/group-policy/group-policy-overview)
- [Group Policy Management Console](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/group-policy/group-policy-management-console)
- [Configure Windows Update client policies via Group Policy](https://learn.microsoft.com/en-us/windows/deployment/update/waas-wufb-group-policy)
- [Create and Manage Central Store](https://learn.microsoft.com/en-us/troubleshoot/windows-client/group-policy/create-and-manage-central-store)
- [Administrative Templates (.admx) for Windows Server 2025](https://www.microsoft.com/en-us/download/details.aspx?id=108430)
- [Administrative Templates (.admx) for Windows 11 25H2](https://www.microsoft.com/en-us/download/details.aspx?id=108394)
- [Delivery Optimization reference](https://learn.microsoft.com/en-us/windows/deployment/do/waas-delivery-optimization-reference)
- [Group Policy Settings Reference Spreadsheets](https://www.microsoft.com/en-us/download/details.aspx?id=25250)
