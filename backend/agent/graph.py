"""선급 문서 기술검토 에이전트 (LangGraph).

질문 분석 → 검색어 정리 → 검색 → 판 비교 → 근거 판정 ─┬─ 답변 생성 → 근거 검증 ─┬─ 끝
                       ▲                      │              ▲            │
                       └──── 재검색(1회) ─────┤              └─ 다시 생성 ─┘ (근거 없는 문장이 있으면 1회)
                                              └─ 웹 검색(문서에 근거가 없을 때만) ─→ 답변 생성

각 노드는 get_stream_writer()로 진행 이벤트를 보낸다. 웹 서버는 stream_mode="custom"으로 받아 SSE로 넘긴다.
이벤트 형식은 web/src/lib/types.ts의 AskEvent와 같다.
화면용 이벤트: 질문 분석이 가정 · 되묻기(clarify), 근거가 없으면 답변 생성이 찾지 못함(not_found),
최종 답이 정해지면 finalize()가 인용 구절(passages) · 질문 유형별 표(table) 또는 노테이션 카드(cards)를 보낸다 (agent/present.py).
"""
import re
import time
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from rag import entities as ENT
from rag import part1 as P
from rag import query_intent as QI

from . import llm, present
from .tools import DOC_LABEL, edition_diff, excerpt, has_tavily, search_documents, terms_of, web_search

DOC_SHORT = {"KR2022": "KR 2022", "KR2026": "KR 2026", "ABS2025": "ABS 2025"}
MAX_CONTEXT_PAGES = 4
GRADE_PAGES = 5


MULTI_EXTRA = 3        # 선급 비교 질문은 근거 판정에 3쪽 더, 답변 근거에 2쪽 더
MIN_PER_SOCIETY = 2


def multi_society(trace) -> bool:
    return len(trace.get("societies") or []) >= 2


def pick_pages(ranking, trace, n):
    """상위 n쪽. 선급이 둘 이상인 질문(선급 비교)은 n+3쪽을 고르고, 선급마다 최소 2쪽이 들어가게 한다
    (KR·ABS 비교에서 상위가 ABS로만 채워져 KR 근거가 빠지는 일을 막음)"""
    if not multi_society(trace):
        return ranking[:n]
    soc_of = lambda p: P.SOURCES[p.split(":")[0]][1]
    out = list(ranking[:n + MULTI_EXTRA])
    for s in trace["societies"]:
        have = [p for p in out if soc_of(p) == s]
        add = [p for p in ranking if soc_of(p) == s and p not in out][:max(0, MIN_PER_SOCIETY - len(have))]
        if add:
            others = [p for p in out if soc_of(p) != s]
            drop = set(others[len(others) - len(add):])   # 다른 선급의 맨 아래 쪽을 내보냄
            out = [p for p in out if p not in drop] + add
    return out


class AgentState(TypedDict, total=False):
    question: str
    nodes: dict            # 노드 켜고 끄기 {"rewrite": False, ...}
    filters: list          # 사용자가 고른 문서 범위
    attachments: list
    gt: dict | None        # dev·test 질문이면 정답 {"qid", "rels", "qtype"}
    analysis: dict
    en_query: str
    ranking: list
    trace: dict
    attempt: int
    diff_rows: list
    grade: dict
    web: list
    sentences: list
    verify: list
    gen_round: int
    feedback: str
    first_pages: list      # 첫 검색의 상위 쪽 (재검색이 더 나쁠 때 대비)
    table: list            # 선급 비교표 행 (답변 생성 LLM이 함께 만들고 근거 검증을 거침)
    not_found: bool        # 근거를 찾지 못해 답하지 않음


def on(state, node):
    return state.get("nodes", {}).get(node) is not False


def emit(**event):
    get_stream_writer()(event)


def node_event(nid, status, detail=None):
    emit(type="node", id=nid, status=status, **({"detail": detail} if detail else {}))


