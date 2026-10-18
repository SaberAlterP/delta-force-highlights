<#
Silent local launcher called by the VBS entrypoint.
It starts only services that are not already listening on ports 8000 and 5173.
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

    if (-not (Test-LocalPort 5173)) {
        $viteCmd = Join-Path $FrontendDir "node_modules\.bin\vite.cmd"
        if (-not (Test-Path -LiteralPath $viteCmd)) { throw "Frontend dependency missing: $viteCmd" }
        $cmdArgs = "/d /c call `"$viteCmd`" --host 127.0.0.1 --port 5173 --strictPort"
        Start-Process -FilePath $env:ComSpec -WorkingDirectory $FrontendDir -WindowStyle Hidden -ArgumentList $cmdArgs
        Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) frontend started"
    }

    if (-not (Wait-ForHttp "http://127.0.0.1:8000/api/health")) {
        throw "Backend did not start within 20 seconds. See backend\\storage\\tmp\\launcher.log."
    }
    if (-not (Wait-ForHttp "http://127.0.0.1:5173/")) {
        throw "Frontend did not start within 20 seconds. See backend\\storage\\tmp\\launcher.log."
    }

    if (-not $NoBrowser) {
        Start-Process -FilePath "msedge.exe" -ArgumentList "http://127.0.0.1:5173/"
    }
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) ready"
} catch {
    Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format s) ERROR $($_.Exception.Message)"
    throw
}
