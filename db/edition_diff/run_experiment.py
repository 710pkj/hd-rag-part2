"""판본 비교 SQL 실험
① Python 기준: kr_edition_diff.py가 지금도 93건(kr_edition_diff.csv)을 그대로 내는지
② 파싱 결과(쪽 · 절 · 노테이션 후보)만 DB에 넣고, 정규화 · 판정은 SQL(edition_diff.sql)로
③ SQL 결과를 93건과 비교 (명칭 변경 유사도: lev 주 기준, trgm 참고. 둘 다 0.6, 미리 정함)
④ 정규화가 Python과 같은지(쪽 938개 · 이름 전부), 명칭 변경 후보 쌍의 유사도 비교
⑤ 검색에 쓰는 모양(쪽 → 개정 기록 종류)이 백엔드 CHANGED와 같은지
실행: backend .venv의 python (psycopg 필요). 로컬 PostgreSQL이 localhost:5433에 떠 있어야 함"""
import csv, hashlib, importlib.util, json, os, sys, time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import psycopg

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
SRC = HERE / "kr_edition_diff.py"             # Part 1의 07_판비교_쿼리손질 폴더에서 복사해 둔 원본 스크립트


def env_value(name):
    """환경 변수 → backend/.env 순으로 설정 값을 찾음 (백엔드와 같은 설정)"""
    if os.environ.get(name):
        return os.environ[name]
    env = HERE.parents[1] / "backend" / ".env"
    for line in (env.read_text(encoding="utf-8-sig").splitlines() if env.exists() else []):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip() or None
    return None


# Part 1 제출 폴더: 백엔드(rag/part1.py)와 같은 순서로 찾음 (PART1_DIR → 저장소 data/HD_RAG_Part1 → 만든 사람 PC)
PART1 = next((Path(c) for c in (env_value("PART1_DIR"), HERE.parents[1] / "data" / "HD_RAG_Part1",
                                 r"C:\Users\710pk\OneDrive\Desktop\HD융캡디\제출\HD_RAG_Part1")
              if c and (Path(c) / "test_set.csv").exists()), HERE.parents[1] / "data" / "HD_RAG_Part1")
REF = PART1 / "outputs" / "kr_edition_diff.csv"
HEAD = ["절", "구분", "노테이션", "2022 쪽", "2026 쪽", "2022 요건", "2026 요건"]
md5 = lambda p: hashlib.md5(Path(p).read_bytes()).hexdigest()
read_rows = lambda p: [tuple(r) for r in list(csv.reader(open(p, encoding="utf-8-sig")))[1:]]
summary = {}

spec = importlib.util.spec_from_file_location("ked", SRC)
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)
K.DATA = PART1                       # pkl 위치 (예전 03_데이터 폴더는 없어짐)

# ① Python 기준 ------------------------------------------------------------------------------
K.OUT = OUT / "python_kr_edition_diff.csv"   # 07 폴더의 원본 CSV를 덮어쓰지 않게
t = time.perf_counter()
K.main()
summary["python_main_s"] = round(time.perf_counter() - t, 3)
ref_rows = read_rows(REF)
summary["ref_rows"] = len(ref_rows)
summary["python_same_bytes"] = md5(K.OUT) == md5(REF)
print(f"\n① Python 재실행: {len(read_rows(K.OUT))}건, 원본 CSV와 바이트까지 같음 = {summary['python_same_bytes']} ({summary['python_main_s']}s)")

# 파싱 (DB에 넣을 것)
P = {y: K.load_pages(f"KR_Notation_{y}.pkl") for y in (2022, 2026)}
S = {y: K.section_of_pages(P[y]) for y in P}
U = {y: K.collapse(K.page_units(P[y], S[y])) for y in P}
nul = sum("\x00" in t for y in P for t in P[y].values())
assert nul == 0, f"NUL 문자가 든 쪽 {nul}개"

# ② DB에 넣기 ----------------------------------------------------------------------------------
with psycopg.connect("host=localhost port=5433 user=postgres dbname=postgres", autocommit=True) as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname = 'hdrag'").fetchone():
        c.execute("CREATE DATABASE hdrag")
db = psycopg.connect("host=localhost port=5433 user=postgres dbname=hdrag", autocommit=True)
db.execute((HERE / "edition_diff.sql").read_text(encoding="utf-8"))
summary["server"] = db.execute("SELECT version()").fetchone()[0].split(",")[0]

