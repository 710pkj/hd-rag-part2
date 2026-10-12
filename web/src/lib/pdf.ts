// 원본 PDF 페이지를 이미지(object URL)로 렌더링해 캐시한다.
// pdf.js는 번들러를 거치지 않고 public/pdfjs/ 에서 브라우저가 직접 불러온다 (scripts/prepare.mjs가 복사).
import type * as PdfJs from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";

type Lib = typeof PdfJs;
const BASE = "/pdfjs/";

let libPromise: Promise<Lib> | null = null;
function lib(): Promise<Lib> {
  if (!libPromise) {
    const url = `${BASE}pdf.min.mjs`;
    libPromise = import(/* webpackIgnore: true */ /* turbopackIgnore: true */ url).then((m: Lib) => {
      m.GlobalWorkerOptions.workerSrc = `${BASE}pdf.worker.min.mjs`;
      return m;
    });
  }
  return libPromise;
}

const docs = new Map<string, Promise<PdfJs.PDFDocumentProxy>>();
function openDoc(url: string) {
  let p = docs.get(url);
  if (!p) {
    p = lib().then(
      (m) =>
        m.getDocument({
          url,
          cMapUrl: `${BASE}cmaps/`,
          cMapPacked: true,
          standardFontDataUrl: `${BASE}standard_fonts/`,
          wasmUrl: `${BASE}wasm/`,
        }).promise,
    );
    p.catch(() => docs.delete(url));
    docs.set(url, p);
  }
  return p;
}

// 동시에 두 장까지만 렌더링한다 (앞 카드가 먼저 나오도록 요청 순서대로 처리)
let active = 0;
const waiting: (() => void)[] = [];
async function withSlot<T>(fn: () => Promise<T>): Promise<T> {
  if (active >= 2) await new Promise<void>((r) => waiting.push(r));
  active++;
  try {
    return await fn();
  } finally {
    active--;
    waiting.shift()?.();
  }
}


// ───────── 인용 구절 강조 ─────────
// 백엔드가 고른 구절(pkl 텍스트)을 PDF 글자 층에서 찾는다. 같은 기준선의 글자 조각을 한 줄로 묶고,
// 줄마다 "구절에 있는 낱말 − 없는 낱말"을 낱말 희소도(그 쪽에서 그 낱말이 나온 줄 수의 역수)로 가중해 점수를 매긴 뒤,
// 점수가 높은 줄들이 이어진 구간(최대 부분합)을 고른다. 표의 행처럼 비슷한 줄이 많아도 구분하는 낱말이 있는 줄이 이긴다.
type Box = { x: number; y: number; w: number; h: number };
type Line = { base: number; size: number; boxes: Box[]; toks: string[] };

const TOK_RE = /[0-9a-z가-힣]+\+*/g;
const toks = (s: string) => (s.normalize("NFKC").toLowerCase().match(TOK_RE) ?? []).filter((t) => /[a-z가-힣]/.test(t) || t.length >= 3);

function linesOf(items: { str: string; t: number[]; width: number }[]): Line[] {
  const lines: Line[] = [];
  for (const it of items) {
    const size = Math.hypot(it.t[2], it.t[3]);
    const box = { x: it.t[4], y: it.t[5] - size, w: it.width, h: size * 1.18 };
    const line = lines.find((l) => Math.abs(l.base - it.t[5]) < Math.max(l.size, size) * 0.45);
    if (line) {
      line.boxes.push(box);
      line.toks.push(...toks(it.str));
      line.size = Math.max(line.size, size);
    } else lines.push({ base: it.t[5], size, boxes: [box], toks: toks(it.str) });
  }
  return lines.sort((a, b) => a.base - b.base);
}

