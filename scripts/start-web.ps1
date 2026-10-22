param(
    [ValidateSet('demo','live')][string]$Mode = 'demo',
    [string]$Python = '.venv-web\Scripts\python.exe',
    [int]$StartupTimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$dataRoot = Join-Path $projectRoot ".research_assistant\web\$Mode"
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
foreach ($port in @(2025,8080)) {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $probe.Start() } finally { $probe.Stop() }
}
$env:PYTHONUTF8 = '1'
$env:RA_WEB_MODE = $Mode
$env:RA_WEB_DATA = $dataRoot
$env:RA_AGENT_URL = 'http://127.0.0.1:2025'
$env:RA_WEB_PORT = '8080'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
$agent = Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web.agent' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataRoot 'agent.out.log') -RedirectStandardError (Join-Path $dataRoot 'agent.err.log')
$bff = Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataRoot 'bff.out.log') -RedirectStandardError (Join-Path $dataRoot 'bff.err.log')
@{agent=$agent.Id; bff=$bff.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot 'processes.json') -Encoding utf8
$deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
Write-Output 'Starting local Demo/Live processes. The first import in a new environment can take several minutes.'
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $ready = Invoke-RestMethod 'http://127.0.0.1:8080/ready' -TimeoutSec 2
        if ($ready.ok -and $ready.mode -eq $Mode) {
            Write-Output "Research Assistant ($Mode): http://127.0.0.1:8080"
            return
        }
    } catch { }
    if ($agent.HasExited -or $bff.HasExited) { break }
    Start-Sleep -Milliseconds 500
}
New-Item -ItemType File -Path (Join-Path $dataRoot 'bff.stop') -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $dataRoot 'agent.stop') -Force | Out-Null
throw "Server not ready. Check logs in $dataRoot. Live requires configured API keys."