# ───────────────────────── 노드 ─────────────────────────
def analyze(state: AgentState):
    node_event("analyze", "running")
    q = state["question"]
    info, qi = P.analyze_query(q), QI.analyze(q)
    gt = P.QSETS.get(P.norm_q(q))
    parts = [f"선급 {'+'.join(info['societies'])}",
             f"연도 {'·'.join(str(y) for y, _ in info['years']) or '없음 → 최신판 우선'}",
             f"의도 {qi['intent'] or '일반'}" + (f" ({qi['policy']})" if qi["policy"] else "")]
    allowed, _ = P.allowed_docs(info)
    scope = state.get("filters") or sorted(allowed)
    parts.append(("문서 범위 지정: " if state.get("filters") else "검색 문서: ") + ", ".join(DOC_SHORT[d] for d in scope))
    if gt:
        parts.append(f"정답이 있는 {gt['qid']} 질문")
    if state.get("attachments"):
        parts.append(f"첨부 {len(state['attachments'])}개는 아직 처리하지 않음")
    c = present.clarify(q, state.get("filters") or [], {**info, **qi})
    if c:   # 막지 않는 되묻기: 기본 가정으로 답하고, 다른 범위로 다시 물을 버튼을 준다
        emit(type="clarify", **c)
        parts.append("가정: " + c["assumption"])
    node_event("analyze", "done", " · ".join(parts))
    return {"analysis": {**info, **qi}, "gt": gt, "attempt": 0, "gen_round": 0, "web": [], "diff_rows": [], "table": [],
            "not_found": False}


def rewrite(state: AgentState):
    if not on(state, "rewrite"):
        node_event("rewrite", "skipped", "꺼짐: 원 질문 그대로 검색")
        return {"en_query": ""}
    node_event("rewrite", "running")
    q, qi = state["question"], state["analysis"]
    ko = P.strip_intent(P.clean_query(QI.topic_query(q, qi)), "A")
    en, note = "", ""
    try:
        en = P.english_query(q)
    except Exception as e:   # 키가 없거나 Groq 오류면 한국어 검색어만 쓴다
        note = f" · 영어 검색 문장 없음 ({str(e)[:60]})"
    node_event("rewrite", "done", f"주제 “{ko}”" + (f" · 영어 “{en}”" if en else "") + note)
    return {"en_query": en}


def retrieve(state: AgentState):
    attempt = state.get("attempt", 0) + 1
    node_event("retrieve", "running", "재검색: 영어 검색 문장으로, 같은 선급의 모든 판에서" if attempt > 1 else None)
    t0 = time.time()
    db = P.VECTOR_DB["db"]
    calls0, ms0 = (db.calls, db.ms) if db else (0, 0.0)
    res = search_documents.invoke({"question": state["question"], "english_query": state.get("en_query", ""),
                                   "documents": state.get("filters") or None, "rewrite": on(state, "rewrite"),
                                   "broaden": attempt > 1})
    top = res["top10"]
    counts: dict = {}
    for p in top:
        counts[p.split(":")[0]] = counts.get(p.split(":")[0], 0) + 1
    st = res["stats"]
    sql_ms = db.ms - ms0 if db else 0.0
    detail = (f"{'재검색 ' if attempt > 1 else ''}top-10: " + ", ".join(f"{DOC_SHORT[d]} {n}쪽" for d, n in counts.items())
              + f" · 리랭커 {'한·영' if state.get('en_query') else '한국어'}"
              + (" · 선급 비교 병합(E27)" if res["trace"].get("society_merge") else "")
              + (f" · 새로 계산한 리랭커 점수 {st['rerank_new']}개 ({st['rerank_sec']:.0f}초)" if st.get("rerank_new") else " · 점수 캐시 사용")
              + (f" · 1단계 검색 SQL {db.calls - calls0}번 {f'{sql_ms:.0f}ms' if sql_ms < 1000 else f'{sql_ms / 1000:.1f}초'}"
                 f" ({P.VECTOR_DB['name']})" if db else " · 1단계 검색 FAISS")
              + f" · {time.time() - t0:.1f}초")
    runs, meta = {"final": top}, [{"key": "final", "label": "에이전트 검색", "note": "Part 1 보고서 최종 통합(E27 포함) 구성으로 이번에 검색한 결과"}]
    gt = state.get("gt")
    if gt and attempt == 1:
        e9, _ = P.search_v2(state["question"], idx=P.IDX_E9)
        runs["e9"] = e9[:P.TOP_K]
        meta.append({"key": "e9", "label": "E9 기준 구성", "note": "Part 1 보고 값 구성 (dev로 고름)"})
    emit(type="pages", runs=runs, rels=gt["rels"] if gt else None, defaultRun="final", runMeta=meta)
    node_event("retrieve", "done", detail)
    out = {"ranking": res["ranking"], "trace": res["trace"], "attempt": attempt}
    if attempt == 1:
        out["first_pages"] = pick_pages(res["ranking"], res["trace"], MAX_CONTEXT_PAGES)[:MAX_CONTEXT_PAGES + 2]
    return out