t = time.perf_counter()
db.execute("INSERT INTO documents VALUES ('KR2022', 'KR', 2022), ('KR2026', 'KR', 2026)")
with db.cursor() as cur:
    with cur.copy("COPY pages (page_id, doc_id, page_no, raw, section) FROM STDIN") as cp:
        for y in P:
            for p in sorted(P[y]):
                cp.write_row((f"KR{y}:{p}", f"KR{y}", p, P[y][p], S[y][p]))
    with cur.copy("COPY notations (doc_id, section, name, pages, req) FROM STDIN") as cp:
        for y in U:
            for (sec, name), (pgs, req) in U[y].items():
                cp.write_row((f"KR{y}", sec, name, sorted(pgs), req))
summary["load_s"] = round(time.perf_counter() - t, 3)
t = time.perf_counter()
db.execute("REFRESH MATERIALIZED VIEW section_texts")
db.execute("REFRESH MATERIALIZED VIEW doc_texts")
summary["refresh_s"] = round(time.perf_counter() - t, 3)
cnt = {tb: db.execute(f"SELECT count(*) FROM {tb}").fetchone()[0] for tb in ("documents", "pages", "notations", "section_texts")}
summary["db_rows"] = cnt
print(f"② DB 적재: {cnt} · 적재 {summary['load_s']}s · 본문 뷰 갱신 {summary['refresh_s']}s")

# ④-1 정규화가 같은지 (SQL kkey vs Python compact) -----------------------------------------------
pg_keys = dict(db.execute("SELECT page_id, kkey(raw) FROM pages").fetchall())
bad_pages = [pid for pid, k in pg_keys.items() if k != K.compact(P[int(pid[2:6])][int(pid.split(':')[1])])]
names = db.execute("SELECT name, kkey(name), req, req_key(req) FROM notations").fetchall()
bad_names = [n for n, k, _, _ in names if k != K.compact(n)]
req_fn = lambda v: K.compact(K.re.sub(r"(?<=[,\s])\d\)", "", v or ""))
bad_reqs = [r for _, _, r, rk in names if r is not None and rk != req_fn(r)]
T = {y: K.section_text(P[y], S[y]) for y in P}
sec_hay = {(d, s): h for d, s, h in db.execute("SELECT doc_id, section, hay FROM section_texts").fetchall()}
bad_secs = [(d, s) for (d, s), h in sec_hay.items() if h != T[int(d[2:])][s]]
summary["norm_mismatch"] = {"pages": len(bad_pages), "names": len(bad_names), "reqs": len(bad_reqs), "section_texts": len(bad_secs)}
print(f"④ 정규화 비교 (SQL vs Python): 쪽 {len(pg_keys)}개 중 다름 {len(bad_pages)} · 이름 {len(names)}개 중 다름 {len(bad_names)}"
      f" · 요건 다름 {len(bad_reqs)} · 절 본문 {len(sec_hay)}개 중 다름 {len(bad_secs)}")

# ③ SQL 판정 ------------------------------------------------------------------------------------
longest = db.execute("""SELECT max(length(kkey(name))) FROM notations
                        WHERE doc_id = 'KR2026' AND absent_in(name, section, 'KR2022')""").fetchone()[0]
summary["longest_added_name_key"] = longest   # SequenceMatcher의 b(신설 후보) 쪽만 autojunk 대상
assert longest < 200, "신설 후보 이름이 200자 이상이면 Python autojunk 때문에 seq가 SequenceMatcher와 달라짐"
results = {}
for method in ("lev", "trgm", "seq"):        # lev = 미리 정한 주 기준, trgm = 참고, seq = 결과를 본 뒤 추가 (Python과 같은 알고리즘)
    t = time.perf_counter()
    rows = [tuple(r) for r in db.execute("SELECT * FROM edition_diff('KR2022', 'KR2026', 0.6, %s)", (method,)).fetchall()]
    sec = round(time.perf_counter() - t, 3)
    path = OUT / f"sql_{method}_kr_edition_diff.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        w.writerows(rows)
    only_sql = sorted(set(rows) - set(ref_rows))
    only_py = sorted(set(ref_rows) - set(rows))
    kinds = defaultdict(int)
    for r in rows:
        kinds[r[1].split(" (")[0]] += 1
    results[method] = dict(rows=len(rows), same_bytes=md5(path) == md5(REF), same_order=rows == ref_rows,
                           only_sql=only_sql, only_python=only_py, seconds=sec, kinds=dict(kinds))
    print(f"③ SQL 판정 ({method}): {len(rows)}건 {dict(kinds)} · 원본 CSV와 바이트까지 같음 = {results[method]['same_bytes']}"
          f" · SQL에만 {len(only_sql)} · Python에만 {len(only_py)} · {sec}s")
    for r in only_sql:
        print("    SQL에만:", r[:3])
    for r in only_py:
        print("    Python에만:", r[:3])
