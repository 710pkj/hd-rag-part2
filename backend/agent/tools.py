"""에이전트 도구: 벡터 DB 검색(Part 1 검색기) · 판 비교표 조회 · 웹 검색(Tavily).

LangChain @tool로 만들어 두어 노드에서 .invoke()로 부르고, 노트북에서는 LLM에 bind_tools로 붙일 수도 있다.
"""
import os
import re

from langchain_core.tools import tool

from rag import part1 as P

DOC_LABEL = {"KR2022": "KR Notation Guide 2022", "KR2026": "KR Notation Guide 2026", "ABS2025": "ABS Notations and Symbols 2025"}


@tool
def search_documents(question: str, english_query: str = "", documents: list[str] | None = None,
                     rewrite: bool = True, broaden: bool = False) -> dict:
    """선급 노테이션 문서(KR 2022·KR 2026·ABS 2025)에서 질문과 관련된 페이지를 찾는다.
    Part 1 보고서의 최종 통합 구성(E27 포함, test nDCG@10 0.988): 구조 기반 청크의 dense+sparse 검색 → RRF →
    bge-reranker-v2-m3(한·영) → 선급 비교 병합(E27) → 판 비교 보정 → 구판 감점.
    documents: 검색할 문서 범위(없으면 질문에서 선급·연도를 읽어 정함). rewrite=False면 원 질문 그대로.
    broaden=True면 재검색: 영어 검색 문장을 주 질문으로 쓰고, 질문의 선급은 유지한 채 모든 판에서 찾는다."""
    stats: dict = {}
    if not rewrite:
        order, trace = P.search_v2(question, idx=P.IDX13, rr="ko", raw=True, allowed_override=documents, stats=stats)
    elif broaden:
        q = english_query or question
        socs = P.analyze_query(question)["societies"]          # 선급은 그대로, 판(연도) 제한만 푼다
        scope = documents or [P.DOC_OF[(s, y)] for s in socs for y in P.EDITIONS[s]]
        order, trace = P.search_v2(q, en=english_query or None, idx=P.IDX13, rr="both" if english_query else "ko",
                                   allowed_override=scope, stats=stats, society_merge_on=True)
    else:
        order, trace = P.search_v2(question, en=english_query or None, idx=P.IDX13,
                                   **{**P.FINAL27_OPTS, "rr": "both" if english_query else "ko"},
                                   allowed_override=documents, stats=stats)
    return {"ranking": order[:P.DEPTH], "top10": order[:P.TOP_K], "trace": trace, "stats": stats}


@tool
def edition_diff(pages: list[str], kind: str = "차이") -> list[dict]:
    """KR 2022↔2026 개정 요약표(Part 1에서 두 판 본문을 규칙으로 대조해 만든 표)에서 주어진 쪽과 관련된 행을 찾는다.
    kind: 신설·삭제·변경·차이 (차이는 모든 종류)."""
    kinds = P.BOOST_KINDS.get(kind, P.BOOST_KINDS["차이"])
    rank = {p: i for i, p in enumerate(pages)}   # pages는 검색 순위 순서. 상위 쪽의 행이 먼저 오게 정렬
    rows = []
    for r in P.DIFF.to_dict("records"):
        k = r["구분"].split(" (")[0]
        ps = {f"KR2022:{p}" for p in r["2022 쪽"].split()} | {f"KR2026:{p}" for p in r["2026 쪽"].split()}
        best = min((rank[p] for p in ps if p in rank), default=None)
        if best is not None and k in kinds:
            rows.append((best, {"절": r["절"], "구분": k, "노테이션": r["노테이션"], "2022 쪽": r["2022 쪽"], "2026 쪽": r["2026 쪽"]}))
    return [r for _, r in sorted(rows, key=lambda x: x[0])]


@tool
def web_search(query: str, max_results: int = 3) -> list[dict]:
    """Tavily 웹 검색. 문서에서 근거를 찾지 못했을 때만 쓴다."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    res = client.search(query=query, max_results=max_results, search_depth="basic")
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:900]} for r in res.get("results", [])]


def has_tavily() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY", "").strip())


# ───────── 근거 발췌: 긴 페이지에서 질문 단어가 많이 나오는 줄을 골라 LLM에 넘긴다 ─────────
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-]{1,}|[가-힣]{2,}")


def terms_of(*texts: str) -> set[str]:
    stop = {"the", "and", "for", "notation", "notations", "ships", "ship", "with", "which", "what", "rules", "노테이션", "관련", "기준", "선급"}
    return {w.lower() for t in texts if t for w in WORD_RE.findall(t) if w.lower() not in stop}


def excerpt(text: str, terms: set[str], limit: int = 1500) -> str:
    if len(text) <= limit:
        return text
    lines = [l for l in text.split("\n") if l.strip()]
    head = lines[:2]
    scored = sorted(range(2, len(lines)), key=lambda i: -sum(t in lines[i].lower() for t in terms))
    keep, size = set(), sum(map(len, head))
    for i in scored:
        if size + len(lines[i]) > limit:
            continue
        keep.add(i)
        size += len(lines[i])
    out, prev = list(head), 1
    for i in sorted(keep):
        if i > prev + 1:
            out.append("…")
        out.append(lines[i])
        prev = i
    return "\n".join(out)
