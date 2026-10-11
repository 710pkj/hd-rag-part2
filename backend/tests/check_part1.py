"""포팅한 Part 1 검색기가 웹 데이터(part1.json: E9는 제출 노트북 셀 52, 최종은 보고서의 E27 포함)의 top-10과 같은지 확인한다. 모델을 부르면 실패하게 막고 캐시만으로 돌린다."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P

def blocked(*a, **k):
    raise RuntimeError("캐시에 없는 값 → 모델 호출 시도")
P.M3.encode = blocked
P.cross_reranker = blocked
P.groq_json = blocked

P.init()
web = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ok = 0
for q in web["questions"]:
    t0 = time.time()
    e9, _ = P.search_v2(q["query"], idx=P.IDX_E9)
    en = P.english_query(q["query"])
    fin, tr = P.search_v2(q["query"], en=en, idx=P.IDX13, **P.FINAL27_OPTS)   # 보고서 최종 통합 (E27 포함)
    same = e9[:10] == q["runs"]["e9"] and fin[:10] == q["runs"]["final"]
    ok += same
    print(q["qid"], "OK " if same else "DIFF", f"{time.time()-t0:.2f}s", "| ko:", tr["ko"], "| en:", tr["en"])
    if not same:
        print("   e9 ", e9[:10], "\n   want", q["runs"]["e9"], "\n   fin", fin[:10], "\n   want", q["runs"]["final"])
print(f"{ok}/{len(web['questions'])} 일치")
