---
title: "Windows Server 2025: Microsoft Entra Connect — On-Premises to Cloud Identity Sync"
description: "Complete guide to installing and configuring Microsoft Entra Connect v2 for hybrid identity: prerequisites, express vs custom install, password hash sync, OU filtering, attribute synchronization, writeback, staging mode, and mandatory upgrade before Sep 30, 2026."
date: 2026-05-14T13:00:00-04:00
tags:
  - windows-server
  - entra-id
  - hybrid-identity
  - active-directory
  - azure-ad-connect
keywords:
  - Microsoft Entra Connect install
  - Entra Connect v2 prerequisites
  - hybrid identity sync on-premises to cloud
  - password hash synchronization
  - Entra Connect staging mode
  - OU filtering sync
summary: "Step-by-step Microsoft Entra Connect v2 installation on Windows Server 2025: prerequisites, express install, custom configuration with OU filtering and writeback, verification, and mandatory upgrade before September 30, 2026."
canonical: "https://blog.gntech.me/posts/windows-server-2025-entra-connect-sync/"
cover:
  image: "https://upload.wikimedia.org/wikipedia/commons/2/26/Windows_Server_logo.svg"
  alt: "Windows Server logo"
  caption: "Windows Server logo — © Microsoft Corporation (public domain as simple geometric logo)"
---

Hybrid identity is the bridge. On-premises Active Directory holds your
users, groups, and computers. Microsoft Entra ID (formerly Azure AD)
powers Microsoft 365, Azure, and third-party SaaS apps. Without
synchronization, you manage two directories — and they inevitably drift
apart.

**Microsoft Entra Connect** is the tool that synchronizes on-premises
AD objects to Entra ID. It replaces the older DirSync and Azure AD
Sync tools. As of 2026, only Entra Connect v2 is supported, and
Microsoft has announced that all sync services **will stop on
September 30, 2026** if you are not on at least version **2.5.79.0**.

This guide walks through installing Entra Connect v2 on Windows Server
2025, configuring password hash sync, OU-based filtering, optional
writeback features (password, device, group), staging mode, and
verification.

> **Screenshots and images to add later:**
>
> - Entra Connect download page in Entra admin center
> - Express settings welcome screen
> - Connect to Microsoft Entra ID credentials dialog
> - Domain/OU filtering page
> - Optional features page (password/device/group writeback)
> - Ready to configure summary
> - Synchronization Service Manager UI
> - Synchronization statistics showing imported/exported objects
> - Entra admin center showing synced users
> - Staging mode configuration

## Prerequisites

### Microsoft Entra (Cloud)