def diff(state: AgentState):
    c = state["trace"].get("compare")
    if not c:
        node_event("diff", "skipped", "판 비교 질문이 아님")
        return {}
    if not on(state, "diff"):
        node_event("diff", "skipped", "꺼짐")
        return {}
    node_event("diff", "running")
    kind, prefer, _ = c
    rows = edition_diff.invoke({"pages": state["ranking"][:P.TOP_K], "kind": kind})
    shown = "; ".join(f"{r['절']} {r['구분']}: {r['노테이션']}" for r in rows[:4])
    node_event("diff", "done", f"KR 개정표에서 {len(rows)}건 ({kind})" + (f" — {shown}" if shown else ""))
    return {"diff_rows": rows[:12]}


def grade(state: AgentState):
    top = pick_pages(state["ranking"], state["trace"], GRADE_PAGES)
    if not on(state, "grade"):
        node_event("grade", "skipped", "꺼짐: 상위 페이지를 그대로 근거로 씀")
        return {"grade": {"answerable": True, "pages": top[:MAX_CONTEXT_PAGES], "reason": ""}}
    if not llm.has_key():
        node_event("grade", "skipped", "GROQ_API_KEY 없음")
        return {"grade": {"answerable": True, "pages": top[:MAX_CONTEXT_PAGES], "reason": ""}}
    node_event("grade", "running")
    terms = terms_of(state["question"], state.get("en_query", ""))
    ctx = "\n\n".join(f"[{p}]\n{excerpt(P.PAGE_TEXT[p], terms, 900)}" for p in top)
    if state.get("diff_rows"):   # 판 비교 질문이면 개정표도 근거로 본다 (페이지만으로는 두 판의 차이가 안 보임)
        ctx += "\n\n[tool:edition-diff] KR 2022→2026 revision table\n" + diff_text(state["diff_rows"])
    out = llm.chat_json(GRADE_SYSTEM, f"Question: {state['question']}\n\nPages:\n{ctx}", fast=True, max_tokens=600)
    limit = MAX_CONTEXT_PAGES + (2 if multi_society(state["trace"]) else 0)
    pages = [p for p in out.get("relevant_pages", []) if p in top][:limit]
    ok = bool(out.get("answerable")) and (bool(pages) or bool(state.get("diff_rows")))
    fallback = top[:MAX_CONTEXT_PAGES]
    if not ok and state.get("attempt", 1) > 1 and state.get("first_pages"):
        fallback = state["first_pages"]   # 재검색도 실패하면 첫 검색의 상위 쪽을 근거로 쓴다
    g = {"answerable": ok, "pages": pages or fallback, "reason": str(out.get("reason", ""))}
    node_event("grade", "done", f"{'답할 수 있음' if ok else '근거 부족'} · 근거 페이지 {', '.join(pages) or '없음'}" + (f" · {g['reason']}" if g["reason"] else "") + llm.model_note())
    return {"grade": g}


