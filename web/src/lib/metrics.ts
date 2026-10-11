// 검색 지표 @k. Part 1 노트북과 같은 정의다.
// nDCG는 관련도 등급을 그대로 이득으로 쓴다: DCG = Σ grade / log2(rank + 1)

export type Rels = Record<string, number>;

export type Metrics = {
  p: number;
  pMax: number; // 정답이 k개보다 적으면 P@k가 1이 될 수 없다
  r: number;
  mrr: number;
  ndcg: number;
  hits: number;
  nRel: number;
  firstRank: number | null;
};

export function computeMetrics(ranked: string[], rels: Rels, k = 10): Metrics {
  const top = ranked.slice(0, k);
  const nRel = Object.keys(rels).length;
  let hits = 0;
  let dcg = 0;
  let firstRank: number | null = null;
  top.forEach((id, i) => {
    const g = rels[id] ?? 0;
    if (g <= 0) return;
    hits++;
    if (firstRank === null) firstRank = i + 1;
    dcg += g / Math.log2(i + 2);
  });
  const idcg = Object.values(rels)
    .sort((a, b) => b - a)
    .slice(0, k)
    .reduce((s, g, i) => s + g / Math.log2(i + 2), 0);
  return {
    p: hits / k,
    pMax: Math.min(nRel, k) / k,
    r: nRel ? hits / nRel : 0,
    mrr: firstRank ? 1 / firstRank : 0,
    ndcg: idcg ? dcg / idcg : 0,
    hits,
    nRel,
    firstRank,
  };
}
