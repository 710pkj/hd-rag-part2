"use client";

import { useState } from "react";
import { QTYPE_LABELS } from "@/data/samples";
import {
  FEEDBACK_REASONS,
  NODES,
  TOOL_LABELS,
  parsePageId,
  type AnswerTable,
  type Attachment,
  type Clarify,
  type DocId,
  type DocMeta,
  type NodeId,
  type NodeStatus,
  type NotationCard,
  type NotFound,
  type Passage,
  type RunMeta,
  type Sentence,
  type WebResult,
} from "@/lib/types";
import type { Rels } from "@/lib/metrics";
import { IconCheck, IconFile } from "./Icons";

export type NodeState = { status: NodeStatus; detail?: string };

export type TurnData = {
  id: string;
  question: string;
  qid: string | null;
  qtype: string | null;
  sample: boolean;
  runId?: string; // 백엔드 실행 기록 id (피드백이 여기에 이어짐)
  filters: DocId[];
  attachments: Attachment[];
  nodes: Record<NodeId, NodeState>;
  sentences: Sentence[];
  passages: Passage[];
  table: AnswerTable | null;
  cards: NotationCard[];
  notFound: NotFound | null;
  clarify: Clarify | null;
  pages: { runs: Record<string, string[]>; rels: Rels | null; runMeta?: RunMeta[] } | null;
  web: WebResult[];
  notices: string[];
  rewrites?: number; // 근거 검증에서 걸려 다시 만든 횟수
  elapsed?: number;
  running: boolean;
  stopped?: boolean;
  error?: string;
};

const STATUS_TEXT: Record<NodeStatus, string> = { pending: "대기", running: "진행 중", done: "완료", skipped: "건너뜀" };
const VERIFY_TEXT = { supported: "인용 페이지에서 확인", inferred: "추론 (직접 근거 없음)", unsupported: "근거 없음" } as const;
const KIND_CLASS: Record<string, string> = { 신설: "tag-good", 삭제: "tag-bad", "명칭 변경": "tag-warn", "요건 변경": "tag-warn" };
const PAGE_RE = /^(KR2022|KR2026|ABS2025):\d+$/;

function citeLabel(c: string, docs: Record<string, DocMeta>) {
  if (TOOL_LABELS[c]) return TOOL_LABELS[c];
  if (c.startsWith("web:")) return `웹 ${c.slice(4)}`;
  const p = parsePageId(c);
  return p ? `${docs[p.doc].short} ${p.page}쪽` : c;
}

type Props = {
  turn: TurnData;
  active: boolean;
  onActivate: () => void;
  onCite: (pageId: string) => void;
  onClarify: (filters: DocId[]) => void;
  busy: boolean;
  docs: Record<string, DocMeta>;
};

function PageButton({ id, docs, onCite, title }: { id: string; docs: Record<string, DocMeta>; onCite: (id: string) => void; title?: string }) {
  return (
    <button className="cite" onClick={() => onCite(id)} title={title}>
      {citeLabel(id, docs)}
    </button>
  );
}

function VMark({ status, note }: { status: keyof typeof VERIFY_TEXT; note?: string }) {
  return (
    <span className={`vmark vm-${status}`} role="img" aria-label={VERIFY_TEXT[status]} title={note || VERIFY_TEXT[status]}>
      {status === "supported" ? "✓" : status === "inferred" ? "~" : "!"}
    </span>
  );
}