def web(state: AgentState):
    node_event("web", "running")
    q = state.get("en_query") or state["question"]
    try:
        res = web_search.invoke({"query": f"{q} classification society notation", "max_results": 3})
    except Exception as e:
        node_event("web", "done", f"웹 검색 실패: {str(e)[:80]}")
        return {"web": []}
    items = [{"id": f"web:{i + 1}", **r} for i, r in enumerate(res)]
    emit(type="web", results=[{"id": r["id"], "title": r["title"], "url": r["url"]} for r in items])
    node_event("web", "done", f"웹 결과 {len(items)}건 (문서 근거와 구분해 표시)")
    return {"web": items}


def generate(state: AgentState):
    rnd = state.get("gen_round", 0) + 1
    if rnd > 1:
        emit(type="answer_reset")
    node_event("generate", "running", "근거 없는 문장을 고쳐 다시 생성" if rnd > 1 else None)
    if not llm.has_key():
        sents = [{"text": "GROQ_API_KEY가 없어 답변을 만들 수 없습니다. backend/.env에 키를 넣고 백엔드를 다시 시작하세요.", "cites": []}]
        stream_sentences(sents)
        node_event("generate", "done", "키 없음")
        return {"sentences": sents, "gen_round": rnd}
    g = state.get("grade") or {}
    if g and not g.get("answerable", True) and state.get("attempt", 1) >= 2 and not state.get("web"):
        # 재검색까지 했는데도 근거가 없고 웹 결과도 없으면, 지어내지 않고 "찾지 못함"으로 답한다
        sents = [{"text": "검색한 문서에서 이 질문에 답할 근거를 찾지 못했습니다.", "cites": []}]
        emit(type="not_found", reason=g.get("reason") or "근거 판정에서 관련 페이지를 찾지 못함",
             nearest=list(state.get("ranking", [])[:5]))
        stream_sentences(sents)
        node_event("generate", "done", "근거 부족 → 답하지 않음 (가까운 페이지만 안내)")
        return {"sentences": sents, "gen_round": rnd, "not_found": True, "table": []}
    sources = context_sources(state)
    lang = "Korean" if re.search(r"[가-힣]", state["question"]) else "English"   # 질문 언어로 답하게 명시
    user = (f"Question: {state['question']}\nAnswer language: {lang}\n\nSources:\n"
            + "\n\n".join(f"[{s['id']}] {s['title']}\n{s['text']}" for s in sources))
    # 비교표는 질문에 선급이 둘 이상 '적혀' 있을 때만 (선급이 없는 질문도 내부에서는 KR · ABS 모두로 찾지만 비교 질문은 아님)
    socs = [s for s, rx in QI.SOCIETY_RE.items() if rx.search(state["question"])]
    compare = len(socs) >= 2
    if compare:   # 선급 비교 질문이면 비교표도 함께 (행마다 인용 → 근거 검증에서 문장처럼 판정)
        user += TABLE_TASK.format(cols=", ".join(f'"{s}": "<short text or ->"' for s in socs))
    if rnd > 1 and state.get("feedback"):
        user += (f"\n\nA checker found these sentences in your previous answer NOT supported by their cited sources:\n{state['feedback']}\n"
                 "Write the answer again. Delete each of those claims unless a source above states it explicitly; do not repeat them. "
                 "If a source shows something is absent from a list, you may say it is not listed there.")
    out = llm.chat_json(GENERATE_SYSTEM, user, max_tokens=2400 if compare else 1800)
    valid = {s["id"] for s in sources}
    sents = []
    for s in out.get("sentences", []):
        if not isinstance(s, dict):   # 대체 모델이 문장을 글자열로만 줄 때
            s = {"text": str(s), "cites": []}
        text, inline = strip_inline_ids(" ".join(str(s.get("text", "")).split()))
        if text:   # 문장 안에 직접 쓴 출처 id는 떼어 인용으로 옮긴다
            sents.append({"text": text, "cites": [c for c in dict.fromkeys([*s.get("cites", []), *inline]) if c in valid]})
    if not sents:
        sents = [{"text": "문서에서 이 질문에 답할 근거를 찾지 못했습니다.", "cites": []}]
    table = []
    for r in (out.get("table") or [])[:6] if compare else []:
        if isinstance(r, dict) and str(r.get("item", "")).strip():
            vals = {s: strip_inline_ids(" ".join(str(r.get(s, "-")).split()))[0] or "-" for s in socs}
            table.append({"item": " ".join(str(r["item"]).split()), "vals": vals,
                          "cites": [c for c in dict.fromkeys(r.get("cites") or []) if c in valid]})
    stream_sentences(sents)
    node_event("generate", "done", f"문장 {len(sents)}개 · 인용 {sum(len(s['cites']) for s in sents)}개 · 근거 {len(sources)}건"
               + (f" · 비교표 {len(table)}행" if table else "") + (f" · {rnd}번째 생성" if rnd > 1 else "") + llm.model_note())
    return {"sentences": sents, "gen_round": rnd, "table": table}


