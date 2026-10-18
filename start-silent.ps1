<#
Silent local launcher called by the VBS entrypoint.
It starts the backend on port 8000 (which also serves the built web page) if not already running.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogFile = Join-Path $BackendDir "storage\tmp\launcher.log"

function Test-LocalPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne(250)) {
            $client.EndConnect($async)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ForHttp([string]$Url, [int]$TimeoutSeconds = 20) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-ListeningProcess([int]$Port) {
    $line = netstat -ano -p tcp | Select-String "127\.0\.0\.1:$Port\s+.*LISTENING" | Select-Object -First 1
    if (-not $line) { return }
    $processId = [int](($line.ToString() -split '\s+')[-1])
    if ($processId -gt 0 -and $processId -ne $PID) {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 300
    }
}

try {
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) launcher requested"

    # A listening port is not enough: restart automatically when detector code version changed.
    if (Test-LocalPort 8000) {
        $expectedVersion = (Get-Content -LiteralPath (Join-Path $BackendDir "detector-version.txt") -Raw).Trim()
        $activeVersion = ""
        try {
            $activeVersion = (Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/config" -TimeoutSec 2).detector_version
        } catch { }
        if ($activeVersion -ne $expectedVersion) {
            Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) backend version changed: $activeVersion -> $expectedVersion"
            Stop-ListeningProcess 8000
        }
    }

    if (-not (Test-LocalPort 8000)) {
        $python = Join-Path $BackendDir ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) { throw "Backend runtime missing: $python" }
        Start-Process -FilePath $python -WorkingDirectory $BackendDir -WindowStyle Hidden -ArgumentList @(
            "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"
        )
        Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) backend started"
    }

    # 网页由后端直接提供（frontend\dist），不再启动 Vite 开发服务器。
    $dist = Join-Path $FrontendDir "dist\index.html"
    if (-not (Test-Path -LiteralPath $dist)) { throw "Frontend not built: run 'npm run build' in frontend" }

    if (-not (Wait-ForHttp "http://127.0.0.1:8000/api/health")) {
        throw "Backend did not start within 20 seconds. See backend\storage\tmp\launcher.log."
    }

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:8000/"
    }
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) ready"
} catch {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) ERROR $($_.Exception.Message)"
    throw
}
