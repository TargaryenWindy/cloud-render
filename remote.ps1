$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Test-RenderApp {
    try {
        $response = Invoke-WebRequest 'http://127.0.0.1:7860/' -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'data') | Out-Null
if (!(Test-RenderApp)) {
    Write-Host 'Render app is not running. Starting it now...'
    $appStdout = Join-Path $PSScriptRoot 'data\remote-server.log'
    $appStderr = Join-Path $PSScriptRoot 'data\remote-server-error.log'
    $startScript = Join-Path $PSScriptRoot 'start.ps1'
    $appLauncher = Start-Process -FilePath (Get-Command powershell.exe).Source -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $startScript + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $appStdout -RedirectStandardError $appStderr
    $appReady = $false
    # First launch on a new PC may need to create Python's environment and download dependencies.
    for ($attempt = 0; $attempt -lt 600; $attempt++) {
        if (Test-RenderApp) { $appReady = $true; break }
        if ($appLauncher.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (!$appReady) {
        $details = Get-Content -LiteralPath $appStderr -Tail 12 -ErrorAction SilentlyContinue
        throw "Render app failed to start. See $appStderr`n$details"
    }
}
Write-Host 'Render app is ready at http://127.0.0.1:7860/'
$tunnelExe = Join-Path $PSScriptRoot 'tools\cloudflared.exe'
if (!(Test-Path $tunnelExe)) {
    New-Item -ItemType Directory -Force tools | Out-Null
    Invoke-WebRequest 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $tunnelExe
}
$tunnelLog = Join-Path $PSScriptRoot 'data\tunnel.log'
$tunnelOutput = Join-Path $PSScriptRoot 'data\tunnel-stdout.log'
New-Item -ItemType Directory -Force (Split-Path $tunnelLog) | Out-Null
Write-Host 'Starting remote access. Keep this window open; press Ctrl+C to stop.'
$tunnelProcess = Start-Process -FilePath $tunnelExe -ArgumentList @('tunnel','--url','http://127.0.0.1:7860','--no-autoupdate') -WindowStyle Hidden -PassThru -RedirectStandardError $tunnelLog -RedirectStandardOutput $tunnelOutput
try {
    $remoteUrl = $null
    $deadline = (Get-Date).AddSeconds(60)
    $connected = $false
    while (!$tunnelProcess.HasExited -and (!$remoteUrl -or !$connected) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $content = Get-Content -LiteralPath $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($content -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $remoteUrl = $Matches[0] }
        $connected = $content -match 'Registered tunnel connection'
    }
    if (!$remoteUrl -or !$connected) { throw "Tunnel did not connect. See $tunnelLog" }
    Write-Host "Logs: $tunnelLog"
    Write-Host $remoteUrl
    # Logs go to disk so the URL stays the last terminal line.
    while (!$tunnelProcess.HasExited) { Start-Sleep -Seconds 1 }
} finally {
    if (!$tunnelProcess.HasExited) { Stop-Process -Id $tunnelProcess.Id }
}