def verify(state: AgentState):
    sents = state["sentences"]
    rows = state.get("table") or []
    if not on(state, "verify"):
        node_event("verify", "skipped", "꺼짐")
        finalize(state, sents)
        return {"verify": []}
    if not llm.has_key() or not any(s["cites"] for s in sents):
        node_event("verify", "skipped", "인용이 없음" if llm.has_key() else "GROQ_API_KEY 없음")
        finalize(state, sents)
        return {"verify": []}
    node_event("verify", "running")
    by_id = {s["id"]: s for s in context_sources(state)}
    row_sents = [{"text": f"{r['item']} — " + "; ".join(f"{k}: {v}" for k, v in r["vals"].items()), "cites": r["cites"]} for r in rows]
    judged_all = sents + row_sents                      # 비교표 행도 문장처럼 판정 (번호는 문장 뒤에 이어 붙임)
    used = sorted({c for s in judged_all for c in s["cites"]})
    ctx = "\n\n".join(f"[{c}]\n{by_id[c]['text']}" for c in used if c in by_id)
    lines = "\n".join(f"{i}. {s['text']}  (cites: {', '.join(s['cites']) or 'none'})" for i, s in enumerate(judged_all))
    out = llm.chat_json(VERIFY_SYSTEM, f"Question: {state['question']}\n\nSources:\n{ctx}\n\nSentences:\n{lines}", fast=True,
                        max_tokens=900 + 120 * len(rows))
    judged = {int(r.get("index", -1)): r for r in out.get("results", []) if str(r.get("index", "")).lstrip("-").isdigit()}
    row_status = []
    for k, r in enumerate(row_sents):
        j = judged.get(len(sents) + k, {})
        st = j.get("status") if j.get("status") in ("supported", "inferred", "unsupported") else "inferred"
        if not r["cites"] and st == "supported":
            st = "inferred"
        row_status.append({"status": st, "note": str(j.get("note", ""))})
    results = []
    for i, s in enumerate(sents):
        r = judged.get(i, {})
        status = r.get("status") if r.get("status") in ("supported", "inferred", "unsupported") else "inferred"
        note = str(r.get("note", ""))
        if not s["cites"] and status == "supported":
            status, note = "inferred", note or "인용이 없는 문장"
        missing = missing_terms(s, by_id, state["question"])     # 규칙 검사: 인용 원문에 없는 노테이션 이름
        if missing and status == "supported":
            status, note = "unsupported", f"인용 원문에 없는 표기: {', '.join(missing)}"
        results.append({"index": i, "status": status, "note": note})
    n = {k: sum(r["status"] == k for r in results) for k in ("supported", "inferred", "unsupported")}
    detail = f"{len(results)}문장 중 근거 확인 {n['supported']} · 추론 {n['inferred']} · 근거 없음 {n['unsupported']}"
    bad = [f"- sentence {r['index']}: \"{sents[r['index']]['text']}\" — {r['note'] or 'not supported by the cited sources'}" for r in results if r["status"] == "unsupported"]
    last_round = state.get("gen_round", 1) >= 2
    keep = [i for i, r in enumerate(results) if r["status"] != "unsupported"]
    if bad and last_round and keep:
        # 다시 만들어도 근거를 못 찾은 문장은 답변에서 뺀다 (할루시네이션을 답에 남기지 않음)
        dropped = [sents[r["index"]]["text"] for r in results if r["status"] == "unsupported"]
        sents = [sents[i] for i in keep]
        results = [{**results[i], "index": j} for j, i in enumerate(keep)]
        emit(type="answer_reset")
        stream_sentences(sents, delay=0)
        emit(type="notice", message=f"근거를 확인하지 못한 문장 {len(dropped)}개를 답변에서 뺐습니다: " + " / ".join(f"“{t[:60]}”" for t in dropped))
        detail += f" → 근거 없는 문장 {len(dropped)}개 뺌"
        bad = []
    emit(type="verify", results=results)
    if row_status:
        detail += f" · 비교표 {len(row_status)}행 중 근거 확인 {sum(r['status'] == 'supported' for r in row_status)}"
    node_event("verify", "done", detail + llm.model_note())
    if not (bad and state.get("gen_round", 1) < 2):     # 다시 생성하지 않으면 이 답이 최종 → 인용 구절 · 표 · 카드
        finalize(state, sents, row_status)
    return {"verify": results, "feedback": "\n".join(bad), "sentences": sents}


