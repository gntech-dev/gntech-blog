---
title: "PowerShell Modules Filled My OneDrive — How to Clean Up Safely"
description: "Find PowerShell modules in OneDrive, copy them to local storage, verify imports, and prevent future installs from filling your synced Documents folder."
date: 2026-10-30T13:00:00-04:00
draft: true
tags:
  - powershell
  - windows
  - onedrive
  - troubleshooting
keywords:
  - PowerShell modules OneDrive storage
  - PowerShell module path
  - redirected Documents modules
summary: "A practical cleanup workflow for PowerShell modules in a OneDrive-backed Documents folder, with verification, rollback, and explicit destinations for future downloads."
---

OneDrive was using space for something I never intended to sync: PowerShell modules. An inventory on one of my Windows accounts found approximately 1.16 GiB under `Documents\WindowsPowerShell\Modules` and another 1.22 GiB under `Documents\PowerShell\Modules`.

That is nearly 2.4 GiB of module files, before counting anything else in Documents.

The reason is the combination of PowerShell's per-user module locations and a Documents folder redirected into OneDrive. The fix needs two parts: relocate the existing modules and give future module downloads an explicit destination.

This guide prepares a cleanup on one Windows account. It does not change your Documents location or disable OneDrive backup.

## Before you start

Use the affected user's account. Close scripts and scheduled jobs that use these modules before changing their location. In File Explorer, select **Always keep on this device** for the source module folders and wait until OneDrive finishes downloading them. Keep syncing enabled until that completes.

The examples use built-in Windows tools and PowerShell syntax intended for Windows PowerShell 5.1 and PowerShell 7. They have not been executed against a Windows machine as part of preparing this article. Pilot the procedure before using it broadly.

If your organization manages application control, stop when a policy blocks a command or module import. Moving files does not grant permission to run them.

## 1. Find the actual Documents folder

Run this in each PowerShell edition you use:

```powershell
$PSVersionTable.PSVersion
$ExecutionContext.SessionState.LanguageMode
$env:PSModulePath -split ';'
Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -Name Personal
```

The last command shows the account's configured Documents location. Look for module search paths under that location. Typical redirected paths look like this:

```text
C:\Users\example\OneDrive - Example\Documents\WindowsPowerShell\Modules
C:\Users\example\OneDrive - Example\Documents\PowerShell\Modules
```

`WindowsPowerShell` normally corresponds to Windows PowerShell 5.1; `PowerShell` corresponds to PowerShell 7. Keep their module trees separate because compatibility and dependencies can differ.

Do not assume that Documents is always at `$env:USERPROFILE\Documents`.

## 2. Measure the module folders

Set `$documents` to the real path found above. Replace the example before running:

```powershell
$documents = 'C:\Users\example\OneDrive - Example\Documents'

foreach ($edition in 'WindowsPowerShell', 'PowerShell') {
    $source = Join-Path $documents "$edition\Modules"
    if (Test-Path -LiteralPath $source) {
        $measure = Get-ChildItem -LiteralPath $source -File -Recurse -Force -ErrorAction Stop |
            Measure-Object -Property Length -Sum
        $folders = Get-ChildItem -LiteralPath $source -Directory -ErrorAction Stop |
            Measure-Object
        Write-Output "Path: $source"
        Write-Output "Module folders: $($folders.Count)"
        Write-Output "Logical size in GiB: $($measure.Sum / 1GB)"
    }
}
```

This measures logical file sizes. It does not measure local disk allocation or OneDrive's server-side quota, which can include other content and version history. Resolve access errors before continuing.

## 3. Copy the modules outside OneDrive

Keep `$documents` set in the same window. The destination is under the user's local application data folder, which is normally outside OneDrive. Verify that is true on your machine.

```powershell
$localRoot = Join-Path $env:LOCALAPPDATA 'PowerShellModules'
New-Item -ItemType Directory -Path $localRoot -Force | Out-Null

foreach ($edition in 'WindowsPowerShell', 'PowerShell') {
    $source = Join-Path $documents "$edition\Modules"
    $destination = Join-Path $localRoot "$edition\Modules"
    if (Test-Path -LiteralPath $source) {
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        robocopy.exe $source $destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ
        if ($LASTEXITCODE -ge 8) {
            throw "Copy failed for $source. Keep the source and inspect the robocopy output."
        }
    }
}
```

Robocopy uses exit codes differently from many command-line tools: codes below 8 do not indicate a copy failure. Review its summary for failed files, mismatches, and unexpected extra files too. The command copies subdirectories and does not delete the source or mirror deletions.

Treat this as a migration copy, not your only backup. Preserve an independent backup before the removal step.

## 4. Add the correct local tree to a fresh session

Open a new PowerShell window and run this bootstrap:

```powershell
$editionFolder = 'WindowsPowerShell'
if ($PSVersionTable.PSVersion.Major -ge 6) {
    $editionFolder = 'PowerShell'
}
$localModules = Join-Path $env:LOCALAPPDATA "PowerShellModules\$editionFolder\Modules"
$env:PSModulePath = "$localModules;$env:PSModulePath"

Get-Module -ListAvailable |
    Where-Object { $_.ModuleBase -like "$localModules\*" } |
    Select-Object Name, Version, ModuleBase
```

