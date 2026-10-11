"""Groq 언어모델 호출 (langchain_groq.ChatGroq, JSON 모드).

무료 한도(분당·하루 토큰)에 걸리면 기다리지 않고 대체 모델로 넘어간다. 모델마다 한도가 따로라서
하루 한도를 다 쓴 모델은 풀릴 때까지 건너뛴다. 어떤 모델로 답했는지는 노드 설명에 적는다.
"""
import json
import os
import re
import time

MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"            # 답변 생성 (빈 값이면 기본)
MODEL_FAST = os.environ.get("GROQ_MODEL_FAST") or MODEL                  # 근거 판정·근거 검증
FALLBACKS = [m.strip() for m in (os.environ.get("GROQ_FALLBACK_MODELS") or "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
MAX_WAIT = 20          # 이보다 오래 기다리라는 한도 오류면 대체 모델로

_cache: dict = {}
_blocked: dict = {}    # 모델 → 다시 써 볼 시각
last_model = None      # 마지막으로 답한 모델


def has_key() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


def _llm(model: str, max_tokens: int):
    from langchain_groq import ChatGroq

    k = (model, max_tokens)
    if k not in _cache:
        extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
        _cache[k] = ChatGroq(model=model, temperature=0, max_tokens=max_tokens, max_retries=1,
                             model_kwargs={"response_format": {"type": "json_object"}}, **extra)
    return _cache[k]


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def mask(text: str) -> str:
    """오류 메시지에서 Groq 조직 ID 가리기"""
    return re.sub(r"org_[A-Za-z0-9]+", "org_***", str(text))


def _retry_seconds(err: Exception) -> float | None:
    """한도 오류(429)면 기다리라는 시간(초), 아니면 None"""
    s = str(err)
    if "429" not in s and "rate limit" not in s.lower():
        return None
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", s)
    if not m or not any(m.groups()):
        return 60.0
    h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def chat_json(system: str, user: str, *, fast=False, max_tokens=1500) -> dict:
    """시스템·사용자 메시지를 보내고 JSON 객체를 받는다. 한도에 걸리면 대체 모델로"""
    global last_model
    primary = MODEL_FAST if fast else MODEL
    last_err = None
    for model in [primary] + [m for m in FALLBACKS if m != primary]:
        if _blocked.get(model, 0) > time.time():
            continue
        for _ in range(2):
            try:
                msg = _llm(model, max_tokens).invoke([("system", system), ("user", user)])
                last_model = model
                return parse_json(msg.content)
            except Exception as e:
                wait = _retry_seconds(e)
                if wait is None:
                    raise RuntimeError(mask(f"{type(e).__name__}: {e}")[:300]) from None
                last_err = e
                if wait > MAX_WAIT:
                    _blocked[model] = time.time() + wait
                    break
                time.sleep(wait + 0.5)
    raise RuntimeError(mask(f"Groq 무료 한도에 걸림 (대체 모델까지 모두): {last_err}")[:300])


def model_note() -> str:
    """기본 모델이 아닌 모델로 답했으면 노드 설명에 붙일 문구"""
    return f" · 대체 모델 {last_model.split('/')[-1]}" if last_model and last_model not in (MODEL, MODEL_FAST) else ""
