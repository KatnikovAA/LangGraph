param(
    [Parameter(Mandatory=$true)][ValidateSet('live','demo')][string]$Mode,
    [ValidateRange(1,65535)][int]$AgentPort = 2028,
    [ValidateRange(1,65535)][int]$WebPort = 8083,
    [string]$DataRoot = '',
    [ValidateRange(0,3)][double]$DelaySeconds = 0.4,
    [switch]$FailWorkerB
)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $projectRoot
$pythonPath=(Resolve-Path -LiteralPath '.venv-web/Scripts/python.exe').Path
if ($AgentPort -eq $WebPort) { throw 'Agent and Web ports must differ.' }
foreach ($port in @($AgentPort,$WebPort)) {
    $probe=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$port)
    try { $probe.Start() } finally { $probe.Stop() }
}
if (-not $DataRoot) { $DataRoot=".research_assistant/team/$Mode" }
$resolvedData=[System.IO.Path]::GetFullPath((Join-Path $projectRoot $DataRoot))
foreach ($protectedName in @('.research_assistant/web','.research_assistant/studio')) {
    $protectedRoot=[System.IO.Path]::GetFullPath((Join-Path $projectRoot $protectedName))
    if ($resolvedData -eq $protectedRoot -or $resolvedData.StartsWith($protectedRoot,[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Use a separate Team data-root.' }
}
$record=Join-Path $resolvedData 'processes.json'
if (Test-Path -LiteralPath $record) {
    $previous=Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
    foreach ($processId in @($previous.agent,$previous.bff)) {
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw 'This data-root still has running processes.' }
    }
}
New-Item -ItemType Directory -Path $resolvedData -Force | Out-Null
$env:PYTHONUTF8='1'
$env:RA_WEB_MODE=$Mode
$env:RA_WEB_DATA=$resolvedData
$env:RA_AGENT_URL="http://127.0.0.1:$AgentPort"
$env:RA_WEB_PORT="$WebPort"
$env:RA_TEAM_DEMO_DELAY=$DelaySeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
$env:RA_TEAM_DEMO_FAIL_B=if ($Mode -eq 'demo' -and $FailWorkerB) { '1' } else { '0' }
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
$agent=Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web.agent' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolvedData 'agent.out.log') -RedirectStandardError (Join-Path $resolvedData 'agent.err.log')
$bff=Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolvedData 'bff.out.log') -RedirectStandardError (Join-Path $resolvedData 'bff.err.log')
@{agent=$agent.Id;bff=$bff.Id;agent_port=$AgentPort;web_port=$WebPort;mode=$Mode;data_root=$resolvedData} | ConvertTo-Json | Set-Content -LiteralPath $record -Encoding utf8
Write-Output "Starting $Mode at http://127.0.0.1:$WebPort ; readiness /ready ; data $resolvedData"
Write-Output 'Stop only these processes with agent.stop and bff.stop in this data-root.'
