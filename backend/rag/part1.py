"""Part 1 검색기 (RAG_Part1_제출.ipynb의 최종 통합 구성)를 모듈로 옮긴 것.

노트북 셀 2·4·6·7·12·14·16·18·19·20·38·41·43·45·47의 코드를 거의 그대로 가져왔다.
임베딩·리랭커 점수 캐시(cache/*.pkl)의 키가 텍스트 해시라서, 전처리·청킹 코드를 바꾸면 캐시가 맞지 않는다.
바꾼 것: Colab 전용 코드(Drive 마운트, display, 보안 비밀) 제거 · Groq 키는 환경변수에서 읽음 ·
EN_V2[qid] 대신 영어 검색 문장을 인자로 받음 · 노드 표시용 trace를 돌려줌 · 문서 범위(filters)를 받음.

데이터 폴더(PART1_DIR)에 필요한 것: pkl 3개, rules.csv, dev_set.csv, test_set.csv,
cache/(bge_m3_cache.pkl, score_cache.pkl, query_struct.json), outputs/kr_edition_diff.csv
"""
import hashlib
import json
import math
import os
import pickle
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import query_intent as QI

REPO = Path(__file__).resolve().parents[2]   # hd-rag-part2
try:   # backend/.env의 PART1_DIR (서버 밖에서 이 모듈만 쓸 때도)
    from dotenv import load_dotenv

    load_dotenv(REPO / "backend" / ".env")
except ImportError:
    pass


def _find_data_dir() -> Path:
    """Part 1 제출 폴더 찾기: 환경변수 PART1_DIR → 프로젝트 안 data/HD_RAG_Part1 → 만든 사람 PC의 경로"""
    cands = [os.environ.get("PART1_DIR"), REPO / "data" / "HD_RAG_Part1", r"C:\Users\710pk\OneDrive\Desktop\HD융캡디\제출\HD_RAG_Part1"]
    for c in filter(None, cands):
        if (Path(c) / "test_set.csv").exists():
            return Path(c)
    raise FileNotFoundError(f"Part 1 제출 폴더(HD_RAG_Part1)를 찾지 못함. {REPO / 'data' / 'HD_RAG_Part1'}에 두거나 backend/.env에 PART1_DIR=경로 를 적을 것")


DATA_DIR = _find_data_dir()
CACHE_DIR, OUT_DIR = DATA_DIR / "cache", DATA_DIR / "outputs"
RUNTIME_CACHE = Path(__file__).resolve().parent.parent / "cache_runtime"   # 새 질문의 점수·영어 문장 캐시 (제출 캐시는 건드리지 않음)
RUNTIME_CACHE.mkdir(exist_ok=True)

TOP_K = 10
DEPTH = 50
RRF_K = 60
GROQ_MODEL_QS = "openai/gpt-oss-120b"   # 영어 검색 문장을 만든 LLM. query_struct.json 캐시 키에 들어가므로 바꾸지 않는다

# ───────────────────────── 셀 4: 데이터 로딩 ─────────────────────────
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


SOURCES = {
    "KR2022": ("KR_Notation_2022.pkl", "KR", 2022),
    "KR2026": ("KR_Notation_2026.pkl", "KR", 2026),
    "ABS2025": ("ABS-class-notations-2025.pkl", "ABS", 2025),
}

# ───────────────────────── 셀 6: 규칙 ─────────────────────────
@dataclass
class Rule:
    source: str
    target: str
    type: str
    society: str | None
    stage: str
    pattern: re.Pattern


REPLACE_TYPES = ("repair", "normalize")
EXPAND_TYPES = ("symbol", "abbr", "synonym_one", "synonym_both")


def parse_condition(cond: str) -> dict:
    out = {}
    for part in filter(None, (p.strip() for p in cond.split(";"))):
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def compile_rule(r) -> Rule:
    c = parse_condition(r.condition)
    if c.get("match") == "regex":
        pattern = r.source
    else:
        pattern = re.escape(r.source)
        if r.type in EXPAND_TYPES:
            if r.source[:1].isalnum():
                pattern = r"(?<![A-Za-z0-9])" + pattern
            if r.source[-1:].isalnum():
                pattern += r"(?![A-Za-z0-9])"
    return Rule(r.source, r.target, r.type, c.get("society") or None, c.get("stage", "post_nfkc"), re.compile(pattern))


RULES: list[Rule] = []


def in_scope(rule, societies) -> bool:
    return rule.society is None or rule.society in societies


def apply_replace(text, society, types, stage=None):
    for r in RULES:
        if r.type in types and in_scope(r, {society}) and (stage is None or r.stage == stage):
            text = r.pattern.sub(lambda m, t=r.target: t, text)
    return text


def expand_index_text(text, society, types):
    for r in RULES:
        if r.type not in types or not in_scope(r, {society}) or not r.target:
            continue
        if r.target.lower() in text.lower():
            continue
        text = r.pattern.sub(lambda m, t=r.target: f"{m.group(0)} ({t})", text, count=1)
    return text


def expand_query(query, types, societies):
    extra = []
    for r in RULES:
        if r.type not in types or not in_scope(r, societies) or not r.target:
            continue
        if r.pattern.search(query):
            extra.append(r.target)
        elif r.type == "synonym_both" and r.target in query:
            extra.append(r.source)
    return query + (" " + " ".join(extra) if extra else "")


# ───────────────────────── 셀 7: 전처리 ─────────────────────────
PROTECT = "✠ⒺⓂⓅ"
_PROTECT_RE = re.compile(f"([{PROTECT}])")


def nfkc_protected(s: str) -> str:
    return "".join(p if len(p) == 1 and p in PROTECT else unicodedata.normalize("NFKC", p) for p in _PROTECT_RE.split(s))


