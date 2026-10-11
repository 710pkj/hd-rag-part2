"""보고서(노션)의 네 구성이 실험 노트북 결과(final27_per_question.csv)와 37문항 모두 같은지 확인한다.
nDCG@10(소수 넷째 자리)과 정답 쪽 순위(50위 밖은 '밖')를 비교한다. 모델 호출은 막고 캐시만 쓴다.
실행: python tests/check_final27.py [final27_per_question.csv 경로]"""
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P

def blocked(*a, **k):
    raise RuntimeError("캐시에 없는 값 → 모델 호출 시도")
P.M3.encode = blocked; P.cross_reranker = blocked; P.groq_json = blocked
P.init(verbose=False)

path = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\내 드라이브\HD융캡디\outputs\final27_per_question.csv")
want = {r["qid"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}
CAND = dict(topic=True, policy=True, boost=True, rr="both", old_last=True)
CONFIGS = {"E9 기준 구성": dict(idx=P.IDX_E9), "미리 정한 후보": dict(idx=P.IDX13, **CAND),
           "최종 통합 (E27 전)": dict(idx=P.IDX13, **P.FINAL_OPTS), "최종 통합 (+E27)": dict(idx=P.IDX13, **P.FINAL27_OPTS)}
qs = {v["qid"]: v for v in P.QSETS.values()}
bad = 0
for name, opts in CONFIGS.items():
    ok = 0
    for qid in sorted(qs, key=lambda q: (q[0] != "t", q)):
        q = qs[qid]
        en = P.english_query(q["query"]) if opts.get("rr") == "both" else None
        order, _ = P.search_v2(q["query"], en=en, **opts)
        nd = P.metrics_at_k(order, q["rels"])["nDCG@10"]
        head = order[:P.DEPTH]
        ranks = " · ".join(str(head.index(p) + 1) if p in head else "밖" for p in q["rels"])
        w = want[qid]
        same = abs(nd - float(w[name])) < 5e-5 and ranks == w[f"{name} 순위"]
        ok += same
        if not same:
            bad += 1
            print(f"  DIFF {name} {qid}: nDCG {nd:.4f} vs {w[name]} | 순위 {ranks} vs {w[name + ' 순위']}")
    print(f"{name}: {ok}/{len(qs)} 일치")
sys.exit(1 if bad else 0)
