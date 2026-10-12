# DB — 어디에 무엇이 있나

에이전트가 쓰는 DB는 두 곳이다. 검색용 벡터 DB는 클라우드(Neon)에, 판본 비교 실험과 실행 기록은 이 PC의 로컬 PostgreSQL에 있다.

| | 검색용 벡터 DB | 로컬 DB `hdrag` |
|---|---|---|
| 위치 | Neon 클라우드 (프로젝트 `hd-rag`, AWS 미국 동부 오하이오, DB `neondb`) | 이 PC `localhost:5433` (기본 설치 위치 `%USERPROFILE%\dev\localpg`) |
| 버전 | PostgreSQL 18 + pgvector 0.8.6 | PostgreSQL 16 + pgvector 0.8.6 (conda-forge, 관리자 권한 필요 없음) |
| 내용 | 문서 3 · 쪽 938 · 청크 6,698(dense · sparse 벡터) · 리랭커 점수 37,864 (약 66MB) | 판본 비교: 문서 2 · 쪽 495 · 노테이션 후보 1,152 · 개정 기록 93 + 판정 함수 6개 · 뷰. 에이전트 실행 기록 `agent_runs` · `agent_feedback` |
| 쓰는 곳 | `backend/.env`의 `DATABASE_URL`이 있으면 에이전트의 1단계 검색 (없으면 FAISS, 결과 같음) | 실험 노트북 `edition_diff/로컬DB_판본비교.ipynb`, 실행 기록 저장(`LOG_DATABASE_URL`, 기본 이 DB) |
| 채운 곳 | Colab 노트북 `RAG_SQL연동.ipynb` (Drive 캐시에서 적재, 약 6초) | `edition_diff/` 노트북 · `run_experiment.py`, 에이전트 백엔드 |
| 백업 | 덤프 없음. 지워지면 Colab 노트북을 다시 돌려 채운다 | `edition_diff/localdb/hdrag.dump` (판본 비교 부분) |

- 접속 문자열(비밀번호 포함)은 저장소에 넣지 않는다. Neon은 `backend/.env`와 Colab Secrets에만 있다
- 로컬 DB는 인터넷에서 접속할 수 없어서 Colab에서는 쓰지 못한다. 그래서 Colab 실험은 Neon을 쓴다

## 폴더

```
db/
└─ edition_diff/                    판본 비교를 PostgreSQL 안으로 옮기는 실험 (SQL 연동 보고서 8장)
   ├─ 로컬DB_판본비교.ipynb          실험 전체를 셀마다 주석을 달아 재현하는 노트북 (실행 결과 포함)
   ├─ edition_diff.sql               표 · 정규화 함수 · 판정 함수 · 뷰
   ├─ run_experiment.py              ①–⑤ 스크립트판 (노트북과 같은 계산)
   ├─ check_search.py                ⑥ 비교표를 바꿔 끼우고 검색까지 확인
   ├─ kr_edition_diff.py             Part 1의 Python 판본 비교 원본 (파싱 함수를 빌려 씀)
   ├─ final27_per_question.csv       보고서의 문항별 기준 값 (구성 4개 × 37문항)
   ├─ *.csv · *.json                 보고서에 쓴 결과 (노트북 ⑦이 대조함)
   └─ localdb/
      ├─ hdrag.dump                  pg_dump -Fc (복원용)
      ├─ hdrag.sql                   같은 내용의 SQL (읽어 보기용)
      ├─ restore_localdb.ps1         PostgreSQL 설치부터 복원까지 한 번에
      └─ README.md                   DB에 든 것 · 복원 · 켜고 끄기
```

- `hdrag.dump`에는 KR 2022 · 2026판 쪽 본문(과제 원본 텍스트)이 들어 있다
- 덤프는 판본 비교 부분만이다 (2026-10-12 오전). 그 뒤 에이전트가 같은 DB에 만든 실행 기록 표(`agent_runs` · `agent_feedback`)는 백엔드가 처음 기록할 때 저절로 만든다

## 다시 만들기

```powershell
# 1) 로컬 PostgreSQL 설치 + hdrag 복원 (약 1분)
powershell -ExecutionPolicy Bypass -File db\edition_diff\localdb\restore_localdb.ps1
# 2) 실험 재현: 노트북을 db\edition_diff 폴더에서 backend\.venv 커널로 실행 (약 10초, GPU 필요 없음)
#    커널이 처음이면: uv pip install --python backend\.venv ipykernel
#    Part 1 데이터는 백엔드와 같은 곳(data\HD_RAG_Part1 또는 PART1_DIR)에서 읽는다
```

2026-10-12 이 저장소 위치에서 다시 실행: 오류 0, ⑦ 대조 8개 모두 보고서 결과와 같음.
