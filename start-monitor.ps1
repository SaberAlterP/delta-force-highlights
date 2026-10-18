[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$BackendDir = Join-Path $PSScriptRoot 'backend'
$MonitorLog = Join-Path $BackendDir 'storage\workflow\monitor-launcher.log'
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $MonitorLog) | Out-Null
    try {
        $MonitorHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        if ($MonitorHealth.status -eq 'ok') { exit 0 }
    } catch { }
    $MonitorPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
    Start-Process -FilePath $MonitorPython -WorkingDirectory $BackendDir -WindowStyle Hidden -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'
    ) -RedirectStandardOutput (Join-Path $BackendDir 'storage\workflow\server-out.log') `
      -RedirectStandardError (Join-Path $BackendDir 'storage\workflow\server-error.log')
    Add-Content -LiteralPath $MonitorLog -Value "$(Get-Date -Format s) monitor service launched"
} catch {
    Add-Content -LiteralPath $MonitorLog -Value "$(Get-Date -Format s) $($_.Exception.Message)"
}