SPLIT_RE = re.compile(r"\b([A-Z][a-z]?) ([a-z]{2,})\b")
STANDALONE: dict = {}


def build_standalone_counts(texts):
    total = Counter(w for t in texts for w in re.findall(r"\b[a-z]{2,}\b", t))
    in_split = Counter(m.group(2) for t in texts for m in SPLIT_RE.finditer(t))
    return {w: total[w] - n for w, n in in_split.items()}


def rejoin_split_initials(t: str) -> str:
    return SPLIT_RE.sub(lambda m: m.group(1) + m.group(2) if STANDALONE.get(m.group(2), 1) == 0 else m.group(0), t)


TABLE_RULE_RE = re.compile(r"^(?=.*-{3})[ \t|:\-]+$", re.M)


def normalize_layout(s: str) -> str:
    s = TABLE_RULE_RE.sub("", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def clean_page(raw: str, society: str):
    t = apply_replace(raw, society, ("repair",))
    if society == "ABS":
        t = rejoin_split_initials(t)
    text = t
    s = apply_replace(t, society, ("normalize",), stage="pre_nfkc")
    s = nfkc_protected(s)
    s = apply_replace(s, society, ("normalize",), stage="post_nfkc")
    return text, normalize_layout(s)


# ───────────────────────── 셀 12: 청킹 ─────────────────────────
def struct_chunks(text, society, max_chars=1200):
    if society == "ABS":
        if len(text) <= 2500:
            return [text]
        m = re.search(r"## NOTATION\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        head = "NOTATION: " + " ".join(m.group(1).split())[:200] if m else ""
        secs = [s.strip() for s in re.split(r"\n(?=## )", text) if s.strip()]
        return [s if s.startswith("## NOTATION") or not head else f"{head}\n{s}" for s in secs]
    chunks, buf, heading = [], [], ""

    def flush():
        block = "\n".join(buf).strip()
        buf.clear()
        if len(block) > 20:
            chunks.append(f"{heading}\n{block}" if heading else block)

    for line in text.split("\n"):
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
        elif line.startswith("|"):
            flush()
            row = " | ".join(c.strip() for c in line.strip().strip("|").split("|") if c.strip())
            if len(row) > 20:
                chunks.append(f"{heading}\n{row}" if heading else row)
        else:
            buf.append(line)
            if sum(map(len, buf)) > max_chars:
                flush()
    flush()
    return chunks or [text]


def make_chunks(df, mode, col):
    out = []
    for r in df.itertuples():
        text = getattr(r, col)
        pieces = [text] if mode == "page" else struct_chunks(text, r.society)
        for i, piece in enumerate(pieces):
            out.append({"chunk_id": f"{r.page_id}#{i}", "page_id": r.page_id, "doc_id": r.doc_id, "society": r.society, "text": piece})
    return pd.DataFrame(out)


# ───────────────────────── 셀 14: BGE-M3 · 리랭커 (처음 필요할 때 불러옴) ─────────────────────────
_MODEL_LOCK = threading.Lock()
_DEVICE = None


def device():
    """Intel Arc(XPU) → CUDA → CPU 순. RAG_DEVICE 환경변수로 고정할 수 있다. GPU면 fp16"""
    global _DEVICE
    if _DEVICE is None:
        import torch

        want = os.environ.get("RAG_DEVICE", "").strip()
        if want:
            _DEVICE = want
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            _DEVICE = "xpu"
        elif torch.cuda.is_available():
            _DEVICE = "cuda"
        else:
            _DEVICE = "cpu"
    return _DEVICE


class BGEM3:
    """BAAI/bge-m3의 dense·sparse 출력을 한 번의 forward로 계산 (노트북 셀 14와 같음. GPU면 fp16)"""

    name, max_length = "BAAI/bge-m3", 8192   # 임베딩 캐시 키에 들어가는 값

    def __init__(self):
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(max(1, os.cpu_count() or 1))
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(self.name)
        dev = device()
        self.model = AutoModel.from_pretrained(self.name).to(dev).eval()
        hidden = self.model.config.hidden_size
        self.sparse_linear = torch.nn.Linear(hidden, 1)
        self.sparse_linear.load_state_dict(torch.load(hf_hub_download(self.name, "sparse_linear.pt"), map_location="cpu"))
        self.sparse_linear.to(dev).eval()
        if dev != "cpu":
            self.model.half()
            self.sparse_linear.half()
        self.vocab_size = len(self.tok)
        self.skip_ids = {i for i in (self.tok.cls_token_id, self.tok.eos_token_id, self.tok.pad_token_id, self.tok.unk_token_id) if i is not None}
        self._loaded = True

    def encode(self, texts, batch_size=8):
        with _MODEL_LOCK:
            self.load()
            torch = self.torch
            n = len(texts)
            out = {"dense": [None] * n, "sparse": [None] * n}
            order = sorted(range(n), key=lambda i: -len(texts[i]))
            with torch.no_grad():
                for s in range(0, n, batch_size):
                    idx = order[s:s + batch_size]
                    batch = self.tok([texts[i] for i in idx], padding=True, truncation=True, max_length=self.max_length, return_tensors="pt").to(device())
                    hidden = self.model(**batch).last_hidden_state
                    ids = batch["input_ids"].cpu().numpy()
                    d = torch.nn.functional.normalize(hidden[:, 0].float(), dim=-1).cpu().numpy()
                    w = torch.relu(self.sparse_linear(hidden)).squeeze(-1).float().cpu().numpy()
                    for j, i in enumerate(idx):
                        out["dense"][i] = d[j]
                        lw = {}
                        for tid, wt in zip(ids[j].tolist(), w[j].tolist()):
                            if wt > 0 and tid not in self.skip_ids and wt > lw.get(tid, 0.0):
                                lw[tid] = wt
                        out["sparse"][i] = lw
            out["dense"] = np.stack(out["dense"]).astype(np.float32)
            return out


M3 = BGEM3()
VOCAB_SIZE = 250002   # bge-m3 토크나이저 크기 (모델을 불러오지 않고 sparse 행렬을 만들기 위해)


class CrossReranker:
    """BAAI/bge-reranker-v2-m3 cross-encoder (노트북 셀 19와 같음. GPU면 fp16 — Arc GPU에서 50쌍 2.5초, CPU 80초)"""

    def __init__(self, name="BAAI/bge-reranker-v2-m3", max_length=1024):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).to(device()).eval()
        if device() != "cpu":
            self.model.half()
        self.max_length = max_length

    def score(self, query, passages, batch_size=4):
        out = []
        with _MODEL_LOCK, self.torch.no_grad():
            for i in range(0, len(passages), batch_size):
                b = self.tok([[query, p] for p in passages[i:i + batch_size]], padding=True, truncation=True,
                             max_length=self.max_length, return_tensors="pt").to(device())
                out.extend(self.model(**b).logits.view(-1).float().cpu().tolist())
        return out


_CROSS = None


def cross_reranker():
    global _CROSS
    with _MODEL_LOCK:
        if _CROSS is None:
            _CROSS = CrossReranker()
    return _CROSS


# ───────────────────────── 셀 16: 색인 ─────────────────────────
class EmbeddingCache:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = pickle.load(f)
        self.new = 0

    def key(self, text):
        return hashlib.sha1(f"{M3.name}|{M3.max_length}|{text}".encode()).hexdigest()

    def get(self, texts):
        keys = [self.key(t) for t in texts]
        todo = sorted({k: t for k, t in zip(keys, texts) if k not in self.data}.items())
        if todo:
            t0 = time.time()
            out = M3.encode([t for _, t in todo])
            for j, (k, _) in enumerate(todo):
                self.data[k] = (out["dense"][j].astype(np.float16), out["sparse"][j])
            self.new += len(todo)
            print(f"  임베딩 {len(todo)}개 새로 계산 ({time.time() - t0:.0f}s)")
        return np.stack([self.data[k][0] for k in keys]).astype(np.float32), [self.data[k][1] for k in keys]


STOPWORDS = set("a an the of to in on for and or is are be by with as at from that this which it its into than any all such other shall".split())
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[\-_/.][a-z0-9]+)*\+*")


