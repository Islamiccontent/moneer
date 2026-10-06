"""إعدادات أداة التدقيق من إعدادات Django (``settings.AUDIT`` ومفتاح ``GEMINI_API_KEY``)."""

from dataclasses import dataclass

from django.conf import settings as dj_settings


@dataclass
class Settings:
    api_key: str = ""
    model: str = "gemini-3.1-pro-preview"
    thinking_level: str = "high"  # فارغ = لا يُرسل thinkingConfig
    temperature: float | None = None  # None = افتراضي النموذج
    use_schema: bool = False
    group_size: int = 20  # صفوف لكل طلب
    max_attempts: int = 3
    http_timeout: int = 60  # مهلة النداء الواحد بالثواني
    http_retries: int = 3  # محاولات النداء الواحد للأخطاء العابرة
    short_ratio: float = 0.40
    long_ratio: float = 3.0


def load_settings(**overrides):
    """إعدادات الأداة من Django مع إمكانية تجاوز أي حقل (مثل model أو group_size)."""
    cfg = dj_settings.AUDIT
    values = {
        "api_key": dj_settings.GEMINI_API_KEY,
        "model": cfg["MODEL"],
        "thinking_level": cfg["THINKING_LEVEL"],
        "temperature": cfg["TEMPERATURE"],
        "use_schema": cfg["USE_SCHEMA"],
        "group_size": cfg["GROUP_SIZE"],
        "max_attempts": cfg["MAX_ATTEMPTS"],
        "http_timeout": cfg["HTTP_TIMEOUT"],
        "http_retries": cfg["HTTP_RETRIES"],
        "short_ratio": cfg["LEN_SHORT_RATIO"],
        "long_ratio": cfg["LEN_LONG_RATIO"],
    }
    values.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**values)


def request_config(settings):
    """إعدادات الطلب التي تُحفظ مع المهمة (للتوثيق وإعادة الصياغة لاحقاً)."""
    return {
        "thinking_level": settings.thinking_level or None,
        "temperature": settings.temperature,
        "use_schema": bool(settings.use_schema),
    }
