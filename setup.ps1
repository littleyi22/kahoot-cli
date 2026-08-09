# kahoot-cli Quick Installation Script (Windows / PowerShell)
# Usage: .\setup.ps1 [-Login]
# If blocked by execution policy, run: Set-ExecutionPolicy -Scope Process -Bypass

[CmdletBinding()]
param(
    [switch]$Login
)

$ErrorActionPreference = 'Stop'

Write-Host "===== kahoot-cli Setup Start =====" -ForegroundColor Cyan

# 1. Find Python
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Host "python.exe not found. Please install Python 3.10+ and add it to PATH." -ForegroundColor Red
    Write-Host "Download: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "Using python: $($pyCmd.Source)"
& $pyCmd.Source --version
& $pyCmd.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python version is too old. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

# 2. Install Playwright dependency
Write-Host "`n[1/3] Installing Playwright Python package..." -ForegroundColor Cyan
& $pyCmd.Source -m pip install -r "$PSScriptRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed." -ForegroundColor Red; exit 1 }

# 3. Download Chromium
Write-Host "`n[2/3] Downloading Chromium browser binary (approx. 170MB)..." -ForegroundColor Cyan
& $pyCmd.Source -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Host "Playwright browser install failed." -ForegroundColor Red; exit 1 }

# 4. Run Doctor Check
Write-Host "`n[3/3] Running environment diagnostic check..." -ForegroundColor Cyan
& $pyCmd.Source "$PSScriptRoot\kahoot.py" doctor
if ($LASTEXITCODE -ne 0) { Write-Host "Diagnostic check failed." -ForegroundColor Red; exit 1 }

Write-Host "`n===== Setup Complete =====" -ForegroundColor Green
Write-Host "Next Steps for Kahoot! Login:"
Write-Host "  1. python kahoot.py chrome-login"
Write-Host "  2. Log in manually inside the opened Chrome browser window"
Write-Host "  3. python kahoot.py grab-session"
Write-Host "  4. python kahoot.py check   (Should display [OK])"

if ($Login) {
    Write-Host "`nLaunching dedicated Chrome for Kahoot login..." -ForegroundColor Cyan
    & $pyCmd.Source "$PSScriptRoot\kahoot.py" chrome-login
    Write-Host "After logging in, run: python kahoot.py grab-session" -ForegroundColor Cyan
}
