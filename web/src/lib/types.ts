import type { Rels } from "./metrics";

export type DocId = "KR2022" | "KR2026" | "ABS2025";

export type DocMeta = { label: string; short: string; pages: number; url: string };

export type RunMeta = { key: string; label: string; note: string };

export type TestQuestion = {
  qid: string;
  query: string;
  qtype: string;
  rels: Rels;
  runs: Record<string, string[]>; // runKey → ["KR2026:233", ...] (top-10)
};

// 그래프 노드. 순서대로 진행 표시줄에 그린다.
export const NODES = [
  { id: "analyze", label: "질문 분석" },
  { id: "rewrite", label: "검색어 정리" },
  { id: "retrieve", label: "검색" },
  { id: "diff", label: "판 비교" },
  { id: "grade", label: "근거 판정" },
  { id: "web", label: "웹 검색" },
  { id: "generate", label: "답변 생성" },
  { id: "verify", label: "근거 검증" },
] as const;
export type NodeId = (typeof NODES)[number]["id"];
export type NodeStatus = "pending" | "running" | "done" | "skipped";

// 사용자가 끌 수 있는 노드 (질문 분석·검색·답변 생성은 항상 실행)
export const OPTIONAL_NODES: { id: NodeId; label: string; hint: string }[] = [
  { id: "rewrite", label: "검색어 정리", hint: "선급명·연도 같은 메타 단어를 빼고 영어 검색어를 더함" },
  { id: "diff", label: "판 비교 도구", hint: "KR 2022↔2026 신설·삭제·변경 표를 조회" },
  { id: "grade", label: "근거 판정", hint: "가져온 페이지로 답할 수 있는지 판단, 부족하면 재검색" },
  { id: "web", label: "웹 검색 (Tavily)", hint: "문서에 근거가 없을 때만 사용, 답변에서 따로 표시" },
  { id: "verify", label: "근거 검증", hint: "답변 문장을 인용 페이지와 대조" },
];
export type NodeToggles = Partial<Record<NodeId, boolean>>;

export type VerifyStatus = "supported" | "inferred" | "unsupported";

export type Sentence = {
  text: string;
  cites: string[]; // "KR2026:233" 또는 "tool:edition-diff"
  status?: VerifyStatus;
  note?: string;
};

export type Attachment = { name: string; size: number; kind: "pdf" | "csv" | "other" };

export type AskRequest = {
  question: string;
  qid?: string;
  filters: DocId[];
  nodes: NodeToggles;
  attachments: Attachment[];
};

// 막지 않는 되묻기: 질문에 선급·연도가 빠졌을 때 한 가정과, 다른 범위로 다시 물을 선택지
export type ClarifyOption = { label: string; filters: DocId[] };
export type Clarify = { assumption: string; ask: string; options: ClarifyOption[] };

// 문장 index가 인용한 쪽 page에서 고른 구절 (PDF 강조 · 인용 미리보기)
export type Passage = { index: number; page: string; quote: string };

// 질문 유형별 답 형태: 판 비교 → 변경 표(diff), 선급 비교 → 비교표(compare)
export type TableRow = { cells: string[]; cites?: string[]; status?: VerifyStatus | null; note?: string; badge?: string };
export type AnswerTable = { kind: "diff" | "compare"; title: string; note?: string; columns: string[]; rows: TableRow[] };

// 노테이션 카드 (문서의 표·목록에서 뽑은 엔티티)
export type NotationCard = {
  name: string;
  doc: DocId;
  page: string;
  section: string;
  req: string | null;
  description: string | null;
  refs: string | null;
  source: string;
};

export type NotFound = { reason: string; nearest: string[] };

// /api/ask 가 SSE로 보내는 이벤트
export type AskEvent =
  | { type: "meta"; sample: boolean; qid: string | null; run_id?: string }
  | ({ type: "clarify" } & Clarify)
  | { type: "passages"; items: Passage[] }
  | { type: "table"; table: AnswerTable }
  | { type: "cards"; cards: NotationCard[] }
  | ({ type: "not_found" } & NotFound)
  | { type: "node"; id: NodeId; status: NodeStatus; detail?: string }
  | { type: "pages"; runs: Record<string, string[]>; rels: Rels | null; defaultRun: string; runMeta?: RunMeta[] }
  | { type: "sentence"; index: number; delta: string }
  | { type: "cites"; index: number; cites: string[] }
  | { type: "verify"; results: { index: number; status: VerifyStatus; note?: string }[] }
  | { type: "web"; results: WebResult[] }
  | { type: "answer_reset" } // 근거 검증에서 걸려 답변을 다시 만들 때
  | { type: "notice"; message: string }
  | { type: "error"; message: string }
  | { type: "done"; elapsed?: number };

export type WebResult = { id: string; title: string; url: string };

export type Health = {
  ok: boolean;
  ready?: boolean;
  models?: string;
  groq?: boolean;
  tavily?: boolean;
  model?: string;
  device?: string;
  vector_db?: { name: string; note: string; sql_calls?: number; sql_ms_avg?: number | null; fallback_calls?: number };
  logs?: string; // 실행 기록·피드백 저장소: "postgres" | "jsonl"
};

export const FEEDBACK_REASONS = ["답이 틀림", "근거 페이지가 틀림", "답이 부족함", "질문을 잘못 이해함", "너무 느림"] as const;

export const TOOL_LABELS: Record<string, string> = {
  "tool:edition-diff": "판 비교표",
};

export function parsePageId(id: string): { doc: DocId; page: number } | null {
  const m = id.match(/^(KR2022|KR2026|ABS2025):(\d+)$/);
  return m ? { doc: m[1] as DocId, page: Number(m[2]) } : null;
}
