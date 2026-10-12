"use client";

import type { Rels } from "@/lib/metrics";
import { parsePageId, type DocMeta } from "@/lib/types";
import { IconExpand, IconExternal } from "./Icons";
import { PageStack } from "./PageStack";

type Props = {
  ids: string[];
  rels: Rels | null;
  cited: Set<string>;
  index: number;
  onIndex: (i: number) => void;
  onOpen: (i: number) => void;
  docs: Record<string, DocMeta>;
  runLabel: string | null;
  highlights?: Map<string, string[]>;
};

export function StackPanel({ ids, rels, cited, index, onIndex, onOpen, docs, runLabel, highlights }: Props) {
  const id = ids[index];
  const p = id ? parsePageId(id) : null;
  const doc = p ? docs[p.doc] : null;
  const grade = id && rels ? (rels[id] ?? 0) : 0;

  return (
    <section className="panel stack-panel" aria-label="근거 페이지">
      <header className="panel-head">
        <h2>근거 페이지</h2>
        {runLabel && <span className="muted">{runLabel} · top-{ids.length}</span>}
        <span className="spacer" />
        {ids.length > 0 && (
          <span className="counter" aria-live="polite">
            <b>{index + 1}</b> / {ids.length}
          </span>
        )}
      </header>

      <div className="stack-body">
        <PageStack ids={ids} rels={rels} cited={cited} index={index} onIndex={onIndex} onOpen={onOpen} docs={docs} highlights={highlights} />
        {ids.length > 0 && (
          <nav className="rail" aria-label="순위로 이동">
            {ids.map((pid, i) => {
              const pp = parsePageId(pid);
              const g = rels?.[pid] ?? 0;
              return (
                <button
                  key={`${pid}-${i}`}
                  className={`rail-item${i === index ? " is-active" : ""}`}
                  onClick={() => onIndex(i)}
                  title={`${i + 1}위 · ${pp ? `${docs[pp.doc].short} ${pp.page}쪽` : pid}${g ? " · 정답" : ""}${cited.has(pid) ? " · 인용" : ""}`}
                >
                  <span className={`rail-bar doc-bg-${pp?.doc}`} />
                  <span className="rail-num">{i + 1}</span>
                  {g > 0 && <span className="rail-gt" aria-label="정답" />}
                </button>
              );
            })}
          </nav>
        )}
      </div>

      {id && p && doc && (
        <footer className="stack-caption">
          <div className="caption-main">
            <span className={`doc-chip doc-${p.doc}`}>{doc.short}</span>
            <b>{p.page}쪽</b>
            <span className="muted">검색 {index + 1}위</span>
            {rels &&
              (grade > 0 ? (
                <span className="tag-good">정답 · 관련도 {grade}</span>
              ) : (
                <span className="tag-plain">정답 아님</span>
              ))}
            {cited.has(id) && <span className="tag-cite">답변에서 인용</span>}
          </div>
          <div className="caption-actions">
            <button className="btn-ghost" onClick={() => onOpen(index)}>
              <IconExpand size={15} /> 크게 보기
            </button>
            <a className="btn-ghost" href={`${doc.url}#page=${p.page}`} target="_blank" rel="noreferrer">
              <IconExternal size={15} /> PDF
            </a>
          </div>
          <p className="caption-hint muted">스크롤하거나 오른쪽 스크롤바를 끌어 넘기기 · ↑↓ 키 · 뒤 장의 윗단을 눌러 바로 가기</p>
        </footer>
      )}
    </section>
  );
}
