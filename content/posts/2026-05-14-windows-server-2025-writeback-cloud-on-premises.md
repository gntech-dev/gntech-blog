---
title: "Windows Server 2025: Writeback — Cloud to On-Premises (Password, Device, and Group)"
description: "Enable password writeback with SSPR, device writeback for Hybrid Entra Join and Conditional Access, and Microsoft 365 group writeback on Windows Server 2025 via Microsoft Entra Connect."
date: 2026-05-14T14:00:00-04:00
tags:
  - windows-server
  - entra-id
  - hybrid-identity
  - sspr
  - password-writeback
  - group-writeback
  - device-writeback
keywords:
  - password writeback Entra Connect
  - device writeback hybrid join
  - group writeback M365 groups
  - SSPR password reset writeback
  - cloud to on-premises writeback
  - Entra ID writeback configuration
summary: "Enable password writeback (SSPR), device writeback (Hybrid Entra Join), and group writeback (Microsoft 365 groups) from cloud to on-premises Active Directory using Entra Connect."
canonical: "https://blog.gntech.me/posts/windows-server-2025-writeback-cloud-on-premises/"
cover:
  image: "https://upload.wikimedia.org/wikipedia/commons/2/26/Windows_Server_logo.svg"
  alt: "Windows Server logo"
  caption: "Windows Server logo — © Microsoft Corporation (public domain as simple geometric logo)"
---

Writeback is the reverse direction of hybrid identity. In the previous
post, Entra Connect synchronized users, groups, and passwords from
on-premises Active Directory to Microsoft Entra ID. Writeback moves
data in the opposite direction — from the cloud back to your on-premises AD.

Three writeback types matter in a modern hybrid environment:

| Writeback | What It Does | Why You Need It |
|---|---|---|
| **Password** | Cloud password changes/ resets are written back to on-premises AD in real time | Enables Self-Service Password Reset (SSPR); users reset passwords from anywhere |
| **Device** | Devices registered in Entra ID appear as computer objects in on-premises AD | Required for Hybrid Entra Join, Conditional Access, Windows Hello for Business |
| **Group (M365)** | Microsoft 365 groups are created in on-premises AD | Mail-enabled security groups for hybrid Exchange; deprecated for cloud-only groups |

> **Important deprecation notice:** Group Writeback v2 in Entra Connect
> Sync is **deprecated**. Microsoft recommends using **Entra Cloud
> Sync** for provisioning cloud security groups to on-premises AD. If
> you need Microsoft 365 groups written back, Group Writeback v1 is
> still supported through Entra Connect Sync. Read the group writeback
> section carefully before enabling.

> **Screenshots and images to add later:**
>
> - Entra Connect wizard — Additional Tasks page showing writeback options
> - Password writeback option in Entra Connect
> - SSPR configuration in Entra admin center — writeback toggle
> - Device writeback — forest selection
> - Device writeback — OU container configuration
> - Group writeback — OU selection
> - User SSPR registration portal
> - Confirmation of synced device in AD

## Prerequisites

This post builds on the previous one. Before starting:

