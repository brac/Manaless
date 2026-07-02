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
  # $ErrorActionPreference="Stop" does NOT stop a native-command failure, so check
  # the exit code explicitly rather than falling through to a broken launch.
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create .venv (python -m venv exited $LASTEXITCODE). Is Python 3.12+ on PATH?"
    exit 1
  }
}

# 2. Dependencies -------------------------------------------------------------
# Import the runtime deps as a cheap "is it set up?" probe; install only on miss,
# so warm runs launch instantly. The multipart package imports as either
# `python_multipart` (current) or the deprecated `multipart` alias — probe the
# new name first so a warm launch doesn't reinstall once the alias is removed.
& $py -c "import manaless, uvicorn, fastapi, jinja2" 2>$null
$depsOk = $LASTEXITCODE -eq 0
if ($depsOk) {
  & $py -c "import python_multipart" 2>$null
  if ($LASTEXITCODE -ne 0) { & $py -c "import multipart" 2>$null }
  $depsOk = $LASTEXITCODE -eq 0
}
if (-not $depsOk) {
  Write-Host "Installing dependencies (editable + [web] extra)..." -ForegroundColor Cyan
  & $py -m pip install --upgrade pip | Out-Null
  & $py -m pip install -e ".[web]"
}

# 3. Launch -------------------------------------------------------------------
$url = "http://${BindHost}:${Port}"
Write-Host "Manaless -> $url" -ForegroundColor Green

$browserJob = $null
try {
  if (-not $NoBrowser) {
    # Poll in the background and open the tab only once the server actually
    # answers, so the browser doesn't beat uvicorn to the port and show a dead
    # page (and don't Start-Process at all if it never comes up).
    $browserJob = Start-Job -ScriptBlock {
      param($u)
      $ok = $false
      for ($i = 0; $i -lt 50; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 1 | Out-Null; $ok = $true; break }
        catch { Start-Sleep -Milliseconds 300 }
      }
      if ($ok) { Start-Process $u }
    } -ArgumentList $url
  }

  $uargs = @("-m", "manaless.web", "--host", $BindHost, "--port", $Port)
  if ($Reload) { $uargs += "--reload" }
  & $py @uargs
}
finally {
  if ($browserJob) { Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue }
}
