---
title: "Windows Server 2025: Windows Hello for Business — Hybrid Key Trust"
description: "Deploy Windows Hello for Business in hybrid key trust mode: PKI setup (AD CS), domain controller certificates, Entra Connect key sync, GPO configuration, PIN policy, enrollment on hybrid joined devices, and troubleshooting."
date: 2026-05-14T14:30:00-04:00
tags:
  - windows-server
  - windows-hello
  - passwordless
  - hybrid-identity
  - ad-cs
  - pki
keywords:
  - Windows Hello for Business hybrid key trust
  - WHfB deployment guide
  - AD CS certs for Windows Hello
  - domain controller certificates Kerberos authentication
  - PIN policy GPO Windows Hello
  - msDS-KeyCredentialLink attribute
  - passwordless authentication hybrid
summary: "Deploy Windows Hello for Business in hybrid key trust mode: enterprise PKI setup, DC certificates, GPO policy, user enrollment, PIN configuration, and verification."
canonical: "https://blog.gntech.me/posts/windows-server-2025-windows-hello-hybrid-key-trust/"
cover:
  image: "https://upload.wikimedia.org/wikipedia/commons/2/26/Windows_Server_logo.svg"
  alt: "Windows Server logo"
  caption: "Windows Server logo — © Microsoft Corporation (public domain as simple geometric logo)"
---

Windows Hello for Business (WHfB) replaces passwords with strong
two-factor authentication tied to the device. Users sign in with a PIN,
biometric (fingerprint, face), or FIDO2 security key instead of a
password.

In a hybrid deployment (on-premises AD + Microsoft Entra ID), WHfB
authenticates users to both on-premises and cloud resources. **Key
trust** is one of three trust models:

| Trust Model | PKI Required | Key Storage | Best For |
|---|---|---|---|
| **Key trust** | ✅ Yes (DC certs) | Device TPM | Hybrid environments with existing PKI |
| **Cloud Kerberos trust** | ❌ No | Device TPM | ⭐ **Recommended** — simpler, no PKI needed |
| **Certificate trust** | ✅ Yes (user + DC certs) | Device TPM | Legacy apps requiring explicit certs |

> **Microsoft recommends cloud Kerberos trust** over key trust. However,
> key trust is still widely deployed in existing PKI environments and
> is the focus of this post. If you are starting fresh in 2026,
> evaluate cloud Kerberos trust first.

This post assumes the infrastructure from the previous four posts:

1. ✅ Entra Connect sync (Post #2)
2. ✅ Device writeback (Post #3)
3. ✅ Hybrid join (Post #4)
4. ✅ AD users synced to Entra ID

> **Screenshots and images to add later:**
>
> - AD CS installation via Server Manager
> - CA configuration — enterprise root CA
> - Domain Controller certificate template configuration
> - WSUS DC-autoenrollment GPO
> - WHfB policy in GPMC — Use Windows Hello for Business
> - PIN complexity policy settings
> - dsregcmd /status showing Ngc data
> - Entra ID — user sign-in logs showing WHfB authentication

## How WHfB Key Trust Works

```
User signs in with PIN/biometric on hybrid-joined device
    → Windows creates asymmetric key pair in TPM
    → Public key published to Entra ID (via sync)
    → msDS-KeyCredentialLink attribute written to user in AD
    → KDC on domain controller validates user's key against attribute
    → Kerberos TGT issued using WHfB key (not password)
    → User authenticated to on-prem + cloud resources
```

The domain controller needs a **Kerberos Authentication certificate** so
the device trusts the KDC. The enterprise CA issues this certificate.
Without it, WHfB enrollment fails with cryptic errors.

## Prerequisites

### Infrastructure

| Component | Requirement |
|---|---|
| Windows Server 2025 PKI server | AD CS installed, enterprise root CA |
| Domain controller certificate | Kerberos Authentication cert on every DC |
| Entra Connect | v2, syncing, device writeback enabled |
| Hybrid join | Devices hybrid joined (Post #4) |
| Entra ID P1/P2 license | Required for WHfB in hybrid key trust |
| Windows 11 / Windows 10 | Devices must support TPM 2.0 |
| Windows Server 2025 | Optional — WHfB on server (Desktop Experience only) |

### Network

Devices need line of sight to:
- Domain controller (Kerberos authentication)
- Enterprise CA (certificate enrollment)
- `enterpriseregistration.windows.net` (device registration)

### Users

- Each user must have a synced on-prem AD account
- Users must be licensed for Entra ID (P1/P2)
- Users must register for device registration:
  ```
  Entra admin center → Identity → Devices → Device settings
  → "Users may register devices with Microsoft Entra ID" → All
  ```

## Step 1 — Deploy Active Directory Certificate Services

If you do not have an enterprise PKI, spin up a CA on a Windows Server
2025 member server (not a domain controller).

### Install AD CS

```powershell
# On the PKI server (e.g., CA01.gntech.me)
# Run as Enterprise Admin

# Install the AD CS role with management tools
Add-WindowsFeature Adcs-Cert-Authority -IncludeManagementTools

# Configure as an Enterprise Root CA
Install-AdcsCertificationAuthority -CACommonName "GNTECH Root CA" -CAType EnterpriseRootCa -CryptoProviderName "RSA#Microsoft Software Key Storage Provider" -KeyLength 4096 -ValidityPeriod Years -ValidityPeriodUnits 10 -HashAlgorithmName SHA256
```

The wizard alternative: **Server Manager** → **Manage** → **Add Roles
and Features** → Select **Active Directory Certificate Services** →
Check **Certification Authority** → Install → Configure → **Enterprise
CA** → **Root CA** → Create new private key → Default settings →
Complete.

### Configure Certificate Templates

Domain controllers need a **Kerberos Authentication** certificate. The
default **Domain Controller** template works, but for clarity, create a
dedicated template:

1. Open **Certification Authority** snap-in on the CA server
2. Right-click **Certificate Templates** → **Manage**
3. Right-click **Kerberos Authentication** template → **Duplicate
   Template**
4. On **Compatibility** tab:
   - Certification Authority: **Windows Server 2016**
   - Certificate recipient: **Windows Server 2016**
5. On **General** tab:
   - Template display name: `GNTECH Domain Controller Auth`
   - Validity period: **5 years** (default)
6. On **Request Handling**:
   - Purpose: **Signature and encryption**
   - Check **Allow private key to be exported**
7. On **Cryptography** tab:
   - Provider Category: **Key Storage Provider**
   - Algorithm: **RSA**, minimum key size **2048**
   - Request hash: **SHA256**
8. On **Extensions** tab:
   - Verify **Application Policies** includes **Kerberos Authentication**
9. On **Security** tab:
   - Add **Domain Controllers** group → **Enroll** permission
   - Remove other groups from Enroll except Domain Controllers
10. Click **OK**

Now publish the template:

1. In **Certification Authority** snap-in, right-click **Certificate
   Templates** → **New** → **Certificate Template to Issue**
2. Select **GNTECH Domain Controller Auth** → **OK**

### Issue DC Certificates

Domain controllers auto-enroll certificates when they find an enterprise
CA. To trigger immediately:

```powershell
# On each domain controller, run as Domain Admin
certreq -autoenroll

# Verify certificate issued
Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.EnhancedKeyUsageList -match "Kerberos Authentication" } | Format-Table Subject, NotAfter, Thumbprint
```

If no certificate appears, check:

1. Does the DC have network access to the CA?
2. Is the **Domain Controllers** group allowed to enroll the template?
3. Run `gpupdate /force` and `certreq -autoenroll` again.

For automated enrollment via GPO for all DCs:

```
Group Policy Management → Default Domain Controllers Policy → Edit
→ Computer Configuration → Policies → Windows Settings → Security Settings
→ Public Key Policies → Certificate Services Client - Auto-Enrollment
→ Configuration Model: Enabled
→ Check: Renew expired certificates, update pending certificates,
         remove revoked certificates
→ Check: Update certificates that use certificate templates
```

### Verify DC Certificate

```powershell
# Verify the DC cert is trusted (issued by the root CA installed)
# Check that the cert's Intended Purposes include "Kerberos Authentication"
certlm.msc
# Personal → Certificates → double-click the DC cert → Details → Enhanced Key Usage
```

Also verify **LDAP over SSL** works (DC cert enables this):

```powershell
# Quick LDAPS test
Test-NetConnection -ComputerName DC01.gntech.me -Port 636
# Should show TcpTestSucceeded: True
```

## Step 2 — Configure Entra Connect Key Sync

WHfB key trust requires the user's public key (from their TPM) to be
synced to Entra ID. Entra Connect v2 does this automatically when the
correct attribute (`msDS-KeyCredentialLink`) is in the sync scope.

### Verify the Attribute is Syncing

1. On the Entra Connect server, open **Synchronization Rules Editor**
   (Start menu → Microsoft Entra Connect → Synchronization Rules Editor)
2. Look for the rule **Out to AAD - User Join** (or similar)
3. Verify that `msDS-KeyCredentialLink` is mapped to `keyCredentials`
   in the transformation

If not present, edit the rule to add:

```
FlowType: Direct
Source Attribute: msDS-KeyCredentialLink
Target Attribute: keyCredentials
```

Or run the Entra Connect wizard → **Customize synchronization options**
→ **Optional Features** → ensure **Directory extension attribute sync**
is enabled.

### Force a Full Sync After Config Changes

```powershell
Start-ADSyncSyncCycle -PolicyType Initial
```

## Step 3 — Deploy WHfB Policy (GPO)

### Enable Windows Hello for Business

1. Open **Group Policy Management Console**
2. Create a new GPO: **Windows Hello for Business — Hybrid**
3. Link it to the domain `gntech.me` (or to a specific OU with
   WHfB-eligible users and computers)

### Configure Policy Settings

Navigate to:

```
Computer Configuration → Policies → Administrative Templates
→ Windows Components → Windows Hello for Business
```

Set these:

**Required:**

| Policy | Setting |
|---|---|
| **Use Windows Hello for Business** | **Enabled** |

**Recommended (Optional):**

| Policy | Setting |
|---|---|
| **Use a hardware security device** | **Enabled** (requires TPM 2.0) |
| **Minimum PIN length** | Enabled → **6** |
| **Maximum PIN length** | Enabled → **127** |
| **Require lowercase letters in PIN** | Enabled → **Allowed** |
| **Require uppercase letters in PIN** | Enabled → **Allowed** |
| **Require special characters in PIN** | Disabled or **Allowed** |
| **Expiration** | Enabled → **90** days |
| **History** | Enabled → **10** |

For a homelab, less restrictive PIN is fine:

| Policy | Setting |
|---|---|
| **Minimum PIN length** | Enabled → **4** |
| **Require lowercase letters in PIN** | Disabled |
| **Require uppercase letters in PIN** | Disabled |
| **Require special characters in PIN** | Disabled |

### Configure Smart Card (Applies to WHfB)

Additionally, groups can be excluded from WHfB:

```
Computer Configuration → Policies → Administrative Templates
→ Windows Components → Windows Hello for Business
→ "Disable Windows Hello for Business on devices where the
   target machine is Azure AD joined or has already registered
   for PIN reset or Hello"
```

Leave this **Not Configured** (default) in standard deployments.

### Deploy the GPO

```powershell
gpupdate /force
```

Wait for replication, or trigger remotely:

```powershell
Invoke-GPUpdate -Computer "WS01" -RandomDelayInMinutes 0
```

## Step 4 — Enroll in Windows Hello for Business

### User-Initiated Enrollment

After GPO deployment, users set up WHfB from their hybrid-joined device:

1. **Settings** → **Accounts** → **Sign-in options**
2. Under **Windows Hello**, click **Set up** for PIN, Fingerprint, or
   Face
3. **Windows Security** opens → **Create a PIN**
4. Enter current password to verify identity
5. Enter new PIN (confirm)
6. Click **OK**

The device generates an asymmetric key pair in the TPM. The public key
is published to Entra ID and synced back to the user's AD object
(`msDS-KeyCredentialLink` attribute).

### Verify Enrollment

```cmd
dsregcmd /status
```

Look for:

```
+----------------------------------------------------------------------+
| Ngc Data (a.k.a. Windows Hello for Business)                        |
+----------------------------------------------------------------------+
   ngcState: YES
NgcContainerId: <guid>
  IsReady: YES
   IsEnabled: YES
  IsPreKeyRecoveryEnabled: False
   DevicePKeyId: <guid>
    SignId: <guid>
```

Also check the AD attribute:

```powershell
# On a domain controller, verify the user's key credential link
Get-ADUser jsmith -Properties msDS-KeyCredentialLink | Select-Object -ExpandProperty msDS-KeyCredentialLink
```

If empty, the public key has not synced from Entra ID. Check:
- Entra Connect attribute sync for `msDS-KeyCredentialLink` ↔ `keyCredentials`
- A full sync cycle
- Sync errors in Synchronization Service Manager

### Entra Admin Center Verification

1. Sign in to the [Entra admin center](https://entra.microsoft.com)
2. Go to **Identity** → **Users** → **All users** → select user →
   **Sign-in logs**
3. Look for authentication events showing:
   - **Windows Hello for Business** in **Authentication requirement**
   - **Primary refresh token** as token type

## Step 5 — Test Passwordless Sign-In

### Local Sign-In

1. Lock the device (`Win + L`)
2. On the lock screen, use the PIN (or biometric) instead of password
3. Verify you can access:
   - On-premises network shares (Kerberos)
   - Microsoft 365 apps (Outlook, Teams) — SSO via PRT
   - Entra admin center (browser — promptless)

### Remote (RDP) Consideration

WHfB does **not** work for RDP logins by default. To use WHfB with RDP:

1. Enable certificate authentication for RDP:
   ```
   GPO → Computer Configuration → Administrative Templates
   → Windows Components → Remote Desktop Services → Remote Desktop Session Host
   → Security
   → "Require use of specific security layer for remote (RDP) connections"
   → Set to: Negotiate
   → "Require user authentication for remote connections by using Network Level Authentication"
   → Enabled
   ```
2. The user must have a WHfB certificate (not just key pair — requires
   certificate trust model)
3. Alternatively, authenticate with PIN on the console, then RDP using
   password or smart card

For a homelab, WHfB is primarily a **console sign-in** feature.

## Single Sign-On

With hybrid key trust configured, users get:

| Resource | How It Works |
|---|---|
| On-prem AD domain resources | Kerberos ticket issued via WHfB key (no password required) |
| Microsoft 365 (Outlook, Teams, SharePoint) | PRT obtained via WHfB enrollment |
| Azure Portal | SSO via PRT through seamless SSO |
| Entra ID integrated SaaS apps | SAML/OIDC tokens issued via PRT |
| On-premises web apps using ADFS | Device-based Conditional Access via device writeback |

The Primary Refresh Token (PRT) is the key. WHfB enrollment generates
a PRT that is cached on the device and renewed automatically.

## Troubleshooting

### Enrollment Fails — "Something went wrong"

| Symptom | Likely Cause | Fix |
|---|---|---|
| "Key registration failed" | DC certificate missing or untrusted | Install Kerberos Auth cert on DC |
| "Windows Hello isn't available" | TPM not available | Check `tpm.msc` — TPM 2.0 required |
| "PIN setup failed" | GPO not applied | `rsop.msc` or `gpresult /h` to verify |

### DC Not Trusted

```cmd
# Check if domain controller has a valid Kerberos cert on the device
certutil -viewstore -enterprise CA
certutil -DCInfo

# Verify DC certificate chain
CertReq -enroll -machine -policyserver "CA01.gntech.me\GNTECH Root CA" -Policy "GNTECH Domain Controller Auth"
```

### WHfB Not Available After GPO Deploy

```cmd
# Force GP update
gpupdate /force

# Check registry keys applied
reg query HKLM\SOFTWARE\Policies\Microsoft\PassportForWork

# Check the specific policy value
reg query HKLM\SOFTWARE\Policies\Microsoft\PassportForWork /v Enabled
```

Expected: `Enabled` REG_DWORD `0x1`

### Key Sync Not Working

```powershell
# Check user's msDS-KeyCredentialLink in AD
Get-ADUser jsmith -Properties msDS-KeyCredentialLink, msDS-KeyCredentialLink2

# If empty, check Entra Connect sync rules
# The attribute must be mapped from AD to Entra ID
```

### User Cannot Sign In After Enrollment

```cmd
# Check user token state
whoami /upn

# Verify Kerberos ticket
klist

# Force re-authentication
klist purge
```

If the user can't authenticate, they can still use their password as
fallback. WHfB doesn't disable password sign-in unless explicitly
configured via GPO (`EnableWindowsHelloForBusiness` + PIN-only
policies).

## What We Built

| Component | Detail |
|---|---|
| Enterprise PKI (AD CS) | Root CA on Windows Server 2025 |
| DC certificates | Kerberos Authentication cert issued to each DC |
| WHfB key sync | `msDS-KeyCredentialLink` synced via Entra Connect |
| WHfB policy | GPO: PIN complexity, TPM requirement |
| User enrollment | PIN set up on hybrid-joined device |
| SSO | Passwordless sign-in to on-prem + cloud resources |

## Next in the Series

> **Post 6: Self-Service Password Reset (SSPR)**
>
> Enable SSPR for users: registration, authentication methods, writeback
> testing, and Conditional Access integration.

## References

- [WHfB hybrid key trust deployment guide](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/deploy/hybrid-key-trust)
- [Plan WHfB deployment](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/deploy/)
- [Configure WHfB enrollment (hybrid key trust)](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/deploy/hybrid-key-trust-enroll)
- [WHfB policy settings](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/policy-settings)
- [AD CS deployment guide](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2012-R2-and-2012/hh831574%28v=ws.11%29)
- [KDC certificates for Windows Hello](https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/hello-key-trust-validate-pki)