1. **Microsoft Entra Connect v2** installed and syncing (Post #2)
2. **Password hash sync** enabled and verified
3. At least **Microsoft Entra ID P1** license (all writeback features
   require P1 or P2)
4. **Hybrid Identity Administrator** account in Entra ID
5. **Enterprise Admin** credentials for on-premises AD
6. Initial sync cycle completed (all users and groups visible in cloud)

## Password Writeback

Password writeback synchronizes password changes made in the cloud back
to on-premises AD. When a user changes or resets their password through
the SSPR portal (`https://aka.ms/sspr`), it is written to on-prem AD in
real time via the Entra Connect Azure Service Bus relay.

### How It Works

```
User → SSPR portal → Entra ID → Azure Service Bus → Entra Connect
    → AD DS (password updates in real time)
```

The connection is **outbound only** from the Entra Connect server. No
inbound firewall rules are needed. The Entra Connect server opens a
persistent outbound connection to an Azure Service Bus relay, and
password changes flow through it synchronously — the user sees
immediate feedback if the new password violates on-premises AD policy.

### Step 1 — Set AD Permissions

The Entra Connect AD Connector account needs specific permissions to
write passwords. These are set automatically during installation if you
run the wizard with Enterprise Admin credentials, but you should verify:

```powershell
# Run on a domain controller as Domain Admin
# Check if password writeback permissions are set
$adConnector = Get-ADUser "MSOL_*" -Filter * | Select-Object Name, DistinguishedName
Write-Host "AD Connector account: $($adConnector.Name)"

# If the account does not have Reset Password permission on user OUs,
# grant it via ADSI Edit or:
dsacls "OU=Users,DC=gntech,DC=me" /G "GNTECH\MSOL_xxxxx:CA;Reset Password;user"
```

The wizard handles this automatically in most cases.

### Step 2 — Enable Password Writeback in Entra Connect

1. On the Entra Connect server, run **Microsoft Entra Connect** from
   the Start menu
2. Click **Configure**
3. Select **Customize synchronization options** → **Next**
4. Enter credentials when prompted
5. Navigate through the wizard until **Optional Features**
6. Check the box **Password writeback**
7. Complete the wizard and commit the configuration

A full sync cycle runs to apply the change.

### Step 3 — Enable Password Writeback in SSPR

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com)
2. Go to **Identity** → **Protection** → **Password reset**
3. Under **Properties**, set **Self-service password reset enabled** to
   **Selected** or **All**
4. Go to **Authentication methods** and configure what users can use:
   - Number of methods required: **2**
   - Methods available: Mobile phone, Email, Security questions, etc.
5. Go to **Registration** → set **Require users to register when
   signing in** to **Yes**
