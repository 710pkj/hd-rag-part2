"use client";

import { computeMetrics, type Metrics, type Rels } from "@/lib/metrics";
import { parsePageId, type DocMeta, type RunMeta } from "@/lib/types";

type Props = {
  runs: Record<string, string[]> | null;
  rels: Rels | null;
  run: string;
  onRun: (key: string) => void;
  runMeta: RunMeta[];
  index: number;
  onIndex: (i: number) => void;
  cited: Set<string>;
  docs: Record<string, DocMeta>;
};

const f3 = (v: number) => v.toFixed(3);

function Tile({ label, value, max, sub, delta }: { label: string; value: number; max?: number; sub: string; delta?: number }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">
        {f3(value)}
        {delta !== undefined && Math.abs(delta) >= 0.0005 && (
          <span className={`tile-delta ${delta > 0 ? "up" : "down"}`}>
            {delta > 0 ? "+" : "−"}
            {f3(Math.abs(delta))}
          </span>
        )}
      </div>
      <div className="meter" aria-hidden>
        <span className="meter-fill" style={{ width: `${value * 100}%` }} />
        {max !== undefined && max < 1 && <span className="meter-max" style={{ left: `${max * 100}%` }} />}
      </div>
      <div className="tile-sub">{sub}</div>
    </div>
  );
}

export function EvalPanel({ runs, rels, run, onRun, runMeta, index, onIndex, cited, docs }: Props) {
  const ids = runs?.[run] ?? [];
  const other = runMeta.find((r) => r.key !== run && runs?.[r.key]);
  const m: Metrics | null = rels && ids.length ? computeMetrics(ids, rels) : null;
  const o: Metrics | null = rels && other && runs ? computeMetrics(runs[other.key], rels) : null;
  const meta = runMeta.find((r) => r.key === run);
  const label = (id: string) => {
    const p = parsePageId(id);
    return p ? { doc: p.doc, short: docs[p.doc].short, page: p.page } : { doc: "", short: id, page: 0 };
  };

  return (
    <section className="panel eval-panel" aria-label="검색 평가">
      <header className="panel-head">
        <h2>검색 평가</h2>
        <span className="muted">@10</span>
      </header>

      {!runs ? (
        <div className="eval-empty">
          <p>테스트 질문을 실행하면 네 가지 지표와 페이지 순위가 여기에 나옵니다.</p>
          <p className="muted">정답이 정해진 질문(test 10개)만 지표를 계산할 수 있습니다.</p>
        </div>
      ) : (
        <div className="eval-scroll">
          <div className="seg" role="group" aria-label="비교할 검색 결과">
            {runMeta
              .filter((r) => runs[r.key])
              .map((r) => (
                <button key={r.key} aria-pressed={r.key === run} onClick={() => onRun(r.key)}>
                  {r.label}
                </button>
              ))}
          </div>
          {meta && <p className="run-note muted">{meta.note}</p>}

          {m && rels ? (
            <>
              <div className="tiles">
                <Tile
                  label="P@10"
                  value={m.p}
                  max={m.pMax}
                  sub={`정답 ${m.hits}쪽 / 10 · 최대 ${m.pMax.toFixed(1)}`}
                  delta={o ? m.p - o.p : undefined}
                />
                <Tile label="R@10" value={m.r} sub={`정답 ${m.nRel}쪽 중 ${m.hits}쪽 찾음`} delta={o ? m.r - o.r : undefined} />
                <Tile
                  label="MRR@10"
                  value={m.mrr}
                  sub={m.firstRank ? `첫 정답 ${m.firstRank}위` : "top-10에 정답 없음"}
                  delta={o ? m.mrr - o.mrr : undefined}
                />
                <Tile label="nDCG@10" value={m.ndcg} sub="관련도 등급 반영" delta={o ? m.ndcg - o.ndcg : undefined} />
              </div>
              {o && other && <p className="muted small">작은 숫자는 {other.label} 대비 차이</p>}

              <h3 className="sub-head">정답 페이지</h3>
              <ul className="gt-list">
                {Object.entries(rels)
                  .sort((a, b) => b[1] - a[1])
                  .map(([id, g]) => {
                    const pos = ids.indexOf(id);
                    const l = label(id);
                    return (
                      <li key={id}>
                        <span className={`doc-chip doc-${l.doc}`}>{l.short}</span>
                        <span>{l.page}쪽</span>
                        <span className="muted">관련도 {g}</span>
                        <span className="spacer" />
                        {pos >= 0 ? (
                          <button className="rank-link" onClick={() => onIndex(pos)}>
                            {pos + 1}위
                          </button>
                        ) : (
                          <span className="tag-bad">10위 밖</span>
                        )}
                      </li>
                    );
                  })}
              </ul>

              <h3 className="sub-head">페이지 순위</h3>
              <ol className="rank-list">
                {ids.map((id, i) => {
                  const l = label(id);
                  const g = rels[id] ?? 0;
                  return (
                    <li key={`${id}-${i}`}>
                      <button className={`rank-row${i === index ? " is-active" : ""}${g ? " is-gt" : ""}`} onClick={() => onIndex(i)}>
                        <span className="rank-num">{i + 1}</span>
                        <span className={`doc-chip doc-${l.doc}`}>{l.short}</span>
                        <span className="rank-page">{l.page}쪽</span>
                        <span className="spacer" />
                        {cited.has(id) && <span className="tag-cite">인용</span>}
                        {g > 0 && <span className="tag-good">정답 {g}</span>}
                      </button>
                    </li>
                  );
                })}
              </ol>
            </>
          ) : (
            <div className="eval-empty">
              <p>정답이 없는 질문이라 지표를 계산하지 않습니다.</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
