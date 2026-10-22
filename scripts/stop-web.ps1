param([ValidateSet('demo','live')][string]$Mode = 'demo')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path $projectRoot ".research_assistant\web\$Mode"
if (-not (Test-Path -LiteralPath $dataRoot)) { return }
# Stop files request normal Uvicorn shutdown; never kill a possibly reused PID.
New-Item -ItemType File -Path (Join-Path $dataRoot 'bff.stop') -Force | Out-Null
Start-Sleep -Milliseconds 500
New-Item -ItemType File -Path (Join-Path $dataRoot 'agent.stop') -Force | Out-Null
$record = Join-Path $dataRoot 'processes.json'
if (Test-Path -LiteralPath $record) {
    $processes = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
    foreach ($processId in @($processes.bff, $processes.agent)) {
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
            Wait-Process -Id $processId -Timeout 30 -ErrorAction SilentlyContinue
        }
    }
}
Write-Output 'Orderly shutdown requested. Check /health is offline before backing up the data directory.'
