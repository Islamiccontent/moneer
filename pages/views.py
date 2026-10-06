"""الصفحات العامة: index.html وملفات الجذر وصفحات pages/html كما هي، وأصولها من pages/assets."""

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_safe
from django.views.static import serve

HOME_FILE = "index.html"
HTML_DIR = Path(__file__).resolve().parent / "html"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# الخطوط والصور نادراً ما تتغير؛ الأنماط والسكربت يُتحقَّق منها كل مرة (304 إن لم تتغير)
ASSET_CACHE = {
    ".woff2": "public, max-age=604800",
    ".png": "public, max-age=604800",
    ".webp": "public, max-age=604800",
    ".svg": "public, max-age=604800",
}
CLASSIFY_PAGE = HTML_DIR / "classify.html"
TRANSLATE_PAGE = HTML_DIR / "translate.html"
DOCUMENTS_PAGE = HTML_DIR / "documents.html"

ROOT_FILES = {
    HOME_FILE: "text/html; charset=utf-8",
    "favicon.svg": "image/svg+xml",
    "favicon-16.png": "image/png",
    "favicon-32.png": "image/png",
    "favicon-48.png": "image/png",
    "favicon-192.png": "image/png",
    "favicon-512.png": "image/png",
    "apple-touch-icon.png": "image/png",
    "site.webmanifest": "application/manifest+json",
    "og.jpg": "image/jpeg",
}


def _serve_root_file(name):
    path = Path(settings.BASE_DIR) / name
    if name not in ROOT_FILES or not path.is_file():
        raise Http404(name)
    return FileResponse(path.open("rb"), content_type=ROOT_FILES[name])


@require_safe
def home(request):
    return _serve_root_file(HOME_FILE)


@require_safe
def root_file(request, name):
    if name == HOME_FILE:
        raise Http404(name)
    return _serve_root_file(name)


@require_safe
def classify_page(request, pk=None):
    """صفحة التقطيع والتصنيف بواجهة مُنير، كما هي بايتاً بايت."""
    return FileResponse(CLASSIFY_PAGE.open("rb"), content_type="text/html; charset=utf-8")


@require_safe
def translate_page(request, pk=None, stage=None):
    """صفحة الترجمة لمستند محفوظ؛ بلا مستند يبدأ المشروع من الرفع في /classify/."""
    if pk is None:
        return redirect("pages:classify")
    return FileResponse(TRANSLATE_PAGE.open("rb"), content_type="text/html; charset=utf-8")


@require_safe
def asset(request, path):
    """خطوط الصفحات وصورها وأنماطها ومشغّل قوالبها من pages/assets، بلا collectstatic."""
    suffix = Path(path).suffix.lower()
    if suffix not in ASSET_TYPES:
        raise Http404(path)
    response = serve(request, path, document_root=ASSETS_DIR)
    response.headers["Content-Type"] = ASSET_TYPES[suffix]
    response.headers["Cache-Control"] = ASSET_CACHE.get(suffix, "no-cache")
    return response


@require_safe
def documents_page(request):
    """تصفح المحتوى المحفوظ بمراحله — صفحة خفيفة تقرأ ``/api/translate/documents/``."""
    return FileResponse(DOCUMENTS_PAGE.open("rb"), content_type="text/html; charset=utf-8")
