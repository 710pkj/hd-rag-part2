"""답변을 사용자에게 보여 줄 때 쓰는 계산: 인용 구절 고르기 · 판 비교 변경 표 · 가정과 되묻기.

모두 문서와 검색 결과에서 결정적으로 만든다 (LLM을 부르지 않음). 선급 비교표만 답변 생성 LLM이 함께 만들고 근거 검증을 거친다."""
import re

import numpy as np

from rag import part1 as P
from rag import query_intent as QI

DOC_SHORT = {"KR2022": "KR 2022", "KR2026": "KR 2026", "ABS2025": "ABS 2025"}
PAGE_RE = re.compile(r"^(?:KR2022|KR2026|ABS2025):\d+$")
KV_RE = re.compile(r"^[^:;\n]{1,40}:\s")


# ───────── 인용 구절: 문장마다, 인용한 쪽에서 문장과 가장 비슷한 구절 ─────────
def _e13():
    """구조 기반 청크 색인 (SQL 색인을 쓸 때는 대신용으로 남겨 둔 FAISS 색인)"""
    return P.IDX13 if hasattr(P.IDX13, "chunks") else P.IDX13.fallback


def _body(text: str) -> str:
    """청크 앞의 제목 경로 줄('11. Container Ship > REQUIREMENTS …')을 떼고, KR 표 행('열: 값; …')은 값만 남긴다
    (PDF에서 그 줄을 찾을 때 표 머리글이 아니라 그 행이 걸리게)"""
    lines = text.split("\n")
    if len(lines) > 1 and ":" not in lines[0] and "|" not in lines[0] and len(lines[0]) <= 120:
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if "\n" not in body and all(KV_RE.match(seg.strip()) for seg in body.split("; ") if seg.strip()):
        body = " ".join(seg.split(": ", 1)[1] for seg in body.split("; ") if ": " in seg)
    return body


def _candidates(page_id: str) -> list[str]:
    """그 쪽의 청크를 구절 후보로. 긴 청크(ABS 쪽 통째 등)는 빈 줄 기준 문단으로 나눈다"""
    ix = _e13()
    out = []
    for t in ix.chunks.text[ix.chunks.page_id == page_id]:
        body = _body(t)
        if len(body) <= 400:
            out.append(body)
            continue
        buf = ""
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para or re.fullmatch(r"#+\s*[A-Z ]+", para):      # '## DESCRIPTION' 같은 제목만 있는 문단은 다음과 합침
                buf = (buf + "\n" + para).strip()
                continue
            buf = (buf + "\n" + para).strip()
            if len(buf) >= 60:
                out.append(buf)
                buf = ""
        if buf:
            out.append(buf)
    return [c for c in dict.fromkeys(out) if re.search(r"[A-Za-z0-9가-힣]", c)]


LATIN = re.compile(r"[0-9a-z]+\+*")


def _lex(sentence: str, cand: str) -> float:
    """문장의 영문 · 코드 낱말과 구절 낱말의 겹침 (정밀도 + 재현율). 임베딩은 'LS(CL)'과 'LS(CL, RS+)'처럼
    코드 한 조각 차이를 잘 못 가려서 더한다. 문장에 영문 낱말이 없으면 0"""
    s = set(LATIN.findall(sentence.lower()))
    c = set(LATIN.findall(cand.lower()))
    if not s or not c:
        return 0.0
    hit = len(s & c)
    return hit / len(c) + hit / len(s)


def passages(sentences: list[dict]) -> list[dict]:
    """[{index, page, quote}] — 문장 i가 인용한 쪽 page에서 고른 구절.
    점수 = BGE-M3 dense 유사도(한국어 문장 ↔ 영어 구절) + 0.25 × 영문 · 코드 낱말 겹침"""
    pairs = [(i, c) for i, s in enumerate(sentences) for c in s.get("cites", []) if PAGE_RE.match(c)]
    if not pairs:
        return []
    cands = {p: _candidates(p) for p in {c for _, c in pairs}}
    texts = [sentences[i]["text"] for i in sorted({i for i, _ in pairs})]
    sent_pos = {i: k for k, i in enumerate(sorted({i for i, _ in pairs}))}
    pool = [c for p in cands for c in cands[p]]
    try:
        vec = P.M3.encode(texts + pool, batch_size=16)["dense"]
    except Exception:          # 모델을 못 쓰면 첫 후보로
        vec = None
    pos, k = {}, len(texts)
    for p in cands:
        pos[p] = list(range(k, k + len(cands[p])))
        k += len(cands[p])
    out = []
    for i, p in pairs:
        if not cands[p]:
            continue
        lex = np.array([_lex(sentences[i]["text"], c) for c in cands[p]])
        sims = (vec[pos[p]] @ vec[sent_pos[i]] if vec is not None else np.zeros(len(cands[p]))) + 0.25 * lex
        best = int(np.argmax(sims))
        out.append({"index": i, "page": p, "quote": cands[p][best][:600]})
    return out


# ───────── 판 비교 변경 표: 판 비교표 도구의 행을 그대로 (결정적, LLM 없음) ─────────
def diff_table(rows: list[dict], kind: str) -> dict:
    return {
        "kind": "diff",
        "title": f"KR 2022 → 2026 개정 요약 ({kind})",
        "note": "Part 1에서 두 판 본문을 규칙으로 대조해 만든 판 비교표에서, 검색 상위 쪽과 관련된 행",
        "columns": ["절", "구분", "노테이션", "2022 쪽", "2026 쪽"],
        "rows": [{"cells": [r["절"], r["구분"], r["노테이션"],
                            " ".join(f"KR2022:{p}" for p in r["2022 쪽"].split()),
                            " ".join(f"KR2026:{p}" for p in r["2026 쪽"].split())],
                  "badge": r["구분"]} for r in rows],
    }


# ───────── 가정과 되묻기: 질문에 선급 · 연도가 빠졌을 때 어떤 가정을 했는지 알리고 다른 선택지를 준다 ─────────
def clarify(question: str, filters: list, analysis: dict) -> dict | None:
    """막지 않는 되묻기: 기본 가정으로 바로 답하고, 버튼으로 다른 범위를 골라 다시 물을 수 있게 한다.
    사용자가 문서 범위를 직접 고른 질문에는 하지 않는다"""
    if filters:
        return None
    named = [s for s, rx in QI.SOCIETY_RE.items() if rx.search(question)]
    if not named:
        return {"assumption": "질문에 선급이 없어 KR과 ABS 문서를 모두 찾았습니다.",
                "ask": "어느 선급 기준으로 볼까요?",
                "options": [{"label": "KR 2026판만", "filters": ["KR2026"]}, {"label": "ABS 2025판만", "filters": ["ABS2025"]}]}
    years = {y for y, _ in analysis.get("years", [])}
    if "KR" in named and not (years & set(P.EDITIONS["KR"])) and not str(analysis.get("intent", "")).startswith("판 비교"):
        extra = ["ABS2025"] if "ABS" in named else []
        return {"assumption": "질문에 연도가 없어 KR 최신판(2026)을 우선했습니다. 2022판 쪽은 순위를 낮췄습니다.",
                "ask": "2022판 기준이 필요하면 다시 물어볼 수 있습니다.",
                "options": [{"label": "KR 2022판 기준으로 다시", "filters": ["KR2022", *extra]},
                            {"label": "KR 2026판만", "filters": ["KR2026", *extra]}]}
    return None