function matchLines(lines: Line[], quote: string): Line[] {
  const q = new Set(toks(quote));
  if (!q.size) return [];
  const df = new Map<string, number>();
  for (const l of lines) for (const t of new Set(l.toks)) df.set(t, (df.get(t) ?? 0) + 1);
  const score = lines.map((l) => [...new Set(l.toks)].reduce((s, t) => s + (q.has(t) ? 1 : -1) / (df.get(t) ?? 1), 0));
  const max = Math.max(0, ...score);
  if (max <= 0) return [];
  const tau = 0.25 * max;
  let best = { sum: 0, a: 0, b: -1 };
  let cur = 0;
  let start = 0;
  score.forEach((s, i) => {
    cur += s - tau;
    if (cur <= 0) {
      cur = 0;
      start = i + 1;
    } else if (cur > best.sum) best = { sum: cur, a: start, b: i };
  });
  const sel = lines.slice(best.a, best.b + 1).filter((_, k) => score[best.a + k] > 0);
  const got = new Set(sel.flatMap((l) => l.toks).filter((t) => q.has(t)));
  return got.size / q.size >= 0.35 ? sel : []; // 구절 낱말의 35%도 못 찾으면 엉뚱한 곳을 칠하지 않음
}

function drawMarks(ctx: CanvasRenderingContext2D, groups: Line[][]) {
  ctx.save();
  ctx.globalCompositeOperation = "multiply"; // 글자는 검게 남고 바탕만 노랗게
  ctx.fillStyle = "rgba(255, 214, 64, 0.62)";
  for (const g of groups)
    for (const l of g) {
      const x0 = Math.min(...l.boxes.map((b) => b.x));
      const x1 = Math.max(...l.boxes.map((b) => b.x + b.w));
      const y0 = Math.min(...l.boxes.map((b) => b.y));
      const y1 = Math.max(...l.boxes.map((b) => b.y + b.h));
      ctx.fillRect(x0 - 3, y0 - 1, x1 - x0 + 6, y1 - y0 + 2);
    }
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = "rgba(214, 140, 0, 0.95)"; // 왼쪽 여백의 세로 막대: 강조한 구간 표시
  for (const g of groups) {
    if (!g.length) continue;
    const y0 = Math.min(...g.flatMap((l) => l.boxes.map((b) => b.y)));
    const y1 = Math.max(...g.flatMap((l) => l.boxes.map((b) => b.y + b.h)));
    const x0 = Math.min(...g.flatMap((l) => l.boxes.map((b) => b.x)));
    ctx.fillRect(Math.max(3, x0 - 14), y0 - 1, 4, y1 - y0 + 2);
  }
  ctx.restore();
}

export type PageImage = { src: string; marks: number }; // marks: 강조한 구절 수 (못 찾은 구절은 빠짐)
const images = new Map<string, Promise<PageImage>>();

export function pageImage(url: string, page: number, width: number, quotes: string[] = []): Promise<PageImage> {
  const key = `${url}#${page}@${width}|${quotes.join("\u0001")}`;
  let p = images.get(key);
  if (!p) {
    p = withSlot(async () => {
      const m = await lib();
      const pdf = await openDoc(url);
      const pg = await pdf.getPage(page);
      const viewport = pg.getViewport({ scale: width / pg.getViewport({ scale: 1 }).width });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await pg.render({ canvas, viewport }).promise;
      let marks = 0;
      if (quotes.length) {
        const tc = await pg.getTextContent();
        const items = tc.items
          .filter((it): it is TextItem => "str" in it && !!it.str.trim())
          .map((it) => ({ str: it.str, t: m.Util.transform(viewport.transform, it.transform), width: it.width * viewport.scale }));
        const lines = linesOf(items);
        const groups = quotes.map((q) => matchLines(lines, q)).filter((g) => g.length);
        marks = groups.length;
        const ctx = canvas.getContext("2d");
        if (ctx && marks) drawMarks(ctx, groups);
      }
      pg.cleanup();
      const blob = await new Promise<Blob>((res, rej) =>
        canvas.toBlob((b) => (b ? res(b) : rej(new Error("canvas.toBlob 실패"))), "image/webp", 0.92),
      );
      return { src: URL.createObjectURL(blob), marks };
    });
    p.catch(() => images.delete(key));
    images.set(key, p);
  }
  return p;
}
