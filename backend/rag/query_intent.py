"""쿼리 손질 규칙: 판 비교 의도 감지와 주제 추출.

질문 문장만 보고 판단한다 (정답표·문서 내용은 쓰지 않음). 모든 질문에 같은 규칙을 적용한다.

1. 의도
   - 판 비교: 같은 선급의 판 연도가 2개 이상이고 변화어가 있으면 판 비교.
     최신판 연도 하나와 신설·삭제·변경 단어만 있어도 판 비교로 본다 ("2026년에 신설된" = 직전 판과 비교).
     세부 의도는 구체적인 것부터: 신설 > 삭제 > 변경 > 차이
   - 선급 비교: 선급이 2개 이상이고 비교·차이 단어가 있으면 선급 비교 (판 정책은 바꾸지 않음)
   - 그 밖의 "차이"(노테이션끼리 비교 등)는 의도 없음으로 둔다
2. 판 정책: 신설·변경·차이 → 새 판 우선(구판 감점), 삭제 → 구판 우선. 의도가 없으면 기존 규칙(latest_boost)
3. 주제 쿼리 (dense·리랭커용)
   - 모든 질문: 선급명, "선급 기준", 연도 구절을 지움. E9 규칙과 달리 영어 전치사구("in 2022",
     "between 2022 and 2026")와 한국어 비교 구절("2022년과 비교하여")을 통째로 지움
   - 판 비교 질문만: 변화어와 질문 꼬리("무엇?", "is there any")도 지움 (페이지에는 "신설" 같은 표시가 없음)

실행: python query_intent.py  → dev·test 질문이 어떻게 바뀌는지 query_intent_preview.csv로 저장
"""
import csv
import re
from pathlib import Path

EDITIONS = {"KR": (2022, 2026), "ABS": (2025,)}
SOCIETY_RE = {"KR": re.compile(r"(?<![A-Za-z])KR(?![A-Za-z])|한국선급|Korean Register", re.I),
              "ABS": re.compile(r"(?<![A-Za-z])ABS(?![A-Za-z])|미국선급|American Bureau", re.I)}
EVENT_CUE = re.compile(r"건조|취득|계약|인도|진수|용골|built|contract|deliver|keel", re.I)   # 파이프라인과 같은 규칙
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

INTENT_RE = {   # 구체적인 것부터 검사
    "신설": re.compile(r"신설|새로|새롭게|생긴|추가된|추가되|도입된|\bnew(?:ly)?\b|\badded\b|\bintroduced\b", re.I),
    "삭제": re.compile(r"삭제|폐지|없어진|빠진|\bremoved\b|\bdeleted\b|\bwithdrawn\b", re.I),
    "변경": re.compile(r"변경|개정|바뀐|바뀌|수정된|\bchanged?\b|\bamended\b|\brevised\b|\bmodified\b", re.I),
    "차이": re.compile(r"차이|달라|다른 점|비교|\bdiffer(?:ence|ences|s)?\b|\bcompar", re.I),
}
EDITION_POLICY = {"신설": "new", "변경": "new", "차이": "new", "삭제": "old"}

# 주제 추출용 패턴
YEAR_RANGE_EN = re.compile(r"\b(?:between\s+)?(?:(?:in|the)\s+)*20\d{2}(?:\s+edition)?\s*(?:and|vs\.?|versus|to|-)\s*"
                           r"(?:(?:in|the)\s+)*20\d{2}(?:\s+edition)?\b", re.I)
YEAR_PREP_EN = re.compile(r"\b(?:in|of|for|from|since|until|under|per)\s+(?:the\s+)?20\d{2}(?:\s+(?:edition|version))?\b", re.I)
YEAR_KO = re.compile(r"(?<!\d)20\d{2}\s*년?\s*도?\s*판?\s*(?:과|와|에서|에|의|부터|까지|대비|기준으로|기준)?"
                     r"\s*(?:비교하여|비교해서|비교해|비교하면|대비하여|대비)?")
META_RE = re.compile(r"(?<![A-Za-z])(?:KR|ABS)\s+rules\b|(?<![A-Za-z])(?:KR|ABS)(?![A-Za-z])\s*(?:과|와|의)?"
                     r"|한국선급|미국선급|선급(?:\s*기준\s*(?:으로|에서|의)?)?|(?<![가-힣])기준\s*(?:으로|에서)", re.I)
CHANGE_WORDS = re.compile(r"(?:으로|로)?\s*(?:새로\s*|새롭게\s*)?(?:신설|추가|도입|삭제|폐지|변경|개정)(?:된|되었는지|되는|됨|되었나요)?"
                          r"|새로\s*생긴|달라진|바뀐|차이(?:점|가|는)?|"
                          r"\b(?:newly|new|added|removed|deleted|changed|amended|revised|differences?|differ)\b", re.I)
