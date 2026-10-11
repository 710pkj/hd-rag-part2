// 웹의 지표 계산이 Part 1 노트북 값(test_per_query.csv)과 같은지 확인한다.
// 실행: node scripts/check-metrics.mts
import fs from "node:fs";
import { computeMetrics } from "../src/lib/metrics.ts";

const data = JSON.parse(fs.readFileSync(new URL("../src/data/part1.json", import.meta.url), "utf8"));
const near = (a: number, b: number) => Math.abs(a - b) < 0.006; // CSV는 소수 둘째 자리로 반올림됨
let bad = 0;
for (const q of data.questions) {
  const e9 = computeMetrics(q.runs.e9, q.rels);
  const fin = computeMetrics(q.runs.final, q.rels);
  const r = q.reported;
  const ok =
    near(e9.p, r.e9.p) && near(e9.r, r.e9.r) && near(e9.mrr, r.e9.mrr) && near(e9.ndcg, r.e9.ndcg) && near(fin.ndcg, r.final.ndcg);
  if (!ok) bad++;
  console.log(
    `${q.qid} ${ok ? "OK " : "DIFF"}  E9 P ${e9.p.toFixed(2)} R ${e9.r.toFixed(2)} MRR ${e9.mrr.toFixed(2)} nDCG ${e9.ndcg.toFixed(3)} (보고 ${r.e9.ndcg})  최종 nDCG ${fin.ndcg.toFixed(3)} (보고 ${r.final.ndcg})`,
  );
}
const mean = (run: string, f: "p" | "r" | "mrr" | "ndcg") =>
  data.questions.reduce((s: number, q: any) => s + computeMetrics(q.runs[run], q.rels)[f], 0) / data.questions.length;
console.log(`평균 E9 nDCG ${mean("e9", "ndcg").toFixed(4)} · 최종 nDCG ${mean("final", "ndcg").toFixed(4)} (보고서 E9 0.8230 · 최종 통합 E27 포함 0.9877)`);
process.exit(bad ? 1 : 0);
