# Builds both release forms in a private .venv, leaving global Python alone:
#   dist\QuickResize.exe                       single file
#   dist\QuickResize-<version>-portable.zip    portable folder
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked {
    # Exit codes decide failure. PyInstaller logs normal progress to stderr.
    $ErrorActionPreference = "Continue"
    & $args[0] $args[1..($args.Count - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Failed: $args" }
}

if (-not (Test-Path .venv\Scripts\python.exe)) { Invoke-Checked py -m venv .venv }
$python = ".venv\Scripts\python.exe"
Invoke-Checked $python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
Invoke-Checked $python -m pytest tests -q

Invoke-Checked $python -m PyInstaller --noconfirm --clean --workpath build\exe QuickResize.spec
Invoke-Checked $python -m PyInstaller --noconfirm --clean --workpath build\folder QuickResize.spec '--' --folder

$version = (Get-Content VERSION -Raw).Trim()
$folder = "dist\QuickResize"
Copy-Item packaging\README.txt, THIRD-PARTY-NOTICES.txt $folder
$zip = "dist\QuickResize-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
# The archive holds a single top-level QuickResize folder.
Compress-Archive -Path $folder -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Built dist\QuickResize.exe and $zip"
