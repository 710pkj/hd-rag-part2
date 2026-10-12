"""에이전트 백엔드 (FastAPI). 웹(Next.js)의 /api/ask가 이 서버의 /ask로 질문을 넘기고 SSE를 그대로 받는다.

실행: .venv\\Scripts\\python -m uvicorn server:app --port 8000
"""
import json
import queue
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV, override=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import llm, logstore  # noqa: E402
from agent.graph import graph  # noqa: E402
from agent.tools import has_tavily  # noqa: E402
from rag import part1 as P  # noqa: E402

NODES = ["analyze", "rewrite", "retrieve", "diff", "grade", "web", "generate", "verify"]
STATE = {"ready": False, "models": "loading", "error": None}
BUSY = threading.Lock()


def warm_models():
    """bge-m3·리랭커를 미리 불러 둔다 (CPU에서 1분 가까이 걸려서 첫 질문이 기다리지 않게)"""
    try:
        t0 = time.time()
        P.M3.load()
        P.cross_reranker()
        STATE["models"] = f"ready ({time.time() - t0:.0f}s)"
    except Exception as e:  # 모델이 없어도 캐시된 질문은 답할 수 있다
        STATE["models"] = f"error: {e}"


@asynccontextmanager
async def lifespan(app):
    P.init()
    graph()
    STATE["ready"] = True
    threading.Thread(target=warm_models, daemon=True).start()
    yield


app = FastAPI(title="선급 문서 기술검토 에이전트", lifespan=lifespan)


class AskBody(BaseModel):
    question: str
    qid: str | None = None
    filters: list[str] = []
    nodes: dict = {}
    attachments: list[dict] = []


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
def health():
    load_dotenv(ENV, override=True)   # .env에 키를 넣으면 다시 시작하지 않아도 바로 반영
    return {**STATE, "groq": llm.has_key(), "tavily": has_tavily(), "model": llm.MODEL, "device": P.device(),
            "vector_db": P.vector_db_status(), "logs": logstore.mode()}


class FeedbackBody(BaseModel):
    run_id: str
    rating: str
    reasons: list[str] = []
    comment: str | None = None


@app.post("/feedback")
def feedback(body: FeedbackBody):
    """답변 아래 👍👎와 사유를 저장 (run_id로 그 실행 기록과 이어짐)"""
    if body.rating not in ("up", "down"):
        return {"ok": False, "error": "rating은 up 또는 down"}
    try:
        uuid.UUID(body.run_id)
    except ValueError:
        return {"ok": False, "error": "run_id 형식이 아님"}
    where = logstore.save_feedback(body.run_id, body.rating, [r[:60] for r in body.reasons[:8]], (body.comment or "")[:2000] or None)
    return {"ok": True, "store": where}


class RunLog:
    """이벤트 흐름에서 실행 기록을 모은다 (화면에 나간 그대로 남음)"""

    def __init__(self, run_id, body):
        self.d = {"run_id": run_id, "question": body.question.strip(), "filters": body.filters, "qid": None, "top10": None,
                  "sentences": [], "table_rows": None, "cards": None, "not_found": False, "clarify": None, "nodes": {},
                  "notices": [], "error": None, "elapsed": None}

    def add(self, ev):
        t, d = ev.get("type"), self.d
        if t == "meta":
            d["qid"] = ev.get("qid")
        elif t == "node":
            d["nodes"][ev["id"]] = {"status": ev["status"], "detail": ev.get("detail")}
        elif t == "pages":
            d["top10"] = ev["runs"].get("final")
        elif t == "sentence":
            while len(d["sentences"]) <= ev["index"]:
                d["sentences"].append({"text": "", "cites": []})
            s = d["sentences"][ev["index"]]
            s["text"] = (s["text"] + ev["delta"]).lstrip()
        elif t == "cites":
            d["sentences"][ev["index"]]["cites"] = ev["cites"]
        elif t == "verify":
            for r in ev["results"]:
                if r["index"] < len(d["sentences"]):
                    d["sentences"][r["index"]].update(status=r["status"], note=r.get("note"))
        elif t == "answer_reset":
            d["sentences"], d["table_rows"], d["cards"] = [], None, None
        elif t == "table":
            d["table_rows"] = ev["table"]
        elif t == "cards":
            d["cards"] = ev["cards"]
        elif t == "not_found":
            d["not_found"] = True
        elif t == "clarify":
            d["clarify"] = {k: v for k, v in ev.items() if k != "type"}
        elif t == "notice":
            d["notices"].append(ev["message"])
        elif t == "error":
            d["error"] = ev["message"]
        elif t == "done":
            d["elapsed"] = ev.get("elapsed")


class Cancelled(Exception):
    pass


def run_graph(body: AskBody, out: queue.Queue, cancel: threading.Event):
    """작업 스레드: 그래프를 돌려 이벤트를 큐에 넣는다. 끝나면(오류·중지 포함) 반드시 잠금을 푼다.
    (예전에는 응답 생성기 안에서 돌려서, 브라우저가 중간에 끊기면 잠금이 풀리지 않는 일이 있었음)"""
    seen: dict = {}
    t0 = time.time()
    run_id = str(uuid.uuid4())
    log = RunLog(run_id, body)

    def put(ev):
        if cancel.is_set():
            raise Cancelled()
        log.add(ev)
        out.put(ev)

    try:
        gt = P.QSETS.get(P.norm_q(body.question))
        put({"type": "meta", "sample": False, "qid": gt["qid"] if gt else None, "run_id": run_id})
        state = {"question": body.question.strip(), "nodes": body.nodes, "filters": [d for d in body.filters if d in P.SOURCES],
                 "attachments": body.attachments}
        for ev in graph().stream(state, stream_mode="custom"):
            if ev.get("type") == "node":
                seen[ev["id"]] = ev["status"]
            put(ev)
    except Cancelled:
        log.d["error"] = "사용자가 중지함"
    except Exception as e:
        ev = {"type": "error", "message": llm.mask(f"{type(e).__name__}: {e}")[:300]}
        log.add(ev)
        out.put(ev)
    finally:
        for n in NODES:   # 이번 경로에서 지나지 않은 노드
            if seen.get(n) in (None, "running"):
                out.put({"type": "node", "id": n, "status": "skipped", "detail": "이번 실행 경로에 없음" if n not in seen else "중단됨"})
        done = {"type": "done", "elapsed": round(time.time() - t0, 1)}
        log.add(done)
        out.put(done)
        out.put(None)
        BUSY.release()
        try:
            P.save_runtime_cache()
        except Exception:
            pass
        try:
            logstore.save_run(log.d)   # 질문 · 검색 상위 쪽 · 답변 · 판정을 run_id로 저장 (피드백이 여기에 이어짐)
        except Exception:
            pass


@app.post("/ask")
def ask(body: AskBody):
    load_dotenv(ENV, override=True)
    if not BUSY.acquire(blocking=False):
        busy = [{"type": "error", "message": "다른 질문을 처리하는 중입니다. 끝난 뒤 다시 보내 주세요."}, {"type": "done"}]
        return StreamingResponse(iter(sse(e) for e in busy), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    out: queue.Queue = queue.Queue()
    cancel = threading.Event()
    threading.Thread(target=run_graph, args=(body, out, cancel), daemon=True).start()

    def stream():
        try:
            while (ev := out.get()) is not None:
                yield sse(ev)
        finally:
            cancel.set()   # 브라우저가 끊기면 작업 스레드도 다음 이벤트에서 멈춤

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
