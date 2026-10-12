"""KR Notation Guide 2022판과 2026판을 노테이션 단위로 대조해 신설·삭제·변경 목록을 만든다.

KR 가이드에는 ABS처럼 "New Notations" / "Revision History" 페이지가 없어서 두 판을 직접 맞대어 본다.
- 노테이션 후보: 2장 각 절의 NOTATIONS 목록 항목과 REQUIREMENTS 표의 행, 3·4장 "노테이션 | 요건" 표의 행
  (이어지는 페이지는 절 제목이 없으므로 앞 페이지의 절 제목을 물려받는다)
- 절은 번호를 뺀 제목으로 짝짓는다 (판마다 번호 형식이 다름: "3.1 Chemical Tanker" / "3-1. Chemical Tanker")
- 판정 (판마다 파싱 서식이 조금씩 달라서, 구조가 아니라 본문 존재 여부로 판정한다)
  - 신설: 2026판 후보인데, 2022판의 같은 절 본문에 그 이름이 없음 (공백 무시)
  - 삭제: 2022판 후보인데, 2026판의 같은 절 본문에 그 이름이 없음
  - 명칭 변경: 같은 절의 삭제·신설 쌍 중 이름이 비슷한 것 (문자열 유사도 0.6 이상)
  - 요건 변경: 두 판 모두 요건표 행이 있는데 요건(설계·검사 근거) 문자열이 다름

실행: python kr_edition_diff.py  → kr_edition_diff.csv
"""
import csv
import pickle
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "03_데이터"
OUT = Path(__file__).resolve().parent / "kr_edition_diff.csv"


class _Stub:
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state.get("__dict__", state))


class SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        try:
            return super().find_class(module, name)
        except (ImportError, AttributeError):
            return type(name, (_Stub,), {})


def load_pages(fname):
    docs = SafeUnpickler(open(DATA / fname, "rb")).load()
    return {int(d.metadata["page"]): d.page_content for d in docs}


SEC_RE = re.compile(r"^#*\s*(\d+(?:[-.]\d+)?)\.?\s+([A-Z][^\n|]{2,60}?)\s*$", re.M)
CH_RE = re.compile(r"^#*\s*(?:Ch|CHAPTER)\s*(\d)\b", re.M | re.I)
TEMPLATE_RE = re.compile(r"NOTATIONS|DESCRIPTIONS|REQUIREMENTS|EXAMPLES")
SUP_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+[⁾)]?")   # 각주 위첨자 (닫는 괄호 ⁾ 포함)


def norm(s):
    """표시용 정규화: NFKC, 각주 위첨자·마크다운 강조 제거, 대시·공백 통일"""
    s = SUP_RE.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("**", "").replace("<br>", " ")
    s = re.sub(r"[–—−]", "-", s)
    return " ".join(s.split()).strip(" .")


def compact(s):
    """비교용: 영문 소문자·숫자·한글만 남김 (공백, 괄호, 쉼표, 대시, 표 구분자 차이는 무시)"""
    return re.sub(r"[^0-9a-z가-힣]", "", norm(s).lower())


def section_of_pages(pages):
    """쪽 → 절 이름 (없으면 '')"""
    out, section = {}, ""
    for p in sorted(pages):
        t = pages[p]
        ch, m = CH_RE.search(t), SEC_RE.search(t)
        if re.search(r"^#*\s*Annex\s*\d", t, re.M) or "Written Example" in t[:300]:
            section = ""                       # 부록은 비교하지 않음 (본문 속 "Pt 7 Annex 7-2" 같은 참조는 부록이 아님)
        elif ch and ch.group(1) in ("3", "4"):
            section = f"Ch {ch.group(1)}"
        elif m and not m.group(2).startswith("Notation Guide") and (ch is None or TEMPLATE_RE.search(t)):
            section = m.group(2).strip()       # 쪽 아래 "Notation Guide 2026" 꼬리말은 절 제목이 아님
        elif not TEMPLATE_RE.search(t) and not section.startswith("Ch "):
            section = ""                       # 틀이 없는 페이지(목차·요약표)는 절에 넣지 않음
        out[p] = section
    return out


