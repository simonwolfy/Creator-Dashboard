param([switch]$SkipTests, [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ReleaseDir = Join-Path $Root "release"
$Version = python -m creator_intelligence.core.release_verification --print-version
$ReleaseRank = python -m creator_intelligence.core.release_verification --print-release-rank
python -m creator_intelligence.core.release_verification --source
if (-not $SkipTests) {
    python -m pytest
    python -m creator_intelligence.core.privacy_audit --history
}
python -m PyInstaller --noconfirm --clean CreatorIntelligence.spec
python -m creator_intelligence.core.release_verification --bundle dist\CreatorIntelligence
$PackagedExecutable = Join-Path $Root "dist\CreatorIntelligence\CreatorIntelligence.exe"
$SmokeProcess = Start-Process -FilePath $PackagedExecutable -ArgumentList @("--release-smoke-test") -Wait -PassThru
if ($SmokeProcess.ExitCode -ne 0) {
    throw "The standalone packaged smoke test failed with exit code $($SmokeProcess.ExitCode)."
}
if (-not $SkipInstaller) {
    if (Test-Path -LiteralPath $ReleaseDir) {
        Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
    $Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $Iscc) { throw "Inno Setup 6 is required to build the installer (ISCC.exe was not found)." }
    & $Iscc.Source "/DMyAppVersion=$Version" "/DMyAppReleaseRank=$ReleaseRank" installer\CreatorIntelligence.iss
    Get-ChildItem $ReleaseDir -File -Filter *.exe | ForEach-Object {
        $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash  $($_.Name)" | Set-Content "$($_.FullName).sha256" -Encoding ascii
    }
    python -m creator_intelligence.core.release_verification --write-manifest $ReleaseDir
    python -m creator_intelligence.core.release_verification --artifacts $ReleaseDir
}
