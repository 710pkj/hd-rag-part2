# 선급 문서 기술검토 에이전트 (DT인력양성과정 Part 2)

선급 노테이션 문서(KR 2022·2026, ABS 2025, 938쪽)에 대해 질문하면,
LangGraph 에이전트가 Part 1 검색기로 근거 페이지를 찾아 출처를 붙여 답하고 문장마다 근거를 검증하는 웹 시연입니다.

- `backend/` — Python FastAPI + LangGraph. Part 1 보고서의 최종 통합 검색 구성(E27 포함, test nDCG@10 0.988)을 그대로 씀
- `web/` — Next.js 화면. 대화, 근거 페이지 스택(원본 PDF, 인용 구절을 노랗게 표시), 질문 유형별 답 형태(변경 표 · 비교표 · 노테이션 카드), 가정 · 되묻기, 👍👎 피드백, 개발자 모드의 검색 평가(test 질문이면 4개 지표와 정답 순위)
- `setup.ps1` 설치 · `선급 에이전트 시연.lnk`(= `start-demo.ps1`) 실행 · `assets/` 아이콘
- `docs/AGENT.md` — 에이전트 구성: 노드 흐름과 노드별 방법론
- `docs/설계_노션_DB_에이전트.md` — 설계 결정 기록: 검색 방법 · DB · 에이전트 · 노션에서 무엇을 채택하고 무엇을 채택하지 않았는지, 그 근거와 이유 (2026-10-13). 안의 Drive · 로컬 경로는 작업 PC 기준
- `db/` — DB가 어디에 무엇이 있는지, 로컬 DB 덤프(판본 비교 실험)와 재현 노트북

## 준비물

| 항목 | 내용 |
|---|---|
| OS | Windows 10/11 (PowerShell) |
| 프로그램 | Node.js 24 이상, uv (Python은 uv가 3.13을 받아 씀) |
| 데이터 | `data/HD_RAG_Part1/` = Part 1 제출 폴더(압축을 푼 것: pkl 3개, csv, `cache/`, `outputs/`) · `data/pdf/` = 과제 원본 PDF 3개 |
| API 키 | Groq(필수, 무료) · Tavily(선택, 웹 검색) |
| 벡터 DB | 선택. `setup.ps1 -LocalDb`면 이 PC에 PostgreSQL 16 + pgvector를 설치하고(관리자 권한 필요 없음) 검색용 DB `hdsearch`를 채워 1단계 검색을 거기서 함. `backend\.env`의 `DATABASE_URL`에 Neon 주소를 넣으면 Neon에서, 비어 있으면 FAISS(메모리)에서. 결과는 셋 다 같음 |
| 기록 DB | 선택. 질문 · 답변 실행 기록과 피드백을 같은 로컬 PostgreSQL의 `hdrag`(`LOG_DATABASE_URL`로 바꿈)에 저장. 없으면 `backend/cache_runtime/logs/`의 JSONL 파일 |
| 디스크 | 약 10GB (모델 4.4GB, PyTorch 1–3GB, 패키지) |
| GPU | 없어도 됨. Intel Arc(xpu) 또는 NVIDIA(cuda)가 있으면 새 질문이 수 초 안에 끝남 |

## 설치 (처음 한 번)

```powershell
git clone https://github.com/710pkj/hd-rag-part2.git      # 또는 공유받은 zip을 풀기
cd hd-rag-part2
powershell -ExecutionPolicy Bypass -File setup.ps1 -Torch cpu -Shortcut   # Intel Arc면 -Torch xpu, NVIDIA면 -Torch cuda
                                                                           # 로컬 DB까지 쓰려면 끝에 -LocalDb (약 1분 더, 400MB)
notepad backend\.env                                                       # GROQ_API_KEY= 뒤에 키 붙여 넣기
```

## 실행

저장소 맨 위의 **선급 에이전트 시연** 바로 가기(또는 바탕화면 아이콘)를 더블클릭합니다. 한 번에 다음이 실행됩니다.

1. 꺼져 있는 서버만 켬: 로컬 DB(5433, 설치돼 있으면 백엔드보다 먼저, 창 없이) → 백엔드(8000) · 웹(3000)이 최소화 창으로
2. 웹이 뜨면 시연용 크롬 창(http://localhost:3000)을 엶. 평소 쓰는 크롬과 따로 된 프로필(`%LOCALAPPDATA%\hd-rag-demo\browser`)이라 로그인 · 확장 프로그램은 없음
3. **크롬 창을 닫으면** 이번에 켠 서버 창(에이전트 백엔드 · 웹 화면)과 DB, 실행한 PowerShell이 함께 꺼짐. 이미 켜져 있던 서버 · DB는 건드리지 않음

- 바로 가기에는 절대 경로만 들어가서, 저장소의 바로 가기는 만든 사람 PC 경로로 되어 있습니다. `setup.ps1`이 이 PC 경로로 다시 만듭니다 (`-Shortcut`이면 바탕화면에도)
- 크롬이 없으면 엣지를, 둘 다 없으면 기본 브라우저를 엽니다. 기본 브라우저일 때는 서버 창을 직접 닫아야 꺼집니다
- 서버만 켜려면 `start-demo.ps1 -NoBrowser`. 자세한 내용은 `backend/README.md`, `web/README.md`

## 확인

```powershell
cd backend
.\.venv\Scripts\python tests\check_final27.py <final27_per_question.csv 경로>   # 보고서 네 구성 37문항 일치
.\.venv\Scripts\python tests\check_neon.py <final27_per_question.csv 경로>     # 같은 확인을 DATABASE_URL의 DB(로컬 · Neon)로 + 채널별 후보 50쪽이 FAISS와 같은지
.\.venv\Scripts\python tests\check_part1.py ..\web\src\data\part1.json         # test 10문항 top-10 일치
.\.venv\Scripts\python tests\test_graph_fake.py                                 # 그래프 분기 (가짜 LLM)
```
