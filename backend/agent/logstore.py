"""질문 · 답변 실행 기록과 사용자 피드백 저장.

LOG_DATABASE_URL(기본: 이 PC의 로컬 PostgreSQL localhost:5433/hdrag)에 표 두 개(agent_runs · agent_feedback)를 두고 쓴다.
접속이 안 되면 backend/cache_runtime/logs/의 JSONL 파일에 같은 내용을 쓴다 (기록이 빠지지 않게).
쌓인 기록은 dev 질문 보강과 실패 분석의 재료가 된다 (질문 · 검색 상위 쪽 · 답변 · 판정 · 피드백이 run_id로 이어짐)."""
import json
import os
import threading
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "cache_runtime" / "logs"
DEFAULT_URL = "host=localhost port=5433 user=postgres dbname=hdrag"
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      uuid PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    question    text NOT NULL,
    filters     jsonb NOT NULL DEFAULT '[]',
    qid         text,                       -- dev · test 질문이면 그 번호
    top10       jsonb,                      -- 에이전트 검색 상위 10쪽
    sentences   jsonb,                      -- [{text, cites, status, note}]
    table_rows  jsonb,                      -- 비교표 · 변경 표
    cards       jsonb,                      -- 노테이션 카드
    not_found   boolean NOT NULL DEFAULT false,
    clarify     jsonb,                      -- 가정 · 되묻기
    nodes       jsonb,                      -- 노드별 마지막 상태 · 설명
    notices     jsonb,
    error       text,
    elapsed     real
);
CREATE TABLE IF NOT EXISTS agent_feedback (
    id          serial PRIMARY KEY,
    run_id      uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    rating      text NOT NULL CHECK (rating IN ('up', 'down')),
    reasons     text[] NOT NULL DEFAULT '{}',
    comment     text
);
CREATE INDEX IF NOT EXISTS agent_feedback_run ON agent_feedback (run_id);
"""
_lock = threading.Lock()
_conn = None
_mode = None          # "postgres" | "jsonl"


def _db():
    """로컬 PostgreSQL 연결 (처음 한 번 표를 만듦). 안 되면 None → JSONL"""
    global _conn, _mode
    if _mode == "jsonl":
        return None
    if _conn is not None and not _conn.closed:
        return _conn
    try:
        import psycopg

        _conn = psycopg.connect(os.environ.get("LOG_DATABASE_URL", "").strip() or DEFAULT_URL, autocommit=True, connect_timeout=2)
        _conn.execute(SCHEMA)
        _mode = "postgres"
        return _conn
    except Exception:
        _conn, _mode = None, "jsonl"
        return None


def mode() -> str:
    with _lock:
        _db()
        return _mode or "jsonl"


def _jsonl(name: str, row: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / name, "a", encoding="utf-8") as f:
        f.write(json.dumps({**row, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")


def save_run(run: dict) -> str:
    """run: run_id, question, filters, qid, top10, sentences, table_rows, cards, not_found, clarify, nodes, notices, error, elapsed"""
    with _lock:
        db = _db()
        if db is not None:
            try:
                from psycopg.types.json import Jsonb

                cols = ["run_id", "question", "filters", "qid", "top10", "sentences", "table_rows", "cards", "not_found",
                        "clarify", "nodes", "notices", "error", "elapsed"]
                js = {"filters", "top10", "sentences", "table_rows", "cards", "clarify", "nodes", "notices"}
                vals = [Jsonb(run.get(c)) if c in js and run.get(c) is not None else run.get(c) for c in cols]
                vals[cols.index("filters")] = Jsonb(run.get("filters") or [])
                vals[cols.index("not_found")] = bool(run.get("not_found"))
                db.execute(f"INSERT INTO agent_runs ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", vals)
                return "postgres"
            except Exception:
                pass
        _jsonl("agent_runs.jsonl", run)
        return "jsonl"


def save_feedback(run_id: str, rating: str, reasons: list[str], comment: str | None) -> str:
    with _lock:
        db = _db()
        if db is not None:
            try:
                db.execute("INSERT INTO agent_feedback (run_id, rating, reasons, comment) VALUES (%s, %s, %s, %s)",
                           (run_id, rating, reasons, comment or None))
                return "postgres"
            except Exception:
                pass
        _jsonl("agent_feedback.jsonl", {"run_id": run_id, "rating": rating, "reasons": reasons, "comment": comment})
        return "jsonl"