# ───────────────────────── 분기 ─────────────────────────
def after_grade(state: AgentState):
    g = state.get("grade", {})
    if g.get("answerable", True):
        return "generate"
    if state.get("attempt", 1) < 2:
        return "retrieve"
    if on(state, "web") and has_tavily():
        return "web"
    return "generate"


def after_verify(state: AgentState):
    if state.get("feedback") and state.get("gen_round", 1) < 2:
        return "generate"
    return END


# ───────────────────────── 도움 함수 ─────────────────────────
def finalize(state: AgentState, sents: list, row_status: list | None = None):
    """최종 답이 정해진 뒤 화면에 보낼 것: 문장별 인용 구절(PDF 강조용) · 질문 유형에 맞는 표 또는 노테이션 카드"""
    if state.get("not_found"):
        return
    try:
        items = present.passages(sents)
        if items:
            emit(type="passages", items=items)
    except Exception as e:   # 구절을 못 골라도 답변은 그대로
        emit(type="notice", message=f"인용 구절을 고르지 못했습니다 ({type(e).__name__})")
    c = state.get("trace", {}).get("compare")
    if c and state.get("diff_rows"):
        # 답변이 인용했거나 근거 판정이 고른 쪽의 행만 (검색 상위 10쪽 전체의 개정 행은 다른 절까지 섞임). 하나도 없으면 전부
        focus = {p for s in sents for p in s.get("cites", [])} | set((state.get("grade") or {}).get("pages") or [])
        rows = state["diff_rows"]
        pages_of = lambda r: {f"KR2022:{p}" for p in r["2022 쪽"].split()} | {f"KR2026:{p}" for p in r["2026 쪽"].split()}
        near = [r for r in rows if pages_of(r) & focus]
        emit(type="table", table=present.diff_table(near or rows, c[0]))
        return
    rows = state.get("table") or []
    if rows:
        socs = list(rows[0]["vals"])
        st = row_status or [{"status": None, "note": ""}] * len(rows)
        emit(type="table", table={
            "kind": "compare", "title": "선급 비교", "note": "답변 생성 모델이 근거 페이지에서 정리한 표 · 행마다 근거 검증",
            "columns": ["항목", *[{"KR": "KR", "ABS": "ABS"}.get(s, s) for s in socs]],
            "rows": [{"cells": [r["item"], *r["vals"].values()], "cites": r["cites"], "status": st[k]["status"], "note": st[k]["note"]}
                     for k, r in enumerate(rows)]})
        return
    try:
        cards = ENT.cards_for(sents)
        if cards:
            emit(type="cards", cards=cards)
    except Exception as e:
        emit(type="notice", message=f"노테이션 카드를 만들지 못했습니다 ({type(e).__name__})")


