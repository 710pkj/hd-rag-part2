"""그래프를 직접 돌려 이벤트를 출력한다 (글자 단위 sentence 이벤트는 모아서). 사용: python tests/run_graph.py "질문" [노드=off ...]"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
from rag import part1 as P
from agent.graph import graph
P.init(verbose=False)
q = sys.argv[1]
nodes = {a.split("=")[0]: False for a in sys.argv[2:] if a.endswith("=off")}
t0 = time.time(); text = {}
for ev in graph().stream({"question": q, "nodes": nodes, "filters": [], "attachments": []}, stream_mode="custom"):
    if ev["type"] == "sentence":
        text[ev["index"]] = text.get(ev["index"], "") + ev["delta"]; continue
    if ev["type"] == "node" and ev["status"] == "running" and "detail" not in ev: continue
    if ev["type"] == "pages":
        ev = {**ev, "runs": {k: v[:5] for k, v in ev["runs"].items()}}
    print(f"[{time.time()-t0:5.1f}s]", json.dumps(ev, ensure_ascii=False)[:400])
print("답변:", "".join(text[i] for i in sorted(text)))
