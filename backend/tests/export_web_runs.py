"""웹 샘플 모드용: test 10문항의 E9 · 최종 통합(E27 포함) top-10을 web/src/data/final27.json으로 내보낸다.
web의 prepare-data가 이 파일로 part1.json의 '최종 통합'을 덮어쓴다 (제출 노트북 셀 52의 최종은 E27 전이라서)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P

def blocked(*a, **k):
    raise RuntimeError("캐시에 없는 값 → 모델 호출 시도")
P.M3.encode = blocked; P.cross_reranker = blocked; P.groq_json = blocked
P.init(verbose=False)
out = {}
for v in sorted(P.QSETS.values(), key=lambda v: v["qid"]):
    if not v["qid"].startswith("t"):
        continue
    order, _ = P.search_v2(v["query"], en=P.english_query(v["query"]), idx=P.IDX13, **P.FINAL27_OPTS)
    out[v["qid"]] = {"top10": order[:P.TOP_K], "ndcg": round(P.metrics_at_k(order, v["rels"])["nDCG@10"], 4)}
dst = Path(__file__).resolve().parents[2] / "web" / "src" / "data" / "final27.json"
dst.write_text(json.dumps({"source": "backend tests/export_web_runs.py — Part 1 보고서 최종 통합 (+E27), final27_per_question.csv와 37/37 일치", "questions": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(dst, "평균 nDCG@10", round(sum(q["ndcg"] for q in out.values()) / len(out), 4))
for qid, q in out.items():
    print(qid, q["ndcg"], q["top10"][:5])
