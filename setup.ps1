# 선급 문서 기술검토 에이전트 — 처음 한 번 설치 (Windows PowerShell)
# 실행: powershell -ExecutionPolicy Bypass -File setup.ps1 [-Torch cpu|xpu|cuda] [-Shortcut]
#   -Torch xpu  : Intel Arc GPU (Core Ultra 노트북 등). 리랭커가 CPU보다 약 30배 빠름
#   -Torch cuda : NVIDIA GPU
#   -Torch cpu  : GPU 없음 (기본값). test 질문은 캐시로 바로 나오지만 새 질문은 1~2분 걸림
#   -Shortcut   : 바탕화면에도 "선급 에이전트 시연" 아이콘을 만듦 (저장소 맨 위의 바로 가기는 항상 이 PC 경로로 다시 만듦)
param(
    [ValidateSet("cpu", "xpu", "cuda")][string]$Torch = "cpu",
    [switch]$Shortcut
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Run([string]$exe, [string[]]$argList) {
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argList -join ' ') 실패 (종료 코드 $LASTEXITCODE)" }
}

Step "1/5 필요한 프로그램 확인"
foreach ($t in "node", "npm", "uv") {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        throw "$t 가 없습니다. Node.js(https://nodejs.org, 24 이상)와 uv(https://docs.astral.sh/uv/)를 설치한 뒤 다시 실행하세요"
    }
}
Write-Host "node $(node -v) · uv $((uv --version) -replace 'uv ','')"

Step "2/5 데이터 확인"
$envFile = Join-Path $root "backend\.env"
$part1 = $env:PART1_DIR
if (-not $part1 -and (Test-Path $envFile)) {
    $line = Select-String -Path $envFile -Pattern '^PART1_DIR=(.+)$' | Select-Object -First 1
    if ($line) { $part1 = $line.Matches[0].Groups[1].Value.Trim() }
}
if (-not $part1) { $part1 = Join-Path $root "data\HD_RAG_Part1" }
$pdf = if ($env:DOCS_DIR) { $env:DOCS_DIR } else { Join-Path $root "data\pdf" }
if (-not (Test-Path (Join-Path $part1 "test_set.csv"))) {
    throw "Part 1 제출 폴더가 없습니다: $part1`n  → 팀 Drive의 HD_RAG_Part1 폴더(제출 압축을 푼 것)를 data\HD_RAG_Part1 에 두세요"
}
foreach ($f in "KR Notation Guide 2022.pdf", "KR Notation Guide_2026.pdf", "ABS Notations and Symbols 2025.pdf") {
    if (-not (Test-Path (Join-Path $pdf $f))) { throw "원본 PDF가 없습니다: $pdf\$f`n  → 과제 원본 PDF 3개를 data\pdf 에 두세요" }
}
Write-Host "Part 1 폴더: $part1"
Write-Host "PDF 폴더:    $pdf"

Step "3/5 백엔드 (Python 3.13 가상환경 · 패키지 · PyTorch $Torch)"
Push-Location (Join-Path $root "backend")
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) { Run "uv" @("venv", "--python", "3.13", ".venv") }
    Run "uv" @("pip", "install", "--python", ".venv", "-r", "requirements.txt")
    $index = @{ xpu = "https://download.pytorch.org/whl/xpu"; cuda = "https://download.pytorch.org/whl/cu126" }[$Torch]
    if ($index) { Run "uv" @("pip", "install", "--python", ".venv", "--reinstall-package", "torch", "torch", "--index-url", $index) }
    if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "backend\.env 를 만들었습니다 (키는 비어 있음)" }
    & .\.venv\Scripts\python -c "import torch; d = 'xpu' if hasattr(torch, 'xpu') and torch.xpu.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'; print('PyTorch', torch.__version__, '| 장치', d)"
} finally { Pop-Location }

Step "4/5 웹 (npm 패키지 · pdf.js · 원본 PDF · Part 1 결과)"
Push-Location (Join-Path $root "web")
try {
    Run "npm" @("install", "--no-audit", "--no-fund")
    $env:PART1_DIR = $part1
    $env:DOCS_DIR = $pdf
    Run "npm" @("run", "prepare-data")
} finally { Pop-Location }

Step "5/5 마무리"
function New-DemoShortcut([string]$lnk) {
    # start-demo.ps1을 숨은 PowerShell로 실행하는 바로 가기 (바로 가기는 절대 경로만 담을 수 있어서 PC마다 다시 만든다)
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\start-demo.ps1`""
    $s.WorkingDirectory = $root
    $s.IconLocation = "$root\assets\agent.ico,0"
    $s.WindowStyle = 7
    $s.Save()
}
# 저장소 맨 위의 바로 가기는 만든 사람 PC의 경로가 들어 있으므로, 이 PC의 경로로 다시 만든다
New-DemoShortcut (Join-Path $root "선급 에이전트 시연.lnk")
Write-Host "바로 가기: $root\선급 에이전트 시연.lnk"
if ($Shortcut) {
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "선급 에이전트 시연.lnk"
    New-DemoShortcut $lnk
    Write-Host "바탕화면 아이콘: $lnk"
}
$key = Select-String -Path $envFile -Pattern '^GROQ_API_KEY=\s*\S' -Quiet
if (-not $key) { Write-Host "`n※ backend\.env 의 GROQ_API_KEY= 뒤에 Groq 키를 넣어야 답변이 만들어집니다 (https://console.groq.com/keys)" -ForegroundColor Yellow }
Write-Host "`n설치 끝. 실행: '선급 에이전트 시연' 바로 가기 (또는 start-demo.ps1). 크롬 창을 닫으면 서버도 함께 꺼집니다. 첫 질문 때 모델(약 4.4GB)을 내려받습니다." -ForegroundColor Green
