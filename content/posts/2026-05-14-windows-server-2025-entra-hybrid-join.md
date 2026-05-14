---
title: "Windows Server 2025: Entra ID Hybrid Join + Device Registration"
description: "Configure Microsoft Entra hybrid join for Windows 11 and Windows Server 2025 devices: Entra Connect device options, SCP configuration via GPO, verification with dsregcmd, troubleshooting, and SSO to cloud resources."
date: 2026-05-14T14:15:00-04:00
tags:
  - windows-server
  - entra-id
  - hybrid-join
  - device-registration
  - conditional-access
  - sspr
keywords:
  - Microsoft Entra hybrid join configure
  - SCP configuration group policy
  - dsregcmd status verification
  - Windows Server 2025 device registration
  - hybrid joined device troubleshooting
  - SSO cloud resources on-prem domain join
summary: "Configure Microsoft Entra hybrid join for on-premises domain-joined devices: SCP via GPO or Entra Connect, automatic registration startup via Scheduled Task, verification with dsregcmd, and troubleshooting registration failures."
canonical: "https://blog.gntech.me/posts/windows-server-2025-entra-hybrid-join/"
cover:
  image: "https://upload.wikimedia.org/wikipedia/commons/2/26/Windows_Server_logo.svg"
  alt: "Windows Server logo"
  caption: "Windows Server logo — © Microsoft Corporation (public domain as simple geometric logo)"
---

Hybrid join connects your on-premises domain-joined devices to
Microsoft Entra ID without changing how they join the domain. A Windows
11 workstation or Windows Server 2025 member server that is already
domain-joined to `gntech.me` also registers with Entra ID as a device
identity. This enables:

- **Single sign-on (SSO)** to cloud resources (Microsoft 365, Azure,
  SaaS apps) from the domain-joined desktop — no separate credentials
- **Conditional Access** policies that require hybrid-joined or
  compliant devices
