"""موصل Gemini — نداء generateContent متزامن مع إعادة محدودة للأخطاء العابرة.

مأخوذ من trreview/gemini_batch.py بعد إسقاط مسار Batch: لا حالة داخلية، وكل دالة تأخذ
المفتاح معاملًا. السياسة نفسها: 400/401/403/404 أخطاء دائمة لا تُعاد؛ 429 و5xx أخطاء
عابرة تُعاد.
"""

import json
import logging
import socket
import time
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

logger = logging.getLogger("audit.gemini")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
API_HOST = "generativelanguage.googleapis.com"
REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_RETRIES = 3
SYNC_TIMEOUT_SECONDS = 600


def set_defaults(timeout=None, retries=None):
    """يضبط المهلة وعدد المحاولات الافتراضيين لكل النداءات (من الإعدادات)."""
    global REQUEST_TIMEOUT_SECONDS, DEFAULT_RETRIES
    if timeout:
        REQUEST_TIMEOUT_SECONDS = int(timeout)
    if retries:
        DEFAULT_RETRIES = max(1, int(retries))


def net_log(message):
    """سجل الشبكة: كل محاولة تُسجَّل لحظة بدئها ولحظة انتهائها حتى لا يبدو النداء معلّقًا بصمت."""
    logger.info("[%s] %s", time.strftime("%H:%M:%S"), message)


class GeminiAPIError(RuntimeError):
    def __init__(self, status, message):
        self.status = int(status or 0)
        self.message = str(message)
        super().__init__(f"HTTP {self.status}: {self.message}")

    @property
    def permanent(self):
        return self.status in {400, 401, 403, 404}


def _describe_network_error(exc):
    """وصف عربي واضح لخطأ الشبكة الخام: مهلة، رفض اتصال، DNS، TLS، وكيل…"""
    reason = getattr(exc, "reason", None)
    inner = reason if reason is not None else exc
    text = f"{type(inner).__name__}: {inner}"
    lowered = str(inner).lower()
    if isinstance(inner, TimeoutError | socket.timeout) or "timed out" in lowered:
        kind = "انتهت المهلة دون أي رد من الخادم"
    elif (
        isinstance(inner, socket.gaierror)
        or "name or service not known" in lowered
        or "nodename" in lowered
    ):
        kind = "فشل تحليل اسم النطاق (DNS)"
    elif isinstance(inner, ConnectionRefusedError) or "refused" in lowered:
        kind = "رُفض الاتصال (Connection refused)"
    elif (
        isinstance(inner, ConnectionResetError)
        or "reset" in lowered
        or "remotedisconnected" in lowered
    ):
        kind = "قُطع الاتصال من الطرف الآخر"
    elif "ssl" in lowered or "certificate" in lowered:
        kind = "فشل TLS/الشهادة"
    elif "tunnel" in lowered or "proxy" in lowered:
        kind = "فشل عبر الوكيل (proxy)"
    else:
        kind = "تعذّر الاتصال"
    return kind, text


def api_call(api_key, method, url, body=None, timeout=None, retries=None):
    """نداء HTTP واحد مع إعادة محدودة للأخطاء العابرة (429/5xx/شبكة).

    كل محاولة تُسجَّل لحظة بدئها ونتيجتها فورًا عبر ``net_log`` — لا انتظار صامت.
    400/401/403/404 تُرفع فورًا (دائمة)؛ غيرها يُعاد ``retries`` مرة.
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    timeout = timeout or REQUEST_TIMEOUT_SECONDS
    retries = max(1, retries or DEFAULT_RETRIES)
    path = url.replace(API_BASE, "") or "/"
    size = f"، حمولة {len(data) / 1024:.1f}KB" if data else ""
    last_exc = None
    for attempt in range(1, retries + 1):
        net_log(f"{method} {path} (محاولة {attempt}/{retries}{size}، مهلة {timeout} ث) …")
        started = time.time()
        req = urlrequest.Request(
            url,
            data=data,
            method=method,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                net_log(
                    f"✔ HTTP {response.status} في {time.time() - started:.1f} ث "
                    f"({len(raw) / 1024:.1f}KB)"
                )
                return json.loads(raw) if raw else {}
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(raw).get("error", {}).get("message") or raw
            except Exception:
                message = raw or str(exc)
            last_exc = GeminiAPIError(exc.code, message[:1000])
            net_log(f"✖ HTTP {exc.code} بعد {time.time() - started:.1f} ث: {message[:300]}")
            if last_exc.permanent:
                raise last_exc from exc
        except Exception as exc:  # URLError/timeout/OSError/HTTPException/SSL…
            kind, text = _describe_network_error(exc)
            last_exc = GeminiAPIError(0, f"{kind} — {text}")
            net_log(f"✖ {kind} بعد {time.time() - started:.1f} ث — {text}")
        if attempt < retries:
            wait = 2 * attempt
            net_log(f"… إعادة المحاولة بعد {wait} ث")
            time.sleep(wait)
    raise last_exc


def list_models(api_key):
    """النماذج المتاحة فعلًا لهذا المفتاح والتي تدعم توليد المحتوى."""
    payload = api_call(api_key, "GET", f"{API_BASE}/models")
    models = []
    for item in payload.get("models") or []:
        raw_name = str(item.get("name") or "")
        model_id = raw_name.split("/", 1)[1] if "/" in raw_name else raw_name
        methods = [str(m) for m in (item.get("supportedGenerationMethods") or [])]
        if not model_id or (methods and not any("generateContent" in m for m in methods)):
            continue
        models.append(
            {"id": model_id, "label": item.get("displayName") or model_id, "methods": methods}
        )
    return models


def build_request(prompt, thinking_level=None, temperature=None, response_schema=None):
    """حمولة generateContent واحدة."""
    generation_config = {"responseMimeType": "application/json"}
    if temperature is not None:
        generation_config["temperature"] = float(temperature)
    if thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    if response_schema:
        generation_config["responseSchema"] = response_schema
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }


def generate_content(api_key, model, request_body, timeout=None):
    """نداء متزامن واحد. يعيد الرد ملفوفًا {"response": …} ليُحلَّل بـ ``response_text``."""
    encoded_model = urlparse.quote(model, safe="")
    payload = api_call(
        api_key,
        "POST",
        f"{API_BASE}/models/{encoded_model}:generateContent",
        request_body,
        timeout=timeout or SYNC_TIMEOUT_SECONDS,
        retries=2,
    )
    return {"response": payload}


def response_text(item):
    """نص الرد من رد generate_content الملفوف."""
    if item.get("error"):
        error = item["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ValueError(message or "خطأ غير محدد في رد النموذج.")
    response = item.get("response") or {}
    candidates = response.get("candidates") or []
    if not candidates:
        block = (response.get("promptFeedback") or {}).get("blockReason")
        raise ValueError(
            f"لم يُرجع النموذج أي candidate{f' (blockReason={block})' if block else ''}."
        )
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text") or "") for part in parts if not part.get("thought"))
    if not text.strip():
        raise ValueError("رد النموذج فارغ.")
    return text


def usage_tokens(item):
    """(prompt_tokens, output_tokens) من usageMetadata إن وُجدت."""
    usage = (item.get("response") or {}).get("usageMetadata") or {}
    return int(usage.get("promptTokenCount") or 0), int(usage.get("candidatesTokenCount") or 0)