// 질문 유형별 표: 판 비교 → 변경 표(쪽 칸은 누르면 그 쪽으로), 선급 비교 → 비교표(행마다 인용과 근거 판정)
function TableView({ table, docs, onCite }: { table: AnswerTable; docs: Record<string, DocMeta>; onCite: (id: string) => void }) {
  const compare = table.kind === "compare";
  return (
    <figure className="ans-table">
      <figcaption>
        <b>{table.title}</b>
        {table.note && <span className="muted small"> · {table.note}</span>}
      </figcaption>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {table.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
              {compare && <th>근거</th>}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i} className={r.status ? `st-${r.status}` : undefined}>
                {r.cells.map((c, j) => {
                  const ids = c.split(" ").filter((x) => PAGE_RE.test(x));
                  if (!compare && ids.length) // 변경 표의 2022 쪽 · 2026 쪽 칸
                    return (
                      <td key={j} className="td-pages">
                        {ids.map((id) => (
                          <PageButton key={id} id={id} docs={docs} onCite={onCite} />
                        ))}
                      </td>
                    );
                  if (!compare && j === 1) // 구분 칸: 신설 · 삭제 · 변경 배지
                    return (
                      <td key={j}>
                        <span className={KIND_CLASS[c] ?? "tag-plain"}>{c}</span>
                      </td>
                    );
                  return <td key={j}>{c || "-"}</td>;
                })}
                {compare && (
                  <td className="td-pages">
                    {(r.cites ?? []).map((id) =>
                      PAGE_RE.test(id) ? <PageButton key={id} id={id} docs={docs} onCite={onCite} /> : <span key={id} className="cite cite-tool">{citeLabel(id, docs)}</span>,
                    )}
                    {r.status && <VMark status={r.status} note={r.note} />}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}

// 노테이션 카드: 답변에 이름이 나온 노테이션을 문서의 표·목록에서 찾아 정리 (요건 · 설명 · 참조 규칙 · 쪽)
function Cards({ cards, docs, onCite }: { cards: NotationCard[]; docs: Record<string, DocMeta>; onCite: (id: string) => void }) {
  return (
    <div className="ncards">
      {cards.map((c) => (
        <article key={`${c.doc}-${c.name}`} className="ncard">
          <header>
            <b className="ncard-name">{c.name}</b>
            <span className={`doc-chip doc-${c.doc}`}>{docs[c.doc]?.short ?? c.doc}</span>
          </header>
          {c.section && <p className="ncard-sec muted">{c.section}</p>}
          {c.req && (
            <p>
              <span className="label">요건</span> {c.req}
            </p>
          )}
          {c.description && <p className="ncard-desc">{c.description}</p>}
          {c.refs && <p className="muted small">{c.refs}</p>}
          <footer>
            <PageButton id={c.page} docs={docs} onCite={onCite} />
            <span className="muted small">{c.source === "abs_notation" ? "노테이션 설명 쪽" : c.source === "kr_table" ? "요건표 행" : "노테이션 목록"}</span>
          </footer>
        </article>
      ))}
    </div>
  );
}

// 출처 목록 · 기준 판 배지 · 원문 확인 안내
function Sources({ turn, docs, onCite }: { turn: TurnData; docs: Record<string, DocMeta>; onCite: (id: string) => void }) {
  const ids = [...new Set(turn.sentences.flatMap((s) => s.cites).filter((c) => PAGE_RE.test(c)))];
  if (!ids.length) return null;
  const used = [...new Set(ids.map((id) => id.split(":")[0]))] as DocId[];
  const quote = (id: string) => turn.passages.find((p) => p.page === id)?.quote;
  return (
    <div className="sources">
      <div className="sources-row">
        <span className="label">출처</span>
        {ids.map((id) => (
          <PageButton key={id} id={id} docs={docs} onCite={onCite} title={quote(id) ? `“${quote(id)!.slice(0, 200)}”` : undefined} />
        ))}
      </div>
      <div className="sources-row">
        <span className="label">기준 문서</span>
        {used.map((d) => (
          <span key={d} className={`doc-chip doc-${d}`}>
            {docs[d].label}
          </span>
        ))}
        {used.includes("KR2022") && used.includes("KR2026") && <span className="tag-warn">두 판 근거 함께 사용</span>}
        {used.includes("KR2022") && !used.includes("KR2026") && <span className="tag-warn">구판(2022) 근거</span>}
      </div>
      <p className="disclaimer muted small">문서에서 찾은 근거로 만든 답변입니다. 실제 적용 전에는 선급 원문과 최신 개정 여부를 확인하세요.</p>
    </div>
  );
}

// 피드백: 👍는 바로 저장, 👎는 사유를 고르고 보냄. run_id로 백엔드 실행 기록과 이어짐
function Feedback({ runId }: { runId: string }) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [store, setStore] = useState("");

  async function send(r: "up" | "down") {
    setState("sending");
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, rating: r, reasons, comment: comment.trim() || null }),
      });
      const j = await res.json();
      if (!j.ok) throw new Error(j.error ?? "저장 실패");
      setStore(j.store === "postgres" ? "로컬 DB" : "파일");
      setState("sent");
    } catch {
      setState("error");
    }
  }

  if (state === "sent")
    return <p className="feedback muted small">피드백을 저장했습니다 ({store}). 답변 개선과 평가 질문 보강에 씁니다.</p>;
  return (
    <div className="feedback">
      <span className="muted small">이 답변이 도움이 됐나요?</span>
      <button
        className={`fb-btn${rating === "up" ? " is-on" : ""}`}
        aria-label="도움이 됨"
        disabled={state === "sending"}
        onClick={() => {
          setRating("up");
          void send("up");
        }}
      >
        👍
      </button>
      <button className={`fb-btn${rating === "down" ? " is-on" : ""}`} aria-label="도움이 안 됨" onClick={() => setRating(rating === "down" ? null : "down")}>
        👎
      </button>
      {state === "error" && <span className="tag-bad">저장하지 못함 (백엔드 확인)</span>}
      {rating === "down" && (
        <div className="fb-form">
          <div className="fb-reasons" role="group" aria-label="이유">
            {FEEDBACK_REASONS.map((r) => (
              <button
                key={r}
                type="button"
                className="filter-chip"
                aria-pressed={reasons.includes(r)}
                onClick={() => setReasons(reasons.includes(r) ? reasons.filter((x) => x !== r) : [...reasons, r])}
              >
                {r}
              </button>
            ))}
          </div>
          <textarea rows={2} value={comment} placeholder="무엇이 틀렸는지 적어 주세요 (선택)" onChange={(e) => setComment(e.target.value)} />
          <button className="btn-ghost" disabled={state === "sending"} onClick={() => void send("down")}>
            보내기
          </button>
        </div>
      )}
    </div>
  );
}

