"use client";

import { useEffect } from "react";
import { parsePageId, type DocMeta } from "@/lib/types";
import { IconClose, IconExternal } from "./Icons";
import { PdfPage } from "./PdfPage";

type Props = {
  ids: string[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  docs: Record<string, DocMeta>;
  highlights?: Map<string, string[]>;
};

export function Lightbox({ ids, index, onIndex, onClose, docs, highlights }: Props) {
  const id = ids[index];
  const p = parsePageId(id);
  const doc = p ? docs[p.doc] : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") onIndex(Math.min(ids.length - 1, index + 1));
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") onIndex(Math.max(0, index - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ids.length, index, onIndex, onClose]);

  if (!p || !doc) return null;
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={`${doc.label} ${p.page}쪽 크게 보기`} onClick={onClose}>
      <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
        <span className={`doc-chip doc-${p.doc}`}>{doc.short}</span>
        <b>{p.page}쪽</b>
        <span className="muted">
          {index + 1} / {ids.length} · ←→ 이동 · Esc 닫기
        </span>
        <span className="spacer" />
        <a className="btn-ghost" href={`${doc.url}#page=${p.page}`} target="_blank" rel="noreferrer">
          <IconExternal size={15} /> PDF
        </a>
        <button className="btn-ghost" onClick={onClose} aria-label="닫기">
          <IconClose size={16} />
        </button>
      </div>
      <div className="lightbox-page" onClick={(e) => e.stopPropagation()}>
        <PdfPage url={doc.url} page={p.page} width={1600} alt={`${doc.label} ${p.page}쪽`} highlights={highlights?.get(id)} />
      </div>
    </div>
  );
}
