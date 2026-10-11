"""공유용 소스 압축: 비밀 값(.env), 설치 결과(node_modules, .venv, .next), 실행 캐시, 과제 원본 PDF를 뺀다.
실행: python tools/make_zip.py [출력 경로]  →  기본 dist/hd-rag-part2-src.zip"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"node_modules", ".next", ".venv", "__pycache__", "cache_runtime", ".git"}
SKIP_PATHS = {"web/public/docs", "web/public/pdfjs", "data", "dist"}   # public은 setup.ps1(prepare-data)이 다시 만듦, data는 각자 둠
SKIP_FILES = {".env", "tsconfig.tsbuildinfo", "next-env.d.ts"}
SECRET_RE = re.compile(rb"gsk_[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9-]{20,}|postgres(?:ql)?://\S+:\S+@")


def wanted(p: Path) -> bool:
    rel = p.relative_to(ROOT).as_posix()
    parts = set(p.relative_to(ROOT).parts)
    if parts & SKIP_DIRS or any(rel == s or rel.startswith(s + "/") for s in SKIP_PATHS):
        return False
    return p.name not in SKIP_FILES and not p.name.startswith(".venv")


out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "hd-rag-part2-src.zip"
out.parent.mkdir(parents=True, exist_ok=True)
files = sorted(p for p in ROOT.rglob("*") if p.is_file() and wanted(p))
for p in files:   # 키가 섞여 들어가지 않았는지 검사
    if SECRET_RE.search(p.read_bytes()):
        raise SystemExit(f"비밀 값으로 보이는 문자열이 있음: {p}")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, Path("hd-rag-part2") / p.relative_to(ROOT))
    for d in ("data/HD_RAG_Part1", "data/pdf"):   # 데이터 자리만 만들어 둠
        z.writestr(f"hd-rag-part2/{d}/README.txt", "여기에 데이터를 둔다. 루트 README.md의 준비물 참고\n")
print(f"{out} · 파일 {len(files)}개 · {out.stat().st_size / 1024:.0f} KB")
