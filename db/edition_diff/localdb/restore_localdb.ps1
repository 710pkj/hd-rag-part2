<#
로컬 PostgreSQL 복원 (판본 비교 실험 DB hdrag, SQL 연동 보고서 8장)
  powershell -ExecutionPolicy Bypass -File restore_localdb.ps1 [-Dir C:\Users\<나>\dev\localpg] [-Port 5433]
1) micromamba를 받아 conda-forge postgresql=16 · pgvector=0.8.6 설치 (관리자 권한 불필요, 약 400MB)
2) 데이터 폴더를 만들고 (initdb: locale C, UTF8, 이 PC에서만 접속·비밀번호 없음) 서버를 켬
3) hdrag DB를 만들고 hdrag.dump를 복원한 뒤 표마다 줄 수를 보여 줌
데이터 폴더는 OneDrive · Google Drive 밖에 둔다 (동기화가 실행 중인 DB 파일을 깨뜨릴 수 있음)
#>
param(
    [string]$Dir = (Join-Path $env:USERPROFILE 'dev\localpg'),
    [int]$Port = 5433,
    [string]$Dump = (Join-Path $PSScriptRoot 'hdrag.dump')
)
$ErrorActionPreference = 'Stop'
$full = [IO.Path]::GetFullPath($Dir)
$synced = @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) | Where-Object { $_ -and $full.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }
if ($synced -or $full -match '\\(내 드라이브|My Drive|공유 드라이브|Shared drives)(\\|$)') { throw "데이터 폴더를 동기화 폴더 밖에 두세요: $Dir" }
if (-not (Test-Path $Dump)) { throw "덤프 파일이 없음: $Dump" }
New-Item -ItemType Directory -Force $Dir | Out-Null
$mm = Join-Path $Dir 'micromamba.exe'
$envDir = Join-Path $Dir 'env'
$bin = Join-Path $envDir 'Library\bin'
$data = Join-Path $Dir 'data'
$pgArgs = @('-h', 'localhost', '-p', $Port, '-U', 'postgres')

# 1) PostgreSQL 16 + pgvector 설치 (이미 있으면 건너뜀)
if (-not (Test-Path (Join-Path $bin 'pg_ctl.exe'))) {
    if (-not (Test-Path $mm)) {
        Write-Host 'micromamba 받는 중'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest 'https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64' -OutFile $mm -UseBasicParsing
    }
    $env:MAMBA_ROOT_PREFIX = Join-Path $Dir 'mroot'
    for ($try = 1; $try -le 2; $try++) {   # 패키지 목록을 받다가 끊기는 일이 있어 한 번 더 시도함
        Write-Host "PostgreSQL 16 + pgvector 0.8.6 설치 중 (시도 $try)"
        & $mm create -y -p $envDir -c conda-forge postgresql=16 pgvector=0.8.6
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) { throw 'micromamba 설치 실패. 인터넷 연결을 확인하고 다시 실행' }
}

# 2) 데이터 폴더 만들기 (이미 있으면 건너뜀) → 서버 켜기
if (-not (Test-Path (Join-Path $data 'PG_VERSION'))) {
    & (Join-Path $bin 'initdb.exe') -D $data -U postgres -A trust -E UTF8 --locale=C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'initdb 실패' }
}
& (Join-Path $bin 'pg_isready.exe') @pgArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    # pg_ctl을 따로 띄워야 이 창이 서버 출력에 묶이지 않음
    Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') -WindowStyle Hidden `
        -ArgumentList @('-D', "`"$data`"", '-l', "`"$(Join-Path $Dir 'pg.log')`"", '-o', "`"-p $Port`"", 'start')
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        & (Join-Path $bin 'pg_isready.exe') @pgArgs | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) { throw "서버가 켜지지 않음. $(Join-Path $Dir 'pg.log') 확인" }
}

# 3) hdrag 복원
$psql = Join-Path $bin 'psql.exe'
$exists = & $psql @pgArgs -At -c "SELECT 1 FROM pg_database WHERE datname = 'hdrag'"
if ($exists -eq '1') { throw 'hdrag DB가 이미 있음. 다시 복원하려면 먼저 DROP DATABASE hdrag' }
& $psql @pgArgs -q -c 'CREATE DATABASE hdrag'
& (Join-Path $bin 'pg_restore.exe') @pgArgs -d hdrag --no-owner $Dump
if ($LASTEXITCODE -ne 0) { throw 'pg_restore 실패' }
& $psql @pgArgs -d hdrag -c "SELECT 'documents' AS tbl, count(*) AS n FROM documents UNION ALL SELECT 'pages', count(*) FROM pages UNION ALL SELECT 'notations', count(*) FROM notations UNION ALL SELECT 'edition_changes', count(*) FROM edition_changes UNION ALL SELECT 'section_texts', count(*) FROM section_texts UNION ALL SELECT 'doc_texts', count(*) FROM doc_texts"
Write-Host "완료: host=localhost port=$Port user=postgres dbname=hdrag"
Write-Host "끄기: & '$(Join-Path $bin 'pg_ctl.exe')' -D '$data' stop"
