# Builds the single-file dist\QuickResize.exe in a private .venv, leaving global Python alone.
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
Invoke-Checked $python -m PyInstaller --noconfirm --clean QuickResize.spec
Write-Host "Built dist\QuickResize.exe"
