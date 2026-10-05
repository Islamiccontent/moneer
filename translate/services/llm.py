"""عميلان رفيعان بـ HTTP خام: Gemini لترجمة النصوص وOpenAI لاستخراج ترجمة الآيات المعتمدة."""

import json
import urllib.request

from classify.services.reviewer import GEMINI_ENDPOINT, UA, _post

OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"


class LLMError(RuntimeError):
    """فشل استدعاء النموذج أو ردٌّ فارغ."""


def _post_json(url, body, headers):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA, **headers},
    )
    try:
        return _post(request)
    except RuntimeError as exc:
        raise LLMError(str(exc)) from exc


def gemini_generate(prompt, *, model, api_key, temperature=1.0):
    """يعيد نص رد Gemini على prompt واحد."""
    if not api_key:
        raise LLMError("GEMINI_API_KEY غير مضبوط.")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    payload = _post_json(GEMINI_ENDPOINT.format(model=model), body, {"x-goog-api-key": api_key})
    candidates = payload.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise LLMError(f"ردّ Gemini فارغ: {json.dumps(payload, ensure_ascii=False)[:200]}")
    return text


def openai_generate(prompt, *, model, api_key):
    """يعيد نص ردّ OpenAI (chat completions). بلا temperature لأن عائلة gpt-5 لا تقبلها."""
    if not api_key:
        raise LLMError("OPENAI_API_KEY غير مضبوط.")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    payload = _post_json(OPENAI_ENDPOINT, body, {"Authorization": f"Bearer {api_key}"})
    choices = payload.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not text:
        raise LLMError(f"ردّ OpenAI فارغ: {json.dumps(payload, ensure_ascii=False)[:200]}")
    return text


def strip_quotes(text):
    """يزيل الفراغات وعلامتي الاقتباس المحيطتين بالناتج."""
    return text.strip().strip('"').strip("“”").strip()
