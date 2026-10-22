param(
    [ValidateRange(1,65535)][int]$AgentPort = 2027,
    [ValidateRange(1,65535)][int]$WebPort = 8082,
    [string]$DataRoot = '.research_assistant/interview-demo',
    [ValidateRange(0,5)][double]$DelaySeconds = 0.6,
    [switch]$FailSecondAnswerOnce
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $projectRoot
$pythonPath = (Resolve-Path -LiteralPath '.venv-web/Scripts/python.exe').Path
if ($AgentPort -eq $WebPort) { throw 'AgentPort and WebPort must differ.' }
foreach ($port in @($AgentPort,$WebPort)) {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $probe.Start() } finally { $probe.Stop() }
}
$resolvedData = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $DataRoot))
$protectedRoot = Join-Path $projectRoot '.research_assistant/web'
if ($resolvedData -eq $protectedRoot -or $resolvedData.StartsWith($protectedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Use a separate interview Demo data-root.' }
$processFile = Join-Path $resolvedData 'processes.json'
if (Test-Path -LiteralPath $processFile) {
    $previous = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
    foreach ($processId in @($previous.agent,$previous.bff)) {
        if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw 'This data-root still has a running process. Stop only its own servers first.' }
    }
}
New-Item -ItemType Directory -Path $resolvedData -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:RA_WEB_MODE = 'demo'
$env:RA_WEB_DATA = $resolvedData
$env:RA_AGENT_URL = "http://127.0.0.1:$AgentPort"
$env:RA_WEB_PORT = "$WebPort"
$env:RA_INTERVIEW_DEMO_DELAY = $DelaySeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
$env:RA_INTERVIEW_DEMO_FAIL_ONCE = if ($FailSecondAnswerOnce) { '1' } else { '0' }
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
$agent = Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web.agent' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolvedData 'agent.out.log') -RedirectStandardError (Join-Path $resolvedData 'agent.err.log')
$bff = Start-Process -FilePath $pythonPath -ArgumentList '-m','research_assistant.web' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $resolvedData 'bff.out.log') -RedirectStandardError (Join-Path $resolvedData 'bff.err.log')
@{agent=$agent.Id;bff=$bff.Id;agent_port=$AgentPort;web_port=$WebPort;data_root=$resolvedData} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolvedData 'processes.json') -Encoding utf8
Write-Output "Demo starting at http://127.0.0.1:$WebPort; readiness: /ready; data: $resolvedData"
Write-Output 'Orderly stop: create agent.stop and bff.stop ONLY in this data-root.'
