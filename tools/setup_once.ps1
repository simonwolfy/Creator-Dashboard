$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

function Test-PythonCommand {
    param([string]$Command, [string[]]$Arguments)
    try {
        & $Command @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

$pythonCommand = $null
$pythonArguments = @()
if ((Get-Command py.exe -ErrorAction SilentlyContinue) -and (Test-PythonCommand "py.exe" @("-3.12"))) {
    $pythonCommand = "py.exe"
    $pythonArguments = @("-3.12")
} elseif ((Get-Command python.exe -ErrorAction SilentlyContinue) -and (Test-PythonCommand "python.exe" @())) {
    $pythonCommand = "python.exe"
}

if (-not $pythonCommand) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.12+ and Windows Package Manager were not found. Install Python from https://www.python.org/downloads/windows/ and run Setup Once again."
    }
    Write-Host "Installing Python 3.12 for the current user..."
    & $winget.Source install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE." }
    $python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch "\\Scripts\\" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $python) { throw "Python installed, but python.exe could not be located. Restart Windows and run Setup Once again." }
    $pythonCommand = $python.FullName
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating the private Creator Intelligence Python environment..."
    & $pythonCommand @pythonArguments -m venv (Join-Path $repoRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Python environment creation failed." }
}

Write-Host "Installing Creator Intelligence libraries..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip could not be upgraded." }
& $venvPython -m pip install -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Creator Intelligence library installation failed." }

Write-Host "Preparing FFmpeg, FFprobe, and the local Whisper base model..."
& $venvPython -m creator_intelligence.services.runtime_setup --install
if ($LASTEXITCODE -ne 0) { throw "Local processing component setup did not complete." }

Write-Host "Setup verification passed. START_CREATOR_INTELLIGENCE.bat is ready to use."
