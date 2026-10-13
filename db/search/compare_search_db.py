"""검색 DB 두 곳(기본: 로컬 hdsearch와 Neon)의 표 내용을 해시로 비교한다. 접속 주소는 출력하지 않는다.

- 표 5개를 7가지로 나눠 비교: documents · pages · pipeline_versions · chunks의 일반 칸 · dense · sparse · rerank_scores
- 줄 순서는 키로 고정 (COLLATE "C": 서버 버전 · 로케일이 달라도 같은 순서)
- 다시 적재한 뒤 두 곳이 같은지 볼 때 씀 (설계서 3.5.6). 모두 같으면 종료 코드 0

실행 (저장소 맨 위에서):
    backend\\.venv\\Scripts\\python db\\search\\compare_search_db.py [A 주소] [B 주소]
A 기본: host=localhost port=5433 user=postgres dbname=hdsearch
B 기본: backend\\.env의 NEON_DATABASE_URL (비밀번호가 들어 있으니 명령줄보다 .env에 둠)
"""
import sys
import time
from pathlib import Path

import psycopg
from dotenv import dotenv_values

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
LOCAL = "host=localhost port=5433 user=postgres dbname=hdsearch"

C = 'COLLATE "C"'
QUERIES = {
    "documents": f"SELECT md5(string_agg(concat_ws('|', doc_id, society, year, source), ',' ORDER BY doc_id {C})) FROM documents",
    "pages": "SELECT md5(string_agg(concat_ws('|', page_id, doc_id, page_no, md5(coalesce(raw, '')), md5(coalesce(search_text, ''))),"
             f" ',' ORDER BY page_id {C})) FROM pages",
    "pipeline_versions": f"SELECT string_agg(concat_ws('|', pipeline_ver, rules_version, model, note), ',' ORDER BY pipeline_ver {C}) FROM pipeline_versions",
    "chunks (일반 칸)": "SELECT md5(string_agg(concat_ws('|', chunker, chunk_id, ord, page_id, doc_id, md5(text), content_hash, pipeline_ver),"
                      f" ',' ORDER BY chunker {C}, ord)) FROM chunks",
    "chunks (dense)": f"SELECT md5(string_agg(md5(dense::text), ',' ORDER BY chunker {C}, ord)) FROM chunks",
    "chunks (sparse)": f"SELECT md5(string_agg(md5(sparse::text), ',' ORDER BY chunker {C}, ord)) FROM chunks",
    "rerank_scores": "SELECT md5(string_agg(concat_ws('|', md5(query), passage_hash, model, score),"
                     f" ',' ORDER BY md5(query) {C}, passage_hash {C}, model {C})) FROM rerank_scores",
}


def digest(name: str, url: str) -> dict | None:
    t0 = time.time()
    try:
        with psycopg.connect(url, connect_timeout=30) as conn:
            ver = conn.execute("SHOW server_version").fetchone()[0].split()[0]
            out = {k: conn.execute(q).fetchone()[0] for k, q in QUERIES.items()}
    except Exception as e:                 # 오류 문장에 호스트가 들어갈 수 있어 종류만 보임
        print(f"{name}: 접속 · 조회 실패 ({type(e).__name__})")
        return None
    print(f"{name}: PostgreSQL {ver} · {time.time() - t0:.1f}초")
    return out


def main() -> int:
    a_url = sys.argv[1] if len(sys.argv) > 1 else LOCAL
    b_url = sys.argv[2] if len(sys.argv) > 2 else (dotenv_values(ROOT / "backend" / ".env").get("NEON_DATABASE_URL") or "").strip()
    if not b_url:
        print("비교할 B 주소가 없음: backend\\.env에 NEON_DATABASE_URL을 넣거나 두 번째 인자로 줌")
        return 2
    a, b = digest("A", a_url), digest("B", b_url)
    if a is None or b is None:
        return 2
    same = 0
    for k in QUERIES:
        ok = a[k] == b[k]
        same += ok
        shown = a[k] if k == "pipeline_versions" else f"{(a[k] or '')[:12]}…"
        print(f"  {'같음' if ok else '다름'}  {k:18} {shown}")
    print(f"{same}/{len(QUERIES)} 같음")
    return 0 if same == len(QUERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
