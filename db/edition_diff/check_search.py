"""판본 비교표를 바꿔 끼우고 검색까지 돌려, 노션 보고서의 네 구성 × 37문항이 그대로인지 확인한다.
바꿔 끼우는 것: 지금 CSV / SQL seq(DB 표 edition_changes를 직접 읽음) / SQL lev / SQL trgm.
기준 값: 같은 폴더의 final27_per_question.csv (실험 노트북 결과를 복사해 둔 것. backend tests/check_final27.py와 같은 비교). 모델 호출은 막고 캐시만 씀.
실행: VECTOR_DB=faiss 로 backend .venv의 python (1단계 색인은 FAISS, 판본 비교표만 로컬 PostgreSQL에서)"""
import csv, json, os, sys, time
from collections import defaultdict
from pathlib import Path

os.environ["VECTOR_DB"] = "faiss"              # backend/.env의 검색 DB(로컬 · Neon)에 붙지 않게 (판본 비교표만 바꿔 보는 실험)
BACKEND = Path(__file__).resolve().parents[2] / "backend"   # 저장소의 에이전트 백엔드
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")
import psycopg
from rag import part1 as P

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


def blocked(*a, **k):
    raise RuntimeError("캐시에 없는 값 → 모델 호출 시도")


P.M3.encode = blocked
P.cross_reranker = blocked
P.groq_json = blocked
t = time.perf_counter()
P.init(verbose=False)
print(f"검색기 준비 {time.perf_counter() - t:.0f}s · 1단계 색인 {P.VECTOR_DB['name']}")


def from_csv(path):
    m = defaultdict(set)                       # part1.init 934–939행과 같은 방식
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        kind = r["구분"].split(" (")[0]
        for col, doc in (("2022 쪽", "KR2022"), ("2026 쪽", "KR2026")):
            for p in r[col].split():
                m[f"{doc}:{p}"].add(kind)
    return m


def from_db():
    m = defaultdict(set)
    with psycopg.connect("host=localhost port=5433 user=postgres dbname=hdrag") as db:
        for pid, kind in db.execute("SELECT page_id, kind FROM edition_change_pages"):
            m[pid].add(kind)
    return m


VARIANTS = {"지금 CSV": lambda: from_csv(P.OUT_DIR / "kr_edition_diff.csv"),
            "SQL seq (DB 표)": from_db,
            "SQL lev": lambda: from_csv(OUT / "sql_lev_kr_edition_diff.csv"),
            "SQL trgm": lambda: from_csv(OUT / "sql_trgm_kr_edition_diff.csv"),
            "빈 표 (대조군)": lambda: defaultdict(set)}
want = {r["qid"]: r for r in csv.DictReader(open(HERE / "final27_per_question.csv", encoding="utf-8-sig"))}
CAND = dict(topic=True, policy=True, boost=True, rr="both", old_last=True)
CONFIGS = {"E9 기준 구성": dict(idx=P.IDX_E9), "미리 정한 후보": dict(idx=P.IDX13, **CAND),
           "최종 통합 (E27 전)": dict(idx=P.IDX13, **P.FINAL_OPTS), "최종 통합 (+E27)": dict(idx=P.IDX13, **P.FINAL27_OPTS)}
qs = sorted(({**v} for v in P.QSETS.values()), key=lambda q: (q["qid"][0] != "t", q["qid"]))
base = dict(P.CHANGED)
report = {}
for vname, make in VARIANTS.items():
    m = make()
    P.CHANGED.clear()
    P.CHANGED.update(m)
    changed_pages = sorted(p for p in set(m) | set(base) if m.get(p) != base.get(p))
    res = {"changed_pages_vs_csv": changed_pages}
    for cname, opts in CONFIGS.items():
        ok, nd = 0, {"t": [], "d": []}
        diffs = []
        for q in qs:
            en = P.english_query(q["query"]) if opts.get("rr") == "both" else None
            order, _ = P.search_v2(q["query"], en=en, **opts)
            v = P.metrics_at_k(order, q["rels"])["nDCG@10"]
            nd[q["qid"][0]].append(v)
            head = order[:P.DEPTH]
            ranks = " · ".join(str(head.index(p) + 1) if p in head else "밖" for p in q["rels"])
            w = want[q["qid"]]
            same = abs(v - float(w[cname])) < 5e-5 and ranks == w[f"{cname} 순위"]
            ok += same
            if not same:
                diffs.append(f"{q['qid']}: {v:.4f} ({ranks}) vs {w[cname]} ({w[cname + ' 순위']})")
        res[cname] = {"match": f"{ok}/{len(qs)}", "test_nDCG@10": round(sum(nd["t"]) / len(nd["t"]), 4),
                      "dev_nDCG@10": round(sum(nd["d"]) / len(nd["d"]), 4), "diffs": diffs}
    report[vname] = res
    line = " | ".join(f"{c} {r['match']} (test {r['test_nDCG@10']:.4f} · dev {r['dev_nDCG@10']:.4f})" for c, r in res.items() if c in CONFIGS)
    print(f"[{vname}] 지금 CSV와 개정 종류가 다른 쪽 {len(changed_pages)}개 {changed_pages}\n   {line}")
    for c in CONFIGS:
        for d in res[c]["diffs"]:
            print(f"   DIFF {c} {d}")
P.CHANGED.clear()
P.CHANGED.update(base)
json.dump(report, open(OUT / "search_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
