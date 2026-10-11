// Part 1 결과물과 원본 PDF를 웹에서 쓸 수 있게 준비한다.
//  1) pdf.js 실행 파일(worker, 글꼴, cmap, wasm) → public/pdfjs/
//  2) 원본 PDF 3개 → public/docs/ (ASCII 파일명)
//  3) test_set.csv + 제출 노트북의 "상위 10쪽" 출력 → src/data/part1.json
// 경로 찾는 순서: 환경변수 PART1_DIR·DOCS_DIR → 프로젝트 안 data/HD_RAG_Part1 · data/pdf → 만든 사람 PC의 경로
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO = path.resolve(ROOT, "..");
const HD = "C:/Users/710pk/OneDrive/Desktop/HD융캡디";
const pick = (label, cands, mark) => {
  const hit = cands.filter(Boolean).find((d) => fs.existsSync(path.join(d, mark)));
  if (!hit) throw new Error(`${label}를 찾지 못함 (${mark}가 있는 폴더). 찾아본 곳: ${cands.filter(Boolean).join(" | ")}`);
  return hit;
};
const PART1_DIR = pick("Part 1 제출 폴더", [process.env.PART1_DIR, path.join(REPO, "data/HD_RAG_Part1"), `${HD}/제출/HD_RAG_Part1`], "test_set.csv");
const DOCS_DIR = pick("원본 PDF 폴더", [process.env.DOCS_DIR, path.join(REPO, "data/pdf"), `${HD}/02_원본문서`], "KR Notation Guide_2026.pdf");
console.log("Part 1 폴더:", PART1_DIR, "| PDF 폴더:", DOCS_DIR);

const DOCS = {
  KR2022: { label: "KR Notation Guide 2022", short: "KR 2022", src: "KR Notation Guide 2022.pdf", pages: 244 },
  KR2026: { label: "KR Notation Guide 2026", short: "KR 2026", src: "KR Notation Guide_2026.pdf", pages: 251 },
  ABS2025: { label: "ABS Notations and Symbols 2025", short: "ABS 2025", src: "ABS Notations and Symbols 2025.pdf", pages: 443 },
};

// 노트북 셀 52 출력의 실행 이름 → 웹에서 쓰는 키
const RUNS = {
  "E9 기준 구성": { key: "e9", label: "E9 기준 구성", note: "Part 1 보고 값 (dev로 고름)" },
  "최종 통합": { key: "final", label: "최종 통합", note: "Part 1 상한 (test로 고름)" },
};

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    e.isDirectory() ? copyDir(s, d) : fs.copyFileSync(s, d);
  }
}

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...body] = rows.filter((r) => r.some((x) => x !== ""));
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

// 1) pdf.js
const PDFJS = path.join(ROOT, "node_modules/pdfjs-dist");
const PUB_PDFJS = path.join(ROOT, "public/pdfjs");
fs.mkdirSync(PUB_PDFJS, { recursive: true });
for (const f of ["pdf.min.mjs", "pdf.worker.min.mjs"]) fs.copyFileSync(path.join(PDFJS, "build", f), path.join(PUB_PDFJS, f));
for (const d of ["cmaps", "standard_fonts", "wasm"]) copyDir(path.join(PDFJS, d), path.join(PUB_PDFJS, d));
console.log("pdf.js →", path.relative(ROOT, PUB_PDFJS));

// 2) 원본 PDF
const PUB_DOCS = path.join(ROOT, "public/docs");
fs.mkdirSync(PUB_DOCS, { recursive: true });
for (const [id, d] of Object.entries(DOCS)) fs.copyFileSync(path.join(DOCS_DIR, d.src), path.join(PUB_DOCS, `${id}.pdf`));
console.log("PDF 3개 →", path.relative(ROOT, PUB_DOCS));

