---
title: "Windows LAPS — Delegate Password Access by OU"
description: "Delegate Windows LAPS access to one Active Directory OU using separate read and rotation groups, encrypted-password policy, and non-admin validation."
date: 2026-11-01T00:00:00-04:00
draft: false
tags: [windows-server, active-directory, laps, powershell, security, homelab]
keywords: [Windows LAPS OU delegation, Set-LapsADReadPasswordPermission, ADPasswordEncryptionPrincipal]
summary: "Scope LAPS support access to one OU, keep read and rotation roles separate, and verify both successful decryption and denial outside the intended scope."
cover:
  image: "/images/posts/windows-laps-ou/cover.png"
  alt: "Illustration of servers in separate compartments with a key and shield highlighting one compartment."
  caption: "AI-generated editorial illustration; not a screenshot or an exact permission diagram."
  relative: false
---

A help desk operator may need the local administrator password for a file server without receiving access to every workstation and server in the domain. Windows LAPS can support that boundary, but an OU permission alone does not settle the whole question.

For encrypted passwords, the operator needs permission to read the AD data **and** authorization to decrypt it. This guide sets up a small pilot and checks both gates.

## Verification status

| Area | Status |
|---|---|
| Scope | Windows LAPS with passwords backed up to Active Directory; member servers in one OU. Legacy Microsoft LAPS, Entra-only backup, and domain-controller DSRM are outside this walkthrough. |
| Source review | Microsoft documentation reviewed on November 1, 2026; references appear beside the relevant steps. |
| Runtime | These commands were not executed against a live AD domain during article preparation. |
| Acceptance | Test an intended server and an out-of-scope server with a real, unprivileged operator account before expanding the rollout. |

## 1. Define the pilot and prerequisites

Start with a dedicated pilot OU containing a disposable or recoverable member server. Have a second LAPS-managed test computer in a sibling OU for the denial test. Do not start on the domain root or Domain Controllers OU.

You need an updated Windows management host with the **ActiveDirectory** and **LAPS** PowerShell modules, permission to modify the target OU's delegation, and authority to edit its LAPS GPO. Use Windows PowerShell for the examples.

