import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P
P.init()
q = "KR 선급 기준, 혹한 지역을 다니는 배의 방한 설비 관련 노테이션 알려줘"
t0 = time.time(); P.M3.load(); print(f"bge-m3 로딩 {time.time()-t0:.1f}s")
t0 = time.time(); P.cross_reranker(); print(f"리랭커 로딩 {time.time()-t0:.1f}s")
st = {}
t0 = time.time(); order, tr = P.search_v2(q, en=None, idx=P.IDX13, **{**P.FINAL_OPTS, "rr": "ko"}, stats=st)
print(f"검색 전체 {time.time()-t0:.1f}s | 리랭커 쌍 {st.get('rerank_new')}개 {st.get('rerank_sec',0):.1f}s")
print("top5", order[:5], "| ko:", tr["ko"])
import torch; print("threads", torch.get_num_threads(), "| vocab", len(P.M3.tok))