TAIL = re.compile(r"\bis there any\b|\bare there any\b|\bwhat\s+(?:is|are)\b|\s*(?:항목|것)?(?:은|는|이)?\s*무엇\s*\??\s*$"
                  r"|(?:이|가)?\s*있나요\s*\??\s*$", re.I)


def analyze(q):
    socs = [s for s, rx in SOCIETY_RE.items() if rx.search(q)]
    years = [(int(m.group(1)), bool(EVENT_CUE.search(q[m.end(): m.end() + 20]))) for m in YEAR_RE.finditer(q)]
    found = [k for k, rx in INTENT_RE.items() if rx.search(q)]
    out = {"societies": socs or list(EDITIONS), "intent": "", "editions": [], "policy": ""}
    for s in out["societies"]:
        eds = sorted({y for y, ev in years if not ev and y in EDITIONS[s]})
        if not found or len(EDITIONS[s]) < 2:
            continue
        intent = found[0]
        if len(eds) >= 2 or (len(eds) == 1 and eds[0] == max(EDITIONS[s]) and intent in ("신설", "삭제", "변경")):
            prev = [e for e in EDITIONS[s] if e < max(eds)]
            out.update(intent=f"판 비교: {intent}", editions=eds if len(eds) >= 2 else [max(prev), eds[0]],
                       policy=f"{s} {'새 판' if EDITION_POLICY[intent] == 'new' else '구판'} 우선")
            return out
    if len(socs) >= 2 and INTENT_RE["차이"].search(q):
        out["intent"] = "선급 비교"
    return out


def topic_query(q, info=None):
    info = info or analyze(q)
    s = YEAR_RANGE_EN.sub(" ", q)
    s = YEAR_PREP_EN.sub(" ", s)
    s = YEAR_KO.sub(" ", s)
    s = META_RE.sub(" ", s)
    if info["intent"].startswith("판 비교"):
        s = CHANGE_WORDS.sub(" ", s)
        s = TAIL.sub(" ", s)
        s = re.sub(r"\s*(?:은|는|이|가)?\s*\?\s*$", "", s)             # 남은 질문 꼬리 ("노테이션은?")
        s = re.sub(r"^\s*(?:(?:in|of|for|on|about|the)\s+)+", "", s, flags=re.I)   # 앞에 남은 전치사
    s = re.sub(r"\s+([,?.])", r"\1", s)
    s = re.sub(r"^[\s,.]+|[\s,]+$", "", " ".join(s.split()))
    return s or q


# 비교용: 지금 쓰는 E9 규칙 (Colab 노트북의 strip_dense_meta와 같음)
E9_META_RE = re.compile(r"(?<![A-Za-z])(?:KR|ABS)(?![A-Za-z])\s*(?:과|와|의)?|한국선급|미국선급"
                        r"|선급\s*기준\s*(?:으로|에서|의)?|(?<!\d)20\d{2}\s*년?\s*도?\s*(?:에|의|과|와)?", re.I)


def e9_query(q):
    s = E9_META_RE.sub(" ", q)
    s = re.sub(r"^[\s,]+|\s+(?=[,?])", "", s)
    return " ".join(s.split()) or q


def main():
    data = Path(__file__).resolve().parent.parent / "03_데이터"
    rows = []
    for name in ("dev_set.csv", "test_set.csv"):
        for r in csv.DictReader(open(data / name, encoding="utf-8-sig")):
            info = analyze(r["query"])
            rows.append({"qid": r["qid"], "원래 질문": r["query"], "의도": info["intent"] or "-",
                         "비교 판": "→".join(map(str, info["editions"])), "판 정책": info["policy"],
                         "지금(E9) 쿼리": e9_query(r["query"]), "새 주제 쿼리": topic_query(r["query"], info)})
    out = Path(__file__).resolve().parent / "query_intent_preview.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        changed = "*" if r["지금(E9) 쿼리"] != r["새 주제 쿼리"] else " "
        print(f"{r['qid']} {changed} [{r['의도']}{' ' + r['비교 판'] if r['비교 판'] else ''}{' / ' + r['판 정책'] if r['판 정책'] else ''}]")
        if changed == "*":
            print(f"      E9 : {r['지금(E9) 쿼리']}")
            print(f"      새것: {r['새 주제 쿼리']}")
    print(f"\n→ {out.name} ({len(rows)}문항, * = 쿼리가 바뀐 문항)")


if __name__ == "__main__":
    main()
