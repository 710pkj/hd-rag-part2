"use client";

import { useState } from "react";
import { QTYPE_LABELS } from "@/data/samples";
import {
  NODES,
  TOOL_LABELS,
  parsePageId,
  type Attachment,
  type DocId,
  type DocMeta,
  type NodeId,
  type NodeStatus,
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
  filters: DocId[];
  attachments: Attachment[];
  nodes: Record<NodeId, NodeState>;
  sentences: Sentence[];
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
  docs: Record<string, DocMeta>;
};

export function Turn({ turn, active, onActivate, onCite, docs }: Props) {
  const [open, setOpen] = useState<NodeId | null>(null);
  const openNode = open ? NODES.find((n) => n.id === open) : null;
  const verified = turn.sentences.filter((s) => s.status);
  const count = (st: string) => verified.filter((s) => s.status === st).length;

  return (
    <article className={`turn${active ? " is-active" : ""}`}>
      <button className="turn-q" onClick={onActivate} title="이 답변의 근거 페이지와 평가를 오른쪽에 표시">
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
                  return w ? (
                    <a key={c} className="cite cite-web" href={w.url} target="_blank" rel="noreferrer" title={`${w.title}
${w.url}`}>
                      {citeLabel(c, docs)}
                    </a>
                  ) : (
                    <button
                      key={c}
                      className={`cite${c.startsWith("tool:") ? " cite-tool" : ""}`}
                      onClick={() => (c.startsWith("tool:") ? setOpen("diff") : onCite(c))}
                    >
                      {citeLabel(c, docs)}
                    </button>
                  );
                })}
                {s.status && (
                  <span className={`vmark vm-${s.status}`} role="img" aria-label={VERIFY_TEXT[s.status]} title={s.note ?? VERIFY_TEXT[s.status]}>
                    {s.status === "supported" ? "✓" : s.status === "inferred" ? "~" : "!"}
                  </span>
                )}
              </span>
            ))}
            {turn.running && <span className="caret" aria-hidden />}
          </p>
        )}

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
            <span className="muted"> · 문장에 마우스를 올리면 판정 이유</span>
          </p>
        )}
      </div>
    </article>
  );
}
