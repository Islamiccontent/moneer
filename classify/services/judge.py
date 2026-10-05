"""النموذج اللغوي حَكَم بين خيارات مغلقة لا مولّد للنص: سياق ضيق ومخرج مقيّد وسجل لكل قرار."""

import json
import os
import time
from pathlib import Path

from .reviewer import GEMINI_ENDPOINT, GROQ_ENDPOINT, UA, _key, _model, _post, provider

LOG_PATH = Path(
    os.environ.get(
        "JUDGE_LOG", str(Path(__file__).resolve().parent.parent / "data" / "judge_log.jsonl")
    )
)


def enabled(flag: str) -> bool:
    """يقرأ مفتاح تفعيل من البيئة؛ الأصل الإغلاق."""
    return os.environ.get(flag) == "1" and bool(_key(provider()))


def context(prev: str, current: str, nxt: str, limit: int = 600) -> str:
    """يعيد الفقرة وجارتيها فقط سياقاً للنموذج."""
    parts = []
    if prev:
        parts.append(f"[قبل] {prev[-limit:]}")
    parts.append(f"[النصّ] {current[: limit * 2]}")
    if nxt:
        parts.append(f"[بعد] {nxt[:limit]}")
    return "\n".join(parts)


def ask(
    system: str, user: str, options: list[str], key: str = "answer", extra: dict | None = None
) -> dict | None:
    """سؤالٌ جوابُه من قائمةٍ مغلقة. يرجع None عند أيّ تعذّر أو خروجٍ عنها."""
    schema = {
        "type": "object",
        "properties": {key: {"type": "string", "enum": list(options)}, **(extra or {})},
        "required": [key],
    }
    prov = provider()
    model, api_key = _model(prov), _key(prov)
    try:
        if prov == "groq":
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": 256,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "verdict",
                        "strict": True,
                        "schema": {**schema, "additionalProperties": False},
                    },
                },
            }
            payload = _post_json(GROQ_ENDPOINT, body, {"Authorization": f"Bearer {api_key}"})
            content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
        else:
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 256,
                    "responseMimeType": "application/json",
                    "responseSchema": schema,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }
            payload = _post_json(
                GEMINI_ENDPOINT.format(model=model), body, {"x-goog-api-key": api_key}
            )
            parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            content = parts[0]["text"] if parts else None
        if not content:
            return None
        data = json.loads(content)
    except Exception:
        return None
    if data.get(key) not in options:
        return None
    return data


def ask_list(
    system: str, user: str, options: list[str], count: int, key: str = "verdicts"
) -> list[str] | None:
    """حكم لكل عنصر من قائمة مغلقة؛ اختلاف عدد الأحكام عن العناصر يُهمل الرد كله."""
    schema = {
        "type": "object",
        "properties": {key: {"type": "array", "items": {"type": "string", "enum": list(options)}}},
        "required": [key],
    }
    data = _call(system, user, schema)
    if not data:
        return None
    out = data.get(key)
    if not isinstance(out, list) or len(out) != count:
        return None
    return out if all(v in options for v in out) else None


def _call(system: str, user: str, schema: dict, max_tokens: int = 2048) -> dict | None:
    prov = provider()
    model, api_key = _model(prov), _key(prov)
    try:
        if prov == "groq":
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "verdict",
                        "strict": True,
                        "schema": {**schema, "additionalProperties": False},
                    },
                },
            }
            payload = _post_json(GROQ_ENDPOINT, body, {"Authorization": f"Bearer {api_key}"})
            content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
        else:
            think = int(os.environ.get("JUDGE_THINK", "0"))
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": max_tokens + think,
                    "responseMimeType": "application/json",
                    "responseSchema": schema,
                    "thinkingConfig": {"thinkingBudget": think},
                },
            }
            payload = _post_json(
                GEMINI_ENDPOINT.format(model=model), body, {"x-goog-api-key": api_key}
            )
            parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            content = parts[-1]["text"] if parts else None
        return json.loads(content) if content else None
    except Exception:
        return None


def _post_json(url, body, headers):
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA, **headers},
    )
    return _post(req)


def log(task: str, text: str, verdict, fallback, meta: dict | None = None) -> None:
    """يسجل كل حكم مع بديله الحتمي لحساب الصافي."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "t": int(time.time()),
                        "task": task,
                        "text": text[:300],
                        "llm": verdict,
                        "deterministic": fallback,
                        **(meta or {}),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass
