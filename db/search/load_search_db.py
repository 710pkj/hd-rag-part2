"""로컬 PostgreSQL에 검색용 DB(hdsearch)를 만들고, Neon과 같은 표 5개를 캐시에서 채운다.

- 표 · 칸 · 제약 · 색인은 Neon(RAG_SQL연동.ipynb 셀 23)과 같음 → schema.sql
- 값도 Neon 적재(셀 24)와 같은 방법으로 넣음: 백엔드가 만드는 쪽 · 청크(struct · e13_2),
  임베딩 캐시(cache/bge_m3_cache.pkl), 리랭커 점수 캐시(cache/score_cache.pkl, GPU fp16 값만)
- 모델 · LLM은 부르지 않음 (캐시에 없는 값이 나오면 멈춤). 다시 돌려도 중복되지 않음 (ON CONFLICT DO NOTHING)
- 판본 비교 DB(hdrag)와는 DB를 나눔: 이름이 같고 구조가 다른 documents · pages가 부딪치지 않게 (설계서 3.5.4)

실행 (저장소 맨 위에서, 로컬 PostgreSQL이 켜져 있어야 함):
    backend\\.venv\\Scripts\\python db\\search\\load_search_db.py [접속 주소]
기본 접속 주소: host=localhost port=5433 user=postgres dbname=hdsearch (이 PC 안에서만 받는 서버라 비밀번호 없음)
다 넣은 뒤 backend\\.env의 DATABASE_URL을 postgresql://postgres@localhost:5433/hdsearch 로 바꾸면 에이전트가 이 DB로 검색한다.
"""
import hashlib
import os
import pickle
import sys
import time
from pathlib import Path

os.environ["VECTOR_DB"] = "faiss"     # 적재할 때는 backend\.env의 원격 DB에 붙지 않음. import 전에 정해야 함
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402
from pgvector import SparseVector  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from rag import part1 as P  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LOCAL_SEARCH_URL", "host=localhost port=5433 user=postgres dbname=hdsearch")
PIPE_VER = "v1"
RERANK_TAG = "BAAI/bge-reranker-v2-m3|fp16"
nz = lambda s: s.replace(chr(0), "") if isinstance(s, str) else s     # Postgres text에는 NUL 문자를 못 넣음


def blocked(*a, **k):
    raise RuntimeError("캐시에 없는 값 → 모델 호출 시도 (적재는 캐시만 씀)")


def ensure_database(url: str) -> None:
    """대상 DB가 없으면 같은 서버의 postgres DB로 접속해 만든다"""
    params = conninfo_to_dict(url)
    name = params.get("dbname") or "hdsearch"
    with psycopg.connect(make_conninfo(**{**params, "dbname": "postgres"}), autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            c.execute(f'CREATE DATABASE "{name}"')
            print(f"DB 만듦: {name}")


def main():
    t0 = time.time()
    P.M3.encode = blocked
    P.cross_reranker = blocked
    P.groq_json = blocked
    P.init(verbose=False)                       # 쪽 · 청크 · FAISS 색인을 캐시로 만듦 (제출 노트북과 같은 코드)
    print(f"검색기 준비 {time.time() - t0:.0f}초 · 쪽 {len(P.pages)} · 청크 struct {len(P.IDX_E9.chunks)} / e13_2 {len(P.IDX13.chunks)}")

    ensure_database(URL)
    conn = psycopg.connect(URL, autocommit=True)
    conn.execute((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
    register_vector(conn)
    server = conn.execute("SHOW server_version").fetchone()[0]
    pgv = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
    print(f"PostgreSQL {server.split()[0]} · pgvector {pgv} · DB {conn.info.dbname}")

    t1 = time.time()
    rules_hash = hashlib.sha1((P.DATA_DIR / "rules.csv").read_bytes()).hexdigest()[:12]
    model_tag = f"{P.M3.name}|max_length={P.M3.max_length}"
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO documents (doc_id, society, year, source) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(d, s, y, f) for d, (f, s, y) in P.SOURCES.items()])
        cur.executemany("INSERT INTO pages (page_id, doc_id, page_no, raw, search_text) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(r.page_id, r.doc_id, int(r.page), nz(r.raw), nz(r.search_text)) for r in P.pages.itertuples()])
        cur.execute("INSERT INTO pipeline_versions (pipeline_ver, rules_version, model, note) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (PIPE_VER, rules_hash, model_tag, "제출 노트북과 같은 전처리 · rules.csv 44개 규칙"))
    # 같은 버전 이름에 다른 규칙이 들어가면 멈춤 (일관성 장치)
    saved = conn.execute("SELECT rules_version, model FROM pipeline_versions WHERE pipeline_ver = %s", (PIPE_VER,)).fetchone()
    assert saved == (rules_hash, model_tag), f"{PIPE_VER}의 규칙이 지금과 다름: DB {saved} · 지금 {(rules_hash, model_tag)}"

    cache = P.EmbeddingCache(P.CACHE_DIR / "bge_m3_cache.pkl")
    for chunker, idx in (("struct", P.IDX_E9), ("e13_2", P.IDX13)):
        ch = idx.chunks
        dense, sparse = cache.get(ch.dense_text.tolist())      # FAISS에 넣은 것과 같은 값 (fp16 캐시 → fp32)
        rows = [(chunker, r.chunk_id, i, r.page_id, r.doc_id, nz(r.dense_text), cache.key(r.dense_text), PIPE_VER,
                 dense[i], SparseVector({int(k): float(v) for k, v in sparse[i].items()}, P.VOCAB_SIZE))
                for i, r in enumerate(ch.itertuples())]
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO chunks (chunker, chunk_id, ord, page_id, doc_id, text, content_hash, pipeline_ver, dense, sparse)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", rows)
        n = conn.execute("SELECT count(*) FROM chunks WHERE chunker = %s", (chunker,)).fetchone()[0]
        assert n == len(ch), f"{chunker}: DB {n}개 vs 색인 {len(ch)}개"

    with open(P.CACHE_DIR / "score_cache.pkl", "rb") as f:       # 제출 캐시의 점수만 (Colab T4 GPU fp16). 이 PC에서 새로 계산한 점수는 넣지 않음
        cross = pickle.load(f)["CROSS_MEMO"]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO rerank_scores (query, passage_hash, model, score) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(q, h, RERANK_TAG, float(s)) for (q, h), s in cross.items()])

    counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("documents", "pages", "pipeline_versions", "chunks", "rerank_scores")}
    by_ver = conn.execute("SELECT pipeline_ver, chunker, count(*) FROM chunks GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    size = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    print("줄 수:", " · ".join(f"{t} {n:,}" for t, n in counts.items()))
    print("처리 버전별 청크:", " · ".join(f"{v}/{c} {n:,}" for v, c, n in by_ver))
    print(f"DB 크기 {size} · 적재 {time.time() - t1:.1f}초 · 전체 {time.time() - t0:.0f}초")
    conn.close()


if __name__ == "__main__":
    main()
