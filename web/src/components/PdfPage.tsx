"use client";

import { useEffect, useState } from "react";
import { pageImage } from "@/lib/pdf";

// highlights: 이 쪽에서 답변이 인용한 구절들. 있으면 그 줄을 노랗게 칠해 그린다
type Props = { url: string; page: number; width: number; alt: string; highlights?: string[] };

export function PdfPage({ url, page, width, alt, highlights }: Props) {
  const qkey = (highlights ?? []).join("\u0001");
  const [state, setState] = useState<{ key: string; src?: string; marks?: number; error?: string }>({ key: "" });
  const key = `${url}#${page}@${width}|${qkey}`;

  useEffect(() => {
    let alive = true;
    pageImage(url, page, width, qkey ? qkey.split("\u0001") : []).then(
      (img) => alive && setState({ key, src: img.src, marks: img.marks }),
      (e) => alive && setState({ key, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      alive = false;
    };
  }, [url, page, width, qkey, key]);

  const current = state.key === key ? state : { key };
  if (current.error) return <div className="pdf-fallback">페이지를 그리지 못했습니다: {current.error}</div>;
  if (!current.src) return <div className="pdf-loading" aria-label="페이지 불러오는 중" />;
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element -- object URL이라 next/image 최적화 대상이 아님 */}
      <img className="pdf-img" src={current.src} alt={alt} draggable={false} />
      {qkey && (
        <span
          className={`hl-badge${current.marks ? "" : " is-miss"}`}
          title={current.marks ? "답변이 인용한 구절을 노란색으로 표시" : "인용 구절의 위치를 페이지에서 찾지 못함"}
        >
          {current.marks ? `인용 구절 ${current.marks}곳` : "구절 위치 못 찾음"}
        </span>
      )}
    </>
  );
}
