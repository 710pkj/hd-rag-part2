-- KR 판본 비교를 SQL로: 파싱(쪽 → 절, 노테이션 후보 뽑기)만 Python이 하고,
-- 정규화 · 신설 · 삭제 · 명칭 변경 · 요건 변경 판정은 모두 DB 안에서 한다.
-- 기준: 07_판비교_쿼리손질/kr_edition_diff.py 와 같은 규칙 (결과 93건을 그대로 내는지 확인)

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP FUNCTION IF EXISTS edition_diff, name_sim, seq_ratio, absent_in CASCADE;
DROP MATERIALIZED VIEW IF EXISTS doc_texts, section_texts CASCADE;
DROP TABLE IF EXISTS edition_changes, notations, pages, documents CASCADE;

CREATE TABLE documents (
    doc_id  text PRIMARY KEY,                       -- 'KR2022', 'KR2026'
    society text NOT NULL,
    year    int  NOT NULL,
    UNIQUE (society, year)
);

CREATE TABLE pages (
    page_id text PRIMARY KEY,                       -- 'KR2026:176'
    doc_id  text NOT NULL REFERENCES documents,
    page_no int  NOT NULL,
    raw     text NOT NULL,                          -- pkl의 page_content 그대로
    section text NOT NULL DEFAULT '',               -- Python 파싱 결과 (절이 없으면 '')
    UNIQUE (doc_id, page_no)
);

CREATE TABLE notations (                            -- 노테이션 후보 (NOTATIONS 목록 항목 · 요건표 행)
    doc_id  text  NOT NULL REFERENCES documents,
    section text  NOT NULL,
    name    text  NOT NULL,                         -- 표시용 정규화(norm)까지 한 이름
    pages   int[] NOT NULL,                         -- 나온 쪽 (오름차순)
    req     text,                                   -- 요건(설계 · 검사 근거), 목록 항목뿐이면 NULL
    PRIMARY KEY (doc_id, section, name)
);