6. Go to **On-premises integration**:
   - Set **Write back passwords to your on-premises directory** to **Yes**
   - Choose the OU where users receive password writeback (or leave
     default — writeback respects the user's current OU)
7. Click **Save**

### Step 4 — Test Password Writeback

**Via SSPR portal:**

1. Browse to `https://aka.ms/sspr` on a test user's device
2. Enter the test user's UPN (e.g., `testuser@gntech.me`)
3. Complete the CAPTCHA
4. Verify identity via configured method (phone, email)
5. Enter a new password and confirm
6. Check on-prem AD immediately:

```powershell
# Verify the password changed on-premises
Get-ADUser "testuser" -Properties PasswordLastSet, LastBadPasswordAttempt
```

**Via admin reset:**

1. In the Entra admin center, go to **Identity** → **Users** →
   **All users**
2. Select a test user → **Reset password**
3. Set a temporary password and click **Reset**
4. Verify on-prem AD password was updated:

```powershell
# Check that PasswordLastSet updated
Get-ADUser "testuser" -Properties PasswordLastSet, LastLogonDate
```

### Step 5 — Monitor Password Writeback

```powershell
# Check Entra Connect event logs for password writeback events
Get-WinEvent -LogName "Application" -ProviderName "PasswordWriteBack" | Select TimeCreated, Message
```

In Synchronization Service Manager, look for export runs with
**PasswordChange** or **PasswordSet** export types.

## Device Writeback

Device writeback registers devices from Entra ID as computer objects in
on-premises AD. This is a prerequisite for:

- **Hybrid Entra Join** (Post #4)
- **Windows Hello for Business — Hybrid Certificate Trust** (Post #5)
- **Conditional Access** against on-premises applications (via ADFS)

### How It Works

```
Hybrid-joined device → syncs to Entra ID during registration
    → Entra Connect picks up the device registration
    → writes object to on-prem AD under a designated OU
```

### Step 1 — Prerequisites

- **Entra ID P1 or P2** license
- **Entra Connect** fully installed and syncing (Post #2)
- A single AD forest (device writeback does not support multi-forest
  with users in one forest and devices in another)
- Devices registered or joining Entra ID

### Step 2 — Enable Device Writeback

1. On the Entra Connect server, run **Microsoft Entra Connect**
2. Click **Configure**
3. Select **Configure device options** → **Next**
4. On **Device options**, select **Configure device writeback** → **Next**
5. **Device writeback forest:** Select `gntech.me` (your AD forest)
6. **Device container:** Choose the OU for written-back devices:
   - Option A: **Provide enterprise admin credentials** — Entra Connect
     creates and configures the container automatically
   - Option B: **Download PowerShell script** — run it manually to
     prepare the container
7. Complete the wizard

### Step 3 — Verifying Device Objects

After device writeback is enabled, domain-joined devices that have
registered in Entra ID appear in AD:

```powershell
# Check the device writeback container
Get-ADComputer -Filter * -SearchBase "CN=RegisteredDevices,DC=gntech,DC=me" | Select Name, Enabled

# Check Entra Connect sync status for devices
Get-ADSyncRule -Identifier "In from AD - Device Join" | Format-List
```

Device objects in AD will have:
- `objectClass`: `computer`
- `userCertificate`: populated if Windows Hello for Business is configured
- `altSecurityIdentities`: populated for device registration

### Step 4 — Troubleshooting Device Writeback

If devices do not appear:

1. Is the device registered in Entra ID?
   ```
   Entra admin center → Identity → Devices → All devices
   ```
2. Has a sync cycle completed since registration?
   ```powershell
   Start-ADSyncSyncCycle -PolicyType Delta
   ```
3. Check for device writeback errors in:
   ```
   Synchronization Service Manager → Operations → look for export errors
   ```

## Group Writeback

Group writeback provisions cloud groups to on-premises AD. There are
two scenarios with different recommendations:

| Scenario | Recommendation |
|---|---|
| **Microsoft 365 groups** (Teams, Outlook groups) | Group Writeback v1 via Entra Connect Sync (still supported) |
| **Cloud-only security groups** | Use **Entra Cloud Sync** (Group Writeback v2 is deprecated) |

### Scenario 1: M365 Group Writeback (v1)

Microsoft 365 groups (formerly Office 365 Groups) are managed in the
cloud but need to exist on-premises for Exchange hybrid scenarios or
on-premises applications that read security groups from AD.

**Step 1 — Enable in Entra Connect**

1. Run **Microsoft Entra Connect** → **Configure**
2. Select **Customize synchronization options**
3. Navigate through the wizard to **Optional Features**
4. Check **Group writeback** (if it appears — v1 must be enabled in
   the sync rules editor if the checkbox is absent)
5. Select the destination OU for written-back groups
6. Complete the wizard

**Step 2 — Enable in Entra Admin Center**

1. Sign in to the [Entra admin center](https://entra.microsoft.com)
2. Go to **Identity** → **Groups** → **All groups**
3. Click **Group settings**
4. Set **Write back Microsoft 365 groups to on-premises** to **Yes**
5. Save

**Step 3 — Verify**

```powershell
# Check synced cloud groups in on-prem AD
Get-ADGroup -Filter * -SearchBase "OU=CloudGroups,DC=gntech,DC=me" -Properties * | Select Name, GroupCategory, GroupScope, Mail
```

Only groups with a **Microsoft 365** group type (not Security, not
Distribution) are written back. Their `groupType` in AD is
`SECURITY_GROUP | DISTRIBUTION_GROUP | UNIVERSAL_GROUP` to preserve
mail flow.

### Scenario 2: Cloud Security Groups (via Entra Cloud Sync)

Group Writeback v2 in Entra Connect Sync is **deprecated**. For
provisioning cloud security groups to on-premises AD, Microsoft
recommends **Microsoft Entra Cloud Sync**:

```powershell
# Install Cloud Sync agent
# Download from Entra admin center → Hybrid management → Cloud Sync
# Run on the Entra Connect server (or a separate member server)

# After installation, configure via:
# Entra admin center → Hybrid management → Cloud Sync → Group provisioning
```

Cloud Sync provisions cloud security groups as universal security
groups in AD. It can run alongside Entra Connect Sync — Entra Connect
handles user sync, while Cloud Sync handles group writeback.

> **Homelab note:** Group writeback (both v1 and Cloud Sync) requires
> real-world multicloud management to be useful. For a homelab without
> Exchange hybrid or Teams governance, skip group writeback unless you
> have a specific use case.

## Writeback Licensing Summary

| Feature | License Required |
|---|---|
| Password writeback | Entra ID P1 or P2 |
| Device writeback | Entra ID P1 or P2 |
| Group writeback v1 (M365 groups) | Entra ID P1 or P2 + Exchange hybrid |
| Group writeback Cloud Sync (security groups) | Entra ID P1 or P2 |

Without at least P1 licenses, the writeback options do not appear in
the Entra Connect wizard.

## Post-Installation Verification

### Check Writeback Status from PowerShell

```powershell
# Verify password writeback is enabled
Get-ADSyncAADCompanyFeature | Select PasswordWriteback

# Verify device writeback
Get-ADSyncAADCompanyFeature | Select DeviceWriteback

# Check device writeback forest
Get-ADSyncAADCompanyFeature | Select DeviceWritebackForest
```

Expected output:

```
PasswordWriteback        : Enabled
DeviceWriteback          : Enabled
DeviceWritebackForest    : gntech.me
```

### Monitor with Synchronization Service Manager

Open `C:\Program Files\Microsoft Azure AD Sync\UIShell\MiisClient.exe`:

1. **Operations** tab — filter by connector and look for **Export** runs
2. Each export shows the number of:
   - **adds** — new objects written back (first sync of a device/group)
   - **updates** — existing objects updated (password change sync)
   - **deletes** — objects removed

### Check Synchronization Statistics

```powershell
# View last sync results
Get-ADSyncExportStatistics | Format-Table Connector, ExportType, Status, ObjectType, ExportCount
```

## Troubleshooting Writeback

### Password Writeback Fails

| Symptom | Likely Cause | Fix |
|---|---|---|
| "Password does not meet complexity requirements" | On-prem AD policy is more restrictive than cloud | Align policies or check AD password filter |
| "Writeback timeout" | Network latency to Azure Service Bus | Check outbound connectivity from Entra Connect server |
| "Access denied" | AD Connector account lacks reset password permission | Grant via ADSI Edit or dsacls |

```powershell
# Force a writeback connectivity test
Test-ADSyncPasswordWriteback -AdConnectorName "gntech.me" -AADConnectorName "Entra ID"
```

### Device Writeback Fails

| Symptom | Likely Cause | Fix |
|---|---|---|
| Device not in AD after sync | Container not configured | Run Entra Connect wizard → Configure device options |
| Export error "no-writeback-container" | Device writeback OU missing | Create manually with the provided PowerShell script |
| Device shows in Entra but not on-prem | Device registered before writeback was enabled | Trigger a delta sync |

```powershell
# Export device writeback container configuration
$config = Get-ADSyncDeviceWritebackConfiguration
$config | Format-List
```

### Group Writeback Fails

| Symptom | Likely Cause | Fix |
|---|---|---|
| M365 group not in AD | Exchange hybrid not configured | Configure Exchange hybrid or check group writeback v1 is on |
| "Group writeback not enabled" | Sync rule not configured | Enable via Entra Connect Optional Features |
| Cloud Sync group not provisioned | Scope not configured | Check Cloud Sync group provisioning settings |

## When to Skip Writeback

- **No on-premises Exchange?** Skip group writeback v1
- **No Hybrid Entra Join planned?** Skip device writeback (comes in Post #4)
- **Small lab with same admin passwords?** Password writeback is optional —
  but SSPR is a good demo feature

If unsure, enable password writeback (it adds real value) and skip the
others until the next post in the series requires them.

## What We Built

| Feature | Status |
|---|---|
| Password writeback (SSPR) | Enabled — cloud password resets sync to on-prem AD |
| Device writeback | Enabled — registered devices appear in AD |
| Group writeback v1 (M365 groups) | Optional — skip unless Exchange hybrid exists |
| Group writeback Cloud Sync | Optional — skip unless cloud security groups need to exist on-prem |

## Next in the Series

With writeback configured, devices can be registered in both on-premises
AD and Entra ID simultaneously. The next post covers:

> **Post 4: Entra ID Hybrid Join + Device Registration**
>
> Configure automatic device registration via GPO, verify hybrid join
> status, and enable SSO to cloud resources from domain-joined devices.

## References

- [Password writeback concept](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-sspr-writeback)
- [Enable password writeback tutorial](https://learn.microsoft.com/en-us/entra/identity/authentication/tutorial-enable-sspr-writeback)
- [Device writeback](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-device-writeback)
- [Group writeback (v1) for M365 groups](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-group-writeback-enable)
- [Group writeback via Cloud Sync](https://learn.microsoft.com/en-us/entra/identity/hybrid/group-writeback-cloud-sync)
