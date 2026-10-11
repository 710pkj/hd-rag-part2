# 선급 기술검토 에이전트 시연: 백엔드(8000)와 웹(3000)을 켜고 브라우저를 연다.
# 이미 켜져 있으면 다시 켜지 않고 브라우저만 연다. 끄려면 작업 표시줄의 두 창(에이전트 백엔드, 웹 화면)을 닫는다.
param([switch]$NoBrowser)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$webUrl = "http://localhost:3000"

function Test-Url([string]$url) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url | Out-Null; return $true } catch { return $false }
}

if (-not (Test-Url "http://127.0.0.1:8000/health")) {
    $cmd = "`$host.UI.RawUI.WindowTitle = '에이전트 백엔드 - 닫으면 꺼짐'; `$env:PYTHONIOENCODING = 'utf-8'; Set-Location '$root\backend'; .\.venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8000"
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $cmd
}
if (-not (Test-Url "$webUrl/api/health")) {
    $cmd = "`$host.UI.RawUI.WindowTitle = '웹 화면 - 닫으면 꺼짐'; Set-Location '$root\web'; npm run dev"
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $cmd
}

# 웹이 뜰 때까지 최대 90초 기다린다 (백엔드 모델은 화면이 뜬 뒤에도 30초쯤 더 불러옴 - 상단 바에 표시)
for ($i = 0; $i -lt 90; $i++) {
    if (Test-Url "$webUrl/api/health") { break }
    Start-Sleep -Seconds 1
}
if (-not $NoBrowser) { Start-Process $webUrl }
