param([switch]$SkipTests, [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ReleaseDir = Join-Path $Root "release"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

$Version = & python -m creator_intelligence.core.release_verification --print-version
if ($LASTEXITCODE -ne 0) { throw "Version detection failed with exit code $LASTEXITCODE." }
$ReleaseRank = & python -m creator_intelligence.core.release_verification --print-release-rank
if ($LASTEXITCODE -ne 0) { throw "Release-rank detection failed with exit code $LASTEXITCODE." }
Invoke-Checked { python -m creator_intelligence.core.release_verification --source } "Source release verification"
if (-not $SkipTests) {
    Invoke-Checked { python -m pytest } "Regression tests"
    Invoke-Checked { python -m creator_intelligence.core.privacy_audit --history } "Git history privacy audit"
}
Invoke-Checked { python -m PyInstaller --noconfirm --clean CreatorIntelligence.spec } "PyInstaller build"
Invoke-Checked { python -m creator_intelligence.core.release_verification --bundle dist\CreatorIntelligence } "Bundle verification"
$StandaloneExe = Join-Path $Root "dist\CreatorIntelligence\CreatorIntelligence.exe"
Invoke-Checked { & $StandaloneExe --release-smoke-test } "Packaged application smoke test"
if (-not $SkipInstaller) {
    if (Test-Path -LiteralPath $ReleaseDir) {
        Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
    $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $IsccPath = if ($IsccCommand) { $IsccCommand.Source } else { $null }
    if (-not $IsccPath) {
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
        )
        $IsccPath = $Candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    }
    if (-not $IsccPath) { throw "Inno Setup 6 is required to build the installer (ISCC.exe was not found)." }
    Invoke-Checked {
        & $IsccPath "/DMyAppVersion=$Version" "/DMyAppReleaseRank=$ReleaseRank" installer\CreatorIntelligence.iss
    } "Inno Setup compilation"
    Get-ChildItem $ReleaseDir -File -Filter *.exe | ForEach-Object {
        $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash  $($_.Name)" | Set-Content "$($_.FullName).sha256" -Encoding ascii
    }
    Invoke-Checked { python -m creator_intelligence.core.release_verification --write-manifest $ReleaseDir } "Release manifest creation"
    Invoke-Checked { python -m creator_intelligence.core.release_verification --artifacts $ReleaseDir } "Installer artifact verification"
}
