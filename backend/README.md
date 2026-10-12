# 선급 문서 기술검토 에이전트 — 백엔드 (Part 2)

FastAPI + LangGraph. 웹(Next.js)의 `/api/ask`가 이 서버의 `/ask`로 질문을 넘기고, 진행 이벤트를 SSE로 그대로 받는다.

## 실행

```powershell
cd C:\Users\710pk\dev\hd-rag-part2\backend
# 처음 한 번: 가상환경과 패키지 (PyTorch는 Intel Arc GPU용 xpu 빌드)
uv venv --python 3.13 .venv
uv pip install --python .venv -r requirements.txt
uv pip install --python .venv --reinstall-package torch torch --index-url https://download.pytorch.org/whl/xpu
# .env에 GROQ_API_KEY(필수), TAVILY_API_KEY(선택) 입력
.\.venv\Scripts\python -m uvicorn server:app --port 8000
```

웹과 함께 띄우려면 바탕화면의 **선급 에이전트 시연** 아이콘(= 상위 폴더 `start-demo.ps1`)을 누른다.
꺼져 있는 서버만 최소화 창으로 켜고 브라우저(http://localhost:3000)를 연다. 이미 켜져 있으면 브라우저만 연다.
끌 때는 작업 표시줄의 두 창(에이전트 백엔드, 웹 화면)을 닫는다. 아이콘은 `assets/make_icon.py`로 만든다.
`.env`는 요청마다 다시 읽으므로 키를 넣은 뒤 서버를 다시 시작하지 않아도 된다.

데이터는 Part 1 제출 폴더(`PART1_DIR`, 기본 `HD융캡디/제출/HD_RAG_Part1`)에서 읽는다: pkl 3개, rules.csv, dev·test 질문, `cache/`, `outputs/kr_edition_diff.csv`.
새 질문에서 계산한 질문 벡터·리랭커 점수·영어 검색 문장은 `cache_runtime/`에 따로 쌓는다 (제출 캐시는 건드리지 않음).

## 그래프

```
질문 분석 → 검색어 정리 → 검색 → 판 비교 → 근거 판정 ─┬→ 답변 생성 → 근거 검증 ─┬→ 끝
                          ▲                       │            ▲            │
                          └──── 재검색(1회) ──────┤            └─ 다시 생성(1회, 근거 없는 문장이 있을 때)
                                                  └→ 웹 검색(문서에 근거가 없을 때) → 답변 생성
```

| 노드 | 하는 일 | 근거 |
|---|---|---|
| 질문 분석 | 선급·연도·의도(판 비교·선급 비교) 판별, dev·test 질문이면 정답 연결 | Part 1 규칙 (`analyze_query`, `query_intent.py`) |
| 검색어 정리 | 메타 단어를 뺀 주제 쿼리 + LLM 영어 검색 문장 | Part 1 E9·E12·E14 (메타 단어가 dense·리랭커를 망침, Q10) |
| 검색 | 도구 `search_documents`: Part 1 보고서의 최종 통합 구성 (선급 비교 병합 E27 포함) | test nDCG@10 0.988 · dev 1.000 구성 그대로 |
| 판 비교 | 도구 `edition_diff`: KR 2022↔2026 개정표에서 상위 쪽의 행 | Part 1 E12-4 개정표 |
| 근거 판정 | LLM이 상위 5쪽으로 답할 수 있는지 판단, 근거 쪽을 고름 | 부족하면 영어 문장·전체 문서로 재검색 1회 |
| 웹 검색 | 도구 `web_search`(Tavily): 문서에 근거가 없을 때만 | 답변에서 `웹 N`으로 따로 표시 |
| 답변 생성 | 근거만으로 답하고 문장마다 출처 id를 붙임 (JSON) | 없는 출처 id는 버림 |
| 근거 검증 | LLM이 문장별로 확인·추론·근거 없음 판정 + 규칙 검사(인용 원문에 없는 노테이션 표기) | 근거 없는 문장이 있으면 피드백을 주고 1회 다시 생성 |

## 사용자에게 보여 주는 형태 (2026-10-12)

최종 답이 정해지면 그래프가 화면용 이벤트를 더 보낸다 (`agent/graph.py`의 `finalize`, 계산은 `agent/present.py`).

| 기능 | 이벤트 | 만드는 법 |
|---|---|---|
| 인용 구절 강조 | `passages` | 문장마다, 인용한 쪽의 청크·문단 중 문장과 가장 비슷한 구절 (BGE-M3 dense + 0.25 × 영문·코드 낱말 겹침). 웹이 pdf.js 글자 층에서 그 줄을 찾아 노랗게 칠함 |
| 질문 유형별 답 형태 | `table` · `cards` | 판 비교 → 판 비교표 행을 그대로 변경 표로 (인용·근거 쪽의 행만) · 질문에 선급이 둘 이상 적힘 → 답변 생성 LLM이 비교표도 만들고 행마다 근거 검증 · 그 밖 → 노테이션 카드 (`rag/entities.py`: 문서 표·목록에서 뽑은 엔티티 표, 실험 E29와 같은 규칙) |
| 찾지 못함 | `not_found` | 재검색 뒤에도 근거 판정이 실패하고 웹 결과도 없으면 지어내지 않고 이유와 가까운 쪽 5개만 안내 |
| 가정 · 되묻기 | `clarify` | 질문에 선급이 없거나(KR·ABS 모두 찾음), KR인데 연도가 없을 때(최신판 우선) 가정을 알리고 다른 범위로 다시 물을 선택지를 줌. 사용자가 문서 범위를 고르면 하지 않음 |
| 실행 기록 · 피드백 | `meta.run_id` · `POST /feedback` | 질문·상위 10쪽·문장·판정·표·카드를 `agent_runs`에, 👍👎·사유를 `agent_feedback`에 (`agent/logstore.py`). 기본은 로컬 PostgreSQL `localhost:5433/hdrag`(`LOG_DATABASE_URL`로 바꿈), 안 되면 `cache_runtime/logs/*.jsonl` |

개발자 모드(검색 평가 칸 · 정답 표시)는 웹에서만 켜고 끈다.

## 확인한 것

- `tests/check_final27.py`: 보고서(노션)의 네 구성(E9 · 미리 정한 후보 · 최종 통합 E27 전 · 최종 통합 +E27)이 실험 노트북 결과 `final27_per_question.csv`와 37문항 모두 일치 (nDCG@10과 정답 쪽 순위, 캐시만으로, 모델 호출 차단)
- `tests/check_part1.py`: 웹 데이터(part1.json)의 test top-10과 10/10 일치 · `tests/export_web_runs.py`: 웹 샘플 모드용 E27 최종 top-10을 `web/src/data/final27.json`으로 내보냄
- 제출 노트북의 최종 통합은 E27 전(test 0.974)이고, 보고서와 에이전트는 E27 포함(0.988)을 씀. E27은 실험 노트북 `RAG_LLM재정렬.ipynb` 셀 53의 `mix_rank`를 그대로 옮김 (`rag/part1.py`의 `society_merge`)
- `tests/test_graph_fake.py`: 가짜 LLM으로 분기 확인 (근거 부족 → 재검색 → 웹 → 생성 → 근거 없음 → 다시 생성)
- 속도 (새 질문, 리랭커 50쌍): CPU 80초 → Intel Arc GPU(xpu, fp16) 2.5–6초. 점수 차 최대 0.011, 순위 같음
- 실제 Groq(openai/gpt-oss-120b)로 test 질문 t04–t10과 새 질문을 돌려 고친 것:
  - 근거 판정이 판 비교 질문에서 개정표를 못 봐서 "근거 부족" → 개정표도 판정에 보여 줌. "목록에 없다"도 답으로 인정
  - 재검색이 다른 선급(ABS)으로 넘어감 → 선급은 유지하고 판 제한만 풂
  - 선급 비교(t10)에서 상위가 ABS로만 차서 KR 근거가 빠짐 → 판정 8쪽, 선급마다 최소 2쪽, 근거 6쪽까지
  - 모델이 문장 안에 "(ABS2025:26)"을 써서 규칙 검사가 노테이션으로 오인 → 문장 안 출처 id를 떼어 인용으로 옮김
  - 다시 생성해도 근거 없는 문장은 답변에서 빼고 안내(notice)를 붙임 / 영어 질문은 영어로 답하게 명시
  - 결과: t04·t05·t06·t07·t08·t09·t10 모두 정답 내용, 근거 검증 통과. 캐시된 질문 3–4초, Groq 사용량 한도에 걸리면 30초 안팎

## 벡터 DB: Neon (PostgreSQL + pgvector)

`.env`에 `DATABASE_URL`이 있으면 1단계 검색(허용 문서 거르기 → 청크 내적 점수 → 쪽별 최고점 → 상위 50쪽)을 Neon의 `chunks` 표에서 SQL 한 문장으로 한다.
없거나 접속이 안 되면 FAISS(메모리)를 쓰고, 검색 중 SQL이 실패하면 그 호출만 FAISS로 대신한다. `VECTOR_DB=faiss`로 FAISS에 고정할 수 있다.

- `rag/pg_index.py` = Colab `RAG_SQL연동.ipynb` 셀 25의 `PgIndex` 그대로 + 끊기면 다시 접속(Neon은 5분 쉬면 절전). `search_v2`·E27·리랭커는 고치지 않음
- DB 내용(문서 3 · 쪽 938 · 청크 6,698 · 리랭커 점수 37,864)은 Colab에서 적재한 것을 그대로 읽음. 서버를 켤 때 청크 수가 FAISS와 다르면 FAISS를 씀
- `tests/check_neon.py`: Neon 경로로 보고서 네 구성 × 37문항 37/37 일치(E27 포함 구성은 SQL 경로로 처음 확인), 채널별 후보 50쪽 148/148 같음, FAISS 대신 호출 0번
- 속도: 한국 → Neon(AWS Ohio) SQL 한 번 약 0.2초, 질문당 1–2번(한국어로만 된 질문은 sparse가 비어 1번). 5분 넘게 쉬면 첫 SQL 1–2초
- 화면 상단 바에 "벡터 DB Neon / FAISS", 검색 노드 설명에 "1단계 검색 Neon SQL n번 t초"가 나옴
- 리랭커 점수 캐시는 아직 pkl에서 읽음 (DB `rerank_scores`에 사본 있음)

## Groq 무료 한도

`openai/gpt-oss-120b`는 하루 20만 토큰이 한도다. 한도에 걸리면 `GROQ_FALLBACK_MODELS`(기본 `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`)로 넘어가고, 노드 설명에 "대체 모델 …"이 붙는다.
영어 검색 문장(LLM)은 한도에 걸리면 기다리지 않고 한국어 검색어로만 검색한다.