def context_sources(state: AgentState) -> list[dict]:
    terms = terms_of(state["question"], state.get("en_query", ""))
    pages = (state.get("grade") or {}).get("pages") or pick_pages(state["ranking"], state["trace"], MAX_CONTEXT_PAGES)[:MAX_CONTEXT_PAGES + 2]
    out = []
    for p in pages:
        doc, num = p.split(":")
        out.append({"id": p, "title": f"{DOC_LABEL[doc]}, page {num}", "text": excerpt(P.PAGE_TEXT[p], terms, 1500)})
    if state.get("diff_rows"):
        out.append({"id": "tool:edition-diff", "title": "KR 2022→2026 revision table (section | change | notation | pages)", "text": diff_text(state["diff_rows"])})
    for w in state.get("web") or []:
        out.append({"id": w["id"], "title": f"Web: {w['title']} ({w['url']})", "text": w["content"]})
    return out


ID_RE = re.compile(r"(?:KR2022|KR2026|ABS2025):\d+|tool:edition-diff|web:\d+")
INLINE_ID_RE = re.compile(r"\s*[(\[]\s*(?:(?:KR2022|KR2026|ABS2025):\d+|tool:edition-diff|web:\d+)(?:\s*[,;]\s*(?:(?:KR2022|KR2026|ABS2025):\d+|tool:edition-diff|web:\d+))*\s*[)\]]")


def strip_inline_ids(text):
    """'…부여됩니다 (ABS2025:26).' → ('…부여됩니다.', ['ABS2025:26'])"""
    ids = [m for g in INLINE_ID_RE.findall(text) for m in ID_RE.findall(g)]
    return INLINE_ID_RE.sub("", text).strip(), ids


def diff_text(rows):
    return "\n".join(f"- {r['절']} | {r['구분']} | {r['노테이션']} | 2022 p.{r['2022 쪽'] or '-'} | 2026 p.{r['2026 쪽'] or '-'}" for r in rows)


NOTATION_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9]*(?:[-+(][A-Za-z0-9+)]*)*[A-Z0-9+)](?![A-Za-z0-9])")
IGNORE = {"KR", "ABS", "IMO", "LLM", "OK"}


def missing_terms(sentence: dict, by_id: dict, question: str) -> list[str]:
    """문장에 나온 노테이션 같은 표기(대문자 2개 이상)가 인용 원문에도 있는지 본다. 질문에 있던 표기는 제외"""
    src = " ".join(by_id[c]["text"] for c in sentence["cites"] if c in by_id).lower()
    if not src:
        return []
    out = []
    for m in NOTATION_RE.finditer(sentence["text"]):
        t = m.group(0).rstrip(")")
        if sum(ch.isupper() for ch in t) < 2 or t in IGNORE or t.lower() in question.lower() or re.fullmatch(r"(?:KR|ABS)\d{4}", t):
            continue
        if t.lower() not in src:
            out.append(t)
    return sorted(set(out))


def stream_sentences(sents, delay=0.012):
    for i, s in enumerate(sents):
        text = (" " if i else "") + s["text"]
        step = 6 if delay else max(1, len(text))
        for j in range(0, len(text), step):
            emit(type="sentence", index=i, delta=text[j:j + step])
            if delay:
                time.sleep(delay)
        if s["cites"]:
            emit(type="cites", index=i, cites=s["cites"])


