param([switch]$SkipTests, [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $SkipTests) {
    python -m pytest
    python -m creator_intelligence.core.privacy_audit
}
python -m PyInstaller --noconfirm --clean CreatorIntelligence.spec
if (-not $SkipInstaller) {
    $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $Iscc) { throw "Inno Setup 6 is required to build the installer (ISCC.exe was not found)." }
    & $Iscc.Source installer\CreatorIntelligence.iss
}
New-Item -ItemType Directory -Force release | Out-Null
Get-ChildItem release -File | ForEach-Object {
    $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  $($_.Name)" | Set-Content "$($_.FullName).sha256"
}