- **Windows Hello for Business** (covered in Post #5)
- **Enterprise State Roaming** — sync Windows settings across devices

This post builds on the device writeback configured in Post #3, which
is a prerequisite. Device writeback ensures that device registrations
in Entra ID create computer objects in on-premises AD.

> **Screenshots and images to add later:**
>
> - Entra Connect wizard — Configure device options page
> - Entra Connect — SCP configuration page
> - Group Policy Management Editor — SCP registry keys
> - dsregcmd /status output (successful hybrid join)
> - Device registration Scheduled Task in Task Scheduler
> - Verification script output (Azure registration connectivity)
> - Entra admin center — All devices showing hybrid joined devices

## How Hybrid Join Works

The registration flow:

```
Domain-joined device boots
    → Workstation service checks SCP in AD
    → SCP points to Entra ID tenant
    → Device Registration Scheduled Task triggers
    → Device authenticates to Entra ID (device certificate)
    → Registration completes → Device object in Entra ID
    → Device writeback → Computer object in on-prem AD
```

The key piece is the **Service Connection Point (SCP)**. The SCP is
stored in AD under the device registration configuration container. It
tells domain-joined devices which Entra ID tenant to register with.

Devices read the SCP automatically via the
`Workstation` service (`LANManWorkstation`) during startup and schedule
the device registration task.

## Prerequisites

From the previous posts in this series:

1. ✅ **Microsoft Entra Connect v2** installed and syncing (Post #2)
2. ✅ **Device writeback** enabled (Post #3)
3. **Entra ID P1 or P2** license (device registration requires it)
4. **Hybrid Identity Administrator** account
5. **Enterprise Administrator** credentials for AD
6. Windows 10/11 or Windows Server 2016/2019/2022/2025 devices
   (Server Core does NOT support device registration)
7. Domain controllers at minimum **Windows Server 2008 R2**

### Network Connectivity

Devices need outbound HTTPS (TCP 443) access from the internal network
to:

| URL | Purpose |
|---|---|
| `https://enterpriseregistration.windows.net` | Device registration |
| `https://login.microsoftonline.com` | Authentication |
| `https://device.login.microsoftonline.com` | Device auth |
| `https://autologon.microsoftazuread-sso.com` | Seamless SSO |

If you use TLS inspection (break-and-inspect), **exclude** the device
registration URLs from inspection. The device registration flow uses
client certificates for authentication, and TLS interception breaks
the certificate chain.

### Verify Device Writeback First

Confirm device writeback is working:

```powershell
# On the Entra Connect server
Get-ADSyncAADCompanyFeature | Select DeviceWriteback, DeviceWritebackForest
```

Expected:

```
DeviceWriteback        : Enabled
DeviceWritebackForest  : gntech.me
```

Also verify that a `RegisteredDevices` container exists in AD:

```powershell
Get-ADOrganizationalUnit -Filter "Name -eq 'RegisteredDevices'" -SearchBase "DC=gntech,DC=me" | Format-Table Name, DistinguishedName
```

If missing, run the Entra Connect wizard → **Configure device options**
→ provide Enterprise Admin credentials to create it.

## Method 1: SCP via Entra Connect (Easiest)

This is the recommended method for single-forest deployments. Entra
Connect writes the SCP to AD automatically.

### Step 1 — Run Entra Connect Device Configuration

1. On the Entra Connect server, run **Microsoft Entra Connect**
2. Click **Configure**
3. Select **Configure device options** → **Next**
4. On **Overview**, click **Next**
5. Enter **Hybrid Identity Administrator** credentials
6. On **Device options**, select **Configure hybrid join** → **Next**

### Step 2 — Configure SCP for Managed Domain

If you use **password hash sync** (which we set up in Post #2), the
wizard shows:

1. **SCP configuration for managed domain** page
2. Select the forest `gntech.me`
3. In **Device writeback target forest**, confirm `gntech.me` is selected
4. **Authentication Service** section:
   - Enter the UPN suffix for on-premises users (e.g., `gntech.me`)
   - Or select **User name** if your on-prem domain matches cloud UPN
5. Click **Next**

### Step 3 — Configure Device OU

1. On the **Device container** page:
   - **Device writeback forest:** `gntech.me`
   - **Device container for computers joined:** Browse to the OU where
     you want hybrid-joined computers to appear
   - If you ran device writeback already, the `RegisteredDevices`
     container is available
2. Click **Next** → **Configure**

The wizard writes the SCP to AD and triggers device writeback
configuration if not already done.

### Step 4 — Verify SCP

```powershell
# On a domain controller or Entra Connect server
# Find the SCP object in AD
Get-ADObject -Filter {objectClass -eq "serviceConnectionPoint"} -SearchBase "CN=Device Registration Configuration,CN=Services,CN=Configuration,DC=gntech,DC=me" -Properties * | Select Name, Keywords, ServiceBindingInformation
```

Expected: `Keywords` contains `azureADId:<tenant-id>` and
`ServiceBindingInformation` contains your tenant's registration URL.

## Method 2: SCP via GPO (Alternative)

If you cannot run the Entra Connect wizard (e.g., multi-forest,
restricted admin access), configure the SCP via registry policy.

### Step 1 — Build the GPO

1. Open **Group Policy Management Console** on a management server
2. Create a new GPO named **Entra Hybrid Join SCP**
3. Link it to the domain `gntech.me`

### Step 2 — Configure Registry Keys

Navigate the GPO editor to:

```
Computer Configuration → Preferences → Windows Settings → Registry
```

Create two registry entries:

| Action | Key Path | Value Name | Value Data |
|---|---|---|---|
| Update | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\CDJ\AAD` | `TenantId` | `your-tenant-id` |
| Update | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\CDJ\AAD` | `TenantName` | `gntech.me` |

Where `your-tenant-id` is the GUID of your Entra ID tenant:

```powershell
# Get your tenant ID
(Get-AzureADTenantDetail).ObjectId
# Or from Entra admin center → Identity → Overview → Tenant ID
```

### Step 3 — Configure Scheduled Task

The same GPO or a separate GPO deploys the registration task:

```
Computer Configuration → Preferences → Control Panel Settings → Scheduled Tasks
→ New → Scheduled Task (Windows 10 and later)
```

- **Name:** `CreateMicrosoftEntraJoinTask`
- **Security options:** Run as `NT AUTHORITY\SYSTEM`, run whether user
  is logged on or not
- **Trigger:** At system startup, repeat every 1 hour for 1 day
- **Action:** Start a program → `C:\Windows\System32\dsregcmd.exe`
  - Arguments: `/join`
- **Conditions:** Uncheck "Start the task only if the computer is on AC
  power"

Wait for GPO refresh (`gpupdate /force`) and the next scheduled task
execution.

## Verification

### On the Device

Run as administrator:

```cmd
dsregcmd /status
```

The output shows:

```
+----------------------------------------------------------------------+
| Device State                                                         |
+----------------------------------------------------------------------+

    AzureAdJoined: YES
 EnterpriseJoined: NO
         DeviceId: <guid>
       Thumbprint: <cert-thumbprint>
   KeyContainerId: <guid>
      KeyProvider: Microsoft Platform Crypto Provider
     TpmProtected: YES
     KeySignTest: : PASSED
              Idp: login.microsoftonline.com
         TenantId: <your-tenant-id>
       TenantName: gntech.me
      AuthCodeUrl: https://login.microsoftonline.com/<tenant>/oauth2/authorize
   AccessTokenUrl: https://login.microsoftonline.com/<tenant>/oauth2/token

+----------------------------------------------------------------------+
| Domain Name Services                                                 |
+----------------------------------------------------------------------+
...
+----------------------------------------------------------------------+
| SSO Data                                                             |
+----------------------------------------------------------------------+
        AzureAdPrt: YES
...
+----------------------------------------------------------------------+
| Ngc Data (a.k.a. Windows Hello for Business)                        |
+----------------------------------------------------------------------+
   ngcState: NOT_SET
...
```

Key indicators of success:

| Field | Expected Value |
|---|---|
| `AzureAdJoined` | `YES` |
| `KeySignTest` | `PASSED` (requires elevated) |
| `AzureAdPrt` | `YES` (Primary Refresh Token obtained) |

If `AzureAdJoined` is `NO`, the device has not completed registration.

### Connectivity Test

Download and run the Microsoft connectivity test script:

```powershell
# Download the test script
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/azure-samples/TestDeviceRegConnectivity/master/TestDeviceRegConnectivity.ps1" -OutFile "$env:TEMP\TestDeviceRegConnectivity.ps1"

# Run (elevated)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\$env:TEMP\TestDeviceRegConnectivity.ps1
```

The script tests each required URL and reports pass/fail.

### In Entra Admin Center

1. Sign in to the [Entra admin center](https://entra.microsoft.com)
2. Go to **Identity** → **Devices** → **All devices**
3. The device should appear with:
   - **Join type:** `Hybrid Azure AD joined` (the legacy label may
     still show this)
   - **Registered:** date/time of registration
   - **Owner:** user who was logged in during registration

### On-Premises AD

The device should also appear in the device writeback container:

```powershell
Get-ADComputer -Filter * -SearchBase "CN=RegisteredDevices,DC=gntech,DC=me" -Properties * | Select Name, LastLogonDate, OperatingSystem
```

## The Registration Process in Detail

When a domain-joined device boots:

1. **Workstation Service** (`LANManWorkstation`) queries AD for SCPs in
   `CN=Device Registration Configuration,CN=Services,CN=Configuration,<domain>`
2. If an SCP with keyword `azureADId:<tenant-id>` is found, the service
   schedules the **CreateMicrosoftEntraJoinTask** (Scheduled Task)
3. The task runs `dsregcmd /join` in system context
4. The device authenticates to `enterpriseregistration.windows.net`
   using its domain computer account credentials
5. Entra ID issues a device identity and certificate
6. The device stores the certificate in the TPM (if available)
7. Entra Connect syncs the device registration to on-prem AD via
   device writeback

This process is automatic and transparent to users. No reboot is
required after SCP configuration — the task triggers within an hour.

### Trigger Immediately for Testing

```cmd
# On the target device, as administrator
dsregcmd /join
```

Refresh registration status:

```cmd
dsregcmd /status
```

If the device is already registered, `dsregcmd /join` is a no-op.

### Force Re-registration

```cmd
# Leave the join (will remove from Entra ID)
dsregcmd /leave

# Re-join
dsregcmd /join

# Verify
dsregcmd /status
```

## Windows Server 2025 as Hybrid Joined

Windows Server 2025 member servers (not domain controllers) support
hybrid join. This is useful for:

- **Conditional Access on server-management tools** — require hybrid
  join to access Entra ID protected APIs
- **Windows Hello for Business on server** — used for service accounts
  or admin access
- **Managed servers** that need SSO to Microsoft 365 or Azure

> **Important:** Server Core does NOT support device registration.
> Only Windows Server with Desktop Experience (GUI) can hybrid join.

To check if a Server 2025 device supports registration:

```powershell
# Check Windows edition
(Get-WmiObject Win32_OperatingSystem).Caption
# "Microsoft Windows Server 2025 Standard" → Desktop Experience hybrid join supported

# Check Server Core
# "Microsoft Windows Server 2025 Standard" with ServerCoreEnabled=1 → NOT supported
```

## SSO with Hybrid Joined Devices

Once hybrid joined, users get SSO to:

- **Microsoft 365** (Outlook, Teams, SharePoint, OneDrive for Business)
  — no password prompts on domain-joined machines
- **Azure Portal** — via seamless SSO
- **Entra ID integrated apps** — SAML/OIDC apps federated with Entra ID
- **On-premises resources** — Kerberos still works for on-prem apps

The **Primary Refresh Token (PRT)** is obtained during device
registration. You can verify:

```cmd
dsregcmd /status
# Look for:
#   AzureAdPrt: YES
```

If `AzureAdPrt` is `NO`, the user may need to sign out and sign back
in, or the device needs a `gpupdate /force`.

## Troubleshooting

### dsregcmd /status Shows AzureAdJoined: NO

| Symptom | Likely Cause | Fix |
|---|---|---|
| No SCP found | AD SCP not configured | Run Entra Connect device config or deploy GPO |
| SCP found but join fails | Network blocked | Test with `TestDeviceRegConnectivity.ps1` |
| Registration timeout | TLS inspection breaking cert auth | Exclude device registration URLs from break-and-inspect |
| "Access denied" | Device computer account lacks auth | Ensure device OU is synced by Entra Connect |

### dsregcmd /status Shows KeySignTest: FAILED

Run the command elevated (as Administrator). If it still fails:

```cmd
# Check TPM status
tpm.msc
```

### Device Shows "Pending" in Entra Admin Center

A **Pending** state means the device registration started but did not
complete. Common causes:

- Network connectivity issues
- TLS inspection blocking certificate authentication
- Device clock skew (NTP not synced)

```cmd
# Check time sync
w32tm /query /status

# Force sync
w32tm /resync
```

### Device Not Appearing in Entra Admin Center

1. Verify **hybrid join completed** on the device
2. Verify **device writeback** is enabled in Entra Connect
3. Run a **delta sync** on the Entra Connect server
4. Check **Synchronization Service Manager** → **Operations** for
   device export errors

### Dual State (Azure AD Registered + Hybrid Joined)

If a device was previously Azure AD registered (work or school account
added manually) and is now hybrid joined, it may appear twice in Entra
admin center. The hybrid join entry is authoritative. The Azure AD
registered entry can be removed under device settings.

## What We Built

| Component | Status |
|---|---|
| SCP in AD | Configured via Entra Connect or GPO |
| Device writeback | Enabled (Post #3) |
| Hybrid join registration | Automatic via Scheduled Task |
| SSO to cloud resources | Enabled via PRT |
| Verification | dsregcmd /status + Entra admin center |

## Next in the Series

With devices hybrid joined and SSO working, the next post covers
passwordless authentication:

> **Post 5: Windows Hello for Business — Hybrid Key Trust**
>
> Deploy WHfB in hybrid key trust mode: GPO configuration, certificate
> registration, PIN/policy setup, and enrollment verification.

## References

- [Configure Microsoft Entra hybrid join](https://learn.microsoft.com/en-us/entra/identity/devices/how-to-hybrid-join)
- [Plan your hybrid join deployment](https://learn.microsoft.com/en-us/entra/identity/devices/hybrid-join-plan)
- [Troubleshoot hybrid joined devices](https://learn.microsoft.com/en-us/entra/identity/devices/troubleshoot-hybrid-join-windows-current)
- [Device registration connectivity test script](https://github.com/azure-samples/TestDeviceRegConnectivity)
- [How SSO to on-premises resources works on Entra joined devices](https://learn.microsoft.com/en-us/entra/identity/devices/device-sso-to-on-premises-resources)
- [dsregcmd command reference](https://learn.microsoft.com/en-us/entra/identity/devices/troubleshoot-device-dsregcmd)