This changes the current process only. Windows and PowerShell reconstruct module paths at startup; a custom search path also does not redefine the default destination used by `Install-Module -Scope CurrentUser`.

For an interactive setup, the bootstrap can live in an approved PowerShell profile. Review the existing profile before adding it, and remember that profiles differ between editions and hosts. A profile under redirected Documents may still sync, but the large module files stay local.

For scheduled jobs or sessions launched with `-NoProfile`, put the bootstrap directly in the job's approved entry script. A profile is not a tenant-wide deployment mechanism.

## 5. Verify the modules you actually use

In the fresh session, replace the example with a module you rely on:

```powershell
Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
Get-Module Microsoft.Graph.Authentication |
    Select-Object Name, Version, ModuleBase
Get-Command Connect-MgGraph -ErrorAction Stop |
    Select-Object Name, Source, Version
```

Check that `ModuleBase` points into the new local tree. If the module is not installed, choose one that appeared in your inventory. Repeat in both editions and run a harmless read-only operation from each important module. Importing successfully does not prove every feature works.

Also check scheduled tasks, VS Code sessions, and scripts with hardcoded OneDrive paths. They need the local bootstrap or updated paths before cleanup.

## 6. Prevent future downloads from returning to OneDrive

When using PowerShellGet, `Save-Module` lets you choose the destination. After running the bootstrap above, this example downloads a module and its dependencies into the local tree:

```powershell
Save-Module -Name Microsoft.Graph.Authentication -Path $localModules -Repository PSGallery -ErrorAction Stop
```

Select a version appropriate to your environment; use `-RequiredVersion` when you need a reproducible installation. Review repository trust and any prompts rather than automatically bypassing them. If the command is unavailable, arrange an approved installation of PowerShellGet first.

`Save-Module` saves files; the module becomes discoverable because its destination is on `PSModulePath`. It does not make `Get-InstalledModule` or `Update-Module` manage those saved copies as ordinary `Install-Module` installations. Maintain them with an explicit, versioned download workflow.

Continuing to use `Install-Module -Scope CurrentUser` can recreate modules in redirected Documents. Merely prepending a directory to `PSModulePath` does not prevent that.

## 7. Remove only a verified source tree

Deletion inside OneDrive propagates to the cloud and other synced devices. First confirm that other machines have their own working local copies or an approved way to reinstall the required modules. The destination under LocalAppData does not travel to those machines with OneDrive.

For each edition, verify the copy and important imports, confirm an independent backup exists, and then preview removal of that specific source folder:

```powershell
$sourceToRemove = Join-Path $documents 'WindowsPowerShell\Modules'
Get-Item -LiteralPath $sourceToRemove -ErrorAction Stop
Remove-Item -LiteralPath $sourceToRemove -Recurse -Force -WhatIf
```

The preview deletes nothing. Only after reviewing the exact path and completing the checks above, run:

```powershell
Remove-Item -LiteralPath $sourceToRemove -Recurse -Force -Confirm
```

Repeat separately for `PowerShell\Modules` if it has also passed validation. Do not delete Documents, either parent PowerShell folder, or profiles as part of this cleanup.

Wait for OneDrive to finish syncing, then inspect storage in OneDrive on the web. Do not promise an immediate quota reduction equal to the inventory. Review recycle bin and version retention behavior for your account before permanently removing recovery options.

## If PowerShell reports ConstrainedLanguage

On my account, a previous inventory attempt failed because method invocation was restricted. Check the mode with:

```powershell
$ExecutionContext.SessionState.LanguageMode
```

The inventory above avoids calling methods such as `[Environment]::GetFolderPath()`. This helps with that specific restriction, but it does not guarantee that module imports, profile changes, or every command will be permitted by application control.

If policy blocks a step, use your organization's approved deployment process. Do not switch language modes or weaken execution controls to complete the cleanup.

## Rollback

Before removal, the original module folders remain available. To undo the session-only search path change, close that window and start a new one without the bootstrap. If you added it to a profile or task, remove only your added block.

After removal, restore the original tree from your independent backup, or use OneDrive recovery if the content is still recoverable. Recheck module versions and import locations in a fresh session. Avoid blindly overwriting newer files with an older copy.

## For multiple managed Windows devices

Pilot on one account first. Package the approved module versions into a local location, configure discovery in each supported host, verify application-control compatibility, and only then remove synced copies. Include jobs running under different identities in the pilot.

A OneDrive exclusion rule is not a substitute for moving the module workload: modules left in Documents still need a deliberate installation and discovery strategy. Treat fleet deployment as a separate change with detection, logging, and rollback.

## References

- [Microsoft: about_PSModulePath](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_psmodulepath)
- [Microsoft: Save-Module](https://learn.microsoft.com/en-us/powershell/module/powershellget/save-module)
- [Microsoft: about_Language_Modes](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_language_modes)
- [Microsoft: Robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy)

These are the vendor documentation entry points for the commands used here. Confirm the documentation matches the PowerShell and PowerShellGet versions installed on your machine.