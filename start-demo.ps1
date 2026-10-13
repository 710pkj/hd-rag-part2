# 선급 기술검토 에이전트 시연: 로컬 DB(5433, 설치돼 있으면) · 백엔드(8000) · 웹(3000)을 켜고 시연용 크롬 창을 연다.
# 크롬 창을 닫으면 이 스크립트가 켠 서버 창(에이전트 백엔드, 웹 화면)과 DB도 함께 꺼지고 이 스크립트도 끝난다.
# 이미 켜져 있던 서버 · DB는 다시 켜지 않고, 크롬을 닫아도 끄지 않는다.
# -NoBrowser: 서버만 켜고 끝냄 (서버 창을 직접 닫아야 꺼짐. DB는 pg_ctl stop으로 끔)
param([switch]$NoBrowser)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$webUrl = "http://localhost:3000"
# 시연 전용 브라우저 프로필. 평소 쓰는 크롬과 따로 띄워야 이 창이 언제 닫혔는지 알 수 있다
# (평소 크롬이 켜져 있으면 새로 실행한 크롬은 기존 창에 탭만 넘기고 바로 끝나 버림)
$profileDir = Join-Path $env:LOCALAPPDATA "hd-rag-demo\browser"
# 로컬 PostgreSQL: 1단계 검색용 DB(hdsearch)와 실행 기록(hdrag). setup.ps1 -LocalDb가 설치함
# 설치돼 있지 않으면 건너뜀 (백엔드는 FAISS(메모리)로 검색하고 기록은 JSONL 파일에 씀. 검색 결과는 같음)
$pgDir = if ($env:HD_PG_DIR) { $env:HD_PG_DIR } else { Join-Path $env:USERPROFILE "dev\localpg" }
$pgPort = 5433
$pgBin = Join-Path $pgDir "env\Library\bin"
$env:PGGSSENCMODE = "disable"   # conda-forge PostgreSQL 도구가 Kerberos 인증을 먼저 시도하며 오류를 내지 않게

function Test-Pg {
    # DB가 접속을 받는지 (켜는 중이면 아직 아님)
    & (Join-Path $pgBin "pg_isready.exe") -h localhost -p $pgPort -q 2> $null
    return $LASTEXITCODE -eq 0
}

function Test-Url([string]$url) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url | Out-Null; return $true } catch { return $false }
}

function Stop-Tree([int]$procId) {
    # 서버 창(PowerShell)과 그 아래 python · node 프로세스를 한꺼번에 끈다
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { & taskkill.exe /PID $procId /T /F > $null 2> $null }
}

function Stop-Port([int]$port) {
    # 창을 꺼도 남은 서버가 있으면 그 포트를 잡고 있는 프로세스까지 끈다
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Tree $_ }
}

function Find-Browser {
    # 크롬 → 엣지 순. 둘 다 크로뮴이라 같은 옵션을 쓴다
    $appPaths = "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    @((Get-ItemProperty "HKCU:\$appPaths" -ErrorAction SilentlyContinue).'(default)',
      (Get-ItemProperty "HKLM:\$appPaths" -ErrorAction SilentlyContinue).'(default)',
      "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
      "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
      "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
      "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
      "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Get-DemoBrowser {
    # 시연 전용 프로필로 떠 있는 크롬 · 엣지 프로세스
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileDir) }
}

$started = @()   # 이 스크립트가 켠 서버 {창 프로세스, 포트}
$pgStarted = $false   # 이 스크립트가 DB를 켰는지 (켰으면 크롬을 닫을 때 끔)
# DB를 백엔드보다 먼저 켠다. 백엔드는 켜질 때 한 번 DB를 보고 1단계 검색에 쓸지 정함
if ((Test-Path (Join-Path $pgBin "pg_ctl.exe")) -and -not (Test-Pg)) {
    # pg_ctl을 따로 띄워야 이 스크립트가 서버 출력에 묶이지 않음
    Start-Process (Join-Path $pgBin "pg_ctl.exe") -WindowStyle Hidden `
        -ArgumentList "-D", "`"$pgDir\data`"", "-l", "`"$pgDir\pg.log`"", "-o", "`"-p $pgPort`"", "start"
    for ($i = 0; $i -lt 20 -and -not (Test-Pg); $i++) { Start-Sleep -Milliseconds 500 }
    $pgStarted = $true
}
if (-not (Test-Url "http://127.0.0.1:8000/health")) {
    $cmd = "`$host.UI.RawUI.WindowTitle = '에이전트 백엔드 - 크롬을 닫으면 함께 꺼짐'; `$env:PYTHONIOENCODING = 'utf-8'; Set-Location '$root\backend'; .\.venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8000"
    $p = Start-Process powershell -PassThru -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $cmd
    $started += [pscustomobject]@{ Process = $p; Port = 8000 }
}
if (-not (Test-Url "$webUrl/api/health")) {
    $cmd = "`$host.UI.RawUI.WindowTitle = '웹 화면 - 크롬을 닫으면 함께 꺼짐'; Set-Location '$root\web'; npm run dev"
    $p = Start-Process powershell -PassThru -WindowStyle Minimized -ArgumentList "-NoExit", "-Command", $cmd
    $started += [pscustomobject]@{ Process = $p; Port = 3000 }
}

# 웹이 뜰 때까지 최대 90초 기다린다 (백엔드 모델은 화면이 뜬 뒤에도 30초쯤 더 불러옴 - 상단 바에 표시)
for ($i = 0; $i -lt 90; $i++) {
    if (Test-Url "$webUrl/api/health") { break }
    Start-Sleep -Seconds 1
}
if ($NoBrowser) { return }

$browser = Find-Browser
if (-not $browser) {
    # 크롬 · 엣지가 없으면 기본 브라우저로 연다. 이때는 서버 창을 직접 닫아야 꺼짐
    Start-Process $webUrl
    return
}
Start-Process $browser -ArgumentList "--user-data-dir=`"$profileDir`"", "--no-first-run", "--no-default-browser-check", "--new-window", $webUrl
if (-not $started -and -not $pgStarted) { return }   # 이번에 켠 서버가 없으면 기다릴 일도 없음 (서버를 켠 쪽이 끔)

# 시연 창이 뜨기를 기다렸다가 (최대 15초), 그 창이 모두 닫힐 때까지 기다린다
for ($i = 0; $i -lt 30 -and -not (Get-DemoBrowser); $i++) { Start-Sleep -Milliseconds 500 }
while (Get-DemoBrowser) { Start-Sleep -Seconds 2 }

# 크롬을 닫았으니 이 스크립트가 켠 서버만 끈다
foreach ($s in $started) {
    Stop-Tree $s.Process.Id
    Stop-Port $s.Port
}
# DB는 백엔드를 끈 뒤에 끈다 (fast: 접속을 끊고 깨끗하게 내림)
if ($pgStarted) { & (Join-Path $pgBin "pg_ctl.exe") -D "$pgDir\data" stop -m fast *> $null }
