# 선급 문서 기술검토 에이전트 (DT인력양성과정 Part 2)

선급 노테이션 문서(KR 2022·2026, ABS 2025, 938쪽)에 대해 질문하면,
LangGraph 에이전트가 Part 1 검색기로 근거 페이지를 찾아 출처를 붙여 답하고 문장마다 근거를 검증하는 웹 시연입니다.

- `backend/` — Python FastAPI + LangGraph. Part 1 보고서의 최종 통합 검색 구성(E27 포함, test nDCG@10 0.988)을 그대로 씀
- `web/` — Next.js 화면. 대화, 근거 페이지 스택(원본 PDF), 검색 평가(test 질문이면 4개 지표와 정답 순위)
- `setup.ps1` 설치 · `start-demo.ps1` 실행 · `assets/` 아이콘

## 준비물

| 항목 | 내용 |
|---|---|
| OS | Windows 10/11 (PowerShell) |
| 프로그램 | Node.js 24 이상, uv (Python은 uv가 3.13을 받아 씀) |
| 데이터 | `data/HD_RAG_Part1/` = Part 1 제출 폴더(압축을 푼 것: pkl 3개, csv, `cache/`, `outputs/`) · `data/pdf/` = 과제 원본 PDF 3개 |
| API 키 | Groq(필수, 무료) · Tavily(선택, 웹 검색) |
| 벡터 DB | 선택. `backend.env`에 Neon `DATABASE_URL`이 있으면 Neon(PostgreSQL + pgvector), 없으면 FAISS(메모리). 결과는 같음 |
| 디스크 | 약 10GB (모델 4.4GB, PyTorch 1–3GB, 패키지) |
| GPU | 없어도 됨. Intel Arc(xpu) 또는 NVIDIA(cuda)가 있으면 새 질문이 수 초 안에 끝남 |

## 설치 (처음 한 번)

```powershell
git clone https://github.com/710pkj/hd-rag-part2.git      # 또는 공유받은 zip을 풀기
cd hd-rag-part2
powershell -ExecutionPolicy Bypass -File setup.ps1 -Torch cpu -Shortcut   # Intel Arc면 -Torch xpu, NVIDIA면 -Torch cuda
notepad backend\.env                                                       # GROQ_API_KEY= 뒤에 키 붙여 넣기
```

## 실행

바탕화면 **선급 에이전트 시연** 아이콘을 누르거나 `start-demo.ps1`을 실행합니다.
백엔드(8000)와 웹(3000)이 최소화 창으로 켜지고 브라우저(http://localhost:3000)가 열립니다.
끌 때는 작업 표시줄의 두 창을 닫습니다. 자세한 내용은 `backend/README.md`, `web/README.md`.

## 확인

```powershell
cd backend
.\.venv\Scripts\python tests\check_final27.py <final27_per_question.csv 경로>   # 보고서 네 구성 37문항 일치
.\.venv\Scripts\python tests\check_part1.py ..\web\src\data\part1.json         # test 10문항 top-10 일치
.\.venv\Scripts\python tests\test_graph_fake.py                                 # 그래프 분기 (가짜 LLM)
```