def bm25_tokenize(text: str):
    toks = []
    for m in TOKEN_RE.finditer(text.lower()):
        tok = m.group(0)
        toks.append(tok)
        base = tok.rstrip("+")
        if base != tok:
            toks.append(base)
        parts = [p for p in re.split(r"[\-_/.]", base) if p]
        if len(parts) > 1:
            toks.extend(parts)
    return [t for t in toks if t not in STOPWORDS]


def to_csc(sparse_list, vocab_size):
    from scipy.sparse import csr_matrix

    indptr, indices, data = [0], [], []
    for lw in sparse_list:
        indices.extend(lw.keys())
        data.extend(lw.values())
        indptr.append(len(indices))
    m = csr_matrix((np.asarray(data, dtype=np.float32), np.asarray(indices, dtype=np.int64), np.asarray(indptr)), shape=(len(sparse_list), vocab_size))
    return m.tocsc()


class HybridIndex:
    """청크 단위 색인: FAISS(dense) · BGE-M3 sparse 행렬 (최종 구성은 BM25 채널을 쓰지 않아 만들지 않음)"""

    def __init__(self, chunks: pd.DataFrame, cache: EmbeddingCache):
        import faiss

        self.chunks = chunks.reset_index(drop=True)
        dense, sparse = cache.get(self.chunks.dense_text.tolist())
        self.faiss = faiss.IndexFlatIP(dense.shape[1])
        self.faiss.add(dense)
        self.sparse = to_csc(sparse, VOCAB_SIZE)
        self.page_of = self.chunks.page_id.to_numpy()
        self.doc_of = self.chunks.doc_id.to_numpy()

    def scores(self, channel, qv):
        n = len(self.chunks)
        if channel == "dense":
            D, I = self.faiss.search(qv["dense"][None, :], n)
            s = np.full(n, -np.inf, dtype=np.float32)
            s[I[0]] = D[0]
            return s
        if channel == "sparse":
            if not qv["sparse"]:
                return np.zeros(n)
            ids = np.fromiter(qv["sparse"].keys(), dtype=np.int64)
            w = np.fromiter(qv["sparse"].values(), dtype=np.float32)
            return np.asarray(self.sparse[:, ids] @ w).ravel()
        raise ValueError(channel)

    def ranked_pages(self, scores, allowed_docs, depth=DEPTH, positive_only=False):
        ok = np.isin(self.doc_of, list(allowed_docs))
        out, seen = [], set()
        for i in np.argsort(-scores, kind="stable"):
            s = scores[i]
            if not np.isfinite(s) or (positive_only and s <= 0):
                break
            if not ok[i] or self.page_of[i] in seen:
                continue
            seen.add(self.page_of[i])
            out.append((self.page_of[i], float(s)))
            if len(out) >= depth:
                break
        return out


# ───────────────────────── 셀 18: 질문 분석 · 허용 문서 ─────────────────────────
SOCIETY_RE = QI.SOCIETY_RE
EDITIONS = {"KR": (2022, 2026), "ABS": (2025,)}
DOC_OF = {("KR", 2022): "KR2022", ("KR", 2026): "KR2026", ("ABS", 2025): "ABS2025"}
EVENT_CUE = re.compile(r"건조|취득|계약|인도|진수|용골|built|contract|deliver|keel", re.I)


