"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PART1 } from "@/data/part1";
import { readSse } from "@/lib/sse";
import {
  NODES,
  type AskEvent,
  type AskRequest,
  type Attachment,
  type DocId,
  type Health,
  type NodeId,
  type NodeToggles,
  type TestQuestion,
} from "@/lib/types";
import { Composer } from "./Composer";
import { EvalPanel } from "./EvalPanel";
import { Lightbox } from "./Lightbox";
import { StackPanel } from "./StackPanel";
import { QuestionList, TopBar } from "./TopBar";
import { Turn, type NodeState, type TurnData } from "./Turn";

const DOCS = PART1.docs;
const RUNS = PART1.runs;
const QUESTIONS = PART1.questions;

const pendingNodes = () => Object.fromEntries(NODES.map((n) => [n.id, { status: "pending" }])) as Record<NodeId, NodeState>;

type LightboxState = { mode: "stack" } | { mode: "single"; id: string } | null;

export default function App() {
  const [turns, setTurns] = useState<TurnData[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [run, setRun] = useState("final");
  const [index, setIndex] = useState(0);
  const [lightbox, setLightbox] = useState<LightboxState>(null);
  const [toggles, setToggles] = useState<NodeToggles>({});
  const [filters, setFilters] = useState<DocId[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const running = turns.some((t) => t.running);
  const active = turns.find((t) => t.id === activeId) ?? null;
  const ids = active?.pages?.runs[run] ?? [];
  const cited = useMemo(() => new Set(active?.sentences.flatMap((s) => s.cites) ?? []), [active]);
  const lastLen = turns.at(-1)?.sentences.reduce((n, s) => n + s.text.length, 0) ?? 0;

  useEffect(() => {
    if (turns.length) endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length, lastLen]);

  // 백엔드 상태를 10초마다 확인 (상단 바 표시)
  useEffect(() => {
    let alive = true;
    const check = () =>
      fetch("/api/health", { cache: "no-store" })
        .then((r) => r.json())
        .then((h: Health) => alive && setHealth(h))
        .catch(() => alive && setHealth({ ok: false }));
    check();
    const t = setInterval(check, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const update = (id: string, fn: (t: TurnData) => TurnData) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  function apply(id: string, ev: AskEvent) {
    switch (ev.type) {
      case "meta":
        return update(id, (t) => ({ ...t, sample: ev.sample, qid: ev.qid, qtype: QUESTIONS.find((q) => q.qid === ev.qid)?.qtype ?? null }));
      case "node":
        return update(id, (t) => ({ ...t, nodes: { ...t.nodes, [ev.id]: { status: ev.status, detail: ev.detail ?? t.nodes[ev.id]?.detail } } }));
      case "pages":
        update(id, (t) => ({ ...t, pages: { runs: ev.runs, rels: ev.rels, runMeta: ev.runMeta } }));
        setActiveId(id);
        setRun(ev.defaultRun);
        setIndex(0);
        return;
      case "sentence":
        return update(id, (t) => {
          const s = [...t.sentences];
          const cur = s[ev.index] ?? { text: "", cites: [] };
          s[ev.index] = { ...cur, text: cur.text + ev.delta };
          return { ...t, sentences: s };
        });
      case "cites":
        return update(id, (t) => ({ ...t, sentences: t.sentences.map((s, i) => (i === ev.index ? { ...s, cites: ev.cites } : s)) }));
      case "verify":
        return update(id, (t) => ({
          ...t,
          sentences: t.sentences.map((s, i) => {
            const r = ev.results.find((x) => x.index === i);
            return r ? { ...s, status: r.status, note: r.note } : s;
          }),
        }));
      case "web":
        return update(id, (t) => ({ ...t, web: ev.results }));
      case "answer_reset":
        return update(id, (t) => ({ ...t, sentences: [], rewrites: (t.rewrites ?? 0) + 1 }));
      case "notice":
        return update(id, (t) => ({ ...t, notices: [...t.notices, ev.message] }));
      case "done":
        return update(id, (t) => ({ ...t, elapsed: ev.elapsed }));
      case "error":
        return update(id, (t) => ({ ...t, error: ev.message }));
    }
  }

  async function ask(question: string, qid?: string) {
    if (running) return;
    const id = crypto.randomUUID();
    const sent = { filters, attachments };
    setTurns((ts) => [
      ...ts,
      { id, question, qid: qid ?? null, qtype: null, sample: false, ...sent, nodes: pendingNodes(), sentences: [], pages: null, web: [], notices: [], running: true },
    ]);
    setActiveId(id);
    setAttachments([]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const body: AskRequest = { question, qid, filters, nodes: toggles, attachments };
      const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ac.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      for await (const ev of readSse(res)) apply(id, ev);
    } catch (e) {
      if (ac.signal.aborted) update(id, (t) => ({ ...t, stopped: true }));
      else update(id, (t) => ({ ...t, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      update(id, (t) => ({
        ...t,
        running: false,
        nodes: Object.fromEntries(
          Object.entries(t.nodes).map(([k, v]) => [k, v.status === "running" ? { ...v, status: "skipped", detail: "중지됨" } : v]),
        ) as Record<NodeId, NodeState>,
      }));
      abortRef.current = null;
    }
  }

  function activate(t: TurnData) {
    if (t.id === activeId) return;
    setActiveId(t.id);
    setRun("final");
    setIndex(0);
  }

  function cite(t: TurnData, pageId: string) {
    if (t.id !== activeId) activate(t);
    const runs = t.pages?.runs ?? {};
    const here = runs[t.id === activeId ? run : "final"]?.indexOf(pageId) ?? -1;
    if (here >= 0) {
      if (t.id !== activeId) setRun("final");
      setIndex(here);
      return;
    }
    const other = (t.pages?.runMeta ?? RUNS).find((r) => runs[r.key]?.includes(pageId));
    if (other) {
      setRun(other.key);
      setIndex(runs[other.key].indexOf(pageId));
      setToast(`이 페이지는 ${other.label} 결과에 있어 그쪽으로 바꿨습니다`);
      return;
    }
    setLightbox({ mode: "single", id: pageId });
    setToast("검색 top-10에 없는 페이지라 따로 엽니다");
  }

  const pickTest = (q: TestQuestion) => ask(q.query, q.qid);
  const runMeta = active?.pages?.runMeta ?? RUNS;
  const runLabel = active?.pages ? (runMeta.find((r) => r.key === run)?.label ?? run) : null;

  return (
    <div className="app">
      <TopBar
        questions={QUESTIONS}
        onPick={pickTest}
        toggles={toggles}
        onToggles={setToggles}
        running={running}
        health={health}
        hasTurns={turns.length > 0}
        onReset={() => {
          setTurns([]);
          setActiveId(null);
          setIndex(0);
        }}
      />
      <main className="main">
        <section className="panel chat-panel" aria-label="대화">
          <div className="messages">
            {turns.length === 0 ? (
              <div className="chat-empty">
                <h2>선급 규정을 물어보세요</h2>
                <p className="muted">
                  답변의 근거 페이지는 가운데에 겹쳐 쌓이고, 정답이 있는 테스트 질문은 오른쪽에 네 가지 지표와 페이지 순위가 나옵니다.
                </p>
                <p className="sub-head">테스트 질문으로 시작하기</p>
                <QuestionList questions={QUESTIONS} onPick={pickTest} />
              </div>
            ) : (
              turns.map((t) => (
                <Turn key={t.id} turn={t} active={t.id === activeId} onActivate={() => activate(t)} onCite={(c) => cite(t, c)} docs={DOCS} />
              ))
            )}
            <div ref={endRef} />
          </div>
          <Composer
            running={running}
            onSend={(q) => ask(q)}
            onStop={() => abortRef.current?.abort()}
            filters={filters}
            onFilters={setFilters}
            attachments={attachments}
            onAttachments={setAttachments}
            docs={DOCS}
          />
        </section>

        <div className="right">
          <StackPanel
            ids={ids}
            rels={active?.pages?.rels ?? null}
            cited={cited}
            index={Math.min(index, Math.max(0, ids.length - 1))}
            onIndex={setIndex}
            onOpen={(i) => {
              setIndex(i);
              setLightbox({ mode: "stack" });
            }}
            docs={DOCS}
            runLabel={runLabel}
          />
          <EvalPanel
            runs={active?.pages?.runs ?? null}
            rels={active?.pages?.rels ?? null}
            run={run}
            onRun={(k) => {
              const cur = ids[index];
              const next = active?.pages?.runs[k] ?? [];
              setRun(k);
              setIndex(Math.max(0, cur ? next.indexOf(cur) : 0));
            }}
            runMeta={runMeta}
            index={index}
            onIndex={setIndex}
            cited={cited}
            docs={DOCS}
          />
        </div>
      </main>

      {lightbox?.mode === "stack" && ids.length > 0 && (
        <Lightbox ids={ids} index={index} onIndex={setIndex} onClose={() => setLightbox(null)} docs={DOCS} />
      )}
      {lightbox?.mode === "single" && (
        <Lightbox ids={[lightbox.id]} index={0} onIndex={() => {}} onClose={() => setLightbox(null)} docs={DOCS} />
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