// 3) 테스트셋 + 상위 10쪽
const tests = parseCsv(fs.readFileSync(path.join(PART1_DIR, "test_set.csv"), "utf8"));
const reported = Object.fromEntries(
  parseCsv(fs.readFileSync(path.join(PART1_DIR, "outputs/test_per_query.csv"), "utf8")).map((r) => [r.qid, r]),
);
const nb = JSON.parse(fs.readFileSync(path.join(PART1_DIR, "RAG_Part1_제출.ipynb"), "utf8"));
const cell = nb.cells.find((c) => c.cell_type === "code" && c.source.join("").startsWith("# 상위 10쪽"));
if (!cell) throw new Error("노트북에서 '# 상위 10쪽' 셀을 찾지 못함");
const out = cell.outputs.map((o) => (Array.isArray(o.text) ? o.text.join("") : o.text ?? "")).join("");

const ranked = {}; // runKey → qid → [pageId]
let run = null;
for (const line of out.split("\n")) {
  const head = line.match(/^■ (.+)$/);
  if (head) { run = RUNS[head[1].trim()]?.key ?? null; if (run) ranked[run] = {}; continue; }
  const m = line.match(/^\s+(t\d+): (.+)$/);
  if (run && m) ranked[run][m[1]] = m[2].split(", ").map((s) => s.replace(" ✓", "").trim());
}

const questions = tests.map((t) => {
  const rels = Object.fromEntries(t.relevant.split(";").map((s) => { const [id, g] = s.split("="); return [id, Number(g)]; }));
  const r = reported[t.qid];
  return {
    qid: t.qid,
    query: t.query,
    qtype: t.qtype,
    rels,
    runs: Object.fromEntries(Object.keys(ranked).map((k) => [k, ranked[k][t.qid]])),
    reported: r && {
      e9: { p: +r["E9 P@10"], r: +r["E9 R@10"], mrr: +r["E9 MRR@10"], ndcg: +r["E9 nDCG@10"] },
      final: { ndcg: +r["최종 nDCG@10"] },
    },
  };
});
// 제출 노트북 셀 52의 '최종 통합'은 E27 전(test 0.974)이다. 보고서(노션)의 최종 통합은 E27 포함(test 0.988)이라,
// 백엔드가 내보낸 src/data/final27.json(backend/tests/export_web_runs.py, 실험 노트북 결과와 37/37 일치)으로 덮어쓴다.
const F27 = path.join(ROOT, "src/data/final27.json");
const final27 = fs.existsSync(F27) ? JSON.parse(fs.readFileSync(F27, "utf8")).questions : null;
if (final27) {
  for (const q of questions) {
    const f = final27[q.qid];
    if (!f) throw new Error(`final27.json에 ${q.qid}가 없음`);
    q.runs.final = f.top10;
    if (q.reported) q.reported.final = { ndcg: f.ndcg };
  }
  RUNS["최종 통합"].label = "최종 통합 (E27 포함)";
  RUNS["최종 통합"].note = "Part 1 보고서 최종 (test로 고름, test nDCG@10 0.988)";
  console.log("최종 통합을 final27.json(E27 포함)으로 덮어씀");
}
for (const q of questions) for (const [k, list] of Object.entries(q.runs))
  if (!list || list.length !== 10) throw new Error(`${q.qid} ${k}: 상위 10쪽이 10개가 아님`);

const data = {
  source: "Part 1 제출 노트북(RAG_Part1_제출.ipynb) 셀 52 출력(E9) + final27.json(보고서 최종 통합, E27 포함) + test_set.csv",
  docs: Object.fromEntries(Object.entries(DOCS).map(([id, d]) => [id, { label: d.label, short: d.short, pages: d.pages, url: `/docs/${id}.pdf` }])),
  runs: Object.values(RUNS).map(({ key, label, note }) => ({ key, label, note })),
  questions,
};
const OUT = path.join(ROOT, "src/data/part1.json");
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(data, null, 2) + "\n");
console.log(`테스트 ${questions.length}문항, 실행 ${Object.keys(ranked).join("·")} →`, path.relative(ROOT, OUT));
