"""가짜 LLM으로 그래프의 분기를 확인한다: 근거 부족 → 재검색 → 웹 검색 → 생성 → 검증에서 근거 없음 → 다시 생성 → 끝"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag import part1 as P
from agent import graph as G, llm, tools

P.init(verbose=False)
calls = []
def fake_chat_json(system, user, fast=False, max_tokens=0):
    kind = "grade" if system is G.GRADE_SYSTEM else "generate" if system is G.GENERATE_SYSTEM else "verify"
    calls.append(kind)
    if kind == "grade":
        return {"answerable": False, "relevant_pages": [], "reason": "테스트: 근거 부족"}
    if kind == "generate":
        rnd = calls.count("generate")
        if rnd == 1:   # 일부러 원문에 없는 노테이션 이름(FAKE-X9)을 넣음 → 규칙 검사가 잡아야 함
            return {"sentences": [{"text": "방한 설비 노테이션은 Winterization과 FAKE-X9입니다.", "cites": ["KR2026:225"]},
                                  {"text": "웹 자료도 참고했습니다.", "cites": ["web:1", "BAD:1"]}]}
        return {"sentences": [{"text": "방한 설비 노테이션은 Winterization입니다.", "cites": ["KR2026:225"]}]}
    return {"results": [{"index": 0, "status": "supported", "note": ""}, {"index": 1, "status": "inferred", "note": "웹"}]}

llm.chat_json = fake_chat_json
llm.has_key = lambda: True
G.has_tavily = lambda: True
G.web_search = type("T", (), {"invoke": staticmethod(lambda a: [{"title": "Example", "url": "https://example.com", "content": "Winterization notation example"}])})
G.P.english_query = lambda q: "winterization notation for ships in cold climate"   # Groq 대신

events = []
for ev in G.graph().stream({"question": "KR 선급 기준, 혹한 지역을 다니는 배의 방한 설비 관련 노테이션 알려줘", "nodes": {}, "filters": [], "attachments": []}, stream_mode="custom"):
    if ev["type"] in ("sentence",): continue
    events.append(ev)
    if ev["type"] == "node" and ev["status"] != "running":
        print(f"{ev['id']:9s} {ev['status']:8s} {ev.get('detail','')[:110]}")
    elif ev["type"] != "node":
        print("  •", json.dumps(ev, ensure_ascii=False)[:160])
print("LLM 호출 순서:", calls)
v = [e for e in events if e["type"] == "verify"]
assert calls == ["grade", "grade", "generate", "verify", "generate", "verify"], calls
assert v[0]["results"][0]["status"] == "unsupported" and "FAKE-X9" in v[0]["results"][0]["note"], v[0]
assert any(e["type"] == "answer_reset" for e in events)
assert any(e["type"] == "web" for e in events)
cites = [e for e in events if e["type"] == "cites"]
assert all("BAD:1" not in e["cites"] for e in cites), cites
print("분기 확인 통과")
