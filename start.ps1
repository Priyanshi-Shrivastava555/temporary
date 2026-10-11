[CmdletBinding()]
param([switch]$NoInstall)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Get-PythonLauncher {
    foreach ($candidate in @('py', 'python')) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $command) { continue }
        try {
            if ($candidate -eq 'py') { & $command.Source -3 --version *> $null } else { & $command.Source --version *> $null }
            if ($LASTEXITCODE -eq 0) { return @{ Path = $command.Source; UsesPyLauncher = ($candidate -eq 'py') } }
        } catch { }
    }
    throw 'A working Python 3 installation was not found. Install Python 3.11+ from python.org, then run this script again.'
}

function Get-CommandPath([string]$name) {
    $candidate = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { throw "$name was not found. Install it and run this script again." }
    return $candidate.Source
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    $pythonLauncher = Get-PythonLauncher
    Write-Host 'Creating local Python environment...' -ForegroundColor Cyan
    if ($pythonLauncher.UsesPyLauncher) { & $pythonLauncher.Path -3 -m venv .venv } else { & $pythonLauncher.Path -m venv .venv }
}

$npmPath = Get-CommandPath 'npm.cmd'
if (-not $NoInstall) {
    Write-Host 'Installing/verifying Python packages...' -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'Python package installer upgrade failed.' }
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Write-Host 'Installing/verifying React packages...' -ForegroundColor Cyan
    Push-Location frontend
    & $npmPath install
    if ($LASTEXITCODE -ne 0) { throw 'React dependency installation failed.' }
    Pop-Location
}

if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
New-Item -ItemType Directory -Force -Path 'logs' | Out-Null

function Test-Port($port) {
    try { return (Test-NetConnection -ComputerName '127.0.0.1' -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) } catch { return $false }
}

if (-not (Test-Port 8000)) {
    Start-Process -FilePath $venvPython -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'logs\api.log') -RedirectStandardError (Join-Path $projectRoot 'logs\api-error.log')
}
if (-not (Test-Port 5173)) {
    Start-Process -FilePath $npmPath -ArgumentList @('run','dev','--','--host','127.0.0.1','--port','5173') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot 'logs\frontend.log') -RedirectStandardError (Join-Path $projectRoot 'logs\frontend-error.log')
}

$deadline = (Get-Date).AddSeconds(30)
while ((-not (Test-Port 8000) -or -not (Test-Port 5173)) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if (-not (Test-Port 8000)) { throw 'The API did not start. Check logs\api-error.log.' }
if (-not (Test-Port 5173)) { throw 'The React frontend did not start. Check logs\frontend-error.log.' }
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5
    if ($health.status -ne 'ok') { throw 'Health endpoint did not report ok.' }
} catch {
    throw "The API port opened but its health check failed: $($_.Exception.Message)"
}

Write-Host ''
Write-Host 'Shop Buddy is running.' -ForegroundColor Green
Write-Host '  Storefront: http://127.0.0.1:5173'
Write-Host '  API docs:   http://127.0.0.1:8000/docs'
Write-Host '  Logs:       .\logs\'

