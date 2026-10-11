"use client";

import { useEffect, useState } from "react";
import { pageImage } from "@/lib/pdf";

type Props = { url: string; page: number; width: number; alt: string };

export function PdfPage({ url, page, width, alt }: Props) {
  const [state, setState] = useState<{ key: string; src?: string; error?: string }>({ key: "" });
  const key = `${url}#${page}@${width}`;

  useEffect(() => {
    let alive = true;
    pageImage(url, page, width).then(
      (src) => alive && setState({ key, src }),
      (e) => alive && setState({ key, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      alive = false;
    };
  }, [url, page, width, key]);

  const current = state.key === key ? state : { key };
  if (current.error) return <div className="pdf-fallback">페이지를 그리지 못했습니다: {current.error}</div>;
  if (!current.src) return <div className="pdf-loading" aria-label="페이지 불러오는 중" />;
  // eslint-disable-next-line @next/next/no-img-element -- object URL이라 next/image 최적화 대상이 아님
  return <img className="pdf-img" src={current.src} alt={alt} draggable={false} />;
}
