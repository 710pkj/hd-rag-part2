-- 검색용 DB 스키마: Neon(RAG_SQL연동.ipynb 셀 23)과 같은 표 · 칸 · 제약 · 색인
-- 로컬 PostgreSQL의 검색용 DB(hdsearch)에 그대로 씀. 판본 비교 DB(hdrag)와는 DB를 나눠
-- 이름이 같고 구조가 다른 documents · pages가 부딪치지 않게 함 (설계서 3.5.4)
-- 실행은 load_search_db.py가 함 (직접 실행해도 됨: 모두 IF NOT EXISTS)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  doc_id   text PRIMARY KEY,                               -- 'KR2026'
  society  text NOT NULL,                                  -- 'KR' | 'ABS' | ...
  year     int  NOT NULL CHECK (year BETWEEN 2000 AND 2100),
  source   text,                                           -- 원본 pkl 이름
  added_at timestamptz DEFAULT now(),
  UNIQUE (society, year)                                   -- 같은 판을 두 번 넣으면 거부
);
CREATE TABLE IF NOT EXISTS pages (
  page_id     text PRIMARY KEY,                            -- 'KR2026:236'
  doc_id      text NOT NULL REFERENCES documents,
  page_no     int  NOT NULL,
  raw         text,
  search_text text
);
CREATE TABLE IF NOT EXISTS pipeline_versions (             -- 처리 규칙 묶음. 규칙을 바꾸면 새 버전
  pipeline_ver  text PRIMARY KEY,
  rules_version text NOT NULL,                             -- rules.csv 해시
  model         text NOT NULL,                             -- 임베딩 모델 · 최대 길이
  note          text,
  created_at    timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chunks (
  chunker      text NOT NULL,                              -- 'struct'(E9) | 'e13_2'(구조 기반)
  chunk_id     text NOT NULL,                              -- 'KR2026:236#2'
  ord          int  NOT NULL,                              -- FAISS 색인의 행 번호 (동점 순서용)
  page_id      text NOT NULL REFERENCES pages,
  doc_id       text NOT NULL REFERENCES documents,
  text         text NOT NULL,                              -- 임베딩한 글 (dense_text)
  content_hash text NOT NULL,                              -- EmbeddingCache와 같은 키
  pipeline_ver text NOT NULL REFERENCES pipeline_versions,
  dense        vector(1024) NOT NULL,
  sparse       sparsevec(250002) NOT NULL,
  PRIMARY KEY (chunker, chunk_id),
  UNIQUE (chunker, ord)
);
CREATE INDEX IF NOT EXISTS chunks_filter ON chunks (chunker, doc_id);
CREATE INDEX IF NOT EXISTS chunks_hash ON chunks (content_hash);
CREATE TABLE IF NOT EXISTS rerank_scores (                 -- 리랭커 점수 캐시 (GPU fp16 값만)
  query        text NOT NULL,
  passage_hash text NOT NULL,
  model        text NOT NULL,
  score        real NOT NULL,
  PRIMARY KEY (query, passage_hash, model)
);
