# 로컬 PostgreSQL 백업 — 판본 비교 실험 DB `hdrag`

2026-10-11 판본 비교 SQL 실험(SQL 연동 보고서 8장)에 쓴 로컬 PostgreSQL DB를 보관한 폴더임.
처음에는 임시 폴더에 만든 DB라서 덤프로 떠서 보관했고, 지금은 이 덤프를 `restore_localdb.ps1`로 `%USERPROFILE%\dev\localpg`에 복원해 씀.

## 파일

| 파일 | 내용 |
|---|---|
| `hdrag.dump` | `pg_dump -Fc`로 뜬 DB 전체 (복원용, 160 KB) |
| `hdrag.sql` | 같은 내용을 SQL 문장으로 (읽어 보기용, 860 KB) |
| `restore_localdb.ps1` | PostgreSQL 설치부터 복원까지 한 번에 하는 스크립트 |

## DB에 든 것

| 종류 | 이름 | 줄 수 · 내용 |
|---|---|---|
| 표 | `documents` | 2 (KR2022, KR2026) |
| 표 | `pages` | 495 (KR 두 판의 쪽 원문 + Python이 정한 절 이름) |
| 표 | `notations` | 1,152 (노테이션 후보: 판, 절, 이름, 나온 쪽, 요건) |
| 표 | `edition_changes` | 93 (판본 비교 결과, seq 판정 = 기존 Python 결과와 바이트까지 같음) |
| 구체화 뷰 | `section_texts` · `doc_texts` | 92 · 2 (절 본문 · 판 전체 본문) |
| 뷰 | `edition_change_pages` | 쪽 → 개정 종류 (검색에 쓰는 모양) |
| 함수 | `kkey` · `req_key` · `absent_in` · `seq_ratio` · `name_sim` · `edition_diff` | 판본 비교 판정 |
| 확장 | `fuzzystrmatch` · `pg_trgm` | 편집 거리 · 삼중 문자 유사도 |

- **청크와 벡터는 이 DB에 없음.** 에이전트의 1단계 검색은 같은 서버의 검색용 DB `hdsearch`에서 함 (2026-10-13부터, `db/search/`). 표 이름(`documents` · `pages`)이 같고 칸이 달라 DB를 나눔
- 각 표 · 함수의 자세한 설명은 상위 폴더의 `로컬DB_판본비교.ipynb` (이 DB를 처음부터 다시 만들며 실험을 재현하는 노트북)

## 복원 (새 PC · 다른 위치)

```powershell
powershell -ExecutionPolicy Bypass -File restore_localdb.ps1                      # 기본: C:\Users\<나>\dev\localpg, 포트 5433
powershell -ExecutionPolicy Bypass -File restore_localdb.ps1 -Dir D:\pg -Port 5434  # 위치 · 포트를 바꿀 때
```

하는 일
1. micromamba(설치 관리 도구, 11 MB)를 받아 conda-forge의 PostgreSQL 16 + pgvector 0.8.6 설치 (관리자 권한 필요 없음, 약 400 MB)
2. 데이터 폴더를 만들고 서버를 켬 (locale C, UTF8, 이 PC 안에서만 접속 · 비밀번호 없음)
3. `hdrag` DB를 만들고 `hdrag.dump`를 복원한 뒤 표마다 줄 수를 보여 줌 (이미 있으면 복원을 건너뛰고 줄 수만 보여 줌)

- 데이터 폴더는 **OneDrive · Google Drive 밖에** 둠. 동기화가 실행 중인 DB 파일을 깨뜨릴 수 있어서, 스크립트가 동기화 폴더면 멈춤
- 확인 (2026-10-12): 빈 폴더에서 설치 + 복원까지 57초. 복원한 DB와 원본 DB의 함수 6개, 표 · 뷰 7개 내용 해시가 모두 같음

## 접속 · 켜기 · 끄기

- 접속: `host=localhost port=5433 user=postgres dbname=hdrag`
- PC를 다시 켜면 서버는 꺼져 있음. 시연 바로 가기(`start-demo.ps1`)와 노트북의 0-2 셀이 켜 주고, 직접 켤 때는:

```powershell
$pg = "C:\Users\710pk\dev\localpg"
& "$pg\env\Library\bin\pg_ctl.exe" -D "$pg\data" -l "$pg\pg.log" -o "-p 5433" start   # 켜기
& "$pg\env\Library\bin\pg_ctl.exe" -D "$pg\data" stop                                  # 끄기
```