summary["sql"] = results

# ④-2 명칭 변경 후보 쌍: 같은 절의 (삭제 후보 × 신설 후보) 유사도 세 가지 -----------------------------
pairs = db.execute("""
    SELECT r.section, r.name, a.name, name_sim(r.name, a.name, 'lev'), name_sim(r.name, a.name, 'trgm'),
           name_sim(r.name, a.name, 'seq')
    FROM notations r JOIN notations a ON a.section = r.section
    WHERE r.doc_id = 'KR2022' AND a.doc_id = 'KR2026'
      AND absent_in(r.name, r.section, 'KR2026') AND absent_in(a.name, a.section, 'KR2022')
    ORDER BY 1, 2, 3""").fetchall()
with open(OUT / "rename_pairs.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["절", "2022 이름", "2026 이름", "Python SequenceMatcher", "SQL levenshtein", "SQL trigram", "SQL seq_ratio",
                "0.6 판정 (py/lev/trgm/seq)"])
    flip = {"lev": 0, "trgm": 0, "seq": 0}
    seq_diff = 0.0
    for sec, a, b, lev, tg, sq in pairs:
        py = SequenceMatcher(None, K.compact(a), K.compact(b)).ratio()
        seq_diff = max(seq_diff, abs(py - sq))
        for m, v in (("lev", lev), ("trgm", tg), ("seq", sq)):
            flip[m] += (py >= 0.6) != (v >= 0.6)
        marks = "".join("O" if v >= 0.6 else "-" for v in (py, lev, tg, sq))
        w.writerow([sec, a, b, f"{py:.3f}", f"{lev:.3f}", f"{tg:.3f}", f"{sq:.3f}", marks])
summary["rename_pairs"] = {"pairs": len(pairs), "disagree_with_python_at_0.6": flip, "seq_max_abs_diff": seq_diff}
print(f"④ 명칭 변경 후보 쌍 {len(pairs)}개: Python과 0.6 판정이 다른 쌍 {flip} · seq_ratio와 Python 값 최대 차이 {seq_diff:.2e}")

# 검색에 쓸 결과를 저장 표에 넣고, 검색에 쓰는 모양을 백엔드 방식과 비교 ---------------------------------------
STORE = "seq" if results["seq"]["same_bytes"] else "lev"
summary["stored_method"] = STORE
db.execute("TRUNCATE edition_changes")
db.execute("INSERT INTO edition_changes SELECT 'KR2022', 'KR2026', * FROM edition_diff('KR2022', 'KR2026', 0.6, %s)", (STORE,))
sql_changed = defaultdict(set)
for pid, kind in db.execute("SELECT page_id, kind FROM edition_change_pages").fetchall():
    sql_changed[pid].add(kind)
ref_changed = defaultdict(set)          # backend rag/part1.py 934–939행과 같은 방식
for r in csv.DictReader(open(REF, encoding="utf-8-sig")):
    kind = r["구분"].split(" (")[0]
    for col, doc in (("2022 쪽", "KR2022"), ("2026 쪽", "KR2026")):
        for p in r[col].split():
            ref_changed[f"{doc}:{p}"].add(kind)
summary["changed_pages"] = {"sql": len(sql_changed), "csv": len(ref_changed), "same": dict(sql_changed) == dict(ref_changed)}
print(f"⑤ 쪽 → 개정 기록 종류 (DB 표 edition_changes, {STORE}): SQL {len(sql_changed)}쪽 · CSV {len(ref_changed)}쪽"
      f" · 같음 = {summary['changed_pages']['same']}")
for pid in sorted(set(sql_changed) | set(ref_changed)):
    if sql_changed.get(pid) != ref_changed.get(pid):
        print(f"    {pid}: SQL {sorted(sql_changed.get(pid, []))} · CSV {sorted(ref_changed.get(pid, []))}")
json.dump({k: v for k, v in sql_changed.items()}, open(OUT / "sql_changed_pages.json", "w", encoding="utf-8"),
          ensure_ascii=False, default=sorted, indent=0)
json.dump(summary, open(OUT / "summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
