"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { QTYPE_LABELS } from "@/data/samples";
import { OPTIONAL_NODES, type Health, type NodeToggles, type TestQuestion } from "@/lib/types";
import { IconChevron, IconNodes, IconPlus } from "./Icons";

function Popover({ label, icon, badge, children }: { label: string; icon?: ReactNode; badge?: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className="popover" ref={ref}>
      <button className="btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        {icon}
        {label}
        {badge && <span className="badge">{badge}</span>}
        <IconChevron size={14} />
      </button>
      {open && <div className="popover-panel">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function QuestionList({ questions, onPick, disabled }: { questions: TestQuestion[]; onPick: (q: TestQuestion) => void; disabled?: boolean }) {
  return (
    <ul className="q-list">
      {questions.map((q) => (
        <li key={q.qid}>
          <button disabled={disabled} onClick={() => onPick(q)}>
            <span className="q-list-meta">
              <b>{q.qid}</b>
              <span className="chip">{QTYPE_LABELS[q.qtype] ?? q.qtype}</span>
            </span>
            <span className="q-list-text">{q.query}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

type Props = {
  questions: TestQuestion[];
  onPick: (q: TestQuestion) => void;
  toggles: NodeToggles;
  onToggles: (t: NodeToggles) => void;
  onReset: () => void;
  running: boolean;
  health: Health | null;
  hasTurns: boolean;
  devMode: boolean;
  onDevMode: () => void;
};

function HealthLine({ h }: { h: Health | null }) {
  if (!h) return <p className="muted">백엔드 확인 중…</p>;
  if (!h.ok) return <p className="muted"><span className="dot dot-off" /> 샘플 모드 · 백엔드 꺼짐</p>;
  const dev = h.device === "xpu" ? "Arc GPU" : h.device === "cuda" ? "GPU" : "CPU";
  const models = h.models?.startsWith("ready") ? "" : h.models?.startsWith("error") ? " · 모델 오류" : " · 모델 불러오는 중";
  return (
    <p className="muted" title={`LLM ${h.model ?? ""} · 모델 ${h.models ?? ""} · 벡터 DB ${h.vector_db?.name ?? ""} (${h.vector_db?.note ?? ""})`}>
      <span className={`dot ${h.groq ? "dot-on" : "dot-warn"}`} /> 백엔드 연결 · {dev}
      {models} · 벡터 DB {h.vector_db?.name ?? "?"} · Groq {h.groq ? "✓" : "키 없음"} · 웹 검색 {h.tavily ? "✓" : "꺼짐"}
      {h.logs && ` · 기록 ${h.logs === "postgres" ? "로컬 DB" : "파일"}`}
    </p>
  );
}

export function TopBar({ questions, onPick, toggles, onToggles, onReset, running, health, hasTurns, devMode, onDevMode }: Props) {
  const off = OPTIONAL_NODES.filter((n) => toggles[n.id] === false).length;
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden>
          <span />
          <span />
          <span />
        </span>
        <div>
          <h1>선급 문서 기술검토 에이전트</h1>
          <HealthLine h={health} />
        </div>
      </div>
      <span className="spacer" />
      <Popover label="테스트 질문">
        {(close) => (
          <>
            <p className="popover-title">test 10문항 · 고르면 바로 실행</p>
            <QuestionList
              questions={questions}
              disabled={running}
              onPick={(q) => {
                close();
                onPick(q);
              }}
            />
          </>
        )}
      </Popover>
      <Popover label="노드 설정" icon={<IconNodes size={15} />} badge={off ? `${off}개 꺼짐` : undefined}>
        {() => (
          <>
            <p className="popover-title">끌 수 있는 노드 · 다음 질문부터 적용</p>
            <ul className="toggle-list">
              {OPTIONAL_NODES.map((n) => (
                <li key={n.id}>
                  <label>
                    <input
                      type="checkbox"
                      className="switch"
                      checked={toggles[n.id] !== false}
                      onChange={(e) => onToggles({ ...toggles, [n.id]: e.target.checked })}
                    />
                    <span>
                      <b>{n.label}</b>
                      <span className="muted small">{n.hint}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <p className="muted small">질문 분석 · 검색 · 답변 생성은 항상 실행합니다.</p>
          </>
        )}
      </Popover>
      <button
        className={`btn-ghost${devMode ? " is-on" : ""}`}
        aria-pressed={devMode}
        onClick={onDevMode}
        title="검색 평가 칸(지표 · 정답 쪽 순위 · 검색 구성 비교)과 정답 표시를 켜고 끕니다"
      >
        개발자 모드
      </button>
      <button className="btn-ghost" onClick={onReset} disabled={running || !hasTurns}>
        <IconPlus size={15} /> 새 대화
      </button>
    </header>
  );
}
