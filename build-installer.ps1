# Builds dist\QuickResize-<version>-Setup.exe, which installs into C:\Program Files\QuickResize.
#   ./build-installer.ps1             build all release files (runs build.ps1 first)
#   ./build-installer.ps1 -Install    also install the new Setup.exe on this PC
#   ./build-installer.ps1 -Release    also publish GitHub release v<version>, which installed copies offer as an update
param(
  [string]$Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  [switch]$Install,
  [switch]$Release
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path -LiteralPath $Compiler)) {
  $Compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
  if (!(Test-Path -LiteralPath $Compiler)) { throw 'Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup --scope user' }
}
if ($Release -and (& git status --porcelain)) { throw 'Commit your changes before releasing, so the release tag matches the build.' }

$version = (Get-Content VERSION -Raw).Trim()
if ($version -notmatch '^\d{4}\.\d{2}\.\d{2}\.\d+$') { throw "Unexpected version '$version'." }
$appVersion = (Select-String -Path qr\__init__.py -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
if ($appVersion -ne $version) { throw "VERSION says $version but qr\__init__.py says $appVersion." }

& .\build.ps1
$payload = Join-Path $PSScriptRoot 'dist\QuickResize'
& $Compiler /Q "/DAppVersion=$version" "/DPayloadRoot=$payload" installer\QuickResize.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$setup = Join-Path $PSScriptRoot "dist\QuickResize-$version-Setup.exe"
Write-Host "Built $setup (SHA-256 $((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash))."

if ($Install) {
  # Setup elevates through UAC and closes a running QuickResize itself.
  $process = Start-Process -FilePath $setup -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS' -Verb RunAs -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Setup exited with code $($process.ExitCode)." }
  $installed = Join-Path $env:ProgramFiles 'QuickResize\QuickResize.exe'
  if (!(Test-Path -LiteralPath $installed)) { throw "Setup finished but $installed is missing." }
  Write-Host "Installed QuickResize $version to $(Split-Path $installed)."
}

if ($Release) {
  $tag = "v$version"
  $commit = (& git rev-parse HEAD).Trim()
  & git fetch --quiet origin
  if (!(& git branch -r --contains $commit)) { throw "Push $commit to GitHub before releasing." }
  $notes = @"
QuickResize $version. See [CHANGELOG.md](https://github.com/dgoldwas/QuickResize/blob/$commit/CHANGELOG.md).

- **QuickResize-$version-Setup.exe**: installs into Program Files and updates itself. Installed copies offer this release from Check for updates.
- **QuickResize.exe**: one portable file, nothing to install.
- **QuickResize-$version-portable.zip**: portable folder, starts faster.
"@
  # Tag the commit that was built, not whatever the default branch points at.
  & gh release create $tag $setup dist\QuickResize.exe "dist\QuickResize-$version-portable.zip" THIRD-PARTY-NOTICES.txt `
    --repo dgoldwas/QuickResize --target $commit --title "QuickResize $tag" --notes $notes
  if ($LASTEXITCODE -ne 0) { throw "Creating GitHub release $tag failed." }
  Write-Host "Released $tag."
}