GRADE_SYSTEM = """You check whether retrieved pages from ship classification notation guides can answer a user's question.
Return JSON only: {"answerable": true|false, "relevant_pages": ["DOC:PAGE", ...], "reason": "..."}
- relevant_pages: ids of the pages that contain information needed for the answer, most useful first (at most 4; at most 6 when the question compares societies, and then include pages from each society). Use the ids exactly as given.
- answerable: true if those pages (and the revision table, if given) together contain enough to answer the question.
  A partial answer counts, and so does an answer that something is NOT listed (e.g. a notation missing from an edition's list on a page about that topic).
  Set false only when the pages are about a different topic, ship type or society than the question asks.
- reason: one short sentence in Korean."""

GENERATE_SYSTEM = """You are a technical reviewer of ship classification notations (KR Notation Guide 2022/2026, ABS Notations and Symbols 2025).
Answer the question using ONLY the sources given. Do not use outside knowledge.
Return JSON only: {"sentences": [{"text": "...", "cites": ["SOURCE_ID", ...]}, ...]}
- Write in the language of the question (Korean question → Korean answer). 2 to 6 short sentences. Put the direct answer first.
- Every sentence that states a fact must cite at least one source id exactly as given in brackets (e.g. "KR2026:233", "tool:edition-diff", "web:1").
  Put ids only in "cites", never inside "text".
- A notation exists or applies only if its exact name appears in a source. A similar symbol (e.g. "LPG" in another notation) is not the same notation.
- Write notation names, symbols and abbreviations exactly as they appear in the sources.
- For questions about what was added, removed or changed between editions, rely on the revision table source.
- If the sources do not contain the answer, say so in one sentence with no citation. Never guess."""

TABLE_TASK = """

This question compares classification societies. Also return "table" in the same JSON object:
"table": [{{"item": "<aspect, in the answer language>", {cols}, "cites": ["SOURCE_ID", ...]}}, ...]
- 2 to 5 rows, one aspect per row (e.g. notation names, what each covers, requirements). Keep cells short (under 60 characters).
- Use only the sources; write "-" when a society's sources say nothing about that aspect. Cite every source a row uses."""

VERIFY_SYSTEM = """You verify an answer sentence by sentence against the cited sources (ship classification notation guides).
Return JSON only: {"results": [{"index": 0, "status": "supported|inferred|unsupported", "note": "..."}, ...]}
- supported: every claim in the sentence is stated in its cited sources.
- inferred: a reasonable conclusion drawn from the cited sources (or the question) but not stated directly; or a sentence with no citation that makes no new factual claim.
- unsupported: any claim (a notation name, number, requirement, yes/no) is missing from or contradicts the cited sources.
  Treat notation names as exact strings: a sentence saying notation X exists, is listed or applies is supported only if X itself appears in the cited text.
  A related symbol or a different notation that shares a word (e.g. "LPG(4)" vs "LPG Ready") does not support it.
- Paraphrases and translations into Korean of what the source says count as supported.
- note: one short reason in Korean (empty for supported is fine). Judge every sentence index."""


def build_graph():
    g = StateGraph(AgentState)
    for name, fn in (("analyze", analyze), ("rewrite", rewrite), ("retrieve", retrieve), ("diff", diff),
                     ("grade", grade), ("web", web), ("generate", generate), ("verify", verify)):
        g.add_node(name, fn)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_edge("retrieve", "diff")
    g.add_edge("diff", "grade")
    g.add_conditional_edges("grade", after_grade, ["generate", "retrieve", "web"])
    g.add_edge("web", "generate")
    g.add_edge("generate", "verify")
    g.add_conditional_edges("verify", after_verify, ["generate", END])
    return g.compile()


GRAPH = None


def graph():
    global GRAPH
    if GRAPH is None:
        GRAPH = build_graph()
    return GRAPH