def analyze_query(q):
    socs = [s for s, rx in SOCIETY_RE.items() if rx.search(q)]
    years = [(int(m.group(1)), bool(EVENT_CUE.search(q[m.end(): m.end() + 20]))) for m in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", q)]
    return {"societies": socs or list(EDITIONS), "years": years}


def allowed_docs(info, society_filter=True, year_policy="latest_boost"):
    socs = info["societies"] if society_filter else list(EDITIONS)
    allowed, penalized = set(), set()
    for s in socs:
        eds = EDITIONS[s]
        named = [y for y, is_event in info["years"] if y in eds and not is_event]
        if year_policy != "none" and named:
            chosen = named
        else:
            chosen = list(eds)
            if year_policy == "latest_boost":
                penalized |= {DOC_OF[(s, y)] for y in eds if y != max(eds)}
        allowed |= {DOC_OF[(s, y)] for y in chosen}
    return allowed, penalized


# ───────────────────────── 셀 19: 쿼리 · RRF · 리랭킹 ─────────────────────────
QUERY_MEMO, CROSS_MEMO = {}, {}


def clean_query(q, text_mode="clean"):
    return q if text_mode == "raw" else " ".join(nfkc_protected(q).split())


META_RE = re.compile(r"(?<![A-Za-z])(?:KR|ABS|notations?|rules?|classification|class)(?![A-Za-z])|(?<!\d)20\d{2}(?!\d)", re.I)
DENSE_META_RE = re.compile(
    r"(?<![A-Za-z])(?:KR|ABS)(?![A-Za-z])\s*(?:과|와|의)?|한국선급|미국선급"
    r"|선급\s*기준\s*(?:으로|에서|의)?|(?<!\d)20\d{2}\s*년?\s*도?\s*(?:에|의|과|와)?", re.I)


def strip_dense_meta(q):
    s = DENSE_META_RE.sub(" ", q)
    s = re.sub(r"^[\s,]+|\s+(?=[,?])", "", s)
    return " ".join(s.split()) or q


def lexical_query(q, societies):
    """어휘 채널(sparse)용: 메타 용어 제거 (BEST.strip_meta=True, 사전 확장 없음)"""
    return " ".join(META_RE.sub(" ", q).split())


def rrf(lists, k=RRF_K):
    score = defaultdict(float)
    for lst in lists:
        for rank, (p, _) in enumerate(lst, 1):
            score[p] += 1.0 / (k + rank)
    return score


def _h(t):
    return hashlib.sha1(t.encode()).hexdigest()


def rerank_cross(query, cands, ptexts, stats=None):
    texts = [ptexts[p] for p in cands]
    todo = [t for t in texts if (query, _h(t)) not in CROSS_MEMO]
    if todo:
        t0 = time.time()
        scores = cross_reranker().score(query, todo)
        CROSS_MEMO.update({(query, _h(t)): s for t, s in zip(todo, scores)})
        if stats is not None:
            stats["rerank_new"] = stats.get("rerank_new", 0) + len(todo)
            stats["rerank_sec"] = stats.get("rerank_sec", 0) + time.time() - t0
    s = np.array([CROSS_MEMO[(query, _h(t))] for t in texts])
    return [cands[i] for i in np.argsort(-s, kind="stable")]


# ───────────────────────── 셀 41: 구조 기반 청킹 (E13-2) ─────────────────────────
CHAP_RE = re.compile(r"^#*\s*(?:(?:Ch|CHAPTER)\s*(\d)\b|Annex\s*(\d+)\b)", re.I)
SECT_RE = re.compile(r"^#*\s*(\d+(?:-\d+)?\.\s+[A-Z][^|]{2,80}?)\s*$")
BLOCK_RE = re.compile(r"^#*\s*((?:NOTATIONS|DESCRIPTIONS|REQUIREMENTS|EXAMPLES)\b.*?)\s*$")
HEAD_CELL_RE = re.compile(r"\b(?:Notations?|Design|Survey|Remarks|Requirements|Purpose|Contents)\b", re.I)


def row_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_header(cells):
    filled = [c for c in cells if c]
    return bool(filled) and 2 * sum(len(c) <= 40 and bool(HEAD_CELL_RE.search(c)) for c in filled) >= len(filled)


def kr_chunks(doc_pages):
    """노트북 kr_chunks(mode='kv'): 제목 경로 + 표 행을 '열: 값'으로"""
    st = {"chap_key": None, "chap": "", "sect": "", "block": "", "header": None}
    out = []

    def path():
        return " > ".join(p for p in (st["sect"] or st["chap"], st["block"]) if p)

    def emit(pid, body):
        if len(body) > 20:
            out.append((pid, f"{path()}\n{body}" if path() else body))

    def flush_table(pid, rows):
        for cells in rows:
            raw = " | ".join(c for c in cells if c)
            if is_header(cells):
                st["header"] = cells
                continue
            if len(raw) <= 20:
                continue
            h = st["header"]
            if h and len(h) == len(cells) and cells is not h:
                emit(pid, "; ".join(f"{a}: {b}" if a else b for a, b in zip(h, cells) if b))
            else:
                emit(pid, raw)

    for r in doc_pages.sort_values("page").itertuples():
        lines = r.search_text.split("\n")
        own_sect = any(SECT_RE.match(l) for l in lines)
        if not own_sect and not any(BLOCK_RE.match(l) for l in lines):
            st["sect"] = st["block"] = ""
        buf, rows, n0 = [], [], len(out)

        def flush_buf():
            text = "\n".join(buf).strip()
            buf.clear()
            emit(r.page_id, text)

        for line in lines:
            if line.startswith("|"):
                flush_buf()
                rows.append(row_cells(line))
                continue
            flush_table(r.page_id, rows)
            rows = []
            m_c, m_s, m_b = CHAP_RE.match(line), SECT_RE.match(line), BLOCK_RE.match(line)
            if m_c or m_s or m_b or line.startswith("#"):
                flush_buf()
                if m_c:
                    key = m_c.group(1) or f"A{m_c.group(2)}"
                    name = " ".join(line.lstrip("#").split())
                    if key != st["chap_key"]:
                        st.update(chap_key=key, chap=name, sect="", block="", header=None)
                    elif len(name) > len(st["chap"]):
                        st["chap"] = name
                elif m_s:
                    st["sect"], st["block"] = m_s.group(1).strip(), ""
                elif m_b:
                    st["block"] = m_b.group(1).strip()
                else:
                    st["block"] = line.lstrip("#").strip()
                continue
            buf.append(line)
            if sum(map(len, buf)) > 1200:
                flush_buf()
        flush_table(r.page_id, rows)
        flush_buf()
        if len(out) == n0 and r.search_text.strip():
            out.append((r.page_id, r.search_text))
    return out


def build_e13(pages):
    rows = []
    for doc, g in pages.groupby("doc_id"):
        soc = g.society.iloc[0]
        if soc == "KR":
            ch = kr_chunks(g)
        else:
            ch = [(r.page_id, piece) for r in g.itertuples() for piece in struct_chunks(r.search_text, r.society)]
        rows += [(pid, doc, soc, t) for pid, t in ch]
    df = pd.DataFrame(rows, columns=["page_id", "doc_id", "society", "text"])
    df["chunk_id"] = df.page_id + "#" + df.groupby("page_id").cumcount().astype(str)
    df["bm25_text"] = df["dense_text"] = df.text
    return df


# ───────────────────────── 셀 43: 영어 검색 문장 (LLM, 캐시 우선) ─────────────────────────
QS_CACHE: dict = {}
QS_RUNTIME = RUNTIME_CACHE / "query_struct_runtime.json"
FIELDS_TAIL = """- intent: one of "definition", "which_notation", "difference", "society_comparison", "new", "removed", "changed", "other".
- societies: classification societies named in the question, such as ["KR"], ["KR", "ABS"] or [].
- years: years named in the question as integers, or [].
Do not answer the question and do not add notation names that are not in the question."""
QS_V2 = """You prepare search queries for English ship classification notation guides (KR Notation Guide, ABS Notations and Symbols) from user questions in Korean or English.
Split the question into fields and return JSON only:
{"query_en": "...", "intent": "...", "societies": [...], "years": [...]}
- query_en: the question rewritten as an English search query in the wording used in classification rules. Keep every condition and detail that narrows the answer: ship type, equipment, purpose, operating area, power source, and notation names, symbols and abbreviations exactly as written. Leave out only society names, years or editions, question words (what, which, is there), and words about comparing, differences, or what was added, removed or changed; the other fields carry those.
""" + FIELDS_TAIL
BAD_RE = re.compile(r"(?<!\d)20\d{2}(?!\d)|(?<![A-Za-z])(?:KR|ABS)(?![A-Za-z])|한국선급|미국선급"
                    r"|\b(?:compar\w*|differ\w*|versus|vs\.?|newly|new|added|removed|deleted|changed|amended|revised)\b", re.I)


def groq_json(messages, model=GROQ_MODEL_QS):
    import requests

    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY가 없음 (backend/.env)")
    for attempt in range(6):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "temperature": 0, "reasoning_effort": "low",
                                "response_format": {"type": "json_object"}, "messages": messages})
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("retry-after") or 3 * (attempt + 1))
            if wait > 20:   # 하루 한도 등: 몇 분씩 기다리지 않고 포기 → 영어 검색 문장 없이 한국어로만 검색
                raise RuntimeError(f"Groq 한도 (약 {wait / 60:.0f}분 뒤 풀림)")
            time.sleep(wait + 1)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Groq 오류 {r.status_code}: {re.sub(r'org_[A-Za-z0-9]+', 'org_***', r.text[:300])}")
        return json.loads(r.json()["choices"][0]["message"]["content"])
    raise RuntimeError("Groq 재시도 초과")


