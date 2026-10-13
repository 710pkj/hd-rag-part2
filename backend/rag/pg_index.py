"""PostgreSQL + pgvector 색인 (이 PC의 로컬 DB hdsearch 또는 Neon). RAG_SQL연동.ipynb 셀 25(SQL 4. PgIndex)를 그대로 옮겼다.

FAISS 색인(HybridIndex)과 호출 모양이 같아서 search_v2는 고치지 않는다:
scores()는 질문 벡터만 들고 있다가, ranked_pages()에서 SQL 한 문장으로
허용 문서 거르기 → 청크 점수(내적 <#>) → 페이지별 최고점 → 상위 depth쪽을 받는다.
점수가 같으면 FAISS 경로처럼 원래 행 번호(ord)가 앞선 청크·페이지가 먼저 온다.

더한 것: 연결이 끊기면 다시 접속한다 (Neon은 5분 쉬면 절전하며 끊김, 로컬 DB는 서버를 껐다 켜면 끊김).
그래도 SQL이 실패하면 그 호출만 FAISS 색인으로 대신한다 (결과는 같음을 Colab · Neon · 로컬 DB에서 검증).
"""
import socket
import threading
import time

import numpy as np

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def endpoint(url: str) -> tuple[str, int]:
    """접속 주소의 (호스트, 포트). 주소 · 비밀번호는 내보내지 않는다"""
    from psycopg.conninfo import conninfo_to_dict

    d = conninfo_to_dict(url)
    return (d.get("host") or "localhost").split(",")[0].lower(), int(str(d.get("port") or 5432).split(",")[0])


def fail_fast_if_down(url: str, timeout: float = 0.5) -> None:
    """이 PC의 DB면 포트가 접속을 받는지 먼저 본다 (꺼져 있으면 OSError).
    Windows에서는 꺼진 포트에 psycopg로 바로 접속하면 거절이 곧바로 오지 않아, 주소(::1 · 127.0.0.1)와
    방식마다 connect_timeout까지 기다림 → 15초 제한이면 약 1분 (백엔드 준비 · 검색 한 번이 그만큼 멈춤)"""
    host, port = endpoint(url)
    if host in LOCAL_HOSTS:
        socket.create_connection((host, port), timeout=timeout).close()


class Db:
    """psycopg 연결 하나를 잠금으로 감싸고, 끊기면 다시 접속한다"""

    def __init__(self, url: str):
        self.url = url
        self.conn = None
        self.lock = threading.Lock()
        self.calls, self.ms, self.reconnects = 0, 0.0, 0

    def _connect(self):
        import psycopg
        from pgvector.psycopg import register_vector

        fail_fast_if_down(self.url)   # 로컬 DB가 꺼져 있으면 OSError → 서버를 켤 때는 FAISS, 검색 중이면 그 호출만 FAISS
        self.conn = psycopg.connect(self.url, autocommit=True, connect_timeout=15, keepalives=1, keepalives_idle=30)
        register_vector(self.conn)

    def execute(self, sql, params=None):
        import psycopg

        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.conn is None or self.conn.closed:
                        if self.conn is not None:
                            self.reconnects += 1
                        self._connect()
                    t0 = time.perf_counter()
                    rows = self.conn.execute(sql, params).fetchall()
                    self.calls += 1
                    self.ms += (time.perf_counter() - t0) * 1000
                    return rows
                except (psycopg.OperationalError, psycopg.InterfaceError):
                    self.conn = None
                    if attempt == 2:
                        raise


class PgIndex:
    SQL = """
        SELECT page_id, score FROM (
            SELECT page_id, ord, -({col} <#> %(q)s) AS score,
                   row_number() OVER (PARTITION BY page_id ORDER BY {col} <#> %(q)s, ord) AS rn
            FROM chunks
            WHERE chunker = %(chunker)s AND doc_id = ANY(%(allowed)s)
        ) t
        WHERE rn = 1 {positive}
        ORDER BY score DESC, ord
        LIMIT %(depth)s"""

    def __init__(self, db: Db, chunker: str, vocab_size: int, fallback=None, depth=50):
        self.db, self.chunker, self.vocab_size, self.fallback, self.depth = db, chunker, vocab_size, fallback, depth
        self.n_chunks = db.execute("SELECT count(*) FROM chunks WHERE chunker = %s", (chunker,))[0][0]
        self.fallback_calls = 0
        self.last_error = None

    def scores(self, channel, qv):
        return channel, qv

    def ranked_pages(self, spec, allowed_docs, depth=None, positive_only=False):
        from pgvector import SparseVector

        channel, qv = spec
        depth = depth or self.depth
        if channel == "dense":
            col, q = "dense", np.asarray(qv["dense"], dtype=np.float32)
        elif channel == "sparse":
            if not qv["sparse"]:
                return []
            col, q = "sparse", SparseVector(qv["sparse"], self.vocab_size)
        else:
            raise ValueError(f"{channel}: SQL 색인에는 dense · sparse만 있음 (최종 구성이 쓰는 채널)")
        sql = self.SQL.format(col=col, positive="AND score > 0" if positive_only else "")
        try:
            rows = self.db.execute(sql, {"q": q, "chunker": self.chunker, "allowed": sorted(allowed_docs), "depth": depth})
            return [(p, float(s)) for p, s in rows]
        except Exception as e:   # 인터넷이 끊기는 등 → 이 호출만 FAISS로
            if self.fallback is None:
                raise
            self.fallback_calls += 1
            self.last_error = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
            fb = self.fallback
            return fb.ranked_pages(fb.scores(channel, qv), allowed_docs, depth=depth, positive_only=positive_only)