export function Turn({ turn, active, onActivate, onCite, onClarify, busy, docs }: Props) {
  const [open, setOpen] = useState<NodeId | null>(null);
  const openNode = open ? NODES.find((n) => n.id === open) : null;
  const verified = turn.sentences.filter((s) => s.status);
  const count = (st: string) => verified.filter((s) => s.status === st).length;
  const quoteOf = (i: number, c: string) => turn.passages.find((p) => p.index === i && p.page === c)?.quote;

  return (
    <article className={`turn${active ? " is-active" : ""}`}>
      <button className="turn-q" onClick={onActivate} title="이 답변의 근거 페이지를 오른쪽에 표시">
        <span className="turn-q-meta">
          <span className="label">질문</span>
          {turn.qid && (
            <span className="chip">
              {turn.qid}
              {turn.qtype && ` · ${QTYPE_LABELS[turn.qtype] ?? turn.qtype}`}
            </span>
          )}
          {turn.filters.map((d) => (
            <span key={d} className={`doc-chip doc-${d}`}>
              {docs[d].short}
            </span>
          ))}
        </span>
        <span className="turn-q-text">{turn.question}</span>
        {turn.attachments.length > 0 && (
          <span className="att-list">
            {turn.attachments.map((a, i) => (
              <span key={i} className="att-chip">
                <IconFile size={13} /> {a.name}
              </span>
            ))}
          </span>
        )}
      </button>

      <div className="turn-a">
        <div className="turn-a-head">
          <span className="label">에이전트</span>
          {turn.sample && <span className="badge-sample">샘플 응답 · 백엔드 연결 전</span>}
          {turn.stopped && <span className="tag-plain">중지됨</span>}
          {turn.error && <span className="tag-bad">오류: {turn.error}</span>}
          {!!turn.rewrites && <span className="tag-plain">근거 검증 뒤 {turn.rewrites}번 다시 생성</span>}
          {turn.elapsed !== undefined && !turn.running && <span className="muted small">{turn.elapsed.toFixed(1)}초</span>}
        </div>

        {turn.clarify && (
          <div className="clarify" role="note">
            <p>
              <span className="label">가정</span> {turn.clarify.assumption} <span className="muted">{turn.clarify.ask}</span>
            </p>
            <div className="clarify-opts">
              {turn.clarify.options.map((o) => (
                <button key={o.label} className="btn-ghost btn-sm" disabled={busy} onClick={() => onClarify(o.filters)}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {turn.notices.map((n, i) => (
          <p key={i} className="notice">
            {n}
          </p>
        ))}

        <ol className="node-track" aria-label="그래프 진행">
          {NODES.map((n) => {
            const st = turn.nodes[n.id]?.status ?? "pending";
            return (
              <li key={n.id}>
                <button
                  className={`node node-${st}${open === n.id ? " is-open" : ""}`}
                  onClick={() => setOpen(open === n.id ? null : n.id)}
                  aria-expanded={open === n.id}
                  title={`${n.label}: ${STATUS_TEXT[st]}${turn.nodes[n.id]?.detail ? ` — ${turn.nodes[n.id].detail}` : ""}`}
                >
                  <span className="node-icon" aria-hidden>
                    {st === "done" ? <IconCheck size={12} /> : null}
                  </span>
                  {n.label}
                </button>
              </li>
            );
          })}
        </ol>
        {openNode && (
          <div className="node-detail">
            <b>{openNode.label}</b>
            <span className="muted">{STATUS_TEXT[turn.nodes[openNode.id]?.status ?? "pending"]}</span>
            <p>{turn.nodes[openNode.id]?.detail ?? "아직 실행되지 않음"}</p>
          </div>
        )}

        {(turn.sentences.length > 0 || turn.running) && (
          <p className="answer">
            {turn.sentences.map((s, i) => (
              <span key={i} className={`sent${s.status ? ` st-${s.status}` : ""}`} title={s.note}>
                {s.text}
                {s.cites.map((c) => {
                  const w = c.startsWith("web:") ? turn.web.find((x) => x.id === c) : undefined;
                  const q = quoteOf(i, c);
                  return w ? (
                    <a key={c} className="cite cite-web" href={w.url} target="_blank" rel="noreferrer" title={`${w.title}\n${w.url}`}>
                      {citeLabel(c, docs)}
                    </a>
                  ) : (
                    <button
                      key={c}
                      className={`cite${c.startsWith("tool:") ? " cite-tool" : ""}`}
                      title={q ? `인용 구절 (페이지에 노란색으로 표시)\n“${q.slice(0, 240)}${q.length > 240 ? "…" : ""}”` : undefined}
                      onClick={() => (c.startsWith("tool:") ? setOpen("diff") : onCite(c))}
                    >
                      {citeLabel(c, docs)}
                    </button>
                  );
                })}
                {s.status && <VMark status={s.status} note={s.note} />}
              </span>
            ))}
            {turn.running && <span className="caret" aria-hidden />}
          </p>
        )}

        {turn.notFound && (
          <div className="notfound" role="status">
            <b>문서에서 근거를 찾지 못했습니다</b>
            <p className="muted">{turn.notFound.reason}</p>
            {turn.notFound.nearest.length > 0 && (
              <div className="sources-row">
                <span className="label">가까운 쪽</span>
                {turn.notFound.nearest.map((id) => (
                  <PageButton key={id} id={id} docs={docs} onCite={onCite} />
                ))}
              </div>
            )}
            <p className="muted small">노테이션 이름 · 선급 · 연도를 넣어 더 구체적으로 묻거나, 아래 입력창의 문서 범위를 바꿔 다시 물어보세요.</p>
          </div>
        )}

        {turn.table && <TableView table={turn.table} docs={docs} onCite={onCite} />}
        {turn.cards.length > 0 && <Cards cards={turn.cards} docs={docs} onCite={onCite} />}

        {turn.web.length > 0 && (
          <ul className="web-list">
            {turn.web.map((w) => (
              <li key={w.id}>
                <span className="chip">웹 {w.id.slice(4)}</span>
                <a href={w.url} target="_blank" rel="noreferrer">
                  {w.title || w.url}
                </a>
              </li>
            ))}
          </ul>
        )}

        {verified.length > 0 && (
          <p className="verify-legend">
            <span className="vmark vm-supported">✓</span> 근거 확인 {count("supported")}
            <span className="vmark vm-inferred">~</span> 추론 {count("inferred")}
            <span className="vmark vm-unsupported">!</span> 근거 없음 {count("unsupported")}
            <span className="muted"> · 문장에 마우스를 올리면 판정 이유, 인용에 올리면 인용 구절</span>
          </p>
        )}

        {!turn.running && <Sources turn={turn} docs={docs} onCite={onCite} />}
        {!turn.running && turn.runId && !turn.error && <Feedback runId={turn.runId} />}
      </div>
    </article>
  );
}
