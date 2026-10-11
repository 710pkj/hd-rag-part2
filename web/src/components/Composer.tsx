"use client";

import { useLayoutEffect, useRef, useState } from "react";
import type { Attachment, DocId, DocMeta } from "@/lib/types";
import { IconClip, IconClose, IconFile, IconSend, IconStop } from "./Icons";

type Props = {
  running: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  filters: DocId[];
  onFilters: (f: DocId[]) => void;
  attachments: Attachment[];
  onAttachments: (a: Attachment[]) => void;
  docs: Record<string, DocMeta>;
};

const kindOf = (name: string): Attachment["kind"] =>
  /\.pdf$/i.test(name) ? "pdf" : /\.csv$/i.test(name) ? "csv" : "other";
const sizeText = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))}KB` : `${(n / 1024 / 1024).toFixed(1)}MB`);

export function Composer({ running, onSend, onStop, filters, onFilters, attachments, onAttachments, docs }: Props) {
  const [text, setText] = useState("");
  const [drag, setDrag] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, [text]);

  const addFiles = (files: FileList | null) => {
    if (!files?.length) return;
    onAttachments([...attachments, ...Array.from(files).map((f) => ({ name: f.name, size: f.size, kind: kindOf(f.name) }))]);
  };
  const submit = () => {
    const q = text.trim();
    if (!q || running) return;
    onSend(q);
    setText("");
  };
  const toggle = (d: DocId) => onFilters(filters.includes(d) ? filters.filter((x) => x !== d) : [...filters, d]);

  return (
    <form
      className={`composer${drag ? " is-drag" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        addFiles(e.dataTransfer.files);
      }}
    >
      {attachments.length > 0 && (
        <div className="att-list">
          {attachments.map((a, i) => (
            <span key={i} className="att-chip" title="백엔드 연결 후 처리됩니다">
              <IconFile size={13} />
              {a.name}
              <span className="muted">{sizeText(a.size)}</span>
              <button
                type="button"
                className="att-x"
                aria-label={`${a.name} 빼기`}
                onClick={() => onAttachments(attachments.filter((_, j) => j !== i))}
              >
                <IconClose size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <textarea
        ref={taRef}
        rows={1}
        value={text}
        placeholder="선급 규정에 대해 질문하세요 (Enter 전송 · Shift+Enter 줄바꿈)"
        aria-label="질문 입력"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // 한글 조합 중 Enter는 글자 확정이므로 전송하지 않는다
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <div className="composer-bar">
        <button type="button" className="icon-btn" onClick={() => fileRef.current?.click()} title="파일 첨부 (PDF·CSV) · 끌어다 놓아도 됨" aria-label="파일 첨부">
          <IconClip size={17} />
        </button>
        <input ref={fileRef} type="file" hidden multiple accept=".pdf,.csv" onChange={(e) => (addFiles(e.target.files), (e.target.value = ""))} />
        <div className="filters" role="group" aria-label="검색할 문서">
          <span className="muted" title="하나도 고르지 않으면 질문에서 선급·연도를 읽어 자동으로 정함">문서</span>
          {(Object.keys(docs) as DocId[]).map((d) => (
            <button
              key={d}
              type="button"
              className={`filter-chip doc-${d}`}
              aria-pressed={filters.includes(d)}
              onClick={() => toggle(d)}
            >
              {docs[d].short}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {running ? (
          <button type="button" className="send-btn is-stop" onClick={onStop} aria-label="중지">
            <IconStop size={16} />
          </button>
        ) : (
          <button type="submit" className="send-btn" disabled={!text.trim()} aria-label="전송">
            <IconSend size={17} />
          </button>
        )}
      </div>
    </form>
  );
}
