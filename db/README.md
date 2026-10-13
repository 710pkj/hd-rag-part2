# DB — 어디에 무엇이 있나

에이전트가 쓰는 DB는 이 PC의 로컬 PostgreSQL 서버 하나(`localhost:5433`)에 두 개 있다. 검색용 `hdsearch`와 판본 비교 실험 · 실행 기록용 `hdrag`다.
클라우드 Neon에는 `hdsearch`와 같은 내용이 있고, 로컬 DB에 접속할 수 없는 Colab 실험이 쓴다. 2026-10-13에 에이전트의 1단계 검색을 Neon에서 로컬 `hdsearch`로 옮겼다.

| | 검색용 `hdsearch` (로컬) | 판본 비교 · 기록 `hdrag` (로컬) | 검색용 사본 (Neon) |
|---|---|---|---|
| 위치 | 이 PC `localhost:5433` (기본 설치 위치 `%USERPROFILE%\dev\localpg`) | 같은 서버 | Neon 클라우드 (프로젝트 `hd-rag`, AWS 미국 동부 오하이오, DB `neondb`) |
| 버전 | PostgreSQL 16 + pgvector 0.8.6 (conda-forge, 관리자 권한 필요 없음) | 같은 서버 (확장은 `fuzzystrmatch` · `pg_trgm`) | PostgreSQL 18 + pgvector 0.8.6 |
| 내용 | 문서 3 · 쪽 938 · 청크 6,698(dense · sparse 벡터) · 리랭커 점수 37,864 (66MB) | 판본 비교: 문서 2 · 쪽 495 · 노테이션 후보 1,152 · 개정 기록 93 + 판정 함수 6개 · 뷰. 에이전트 실행 기록 `agent_runs` · `agent_feedback` | `hdsearch`와 같음 (표 내용 해시 7/7 같음) |
| 쓰는 곳 | 에이전트의 1단계 검색 (`backend/.env`의 `DATABASE_URL`) | 실험 노트북 `edition_diff/로컬DB_판본비교.ipynb`, 실행 기록 저장(`LOG_DATABASE_URL`, 기본 이 DB) | Colab 실험 `RAG_SQL연동.ipynb`. `DATABASE_URL`을 바꾸면 에이전트도 씀 |
| 채우는 법 | `search/load_search_db.py`: Part 1 캐시에서 몇 초 (모델 호출 없음) | `edition_diff/localdb/hdrag.dump` 복원. 실행 기록 표는 백엔드가 만듦 | Colab 노트북 `RAG_SQL연동.ipynb`: Drive 캐시에서 약 6초 |
| 백업 | 덤프 없음. 캐시에서 다시 채움 | `edition_diff/localdb/hdrag.dump` (판본 비교 부분) | 덤프 없음. Colab 노트북을 다시 돌려 채움 |

- DB를 둘로 나눈 까닭: 두 쪽 모두 `documents` · `pages` 표가 있는데 칸이 다르다. 판본 비교 쪽 `pages`에는 절 이름(`section`)이, 검색 쪽에는 검색용 본문(`search_text`)이 있고, 판본 비교 쪽은 KR 두 판만 담는다. 한 DB에 넣으면 이름이 부딪친다
- PC를 다시 켜면 서버는 꺼져 있다. 시연 바로 가기(`start-demo.ps1`)가 백엔드보다 먼저 켜고, 크롬을 닫으면 끈다 (이미 켜져 있던 서버는 그대로 둠). 서버가 꺼져 있으면 에이전트는 FAISS(메모리)로 검색하고 기록은 JSONL 파일에 쓴다 (검색 결과는 같음)
- 접속 문자열(비밀번호 포함)은 저장소에 넣지 않는다. Neon 주소는 `backend/.env`와 Colab Secrets에만 있다. 로컬 DB는 이 PC 안에서만 접속을 받아 비밀번호가 없다
- 로컬 DB는 인터넷에서 접속할 수 없어서 Colab에서는 쓰지 못한다. 그래서 Colab 실험은 Neon을 쓴다

## 폴더

```
db/
├─ search/                          검색용 DB hdsearch (에이전트의 1단계 검색)
│  ├─ schema.sql                    Neon과 같은 표 5개 · 제약 · 색인
│  ├─ load_search_db.py             DB를 만들고 Part 1 캐시에서 채움 (다시 돌려도 중복 없음)
│  └─ compare_search_db.py          두 검색 DB(기본: 로컬 · Neon)의 표 내용을 해시로 비교
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

`setup.ps1 -LocalDb`가 1) · 2)를 하고, `backend\.env`의 `DATABASE_URL`이 비어 있으면 로컬 검색 DB 주소를 넣는다.

```powershell
# 1) 로컬 PostgreSQL 설치 + hdrag 복원 (약 1분. 이미 있으면 건너뜀)
powershell -ExecutionPolicy Bypass -File db\edition_diff\localdb\restore_localdb.ps1
# 2) 검색용 DB hdsearch 만들고 채우기 (몇 초. Part 1 데이터는 백엔드와 같은 곳에서 읽음)
backend\.venv\Scripts\python db\search\load_search_db.py
#    에이전트가 쓰게 하려면 backend\.env: DATABASE_URL=postgresql://postgres@localhost:5433/hdsearch (백엔드를 다시 켬)
#    확인: cd backend; .\.venv\Scripts\python tests\check_neon.py → 네 구성 37/37, 채널별 후보 50쪽 148/148
#    Neon과 내용 비교: backend\.env에 NEON_DATABASE_URL을 두고 backend\.venv\Scripts\python db\search\compare_search_db.py → 7/7 같음
# 3) 판본 비교 실험 재현: 노트북을 db\edition_diff 폴더에서 backend\.venv 커널로 실행 (약 10초, GPU 필요 없음)
#    커널이 처음이면: uv pip install --python backend\.venv ipykernel
#    Part 1 데이터는 백엔드와 같은 곳(data\HD_RAG_Part1 또는 PART1_DIR)에서 읽는다
```

- 2026-10-12 이 저장소 위치에서 3) 다시 실행: 오류 0, ⑦ 대조 8개 모두 보고서 결과와 같음
- 2026-10-13 2)로 만든 `hdsearch` 확인: Neon과 표 내용 해시 7/7 같음. 네 구성 × 37문항 37/37, 채널별 후보 50쪽 148/148, FAISS 대신 호출 0번. SQL 평균 4.4ms (같은 확인을 Neon으로 하면 204ms)
