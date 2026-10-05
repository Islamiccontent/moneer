"""الصفحات العامة: index.html وملفات الجذر وحزم الواجهة في pages/html تُخدم كما هي."""

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe

HOME_FILE = "index.html"
HTML_DIR = Path(__file__).resolve().parent / "html"
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
    """صفحة الترجمة كما هي؛ الرابط الدائم /translate/documents/<pk>/ يخدم الحزمة نفسها."""
    return FileResponse(TRANSLATE_PAGE.open("rb"), content_type="text/html; charset=utf-8")


@require_safe
def documents_page(request):
    """تصفح المحتوى المحفوظ بمراحله — صفحة خفيفة تقرأ ``/api/translate/documents/``."""
    return FileResponse(DOCUMENTS_PAGE.open("rb"), content_type="text/html; charset=utf-8")
