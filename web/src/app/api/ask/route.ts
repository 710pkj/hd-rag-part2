// 질문 → 그래프 진행 상황·근거 페이지·답변을 SSE로 흘려보낸다.
// Python 백엔드(FastAPI + LangGraph, AGENT_BACKEND_URL)로 그대로 넘기고, 백엔드가 꺼져 있으면 샘플 모드로 답한다.
// 샘플 모드: 테스트 질문이면 Part 1 검색 결과와 샘플 답변을, 아니면 "백엔드 연결 전" 안내를 보낸다.
import { PART1 } from "@/data/part1";
import { QTYPE_LABELS, SAMPLES } from "@/data/samples";
import type { AskEvent, AskRequest, NodeId, Sentence, TestQuestion, VerifyStatus } from "@/lib/types";

const QUESTIONS = PART1.questions;
const DOC_SHORT: Record<string, string> = Object.fromEntries(Object.entries(PART1.docs).map(([id, d]) => [id, d.short]));

const norm = (s: string) => s.toLowerCase().replace(/[\s,.?!·"'()]/g, "");

function findQuestion(req: AskRequest): TestQuestion | null {
  if (req.qid) return QUESTIONS.find((q) => q.qid === req.qid) ?? null;
  const n = norm(req.question);
  return QUESTIONS.find((q) => norm(q.query) === n) ?? null;
}

// Part 1에서 배운 것: 선급명·"선급 기준"·연도 같은 메타 단어가 dense·리랭커 질의를 망친다 (Q10).
function stripMeta(question: string): { query: string; removed: string[] } {
  const removed: string[] = [];
  const take = (re: RegExp) => (s: string) => s.replace(re, (m) => (removed.push(m.trim().replace(/,$/, "")), " "));
  if (/^[\x00-\x7F]*$/.test(question)) return { query: question, removed }; // 영어 질문은 그대로 (Part 1 Q9 교훈)
  let s = take(/(KR|ABS)\s*(과|와|및)?\s*(KR|ABS)?\s*선급\s*기준\s*(으로|에서|의)?\s*,?/gi)(question);
  s = take(/20\d\d\s*년\s*도?\s*(에|과|와|의)?/g)(s);
  return { query: s.replace(/\s+/g, " ").trim(), removed };
}

function analyzeDetail(req: AskRequest, q: TestQuestion | null): string {
  const text = req.question;
  const soc = [/\bKR\b|KR\s*선급|KR과/.test(text) && "KR", /ABS/.test(text) && "ABS"].filter(Boolean).join("+") || "미지정";
  const years = text.match(/20\d\d/g);
  const parts = [`선급 ${soc}`, `연도 ${years ? [...new Set(years)].join("·") : "없음 → 최신판 우선"}`];
  if (q) parts.push(`유형 ${QTYPE_LABELS[q.qtype] ?? q.qtype}`);
  parts.push(req.filters.length ? `문서 범위 지정: ${req.filters.map((d) => DOC_SHORT[d]).join(", ")}` : "문서 범위 자동");
  if (req.attachments.length) parts.push(`첨부 ${req.attachments.length}개 (백엔드 연결 후 처리)`);
  return parts.join(" · ");
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(t), reject(new Error("aborted"))), { once: true });
  });

