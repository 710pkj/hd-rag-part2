"""노테이션 엔티티 표: 문서의 표 · 목록에서 노테이션을 한 줄씩 뽑은 것 (실험 E29와 같은 규칙).

검색 순위에는 쓰지 않는다 (E29: 엔티티 채널을 더해도 dev가 오르지 않아 기각). 답변 화면의 '노테이션 카드' 데이터로 쓴다.
- KR: 판본 비교 스크립트(07_판비교_쿼리손질/kr_edition_diff.py)와 같은 파서. 2장 각 절의 NOTATIONS 목록 항목과
      머리글에 Notation이 있는 표의 행(나머지 칸 = 요건). 절이 없는 쪽(목차 · 요약표 · 부록)은 뺀다
- ABS: 쪽마다 '## NOTATION' 제목 아래 줄이 노테이션 이름, '## DESCRIPTION' · '## REFERENCES'를 설명 · 참조 규칙으로
문서만 보고 만들며(질문 · 정답을 보지 않음), init() 뒤 처음 부를 때 메모리에 한 번 만든다 (1초 안쪽)."""
import re
import unicodedata
from collections import defaultdict

from . import part1 as P

# ───────── KR 파서 (kr_edition_diff.py와 같은 규칙) ─────────
SEC_RE = re.compile(r"^#*\s*(\d+(?:[-.]\d+)?)\.?\s+([A-Z][^\n|]{2,60}?)\s*$", re.M)
CH_RE = re.compile(r"^#*\s*(?:Ch|CHAPTER)\s*(\d)\b", re.M | re.I)
TEMPLATE_RE = re.compile(r"NOTATIONS|DESCRIPTIONS|REQUIREMENTS|EXAMPLES")
SUP_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+[⁾)]?")


def norm(s):
    s = SUP_RE.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("**", "").replace("<br>", " ")
    s = re.sub(r"[–—−]", "-", s)
    return " ".join(s.split()).strip(" .")


def section_of_pages(pages):
    out, section = {}, ""
    for p in sorted(pages):
        t = pages[p]
        ch, m = CH_RE.search(t), SEC_RE.search(t)
        if re.search(r"^#*\s*Annex\s*\d", t, re.M) or "Written Example" in t[:300]:
            section = ""
        elif ch and ch.group(1) in ("3", "4"):
            section = f"Ch {ch.group(1)}"
        elif m and not m.group(2).startswith("Notation Guide") and (ch is None or TEMPLATE_RE.search(t)):
            section = m.group(2).strip()
        elif not TEMPLATE_RE.search(t) and not section.startswith("Ch "):
            section = ""
        out[p] = section
    return out


def page_units(pages, sec_of):
    units = defaultdict(list)                  # (절, 이름) → [(쪽, 요건 또는 None)]
    for p in sorted(pages):
        section, t = sec_of[p], pages[p]
        if not section or "Typical Example" in t:
            continue
        lines = t.splitlines()
        header_ok = False
        for line in lines:
            s = line.strip()
            if not s.startswith("|"):
                if s:
                    header_ok = False
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if re.fullmatch(r"[-: ]*", cells[0]):
                continue
            if "notation" in cells[0].lower():
                header_ok = True
                continue
            if header_ok and re.search(r"[0-9A-Za-z]", cells[0]):
                name = norm(re.sub(r"^[*\\]+", "", cells[0]))
                units[(section, name)].append((p, norm(" | ".join(cells[1:]))))
        if section.startswith("Ch "):
            continue
        in_list = False
        for line in lines:
            s = line.strip()
            if re.match(r"^#*\s*NOTATIONS", s):
                in_list = True
                continue
            if in_list and (s.startswith("#") or re.match(r"^(DESCRIPTIONS|REQUIREMENTS|EXAMPLES)", s)):
                in_list = False
            if in_list and s and not s.startswith("|"):
                name = norm(re.sub(r"^[-•*\\]+\s*", "", s))
                if 0 < len(name) <= 80 and re.search(r"[0-9A-Za-z]", name):
                    units[(section, name)].append((p, None))
    return units


# ───────── ABS 파서 ─────────
HEAD_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$")
BLOCKS = ("NOTATION", "NOTATIONS", "DESCRIPTION", "REFERENCES", "REMARKS")


def abs_rows(pages):
    rows = []
    for p, text in sorted(pages.items()):
        lines = [l.strip() for l in text.split("\n")]
        heads = [(i, HEAD_RE.match(l).group(1).strip()) for i, l in enumerate(lines) if HEAD_RE.match(l)]
        category = next((h for _, h in heads if h.upper() not in BLOCKS), "")

        def block(name):
            out = []
            for k, (i, h) in enumerate(heads):
                if h.upper() == name:
                    end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
                    body = [l for l in lines[i + 1:end] if l]
                    # 이름이 제목 줄로 들어간 쪽('## NOTATION' 바로 다음이 '## ✠ ABCU'): 그 제목을 이름으로
                    if not body and name == "NOTATION" and k + 1 < len(heads) and heads[k + 1][1].upper() not in BLOCKS:
                        body = [heads[k + 1][1]]
                    out.append(body)
            return out

        desc = "\n".join(l for b in block("DESCRIPTION") for l in b) or None
        refs = "\n".join(l for b in block("REFERENCES") for l in b) or None
        for b in block("NOTATION"):
            for line in b:
                name = " ".join(line.split())
                if re.search(r"[0-9A-Za-z]", name):
                    rows.append((p, category, name, None, desc, refs))
    return rows