def struct_query(q):
    k = hashlib.sha1(f"qs-v2|{GROQ_MODEL_QS}|{q}".encode()).hexdigest()
    if k not in QS_CACHE:
        msgs = [{"role": "system", "content": QS_V2}, {"role": "user", "content": q}]
        out, retried = groq_json(msgs), False
        bad = sorted({m.group(0) for m in BAD_RE.finditer(str(out.get("query_en", "")))})
        if bad:
            msgs += [{"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
                     {"role": "user", "content": f"query_en still contains {bad}. Remove them and return the JSON again."}]
            out, retried = groq_json(msgs), True
        QS_CACHE[k] = {"q": q, "out": out, "retried": retried, "first_bad": bad}
        runtime = json.loads(QS_RUNTIME.read_text(encoding="utf-8")) if QS_RUNTIME.exists() else {}
        runtime[k] = QS_CACHE[k]
        QS_RUNTIME.write_text(json.dumps(runtime, ensure_ascii=False, indent=1), encoding="utf-8")
    return QS_CACHE[k]


def final_topic(text):
    t = BAD_RE.sub(" ", text)
    t = re.sub(r"\s+([,?.])", r"\1", " ".join(t.split()))
    return re.sub(r"^[\s,.?]+|[\s,.?]+$", "", t)


def english_query(q):
    raw = " ".join(str(struct_query(q)["out"].get("query_en", "")).split())
    return final_topic(raw) or q


def en_vectors(en, societies):
    q = strip_dense_meta(clean_query(en))
    lex = lexical_query(q, societies)
    key = ("en", q, lex)
    if key not in QUERY_MEMO:
        o = M3.encode([q, lex])
        has_ascii = bool(re.search(r"[A-Za-z0-9]", lex))
        QUERY_MEMO[key] = {"dense": o["dense"][0], "sparse": o["sparse"][1] if has_ascii else {}, "tokens": bm25_tokenize(lex)}
    return q, QUERY_MEMO[key]


# ───────────────────────── 셀 45: 구판 감점 · 의도어 빼기 ─────────────────────────
INTENT_RE = {
    "A": re.compile(r"\s*(?:의\s*)?(?:비교(?:하여|해서|해|하면)?|차이(?:점|가|는|를)?|다른\s*점)"
                    r"|\b(?:comparison|compare[sd]?|comparing|differences?|differ|versus|vs\.?)\b(?:\s+(?:of|between|in))?", re.I),
}


def strip_intent(text, mode="A"):
    s = text
    for k in mode:
        s = INTENT_RE[k].sub(" ", s)
    s = re.sub(r"\s+([,?.])", r"\1", " ".join(s.split()))
    s = re.sub(r"^[\s,.]+|[\s,]+$", "", s)
    return s or text


def compare_info(qi):
    """판 비교 질문이면 (세부 의도, 우선 판, 다른 판)"""
    if not qi["intent"].startswith("판 비교"):
        return None
    kind = qi["intent"].split(": ")[1]
    soc = qi["policy"].split()[0]
    old, new = DOC_OF[(soc, min(qi["editions"]))], DOC_OF[(soc, max(qi["editions"]))]
    prefer, other = (new, old) if QI.EDITION_POLICY[kind] == "new" else (old, new)
    return kind, prefer, other


def penalized_docs(query, policy=False):
    info, qi = analyze_query(query), QI.analyze(query)
    _, pen = allowed_docs(info)
    c = compare_info(qi)
    if policy and c:
        pen = (set(pen) - {c[1]}) | {c[2]}
    return set(pen)


def demote_old(order, pen):
    if not pen:
        return order
    head = order[:DEPTH]
    return [p for p in head if p.split(":")[0] not in pen] + [p for p in head if p.split(":")[0] in pen] + order[DEPTH:]


# ───────────────────────── 셀 38: 판 비교표 ─────────────────────────
DIFF: pd.DataFrame | None = None
CHANGED = defaultdict(set)
BOOST_KINDS = {"신설": {"신설", "명칭 변경"}, "삭제": {"삭제", "명칭 변경"},
               "변경": {"요건 변경", "명칭 변경"}, "차이": {"신설", "삭제", "명칭 변경", "요건 변경"}}

# ───────────────────────── 셀 47: 통합 검색 ─────────────────────────
pages: pd.DataFrame | None = None
PAGE_TEXT: dict = {}     # page_id → search_text (리랭커·LLM 근거)
IDX_E9: HybridIndex | None = None
IDX13: HybridIndex | None = None
QSETS: dict = {}         # 정규화한 질문 → {"qid", "rels", "qtype"} (dev·test)
CHANNELS = ("dense", "sparse")


def soc_of(p):
    return SOURCES[p.split(":")[0]][1]


def society_merge(cands, orig, rqs, pen_docs):
    """E27 선급 비교 병합 (RAG_LLM재정렬.ipynb 셀 53의 search27, mode='mix_rank'와 같음).
    한·영 리랭커 원점수를 선급마다 표준화(구판 감점 쪽은 평균·표준편차에서 뺌)해 평균 → 시그모이드(E26 값),
    원래 순위 점수(1위 1.0 → 마지막 0.0)와 반반 섞어 다시 줄 세움. 동점은 원래 순서"""
    pos = {p: i for i, p in enumerate(orig)}
    groups = [[p for p in cands if soc_of(p) == s] for s in sorted({soc_of(p) for p in cands})]
    z = {p: 0.0 for p in cands}
    for rq in rqs:
        raw = {p: CROSS_MEMO[(rq, _h(PAGE_TEXT[p]))] for p in cands}
        for ps in groups:
            ref = [p for p in ps if p.split(":")[0] not in pen_docs] or ps
            vals = np.array([raw[p] for p in ref], dtype=float)
            mu, sd = vals.mean(), vals.std()
            for p in ps:
                z[p] += ((raw[p] - mu) / sd if sd > 1e-9 else 0.0) / len(rqs)
    sig = lambda x: 1 / (1 + math.exp(-x))
    s_rank = {p: 1 - pos[p] / (len(orig) - 1) if len(orig) > 1 else 1.0 for p in cands}
    g = {p: 0.5 * sig(z[p]) + 0.5 * s_rank[p] for p in cands}
    return sorted(cands, key=lambda p: (-g[p], pos[p])), g


def ko_vectors(dense_text, lex_text, societies):
    lex = lexical_query(lex_text, societies)
    key = ("ko16", dense_text, lex)
    if key not in QUERY_MEMO:
        o = M3.encode([dense_text, lex])
        has_ascii = bool(re.search(r"[A-Za-z0-9]", lex))
        QUERY_MEMO[key] = {"dense": o["dense"][0], "sparse": o["sparse"][1] if has_ascii else {}, "tokens": bm25_tokenize(lex)}
    return QUERY_MEMO[key]


def search_v2(query, en=None, idx=None, topic=False, policy=False, boost=False, rr="ko", old_last=False, intent=False,
              raw=False, allowed_override=None, stats=None, society_merge_on=False):
    """노트북 search_v2와 같다 (qid 대신 영어 검색 문장 en을 받음).
    society_merge_on=True: 선급 비교 질문이면 리랭크 뒤 E27 병합 (보고서의 최종 통합, test 0.988)
    raw=True: 검색어 정리를 끈 비교용 — 원 질문 그대로 dense·sparse·리랭커에 넣는다.
    allowed_override: 사용자가 고른 문서 범위. 돌려주는 값: (50위까지의 순서, trace)"""
    idx = idx or IDX13
    info, qi = analyze_query(query), QI.analyze(query)
    allowed, penalized = allowed_docs(info)
    if allowed_override:
        allowed = set(allowed_override)
    c = compare_info(qi)
    if policy and c:
        penalized = (set(penalized) - {c[1]}) | {c[2]}
    if raw:
        ko = clean_query(query)
        dense_text = ko
    else:
        ko = clean_query(QI.topic_query(query, qi)) if topic else strip_dense_meta(clean_query(query))
        if intent:
            ko = strip_intent(ko, "A")
        dense_text = ko if topic else strip_dense_meta(ko)
    qv = ko_vectors(dense_text, ko, info["societies"])
    lists = [idx.ranked_pages(idx.scores(ch, qv), allowed, depth=DEPTH, positive_only=(ch != "dense")) for ch in CHANNELS]
    fused = rrf([l for l in lists if l])
    for p in fused:
        if p.split(":")[0] in penalized:
            fused[p] *= 0.5
    order = sorted(fused, key=lambda p: -fused[p])
    cands = order[:DEPTH]
    ranks, rqs, en_rq = [], [], None
    if rr in ("ko", "both"):
        ranks.append(rerank_cross(ko, cands, PAGE_TEXT, stats))
        rqs.append(ko)
    if rr in ("en", "both") and en:
        en_rq, _ = en_vectors(QI.topic_query(en, qi) if topic else en, info["societies"])
        ranks.append(rerank_cross(en_rq, cands, PAGE_TEXT, stats))
        rqs.append(en_rq)
    if len(ranks) == 1:
        top = ranks[0]
    elif ranks:
        f = rrf([[(p, 0) for p in r] for r in ranks])
        top = sorted(cands, key=lambda p: -f[p])
    else:
        top = cands
    merged = False
    if society_merge_on and ranks and qi["intent"].startswith("선급 비교"):
        pen_docs = set() if allowed_override else penalized_docs(query, policy)
        top, _ = society_merge(cands, top, rqs, pen_docs)
        merged = True
    order = top + order[DEPTH:]
    if boost and c:
        kind, prefer, _ = c
        head = order[:DEPTH]
        hit = [p for p in head if p.startswith(prefer + ":") and CHANGED.get(p, set()) & BOOST_KINDS[kind]]
        order = hit + [p for p in head if p not in hit] + order[DEPTH:]
    pen_after = penalized_docs(query, policy) if old_last else set()
    if allowed_override:
        pen_after = set()
    if old_last:
        order = demote_old(order, pen_after)
    trace = {"ko": ko, "dense": dense_text, "en": en_rq, "allowed": sorted(allowed), "penalized": sorted(penalized | pen_after),
             "intent": qi["intent"], "editions": qi["editions"], "policy": qi["policy"], "societies": info["societies"],
             "years": [y for y, _ in info["years"]], "compare": c, "society_merge": merged}
    return order, trace


FINAL_OPTS = dict(topic=True, policy=True, boost=True, rr="both", old_last=True, intent=True)   # 제출 노트북의 최종 통합 (E27 전, test 0.974)
FINAL27_OPTS = {**FINAL_OPTS, "society_merge_on": True}                                    # 보고서의 최종 통합 (+E27, test 0.988)


def norm_q(s):
    return re.sub(r"[\s,.?!·\"'()]", "", s.lower())


def init(verbose=True):
    """데이터·캐시를 읽고 두 색인을 만든다 (모델은 새 질문이 올 때 처음 불러옴)"""
    global pages, RULES, STANDALONE, IDX_E9, IDX13, DIFF
    if pages is not None:
        return
    t0 = time.time()
    rows = []
    for doc_id, (fname, society, year) in SOURCES.items():
        with open(DATA_DIR / fname, "rb") as f:
            docs = SafeUnpickler(f).load()
        for d in docs:
            page = int(d.metadata.get("page", d.metadata.get("page_number")))
            rows.append({"page_id": f"{doc_id}:{page}", "doc_id": doc_id, "society": society, "year": year, "page": page, "raw": d.page_content})
    pg = pd.DataFrame(rows).sort_values(["doc_id", "page"]).reset_index(drop=True)
    rules_df = pd.read_csv(DATA_DIR / "rules.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    RULES[:] = [compile_rule(r) for r in rules_df.itertuples()]
    STANDALONE.clear()
    STANDALONE.update(build_standalone_counts(pg.raw))
    cleaned = [clean_page(r, s) for r, s in zip(pg.raw, pg.society)]
    pg["text"] = [c[0] for c in cleaned]
    pg["search_text"] = [c[1] for c in cleaned]
    pages = pg
    PAGE_TEXT.update(zip(pg.page_id, pg.search_text))

    with open(CACHE_DIR / "score_cache.pkl", "rb") as f:
        saved = pickle.load(f)
    CROSS_MEMO.update(saved.get("CROSS_MEMO", {}))
    QUERY_MEMO.update(saved.get("QUERY_MEMO", {}))
    QS_CACHE.update(json.loads((CACHE_DIR / "query_struct.json").read_text(encoding="utf-8")))
    if QS_RUNTIME.exists():
        QS_CACHE.update(json.loads(QS_RUNTIME.read_text(encoding="utf-8")))
    rt = RUNTIME_CACHE / "score_runtime.pkl"
    if rt.exists():
        with open(rt, "rb") as f:
            extra = pickle.load(f)
        CROSS_MEMO.update(extra.get("CROSS_MEMO", {}))
        QUERY_MEMO.update(extra.get("QUERY_MEMO", {}))

    cache = EmbeddingCache(CACHE_DIR / "bge_m3_cache.pkl")
    ch = make_chunks(pg, "struct", "search_text")
    ch["bm25_text"] = ch.text
    ch["dense_text"] = ch.text
    IDX_E9 = HybridIndex(ch, cache)
    IDX13 = HybridIndex(build_e13(pg), cache)
    use_vector_db(IDX_E9, IDX13)

    DIFF = pd.read_csv(OUT_DIR / "kr_edition_diff.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for r in DIFF.to_dict("records"):
        kind = r["구분"].split(" (")[0]
        for col, doc in (("2022 쪽", "KR2022"), ("2026 쪽", "KR2026")):
            for p in r[col].split():
                CHANGED[f"{doc}:{p}"].add(kind)

    for name in ("dev_set.csv", "test_set.csv"):
        df = pd.read_csv(DATA_DIR / name, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        for r in df.itertuples():
            rels = {k: float(v) for k, v in (x.split("=") for x in r.relevant.split(";"))}
            QSETS[norm_q(r.query)] = {"qid": r.qid, "query": r.query, "rels": rels, "qtype": r.qtype}
    if verbose:
        print(f"Part 1 검색기 준비: 페이지 {len(pg)} · 벡터 DB {VECTOR_DB['name']} · 청크 E9 {IDX_E9.n_chunks if hasattr(IDX_E9, 'n_chunks') else len(IDX_E9.chunks)}"
              f" / E13 {IDX13.n_chunks if hasattr(IDX13, 'n_chunks') else len(IDX13.chunks)} · "
              f"새로 계산한 임베딩 {cache.new}개 · 리랭커 점수 캐시 {len(CROSS_MEMO):,}개 · {time.time() - t0:.0f}초")


# ──────────────── 벡터 DB 선택: PostgreSQL + pgvector(이 PC의 로컬 DB 또는 Neon) 또는 FAISS ────────────────
VECTOR_DB = {"name": "FAISS", "note": "메모리 (제출 노트북과 같음)", "db": None, "indexes": []}


def db_label(url: str) -> tuple[str, bool]:
    """접속 주소의 호스트로 화면에 보일 DB 이름과 로컬 여부를 정한다 (주소 · 비밀번호는 내보내지 않음)"""
    from .pg_index import LOCAL_HOSTS, endpoint

    try:
        host, _ = endpoint(url)
    except Exception:
        return "PostgreSQL", False
    if host in LOCAL_HOSTS:
        return "로컬 PostgreSQL", True
    return ("Neon" if host.endswith(".neon.tech") else "PostgreSQL"), False


def use_vector_db(faiss_e9, faiss_13):
    """DATABASE_URL이 있으면 그 DB(이 PC의 로컬 PostgreSQL 또는 Neon)의 chunks 표를 1단계 검색 색인으로 쓴다 (VECTOR_DB=faiss로 끌 수 있음).
    청크 수가 FAISS와 다르거나 접속이 안 되면 FAISS를 그대로 쓴다. FAISS 색인은 SQL 실패 때의 대신으로 남겨 둠"""
    global IDX_E9, IDX13
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or os.environ.get("VECTOR_DB", "").strip().lower() == "faiss":
        VECTOR_DB.update(name="FAISS", note="DATABASE_URL 없음" if not url else "VECTOR_DB=faiss")
        return
    name, local = db_label(url)
    try:
        from .pg_index import Db, PgIndex

        db = Db(url)
        pg_e9 = PgIndex(db, "struct", VOCAB_SIZE, fallback=faiss_e9, depth=DEPTH)
        pg_13 = PgIndex(db, "e13_2", VOCAB_SIZE, fallback=faiss_13, depth=DEPTH)
        if (pg_e9.n_chunks, pg_13.n_chunks) != (len(faiss_e9.chunks), len(faiss_13.chunks)):
            raise RuntimeError(f"청크 수가 다름: {name} {pg_e9.n_chunks}/{pg_13.n_chunks} · FAISS {len(faiss_e9.chunks)}/{len(faiss_13.chunks)}")
        ver, pgv, dbname = db.execute("SELECT current_setting('server_version'), "
                                      "(SELECT extversion FROM pg_extension WHERE extname = 'vector'), current_database()")[0]
        IDX_E9, IDX13 = pg_e9, pg_13
        VECTOR_DB.update(name=name, note=f"PostgreSQL {ver.split()[0]} + pgvector {pgv}" + (f" · 이 PC의 {dbname} DB" if local else ""),
                         db=db, indexes=[pg_e9, pg_13])
    except Exception as e:
        VECTOR_DB.update(name="FAISS", note=f"{name} 사용 불가 → FAISS ({type(e).__name__}: {str(e).splitlines()[0][:100]})")


def vector_db_status() -> dict:
    db = VECTOR_DB["db"]
    out = {"name": VECTOR_DB["name"], "note": VECTOR_DB["note"]}
    if db is not None:
        out.update(sql_calls=db.calls, sql_ms_avg=round(db.ms / db.calls, 1) if db.calls else None, reconnects=db.reconnects,
                   fallback_calls=sum(ix.fallback_calls for ix in VECTOR_DB["indexes"]),
                   last_error=next((ix.last_error for ix in VECTOR_DB["indexes"] if ix.last_error), None))
    return out


def save_runtime_cache():
    """새 질문에서 계산한 질문 벡터·리랭커 점수를 따로 저장 (다음 실행에서 다시 계산하지 않게)"""
    with open(RUNTIME_CACHE / "score_runtime.pkl", "wb") as f:
        pickle.dump({"CROSS_MEMO": CROSS_MEMO, "QUERY_MEMO": QUERY_MEMO}, f)


def metrics_at_k(ranked, rels, k=TOP_K):
    top = ranked[:k]
    hits = [p for p in top if p in rels]
    dcg = sum(rels.get(p, 0.0) / math.log2(i + 2) for i, p in enumerate(top))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(rels.values(), reverse=True)[:k]))
    first = next((i for i, p in enumerate(top) if p in rels), None)
    return {"nDCG@10": dcg / idcg, "R@10": len(hits) / len(rels), "MRR@10": 0.0 if first is None else 1.0 / (first + 1), "P@10": len(hits) / k}