def page_units(pages, sec_of):
    units = defaultdict(list)                  # (절, 이름) -> [(쪽, 요건 또는 None)]
    for p in sorted(pages):
        section, t = sec_of[p], pages[p]
        if not section or "Typical Example" in t:
            continue
        lines = t.splitlines()
        header_ok = False                      # 1) 첫 칸 머리글에 Notation이 들어간 표의 행
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
                name = norm(re.sub(r"^[*\\]+", "", cells[0]))   # 각주 별표(*)는 이름에서 뺌
                units[(section, name)].append((p, norm(" | ".join(cells[1:]))))
        if section.startswith("Ch "):
            continue
        in_list = False                        # 2) 2장 NOTATIONS 목록 (기호가 없는 판도 있음)
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


def collapse(units):
    out = {}
    for k, v in units.items():
        vals = [x for _, x in v if x]
        out[k] = (sorted({p for p, _ in v}), vals[0] if vals else None)
    return out


def section_text(pages, sec_of):
    txt = defaultdict(str)
    for p, s in sec_of.items():
        if s:
            txt[s] += compact(pages[p])
    return txt


def main():
    P = {y: load_pages(f"KR_Notation_{y}.pkl") for y in (2022, 2026)}
    S = {y: section_of_pages(P[y]) for y in P}
    U = {y: collapse(page_units(P[y], S[y])) for y in P}
    T = {y: section_text(P[y], S[y]) for y in P}
    whole = {y: compact(" ".join(P[y].values())) for y in P}
    secs = {y: {s for s, _ in U[y]} for y in P}

    def absent(name, sec, year):
        """그 판의 같은 절 본문(절이 없으면 문서 전체)에 이름이 없으면 True"""
        hay = T[year].get(sec) or whole[year]
        return compact(name) not in hay

    def req(v):
        """요건 비교용: 2022판에만 일반 문자로 남은 각주 번호("Pt 3, 2), 3)")를 뺀다"""
        return compact(re.sub(r"(?<=[,\s])\d\)", "", v or ""))

    pg = lambda x: " ".join(map(str, x))
    added = [(sec, name, p, v) for (sec, name), (p, v) in sorted(U[2026].items()) if absent(name, sec, 2022)]
    removed = [(sec, name, p, v) for (sec, name), (p, v) in sorted(U[2022].items()) if absent(name, sec, 2026)]
    rows = []
    # 같은 절에서 이름이 비슷한 삭제·신설 쌍은 명칭 변경으로 묶는다 (예: LFSS → LFFS)
    for r in list(removed):
        cands = [a for a in added if a[0] == r[0]]
        best = max(cands, key=lambda a: SequenceMatcher(None, compact(r[1]), compact(a[1])).ratio(), default=None)
        if best and SequenceMatcher(None, compact(r[1]), compact(best[1])).ratio() >= 0.6:
            rows.append((r[0], "명칭 변경", f"{r[1]} → {best[1]}", pg(r[2]), pg(best[2]), r[3] or "", best[3] or ""))
            removed.remove(r)
            added.remove(best)
    for sec, name, p, v in added:
        rows.append((sec, "신설 (절 신설)" if sec not in secs[2022] else "신설", name, "", pg(p), "", v or ""))
    for sec, name, p, v in removed:
        rows.append((sec, "삭제 (절 삭제)" if sec not in secs[2026] else "삭제", name, pg(p), "", v or "", ""))
    for (sec, name), (p, v) in sorted(U[2026].items()):    # 이름은 같고 요건(설계·검사 근거)이 바뀐 경우
        o = U[2022].get((sec, name))
        if o and o[1] and v and req(o[1]) != req(v):
            rows.append((sec, "요건 변경", name, pg(o[0]), pg(p), o[1], v))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    head = ["절", "구분", "노테이션", "2022 쪽", "2026 쪽", "2022 요건", "2026 요건"]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)
    by = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by[r[0]][r[1].split(" ")[0]] += 1
    print(f"절: 2022판 {len(secs[2022])}개, 2026판 {len(secs[2026])}개 | 노테이션 후보: 2022판 {len(U[2022])}개, 2026판 {len(U[2026])}개")
    print(f"변경 기록 {len(rows)}건 → {OUT.name}")
    for sec in sorted(by, key=lambda s: -sum(by[s].values())):
        print(f"  {sec:<50} " + ", ".join(f"{k} {v}" for k, v in sorted(by[sec].items())))
    only = lambda y: sorted(secs[y] - secs[2026 if y == 2022 else 2022])
    print("2022판에만 있는 절:", only(2022))
    print("2026판에만 있는 절:", only(2026))


if __name__ == "__main__":
    main()
