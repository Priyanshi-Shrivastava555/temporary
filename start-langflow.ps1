[CmdletBinding()]
param([switch]$NoInstall, [switch]$InstallOnly)

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
    throw 'A working Python 3.11+ installation was not found.'
}

$langflowPython = Join-Path $projectRoot '.langflow-venv\Scripts\python.exe'
if (-not (Test-Path $langflowPython)) {
    $launcher = Get-PythonLauncher
    Write-Host 'Creating isolated LangFlow environment...' -ForegroundColor Cyan
    if ($launcher.UsesPyLauncher) { & $launcher.Path -3 -m venv .langflow-venv } else { & $launcher.Path -m venv .langflow-venv }
}

if (-not $NoInstall) {
    Write-Host 'Installing/verifying LangFlow...' -ForegroundColor Cyan
    $localUv = Join-Path $projectRoot '.venv\Scripts\uv.exe'
    $systemUv = Get-Command 'uv' -ErrorAction SilentlyContinue
    if (Test-Path $localUv) {
        & $localUv pip install --python $langflowPython -r requirements-langflow.txt
    } elseif ($null -ne $systemUv) {
        & $systemUv.Source pip install --python $langflowPython -r requirements-langflow.txt
    } else {
        & $langflowPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'LangFlow package installer upgrade failed.' }
        & $langflowPython -m pip install -r requirements-langflow.txt
    }
    if ($LASTEXITCODE -ne 0) { throw 'LangFlow dependency installation failed.' }
}

if ($InstallOnly) {
    Write-Host 'LangFlow environment is installed and ready.' -ForegroundColor Green
    exit 0
}

$env:LANGFLOW_COMPONENTS_PATH = Join-Path $projectRoot 'langflow\components'
$env:LANGFLOW_CONFIG_DIR = Join-Path $projectRoot '.langflow-data'
$env:LANGFLOW_AUTO_LOGIN = 'true'
$env:LANGFLOW_SKIP_AUTH_AUTO_LOGIN = 'true'
$env:LANGFLOW_CORS_ORIGINS = 'http://127.0.0.1:7860,http://localhost:7860'
$env:DO_NOT_TRACK = 'true'
if (Test-Path (Join-Path $projectRoot '.env')) {
    foreach ($line in Get-Content (Join-Path $projectRoot '.env')) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name, 'Process'))) {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}
Write-Host 'LangFlow is starting at http://127.0.0.1:7860' -ForegroundColor Green
Write-Host 'Import langflow\shop_buddy.flow.json, or assemble it from the Shop Buddy custom tools category.'
& $langflowPython -m langflow run --host 127.0.0.1 --port 7860