async function run(send: (e: AskEvent) => void, req: AskRequest, q: TestQuestion | null, signal: AbortSignal) {
  const on = (id: NodeId) => req.nodes[id] !== false;
  const step = async (id: NodeId, ms: number, detail: string) => {
    send({ type: "node", id, status: "running" });
    await sleep(ms, signal);
    send({ type: "node", id, status: "done", detail });
  };
  const skip = (id: NodeId, detail: string) => send({ type: "node", id, status: "skipped", detail });
  const sample = q ? SAMPLES[q.qid] : null;

  send({ type: "meta", sample: !!q, qid: q?.qid ?? null });
  await step("analyze", 450, analyzeDetail(req, q));

  if (on("rewrite")) {
    const { query, removed } = stripMeta(req.question);
    await step("rewrite", 550, removed.length ? `“${query}” (뺀 말: ${removed.join(", ")})` : `“${query}” (뺄 메타 단어 없음)`);
  } else skip("rewrite", "꺼짐: 원 질문 그대로 검색");

  if (!q || !sample) {
    await step("retrieve", 500, "백엔드 연결 전이라 검색하지 않음");
    for (const id of ["diff", "grade", "web"] as NodeId[]) skip(id, "백엔드 연결 전");
    const lines: Sentence[] = [
      { text: "아직 에이전트 백엔드가 연결되지 않았습니다.", cites: [] },
      { text: "지금은 테스트 질문 10개에 대해 Part 1 검색 결과와 샘플 답변으로 화면을 시연합니다.", cites: [] },
    ];
    send({ type: "node", id: "generate", status: "running" });
    await streamSentences(send, lines, signal);
    send({ type: "node", id: "generate", status: "done", detail: "안내 문구" });
    skip("verify", "인용이 없음");
    return;
  }

  const counts: Record<string, number> = {};
  for (const id of q.runs.final) counts[id.split(":")[0]] = (counts[id.split(":")[0]] ?? 0) + 1;
  await step("retrieve", 900, `top-10: ${Object.entries(counts).map(([d, n]) => `${DOC_SHORT[d]} ${n}쪽`).join(", ")} (Part 1 최종 통합 결과)`);
  send({ type: "pages", runs: q.runs, rels: q.rels, defaultRun: "final" });

  if (!sample.diff) skip("diff", "판 비교 질문이 아님");
  else if (on("diff")) await step("diff", 600, sample.diff);
  else skip("diff", "꺼짐");

  if (on("grade")) await step("grade", 500, "상위 페이지로 답할 수 있음 → 재검색 불필요 (샘플)");
  else skip("grade", "꺼짐");
  skip("web", on("web") ? "문서 근거가 충분해 호출하지 않음" : "꺼짐");

  send({ type: "node", id: "generate", status: "running" });
  await streamSentences(send, sample.sentences, signal);
  const nCites = sample.sentences.reduce((s, x) => s + x.cites.length, 0);
  send({ type: "node", id: "generate", status: "done", detail: `문장 ${sample.sentences.length}개 · 인용 ${nCites}개` });

  if (!on("verify")) return skip("verify", "꺼짐");
  send({ type: "node", id: "verify", status: "running" });
  await sleep(700, signal);
  const results = sample.sentences.map((s, index) => {
    // 판 비교 도구를 끄면 그 도구를 근거로 쓴 문장은 근거가 사라진다
    const lostTool = !on("diff") && s.cites.some((c) => c.startsWith("tool:")) && !s.cites.some((c) => !c.startsWith("tool:"));
    const status: VerifyStatus = lostTool ? "unsupported" : (s.status ?? "supported");
    return { index, status, note: lostTool ? "근거로 쓴 판 비교 도구가 꺼져 있음" : s.note };
  });
  send({ type: "verify", results });
  const n = (st: VerifyStatus) => results.filter((r) => r.status === st).length;
  send({
    type: "node",
    id: "verify",
    status: "done",
    detail: `${results.length}문장 중 근거 확인 ${n("supported")} · 추론 ${n("inferred")} · 근거 없음 ${n("unsupported")}`,
  });
}

async function streamSentences(send: (e: AskEvent) => void, sentences: Sentence[], signal: AbortSignal) {
  for (const [index, s] of sentences.entries()) {
    const text = (index ? " " : "") + s.text;
    for (let i = 0; i < text.length; i += 4) {
      send({ type: "sentence", index, delta: text.slice(i, i + 4) });
      await sleep(16, signal);
    }
    if (s.cites.length) send({ type: "cites", index, cites: s.cites });
  }
}

const BACKEND = process.env.AGENT_BACKEND_URL ?? "http://127.0.0.1:8000";
const SSE_HEADERS = { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache, no-transform" };

export async function POST(request: Request) {
  const req = (await request.json()) as AskRequest;
  try {
    const res = await fetch(`${BACKEND}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal: request.signal, // 브라우저가 중지하면 백엔드 요청도 끊는다
      cache: "no-store",
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    return new Response(res.body, { headers: SSE_HEADERS });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return sampleResponse(req, request.signal, `백엔드(${BACKEND})에 연결하지 못해 샘플 모드로 답합니다`);
  }
}

function sampleResponse(req: AskRequest, signal: AbortSignal, notice: string) {
  const q = findQuestion(req);
  const enc = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      const send = (e: AskEvent) => {
        if (!closed) controller.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`));
      };
      try {
        send({ type: "notice", message: notice });
        await run(send, req, q, signal);
      } catch (e) {
        if (!signal.aborted) send({ type: "error", message: e instanceof Error ? e.message : String(e) });
      } finally {
        send({ type: "done" });
        closed = true;
        try {
          controller.close();
        } catch {}
      }
    },
  });
  return new Response(stream, { headers: SSE_HEADERS });
}