# ───────── 표 만들기 · 찾기 ─────────
TOK = re.compile(r"[0-9a-z가-힣]+\+*")
ENTITIES: list[dict] = []
BY_PAGE: dict[str, list[dict]] = defaultdict(list)


def toks(s: str) -> list[str]:
    return TOK.findall(unicodedata.normalize("NFKC", s or "").lower())


def top_level_split(name: str) -> list[str]:
    """괄호 밖의 쉼표로만 나눔: 'Cyber Resilience, CSMS' → 2개, 'SeaTrust (DSA1, …, WHIP)' → 1개"""
    parts, depth, cur = [], 0, ""
    for ch in name:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth <= 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur] if p.strip()]


PLACEHOLDER = re.compile(r"\([^)]*\b[a-z]{4,}")   # 괄호 안이 소문자 설명: 'AUTONOMOUS ( function category , … )'


def keys_of(name: str) -> list[str]:
    """답변에서 찾을 이름 열쇠: 이름 전체, 괄호 밖 쉼표로 나열된 각 이름, 그리고 괄호 안이 소문자 설명(자리 표시)일 때만
    괄호 앞 머리('AUTONOMOUS (function category, …)' → 'autonomous'). 'LS(CL, RS)'의 괄호는 이름의 일부라 머리를 쓰지 않음"""
    out = []
    head = [name.split("(")[0]] if PLACEHOLDER.search(name) else []
    for part in [name, *head, *top_level_split(name)]:
        k = " ".join(toks(part))
        if k and k not in out and (len(k) >= 2 and k not in P.STOPWORDS):
            out.append(k)
    return out


def build():
    if ENTITIES or P.pages is None:
        return
    pg = P.pages
    seen = {}
    for doc in ("KR2022", "KR2026"):
        raw = {int(r.page): r.raw for r in pg[pg.doc_id == doc].itertuples()}
        for (section, name), occ in page_units(raw, section_of_pages(raw)).items():
            for p, req in occ:
                k = (f"{doc}:{p}", name)
                if k in seen:
                    seen[k]["req"] = seen[k]["req"] or req
                    continue
                seen[k] = {"doc": doc, "page_id": k[0], "source": "kr_table" if req else "kr_list", "section": section,
                           "name": name, "req": req, "description": None, "refs": None}
    clean = {int(r.page): r.search_text for r in pg[pg.doc_id == "ABS2025"].itertuples()}
    for p, category, name, req, desc, refs in abs_rows(clean):
        k = (f"ABS2025:{p}", name)
        if k not in seen:
            seen[k] = {"doc": "ABS2025", "page_id": k[0], "source": "abs_notation", "section": category,
                       "name": name, "req": req, "description": desc, "refs": refs}
    for e in seen.values():
        e["keys"] = keys_of(e["name"])
        ENTITIES.append(e)
        BY_PAGE[e["page_id"]].append(e)


def cards_for(sentences: list[dict], limit: int = 4) -> list[dict]:
    """답변 문장에 이름이 나온 노테이션 중, 그 문장이 인용한 쪽에 있는 것 → 카드 (인용 순서, 긴 이름 먼저)"""
    build()
    out, seen = [], set()
    for s in sentences:
        ans = " " + " ".join(toks(s["text"])) + " "
        found = []
        for p in s.get("cites", []):
            for e in BY_PAGE.get(p, []):
                k = max((k for k in e["keys"] if f" {k} " in ans), key=len, default=None)
                if k:
                    found.append((k, e))
        keys = {k for k, _ in found}

        def occ(k):   # 겹치는 위치도 셈 (' ls ls cl '에서 ' ls '는 2번)
            return len(re.findall(f"(?= {re.escape(k)} )", ans))

        def own_mention(k):
            """'LS(CL)'만 말했는데 'LS'까지 걸리지 않게: 더 긴 이름에 포함된 횟수를 빼고도 남아야 따로 말한 것"""
            return occ(k) > sum(occ(K) for K in keys if K != k and f" {k} " in f" {K} ")

        found = [(-len(k), e) for k, e in found if own_mention(k)]
        for _, e in sorted(found, key=lambda x: x[0]):
            key = (e["doc"], e["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": e["name"], "doc": e["doc"], "page": e["page_id"], "section": e["section"],
                        "req": e["req"], "description": (e["description"] or "")[:360] or None,
                        "refs": "\n".join((e["refs"] or "").split("\n")[:2]) or None, "source": e["source"]})
            if len(out) >= limit:
                return out
    return out
