# 선급 문서 기술검토 에이전트 — 웹 시연 (Part 2)

Next.js(Node.js) 화면. 질문을 넣으면 그래프 진행 상황, 답변, 근거 페이지 스택, 검색 평가가 나온다.
`/api/ask`는 질문을 에이전트 백엔드(`../backend`, FastAPI + LangGraph, 기본 http://127.0.0.1:8000)로 넘긴다.
백엔드가 꺼져 있으면 **샘플 모드**로 답한다 (테스트 질문 10개는 Part 1 검색 결과와 샘플 답변, 그 밖에는 안내).
백엔드 주소는 환경변수 `AGENT_BACKEND_URL`로 바꾼다. 둘 다 한 번에 띄우려면 상위 폴더의 `start-demo.ps1`.

## 실행

```powershell
cd C:\Users\710pk\dev\hd-rag-part2\web
npm install          # 처음 한 번
npm run prepare-data # 처음 한 번: pdf.js·원본 PDF를 public/에 복사, Part 1 결과를 src/data/part1.json으로
npm run dev          # http://localhost:3000
```

`prepare-data`는 기본으로 `HD융캡디/제출/HD_RAG_Part1`과 `HD융캡디/02_원본문서`를 읽는다.
폴더를 옮겼으면 `PART1_DIR`, `DOCS_DIR` 환경변수로 경로를 준다.
`npm run check-metrics`는 웹의 지표 계산이 Part 1 노트북 값과 같은지 확인한다 (10문항 모두 일치, 평균 nDCG@10 E9 0.8230 · 최종 0.9743).

## 화면

| 영역 | 내용 |
|---|---|
| 왼쪽 대화 | 질문, 노드 진행 표시(눌러서 노드별 입출력 보기), 답변. 문장마다 인용 칩과 근거 검증 표시(✓ 확인 · ~ 추론 · ! 근거 없음) |
| 왼쪽 아래 프롬프트창 | 질문 입력, 파일 첨부(PDF·CSV, 끌어다 놓기 가능), 검색할 문서 고르기 |
| 가운데 근거 페이지 | 원본 PDF 페이지를 A4 용지처럼 겹쳐 쌓음. 스크롤하는 만큼 앞 장이 들려 나가고 뒤 장이 앞으로 나옴, 손을 떼면 가장 가까운 장에 맞춤. 스크롤바를 끌거나 ↑↓로도 넘김, 뒤 장의 윗단을 누르면 그 장으로, 앞 장을 누르면 크게 보기 |
| 오른쪽 검색 평가 | 정답이 있는 질문만. P@10(최대 가능값 표시) · R@10 · MRR@10 · nDCG@10, 정답 페이지 순위, top-10 순위표. E9 기준 구성과 최종 통합을 바꿔 볼 수 있음 |
| 상단 | 테스트 질문 고르기, 노드 설정(검색어 정리·판 비교·근거 판정·웹 검색·근거 검증 끄고 켜기), 새 대화 |

스택은 velog "React Card Stack" 글처럼 스크롤 위치를 카드 위치로 바꾸고, 휠 한 번에 한 장씩 스냅한다.
- 스택 영역은 진짜 스크롤 상자다. 한 장당 160px 스크롤을 두고(`pos = scrollTop / STEP`) 매 프레임 각 장의 위치·크기·불투명도를 계산한다. 오른쪽에 스크롤바가 생긴다.
- 휠·↑↓·순위 클릭은 직접 만든 애니메이션(0.42초, 감속)으로 다음 장까지 스크롤한다. 넘기는 중에 또 굴리면 목표만 한 장 더 늘린다 (0.26초 간격 제한).
- 스크롤바를 끌거나 터치로 밀면 기본 스크롤이 되고, 손을 떼면 CSS scroll-snap이 가장 가까운 장에 맞춘다.
- 브라우저 smooth 스크롤을 쓰지 않는 이유: 이 PC처럼 Windows "애니메이션 효과"가 꺼져 있으면 Chrome이 `prefers-reduced-motion`으로 보고 smooth 스크롤을 순간이동으로 바꾼다.
- 뒤 장일수록 위로 8px씩 비켜나고 조금 작아지며 불투명도가 낮아진다. 넘기는 장은 불투명한 채로 들려 나가다 끝에서 사라진다.
- 값은 `src/components/PageStack.tsx` 맨 위 상수(STEP, GAP, SHRINK, MAX_BEHIND, ANIM_MS, WHEEL_GAP_MS)에서 바꾼다.

## 구조

```
src/app/api/ask/route.ts   질문 → 백엔드 SSE 프록시 (meta·node·pages·sentence·cites·verify·web·answer_reset·notice·done), 백엔드가 꺼져 있으면 샘플 응답
src/data/part1.json        test 10문항의 정답과 Part 1 top-10 (prepare-data가 생성)
src/data/samples.ts        샘플 답변. 정답 페이지 원문과 판 비교표에서 확인한 문장만 씀
src/lib/metrics.ts         지표 계산 (Part 1과 같은 정의, nDCG는 관련도 등급을 이득으로)
src/lib/pdf.ts             pdf.js로 원본 PDF 페이지를 이미지로 렌더링해 캐시
src/components/            App · Turn · Composer · TopBar · StackPanel · PageStack · EvalPanel · Lightbox
```

## 백엔드 연결

`src/app/api/ask/route.ts`는 백엔드 SSE를 그대로 넘기는 프록시이고, 연결이 안 되면 샘플 응답(같은 파일)으로 바꾼다.
`src/app/api/health/route.ts`는 상단 바의 연결 상태(GPU·Groq·웹 검색)를 10초마다 확인한다.
이벤트 형식은 `src/lib/types.ts`의 `AskEvent` (백엔드 `agent/graph.py`와 같음).
첨부 파일은 지금 이름과 크기만 넘기고 처리하지 않는다.
