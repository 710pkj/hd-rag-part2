"""Neon 경로로 보고서 네 구성 × 37문항을 재현하고(check_final27과 같은 기준), FAISS와 채널별 후보 50쪽 순서도 비교한다."""
import runpy, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P

t0 = time.time()
sys.argv = [sys.argv[0]] + sys.argv[1:]
try:
    runpy.run_path(str(Path(__file__).with_name("check_final27.py")), run_name="__main__")
except SystemExit as e:
    code = e.code
print("벡터 DB:", P.vector_db_status(), f"· 전체 {time.time() - t0:.0f}초")

# 채널별 후보 50쪽: FAISS 색인(대신용으로 남겨 둔 것)과 Neon이 같은지
same = total = 0
for v in P.QSETS.values():
    info = P.analyze_query(v["query"]); allowed, _ = P.allowed_docs(info)
    for ix in P.VECTOR_DB["indexes"]:
        for key in [k for k in P.QUERY_MEMO if k[0] == "ko16"][:0]:
            pass
    qi = P.QI.analyze(v["query"])
    ko = P.strip_intent(P.clean_query(P.QI.topic_query(v["query"], qi)), "A")
    qv = P.ko_vectors(ko, ko, info["societies"])
    for ix in P.VECTOR_DB["indexes"]:
        for ch in ("dense", "sparse"):
            a = ix.ranked_pages(ix.scores(ch, qv), allowed, positive_only=(ch != "dense"))
            b = ix.fallback.ranked_pages(ix.fallback.scores(ch, qv), allowed, depth=50, positive_only=(ch != "dense"))
            total += 1
            same += [p for p, _ in a] == [p for p, _ in b] and all(abs(x - y) < 1e-5 for (_, x), (_, y) in zip(a, b))
print(f"채널별 후보 50쪽 순서·점수 같음: {same}/{total}")
print("벡터 DB:", P.vector_db_status())
