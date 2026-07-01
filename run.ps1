#!/usr/bin/env pwsh
# Quickstart: set up once, then launch the Manaless web builder.
#
#   ./run.ps1                # start on http://127.0.0.1:8000 and open a browser
#   ./run.ps1 -Port 9000     # pick a port
#   ./run.ps1 -Reload        # auto-reload on code changes (dev)
#   ./run.ps1 -NoBrowser     # don't open a browser tab
#
# First run creates .venv and installs the package (editable) + web extras.
# Subsequent runs skip straight to launch.
[CmdletBinding()]
param(
  [string]$BindHost = "127.0.0.1",  # not $Host — that's a reserved automatic var
  [int]$Port = 8000,
  [switch]$Reload,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# 1. Virtual environment ------------------------------------------------------
if (-not (Test-Path $py)) {
  Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
  python -m venv .venv
}

# 2. Dependencies -------------------------------------------------------------
# Import the runtime deps as a cheap "is it set up?" probe; install only on miss,
# so warm runs launch instantly.
& $py -c "import manaless, uvicorn, fastapi, jinja2, multipart" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing dependencies (editable + [web] extra)..." -ForegroundColor Cyan
  & $py -m pip install --upgrade pip | Out-Null
  & $py -m pip install -e ".[web]"
}

# 3. Launch -------------------------------------------------------------------
$url = "http://${BindHost}:${Port}"
Write-Host "Manaless -> $url" -ForegroundColor Green

if (-not $NoBrowser) {
  # Poll in the background and open the tab once the server actually answers,
  # so the browser doesn't beat uvicorn to the port and show a dead page.
  Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 50; $i++) {
      try { Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1 | Out-Null; break }
      catch { Start-Sleep -Milliseconds 300 }
    }
    Start-Process $u
  } -ArgumentList $url | Out-Null
}

$uargs = @("-m", "manaless.web", "--host", $BindHost, "--port", $Port)
if ($Reload) { $uargs += "--reload" }
& $py @uargs