The forest must already have the Windows LAPS schema extension. Microsoft documents `Update-LapsADSchema` as a one-time forest operation; plan it separately if it has not been completed. Password encryption requires a domain functional level of **Windows Server 2016 or later**. See [Microsoft's AD deployment prerequisites](https://learn.microsoft.com/en-us/windows-server/identity/laps/laps-scenarios-windows-server-active-directory).

This walkthrough assumes LAPS already manages a valid local account on the pilot endpoint. Account creation and automatic account management have their own OS requirements.

Run these discovery commands from the administrative management session:

```powershell
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory
Import-Module LAPS

$domain = Get-ADDomain
$domain | Select-Object DNSRoot, NetBIOSName, DomainMode
Get-Command -Module LAPS
```

Set the **actual OU distinguished name**, then inspect the exact objects before changing permissions. The example domain and computer names below are placeholders.

```powershell
$ou = 'OU=LAPSPilot,OU=Servers,DC=ad,DC=example,DC=com'
$pilot = 'FILE-PILOT01'

Get-ADOrganizationalUnit -Identity $ou |
    Select-Object Name, DistinguishedName

Get-ADComputer -Identity $pilot |
    Select-Object Name, DistinguishedName

Get-ADComputer -SearchBase $ou -SearchScope Subtree -Filter * |
    Select-Object Name, DistinguishedName
```

Confirm that every listed computer belongs in this delegation scope. Descendant OUs may inherit the grants too; an OU boundary is only useful when its contents and inheritance match your intent.

## 2. Keep the roles separate

Use reviewed security groups that already exist in your directory. Create them through your normal group-management process if necessary.

| Principal | Intended capability |
|---|---|
| Each managed computer's SELF identity | Write its own LAPS data. |
| `ServerLAPSReaders` | Read LAPS data in the pilot OU; also become the policy's authorized decryptor. |
| `ServerLAPSResetters` | Change the expiration timestamp in the pilot OU. This does not itself reveal a password or immediately rotate an offline endpoint. |

A support account can belong to both groups when its job requires both capabilities. Review group owners and nested memberships; do not add broad groups such as Domain Users.

Resolve the groups and record their identities:

```powershell
$readerGroup = Get-ADGroup -Identity 'ServerLAPSReaders'
$resetGroup = Get-ADGroup -Identity 'ServerLAPSResetters'

$readerGroup, $resetGroup |
    Select-Object Name, GroupCategory, GroupScope, SID

$readers = "$($domain.NetBIOSName)\$($readerGroup.SamAccountName)"
$resetters = "$($domain.NetBIOSName)\$($resetGroup.SamAccountName)"
```

Before applying changes, export the OU's current ACL and group membership to a restricted administrative change folder. For example, after setting `$changeFolder` to that existing, access-controlled folder:

```powershell
$changeFolder = Read-Host 'Existing restricted change-folder path'
if (-not (Test-Path -LiteralPath $changeFolder -PathType Container)) {
    throw 'Prepare a restricted change folder first.'
}

$aclPath = Join-Path $changeFolder 'laps-pilot-ou-before.xml'
if (Test-Path -LiteralPath $aclPath) {
    throw 'Use a new change folder; an ACL snapshot already exists.'
}

Get-Acl -LiteralPath "AD:\$ou" | Export-Clixml -LiteralPath $aclPath
Get-ADGroupMember -Identity $readerGroup -Recursive |
    Export-Clixml (Join-Path $changeFolder 'readers-before.xml')
Get-ADGroupMember -Identity $resetGroup -Recursive |
    Export-Clixml (Join-Path $changeFolder 'resetters-before.xml')
```

These are private change records, not blog attachments. They do not replace an AD recovery plan or a GPO backup.

## 3. Grant permissions on the selected OU

First inspect the existing delegation:

```powershell
Find-LapsADExtendedRights -Identity $ou
```

Investigate unexpected principals before proceeding. This report helps identify potentially broad rights; it is not a complete effective-access test. Also inspect inherited permissions and relevant computer-object ACLs. See [Find-LapsADExtendedRights](https://learn.microsoft.com/en-us/powershell/module/laps/find-lapsadextendedrights).

Apply the three separate grants from your authorized administrative session:

```powershell
Set-LapsADComputerSelfPermission -Identity $ou
Set-LapsADReadPasswordPermission -Identity $ou -AllowedPrincipals $readers
Set-LapsADResetPasswordPermission -Identity $ou -AllowedPrincipals $resetters
```

The [SELF permission](https://learn.microsoft.com/en-us/powershell/module/laps/set-lapsadcomputerselfpermission) lets a managed computer update its own LAPS attributes. The [read grant](https://learn.microsoft.com/en-us/powershell/module/laps/set-lapsadreadpasswordpermission) authorizes reading the relevant attributes. The [reset grant](https://learn.microsoft.com/en-us/powershell/module/laps/set-lapsadresetpasswordpermission) authorizes changing their expiration timestamp.

Run the extended-rights report again and retain the before/after review with the change record. Check child OUs and objects with inheritance disabled rather than assuming the OU grant reached every computer.

## 4. Configure the encryption gate

In Group Policy Management, back up the relevant GPO before editing it. Use a GPO scoped to the pilot computers and verify its links, security filtering, and resultant policy.

Under **Computer Configuration → Policies → Administrative Templates → System → LAPS**, configure:

| Setting | Pilot value |
|---|---|
| Configure password backup directory | Active Directory |
| Enable password encryption | Enabled |
| Configure authorized password decryptors | The fully qualified reader group, such as `EXAMPLE\ServerLAPSReaders` |

The decryptor setting corresponds to `ADPasswordEncryptionPrincipal`. It takes one principal; a security group provides controlled membership. If the setting is absent, the default decryptor is Domain Admins. See [LAPS policy settings](https://learn.microsoft.com/en-us/windows-server/identity/laps/laps-management-policy-settings).

Avoid sharing that decryptor group with unrelated OU policies when you want separate support boundaries. Keep a documented, tested recovery path when changing who can decrypt new passwords.

Changing policy does **not** re-encrypt an already stored password. Older ciphertext and password history retain their original encryption authorization. See [Windows LAPS password concepts](https://learn.microsoft.com/en-us/windows-server/identity/laps/laps-concepts-overview).

On the **pilot endpoint itself**, in an elevated administrative shell, apply policy, review the resultant settings, then rotate the pilot password:

```powershell
gpupdate /target:computer /force
gpresult /scope computer /r
Invoke-LapsPolicyProcessing

# After confirming the intended LAPS policy applies:
Reset-LapsPassword

Get-WinEvent -LogName 'Microsoft-Windows-LAPS/Operational' -MaxEvents 20 |
    Select-Object TimeCreated, Id, LevelDisplayName, Message
```

`Reset-LapsPassword` runs locally on the managed endpoint; the delegated AD expiration right does not grant remote execution or local administrator access. Review [the reset cmdlet](https://learn.microsoft.com/en-us/powershell/module/laps/reset-lapspassword) before scheduling rotation around dependent maintenance work.

## 5. Validate with the operator account

Add only the approved pilot operator to the required groups through your normal approval process. Start a fresh sign-in after membership changes. Test from that operator's own session, without Domain Admin membership or alternate administrator credentials.

Query metadata without printing the password:

```powershell
Import-Module LAPS

Get-LapsADPassword -Identity 'FILE-PILOT01' |
    Select-Object ComputerName, Source, PasswordUpdateTime,
        ExpirationTimestamp, DecryptionStatus, AuthorizedDecryptor
```

For this encrypted pilot, require `Source = EncryptedPassword`, `DecryptionStatus = Success`, the intended decryptor, and a recent update time. By default, the password is returned as a SecureString; the explicit projection above omits it. Do not add `-AsPlainText` to shared transcripts or screenshots. See [Get-LapsADPassword](https://learn.microsoft.com/en-us/powershell/module/laps/get-lapsadpassword).

Repeat the same metadata query for the known LAPS-managed computer in the sibling OU. An empty result alone is inconclusive: first establish that this comparison computer has valid LAPS data using a separately authorized administrator.

| Test | Expected result |
|---|---|
| Reader on pilot server | Successful decryption for the intended encrypted password. |
| Same reader on sibling-OU server | No usable password; investigate any unexpected successful decryption. |
| Reader-only operator changes expiration | Denied unless another group or inherited grant supplies that right. |
| Approved reset operator on pilot | Can change expiration; rotation still needs endpoint policy processing. |

For the last test, use a disposable pilot and the reset operator's session:

```powershell
Set-LapsADPasswordExpirationTime -Identity 'FILE-PILOT01'
```

Omitting `-WhenEffective` requests immediate expiration, not immediate endpoint execution. On the endpoint, an administrator can run `Invoke-LapsPolicyProcessing`; then recheck the password update time. See [Set-LapsADPasswordExpirationTime](https://learn.microsoft.com/en-us/powershell/module/laps/set-lapsadpasswordexpirationtime).

## Troubleshooting and rollback

| Symptom | Check |
|---|---|
| Read access exists, decryption is unauthorized | Check the decryptor stored with that password, policy application, rotation since the policy change, and fresh group membership. Keep encryption enabled. |
| No password data | Check account existence, LAPS events, backup directory, schema preparation, SELF rights, and AD replication. |
| Access succeeds outside the pilot | Review ancestor ACLs, nested groups, shared decryptor groups, and computer placement. Stop rollout until explained. |
| Expiration changed but password did not | Check whether the endpoint is online, can reach AD, and has processed LAPS policy. |
| Child OU behaves differently | Review inheritance and the actual computer-object permissions. |

For rollback, remove only the new group memberships and ACEs identified in the change review, and restore the intended GPO settings through your normal controlled process. Do not blindly restore the whole saved OU ACL: other administrators may have made unrelated changes since your snapshot.

Removing delegation cannot erase passwords already retrieved by an operator. If access was over-granted, review the exposure and rotate affected passwords after correcting the policy and ACLs. A decryptor-policy rollback also needs new password generation; old encrypted history is not retroactively rewritten.

Keep the pilot small until the read, decrypt, expiration, out-of-scope denial, and recovery checks all pass. Record those results with the actual OS versions, OU, GPO, and group identities used.