- A Microsoft Entra tenant (get one with an [Azure free trial](https://azure.microsoft.com/pricing/free-trial/))
- A verified custom domain (e.g., `gntech.me` — not just `tenant.onmicrosoft.com`)
- A **Hybrid Identity Administrator** account in the Entra tenant (or
  Global Administrator)
- At least a **Microsoft Entra ID Free** license (P1/P2 unlocks features
  like writeback, password protection, and Self-Service Password Reset)

### Verify Your Domain

If your domain is not yet verified in Entra ID:

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com)
2. Go to **Identity** → **Settings** → **Domain names**
3. Click **Add custom domain**, enter `gntech.me`
4. Add the TXT verification record to your public DNS zone
5. Wait for propagation and click **Verify**

### On-Premises Active Directory

- AD schema + forest functional level: **Windows Server 2003 or later**
  (Server 2025 is fine)
- Domain controller must be **writable** (no RODC)
- At least one DC in the same site as the Entra Connect server (or
  accessible via low-latency link)

### Entra Connect Server Hardware

Entra Connect v2 must run on a **Windows Server 2016 or later**.
Windows Server 2025 is fully supported.

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 1.6 GHz, 2 cores | 2.0 GHz, 4 cores |
| RAM | 8 GB | 16 GB |
| Disk | 70 GB | 100 GB (SSD) |

The server should be:
- **Domain-joined** to `gntech.me`
- **Not a domain controller** (install on a member server)
- Running **Windows Server 2025 Standard or Datacenter**

### Software Prerequisites

Entra Connect v2 installs these automatically, but confirm:

- .NET Framework 4.7.2 or later (Server 2025 ships with newer versions)
- PowerShell 5.0 or later
- TLS 1.2 enabled

```powershell
# Verify TLS 1.2 is enabled
[System.Net.ServicePointManager]::SecurityProtocol
# Should include: Tls12

# Enable TLS 1.2 system-wide if needed
New-Item 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2\Client' -Force
New-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2\Client' -Name Enabled -Value 1 -PropertyType DWORD
New-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2\Client' -Name DisabledByDefault -Value 0 -PropertyType DWORD
```

### Network Requirements

The Entra Connect server needs outbound HTTPS (TCP 443) to:

- `*.msappproxy.net`
- `*.servicebus.windows.net`
- `login.microsoftonline.com`
- `*.microsoftonline.com`

In a homelab with restricted outbound internet, ensure your firewall
allows these destinations. A proxy can be configured during
installation.

### Clean Up Your AD Data

Run the [IdFix tool](https://github.com/Microsoft/idfix) before
installing Entra Connect. It identifies duplicate UPNs, invalid
characters, and formatting issues that cause sync errors:

```powershell
# Download and run IdFix
Invoke-WebRequest -Uri "https://github.com/Microsoft/idfix/releases/latest/download/IdFix.zip" -OutFile "$env:TEMP\IdFix.zip"
Expand-Archive -Path "$env:TEMP\IdFix.zip" -DestinationPath "C:\IdFix"
.\C:\IdFix\IdFix.exe
```

IdFix scans your AD and presents errors. Click **Accept** on each
action to fix them, then click **Apply**.

## Downloading Entra Connect

Entra Connect v2 is available **only** from the Microsoft Entra admin
center (not from the download center's public page):

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com)
2. Navigate to **Identity** → **Hybrid management** → **Microsoft
   Entra Connect** → **Connect Sync**
3. Click **Download Microsoft Entra Connect** → the installer is named
   `AzureADConnect.msi` (version 2.x.x.x)

## Express Installation (Single Forest)

The **Express** option is for single-forest AD with password hash sync.
It configures everything with defaults — perfect for a homelab.

### Step 1 — Run the Installer

```powershell
# From the download location
.\AzureADConnect.msi
```

### Step 2 — Express Settings

1. On the **Welcome** screen, accept the license terms and click
   **Continue**

2. Click **Express Settings** (or **Customize** for advanced options)

3. **Connect to Microsoft Entra ID**
   - Enter your Hybrid Identity Administrator credentials (e.g.,
     `admin@gntech.me`)
   - Click **Next**

4. **Connect to Active Directory**
   - Enter your on-premises AD Enterprise Admin credentials
     (`GNTECH\Administrator`)
   - Entra Connect discovers your local AD forest automatically
   - Click **Next**

5. **Ready to Configure**
   - Review the summary: password hash sync enabled, auto upgrade on,
     no writeback
   - Check the box **Start the synchronization process as soon as the
     configuration completes**
   - Click **Install**

Installation takes 5–15 minutes. When complete, the wizard shows the
**Configuration complete** screen.

### Step 3 — Verify Initial Sync

On the Entra Connect server, open **Synchronization Service Manager**:

```powershell
# Launch from Start menu or
"C:\Program Files\Microsoft Azure AD Sync\UIShell\MiisClient.exe"
```

Look for:

- **Management Agents** tab → `gntech.me` (on-prem AD) and
  `Microsoft Entra ID` (cloud) agents present
- **Operations** tab → a completed **Initial Sync** run with imported
  and exported objects

In the Entra admin center:

1. Go to **Identity** → **Users** → **All users**
2. Confirm users from `gntech.me` appear with **Synced from on-premises**
   in the Source column
3. Check **Identity** → **Groups** → **All groups** for synced security
   groups

## Custom Installation

Use **Custom** when you need:
- Multi-forest topologies
- OU filtering (sync only specific OUs)
- Optional features (password writeback, device writeback, group writeback)
- Federated sign-in (AD FS or 3rd party)
- Staging mode

### Step 1 — Run Custom Install

```powershell
.\AzureADConnect.msi
```

On **Welcome**, click **Customize** (not Express).

### Step 2 — Options

| Option | Recommendation for Homelab |
|---|---|
| **Password Hash Synchronization** | ✅ Enabled — simplest and most secure for lab |
| **Pass-through Authentication** | ❌ Skip — requires more infrastructure (connector agents) |
| **Federation with AD FS** | ❌ Skip — overkill for single-domain homelab |
| **Do not configure** | ❌ Avoid — you need at least one sign-in method |
| **Enable device writeback** | ✅ Enable if you plan to deploy Hybrid Entra Join |
| **Enable directory extension attribute sync** | ✅ Enable (adds AD attributes to cloud) |
| **Enable password writeback** | ⏹ Enable after sync is verified (see Post #3) |

### Step 3 — OU Filtering (Important)

By default, Entra Connect syncs **all** OUs in the domain. In a
homelab with test users, guest accounts, or service accounts that
should not sync to the cloud, restrict it:

1. On the **Domain/OU filtering** page, select **Sync selected domains
   and OUs**
2. Check only the OUs you want to sync:
   ```
   ✓ DC=gntech,DC=me
     ├─ ✓ OU=Users
     ├─ ✓ OU=Workstations
     ├─ ✓ OU=Servers
     ├─ ✓ OU=Groups
     └─ ✗ OU=ServiceAccounts
         └─ ✗ OU=Test
   ```
3. Click **Next**

OU filtering can be changed later, but a full sync cycle runs after
each change.

### Step 4 — Attribute Sync Configuration

On the **Optional Features** page:

- Check **Directory extension attribute sync** if you need custom AD
  attributes in Entra ID (useful for custom claims or apps)
- Check **Password writeback** and **Device writeback** (covered in
  Post #3)

Leave **Exchange hybrid deployment** unchecked unless you run Exchange
on-premises.

### Step 5 — Install

Review the summary, verify settings, check **Start the
synchronization process** and click **Install**.

## Post-Installation Verification

### 1. Synchronization Service Manager

```powershell
# Open Synchronization Service Manager
Start-Process "C:\Program Files\Microsoft Azure AD Sync\UIShell\MiisClient.exe"
```

Check the **Operations** tab. A successful initial sync shows:
- **Import** (staging) → objects pulled from AD and from Entra ID
- **Synchronization** (delta) → differences computed
- **Export** → changes written to target

Expected exports after initial sync:
- **Connector = gntech.me** (on-prem): near-zero exports (cloud objects
  written back, e.g., device writeback)
- **Connector = Entra ID**: users, groups, contacts exported to cloud

### 2. PowerShell Verification

```powershell
# Check sync cycle status
Get-ADSyncScheduler

# View scheduler configuration
Get-ADSyncScheduler | Format-List

# Check connector status
Get-ADSyncConnector | Format-Table Name, ConnectorType, TimeCreated
```

### 3. Entra Admin Center

- **Identity** → **Users** → **All users** — verify synced users
- **Identity** → **Groups** → **All groups** — verify groups
- **Identity** → **Devices** → **All devices** — verify if device
  writeback is enabled

### 4. UPN Mismatch Check

If a user's on-prem UPN suffix is not verified in Entra ID, the
default domain (`tenant.onmicrosoft.com`) is used as fallback. Verify
your custom domain is added and the UPN suffixes match:

```powershell
# Check all UPN suffixes in AD
Get-ADForest | Select-Object -ExpandProperty UPNSuffixes

# Check a specific user
Get-ADUser "jsmith" -Properties UserPrincipalName | Select UserPrincipalName
```

All UPN suffixes should be verified in Entra ID.

## Managing Sync Scope (OU Filtering)

After installation, you can change which OUs are synced:

### Via GUI

1. Start **Microsoft Entra Connect** from the Start menu
2. Click **Configure** → **Customize synchronization options**
3. Enter credentials when prompted
4. On **Domain/OU filtering**, adjust selections
5. Complete the wizard — a full sync cycle runs automatically

### Via PowerShell

```powershell
# Disable sync for a specific OU
Set-ADSyncOrganizationalUnit -OrganizationalUnit "OU=Test,DC=gntech,DC=me" -Enabled $false

# Enable sync for an OU
Set-ADSyncOrganizationalUnit -OrganizationalUnit "OU=Users,DC=gntech,DC=me" -Enabled $true

# Start a full sync to apply changes
Start-ADSyncSyncCycle -PolicyType Initial
```

## Attribute-Based Filtering (Advanced)

Beyond OU filtering, you can filter objects by attribute:

```powershell
# Sync only users in a specific group
# This requires modifying the Synchronization Rules in the Sync Rules Editor
# Recommended approach: use OU filtering for simplicity in homelabs
```

Attribute filtering is managed through the **Synchronization Rules
Editor** (found in the Start menu under Microsoft Entra Connect). Each
sync rule can filter by attribute value. This is advanced — for a
homelab, OU filtering is sufficient.

## The Sep 30, 2026 Upgrade Deadline

Microsoft announced that **all Entra Connect Sync services will stop
working on September 30, 2026** if you are not on at least **version
2.5.79.0**.

### Check Your Version

```powershell
# One-liner
(Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Azure AD Connect\").Version

# Or via the installer path
Get-Item "C:\Program Files\Microsoft Azure AD Sync\Bin\miiskmu.exe" | Select-Object ProductVersion
```

### Upgrade

1. Download the latest `AzureADConnect.msi` from the Entra admin center
2. Run the installer — it detects the existing installation and upgrades
   in place
3. Click **Upgrade** (not reinstall)

No configuration changes are needed. The wizard preserves all settings.

### What Happens If You Miss the Deadline

- All sync cycles **stop**
- New users, groups, and password changes in AD are **not replicated to
  Entra ID**
- Password change/SSPR writeback **fails**
- **Existing users and groups remain** in the cloud (no data deletion)
- To restore sync, upgrade Entra Connect — a full sync cycle runs after

## Scheduling and Performance

Entra Connect syncs on a schedule. The default is **every 30 minutes**.

```powershell
# View schedule
Get-ADSyncScheduler | Select CustomizedSyncCycleInterval

# Adjust sync interval (minimum 30 minutes)
Set-ADSyncScheduler -CustomizedSyncCycleInterval 00:30:00

# Force an immediate sync
Start-ADSyncSyncCycle -PolicyType Delta
```

For a homelab, 30 minutes is fine. For testing, you can trigger delta
syncs on demand.

## Staging Mode

Staging mode installs Entra Connect without exporting changes to the
cloud. The server imports and syncs locally but does not write to
Entra ID. This lets you verify the configuration before going live.

### Enable During Installation

On the **Ready to configure** page, check **Enable staging mode**.

### Enable After Installation

```powershell
# Via GUI: restart the wizard → Configure → Staging mode
# Via PowerShell:
Set-ADSyncScheduler -StagingModeEnabled $true

# Start sync in staging mode (imports and syncs but no exports)
Start-ADSyncSyncCycle -PolicyType Initial

# Check staging status
Get-ADSyncScheduler | Select StagingModeEnabled
```

To exit staging mode, set `StagingModeEnabled $false` and run a full
sync cycle. The next export writes all pending changes to Entra ID.

### When to Use Staging Mode

- **Before going live** with a first-time sync
- **After configuration changes** (new OU, changed attribute mapping)
- **As disaster recovery** standby — install a second Entra Connect
  server in staging mode. If the primary fails, promote staging to
  production by disabling staging mode.

## Disaster Recovery

Entra Connect stores its configuration in the **ADSync** database
(local SQL Express by default, or a full SQL Server instance). To
recover:

1. Install a new member server
2. Run the Entra Connect installer
3. Choose **Customize** → **Restore from a previously created backup**
   (requires the `%ProgramData%\AADConnect\` backup, exported earlier)

Export the configuration periodically:

```powershell
# Export configuration
Export-ADSyncSyncConfig -Path "C:\Backups\sync-config-$(Get-Date -Format 'yyyy-MM-dd').json"
```

The real disaster recovery best practice is a **staging mode server**,
not a config-only backup.

## Common Issues

### "Object is not synced" — UPN Not Verified

**Cause:** The user's UPN suffix (e.g., `@gntech.me`) is not verified
in Entra ID.

**Fix:** Verify the custom domain in Entra admin center → **Domain
names**.

### Sync Export Errors

Check the **Synchronization Service Manager** → **Operations** tab for
errors. Common export errors:

| Error | Cause | Fix |
|---|---|---|
| "Duplicate attribute" | Two objects with the same `proxyAddresses` | Run IdFix |
| "Invalid UPN" | Special characters in UPN | Clean AD data |
| "Missing source anchor" | `ms-ds-consistencyGUID` missing (immutableId) | Attribute sync round-trip |

### Users Not Appearing

1. Is the OU being synced? Check OU filtering.
2. Is the user enabled? Disabled users are synced by default unless
   filtered via attribute.
3. Check if the user passes the connector space filter → run a preview
   in the Sync Rules Editor.

## What We Built

| Component | Detail |
|---|---|
| Entra Connect v2 installation | Express or Custom on Windows Server 2025 |
| Password hash sync | On-prem password hash replicated to cloud |
| OU filtering | Selective sync of `Users`, `Workstations`, `Servers`, `Groups` |
| Writeback ready | Password writeback enabled (config in Post #3) |
| Staging mode | Verification before production writes |
| Backup config | Export JSON for disaster recovery |
| Upgrade awareness | Version check, Sep 2026 deadline noted |

## Next in the Series

With identity sync flowing, the next post covers the reverse direction
— writeback. Password changes in the cloud are written back to
on-premises AD, device registrations are written back for conditional
access, and Microsoft 365 groups are synchronized to Exchange Online:

> **Post 3: Writeback — Cloud to On-Premises (Password, Device, and
> Group)**

After that:

- **Post 4:** Entra ID Hybrid Join + Device Registration
- **Post 5:** Windows Hello for Business — Hybrid Key Trust
- **Post 6:** Self-Service Password Reset (SSPR)

## References

- [Install Microsoft Entra Connect — Roadmap](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-install-roadmap)
- [Microsoft Entra Connect: Prerequisites](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-install-prerequisites)
- [Express installation](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-install-express)
- [Custom installation](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-install-custom)
- [Staging mode](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-sync-staging-server)
- [Password hash synchronization](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-password-hash-synchronization)
- [IdFix tool](https://github.com/Microsoft/idfix)
- [Verify installation](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-post-installation)