-- 비교용 열쇠: 각주 위첨자 삭제 → NFKC → <br> → 소문자 → 영문 · 숫자 · 한글만 (kr_edition_diff.compact)
CREATE OR REPLACE FUNCTION kkey(s text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT regexp_replace(
             lower(replace(normalize(regexp_replace(coalesce(s, ''), '[¹²³⁴⁵⁶⁷⁸⁹⁰]+[⁾)]?', '', 'g'), NFKC), '<br>', ' ')),
             '[^0-9a-z가-힣]', '', 'g')
$$;

-- 요건 비교용: 2022판에만 일반 문자로 남은 각주 번호("Pt 3, 2), 3)")를 뺀 뒤 열쇠로 (kr_edition_diff.req)
CREATE OR REPLACE FUNCTION req_key(s text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT kkey(regexp_replace(coalesce(s, ''), '(?<=[,\s])\d\)', '', 'g'))
$$;

-- 절 본문 · 문서 전체 본문 (열쇠 형태로 이어 붙임). 새 판을 넣으면 REFRESH 한 번
CREATE MATERIALIZED VIEW section_texts AS
    SELECT doc_id, section, string_agg(kkey(raw), '' ORDER BY page_no) AS hay
    FROM pages WHERE section <> '' GROUP BY doc_id, section;
CREATE UNIQUE INDEX ON section_texts (doc_id, section);

CREATE MATERIALIZED VIEW doc_texts AS
    SELECT doc_id, string_agg(kkey(raw), '' ORDER BY page_no) AS hay
    FROM pages GROUP BY doc_id;
CREATE UNIQUE INDEX ON doc_texts (doc_id);

-- 그 판의 같은 절 본문(그 판에 절이 없으면 문서 전체)에 이름이 없으면 true
CREATE OR REPLACE FUNCTION absent_in(p_name text, p_section text, p_doc text) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT strpos(coalesce(nullif((SELECT hay FROM section_texts WHERE doc_id = p_doc AND section = p_section), ''),
                           (SELECT hay FROM doc_texts WHERE doc_id = p_doc)),
                  kkey(p_name)) = 0
$$;

-- Python difflib.SequenceMatcher(None, x, y).ratio()와 같은 계산 (Ratcliff/Obershelp: 가장 긴 공통 구간을 찾고
-- 그 왼쪽 · 오른쪽에서 되풀이, 2 × 맞은 글자 수 / 두 길이 합). 같은 길이면 x에서 먼저, 그다음 y에서 먼저 나온 구간.
-- y가 200자 이상이면 Python은 흔한 글자를 버리는 autojunk를 쓰므로 그때는 같지 않음 (여기 이름은 모두 200자 미만)
CREATE OR REPLACE FUNCTION seq_ratio(x text, y text) RETURNS double precision
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    a text[] := regexp_split_to_array(x, '');
    b text[] := regexp_split_to_array(y, '');
    la int := length(x);
    lb int := length(y);
    stack int[];                 -- (alo, ahi, blo, bhi) 네 개씩, 0부터 세고 끝은 포함 안 함
    alo int; ahi int; blo int; bhi int;
    prev int[]; cur int[];
    i int; j int; k int; bi int; bj int; bk int;
    m int := 0;
BEGIN
    IF la + lb = 0 THEN RETURN 1; END IF;
    IF la = 0 OR lb = 0 THEN RETURN 0; END IF;
    stack := ARRAY[0, la, 0, lb];
    WHILE coalesce(array_length(stack, 1), 0) > 0 LOOP
        alo := stack[1]; ahi := stack[2]; blo := stack[3]; bhi := stack[4];
        stack := stack[5:];
        bi := alo; bj := blo; bk := 0;
        prev := array_fill(0, ARRAY[lb + 1]);
        FOR i IN alo .. ahi - 1 LOOP
            cur := array_fill(0, ARRAY[lb + 1]);
            FOR j IN blo .. bhi - 1 LOOP
                IF a[i + 1] = b[j + 1] THEN
                    k := CASE WHEN j > blo THEN prev[j] ELSE 0 END + 1;   -- prev[j] = (i−1, j−1)에서 끝나는 길이
                    cur[j + 1] := k;
                    IF k > bk THEN bi := i - k + 1; bj := j - k + 1; bk := k; END IF;
                END IF;
            END LOOP;
            prev := cur;
        END LOOP;
        IF bk > 0 THEN
            m := m + bk;
            IF alo < bi AND blo < bj THEN stack := stack || ARRAY[alo, bi, blo, bj]; END IF;
            IF bi + bk < ahi AND bj + bk < bhi THEN stack := stack || ARRAY[bi + bk, ahi, bj + bk, bhi]; END IF;
        END IF;
    END LOOP;
    RETURN 2.0 * m / (la + lb);
END
$$;

-- 이름 유사도 (모두 열쇠끼리): 'lev' = 1 − 편집 거리 / 긴 쪽 길이,  'trgm' = pg_trgm similarity,
-- 'seq' = Python SequenceMatcher와 같은 계산
CREATE OR REPLACE FUNCTION name_sim(a text, b text, method text DEFAULT 'lev') RETURNS double precision
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE method
             WHEN 'trgm' THEN similarity(kkey(a), kkey(b))::double precision
             WHEN 'seq'  THEN seq_ratio(kkey(a), kkey(b))
             ELSE 1 - levenshtein(kkey(a), kkey(b))::double precision / greatest(length(kkey(a)), length(kkey(b)), 1)
           END
$$;

-- 판본 비교: 옛 판과 새 판을 넣으면 신설 · 삭제 · 명칭 변경 · 요건 변경 목록을 돌려줌
CREATE OR REPLACE FUNCTION edition_diff(old_doc text, new_doc text,
                                        rename_min double precision DEFAULT 0.6, method text DEFAULT 'lev')
RETURNS TABLE (section text, kind text, notation text, old_pages text, new_pages text, old_req text, new_req text)
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    b record;
BEGIN
    DROP TABLE IF EXISTS _added, _removed, _out;
    CREATE TEMP TABLE _added AS
        SELECT n.section, n.name, n.pages, n.req FROM notations n
        WHERE n.doc_id = new_doc AND absent_in(n.name, n.section, old_doc);
    CREATE TEMP TABLE _removed AS
        SELECT n.section, n.name, n.pages, n.req FROM notations n
        WHERE n.doc_id = old_doc AND absent_in(n.name, n.section, new_doc);
    CREATE TEMP TABLE _out (section text, kind text, notation text, old_pages text, new_pages text, old_req text, new_req text);

    -- 같은 절의 삭제 · 신설 쌍 중 이름이 비슷한 것 → 명칭 변경 (삭제 쪽을 이름순으로 돌며 가장 비슷한 신설을 짝지음)
    FOR r IN SELECT * FROM _removed x ORDER BY x.section, x.name LOOP
        SELECT a.*, name_sim(r.name, a.name, method) AS s INTO b
        FROM _added a WHERE a.section = r.section
        ORDER BY s DESC, a.name LIMIT 1;
        IF FOUND AND b.s >= rename_min THEN
            INSERT INTO _out VALUES (r.section, '명칭 변경', r.name || ' → ' || b.name,
                                     array_to_string(r.pages, ' '), array_to_string(b.pages, ' '),
                                     coalesce(r.req, ''), coalesce(b.req, ''));
            DELETE FROM _removed x WHERE x.section = r.section AND x.name = r.name;
            DELETE FROM _added a WHERE a.section = b.section AND a.name = b.name;
        END IF;
    END LOOP;

    INSERT INTO _out
    SELECT a.section,
           CASE WHEN EXISTS (SELECT 1 FROM notations o WHERE o.doc_id = old_doc AND o.section = a.section)
                THEN '신설' ELSE '신설 (절 신설)' END,
           a.name, '', array_to_string(a.pages, ' '), '', coalesce(a.req, '')
    FROM _added a;

    INSERT INTO _out
    SELECT x.section,
           CASE WHEN EXISTS (SELECT 1 FROM notations o WHERE o.doc_id = new_doc AND o.section = x.section)
                THEN '삭제' ELSE '삭제 (절 삭제)' END,
           x.name, array_to_string(x.pages, ' '), '', coalesce(x.req, ''), ''
    FROM _removed x;

    -- 이름은 같고 요건(설계 · 검사 근거)이 바뀐 경우
    INSERT INTO _out
    SELECT n.section, '요건 변경', n.name, array_to_string(o.pages, ' '), array_to_string(n.pages, ' '), o.req, n.req
    FROM notations n
    JOIN notations o ON o.doc_id = old_doc AND o.section = n.section AND o.name = n.name
    WHERE n.doc_id = new_doc
      AND coalesce(o.req, '') <> '' AND coalesce(n.req, '') <> ''
      AND req_key(o.req) <> req_key(n.req);

    RETURN QUERY SELECT * FROM _out o ORDER BY o.section, o.kind, o.notation;
END
$$;

-- 비교 결과를 저장하는 표: 새 판을 넣을 때 한 번 계산해 넣음
CREATE TABLE edition_changes (
    old_doc   text NOT NULL REFERENCES documents,
    new_doc   text NOT NULL REFERENCES documents,
    section   text NOT NULL,
    kind      text NOT NULL CHECK (split_part(kind, ' (', 1) IN ('신설', '삭제', '명칭 변경', '요건 변경')),
    notation  text NOT NULL,
    old_pages text NOT NULL,
    new_pages text NOT NULL,
    old_req   text NOT NULL,
    new_req   text NOT NULL
);

-- 검색에서 쓰는 모양: 쪽마다 붙은 개정 기록 종류 (백엔드 part1.CHANGED와 같은 것)
CREATE VIEW edition_change_pages AS
    SELECT DISTINCT d.doc || ':' || p AS page_id, split_part(d.kind, ' (', 1) AS kind
    FROM (SELECT old_doc AS doc, kind, old_pages AS pg FROM edition_changes
          UNION ALL
          SELECT new_doc, kind, new_pages FROM edition_changes) d,
         unnest(string_to_array(nullif(d.pg, ''), ' ')) AS p;
