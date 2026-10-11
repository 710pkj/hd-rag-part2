import sys, time, torch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from rag import part1 as P
P.init(verbose=False)
q = "혹한 지역을 다니는 배의 방한 설비 관련 노테이션 알려줘"
texts = [P.PAGE_TEXT[p] for p in list(P.PAGE_TEXT)[:50]]
name = "BAAI/bge-reranker-v2-m3"
tok = AutoTokenizer.from_pretrained(name)
for dtype in (torch.float16,):
    m = AutoModelForSequenceClassification.from_pretrained(name, dtype=dtype).to("xpu").eval()
    def score(bs):
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), bs):
                b = tok([[q, t] for t in texts[i:i+bs]], padding=True, truncation=True, max_length=1024, return_tensors="pt").to("xpu")
                out.extend(m(**b).logits.view(-1).float().cpu().tolist())
        torch.xpu.synchronize()
        return out
    score(8)  # warmup
    for bs in (4, 8, 16):
        t0 = time.time(); s = score(bs); print(f"xpu {dtype} bs{bs}: {time.time()-t0:.1f}s / 50쌍")
    xs = s
# 같은 쌍을 CPU fp32로 10개만 비교
mc = AutoModelForSequenceClassification.from_pretrained(name).eval()
with torch.no_grad():
    b = tok([[q, t] for t in texts[:10]], padding=True, truncation=True, max_length=1024, return_tensors="pt")
    cs = mc(**b).logits.view(-1).float().tolist()
import numpy as np
print("CPU vs XPU 점수 차 최대", round(float(np.max(np.abs(np.array(cs) - np.array(xs[:10])))), 4), "| 순위 같음:", list(np.argsort(cs)) == list(np.argsort(xs[:10])))
