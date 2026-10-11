// 원본 PDF 페이지를 이미지(object URL)로 렌더링해 캐시한다.
// pdf.js는 번들러를 거치지 않고 public/pdfjs/ 에서 브라우저가 직접 불러온다 (scripts/prepare.mjs가 복사).
import type * as PdfJs from "pdfjs-dist";

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

const images = new Map<string, Promise<string>>();

export function pageImage(url: string, page: number, width: number): Promise<string> {
  const key = `${url}#${page}@${width}`;
  let p = images.get(key);
  if (!p) {
    p = withSlot(async () => {
      const pdf = await openDoc(url);
      const pg = await pdf.getPage(page);
      const viewport = pg.getViewport({ scale: width / pg.getViewport({ scale: 1 }).width });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await pg.render({ canvas, viewport }).promise;
      pg.cleanup();
      const blob = await new Promise<Blob>((res, rej) =>
        canvas.toBlob((b) => (b ? res(b) : rej(new Error("canvas.toBlob 실패"))), "image/webp", 0.92),
      );
      return URL.createObjectURL(blob);
    });
    p.catch(() => images.delete(key));
    images.set(key, p);
  }
  return p;
}
